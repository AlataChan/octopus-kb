"""An interrupted staged part is reconciled on retry."""

from __future__ import annotations

import json

import pytest

from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.envelope import ingest_envelope

from tests.test_phase1c_envelope import FIXTURE, LABEL, NOW, TENANT, VAULT_ID, _bundle


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
    return vault, private


def test_truncated_stage_is_replaced_and_the_revision_activates(world):
    vault, private = world
    built = _bundle(vault, private, ["complete body"], placement="manuals/stage.docx")
    part = built["parts"][0]
    target = (
        vault / ".octopus-kb" / "staging" / built["logical_document_id"] / built["manifest"]["revision_id"]
        / f"{part['part_digest']}.json"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"part_digest":')
    result = ingest_envelope(VAULT_ID, built["manifest"], built["parts"], built["approval"], now=NOW)
    assert result["status"] == "activated"
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["part_digest"] == part["part_digest"]
    assert stored["body"] == "complete body"
