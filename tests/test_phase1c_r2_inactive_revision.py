"""Inactive revisions stay unreachable as vault roots and as locators."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from octopus_kb_compound.adapters.obsidian.store import ObsidianStore
from octopus_kb_compound.cli import main
from octopus_kb_compound.llm import ChatClient, LLMError
from octopus_kb_compound.propose import ProposeRuntimeError, propose_from_raw
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.resolver import VaultRootError

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
    return vault, private

MCP_ROOT = Path(__file__).resolve().parents[1] / "mcp"


@pytest.fixture
def tools():
    sys.path.insert(0, str(MCP_ROOT))
    from octopus_kb_mcp import tools as mcp_tools

    return mcp_tools


@pytest.mark.parametrize(
    ("kind", "old_body", "new_body", "redaction"),
    [
        ("replacement", "OLD_REPLACEMENT_BODY", "NEW_REPLACEMENT_BODY", "none/0.1.0"),
        ("redaction", "OLD_REDACTION_BODY", "NEW_REDACTION_BODY", "strict/0.2.0"),
    ],
)
def test_inactive_revision_is_hidden_after_replacement_and_redaction(
    world, tools, monkeypatch, kind, old_body, new_body, redaction
):
    vault, private = world
    monkeypatch.delenv("OCTOPUS_KB_MODEL_POLICY", raising=False)
    monkeypatch.delenv("OCTOPUS_KB_CONFIG", raising=False)
    placement = f"manuals/{kind}.docx"
    first = _publish(vault, private, old_body, placement=placement, body=old_body)
    second = _publish(
        vault,
        private,
        new_body,
        placement=placement,
        body=new_body,
        parent=first["revision_id"],
        logical_id=first["logical_document_id"],
        redaction=redaction,
    )
    old_dir = vault / ".octopus-kb" / "revisions" / first["revision_id"]
    old_page = f".octopus-kb/revisions/{first['revision_id']}/0000.md"
    active_page = f".octopus-kb/revisions/{second['revision_id']}/0000.md"

    for call in (
        lambda: tools.retrieve_bundle(old_dir, old_body),
        lambda: tools.export_graph(old_dir),
        lambda: tools.lookup(old_dir, old_body),
    ):
        with pytest.raises(VaultRootError) as caught:
            call()
        assert caught.value.reason == "managed_root"

    with pytest.raises(VaultRootError) as caught:
        ObsidianStore(old_dir).list_page_records()
    assert caught.value.reason == "managed_root"

    stderr = io.StringIO()
    stdout = io.StringIO()
    previous_out, previous_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        rc = main(["lookup", old_body, "--vault", str(old_dir), "--json"])
    finally:
        sys.stdout, sys.stderr = previous_out, previous_err
    assert rc == 2
    assert stderr.getvalue().strip() == "managed_root"
    assert old_body not in stdout.getvalue()

    store = ObsidianStore(vault)
    with pytest.raises(VaultRootError) as caught:
        store.read_markdown(old_page)
    assert caught.value.reason == "inactive_revision"
    assert new_body in store.read_markdown(active_page)

    link_dir = vault / "wiki"
    link_dir.mkdir(exist_ok=True)
    alias = link_dir / f"{kind}-old.md"
    alias.symlink_to(old_dir / "0000.md")
    fresh = ObsidianStore(vault)
    assert all(old_body not in page.body for page in fresh.list_page_records())
    assert any(new_body in page.body for page in fresh.list_page_records())
    with pytest.raises(VaultRootError) as caught:
        fresh.read_markdown(alias.relative_to(vault).as_posix())
    assert caught.value.reason == "inactive_revision"

    captured: list[str] = []

    def _capture(self, req):
        captured.append(json.dumps(req.messages))
        raise LLMError("stop-before-network")

    monkeypatch.setattr(ChatClient, "chat", _capture)
    with pytest.raises(VaultRootError) as caught:
        tools.propose(vault, old_page)
    assert caught.value.reason == "inactive_revision"
    assert not captured

    raw = vault / "raw" / f"{kind}-legacy.md"
    raw.parent.mkdir(exist_ok=True)
    raw.write_text(
        "\n".join([
            "---",
            'title: "Legacy Raw"',
            "type: note",
            "lang: en",
            "role: note",
            "---",
            "",
            f"legacy raw stays {kind}",
            "",
        ]),
        encoding="utf-8",
    )
    assert f"legacy raw stays {kind}" in ObsidianStore(vault).read_markdown(raw.relative_to(vault).as_posix())
    with pytest.raises(ProposeRuntimeError, match="stop-before-network"):
        propose_from_raw(raw, vault)
    assert captured
    assert f"legacy raw stays {kind}" in captured[0]
    assert old_body not in captured[0]

    exported = json.dumps(tools.export_graph(vault))
    assert old_body not in exported
    assert new_body in exported
