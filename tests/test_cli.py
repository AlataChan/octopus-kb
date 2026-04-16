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

    assert {
        "lint",
        "suggest-links",
        "ingest-url",
        "ingest-file",
        "vault-summary",
        "impacted-pages",
        "plan-maintenance",
        "inspect-vault",
        "normalize-vault",
        "export-graph",
    } <= commands


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


def test_cli_impacted_pages_reports_related_pages(tmp_path: Path, capsys):
    concept = tmp_path / "wiki" / "concepts" / "RAG.md"
    entity = tmp_path / "wiki" / "entities" / "Vector Store.md"
    index = tmp_path / "wiki" / "INDEX.md"
    log = tmp_path / "wiki" / "LOG.md"
    for path in (concept, entity, index, log):
        path.parent.mkdir(parents=True, exist_ok=True)
    concept.write_text(
        "---\ntitle: RAG\nrole: concept\nlayer: wiki\nsummary: RAG\nrelated_entities:\n  - Vector Store\n---\n[[Vector Store]]\n",
        encoding="utf-8",
    )
    entity.write_text("---\ntitle: Vector Store\nrole: entity\nlayer: wiki\nsummary: Vector\n---\n", encoding="utf-8")
    index.write_text("---\ntitle: INDEX\nrole: index\nlayer: wiki\nsummary: Index\n---\n[[RAG]]\n", encoding="utf-8")
    log.write_text("---\ntitle: LOG\nrole: log\nlayer: wiki\nsummary: Log\n---\n", encoding="utf-8")

    exit_code = main(["impacted-pages", str(concept), "--vault", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "wiki/concepts/RAG.md" in captured.out
    assert "wiki/INDEX.md" in captured.out
    assert "wiki/LOG.md" in captured.out
    assert "wiki/entities/Vector Store.md" in captured.out


def test_cli_plan_maintenance_reports_actions(tmp_path: Path, capsys):
    raw = tmp_path / "raw" / "source.md"
    index = tmp_path / "wiki" / "INDEX.md"
    log = tmp_path / "wiki" / "LOG.md"
    for path in (raw, index, log):
        path.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("---\ntitle: Source\nrole: raw_source\nlayer: source\n---\n", encoding="utf-8")
    index.write_text("---\ntitle: INDEX\nrole: index\nlayer: wiki\nsummary: Index\n---\n", encoding="utf-8")
    log.write_text("---\ntitle: LOG\nrole: log\nlayer: wiki\nsummary: Log\n---\n", encoding="utf-8")

    exit_code = main(["plan-maintenance", str(raw), "--vault", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "changed_page\traw/source.md" in captured.out
    assert "action\tupdate" in captured.out


def test_cli_inspect_vault_reports_missing_files(tmp_path: Path, capsys):
    (tmp_path / "note.md").write_text("# Loose note\n", encoding="utf-8")

    exit_code = main(["inspect-vault", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "missing_file\tAGENTS.md" in captured.out
    assert "missing_frontmatter\tnote.md" in captured.out


def test_cli_export_graph_writes_artifacts(tmp_path: Path):
    vault = tmp_path / "vault"
    page = vault / "wiki" / "INDEX.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: INDEX\nrole: index\nlayer: wiki\n---\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    exit_code = main(["export-graph", str(vault), "--out", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "nodes.json").exists()
    assert (out_dir / "edges.json").exists()
