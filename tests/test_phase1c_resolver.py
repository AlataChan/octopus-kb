"""Tenant-root checks on every filesystem-facing tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from octopus_kb_compound.cli import main
from octopus_kb_compound.resolver import VaultRootError


def _table(root: Path) -> str:
    return json.dumps({
        "vault-1": {"root": str(root), "allowed_access_labels": ["internal"]},
    })


def _raise_outside(call) -> None:
    with pytest.raises(VaultRootError) as caught:
        call()
    assert caught.value.reason == "outside_root"


def test_unset_vaults_keep_the_given_path_and_refuse_escape(tmp_path, monkeypatch):
    monkeypatch.delenv("OCTOPUS_KB_VAULTS", raising=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
    from octopus_kb_mcp.tools import export_graph, propose

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("---\ntitle: Note\ntype: note\nlang: en\nrole: note\n---\n", encoding="utf-8")
    assert export_graph(vault)["nodes"]

    outside = tmp_path / "other"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    _raise_outside(lambda: propose(vault, str(secret)))

    link = vault / "escape.md"
    link.symlink_to(secret)
    _raise_outside(lambda: propose(vault, "escape.md"))


def test_every_tool_refuses_an_outside_root_and_a_symlink(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    inside = allowed / "vault"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()
    (inside / "wiki").mkdir()
    (inside / "raw").mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("OCTOPUS_KB_VAULTS", _table(allowed))
    monkeypatch.setenv("OCTOPUS_KB_TENANT", "tenant-a")
    escape = allowed / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    page_escape = inside / "wiki" / "leak.md"
    page_escape.symlink_to(outside / "secret.md")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
    from octopus_kb_mcp import tools

    tool_calls = [
        lambda: tools.export_graph(outside),
        lambda: tools.export_graph(escape),
        lambda: tools.retrieve_bundle(outside, "query"),
        lambda: tools.retrieve_bundle(escape, "query"),
        lambda: tools.ingest(outside, "# Title\n\nBody"),
        lambda: tools.ingest(escape, "# Title\n\nBody"),
        lambda: tools.neighbors(outside, "wiki/index.md"),
        lambda: tools.neighbors(escape, "wiki/index.md"),
        lambda: tools.lookup(outside, "term"),
        lambda: tools.lookup(escape, "term"),
        lambda: tools.propose(outside, "raw/a.md"),
        lambda: tools.propose(inside, "wiki/leak.md"),
        lambda: tools.validate(outside, "proposal.json"),
        lambda: tools.healthcheck(outside),
        lambda: tools.healthcheck(escape),
    ]
    for call in tool_calls:
        _raise_outside(call)

    commands = [
        ["lint", str(outside)],
        ["lint", str(escape)],
        ["lookup", "term", "--vault", str(outside)],
        ["retrieve-bundle", "query", "--vault", str(escape)],
        ["neighbors", "wiki/leak.md", "--vault", str(inside)],
        ["vault-summary", str(outside)],
        ["inspect-vault", str(outside)],
        ["export-graph", str(outside), "--out", str(tmp_path / "out")],
        ["inbox", "--vault", str(outside), "--list"],
        ["suggest-links", str(page_escape), "--vault", str(inside)],
        ["propose", str(outside / "secret.md"), "--vault", str(inside)],
        ["validate", str(outside / "secret.md"), "--vault", str(inside)],
    ]
    for argv in commands:
        stderr = __import__("io").StringIO()
        previous = sys.stderr
        sys.stderr = stderr
        try:
            rc = main(argv)
        finally:
            sys.stderr = previous
        assert rc == 2, argv
        assert "outside_root" in stderr.getvalue(), argv
