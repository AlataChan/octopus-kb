from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from octopus_kb_compound.links import build_alias_index, extract_wikilinks, frontmatter_aliases, normalize_page_name
from octopus_kb_compound.models import PageRecord
from octopus_kb_compound.profile import load_vault_profile
from octopus_kb_compound.vault import scan_markdown_files


@dataclass(slots=True)
class RetrievalBundle:
    schema: str | None
    index: str | None
    concepts: list[str]
    entities: list[str]
    raw_sources: list[str]
    ordered_pages: list[str]


def build_retrieval_bundle(vault: str | Path, query: str) -> RetrievalBundle:
    root = Path(vault)
    pages = scan_markdown_files(root, load_vault_profile(root))
    alias_index = build_alias_index(pages)
    by_title = {page.title: page for page in pages}

    schema = _first_path_by_role(pages, "schema")
    index = _first_path_by_role(pages, "index")
    concepts = _matching_concepts(pages, query)
    entities = _related_entities(concepts, alias_index, by_title)
    raw_sources = _raw_sources(pages, query, concepts)

    ordered = _dedupe([schema, index] + [p.path for p in concepts] + [p.path for p in entities] + [p.path for p in raw_sources])
    return RetrievalBundle(
        schema=schema,
        index=index,
        concepts=[page.path for page in concepts],
        entities=[page.path for page in entities],
        raw_sources=[page.path for page in raw_sources],
        ordered_pages=ordered,
    )


def _first_path_by_role(pages: list[PageRecord], role: str) -> str | None:
    for page in pages:
        if page.frontmatter.get("role") == role:
            return page.path
    return None


def _matching_concepts(pages: list[PageRecord], query: str) -> list[PageRecord]:
    query_key = normalize_page_name(query)
    query_lower = query.casefold()
    concepts = [
        page
        for page in pages
        if page.frontmatter.get("role") == "concept"
        and (
            query_key == normalize_page_name(page.title)
            or query_key in {normalize_page_name(alias) for alias in frontmatter_aliases(page)}
            or query_lower in page.body.casefold()
        )
    ]
    return sorted(concepts, key=lambda page: page.path)


def _related_entities(
    concepts: list[PageRecord],
    alias_index: dict[str, str],
    by_title: dict[str, PageRecord],
) -> list[PageRecord]:
    entities: list[PageRecord] = []
    for concept in concepts:
        for name in _entity_names(concept):
            title = alias_index.get(normalize_page_name(name))
            page = by_title.get(title or "")
            if page is not None and page.frontmatter.get("role") == "entity":
                entities.append(page)
    return sorted(_dedupe_pages(entities), key=lambda page: page.path)


def _entity_names(page: PageRecord) -> list[str]:
    names = extract_wikilinks(page.body)
    related = page.frontmatter.get("related_entities", [])
    if isinstance(related, list):
        names.extend(str(item) for item in related)
    return names


def _raw_sources(pages: list[PageRecord], query: str, concepts: list[PageRecord]) -> list[PageRecord]:
    raw_pages = [page for page in pages if page.frontmatter.get("role") == "raw_source"]
    if concepts:
        return sorted(raw_pages, key=lambda page: page.path)
    query_lower = query.casefold()
    return sorted([page for page in raw_pages if query_lower in page.body.casefold()], key=lambda page: page.path)


def _dedupe(values: list[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_pages(pages: list[PageRecord]) -> list[PageRecord]:
    result: list[PageRecord] = []
    seen: set[str] = set()
    for page in pages:
        if page.path in seen:
            continue
        seen.add(page.path)
        result.append(page)
    return result
