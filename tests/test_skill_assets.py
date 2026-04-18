from pathlib import Path


def test_kb_skill_file_has_required_sections():
    path = Path(__file__).resolve().parent.parent / "skills" / "kb" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "name: kb" in content
    assert "# Operating Procedure" in content
    assert "## Forbidden" in content
    for phrase in (
        "octopus-kb retrieve-bundle",
        "octopus-kb lookup",
        "octopus-kb impacted-pages",
        "octopus-kb neighbors",
        "octopus-kb lint",
    ):
        assert phrase in content, f"missing command reference: {phrase}"


def test_kb_recipes_exist():
    recipes = Path(__file__).resolve().parent.parent / "skills" / "kb" / "recipes"
    for name in ("kb-retrieve.md", "kb-lookup.md", "kb-impact.md"):
        path = recipes / name
        assert path.exists(), f"missing recipe {name}"
        content = path.read_text(encoding="utf-8")
        assert content.strip().startswith("#")
        assert "octopus-kb" in content
