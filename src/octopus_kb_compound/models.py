from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PageMeta:
    title: str
    page_type: str
    lang: str
    tags: list[str] = field(default_factory=list)
    role: str | None = None
    layer: str | None = None
    workflow: list[str] | None = None
    summary: str | None = None
    publisher: str | None = None
    published: str | None = None
    authors: list[str] | None = None
    aliases: list[str] | None = None


@dataclass(slots=True)
class PageRecord:
    path: str
    title: str
    body: str
    frontmatter: dict[str, Any]


@dataclass(slots=True)
class LinkSuggestion:
    target_title: str
    anchor_text: str
    reason: str


@dataclass(slots=True)
class LintFinding:
    code: str
    path: str
    message: str
