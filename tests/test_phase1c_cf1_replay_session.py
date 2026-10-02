"""A schema-reminder retry stays on the base interpretation key."""

from __future__ import annotations

import json
from pathlib import Path

from octopus_kb_compound.controls import request_digest
from octopus_kb_compound.propose import propose_from_part

_DIAGNOSTIC = ("provenance", "request_digest", "attempt", "served_model")
_PART = "UNIQUE-PART-BODY"
_SERVED = "qwen2.5:7b-instruct"


def test_non_json_then_valid_replays_with_zero_sends(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    part = {"body": _PART, "part_digest": "ab" * 32}
    calls = _install_transport(monkeypatch, [b"not-json", _proposal("model-id"), _proposal("model-id")])
    propose_from_part(part, vault)
    sent = len(calls)
    assert sent == 2
    stored = _records(vault)
    again = propose_from_part(part, vault)
    assert again.replayed is True
    assert len(calls) == sent
    assert _records(vault) == stored
    assert len(list((vault / ".octopus-kb" / "interpretations" / "index").glob("*.json"))) == 1

    winner = _winner(stored)
    attempts = [record for record in stored if record.get("kind") == "attempt"]
    assert winner["attempt"] == 2
    assert winner["request_digest"] == request_digest(calls[0]["messages"], {"type": "json_object"})
    assert winner["request_digest"] != request_digest(calls[1]["messages"], {"type": "json_object"})
    assert {record["attempt"] for record in attempts} == {1, 2}
    assert attempts[0]["request_digest"] == request_digest(
        calls[attempts[0]["attempt"] - 1]["messages"],
        {"type": "json_object"},
    )
    for record in stored:
        _assert_diagnostic(record, provenance=part["part_digest"])
    for record in attempts:
        assert "response_text" not in record
        rendered = json.dumps(record, sort_keys=True)
        assert _PART not in rendered
        assert "not-json" not in rendered
    assert winner["served_model"] == _SERVED
    assert next(record["served_model"] for record in attempts if record["attempt"] == 2) == _SERVED


def test_consecutive_sessions_on_the_same_part_replay(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    part = {"body": _PART, "part_digest": "cd" * 32}
    calls = _install_transport(monkeypatch, [_proposal("once"), _proposal("once")])
    first = propose_from_part(part, vault)
    second = propose_from_part(part, vault)
    assert second.replayed is True
    assert second.proposal_id == first.proposal_id
    assert len(calls) == 1
    assert len(_records(vault)) == len([record for record in _records(vault) if record.get("kind") == "attempt"]) + 1


def test_same_part_twice_uses_identical_key_inputs(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    part = {"body": _PART, "part_digest": "ef" * 32}
    calls = _install_transport(monkeypatch, [_proposal("key-a"), _proposal("key-b")])
    propose_from_part(part, vault)
    propose_from_part(part, vault)
    assert len(calls) == 1
    winner = _winner(_records(vault))
    assert winner["provenance"] == part["part_digest"]
    assert winner["attempt"] == 1
    assert winner["request_digest"] == request_digest(calls[0]["messages"], {"type": "json_object"})
    assert winner["served_model"] == _SERVED
    indexes = list((vault / ".octopus-kb" / "interpretations" / "index").glob("*.json"))
    assert len(indexes) == 1
    assert indexes[0].stem == winner["key"]


def _assert_diagnostic(record: dict, *, provenance: str) -> None:
    for field in _DIAGNOSTIC:
        assert field in record
    assert record["provenance"] == provenance
    rendered = json.dumps({field: record[field] for field in _DIAGNOSTIC}, sort_keys=True)
    assert _PART not in rendered


def _winner(records: list[dict]) -> dict:
    winners = [record for record in records if record.get("accepted") is True]
    assert len(winners) == 1
    return winners[0]


def _records(vault: Path) -> list[dict]:
    directory = vault / ".octopus-kb" / "interpretations" / "records"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


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
