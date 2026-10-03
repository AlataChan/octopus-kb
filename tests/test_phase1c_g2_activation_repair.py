"""An interrupted activation repair leaves the previous record readable."""

from __future__ import annotations

import json
import os

import pytest

from octopus_kb_compound.active import load_view, matching_record
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.envelope import DURABILITY_LOG, ActivationInterrupted
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

_STAGES = (
    "activation-repair-before",
    "activation-repair-during",
    "activation-repair-after",
)


def _tails() -> dict[str, bytes]:
    return {
        "ordinary": b'{"revision_id":"torn","note":"cut',
        "split-utf8": b'{"revision_id":"torn","access_label":"' + "内".encode("utf-8")[:-1],
    }


def _shown(vault, logical: str) -> tuple[str, str]:
    view = load_view(vault)
    revision = view.pointers[logical]
    text = next(
        body
        for path, body in view.text_by_path.items()
        if f"/revisions/{revision}/" in path
    )
    return revision, text


def test_interrupted_repair_keeps_the_old_activation(world, monkeypatch):
    vault, private = world
    old = _publish(vault, private, "old-body", placement="manuals/repair.docx", body="OLD_ACTIVATION_BODY")
    logical = old["logical_document_id"]
    record_path = vault / ".octopus-kb" / "activations" / f"{logical}.jsonl"
    original = record_path.read_bytes()
    assert matching_record(vault, logical, old["revision_id"])["revision_id"] == old["revision_id"]

    real_open = os.open

    def open_and_crash_after_trunc(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is None:
            fd = real_open(path, flags, mode)
        else:
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if flags & os.O_TRUNC and str(path).endswith(".jsonl"):
            os.close(fd)
            raise ActivationInterrupted("after-O_TRUNC")
        return fd

    monkeypatch.setattr(os, "open", open_and_crash_after_trunc)
    try:
        for name, tail in _tails().items():
            for stage in _STAGES:
                record_path.write_bytes(original + tail)
                envelope_mod.FAULT = stage
                with pytest.raises(ActivationInterrupted):
                    _publish(
                        vault,
                        private,
                        f"retry-{name}-{stage}",
                        placement="manuals/repair.docx",
                        body=f"RETRY_{name}_{stage}",
                        parent=old["revision_id"],
                        logical_id=logical,
                    )
                found = matching_record(vault, logical, old["revision_id"])
                assert found is not None
                assert found["revision_id"] == old["revision_id"]
                shown, text = _shown(vault, logical)
                assert shown == old["revision_id"]
                assert "OLD_ACTIVATION_BODY" in text
                assert f"RETRY_{name}_{stage}" not in text
    finally:
        envelope_mod.FAULT = None

    record_path.write_bytes(original + _tails()["split-utf8"])
    healed = _publish(
        vault,
        private,
        "healed-body",
        placement="manuals/repair.docx",
        body="HEALED_ACTIVATION_BODY",
        parent=old["revision_id"],
        logical_id=logical,
    )
    assert matching_record(vault, logical, old["revision_id"])["revision_id"] == old["revision_id"]
    assert matching_record(vault, logical, healed["revision_id"])["revision_id"] == healed["revision_id"]
    shown, text = _shown(vault, logical)
    assert shown == healed["revision_id"]
    assert "HEALED_ACTIVATION_BODY" in text
    lines = record_path.read_bytes().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line.decode("utf-8"))
