from octopus_kb_compound.frontmatter import parse_document, render_frontmatter
from octopus_kb_compound.models import PageMeta


def test_render_frontmatter_writes_role_layer_and_workflow():
    meta = PageMeta(
        title="LLM wiki",
        page_type="meta",
        lang="en",
        tags=["AI/Wiki", "AI/Wiki/Architecture"],
        role="schema",
        layer="wiki",
        workflow=["ingest", "lint", "query"],
        summary="Persistent wiki layer.",
    )

    frontmatter = render_frontmatter(meta)

    assert 'title: "LLM wiki"' in frontmatter
    assert "type: meta" in frontmatter
    assert "role: schema" in frontmatter
    assert "layer: wiki" in frontmatter
    assert "workflow:" in frontmatter
    assert "  - ingest" in frontmatter
    assert "  - lint" in frontmatter
    assert "  - query" in frontmatter


def test_render_frontmatter_writes_empty_tags_as_empty_list():
    meta = PageMeta(
        title="Loose Note",
        page_type="raw_source",
        lang="en",
        tags=[],
    )

    frontmatter = render_frontmatter(meta)

    assert "tags: []" in frontmatter


def test_render_frontmatter_writes_optional_metadata():
    meta = PageMeta(
        title="Agent Notes",
        page_type="concept",
        lang="zh",
        tags=["AI/Agent"],
        authors=["Alice Example"],
        publisher="OpenAI",
        published="2026-04",
    )

    frontmatter = render_frontmatter(meta)

    assert 'publisher: "OpenAI"' in frontmatter
    assert 'published: "2026-04"' in frontmatter
    assert '  - "Alice Example"' in frontmatter


def test_parse_document_supports_crlf_frontmatter():
    raw = "---\r\ntitle: Test\r\nsummary: |\r\n  Body line\r\n---\r\nHello\r\n"

    frontmatter, body = parse_document(raw)

    assert frontmatter["title"] == "Test"
    assert frontmatter["summary"] == "Body line"
    assert body == "Hello"


def test_parse_document_strips_single_quoted_values():
    raw = "---\ntitle: 'Single Quoted'\npublisher: 'O''Reilly'\n---\nBody\n"

    frontmatter, body = parse_document(raw)

    assert frontmatter["title"] == "Single Quoted"
    assert frontmatter["publisher"] == "O'Reilly"
    assert body == "Body"


def test_render_frontmatter_escapes_backslashes_and_whitespace_summary():
    meta = PageMeta(
        title=r"Path C:\Users",
        page_type="concept",
        lang="en",
        tags=[],
        summary="   ",
    )

    frontmatter = render_frontmatter(meta)
    parsed, _ = parse_document(frontmatter + "\nBody")

    assert 'title: "Path C:\\\\Users"' in frontmatter
    assert 'summary: ""' in frontmatter
    assert parsed["title"] == r"Path C:\Users"
    assert parsed["summary"] == ""
