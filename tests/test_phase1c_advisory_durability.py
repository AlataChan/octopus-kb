"""A new revision entry is durable before the active pointer is."""

from __future__ import annotations

import fcntl
import json
import os

import pytest

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


def test_new_revision_ancestors_are_fsynced_before_the_pointer(world, monkeypatch):
    vault, private = world
    order: list[tuple[str, str]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd):
        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
        order.append(("fsync", raw.split(b"\x00", 1)[0].decode("utf-8")))
        return real_fsync(fd)

    def spy_replace(src, dst):
        order.append(("replace", os.fspath(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(envelope_mod.os, "fsync", spy_fsync)
    monkeypatch.setattr(envelope_mod.os, "replace", spy_replace)
    published = _publish(vault, private, "durable", placement="manuals/durable.docx", body="DURABLE_BODY")
    logical = published["logical_document_id"]
    replace_at = next(
        index
        for index, (kind, path) in enumerate(order)
        if kind == "replace" and path.endswith(f"/{logical}")
    )
    fsynced = {path for kind, path in order[:replace_at] if kind == "fsync"}
    assert str(vault / ".octopus-kb" / "revisions") in fsynced
    assert str(vault / ".octopus-kb") in fsynced
    assert str(vault) in fsynced
