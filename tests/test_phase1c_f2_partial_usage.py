"""Unknown usage dimensions keep their reservation on the real run budget."""

from __future__ import annotations

from octopus_kb_compound.controls import Reservation, RunBudget
from octopus_kb_compound.propose import propose_from_raw

from tests.test_phase1c_r3_budget_attempts import _allow_default_endpoint, _limits, _ok, _script
from tests.test_phase1c_controls import _vault


def _send(monkeypatch, vault, raw, budget, usage):
    calls = _script(monkeypatch, [(200, _ok("partial", usage))], budget)
    propose_from_raw(raw, vault)
    assert len(calls) == 1
    return budget


def test_missing_input_usage_keeps_the_input_reservation(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = _send(
        monkeypatch,
        vault,
        raw,
        RunBudget("kb.propose", _limits()),
        {"completion_tokens": 1},
    )
    assert budget.used.input_tokens > 0
    assert budget.used.output_tokens == 1
    kept = budget.used.input_tokens
    budget.limits["input_tokens"] = kept
    assert budget.reserve(Reservation(calls=1, input_tokens=kept, output_tokens=0)) == "input_tokens"


def test_missing_output_usage_keeps_the_output_reservation(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = _send(
        monkeypatch,
        vault,
        raw,
        RunBudget("kb.propose", _limits(output_tokens=4000)),
        {"prompt_tokens": 1},
    )
    assert budget.used.output_tokens == 4000
    assert budget.used.input_tokens == 1
    assert budget.reserve(Reservation(calls=1, input_tokens=0, output_tokens=4000)) == "output_tokens"


def test_absent_usage_keeps_both_reservations(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = _send(monkeypatch, vault, raw, RunBudget("kb.propose", _limits()), None)
    assert budget.used.input_tokens > 0
    assert budget.used.output_tokens == 4000
    assert budget.blocked is False


def test_overrun_usage_is_kept_and_blocks_the_run(tmp_path, monkeypatch):
    _allow_default_endpoint(monkeypatch)
    vault, raw = _vault(tmp_path)
    budget = _send(
        monkeypatch,
        vault,
        raw,
        RunBudget("kb.propose", _limits()),
        {"prompt_tokens": 99999, "completion_tokens": 1},
    )
    assert budget.used.input_tokens == 99999
    assert budget.blocked is True
    assert budget.events[-1]["event"] == "overrun"
