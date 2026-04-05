from __future__ import annotations

import argparse
from pathlib import Path
import sys

from octopus_kb_compound.links import suggest_links
from octopus_kb_compound.lint import lint_pages
from octopus_kb_compound.vault import load_page, scan_markdown_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="octopus-kb", description="Utilities for Obsidian-backed LLM knowledge bases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser("lint", help="Lint a vault for broken links and metadata gaps.")
    lint_parser.add_argument("vault", type=Path)

    suggest_parser = subparsers.add_parser("suggest-links", help="Suggest wikilinks for a page using a vault index.")
    suggest_parser.add_argument("page", type=Path)
    suggest_parser.add_argument("--vault", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "lint":
        if not args.vault.exists():
            print(f"Vault does not exist: {args.vault}", file=sys.stderr)
            return 2
        if not args.vault.is_dir():
            print(f"Vault is not a directory: {args.vault}", file=sys.stderr)
            return 2
        pages = scan_markdown_files(args.vault)
        findings = lint_pages(pages)
        for finding in findings:
            print(f"{finding.code}\t{finding.path}\t{finding.message}")
        return 1 if findings else 0

    if args.command == "suggest-links":
        if not args.vault.exists():
            print(f"Vault does not exist: {args.vault}", file=sys.stderr)
            return 2
        if not args.vault.is_dir():
            print(f"Vault is not a directory: {args.vault}", file=sys.stderr)
            return 2
        if not args.page.exists():
            print(f"Page does not exist: {args.page}", file=sys.stderr)
            return 2
        pages = scan_markdown_files(args.vault)
        target_page = load_page(args.page)
        suggestions = suggest_links(target_page.body, pages, current_title=target_page.title)
        for suggestion in suggestions:
            print(f"{suggestion.target_title}\t{suggestion.anchor_text}\t{suggestion.reason}")
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
