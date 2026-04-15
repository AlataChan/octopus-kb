from pathlib import Path

from octopus_kb_compound.cli import build_parser, main


def test_cli_parser_includes_existing_baseline_commands():
    parser = build_parser()
    subparsers_action = next(
        action
        for action in parser._actions
        if getattr(action, "dest", None) == "command"
    )
    commands = set(subparsers_action.choices)

    assert {"lint", "suggest-links", "ingest-url", "ingest-file", "vault-summary"} <= commands


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


def test_cli_lint_uses_profile_to_exclude_directories(tmp_path: Path, capsys):
    (tmp_path / ".octopus-kb.yml").write_text("exclude_globs:\n  - output/**\n", encoding="utf-8")
    included = tmp_path / "wiki" / "note.md"
    excluded = tmp_path / "output" / "noise.md"
    included.parent.mkdir(parents=True)
    excluded.parent.mkdir(parents=True)
    included.write_text("---\ntitle: Note\nrole: concept\nlayer: wiki\nsummary: ok\n---\n", encoding="utf-8")
    excluded.write_text("---\ntitle: Noise\nlayer: wiki\n---\n", encoding="utf-8")

    exit_code = main(["lint", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "wiki/note.md" in captured.out
    assert "noise.md" not in captured.out


def test_cli_vault_summary_reports_structure(tmp_path: Path, capsys):
    concept = tmp_path / "wiki" / "concepts" / "RAG.md"
    raw = tmp_path / "raw" / "source.md"
    log = tmp_path / "wiki" / "LOG.md"
    index = tmp_path / "wiki" / "INDEX.md"
    schema = tmp_path / "AGENTS.md"
    for path in (concept, raw, log, index, schema):
        path.parent.mkdir(parents=True, exist_ok=True)
    concept.write_text("---\ntitle: RAG\ntype: concept\nrole: concept\nlayer: wiki\nsummary: RAG\n---\n", encoding="utf-8")
    raw.write_text("---\ntitle: Source\ntype: raw_source\nrole: raw_source\nlayer: source\n---\n", encoding="utf-8")
    log.write_text("---\ntitle: LOG\ntype: meta\nrole: log\nlayer: wiki\nsummary: Log\n---\n", encoding="utf-8")
    index.write_text("---\ntitle: INDEX\ntype: meta\nrole: index\nlayer: wiki\nsummary: Index\n---\n[[RAG]]\n", encoding="utf-8")
    schema.write_text("---\ntitle: AGENTS\ntype: meta\nrole: schema\nlayer: wiki\nsummary: Schema\n---\n", encoding="utf-8")

    exit_code = main(["vault-summary", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "total_pages\t5" in captured.out
    assert "type\tconcept\t1" in captured.out
    assert "type\traw_source\t1" in captured.out
    assert "role\tconcept\t1" in captured.out
    assert "entry\tschema\tpresent" in captured.out
