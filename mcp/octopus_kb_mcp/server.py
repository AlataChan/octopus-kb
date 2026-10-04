from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from octopus_kb_compound.resolver import require_mcp_mapping

from . import tools

mcp = FastMCP("octopus-kb")


@mcp.tool()
def kb_export_graph(vault: str) -> dict:
    return tools.export_graph(vault)


@mcp.tool()
def kb_retrieve_bundle(vault: str, query: str, max_tokens: int = 1500, max_text_chars: int = 4000) -> dict:
    return tools.retrieve_bundle(vault, query, max_tokens=max_tokens, max_text_chars=max_text_chars)


@mcp.tool()
def kb_ingest(vault: str, markdown: str, title: str | None = None, tags: list[str] | None = None) -> dict:
    return tools.ingest(vault, markdown, title=title, tags=tags or [])


@mcp.tool()
def kb_ingest_envelope(
    vault_id: str,
    manifest: dict,
    parts: list[dict],
    approval: dict | None = None,
    attestation: dict | None = None,
) -> dict:
    return tools.ingest_envelope(vault_id, manifest, parts, approval, attestation)


@mcp.tool()
def kb_neighbors(vault: str, page: str) -> dict:
    return tools.neighbors(vault, page)


@mcp.tool()
def kb_lookup(vault: str, term: str) -> dict:
    return tools.lookup(vault, term)


@mcp.tool()
def kb_propose(vault: str, raw_path: str, profile: dict | None = None) -> dict:
    return tools.propose(vault, raw_path, profile=profile)


@mcp.tool()
def kb_validate(
    vault: str,
    proposal_path: str,
    apply: bool = False,
    approval: dict | None = None,
) -> dict:
    return tools.validate(vault, proposal_path, apply=apply, approval=approval)


def main() -> None:
    require_mcp_mapping()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
