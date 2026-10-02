"""Control-contract vectors and propose budget, policy, and replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octopus_kb_compound.controls import (
    Policy,
    Reservation,
    RunBudget,
    accounted_input,
    scan_text,
)
from octopus_kb_compound.jsoncanon import canonical_json
from octopus_kb_compound.propose import ProposeDeferred, propose_from_part, propose_from_raw

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "phase1c" / "model_controls"
_ACCOUNTING = {
    "byte_bounded": True,
    "per_message_overhead": 8,
    "per_request_overhead": 16,
    "image_cost": 1105,
    "max_image_dimension": 2048,
}


def test_control_vectors_match_the_parser_fixtures():
    for case in json.loads((FIXTURES / "canonical.json").read_text(encoding="utf-8"))["cases"]:
        assert canonical_json(case["value"]) == case["canonical"]

    for case in json.loads((FIXTURES / "policy.json").read_text(encoding="utf-8"))["cases"]:
        if case["name"] == "unlisted_endpoint":
            policy = Policy({"endpoints": [{
                "name": "known",
                "base_url": "https://allowed.example/v1",
                "model": "m",
                "text_f4": "observe",
                "accounting": _ACCOUNTING,
            }]})
            decision = policy.apply(
                endpoint=case["endpoint"],
                model=case["model"],
                texts=case["texts"],
                endpoint_name=case["endpoint_name"],
            )
            assert decision.disposition == case["expect"]
            continue
        text, hits = scan_text(case["texts"][0], case["text_f4"])
        assert text == case["expect_text"]
        assert hits == case["expect_hits"]

    document = json.loads((FIXTURES / "budget.json").read_text(encoding="utf-8"))
    accounting = dict(_ACCOUNTING)
    accounting.update(document["accounting"])
    for case in document["cases"]:
        assert accounted_input(case["texts"], case["schema"], case["images"], accounting) == case["expect_input"]
    limit = document["boundaries"]["limit"]
    assert _fit(document["boundaries"]["below"], limit) is None
    assert _fit(document["boundaries"]["at"], limit) is None
    assert _fit(document["boundaries"]["above"], limit) == "input_tokens"


def test_each_limit_is_checked_on_its_own():
    base = {"calls": 5, "input_tokens": 100, "output_tokens": 10, "images": 1, "gpu_seconds": 0}
    assert RunBudget("kb.propose", {**base, "calls": 1}).reserve(
        Reservation(calls=2, input_tokens=1, output_tokens=1)
    ) == "calls"
    assert RunBudget("kb.propose", dict(base)).reserve(Reservation(calls=1, input_tokens=101, output_tokens=1)) == "input_tokens"
    assert RunBudget("kb.propose", dict(base)).reserve(Reservation(calls=1, input_tokens=1, output_tokens=11)) == "output_tokens"
    assert RunBudget("kb.propose", dict(base)).reserve(
        Reservation(calls=1, input_tokens=1, output_tokens=1, images=2)
    ) == "images"


def test_retry_is_budgeted_on_its_own_and_a_larger_reminder_is_not_sent(tmp_path, monkeypatch):
    vault, raw = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [b"not-json", b'{"id":"x"}'])
    from octopus_kb_compound.controls import RunBudget

    original = RunBudget.reserve

    def reserve(self, item):
        if "pinned" not in self.limits:
            self.limits["input_tokens"] = item.input_tokens
            self.limits["pinned"] = True
        return original(self, item)

    monkeypatch.setattr(RunBudget, "reserve", reserve)
    with pytest.raises(ProposeDeferred) as caught:
        propose_from_raw(raw, vault)
    assert caught.value.reason == "oversized_prompt"
    assert len(calls) == 1
    assert len(calls[0]["messages"]) == 1


def test_denied_policy_and_missing_accounting_make_no_calls(tmp_path, monkeypatch):
    vault, raw = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [b"{}"])
    monkeypatch.setenv("OCTOPUS_KB_MODEL_POLICY", json.dumps({
        "endpoints": [{
            "base_url": "https://denied.example/v1",
            "model": "other",
            "text_f4": "enforce",
            "accounting": _ACCOUNTING,
        }],
        "budget": _wide_budget(),
    }))
    with pytest.raises(ProposeDeferred) as denied:
        propose_from_raw(raw, vault)
    assert denied.value.reason == "policy_denied"
    assert calls == []

    monkeypatch.setenv("OCTOPUS_KB_MODEL_POLICY", json.dumps({
        "endpoints": [{
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b-instruct",
            "text_f4": "enforce",
        }],
        "budget": _wide_budget(),
    }))
    with pytest.raises(ProposeDeferred) as missing:
        propose_from_raw(raw, vault)
    assert missing.value.reason == "accounting_unavailable"
    assert calls == []


def test_replay_hit_makes_no_second_call(tmp_path, monkeypatch):
    vault, raw = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [_proposal("replay-1")])
    propose_from_raw(raw, vault)
    (vault / ".octopus-kb" / "proposals" / "replay-1.json").unlink()
    propose_from_raw(raw, vault)
    assert len(calls) == 1


def test_replay_with_the_stored_file_still_present_is_idempotent(tmp_path, monkeypatch):
    vault, raw = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [_proposal("replay-kept")])
    first = propose_from_raw(raw, vault)
    stored = vault / ".octopus-kb" / "proposals" / "replay-kept.json"
    before = stored.read_bytes()
    second = propose_from_raw(raw, vault)
    assert len(calls) == 1
    assert second.replayed is True
    assert second.to_dict()["replayed"] is True
    assert second.path == first.path
    assert stored.read_bytes() == before


def test_replay_with_a_different_stored_body_is_a_collision(tmp_path, monkeypatch):
    from octopus_kb_compound.proposals import ProposalCollisionError

    vault, raw = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [_proposal("replay-clash")])
    propose_from_raw(raw, vault)
    stored = vault / ".octopus-kb" / "proposals" / "replay-clash.json"
    body = json.loads(stored.read_text(encoding="utf-8"))
    body["operations"][0]["entry"] = "2026-04-18: replaced"
    stored.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ProposalCollisionError):
        propose_from_raw(raw, vault)
    assert len(calls) == 1
    assert json.loads(stored.read_text(encoding="utf-8"))["operations"][0]["entry"] == "2026-04-18: replaced"


def test_large_legacy_raw_is_deferred(tmp_path, monkeypatch):
    vault, raw = _vault(tmp_path)
    raw.write_text("x" * 200_000, encoding="utf-8")
    calls = _install_transport(monkeypatch, [_proposal("never")])
    monkeypatch.setenv("OCTOPUS_KB_MODEL_POLICY", json.dumps({
        "endpoints": [{
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b-instruct",
            "text_f4": "enforce",
            "accounting": _ACCOUNTING,
        }],
        "budget": {**_wide_budget(), "input_tokens": 1000},
    }))
    with pytest.raises(ProposeDeferred) as caught:
        propose_from_raw(raw, vault)
    assert caught.value.reason == "oversized_prompt"
    assert caught.value.measured_size > 1000
    assert calls == []
    stored = json.loads(next((vault / ".octopus-kb" / "inbox").glob("*.json")).read_text(encoding="utf-8"))
    assert stored["reason"] == "oversized_prompt"
    assert stored["measured_size"] == caught.value.measured_size


def test_envelope_parts_are_proposed_one_at_a_time(tmp_path, monkeypatch):
    vault, _raw = _vault(tmp_path)
    calls = _install_transport(monkeypatch, [_proposal("part-a"), _proposal("part-b")])
    propose_from_part({"body": "ONLY-PART-A", "part_digest": "a" * 64}, vault)
    propose_from_part({"body": "ONLY-PART-B", "part_digest": "b" * 64}, vault)
    first = calls[0]["messages"][0]["content"]
    second = calls[1]["messages"][0]["content"]
    assert "ONLY-PART-A" in first and "ONLY-PART-B" not in first
    assert "ONLY-PART-B" in second and "ONLY-PART-A" not in second


def _fit(amount: int, limit: int) -> str | None:
    budget = RunBudget(
        "kb.propose",
        {"calls": 5, "input_tokens": limit, "output_tokens": 100, "images": 5, "gpu_seconds": 0},
    )
    return budget.reserve(Reservation(calls=1, input_tokens=amount, output_tokens=0, images=0))


def _wide_budget() -> dict:
    return {"family": "kb.propose", "calls": 8, "input_tokens": 50_000_000, "output_tokens": 200_000, "images": 4, "gpu_seconds": 0}


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
    body = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "model": "qwen2.5:7b-instruct",
        "usage": {},
    }
    return json.dumps(body).encode("utf-8")


def _install_transport(monkeypatch, responses: list[bytes]):
    import octopus_kb_compound.llm as llm_mod

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
        return 200, {"choices": [{"message": {"content": content}}], "model": "qwen2.5:7b-instruct", "usage": {}}

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)
    return calls


def _vault(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    raw = vault / "raw" / "demo.md"
    raw.write_text(
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\nlayer: source\ntags: []\n---\nBody.\n',
        encoding="utf-8",
    )
    return vault, raw
