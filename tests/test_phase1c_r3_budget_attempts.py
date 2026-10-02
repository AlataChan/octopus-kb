"""Each HTTP attempt is reserved, settled, and able to block the next send."""

from __future__ import annotations

import json

import pytest

from octopus_kb_compound.controls import RunBudget
from octopus_kb_compound.propose import ProposeDeferred, ProposeRuntimeError, propose_from_raw

from tests.test_phase1c_controls import _proposal, _vault, _wide_budget


def _limits(**overrides) -> dict:
    limits = {
        "calls": 8,
        "input_tokens": 50_000_000,
        "output_tokens": 200_000,
        "images": 4,
        "gpu_seconds": 0,
    }
    limits.update(overrides)
    return limits


def _allow_default_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_KB_CONFIG", raising=False)
    monkeypatch.setenv(
        "OCTOPUS_KB_MODEL_POLICY",
        json.dumps({
            "endpoints": [{
                "base_url": "http://localhost:11434/v1",
                "model": "qwen2.5:7b-instruct",
                "text_f4": "enforce",
                "accounting": {
                    "byte_bounded": True,
                    "per_message_overhead": 8,
                    "per_request_overhead": 16,
                    "image_cost": 1105,
                    "max_image_dimension": 2048,
                },
            }],
            "budget": _wide_budget(),
        }),
    )


def _script(monkeypatch, steps: list[tuple[int, dict]], budget: RunBudget) -> list:
    import octopus_kb_compound.llm as llm_mod
    import octopus_kb_compound.propose as propose_mod

    calls: list = []
    remaining = list(steps)

    def transport(method, url, headers, body, timeout):
        calls.append(body)
        status, payload = remaining.pop(0)
        return status, payload

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: transport)
    monkeypatch.setattr(llm_mod, "_sleep", lambda _delay: None)
    monkeypatch.setattr(propose_mod, "load_budget", lambda: budget)
    return calls


def _ok(proposal_id: str, usage: dict | None) -> dict:
    payload = json.loads(_proposal(proposal_id).decode("utf-8"))
    if usage is not None:
        payload["usage"] = usage
    return payload


def test_calls_limit_one_starts_at_zero_and_does_not_retry(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = RunBudget("kb.propose", _limits(calls=1))
    assert budget.used.calls == 0
    calls = _script(
        monkeypatch,
        [
            (429, {"error": {"message": "slow"}}),
            (200, _ok("should-not-run", {"prompt_tokens": 10, "completion_tokens": 1})),
        ],
        budget,
    )
    with pytest.raises(ProposeRuntimeError):
        propose_from_raw(raw, vault)
    assert len(calls) == 1
    assert budget.used.calls == 1


def test_retry_stops_when_the_call_budget_is_spent(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = RunBudget("kb.propose", _limits(calls=2))
    calls = _script(
        monkeypatch,
        [
            (429, {"error": {"message": "slow"}}),
            (429, {"error": {"message": "slow"}}),
            (200, _ok("late-success", {"prompt_tokens": 10, "completion_tokens": 1})),
        ],
        budget,
    )
    with pytest.raises(ProposeRuntimeError):
        propose_from_raw(raw, vault)
    assert len(calls) == 2
    assert budget.used.calls == 2


def test_provider_overrun_is_settled_and_blocks_the_next_send(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = RunBudget("kb.propose", _limits(calls=4))
    calls = _script(
        monkeypatch,
        [(200, _ok("overrun-1", {"prompt_tokens": 99999, "completion_tokens": 1}))],
        budget,
    )
    propose_from_raw(raw, vault)
    assert len(calls) == 1
    assert budget.used.input_tokens == 99999
    assert budget.blocked is True
    assert budget.events[-1]["event"] == "overrun"

    other = vault / "raw" / "other.md"
    other.write_text(raw.read_text(encoding="utf-8").replace("Body.", "Other body."), encoding="utf-8")
    with pytest.raises(ProposeDeferred) as caught:
        propose_from_raw(other, vault)
    assert caught.value.reason == "budget_exhausted"
    assert len(calls) == 1
