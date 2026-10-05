"""D9 lineage gate. Synthetic revisions only."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from octopus_kb_compound.apply import apply_proposal
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.inbox import accept_inbox
from octopus_kb_compound.lineage import assess_lineage, file_sha256, managed_source, write_lineage
from octopus_kb_compound.propose import ProposeInputError, propose_from_part, propose_from_raw
from octopus_kb_compound import envelope as envelope_mod

from tests.test_phase1c_controls import _install_transport, _proposal
from tests.test_phase1c_envelope import (
    FIXTURE,
    LABEL,
    NOW,
    TENANT,
    VAULT_ID,
    _bundle,
    ingest_envelope,
)
from tests.test_phase1c_r3_budget_attempts import _allow_default_endpoint
from tests.test_phase2a_attestation import DURABILITY_LOG, VECTORS, _succeeded


@pytest.fixture
def world(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    reviewer = parse_private_key(FIXTURE["private_key_pem"])
    verifier = parse_private_key(VECTORS["verifier"]["private_key_pem"])
    monkeypatch.setenv("OCTOPUS_KB_TENANT", TENANT)
    monkeypatch.setenv(
        "OCTOPUS_KB_VAULTS",
        json.dumps({VAULT_ID: {"root": str(vault), "allowed_access_labels": [LABEL, "restricted"]}}),
    )
    monkeypatch.setenv(
        "OCTOPUS_KB_APPROVAL_KEYS",
        json.dumps({
            FIXTURE["key_id"]: public_key_b64(reviewer),
            VECTORS["reviewer"]["key_id"]: VECTORS["reviewer"]["public_key_b64"],
        }),
    )
    monkeypatch.setenv(
        "OCTOPUS_KB_VERIFIER_KEYS",
        json.dumps({VECTORS["verifier"]["key_id"]: VECTORS["verifier"]["public_key_b64"]}),
    )
    envelope_mod.FAULT = None
    DURABILITY_LOG.clear()
    return vault, reviewer, verifier

ROOT_PAGE = ".octopus-kb/revisions/{revision}/0000.md"


def _activate_partial(vault, reviewer):
    built = _bundle(
        vault,
        reviewer,
        ["ledger_status: succeeded"],
        placement="manuals/partial.docx",
        statuses=["completed_partial"],
        manifest_status="completed_partial",
    )
    result = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], built["approval"], now=NOW)
    assert result["status"] == "activated"
    page = ROOT_PAGE.format(revision=result["revision_id"])
    return built, result, page


def _seed_wiki(vault: Path) -> None:
    (vault / "wiki").mkdir(exist_ok=True)
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")


def _propose(monkeypatch, vault: Path, page: str):
    _allow_default_endpoint(monkeypatch)
    _install_transport(monkeypatch, [_proposal("ignored")])
    return propose_from_raw(vault / page, vault)


def _log(vault: Path) -> list[dict]:
    path = vault / ".octopus-kb" / "apply-log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _case_insensitive(directory: Path) -> bool:
    probe = directory / "CaseProbe"
    probe.mkdir()
    try:
        return (directory / "caseprobe").is_dir()
    finally:
        probe.rmdir()


def _assert_alias_is_gated(monkeypatch, vault: Path, page: str, raw: str) -> None:
    proposed = _propose(monkeypatch, vault, raw)
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    assert proposal["source"]["path"] == page
    lineage = json.loads(
        (vault / ".octopus-kb" / "lineage" / f"{proposed.proposal_id}.json").read_text(encoding="utf-8")
    )
    assert lineage["sources"][0]["raw_path"] == page
    result = apply_proposal(vault, proposal, now=NOW)
    assert result.status != "applied"
    assert result.message == "approval_required"


def test_dot_prefix_traversal_and_symlink_are_lineage_gated(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    _built, _result, page = _activate_partial(vault, reviewer)
    (vault / "raw").mkdir()
    alias = vault / "alias.md"
    alias.symlink_to(vault / page)
    _assert_alias_is_gated(monkeypatch, vault, page, "./" + page)
    _assert_alias_is_gated(monkeypatch, vault, page, "raw/../" + page)
    _assert_alias_is_gated(monkeypatch, vault, page, "alias.md")


def test_case_variant_is_lineage_gated(world, monkeypatch):
    vault, reviewer, _verifier = world
    if not _case_insensitive(vault):
        pytest.skip("filesystem is case-sensitive")
    _seed_wiki(vault)
    _built, _result, page = _activate_partial(vault, reviewer)
    _assert_alias_is_gated(monkeypatch, vault, page, page.replace(".octopus-kb", ".OCTOPUS-KB"))


def test_active_partial_page_is_lineage_gated(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, result, page = _activate_partial(vault, reviewer)
    proposed = _propose(monkeypatch, vault, page)
    lineage_path = vault / ".octopus-kb" / "lineage" / f"{proposed.proposal_id}.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert lineage["sources"][0]["part_status"] == "completed_partial"
    assert lineage["sources"][0]["raw_path"] == page
    assert "succeeded" not in lineage["sources"][0]["part_status"]
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    missing = apply_proposal(vault, proposal, now=NOW)
    assert missing.message == "approval_required"
    expired = dict(built["approval"])
    expired["expires_at"] = "2026-10-02T12:00:00Z"
    from octopus_kb_compound.approvals import sign_approval

    expired["signature"] = sign_approval(expired, reviewer)
    assert apply_proposal(vault, proposal, approval=expired, now=NOW).message == "expired"
    full = dict(built["approval"])
    full["scope"] = "full"
    full["signature"] = sign_approval(full, reviewer)
    assert apply_proposal(vault, proposal, approval=full, now=NOW).message == "scope_mismatch"
    applied = apply_proposal(vault, proposal, approval=built["approval"], now=NOW)
    assert applied.status == "applied"
    audit = json.loads(next((vault / ".octopus-kb" / "audit").glob("*.json")).read_text(encoding="utf-8"))
    assert audit["authority"]["kind"] == "approval"
    assert audit["outcome"] == "applied"
    assert _log(vault)[-1]["outcome"] == "applied"


def test_propose_from_part_writes_lineage_for_the_staged_digest(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, _page = _activate_partial(vault, reviewer)
    _allow_default_endpoint(monkeypatch)
    _install_transport(monkeypatch, [_proposal("part")])
    part = built["parts"][0]
    proposed = propose_from_part(part, vault)
    lineage = vault / ".octopus-kb" / "lineage" / f"{proposed.proposal_id}.json"
    assert lineage.is_file()
    recorded = json.loads(lineage.read_text(encoding="utf-8"))
    assert recorded["sources"][0]["raw_path"].startswith(".octopus-kb/part-propose/")
    assert recorded["sources"][0]["part_status"] == "completed_partial"


def test_lineage_file_omitted_edited_or_stale(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, page = _activate_partial(vault, reviewer)
    proposed = _propose(monkeypatch, vault, page)
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    lineage_path = vault / ".octopus-kb" / "lineage" / f"{proposal['id']}.json"
    original = lineage_path.read_text(encoding="utf-8")
    lineage_path.unlink()
    assert apply_proposal(vault, proposal, approval=built["approval"], now=NOW).message == "lineage_missing"
    lineage_path.write_text(original, encoding="utf-8")
    edited = json.loads(original)
    edited["sources"][0]["part_status"] = "succeeded"
    lineage_path.write_text(json.dumps(edited), encoding="utf-8")
    assert apply_proposal(vault, proposal, approval=built["approval"], now=NOW).message == "lineage_mismatch"
    lineage_path.write_text(original, encoding="utf-8")
    target = vault / page
    target.write_text(target.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    assert apply_proposal(vault, proposal, approval=built["approval"], now=NOW).message == "lineage_stale"


def test_inbox_override_still_needs_a_valid_approval(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, page = _activate_partial(vault, reviewer)
    proposed = _propose(monkeypatch, vault, page)
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    proposal["operations"][0]["confidence"] = 0.5
    inbox = vault / ".octopus-kb" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{proposal['id']}.json").write_text(json.dumps(proposal), encoding="utf-8")
    refused = accept_inbox(vault, proposal["id"], now=NOW)
    assert refused.message == "approval_required"
    (inbox / f"{proposal['id']}.json").write_text(json.dumps(proposal), encoding="utf-8")
    accepted = accept_inbox(vault, proposal["id"], approval=built["approval"], now=NOW)
    assert accepted.status == "applied"


def test_multi_source_requires_every_source_and_legacy_stays_unledgered(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, page = _activate_partial(vault, reviewer)
    proposed = _propose(monkeypatch, vault, page)
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    part = built["parts"][0]
    extra = vault / ".octopus-kb" / "part-propose" / f"{part['part_digest']}.md"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(part["body"].encode("utf-8"))
    proposal["operations"][0]["source_span"] = {
        "path": extra.relative_to(vault).as_posix(),
        "start_line": 1,
        "end_line": 1,
    }
    assert apply_proposal(vault, proposal, approval=built["approval"], now=NOW).message == "lineage_missing"
    write_lineage(vault, proposal)
    applied = apply_proposal(vault, proposal, approval=built["approval"], now=NOW)
    assert applied.status == "applied"

    legacy = {
        "id": "legacy-1",
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log",
            "path": "wiki/LOG.md",
            "entry": "2026-04-18: legacy",
            "rationale": "r",
            "confidence": 1.0,
        }],
        "status": "pending",
    }
    assert not (vault / ".octopus-kb" / "lineage" / "legacy-1.json").exists()
    result = apply_proposal(vault, legacy, now=NOW)
    assert result.status == "applied"
    assert _log(vault)[-1]["authority"]["kind"] == "unledgered"
    assert file_sha256(vault, page)


def test_succeeded_attestation_applies_and_approval_admission_is_rechecked(world, monkeypatch):
    vault, reviewer, verifier = world
    _seed_wiki(vault)
    attested = _succeeded(vault, verifier, "attested body", placement="manuals/attested-lineage.docx")
    activated = ingest_envelope(
        VAULT_ID,
        attested["manifest"],
        attested["parts"],
        None,
        attested["attestation"],
        now=NOW,
    )
    assert activated["status"] == "activated"
    page = ROOT_PAGE.format(revision=activated["revision_id"])
    proposed = _propose(monkeypatch, vault, page)
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    assert apply_proposal(vault, proposal, now=NOW).status == "applied"

    approved = _succeeded(vault, verifier, "approved body", placement="manuals/approved-lineage.docx")
    second = ingest_envelope(
        VAULT_ID,
        approved["manifest"],
        approved["parts"],
        approved["approval"],
        now=NOW,
    )
    assert second["status"] == "activated"
    other = ROOT_PAGE.format(revision=second["revision_id"])
    _install_transport(monkeypatch, [_proposal("next")])
    again = propose_from_raw(vault / other, vault)
    body = json.loads((vault / again.path).read_text(encoding="utf-8"))
    assert apply_proposal(vault, body, now=NOW).message == "approval_required"
    later = datetime(2026, 10, 4, tzinfo=timezone.utc)
    assert apply_proposal(vault, body, approval=approved["approval"], now=later).message == "expired"
    assert apply_proposal(vault, body, approval=approved["approval"], now=NOW).status == "applied"


def _park_inbox(vault: Path, proposal: dict) -> None:
    inbox = vault / ".octopus-kb" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{proposal['id']}.json").write_text(json.dumps(proposal), encoding="utf-8")


def test_deleted_managed_source_is_refused_by_apply_and_inbox(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    _built, _result, page = _activate_partial(vault, reviewer)
    proposed = _propose(monkeypatch, vault, page)
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    assert assess_lineage(vault, proposal, approval=None, now=NOW).reason == "approval_required"
    (vault / page).unlink()
    refused = apply_proposal(vault, proposal, now=NOW)
    assert refused.status == "rejected"
    _park_inbox(vault, proposal)
    inbox = accept_inbox(vault, proposal["id"], now=NOW)
    assert inbox.status == "rejected"
    legacy = {
        "id": "legacy-deleted-source",
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log",
            "path": "wiki/LOG.md",
            "entry": "2026-04-18: legacy",
            "rationale": "r",
            "confidence": 1.0,
        }],
        "status": "pending",
    }
    assert not (vault / ".octopus-kb" / "lineage" / "legacy-deleted-source.json").exists()
    assert apply_proposal(vault, legacy, now=NOW).status == "applied"
    assert _log(vault)[-1]["authority"]["kind"] == "unledgered"


def test_hard_link_alias_is_lineage_gated_on_apply_and_inbox(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    _built, _result, page = _activate_partial(vault, reviewer)
    (vault / "raw").mkdir()
    alias = vault / "raw" / "alias.md"
    os.link(vault / page, alias)
    assert os.path.samefile(alias, vault / page)
    proposed = _propose(monkeypatch, vault, "raw/alias.md")
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    refused = apply_proposal(vault, proposal, now=NOW)
    assert refused.status == "rejected"
    assert refused.message == "approval_required"
    assert managed_source(vault, alias) == page
    assert proposal["source"]["path"] == page
    _park_inbox(vault, proposal)
    assert accept_inbox(vault, proposal["id"], now=NOW).message == "approval_required"


FORGED_BODY = "Completely unapproved replacement body."


def _forged_part(part: dict) -> dict:
    forged = dict(part)
    forged["body"] = FORGED_BODY
    return forged


def test_changed_body_with_original_digest_is_refused_before_model(world, monkeypatch):
    vault, reviewer, verifier = world
    _seed_wiki(vault)
    approved, _result, _page = _activate_partial(vault, reviewer)
    attested = _succeeded(vault, verifier, "attested body", placement="manuals/attested-binding.docx")
    activated = ingest_envelope(
        VAULT_ID,
        attested["manifest"],
        attested["parts"],
        None,
        attested["attestation"],
        now=NOW,
    )
    assert activated["status"] == "activated"
    _allow_default_endpoint(monkeypatch)
    for built in (approved, attested):
        calls = _install_transport(monkeypatch, [_proposal("should-not-run")])
        digest = built["parts"][0]["part_digest"]
        with pytest.raises(ProposeInputError):
            propose_from_part(_forged_part(built["parts"][0]), vault)
        assert calls == []
        assert not (vault / ".octopus-kb" / "part-propose" / f"{digest}.md").exists()


def test_propose_from_part_accepts_the_staged_body_named_by_its_digest(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, _page = _activate_partial(vault, reviewer)
    part = built["parts"][0]
    stub = {"body": part["body"], "part_digest": part["part_digest"]}
    _allow_default_endpoint(monkeypatch)
    calls = _install_transport(monkeypatch, [_proposal("part"), _proposal("should-not-run")])
    proposed = propose_from_part(stub, vault)
    assert proposed.proposal_id
    assert calls
    forged = {"body": FORGED_BODY, "part_digest": part["part_digest"]}
    sent = len(calls)
    with pytest.raises(ProposeInputError):
        propose_from_part(forged, vault)
    assert len(calls) == sent
    written = (vault / ".octopus-kb" / "part-propose" / f"{part['part_digest']}.md").read_text(encoding="utf-8")
    assert written == part["body"]


def test_lineage_creation_rejects_raw_bytes_that_differ_from_the_staged_part(world):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, _page = _activate_partial(vault, reviewer)
    part = built["parts"][0]
    rel = f".octopus-kb/part-propose/{part['part_digest']}.md"
    target = vault / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FORGED_BODY, encoding="utf-8")
    proposal = {
        "id": "forged-lineage",
        "source": {
            "kind": "raw_file",
            "path": rel,
            "sha256": hashlib.sha256(FORGED_BODY.encode("utf-8")).hexdigest(),
        },
    }
    assert write_lineage(vault, proposal) is None
    assert not (vault / ".octopus-kb" / "lineage" / "forged-lineage.json").exists()


def test_apply_rejects_raw_bytes_that_differ_from_the_staged_part(world, monkeypatch):
    vault, reviewer, _verifier = world
    _seed_wiki(vault)
    built, _result, _page = _activate_partial(vault, reviewer)
    _allow_default_endpoint(monkeypatch)
    _install_transport(monkeypatch, [_proposal("part")])
    proposed = propose_from_part(built["parts"][0], vault)
    lineage_path = vault / ".octopus-kb" / "lineage" / f"{proposed.proposal_id}.json"
    recorded = json.loads(lineage_path.read_text(encoding="utf-8"))
    target = vault / recorded["sources"][0]["raw_path"]
    target.write_text(FORGED_BODY, encoding="utf-8")
    forged_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    recorded["sources"][0]["raw_sha256"] = forged_hash
    lineage_path.write_text(json.dumps(recorded), encoding="utf-8")
    proposal = json.loads((vault / proposed.path).read_text(encoding="utf-8"))
    proposal["source"]["sha256"] = forged_hash
    refused = apply_proposal(vault, proposal, approval=built["approval"], now=NOW)
    assert refused.status == "rejected"
