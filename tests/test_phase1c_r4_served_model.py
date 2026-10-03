"""A response from a different model is not accepted or published."""

from __future__ import annotations

import json

import pytest

from octopus_kb_compound.propose import ProposeRuntimeError, propose_from_raw

from tests.test_phase1c_controls import _proposal, _vault


def test_unexpected_served_model_is_not_published(tmp_path, monkeypatch):
    monkeypatch.delenv("OCTOPUS_KB_MODEL_POLICY", raising=False)
    monkeypatch.delenv("OCTOPUS_KB_CONFIG", raising=False)
    vault, raw = _vault(tmp_path)
    payload = json.loads(_proposal("wrong-model").decode("utf-8"))
    payload["model"] = "unexpected-model"
    import octopus_kb_compound.llm as llm_mod

    def transport(method, url, headers, body, timeout):
        return 200, payload

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: transport)
    with pytest.raises(ProposeRuntimeError, match="served_model_mismatch"):
        propose_from_raw(raw, vault)
    proposals = vault / ".octopus-kb" / "proposals"
    assert not proposals.exists() or list(proposals.glob("*.json")) == []
    interpretations = vault / ".octopus-kb" / "interpretations"
    if interpretations.exists():
        rendered = "\n".join(path.read_text(encoding="utf-8") for path in interpretations.rglob("*.json"))
        assert "wrong-model" not in rendered
