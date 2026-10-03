"""MCP server mode warns and refuses an unset vault map."""

from __future__ import annotations

import pytest

from octopus_kb_compound.resolver import require_mcp_mapping


def test_unmapped_mcp_refuses_unless_explicitly_allowed(monkeypatch):
    monkeypatch.delenv("OCTOPUS_KB_VAULTS", raising=False)
    monkeypatch.delenv("OCTOPUS_KB_ALLOW_UNMAPPED", raising=False)
    with pytest.warns(RuntimeWarning, match="refusing to serve"):
        with pytest.raises(SystemExit) as caught:
            require_mcp_mapping()
    assert caught.value.code == 2

    monkeypatch.setenv("OCTOPUS_KB_ALLOW_UNMAPPED", "1")
    with pytest.warns(RuntimeWarning, match="ALLOW_UNMAPPED=1"):
        require_mcp_mapping()


def test_mapped_mcp_starts_without_the_allow_flag(monkeypatch):
    monkeypatch.setenv(
        "OCTOPUS_KB_VAULTS",
        '{"vault-1": {"root": "/tmp/vault", "allowed_access_labels": ["internal"]}}',
    )
    monkeypatch.delenv("OCTOPUS_KB_ALLOW_UNMAPPED", raising=False)
    require_mcp_mapping()
