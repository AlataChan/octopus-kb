from __future__ import annotations

from pathlib import Path

from octopus_kb_compound.frontmatter import parse_document
from octopus_kb_compound.models import PageRecord


def load_page(path: str | Path) -> PageRecord:
    page_path = Path(path)
    raw = page_path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = parse_document(raw)
    title = str(frontmatter.get("title") or page_path.stem)
    return PageRecord(
        path=str(page_path),
        title=title,
        body=body,
        frontmatter=frontmatter,
    )


def scan_markdown_files(root: str | Path) -> list[PageRecord]:
    root_path = Path(root)
    pages: list[PageRecord] = []
    for path in sorted(root_path.rglob("*.md")):
        if _is_hidden_path(path.relative_to(root_path)):
            continue
        pages.append(load_page(path))
    return pages


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)
