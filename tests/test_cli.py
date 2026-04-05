from pathlib import Path

from octopus_kb_compound.cli import main


def test_cli_lint_missing_vault_returns_error(tmp_path: Path, capsys):
    exit_code = main(["lint", str(tmp_path / "missing")])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "does not exist" in captured.err


def test_cli_suggest_links_missing_page_returns_error(tmp_path: Path, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()

    exit_code = main(["suggest-links", str(vault / "missing.md"), "--vault", str(vault)])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "does not exist" in captured.err
