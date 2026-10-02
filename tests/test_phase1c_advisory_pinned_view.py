"""propose reads managed bytes and retrieval context from one active view."""

from __future__ import annotations

import json

import pytest

from octopus_kb_compound import active as active_mod
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.llm import ChatClient, LLMError
from octopus_kb_compound.propose import ProposeRuntimeError, propose_from_raw

from tests.test_phase1c_envelope import FIXTURE, LABEL, TENANT, VAULT_ID, _publish
from tests.test_phase1c_r3_budget_attempts import _allow_default_endpoint


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
    _allow_default_endpoint(monkeypatch)
    return vault, private


def test_managed_source_and_retrieval_context_share_one_view(world, monkeypatch):
    vault, private = world
    old = _publish(vault, private, "old", placement="manuals/pin.docx", body="OLD_PINNED_BODY")
    logical = old["logical_document_id"]
    title = "manuals/pin.docx:0:OLD_PINNED_BODY"
    concept = vault / "wiki" / "pin-concept.md"
    concept.parent.mkdir()
    concept.write_text(
        "\n".join([
            "---",
            'title: "Pin"',
            "type: note",
            "role: concept",
            "---",
            "",
            title,
            "",
        ]),
        encoding="utf-8",
    )
    state = {"done": False}

    def hook(root, _pointers):
        if state["done"]:
            return
        state["done"] = True
        _publish(
            vault,
            private,
            "new",
            placement="manuals/pin.docx",
            body="NEW_PINNED_BODY",
            parent=old["revision_id"],
            logical_id=logical,
        )

    captured: list[str] = []

    def chat(self, req, **_kwargs):
        captured.append(req.messages[0]["content"])
        raise LLMError("stop-before-network")

    monkeypatch.setattr(ChatClient, "chat", chat)
    active_mod.AFTER_PIN = hook
    page = vault / ".octopus-kb" / "revisions" / old["revision_id"] / "0000.md"
    try:
        with pytest.raises(ProposeRuntimeError, match="stop-before-network"):
            propose_from_raw(page, vault)
    finally:
        active_mod.AFTER_PIN = None
    assert active_mod.AFTER_PIN is None
    new_id = (vault / ".octopus-kb" / "active" / logical).read_text(encoding="utf-8").strip()
    assert new_id != old["revision_id"]
    prompt = captured[0]
    assert old["revision_id"] in prompt
    assert "OLD_PINNED_BODY" in prompt
    assert new_id not in prompt
    assert "NEW_PINNED_BODY" not in prompt
