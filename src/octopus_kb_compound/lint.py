from __future__ import annotations

from pathlib import Path
import re

from octopus_kb_compound.links import (
    build_alias_index,
    extract_wikilinks,
    find_alias_collisions,
    frontmatter_aliases,
    normalize_page_name,
)
from octopus_kb_compound.models import LintFinding, PageRecord


def lint_pages(pages: list[PageRecord]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    alias_index = build_alias_index(pages)
    title_lookup = {page.title: page for page in pages}
    inbound_counts = {page.path: 0 for page in pages}
    canonical_by_key = _canonical_pages_by_key(pages)
    alias_collisions = find_alias_collisions(pages)

    for alias, titles in alias_collisions.items():
        findings.append(
            LintFinding(
                "ALIAS_COLLISION",
                ",".join(sorted(title_lookup[title].path for title in titles)),
                f"Alias `{alias}` resolves to multiple pages: {', '.join(sorted(titles))}",
            )
        )

    for key, canonical_pages in canonical_by_key.items():
        if len(canonical_pages) > 1:
            findings.append(
                LintFinding(
                    "DUPLICATE_CANONICAL_PAGE",
                    ",".join(sorted(page.path for page in canonical_pages)),
                    f"Canonical identity `{key}` is declared by multiple pages.",
                )
            )

    for page in pages:
        frontmatter = page.frontmatter
        role = frontmatter.get("role")
        layer = frontmatter.get("layer")
        summary = frontmatter.get("summary")

        if not role:
            findings.append(LintFinding("MISSING_ROLE", page.path, "Page is missing `role`."))
        if layer == "wiki" and not summary:
            findings.append(LintFinding("MISSING_SUMMARY", page.path, "Wiki page is missing `summary`."))

        findings.extend(_lint_frontmatter_aliases(page, alias_index, alias_collisions, canonical_by_key))

        for link in extract_wikilinks(_strip_code_blocks(page.body)):
            if _should_ignore_link_target(link):
                continue
            key = normalize_page_name(link)
            canonical_title = alias_index.get(key)
            if canonical_title is None:
                findings.append(LintFinding("BROKEN_LINK", page.path, f"Broken wikilink: [[{link}]]"))
                continue
            target = title_lookup[canonical_title]
            inbound_counts[target.path] += 1

    for page in pages:
        if page.frontmatter.get("role") == "concept" and inbound_counts.get(page.path, 0) == 0:
            findings.append(LintFinding("ORPHAN_PAGE", page.path, "Concept page has no inbound wikilinks."))

    return findings


def _canonical_pages_by_key(pages: list[PageRecord]) -> dict[str, list[PageRecord]]:
    result: dict[str, list[PageRecord]] = {}
    for page in pages:
        key = _canonical_key(page)
        if not key:
            continue
        result.setdefault(key, []).append(page)
    return result


def _canonical_key(page: PageRecord) -> str | None:
    frontmatter = page.frontmatter
    role = frontmatter.get("role")
    page_type = frontmatter.get("type")
    layer = frontmatter.get("layer")
    source_of_truth = frontmatter.get("source_of_truth")
    is_raw = role == "raw_source" or page_type == "raw_source"

    if is_raw and source_of_truth != "canonical":
        return None

    canonical_name = frontmatter.get("canonical_name")
    if isinstance(canonical_name, str) and normalize_page_name(canonical_name):
        return normalize_page_name(canonical_name)

    title = str(frontmatter.get("title") or page.title or "")
    if source_of_truth == "canonical" and normalize_page_name(title):
        return normalize_page_name(title)

    if is_raw:
        return None

    if layer != "wiki":
        return None

    if normalize_page_name(title):
        return normalize_page_name(title)

    stem = Path(page.path).stem
    if normalize_page_name(stem):
        return normalize_page_name(stem)

    return None


def _lint_frontmatter_aliases(
    page: PageRecord,
    alias_index: dict[str, str],
    alias_collisions: dict[str, list[str]],
    canonical_by_key: dict[str, list[PageRecord]],
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for alias in frontmatter_aliases(page):
        key = normalize_page_name(alias)
        if not key:
            findings.append(LintFinding("UNRESOLVED_ALIAS", page.path, f"Frontmatter alias cannot resolve: {alias!r}"))
            continue

        canonical_targets = [target for target in canonical_by_key.get(key, []) if target.path != page.path]
        if canonical_targets:
            findings.append(
                LintFinding(
                    "CANONICAL_ALIAS_COLLISION",
                    page.path,
                    f"Frontmatter alias `{alias}` collides with canonical page `{canonical_targets[0].title}`.",
                )
            )
            continue

        if key in alias_collisions:
            continue

        if alias_index.get(key) != page.title:
            findings.append(LintFinding("UNRESOLVED_ALIAS", page.path, f"Frontmatter alias does not resolve to this page: {alias}"))
    return findings


def _strip_code_blocks(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def _should_ignore_link_target(target: str) -> bool:
    if target.endswith("/"):
        return True
    if "[" in target or "]" in target:
        return True
    if '"' in target or "'" in target:
        return True
    if "\n" in target:
        return True
    if "," in target and "/" not in target and ".md" not in target:
        segments = [segment.strip() for segment in target.split(",")]
        if segments and all(segment and segment == segment.lower() for segment in segments):
            return True
    if not any(char.isalpha() for char in target):
        return True
    return False
