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


def test_lint_reports_duplicate_canonical_pages():
    pages = [
        PageRecord(
            path="wiki/concepts/RAG.md",
            title="RAG",
            body="",
            frontmatter={
                "title": "RAG",
                "role": "concept",
                "layer": "wiki",
                "summary": "RAG overview.",
                "canonical_name": "Retrieval Augmented Generation",
            },
        ),
        PageRecord(
            path="wiki/concepts/Retrieval Augmented Generation.md",
            title="Retrieval Augmented Generation",
            body="",
            frontmatter={
                "title": "Retrieval Augmented Generation",
                "role": "concept",
                "layer": "wiki",
                "summary": "Duplicate overview.",
                "source_of_truth": "canonical",
            },
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "DUPLICATE_CANONICAL_PAGE" for f in findings)


def test_lint_reports_unresolved_frontmatter_alias():
    pages = [
        PageRecord(
            path="wiki/entities/Vector Store.md",
            title="Vector Store",
            body="",
            frontmatter={
                "title": "Vector Store",
                "role": "entity",
                "layer": "wiki",
                "summary": "Vector store.",
                "aliases": ["!!!"],
            },
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "UNRESOLVED_ALIAS" for f in findings)


def test_lint_reports_canonical_alias_collision():
    pages = [
        PageRecord(
            path="wiki/entities/Vector Store.md",
            title="Vector Store",
            body="",
            frontmatter={
                "title": "Vector Store",
                "role": "entity",
                "layer": "wiki",
                "summary": "Vector store.",
                "canonical_name": "Vector Store",
                "aliases": ["Chunking"],
            },
        ),
        PageRecord(
            path="wiki/entities/Chunking.md",
            title="Chunking",
            body="[[Vector Store]]",
            frontmatter={
                "title": "Chunking",
                "role": "entity",
                "layer": "wiki",
                "summary": "Chunking.",
                "canonical_name": "Chunking",
            },
        ),
    ]

    findings = lint_pages(pages)

    assert any(f.code == "CANONICAL_ALIAS_COLLISION" for f in findings)


def test_lint_resolves_filename_and_relative_path_links():
    pages = [
        PageRecord(
            path="Agent相关论文/REACT_ SYNERGIZING REASONING AND ACTING IN LANGUAGE MODELS-2023.3.md",
            title="ReAct Paper",
            body="",
            frontmatter={"role": "raw_source", "layer": "source", "summary": "ReAct source."},
        ),
        PageRecord(
            path="wiki/concepts/Agent设计模式.md",
            title="Agent设计模式",
            body="[[Agent相关论文/REACT_ SYNERGIZING REASONING AND ACTING IN LANGUAGE MODELS-2023.3.md]]",
            frontmatter={"role": "concept", "layer": "wiki", "summary": "Agent patterns."},
        ),
        PageRecord(
            path="wiki/INDEX.md",
            title="INDEX",
            body="[[Agent设计模式]]",
            frontmatter={"role": "index", "layer": "wiki", "summary": "Index."},
        ),
    ]

    findings = lint_pages(pages)

    assert findings == []


def test_lint_ignores_folderish_and_code_block_pseudo_links():
    pages = [
        PageRecord(
            path="wiki/concepts/RAG与知识增强.md",
            title="RAG与知识增强",
            body=(
                "See [[output/reports/]].\n\n"
                "tokens = [[\"to\"]]\n\n"
                "embeddings = [[instruction, sentence]]\n\n"
                "```python\n"
                "weights = [[0.12, 0.45]]\n"
                "```\n"
            ),
            frontmatter={"role": "concept", "layer": "wiki", "summary": "RAG."},
        ),
    ]

    findings = lint_pages(pages)

    assert findings == [f for f in findings if f.code == "ORPHAN_PAGE"]


def test_example_vault_has_no_lint_findings():
    repo_root = Path(__file__).resolve().parents[1]
    pages = scan_markdown_files(repo_root / "examples" / "minimal-vault")

    findings = lint_pages(pages)

    assert findings == []
