"""Interrupted activation keeps the previous revision, and writes finish."""

from __future__ import annotations

import os

from octopus_kb_compound.active import matching_record
from octopus_kb_compound.envelope import DURABILITY_LOG, _write_fsync
from octopus_kb_compound.jsoncanon import canonical_bytes


def test_partial_trailing_activation_keeps_the_previous_record(tmp_path):
    logical = "logical-one"
    revision = "rev-old"
    directory = tmp_path / ".octopus-kb" / "activations"
    directory.mkdir(parents=True)
    record = {
        "revision_id": revision,
        "ledger_status": "consistent_unverified",
        "access_label": "internal",
    }
    path = directory / f"{logical}.jsonl"
    path.write_bytes(canonical_bytes(record) + b"\n" + b'{"revision_id":')
    found = matching_record(tmp_path, logical, revision)
    assert found is not None
    assert found["revision_id"] == revision
    assert found["ledger_status"] == "consistent_unverified"


def test_short_write_persists_the_whole_payload(tmp_path, monkeypatch):
    real = os.write

    def short(fd, data):
        if len(data) > 1:
            return real(fd, memoryview(data)[:1])
        return real(fd, data)

    monkeypatch.setattr("octopus_kb_compound.envelope.os.write", short)
    path = tmp_path / "record"
    _write_fsync(path, b"abcdef", "unit-write")
    assert path.read_bytes() == b"abcdef"
    assert "unit-write" in DURABILITY_LOG
