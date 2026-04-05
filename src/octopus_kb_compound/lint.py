from __future__ import annotations

from octopus_kb_compound.links import (
    build_alias_index,
    extract_wikilinks,
    find_alias_collisions,
    normalize_page_name,
)
from octopus_kb_compound.models import LintFinding, PageRecord


def lint_pages(pages: list[PageRecord]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    alias_index = build_alias_index(pages)
    title_lookup = {page.title: page for page in pages}
    inbound_counts = {page.path: 0 for page in pages}

    for alias, titles in find_alias_collisions(pages).items():
        findings.append(
            LintFinding(
                "ALIAS_COLLISION",
                ",".join(sorted(title_lookup[title].path for title in titles)),
                f"Alias `{alias}` resolves to multiple pages: {', '.join(sorted(titles))}",
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

        for link in extract_wikilinks(page.body):
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
