"""Proposal identity comes from the interpretation key, not the model."""

from __future__ import annotations

import json
from pathlib import Path

from octopus_kb_compound.propose import propose_from_part

_SERVED = "qwen2.5:7b-instruct"
_MODEL_ID = "prop-c6785ad01312"


def test_same_model_supplied_id_for_two_parts_does_not_collide(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    _install_transport(monkeypatch, [_proposal(_MODEL_ID), _proposal(_MODEL_ID)])
    first = propose_from_part({"body": "PART-A", "part_digest": "aa" * 32}, vault)
    second = propose_from_part({"body": "PART-B", "part_digest": "bb" * 32}, vault)
    assert first.proposal_id != _MODEL_ID
    assert second.proposal_id != _MODEL_ID
    assert first.proposal_id != second.proposal_id
    files = list((vault / ".octopus-kb" / "proposals").glob("*.json"))
    assert len(files) == 2
    winners = [record for record in _records(vault) if record.get("accepted") is True]
    assert {first.proposal_id, second.proposal_id} == {record["key"] for record in winners}


def test_identical_replay_keeps_the_derived_proposal(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [_proposal(_MODEL_ID), _proposal(_MODEL_ID)])
    part = {"body": "PART-A", "part_digest": "aa" * 32}
    first = propose_from_part(part, vault)
    stored = (vault / first.path).read_bytes()
    second = propose_from_part(part, vault)
    assert second.replayed is True
    assert second.proposal_id == first.proposal_id
    assert second.path == first.path
    assert (vault / first.path).read_bytes() == stored
    assert len(calls) == 1
    saved = json.loads(stored.decode("utf-8"))
    assert saved["id"] == first.proposal_id
    assert saved["id"] != _MODEL_ID


def _records(vault: Path) -> list[dict]:
    directory = vault / ".octopus-kb" / "interpretations" / "records"
    return [json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")]


def _proposal(proposal_id: str) -> bytes:
    payload = {
        "id": proposal_id,
        "created_at": "2026-04-18T10:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/WRONG.md", "sha256": "0" * 64},
        "produced_by": {"provider_profile": "x", "model": "x", "prompt_version": "x"},
        "operations": [{
            "op": "append_log",
            "path": "wiki/LOG.md",
            "entry": "2026-04-18: added",
            "rationale": "r",
            "confidence": 1.0,
        }],
        "status": "pending",
    }
    return json.dumps({
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "model": _SERVED,
        "usage": {},
    }).encode("utf-8")


def _install_transport(monkeypatch, responses: list[bytes]):
    import octopus_kb_compound.llm as llm_mod

    monkeypatch.delenv("OCTOPUS_KB_MODEL_POLICY", raising=False)
    monkeypatch.delenv("OCTOPUS_KB_VAULTS", raising=False)
    monkeypatch.delenv("OCTOPUS_KB_CONFIG", raising=False)
    calls = []
    remaining = list(responses)

    def fake_transport(method, url, headers, json_body, timeout):
        calls.append(json_body)
        raw = remaining.pop(0)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = text
        if isinstance(payload, dict) and "choices" in payload:
            return 200, payload
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return 200, {"choices": [{"message": {"content": content}}], "model": _SERVED, "usage": {}}

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)
    return calls


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    return vault
