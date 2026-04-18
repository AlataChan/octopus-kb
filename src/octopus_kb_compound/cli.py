from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from octopus_kb_compound import ingest
from octopus_kb_compound.export import export_graph_artifacts
from octopus_kb_compound.frontmatter import FrontmatterError, parse_document
from octopus_kb_compound.impact import find_impacted_pages
from octopus_kb_compound.ingest import OptionalDependencyMissing
from octopus_kb_compound.links import suggest_links
from octopus_kb_compound.lint import lint_pages
from octopus_kb_compound.lookup import lookup_term
from octopus_kb_compound.migrate import inspect_vault_for_migration, normalize_vault, render_migration_report
from octopus_kb_compound.neighbors import compute_neighbors
from octopus_kb_compound.planner import plan_maintenance, render_plan
from octopus_kb_compound.profile import load_vault_profile
from octopus_kb_compound.retrieve import build_retrieval_bundle
from octopus_kb_compound.schema import validate_frontmatter
from octopus_kb_compound.summary import render_summary, summarize_vault
from octopus_kb_compound.vault import load_page, scan_markdown_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="octopus-kb", description="Utilities for Obsidian-backed LLM knowledge bases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser("lint", help="Lint a vault for broken links and metadata gaps.")
    lint_parser.add_argument("vault", type=Path)

    suggest_parser = subparsers.add_parser("suggest-links", help="Suggest wikilinks for a page using a vault index.")
    suggest_parser.add_argument("page", type=Path)
    suggest_parser.add_argument("--vault", required=True, type=Path)

    ingest_parser = subparsers.add_parser("ingest-url", help="Fetch a public URL and write it into raw/ as a markdown source.")
    ingest_parser.add_argument("url")
    ingest_parser.add_argument("--vault", required=True, type=Path)
    ingest_parser.add_argument("--tags", default="")
    ingest_parser.add_argument("--lang", default="zh")

    ingest_file_parser = subparsers.add_parser("ingest-file", help="Convert a local file and write it into raw/ as a markdown source.")
    ingest_file_parser.add_argument("path", type=Path)
    ingest_file_parser.add_argument("--vault", required=True, type=Path)
    ingest_file_parser.add_argument("--tags", default="")
    ingest_file_parser.add_argument("--lang", default="zh")

    summary_parser = subparsers.add_parser("vault-summary", help="Summarize vault structure, entries, and lint findings.")
    summary_parser.add_argument("vault", type=Path)

    impact_parser = subparsers.add_parser("impacted-pages", help="Report pages likely impacted by a page change.")
    impact_parser.add_argument("page", type=Path)
    impact_parser.add_argument("--vault", required=True, type=Path)

    plan_parser = subparsers.add_parser("plan-maintenance", help="Plan deterministic wiki maintenance for a changed page.")
    plan_parser.add_argument("page", type=Path)
    plan_parser.add_argument("--vault", required=True, type=Path)

    inspect_parser = subparsers.add_parser("inspect-vault", help="Inspect an existing vault before migration.")
    inspect_parser.add_argument("vault", type=Path)

    normalize_parser = subparsers.add_parser("normalize-vault", help="Normalize vault frontmatter into staging by default.")
    normalize_parser.add_argument("vault", type=Path)
    normalize_parser.add_argument("--apply", action="store_true")
    normalize_parser.add_argument("--in-place", action="store_true")

    export_parser = subparsers.add_parser("export-graph", help="Export graph-aware JSON artifacts for retrieval systems.")
    export_parser.add_argument("vault", type=Path)
    export_parser.add_argument("--out", required=True, type=Path)

    validate_frontmatter_parser = subparsers.add_parser(
        "validate-frontmatter",
        help="Validate frontmatter blocks against the PageMeta schema.",
    )
    validate_frontmatter_parser.add_argument("path", type=Path)
    validate_frontmatter_parser.add_argument("--json", action="store_true")

    lookup_parser = subparsers.add_parser("lookup", help="Resolve a term to a canonical page or alias collision.")
    lookup_parser.add_argument("term")
    lookup_parser.add_argument("--vault", required=True, type=Path)
    lookup_parser.add_argument("--json", action="store_true")

    retrieve_parser = subparsers.add_parser(
        "retrieve-bundle",
        help="Build an ordered retrieval evidence bundle for a query.",
    )
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument("--vault", required=True, type=Path)
    retrieve_parser.add_argument("--max-tokens", type=int, default=0)
    retrieve_parser.add_argument("--json", action="store_true")

    neighbors_parser = subparsers.add_parser("neighbors", help="Report graph neighbors for a page.")
    neighbors_parser.add_argument("page", type=Path)
    neighbors_parser.add_argument("--vault", required=True, type=Path)
    neighbors_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "lint":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        profile = load_vault_profile(args.vault)
        pages = scan_markdown_files(args.vault, profile)
        findings = lint_pages(pages)
        for finding in findings:
            print(f"{finding.code}\t{finding.path}\t{finding.message}")
        return 1 if findings else 0

    if args.command == "suggest-links":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.page)
        if rc is not None:
            return rc
        profile = load_vault_profile(args.vault)
        pages = scan_markdown_files(args.vault, profile)
        target_page = load_page(args.page, root=args.vault)
        suggestions = suggest_links(target_page.body, pages, current_title=target_page.title)
        for suggestion in suggestions:
            print(f"{suggestion.target_title}\t{suggestion.anchor_text}\t{suggestion.reason}")
        return 0

    if args.command == "ingest-url":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc

        try:
            body, metadata = ingest.fetch_url_as_markdown(args.url)
            output_path = ingest.generate_raw_page(
                body,
                metadata,
                args.vault / "raw",
                lang=args.lang,
                tags=_parse_tags(args.tags),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

        print(output_path)
        return 0

    if args.command == "ingest-file":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.path)
        if rc is not None:
            return rc

        try:
            body, metadata = ingest.convert_file_to_markdown(str(args.path))
            output_path = ingest.generate_raw_page(
                body,
                metadata,
                args.vault / "raw",
                lang=args.lang,
                tags=_parse_tags(args.tags),
            )
        except OptionalDependencyMissing as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

        print(output_path)
        return 0

    if args.command == "vault-summary":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc

        print(render_summary(summarize_vault(args.vault)))
        return 0

    if args.command == "impacted-pages":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.page)
        if rc is not None:
            return rc

        for path in find_impacted_pages(args.page, args.vault):
            print(path)
        return 0

    if args.command == "plan-maintenance":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.page)
        if rc is not None:
            return rc

        print(render_plan(plan_maintenance(args.page, args.vault)))
        return 0

    if args.command == "inspect-vault":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        report = inspect_vault_for_migration(args.vault)
        print(render_migration_report(report))
        return 2 if report.parse_failures else 0

    if args.command == "normalize-vault":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        try:
            report = normalize_vault(args.vault, apply=args.apply, in_place=args.in_place)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(render_migration_report(report))
        return 2 if report.parse_failures else 0

    if args.command == "export-graph":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        if args.out.exists() and not args.out.is_dir():
            print(f"Out path is not a directory: {args.out}", file=sys.stderr)
            return 2
        try:
            export_graph_artifacts(args.vault, args.out)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(args.out)
        return 0

    if args.command == "validate-frontmatter":
        try:
            findings = _collect_frontmatter_findings(args.path)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps({"findings": findings}, ensure_ascii=False))
        else:
            for finding in findings:
                print(
                    f"{finding['code']}\t{finding['path']}\t"
                    f"{finding['field']}\t{finding['message']}"
                )
        return 1 if findings else 0

    if args.command == "lookup":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc

        result = lookup_term(args.term, args.vault)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False))
        else:
            _print_lookup_result(result.to_dict())
        return 0

    if args.command == "retrieve-bundle":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc

        bundle = build_retrieval_bundle(
            args.vault, args.query, max_tokens=args.max_tokens
        )
        data = bundle.to_dict()
        if args.json:
            print(json.dumps(data, ensure_ascii=False))
        else:
            _print_retrieval_bundle(data)
        return 0

    if args.command == "neighbors":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        page_rel_path = _resolve_page_in_vault(args.page, args.vault)
        if page_rel_path is None:
            return 2

        try:
            result = compute_neighbors(page_rel_path, args.vault)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        data = result.to_dict()
        if args.json:
            print(json.dumps(data, ensure_ascii=False))
        else:
            _print_neighbors_result(data)
        return 0

    parser.error("Unknown command")
    return 2


def _validate_vault_dir(vault: Path) -> int | None:
    if not vault.exists():
        print(f"Vault does not exist: {vault}", file=sys.stderr)
        return 2
    if not vault.is_dir():
        print(f"Vault is not a directory: {vault}", file=sys.stderr)
        return 2
    return None


def _validate_page_file(page: Path) -> int | None:
    if not page.exists():
        print(f"Page does not exist: {page}", file=sys.stderr)
        return 2
    if not page.is_file():
        print(f"Page is not a file: {page}", file=sys.stderr)
        return 2
    return None


def _resolve_page_in_vault(page: Path, vault: Path) -> str | None:
    vault_root = vault.resolve()
    page_path = page.resolve() if page.is_absolute() else (vault / page).resolve()
    if not page_path.is_relative_to(vault_root):
        print(f"Page is outside vault: {page}", file=sys.stderr)
        return None
    if not page_path.exists():
        print(f"Page does not exist: {page}", file=sys.stderr)
        return None
    if not page_path.is_file():
        print(f"Page is not a file: {page}", file=sys.stderr)
        return None
    return page_path.relative_to(vault_root).as_posix()


def _parse_tags(raw_tags: str) -> list[str]:
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def _print_lookup_result(result: dict) -> None:
    canonical = result["canonical"]
    if canonical is not None:
        print(f"canonical\t{canonical['path']}")
    for alias in result["aliases"]:
        print(f"alias\t{alias['text']}\t{alias['resolves_to']}")
    for collision in result["collisions"]:
        print(f"collision\t{collision}")
    for command in result["next"]:
        print(f"next\t{command}")


def _print_retrieval_bundle(result: dict) -> None:
    bundle = result["bundle"]
    for path in bundle["schema"]:
        print(f"schema\t{path}")
    for path in bundle["index"]:
        print(f"index\t{path}")
    for section in ("concepts", "entities", "raw_sources"):
        for page in bundle[section]:
            print(f"{section}\t{page['path']}\t{page['reason']}")
    for warning in result["warnings"]:
        print(f"warning\t{warning['code']}\t{warning['message']}")
    print(f"token_estimate\t{result['token_estimate']}")
    for command in result["next"]:
        print(f"next\t{command}")


def _print_neighbors_result(result: dict) -> None:
    print(f"page\t{result['page']}")
    if result["canonical_identity"] is not None:
        print(f"canonical_identity\t{result['canonical_identity']}")
    for alias in result["aliases"]:
        print(f"alias\t{alias}")
    for inbound in result["inbound"]:
        print(f"inbound\t{inbound['path']}\t{inbound['via']}\t{inbound['count']}")
    for outbound in result["outbound"]:
        print(f"outbound\t{outbound['path']}\t{outbound['via']}")
    for command in result["next"]:
        print(f"next\t{command}")


def _collect_frontmatter_findings(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise OSError(f"Path does not exist: {path}")
    if path.is_file():
        return _validate_frontmatter_file(path, str(path))
    if not path.is_dir():
        raise OSError(f"Path is not a file or directory: {path}")

    findings: list[dict[str, str]] = []
    for md_path in sorted(path.rglob("*.md")):
        rel = md_path.relative_to(path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        findings.extend(_validate_frontmatter_file(md_path, rel.as_posix()))
    return findings


def _validate_frontmatter_file(path: Path, display_path: str) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if not raw.replace("\r\n", "\n").replace("\r", "\n").startswith("---\n"):
        return []
    try:
        frontmatter, _ = parse_document(raw, strict=True)
    except FrontmatterError as exc:
        return [
            {
                "code": "PARSE_FAILURE",
                "path": display_path,
                "field": "",
                "message": str(exc),
            }
        ]

    return [
        {
            "code": finding.code,
            "path": display_path,
            "field": finding.field,
            "message": finding.message,
        }
        for finding in validate_frontmatter(frontmatter)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
