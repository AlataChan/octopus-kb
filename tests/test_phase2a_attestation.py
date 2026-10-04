"""Verified publication. Fixture keys are test-only and are never live keys."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from octopus_kb_compound.active import activation_authority, load_view, matching_record
from octopus_kb_compound.approvals import (
    manifest_digest,
    parse_private_key,
    public_key_b64,
    sign_approval,
    sign_attestation,
    verify_approval,
    verify_attestation,
)
from octopus_kb_compound.envelope import DURABILITY_LOG, aggregate_status, ingest_envelope
from octopus_kb_compound.frontmatter import render_frontmatter
from octopus_kb_compound.jsoncanon import canonical_bytes
from octopus_kb_compound.models import PageMeta
from octopus_kb_compound import envelope as envelope_mod

from tests.test_phase1c_envelope import FIXTURE, LABEL, NOW, TENANT, VAULT_ID, _bundle

ROOT = Path(__file__).resolve().parents[1]
VECTOR_DIR = ROOT / "tests" / "fixtures" / "phase2a" / "verification"
VECTORS = json.loads((VECTOR_DIR / "vectors.json").read_text(encoding="utf-8"))
SCHEMA_DIR = ROOT / "src" / "octopus_kb_compound" / "_schemas"
VECTOR_DIGEST = "c7b570d9e142ec5ff1eb2983cdd825e61ce88aa50ae361c99f8a8a70f5d489b4"


def _moment(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _directory_digest(directory: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(item for item in directory.iterdir() if item.is_file()):
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _schema(name: str):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _rejects(name: str, instance: dict) -> bool:
    try:
        Draft202012Validator(_schema(name)).validate(instance)
    except ValidationError:
        return True
    return False


@pytest.fixture
def world(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    reviewer = parse_private_key(VECTORS["reviewer"]["private_key_pem"])
    verifier = parse_private_key(VECTORS["verifier"]["private_key_pem"])
    monkeypatch.setenv("OCTOPUS_KB_TENANT", TENANT)
    monkeypatch.setenv(
        "OCTOPUS_KB_VAULTS",
        json.dumps({VAULT_ID: {"root": str(vault), "allowed_access_labels": [LABEL, "restricted"]}}),
    )
    monkeypatch.setenv(
        "OCTOPUS_KB_APPROVAL_KEYS",
        json.dumps({VECTORS["reviewer"]["key_id"]: VECTORS["reviewer"]["public_key_b64"]}),
    )
    monkeypatch.setenv(
        "OCTOPUS_KB_VERIFIER_KEYS",
        json.dumps({VECTORS["verifier"]["key_id"]: VECTORS["verifier"]["public_key_b64"]}),
    )
    envelope_mod.FAULT = None
    DURABILITY_LOG.clear()
    return vault, reviewer, verifier


def test_vector_directory_digest_is_pinned():
    text = (VECTOR_DIR / "README.md").read_text(encoding="utf-8")
    assert "TEST ONLY" in text
    assert "TEST ONLY" in VECTORS["label"]
    assert _directory_digest(VECTOR_DIR) == VECTOR_DIGEST


def test_version_dispatched_digests_match_the_vectors():
    assert manifest_digest(VECTORS["manifest_0_1_0"]) == VECTORS["digest_0_1_0"]
    assert manifest_digest(VECTORS["manifest_0_2_0"]) == VECTORS["digest_0_2_0"]
    assert manifest_digest(VECTORS["manifest_0_2_0"]) == manifest_digest(VECTORS["manifest_0_2_0_without_ref"])
    with pytest.raises(ValueError, match="unknown_schema_version"):
        manifest_digest({"schema_version": "revision-manifest/9.9.9", "status": "succeeded"})


def test_each_vector_fails_or_passes_with_its_named_reason():
    seen = set()
    for case in VECTORS["cases"]:
        if case["kind"] == "approval":
            verdict = verify_approval(
                case["approval"],
                case["manifest"],
                case["approval_keys"],
                tenant=case["tenant"],
                vault_id=case["vault_id"],
                access_label=case["access_label"],
                now=_moment(case["now"]),
            )
        else:
            verdict = verify_attestation(
                case["attestation"],
                case["manifest"],
                case["verifier_keys"],
                tenant=case["tenant"],
                vault_id=case["vault_id"],
                access_label=case["access_label"],
                logical_document_id=case["logical_document_id"],
                staged_statuses=case["staged_statuses"],
                now=_moment(case["now"]),
            )
        assert verdict.ok is case["ok"], case["name"]
        assert verdict.reason == case["reason"], case["name"]
        seen.add(case["name"])
    assert seen == {
        "valid",
        "forged_succeeded",
        "changed_body",
        "changed_destination",
        "unknown_verifier_key",
        "reviewer_key_as_verifier",
        "verifier_key_as_reviewer",
        "unknown_decision_table",
        "expired",
        "replayed_revision",
    }


def test_schema_keeps_0_1_0_semantics_and_accepts_0_2_0():
    assert not _rejects("revision-manifest.schema.json", VECTORS["manifest_0_1_0"])
    assert not _rejects("revision-manifest.schema.json", VECTORS["manifest_0_2_0"])
    assert not _rejects("revision-manifest.schema.json", VECTORS["manifest_0_2_0_without_ref"])
    assert not _rejects("verification-attestation.schema.json", VECTORS["attestation"])
    succeeded = dict(VECTORS["manifest_0_1_0"])
    succeeded["status"] = "succeeded"
    assert _rejects("revision-manifest.schema.json", succeeded)
    referenced = dict(VECTORS["manifest_0_1_0"])
    referenced["verification_ref"] = "c1" * 16
    assert _rejects("revision-manifest.schema.json", referenced)
    unknown = dict(VECTORS["manifest_0_2_0"])
    unknown["schema_version"] = "revision-manifest/9.9.9"
    assert _rejects("revision-manifest.schema.json", unknown)


def test_0_1_0_ingest_rejects_succeeded_and_verification_ref(world):
    succeeded = dict(VECTORS["manifest_0_1_0"])
    succeeded["status"] = "succeeded"
    assert ingest_envelope(VAULT_ID, succeeded, [], None, now=NOW)["status"] == "rejected:malformed"
    referenced = dict(VECTORS["manifest_0_1_0"])
    referenced["verification_ref"] = "c1" * 16
    assert ingest_envelope(VAULT_ID, referenced, [], None, now=NOW)["status"] == "rejected:malformed"


def test_succeeded_is_the_lowest_ranked_status_and_accepts_either_scope():
    assert aggregate_status(["succeeded", "consistent_unverified"]) == "consistent_unverified"
    assert aggregate_status(["succeeded", "completed_partial"]) == "completed_partial"
    manifest = VECTORS["manifest_0_2_0"]
    reviewer = parse_private_key(VECTORS["reviewer"]["private_key_pem"])
    keys = {VECTORS["reviewer"]["key_id"]: public_key_b64(reviewer)}
    for scope in ("partial", "full"):
        approval = _approval(manifest, reviewer, scope)
        verdict = verify_approval(
            approval,
            manifest,
            keys,
            tenant=manifest["tenant"],
            vault_id=manifest["vault_id"],
            access_label=manifest["access_label"],
            now=NOW,
        )
        assert verdict.ok is True, scope
        assert verdict.reason == "ok"


def test_valid_attestation_activates_without_an_approval(world):
    vault, _reviewer, verifier = world
    built = _succeeded(vault, verifier, "attested body", placement="manuals/attested.docx")
    result = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], None, built["attestation"], now=NOW)
    assert result["status"] == "activated"
    assert "attestation" not in result
    record = _activation(vault, built["logical"])
    assert "approval_id" not in record
    assert record["authority"] == {
        "kind": "attestation",
        "attestation_id": built["attestation"]["attestation_id"],
        "key_id": built["attestation"]["key_id"],
    }
    stored = vault / ".octopus-kb" / "attestations" / f"{built['attestation']['attestation_id']}.json"
    assert stored.read_bytes() == canonical_bytes(built["attestation"]) + b"\n"
    assert DURABILITY_LOG.index("attestation") < DURABILITY_LOG.index("activation-record")
    view = load_view(vault)
    assert view.provenance[f".octopus-kb/revisions/{result['revision_id']}/0000.md"]["authority"]["kind"] == "attestation"


def test_succeeded_revision_activates_through_an_approval(world):
    vault, reviewer, _verifier = world
    built = _succeeded(vault, reviewer, "approved body", placement="manuals/approved.docx")
    result = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], built["approval"], now=NOW)
    assert result["status"] == "activated"
    assert "attestation" not in result
    record = _activation(vault, built["logical"])
    assert record["approval_id"] == built["approval"]["approval_id"]
    assert record["authority"] == {"kind": "approval", "approval_id": built["approval"]["approval_id"]}


def test_refused_attestation_falls_back_to_the_approval_path(world):
    vault, reviewer, verifier = world
    built = _succeeded(vault, verifier, "fallback body", placement="manuals/fallback.docx")
    expired = dict(built["attestation"])
    expired["expires_at"] = "2026-10-02T12:00:00Z"
    expired["signature"] = sign_attestation(expired, verifier)
    approved = ingest_envelope(
        VAULT_ID,
        built["manifest"],
        built["parts"],
        _approval(built["manifest"], reviewer, "full"),
        expired,
        now=NOW,
    )
    assert approved["status"] == "activated"
    assert approved["attestation"] == "expired"
    assert _activation(vault, built["logical"])["authority"]["kind"] == "approval"

    waiting = _succeeded(vault, verifier, "waiting body", placement="manuals/waiting.docx")
    refused = dict(waiting["attestation"])
    refused["catalog_digest"] = "e" + refused["catalog_digest"][1:]
    result = ingest_envelope(VAULT_ID, waiting["manifest"], waiting["parts"], None, refused, now=NOW)
    assert result == {
        "status": "staged_awaiting_approval",
        "revision_id": waiting["manifest"]["revision_id"],
        "attestation": "bad_signature",
    }


def test_overlapping_authorities_are_refused_at_load(world, monkeypatch):
    vault, reviewer, _verifier = world
    built = _bundle(vault, reviewer, ["overlap"], placement="manuals/overlap.docx")
    same_key = json.dumps({FIXTURE["key_id"]: public_key_b64(reviewer)})
    monkeypatch.setenv("OCTOPUS_KB_APPROVAL_KEYS", same_key)
    monkeypatch.setenv("OCTOPUS_KB_VERIFIER_KEYS", json.dumps({"verifier-copy": public_key_b64(reviewer)}))
    shared_material = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], built["approval"], now=NOW)
    assert shared_material["status"] == "rejected:key_configuration"
    monkeypatch.setenv("OCTOPUS_KB_VERIFIER_KEYS", same_key)
    shared_id = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], built["approval"], now=NOW)
    assert shared_id["status"] == "rejected:key_configuration"


def test_old_activation_record_without_authority_still_reads(tmp_path):
    logical = "ab" * 32
    revision = "cd" * 32
    revision_dir = tmp_path / ".octopus-kb" / "revisions" / revision
    revision_dir.mkdir(parents=True)
    meta = PageMeta(
        title="Old",
        page_type="raw_source",
        lang="en",
        role="raw_source",
        layer="source",
        summary="Old",
        source_of_truth="canonical",
    )
    (revision_dir / "0000.md").write_text(f"{render_frontmatter(meta)}\nbody\n", encoding="utf-8")
    record = {
        "revision_id": revision,
        "approval_id": "a" * 32,
        "ledger_status": "consistent_unverified",
        "logical_document_id": logical,
        "access_label": "internal",
    }
    activations = tmp_path / ".octopus-kb" / "activations"
    activations.mkdir(parents=True)
    (activations / f"{logical}.jsonl").write_bytes(canonical_bytes(record) + b"\n")
    active = tmp_path / ".octopus-kb" / "active"
    active.mkdir(parents=True)
    (active / logical).write_text(revision + "\n", encoding="utf-8")
    found = matching_record(tmp_path, logical, revision)
    assert activation_authority(found) == {"kind": "approval", "approval_id": "a" * 32}
    view = load_view(tmp_path)
    page = f".octopus-kb/revisions/{revision}/0000.md"
    assert view.provenance[page]["ledger_status"] == "consistent_unverified"
    assert view.provenance[page]["authority"]["kind"] == "approval"


def _succeeded(vault, private, body, *, placement):
    del vault
    from octopus_kb_compound.approvals import logical_document_id, part_digest

    logical = logical_document_id(TENANT, VAULT_ID, placement, LABEL)
    part = {
        "schema_version": "delivery-envelope/0.2.0",
        "tenant": TENANT,
        "logical_document_id": logical,
        "access_label": LABEL,
        "content_sha256": "11" * 32,
        "part_id": f"{placement}:0:{body}",
        "index": 0,
        "ledger_status": "succeeded",
        "ledger_ref": "ledger:test",
        "body": body,
        "assets": [{
            "hash": "ab" * 32,
            "owner_node_id": "node-0",
            "asset_id": "ab" * 32,
        }],
        "relations": {
            "owners": [{"node_id": "node-0", "owner_node_id": "root"}],
            "spans": [{"node_id": "node-0", "span": {"start": 0, "end": 1}}],
            "captions": [],
            "continues": None,
        },
        "extraction_key": {"redaction_policy": "none/0.1.0"},
        "projection_key": {"digest": "22" * 32},
    }
    part["part_digest"] = part_digest(part)
    manifest = {
        "schema_version": "revision-manifest/0.2.0",
        "tenant": TENANT,
        "vault_id": VAULT_ID,
        "access_label": LABEL,
        "placement": placement,
        "logical_document_id": logical,
        "parent_revision_id": None,
        "parts": [{"part_id": part["part_id"], "index": 0, "part_digest": part["part_digest"]}],
        "status": "succeeded",
        "redaction_policy": "none/0.1.0",
        "policy_version": "policy/0.1.0",
        "verification_ref": "c2" * 16,
    }
    manifest["revision_id"] = manifest_digest(manifest)
    attestation = {
        "schema_version": "verification-attestation/0.1.0",
        "role": "verifier",
        "attestation_id": manifest["verification_ref"],
        "key_id": VECTORS["verifier"]["key_id"],
        "revision_id": manifest["revision_id"],
        "logical_document_id": logical,
        "tenant": TENANT,
        "vault_id": VAULT_ID,
        "access_label": LABEL,
        "parts": [{"index": 0, "part_digest": part["part_digest"], "status": "succeeded"}],
        "catalog_digest": "cd" * 32,
        "validator_registry_version": "validator-registry/0.1.0",
        "probe_scorer_version": "probe-scorer/0.1.0",
        "decision_table_version": "decision-table/0.1.0",
        "issued_at": "2026-10-02T12:00:00Z",
        "expires_at": "2026-10-03T12:00:00Z",
    }
    attestation["signature"] = sign_attestation(attestation, private)
    return {
        "manifest": manifest,
        "parts": [part],
        "approval": _approval(manifest, parse_private_key(VECTORS["reviewer"]["private_key_pem"]), "full"),
        "attestation": attestation,
        "logical": logical,
    }


def _approval(manifest, private, scope):
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
        "key_id": VECTORS["reviewer"]["key_id"],
    }
    record["signature"] = sign_approval(record, private)
    return record


def _activation(vault: Path, logical: str) -> dict:
    path = vault / ".octopus-kb" / "activations" / f"{logical}.jsonl"
    return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
