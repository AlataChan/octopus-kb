from pathlib import Path

from octopus_kb_compound.lint import lint_pages
from octopus_kb_compound.models import PageRecord
from octopus_kb_compound.vault import scan_markdown_files


def test_lint_detects_broken_links():
    pages = [
        PageRecord(
            path="wiki/concepts/Agent设计模式.md",
            title="Agent设计模式",
            body="See [[Missing Page]].",
            frontmatter={"role": "concept", "layer": "wiki", "tags": ["AI/Agent"]},
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "BROKEN_LINK" for f in findings)


def test_lint_detects_orphan_pages():
    pages = [
        PageRecord(
            path="wiki/concepts/Agent设计模式.md",
            title="Agent设计模式",
            body="",
            frontmatter={"role": "concept", "layer": "wiki", "tags": ["AI/Agent"], "summary": "Agent design patterns."},
        ),
        PageRecord(
            path="wiki/INDEX.md",
            title="INDEX",
            body="",
            frontmatter={"role": "index", "layer": "wiki", "tags": ["AI/Wiki"], "summary": "Entry point."},
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "ORPHAN_PAGE" and f.path.endswith("Agent设计模式.md") for f in findings)


def test_lint_detects_missing_summary_and_role():
    pages = [
        PageRecord(
            path="wiki/concepts/RAG与知识增强.md",
            title="RAG与知识增强",
            body="",
            frontmatter={"layer": "wiki", "tags": ["AI/LLM/RAG"]},
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "MISSING_ROLE" for f in findings)
    assert any(f.code == "MISSING_SUMMARY" for f in findings)


def test_lint_resolves_alias_links_without_false_broken_or_orphan():
    pages = [
        PageRecord(
            path="wiki/concepts/RAG and Knowledge Augmentation.md",
            title="RAG and Knowledge Augmentation",
            body="",
            frontmatter={"role": "concept", "layer": "wiki", "summary": "RAG overview.", "aliases": ["RAG"]},
        ),
        PageRecord(
            path="wiki/INDEX.md",
            title="INDEX",
            body="See [[RAG]].",
            frontmatter={"role": "index", "layer": "wiki", "summary": "Entry point."},
        ),
    ]

    findings = lint_pages(pages)

    assert findings == []


def test_lint_reports_alias_collisions():
    pages = [
        PageRecord(
            path="wiki/entities/PageA.md",
            title="Page A",
            body="",
            frontmatter={"role": "entity", "layer": "wiki", "summary": "A", "aliases": ["Shared Alias"]},
        ),
        PageRecord(
            path="wiki/entities/PageB.md",
            title="Page B",
            body="",
            frontmatter={"role": "entity", "layer": "wiki", "summary": "B", "aliases": ["Shared Alias"]},
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "ALIAS_COLLISION" for f in findings)


def test_example_vault_has_no_lint_findings():
    repo_root = Path(__file__).resolve().parents[1]
    pages = scan_markdown_files(repo_root / "examples" / "minimal-vault")

    findings = lint_pages(pages)

    assert findings == []
