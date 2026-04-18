from octopus_kb_compound.frontmatter import parse_document, render_frontmatter
from octopus_kb_compound.models import PageMeta
from octopus_kb_compound.page_types import (
    make_changelog_meta,
    make_comparison_meta,
    make_concept_meta,
    make_entity_meta,
    make_timeline_meta,
)


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
    assert '  - "ingest"' in frontmatter
    assert '  - "lint"' in frontmatter
    assert '  - "query"' in frontmatter


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


def test_render_frontmatter_quotes_scalars_containing_special_characters():
    meta = PageMeta(
        title="t",
        page_type="note",
        lang="en",
        related_entities=["Vector: Store", "Foo # bar"],
        tags=["release: 2026", "api/v1"],
        original_format="md: variant",
        ingest_method="jina: reader",
        status="active",
        source_of_truth="canonical",
        workflow=["review: weekly"],
        summary="",
    )
    rendered = render_frontmatter(meta)
    assert '- "Vector: Store"' in rendered
    assert '- "Foo # bar"' in rendered
    assert '- "release: 2026"' in rendered
    assert '- "api/v1"' in rendered
    assert 'original_format: "md: variant"' in rendered
    assert 'ingest_method: "jina: reader"' in rendered
    assert 'status: "active"' in rendered
    assert 'source_of_truth: "canonical"' in rendered
    assert '- "review: weekly"' in rendered

    frontmatter, _ = parse_document(rendered + "\n")
    assert frontmatter["related_entities"] == ["Vector: Store", "Foo # bar"]
    assert frontmatter["tags"] == ["release: 2026", "api/v1"]
    assert frontmatter["original_format"] == "md: variant"
    assert frontmatter["ingest_method"] == "jina: reader"
    assert frontmatter["status"] == "active"
    assert frontmatter["source_of_truth"] == "canonical"
    assert frontmatter["workflow"] == ["review: weekly"]


def test_make_entity_meta_renders_expected_fields():
    meta = make_entity_meta(
        "Vector Store",
        aliases=["Vector Database"],
        related_entities=["Chunking"],
        summary="Canonical entity page.",
    )

    frontmatter = render_frontmatter(meta)
    parsed, _ = parse_document(frontmatter + "\n# Vector Store\n")

    assert meta.page_type == "entity"
    assert isinstance(meta, PageMeta)
    assert "type: entity" in frontmatter
    assert 'canonical_name: "Vector Store"' in frontmatter
    assert 'status: "active"' in frontmatter
    assert 'source_of_truth: "canonical"' in frontmatter
    assert "related_entities:" in frontmatter
    assert '  - "Chunking"' in frontmatter
    assert "aliases:" in frontmatter
    assert parsed["canonical_name"] == "Vector Store"
    assert parsed["related_entities"] == ["Chunking"]


def test_page_type_helpers_create_standard_metadata():
    concept = make_concept_meta("RAG", aliases=["retrieval augmented generation"])
    comparison = make_comparison_meta("Vector DB vs Graph DB", related_entities=["Vector Store", "Knowledge Graph"])
    timeline = make_timeline_meta("RAG Timeline", related_entities=["RAG"])
    changelog = make_changelog_meta("LOG", changelog=["2026-04-14: normalized aliases"])

    assert concept.page_type == "concept"
    assert concept.role == "concept"
    assert comparison.page_type == "comparison"
    assert comparison.related_entities == ["Vector Store", "Knowledge Graph"]
    assert timeline.page_type == "timeline"
    assert timeline.status == "active"
    assert changelog.page_type == "log"
    assert changelog.changelog == ["2026-04-14: normalized aliases"]
