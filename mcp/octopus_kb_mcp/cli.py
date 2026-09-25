from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="octopus-kb-mcp")
    sub = parser.add_subparsers(dest="command", required=True)

    _vault_parser(sub, "healthcheck")
    _vault_parser(sub, "export-graph")

    retrieve = _vault_parser(sub, "retrieve-bundle")
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--max-tokens", type=int, default=1500)
    retrieve.add_argument("--max-text-chars", type=int, default=4000)

    ingest = _vault_parser(sub, "ingest")
    ingest.add_argument("--markdown", required=True)
    ingest.add_argument("--title")
    ingest.add_argument("--tags", default="")

    lookup = _vault_parser(sub, "lookup")
    lookup.add_argument("--term", required=True)

    neighbors = _vault_parser(sub, "neighbors")
    neighbors.add_argument("--page", required=True)

    propose = _vault_parser(sub, "propose")
    propose.add_argument("--raw-path", required=True)

    validate = _vault_parser(sub, "validate")
    validate.add_argument("--proposal-path", required=True)
    validate.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    try:
        payload = _dispatch(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _vault_parser(sub: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    parser = sub.add_parser(name)
    parser.add_argument("--vault")
    return parser


def _dispatch(args: argparse.Namespace):
    vault = Path(args.vault) if args.vault else None
    if args.command == "healthcheck":
        return tools.healthcheck(vault)
    if vault is None:
        raise ValueError("--vault is required")
    if args.command == "export-graph":
        return tools.export_graph(vault)
    if args.command == "retrieve-bundle":
        return tools.retrieve_bundle(
            vault,
            args.query,
            max_tokens=args.max_tokens,
            max_text_chars=args.max_text_chars,
        )
    if args.command == "ingest":
        tags = [tag for tag in args.tags.split(",") if tag]
        return tools.ingest(vault, args.markdown, title=args.title, tags=tags)
    if args.command == "lookup":
        return tools.lookup(vault, args.term)
    if args.command == "neighbors":
        return tools.neighbors(vault, args.page)
    if args.command == "propose":
        return tools.propose(vault, args.raw_path)
    if args.command == "validate":
        return tools.validate(vault, args.proposal_path, apply=args.apply)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
