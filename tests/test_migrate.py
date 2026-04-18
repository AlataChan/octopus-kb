from pathlib import Path

import pytest

from octopus_kb_compound.migrate import inspect_vault_for_migration, normalize_vault


def _seed_vault(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "wiki").mkdir()
    (root / "wiki" / "existing.md").write_text("# Existing\n", encoding="utf-8")


def test_migrate_vault_dry_run_reports_missing_required_entry_files(tmp_path: Path):
    (tmp_path / "note.md").write_text("# Loose note\nBody\n", encoding="utf-8")

    report = inspect_vault_for_migration(tmp_path)

    assert report.missing_files == ["AGENTS.md", "wiki/INDEX.md", "wiki/LOG.md"]
    assert report.pages_missing_frontmatter == ["note.md"]


def test_normalize_vault_apply_writes_to_staging_without_touching_source(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("# Loose note\nBody\n", encoding="utf-8")

    report = normalize_vault(tmp_path, apply=True)

    assert report.staging_dir is not None
    staged_note = Path(report.staging_dir) / "note.md"
    assert staged_note.exists()
    assert staged_note.read_text(encoding="utf-8").startswith("---\n")
    assert note.read_text(encoding="utf-8") == "# Loose note\nBody\n"


def test_normalize_in_place_rolls_back_created_required_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    import octopus_kb_compound.migrate as migrate_module
    real = migrate_module._replace_staged_file
    calls = {"count": 0}

    def failing(tmp, target):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise OSError("simulated commit failure")
        real(tmp, target)

    monkeypatch.setattr(migrate_module, "_replace_staged_file", failing)

    with pytest.raises(OSError):
        normalize_vault(vault, apply=True, in_place=True)

    assert not (vault / "AGENTS.md").exists(), "created AGENTS.md must be rolled back"
    assert not (vault / "wiki" / "INDEX.md").exists()
    assert not (vault / "wiki" / "LOG.md").exists()


def test_normalize_in_place_rolls_back_modified_existing_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    (vault / "AGENTS.md").write_text("# Pre-existing schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Pre-existing index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Pre-existing log\n", encoding="utf-8")

    before = {
        rel: (vault / rel).read_text(encoding="utf-8")
        for rel in ("wiki/existing.md", "AGENTS.md", "wiki/INDEX.md", "wiki/LOG.md")
    }

    import octopus_kb_compound.migrate as migrate_module
    real = migrate_module._replace_staged_file
    calls = {"count": 0}

    def failing(tmp, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated commit failure")
        real(tmp, target)

    monkeypatch.setattr(migrate_module, "_replace_staged_file", failing)

    with pytest.raises(OSError):
        normalize_vault(vault, apply=True, in_place=True)

    for rel, expected in before.items():
        assert (vault / rel).read_text(encoding="utf-8") == expected, f"{rel} must be restored"


def test_normalize_in_place_cleans_up_staging_files_on_rollback(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    (vault / "AGENTS.md").write_text("# Pre-existing\n", encoding="utf-8")

    import octopus_kb_compound.migrate as migrate_module
    real = migrate_module._replace_staged_file
    calls = {"count": 0}

    def failing(tmp, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated commit failure")
        real(tmp, target)

    monkeypatch.setattr(migrate_module, "_replace_staged_file", failing)

    with pytest.raises(OSError):
        normalize_vault(vault, apply=True, in_place=True)

    stray = [p for p in vault.rglob("*.octopus-tmp")]
    assert stray == [], f"no staged .octopus-tmp files should remain, found: {stray}"


def test_inspect_vault_reports_malformed_frontmatter_as_parse_failure(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "broken.md").write_text(
        '---\ntitle: "broken"\nrole: concept\n# no closing fence\nbody here\n',
        encoding="utf-8",
    )
    from octopus_kb_compound.migrate import inspect_vault_for_migration
    report = inspect_vault_for_migration(vault)
    assert "wiki/broken.md" in report.parse_failures
    assert "wiki/broken.md" not in report.pages_missing_frontmatter
