"""D9 lineage gate. Synthetic revisions only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from octopus_kb_compound.apply import apply_proposal
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.inbox import accept_inbox
from octopus_kb_compound.lineage import file_sha256, write_lineage
from octopus_kb_compound.propose import propose_from_part, propose_from_raw
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
    extra.write_text("ledger_status: succeeded\n", encoding="utf-8")
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
