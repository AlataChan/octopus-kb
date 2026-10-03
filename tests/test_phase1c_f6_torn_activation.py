"""A torn activation tail is repaired before the next record is appended."""

from __future__ import annotations

import json

import pytest

from octopus_kb_compound.active import load_view, matching_record
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.envelope import DURABILITY_LOG
from octopus_kb_compound import envelope as envelope_mod

from tests.test_phase1c_envelope import FIXTURE, LABEL, TENANT, VAULT_ID, _publish


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


def _shown(vault, logical: str) -> tuple[str, str]:
    view = load_view(vault)
    revision = view.pointers[logical]
    text = next(
        body
        for path, body in view.text_by_path.items()
        if f"/revisions/{revision}/" in path
    )
    record = matching_record(vault, logical, revision)
    assert record is not None
    assert record["revision_id"] == revision
    return revision, text


def test_crash_retry_and_next_activation_keep_old_and_new_records(world):
    vault, private = world
    old = _publish(vault, private, "old-body", placement="manuals/torn.docx", body="OLD_ACTIVATION_BODY")
    logical = old["logical_document_id"]
    shown, text = _shown(vault, logical)
    assert shown == old["revision_id"]
    assert "OLD_ACTIVATION_BODY" in text

    record_path = vault / ".octopus-kb" / "activations" / f"{logical}.jsonl"
    torn = b'{"revision_id":"torn","access_label":"' + "内".encode("utf-8")[:-1]
    record_path.write_bytes(record_path.read_bytes() + torn)
    shown, text = _shown(vault, logical)
    assert shown == old["revision_id"]
    assert "OLD_ACTIVATION_BODY" in text
    assert matching_record(vault, logical, old["revision_id"])["ledger_status"] == "consistent_unverified"

    retry = _publish(
        vault,
        private,
        "retry-body",
        placement="manuals/torn.docx",
        body="RETRY_ACTIVATION_BODY",
        parent=old["revision_id"],
        logical_id=logical,
    )
    shown, text = _shown(vault, logical)
    assert shown == retry["revision_id"]
    assert "RETRY_ACTIVATION_BODY" in text
    assert matching_record(vault, logical, old["revision_id"])["revision_id"] == old["revision_id"]
    assert matching_record(vault, logical, retry["revision_id"])["revision_id"] == retry["revision_id"]

    nxt = _publish(
        vault,
        private,
        "next-body",
        placement="manuals/torn.docx",
        body="NEXT_ACTIVATION_BODY",
        parent=retry["revision_id"],
        logical_id=logical,
    )
    shown, text = _shown(vault, logical)
    assert shown == nxt["revision_id"]
    assert "NEXT_ACTIVATION_BODY" in text
    for revision in (old["revision_id"], retry["revision_id"], nxt["revision_id"]):
        assert matching_record(vault, logical, revision)["revision_id"] == revision
    lines = record_path.read_bytes().splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line.decode("utf-8"))
