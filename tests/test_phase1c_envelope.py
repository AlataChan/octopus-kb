"""Staging, the transition table, and durable activation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from octopus_kb_compound.approvals import (
    logical_document_id,
    parse_private_key,
    part_digest,
    public_key_b64,
    sign_approval,
)
from octopus_kb_compound.envelope import (
    DURABILITY_LOG,
    ActivationInterrupted,
    aggregate_status,
    ingest_envelope,
)
from octopus_kb_compound import envelope as envelope_mod

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "phase1c" / "approvals" / "vectors.json").read_text(encoding="utf-8")
)
NOW = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(days=1)
TENANT = "tenant-a"
VAULT_ID = "vault-1"
LABEL = "internal"


@pytest.fixture
def world(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    private = parse_private_key(FIXTURE["private_key_pem"])
    monkeypatch.setenv("OCTOPUS_KB_TENANT", TENANT)
    monkeypatch.setenv(
        "OCTOPUS_KB_VAULTS",
        json.dumps({VAULT_ID: {"root": str(vault), "allowed_access_labels": [LABEL, "restricted"]}}),
    )
    monkeypatch.setenv(
        "OCTOPUS_KB_APPROVAL_KEYS",
        json.dumps({FIXTURE["key_id"]: public_key_b64(private)}),
    )
    envelope_mod.FAULT = None
    DURABILITY_LOG.clear()
    return vault, private


def test_revision_cases_and_transition_precedence(world):
    vault, private = world

    first = _publish(vault, private, "extract-v1", placement="manuals/sample.docx", body="version one")
    assert first["status"] == "activated"
    corrected = _publish(
        vault,
        private,
        "extract-v2",
        placement="manuals/sample.docx",
        body="version two",
        parent=first["revision_id"],
        extraction={"redaction_policy": "none/0.1.0", "pass": "corrected"},
    )
    assert corrected["status"] == "activated"
    assert _pointer(vault, corrected["logical_document_id"]) == corrected["revision_id"]
    assert "version two" in _page_text(vault, corrected["revision_id"])

    redacted = _publish(
        vault,
        private,
        "redaction-v2",
        placement="manuals/sample.docx",
        body="version two",
        parent=corrected["revision_id"],
        logical_id=corrected["logical_document_id"],
        redaction="strict/0.2.0",
    )
    assert redacted["status"] == "activated"
    assert redacted["revision_id"] != corrected["revision_id"]

    internal = _publish(vault, private, "same-bytes", placement="manuals/shared.docx", body="same", label=LABEL)
    restricted = _publish(
        vault, private, "same-bytes", placement="manuals/shared.docx", body="same", label="restricted"
    )
    assert internal["logical_document_id"] != restricted["logical_document_id"]
    assert _pointer(vault, internal["logical_document_id"]) == internal["revision_id"]
    assert _pointer(vault, restricted["logical_document_id"]) == restricted["revision_id"]

    multi = _bundle(vault, private, ["part-a", "part-b"], placement="manuals/multi.docx")
    both = ingest_envelope(VAULT_ID, multi["manifest"], multi["parts"], multi["approval"], now=NOW)
    assert both["status"] == "activated"
    assert len(list((vault / ".octopus-kb" / "revisions" / both["revision_id"]).glob("*.md"))) == 2

    previous = _publish(vault, private, "live", placement="manuals/replace.docx", body="old")
    replacement = _bundle(
        vault,
        private,
        ["new"],
        placement="manuals/replace.docx",
        parent=previous["revision_id"],
        logical_id=previous["logical_document_id"],
    )
    envelope_mod.FAULT = "before_rename"
    with pytest.raises(ActivationInterrupted):
        ingest_envelope(VAULT_ID, replacement["manifest"], replacement["parts"], replacement["approval"], now=NOW)
    assert _pointer(vault, previous["logical_document_id"]) == previous["revision_id"]
    envelope_mod.FAULT = None
    finished = ingest_envelope(
        VAULT_ID, replacement["manifest"], replacement["parts"], replacement["approval"], now=NOW
    )
    assert finished["status"] == "activated"
    assert _pointer(vault, previous["logical_document_id"]) == finished["revision_id"]

    current = _publish(vault, private, "base", placement="manuals/gap.docx", body="base")
    gap = _bundle(
        vault,
        private,
        ["next"],
        placement="manuals/gap.docx",
        parent=current["revision_id"],
        logical_id=current["logical_document_id"],
    )
    envelope_mod.FAULT = "before_pointer"
    with pytest.raises(ActivationInterrupted):
        ingest_envelope(VAULT_ID, gap["manifest"], gap["parts"], gap["approval"], now=NOW)
    assert _pointer(vault, current["logical_document_id"]) == current["revision_id"]
    record = (vault / ".octopus-kb" / "activations" / f"{current['logical_document_id']}.jsonl").read_text()
    assert gap["manifest"]["revision_id"] in record
    envelope_mod.FAULT = None
    healed = ingest_envelope(VAULT_ID, gap["manifest"], gap["parts"], gap["approval"], now=NOW)
    assert healed["status"] == "activated"

    ordered = _bundle(vault, private, ["zero", "one"], placement="manuals/order.docx")
    later, earlier = ordered["parts"][1], ordered["parts"][0]
    first_try = ingest_envelope(VAULT_ID, ordered["manifest"], [later], None, now=NOW)
    assert first_try["status"] == "staged_incomplete"
    assert first_try["missing_indexes"] == [0]
    again = ingest_envelope(VAULT_ID, ordered["manifest"], [later], None, now=NOW)
    assert again["status"] == "staged_incomplete"
    staged = vault / ".octopus-kb" / "staging" / ordered["logical_document_id"] / ordered["manifest"]["revision_id"]
    assert len(list(staged.glob("*.json"))) == 1
    done = ingest_envelope(VAULT_ID, ordered["manifest"], [earlier], ordered["approval"], now=NOW)
    assert done["status"] == "activated"


def test_mixed_status_orders_do_not_publish_early(world):
    vault, private = world
    for order in ("low-high", "high-low"):
        built = _bundle(
            vault,
            private,
            ["low", "high"],
            placement=f"manuals/{order}.docx",
            statuses=["consistent_unverified", "completed_partial"],
            scope="partial",
        )
        parts = built["parts"] if order == "low-high" else list(reversed(built["parts"]))
        early = ingest_envelope(VAULT_ID, built["manifest"], [parts[0], parts[0]], built["approval"], now=NOW)
        assert early["status"] == "rejected:duplicate_part"
        assert not (vault / ".octopus-kb" / "active").exists() or _pointer(vault, built["logical_document_id"]) is None
        first = ingest_envelope(VAULT_ID, built["manifest"], [parts[0]], built["approval"], now=NOW)
        assert first["status"] == "staged_incomplete"
        assert _pointer(vault, built["logical_document_id"]) is None
        second = ingest_envelope(VAULT_ID, built["manifest"], [parts[1]], built["approval"], now=NOW)
        assert second["status"] == "activated"


def test_awaiting_approval_is_not_a_conflict_and_active_retry_ignores_expiry(world):
    vault, private = world
    ready = _bundle(vault, private, ["body"], placement="manuals/wait.docx")
    waiting = ingest_envelope(VAULT_ID, ready["manifest"], ready["parts"], None, now=NOW)
    assert waiting["status"] == "staged_awaiting_approval"
    full_for_partial = _bundle(
        vault,
        private,
        ["body"],
        placement="manuals/partial.docx",
        statuses=["completed_partial"],
        scope="full",
    )
    assert ingest_envelope(
        VAULT_ID, full_for_partial["manifest"], full_for_partial["parts"], full_for_partial["approval"], now=NOW
    )["status"] == "staged_awaiting_approval"

    live = _publish(vault, private, "live", placement="manuals/stale.docx", body="live")
    child = _bundle(
        vault,
        private,
        ["child"],
        placement="manuals/stale.docx",
        parent="ab" * 32,
        logical_id=live["logical_document_id"],
    )
    assert ingest_envelope(VAULT_ID, child["manifest"], child["parts"], child["approval"], now=NOW)["status"] == "revision_conflict"

    expired = dict(live["approval"])
    expired["expires_at"] = "2020-01-01T00:00:00Z"
    expired["signature"] = sign_approval(
        {key: value for key, value in expired.items() if key != "signature"},
        private,
    )
    retry = ingest_envelope(VAULT_ID, live["manifest"], live["parts"], expired, now=NOW)
    assert retry["status"] == "active"


def test_rejects_cross_vault_tenant_parts_and_altered_documents(world):
    vault, private = world
    built = _bundle(vault, private, ["body"], placement="manuals/bad.docx")
    manifest = built["manifest"]
    part = built["parts"][0]
    staging = vault / ".octopus-kb" / "staging"

    other_vault = dict(manifest)
    other_vault["vault_id"] = "vault-2"
    assert ingest_envelope("vault-1", other_vault, [part], None, now=NOW)["status"] == "rejected:vault_mismatch"
    assert not staging.exists()

    other_tenant = dict(manifest)
    other_tenant["tenant"] = "tenant-b"
    assert ingest_envelope(VAULT_ID, other_tenant, [part], None, now=NOW)["status"] == "rejected:tenant_mismatch"

    assert ingest_envelope(VAULT_ID, manifest, [part, part], None, now=NOW)["status"] == "rejected:duplicate_part"
    assert not staging.exists()

    extra = dict(part)
    extra["part_id"] = "part:extra"
    extra["index"] = 1
    extra["body"] = "not in the manifest"
    extra["part_digest"] = part_digest(extra)
    assert ingest_envelope(VAULT_ID, manifest, [extra], None, now=NOW)["status"] == "rejected:extra_part"
    assert not staging.exists()

    altered = dict(manifest)
    altered["policy_version"] = "policy/changed"
    assert ingest_envelope(VAULT_ID, altered, [part], None, now=NOW)["status"] == "rejected:revision_mismatch"
    assert not staging.exists()

    mismatched = _bundle(
        vault,
        private,
        ["one", "two"],
        placement="manuals/status.docx",
        statuses=["consistent_unverified", "completed_partial"],
        manifest_status="consistent_unverified",
        scope="full",
    )
    assert ingest_envelope(
        VAULT_ID, mismatched["manifest"], mismatched["parts"], mismatched["approval"], now=NOW
    )["status"] == "rejected:status_mismatch"
    kept = vault / ".octopus-kb" / "staging" / mismatched["logical_document_id"] / mismatched["manifest"]["revision_id"]
    assert len(list(kept.glob("*.json"))) == 2
    assert _pointer(vault, mismatched["logical_document_id"]) is None


def test_old_revision_and_competing_children(world):
    vault, private = world
    parent = _publish(vault, private, "parent", placement="manuals/race.docx", body="parent")
    left = _bundle(
        vault, private, ["left"], placement="manuals/race.docx", parent=parent["revision_id"], logical_id=parent["logical_document_id"]
    )
    right = _bundle(
        vault, private, ["right"], placement="manuals/race.docx", parent=parent["revision_id"], logical_id=parent["logical_document_id"]
    )
    assert ingest_envelope(VAULT_ID, left["manifest"], left["parts"], left["approval"], now=NOW)["status"] == "activated"
    assert ingest_envelope(VAULT_ID, right["manifest"], right["parts"], right["approval"], now=NOW)["status"] == "revision_conflict"
    assert _pointer(vault, parent["logical_document_id"]) == left["manifest"]["revision_id"]
    replay = ingest_envelope(VAULT_ID, parent["manifest"], parent["parts"], parent["approval"], now=NOW)
    assert replay["status"] == "revision_conflict"


def test_commit_fsyncs_the_record_before_the_pointer(world):
    vault, private = world
    DURABILITY_LOG.clear()
    result = _publish(vault, private, "durable", placement="manuals/fsync.docx", body="body")
    assert result["status"] == "activated"
    assert DURABILITY_LOG.index("activation-record") < DURABILITY_LOG.index("pointer-rename")
    assert DURABILITY_LOG.index("revision-dir") < DURABILITY_LOG.index("activation-record")
    assert DURABILITY_LOG.index("pointer-temp") < DURABILITY_LOG.index("pointer-rename")
    assert DURABILITY_LOG.index("pointer-rename") < DURABILITY_LOG.index("active-dir")
    bindings = json.loads(
        (vault / ".octopus-kb" / "revisions" / result["revision_id"] / "bindings.json").read_text(encoding="utf-8")
    )
    assert bindings["parts"][0]["relations"]["continues"] is None
    assert "octopus-asset://" in _page_text(vault, result["revision_id"])
    written = [path.name for path in (vault / ".octopus-kb" / "revisions" / result["revision_id"]).iterdir()]
    assert set(written) == {"0000.md", "bindings.json"}


def test_aggregate_status_is_the_maximum():
    assert aggregate_status(["consistent_unverified", "completed_partial"]) == "completed_partial"
    assert aggregate_status(["completed_partial", "consistent_unverified"]) == "completed_partial"
    with pytest.raises(ValueError):
        aggregate_status(["profile_unavailable"])


def _publish(vault, private, name, *, body=None, **kwargs):
    built = _bundle(vault, private, [name if body is None else body], **kwargs)
    result = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], built["approval"], now=NOW)
    result["logical_document_id"] = built["logical_document_id"]
    result["manifest"] = built["manifest"]
    result["parts"] = built["parts"]
    result["approval"] = built["approval"]
    return result


def _bundle(
    vault,
    private,
    bodies,
    *,
    placement,
    parent=None,
    label=LABEL,
    logical_id=None,
    statuses=None,
    manifest_status=None,
    scope=None,
    redaction="none/0.1.0",
    extraction=None,
):
    from octopus_kb_compound.approvals import manifest_digest, part_digest

    del vault
    logical = logical_id or logical_document_id(TENANT, VAULT_ID, placement, label)
    statuses = statuses or ["consistent_unverified"] * len(bodies)
    parts = []
    for index, body in enumerate(bodies):
        asset = "ab" * 32
        part = {
            "schema_version": "delivery-envelope/0.1.0",
            "tenant": TENANT,
            "logical_document_id": logical,
            "access_label": label,
            "content_sha256": "11" * 32,
            "part_id": f"{placement}:{index}:{body}",
            "index": index,
            "ledger_status": statuses[index],
            "ledger_ref": "ledger:test",
            "body": body,
            "assets": [{
                "hash": asset,
                "owner_node_id": f"node-{index}",
                "asset_id": asset,
            }],
            "relations": {
                "owners": [{"node_id": f"node-{index}", "owner_node_id": "root"}],
                "spans": [{"node_id": f"node-{index}", "span": {"start": 0, "end": 1}}],
                "captions": [],
                "continues": None if index == len(bodies) - 1 else f"{placement}:{index + 1}",
            },
            "extraction_key": extraction or {"redaction_policy": redaction},
            "projection_key": {"digest": "22" * 32},
        }
        part["part_digest"] = part_digest(part)
        parts.append(part)
    status = manifest_status or aggregate_status(statuses)
    manifest = {
        "schema_version": "revision-manifest/0.1.0",
        "tenant": TENANT,
        "vault_id": VAULT_ID,
        "access_label": label,
        "placement": placement,
        "logical_document_id": logical,
        "parent_revision_id": parent,
        "parts": [
            {"part_id": part["part_id"], "index": part["index"], "part_digest": part["part_digest"]}
            for part in parts
        ],
        "status": status,
        "redaction_policy": redaction,
        "policy_version": "policy/0.1.0",
    }
    manifest["revision_id"] = manifest_digest(manifest)
    chosen_scope = scope or ("partial" if status == "completed_partial" else "full")
    approval = _sign(manifest, private, chosen_scope)
    return {
        "manifest": manifest,
        "parts": parts,
        "approval": approval,
        "logical_document_id": logical,
    }


def _sign(manifest, private, scope):
    record = {
        "approval_id": "a" * 32,
        "tenant": manifest["tenant"],
        "action": "publish",
        "subject_digest": manifest["revision_id"],
        "vault_id": manifest["vault_id"],
        "access_label": manifest["access_label"],
        "scope": scope,
        "reviewer": "reviewer-1",
        "issued_at": "2026-10-02T12:00:00Z",
        "expires_at": "2026-10-03T12:00:00Z",
        "key_id": FIXTURE["key_id"],
    }
    record["signature"] = sign_approval(record, private)
    return record


def _pointer(vault: Path, logical: str) -> str | None:
    path = vault / ".octopus-kb" / "active" / logical
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def _page_text(vault: Path, revision: str) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (vault / ".octopus-kb" / "revisions" / revision).glob("*.md"))
