from octopus_kb_compound.links import (
    build_alias_index,
    extract_wikilinks,
    find_alias_collisions,
    normalize_page_name,
    suggest_links,
)
from octopus_kb_compound.models import PageRecord


def test_extract_wikilinks_reads_plain_and_aliased_links():
    body = "See [[Agent设计模式]] and [[LLM基础与架构|LLM 基础]]."

    assert extract_wikilinks(body) == ["Agent设计模式", "LLM基础与架构"]


def test_normalize_page_name_stabilizes_case_and_spacing():
    assert normalize_page_name("  LLM 基础 与 架构  ") == "llm基础与架构"
    assert normalize_page_name("Agent-Design Patterns") == "agentdesignpatterns"
    assert normalize_page_name("モデル 設計") == "モデル設計"


def test_build_alias_index_maps_aliases_to_canonical_titles():
    pages = [
        PageRecord(path="wiki/concepts/Agent设计模式.md", title="Agent设计模式", body="", frontmatter={"aliases": ["Agent Patterns"]}),
    ]

    alias_index = build_alias_index(pages)

    assert alias_index["agentpatterns"] == "Agent设计模式"


def test_suggest_links_prefers_known_pages_and_aliases():
    pages = [
        PageRecord(path="wiki/concepts/Agent设计模式.md", title="Agent设计模式", body="", frontmatter={"aliases": ["Agent Patterns"]}),
        PageRecord(
            path="wiki/concepts/RAG与知识增强.md",
            title="RAG与知识增强",
            body="",
            frontmatter={"aliases": ["retrieval augmented generation"]},
        ),
    ]
    body = "This note compares Agent Patterns with retrieval augmented generation."

    suggestions = suggest_links(body, pages)

    assert [item.target_title for item in suggestions] == ["Agent设计模式", "RAG与知识增强"]


def test_suggest_links_does_not_return_self_link():
    pages = [
        PageRecord(path="wiki/concepts/RAG与知识增强.md", title="RAG与知识增强", body="", frontmatter={}),
    ]
    body = "RAG与知识增强 connects retrieval augmented generation to evidence."

    suggestions = suggest_links(body, pages, current_title="RAG与知识增强")

    assert suggestions == []


def test_suggest_links_does_not_match_alias_inside_unrelated_word():
    pages = [
        PageRecord(path="wiki/concepts/RAG与知识增强.md", title="RAG与知识增强", body="", frontmatter={"aliases": ["RAG"]}),
    ]

    suggestions = suggest_links("This page is about storage systems.", pages)

    assert suggestions == []


def test_build_alias_index_ignores_ambiguous_alias_and_reports_collision():
    pages = [
        PageRecord(path="wiki/concepts/PageA.md", title="Page A", body="", frontmatter={"aliases": ["Shared Alias"]}),
        PageRecord(path="wiki/concepts/PageB.md", title="Page B", body="", frontmatter={"aliases": ["Shared Alias"]}),
    ]

    alias_index = build_alias_index(pages)
    collisions = find_alias_collisions(pages)

    assert "sharedalias" not in alias_index
    assert collisions["sharedalias"] == ["Page A", "Page B"]
