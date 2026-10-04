from __future__ import annotations

from pathlib import Path
from typing import Any

from octopus_kb_compound.apply import validate_proposal_file
from octopus_kb_compound.adapters.obsidian.store import ObsidianStore
from octopus_kb_compound.envelope import ingest_envelope as _ingest_envelope
from octopus_kb_compound.export import _edges, _nodes
from octopus_kb_compound.ingest import generate_raw_page
from octopus_kb_compound.links import build_alias_index
from octopus_kb_compound.lookup import lookup_term
from octopus_kb_compound.neighbors import compute_neighbors
from octopus_kb_compound.profile import load_vault_profile
from octopus_kb_compound.propose import propose_from_raw
from octopus_kb_compound.resolver import require_inside, resolve_vault
from octopus_kb_compound.retrieve import build_retrieval_bundle

DEFAULT_MAX_TEXT_CHARS = 4000


def export_graph(vault: str | Path) -> dict[str, Any]:
    root = resolve_vault(vault)
    store = ObsidianStore(root, load_vault_profile(root))
    pages = store.list_page_records()
    aliases = build_alias_index(pages)
    nodes = _nodes(pages)
    node_ids = {node["id"] for node in nodes}
    return {
        "nodes": nodes,
        "edges": _edges(pages, aliases, node_ids),
        "provenance": {page.path: store.provenance_for(page.path) for page in pages},
    }


def retrieve_bundle(
    vault: str | Path,
    query: str,
    *,
    max_tokens: int = 1500,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> dict[str, Any]:
    root = resolve_vault(vault)
    store = ObsidianStore(root)
    bundle = build_retrieval_bundle(root, query, max_tokens=max_tokens, store=store)
    data = bundle.to_dict()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path in _ordered_paths(data):
        if path in seen:
            continue
        seen.add(path)
        text = store.read_markdown(path)[:max_text_chars] if path else ""
        item = _item_for_path(data, path) or {"path": path, "title": Path(path).stem, "reason": "bundle"}
        items.append(
            {
                "path": path,
                "title": item.get("title") or Path(path).stem,
                "reason": item.get("reason") or "bundle",
                "text": text,
                "tokenEstimate": _estimate_tokens(text),
                "provenance": store.provenance_for(path),
            }
        )

    return {
        "query": data.get("query", query),
        "items": items,
        "warnings": data.get("warnings", []),
        "tokenEstimate": sum(item["tokenEstimate"] for item in items),
        "next": data.get("next", []),
    }


def ingest(
    vault: str | Path,
    markdown: str,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    root = resolve_vault(vault)
    path = generate_raw_page(
        markdown,
        {"title": title or "source", "ingest_method": "alata"},
        root / "raw",
        lang=lang,
        tags=tags or [],
    )
    return {"path": path.relative_to(root).as_posix()}


def ingest_envelope(
    vault_id: str,
    manifest: dict,
    parts: list[dict],
    approval: dict | None = None,
    attestation: dict | None = None,
) -> dict[str, Any]:
    return _ingest_envelope(vault_id, manifest, parts, approval, attestation)


def neighbors(vault: str | Path, page: str) -> dict[str, Any]:
    root = resolve_vault(vault)
    require_inside(root, page)
    return compute_neighbors(page, root).to_dict()


def lookup(vault: str | Path, term: str) -> dict[str, Any]:
    return lookup_term(term, resolve_vault(vault)).to_dict()


def propose(vault: str | Path, raw_path: str, *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    # octopus-kb v0.6 reads profiles from config/env. Alata M2 will inject a
    # per-call config outside the vault; M1 keeps this wrapper non-persistent.
    if profile:
        raise ValueError("profile injection is handled by the caller in M2")
    root = resolve_vault(vault)
    source = require_inside(root, raw_path)
    return propose_from_raw(source, root).to_dict()


def validate(
    vault: str | Path,
    proposal_path: str,
    *,
    apply: bool = False,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = resolve_vault(vault)
    proposal = require_inside(root, proposal_path)
    return validate_proposal_file(proposal, root, apply=apply, approval=approval).to_dict()


def healthcheck(vault: str | Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True}
    if vault is not None:
        payload["vaultExists"] = resolve_vault(vault).exists()
    return payload


def _ordered_paths(data: dict[str, Any]) -> list[str]:
    bundle = data.get("bundle") or {}
    paths: list[str] = []
    paths.extend(bundle.get("schema") or [])
    paths.extend(bundle.get("index") or [])
    for key in ("concepts", "entities", "raw_sources"):
        for item in bundle.get(key) or []:
            if isinstance(item, dict) and item.get("path"):
                paths.append(item["path"])
            elif isinstance(item, str):
                paths.append(item)
    return paths


def _item_for_path(data: dict[str, Any], path: str) -> dict[str, Any] | None:
    bundle = data.get("bundle") or {}
    for key in ("concepts", "entities", "raw_sources"):
        for item in bundle.get(key) or []:
            if isinstance(item, dict) and item.get("path") == path:
                return item
    return None


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0
