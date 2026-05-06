# Architecture

`octopus-kb` is designed around three layers:

- raw sources
- generated wiki pages
- schema and workflow rules

The Python package provides deterministic helpers. Skills and prompts provide the LLM-facing operating model.

## Canonical Knowledge Representation

The v0.7 foundation introduces a Canonical Knowledge Representation (CKR) as an internal projection layer between the curation pipeline and endpoint storage. CKR v1 is deliberately lossless for the current Obsidian implementation: markdown body text, original wikilink text, aliases, frontmatter metadata, and path-backed audit/CLI outputs remain available during the migration.

The core CKR references are:

- `CanonicalRef`: endpoint-neutral identity for a knowledge object.
- `StorageRef`: adapter-specific storage identity such as `obsidian:wiki/concepts/Foo.md`.
- `CanonicalPage`: page content plus metadata, aliases, related references, body text, body format, and optional storage identity.

`CanonicalRef` and `StorageRef` stay separate so public CLI paths and audit ledgers can remain stable while future endpoint adapters can use non-path storage ids.

## KnowledgeStore Contract

Endpoint adapters implement the `KnowledgeStore` protocol:

- `list_pages() -> list[CanonicalPage]`
- `read_page(ref: CanonicalRef | StorageRef) -> CanonicalPage`
- `resolve_alias(term: str) -> CanonicalRef | None`
- `apply_ops(ops) -> WriteReceipt`

`WriteReceipt` reports created and modified `StorageRef`s. The Obsidian adapter uses those refs to preserve the existing audit ledger shape (`created`, `modified`, and staging paths). Future adapters can map their native ids into `StorageRef` without leaking them into current CLI JSON contracts.

The Obsidian implementation is `ObsidianStore`. Read flows (`lookup`, `neighbors`, `impacted-pages`, and `retrieve-bundle`) go through this adapter boundary, while existing modules such as `frontmatter.py`, `links.py`, and `vault.py` remain compatibility shims for public imports and lower-level parsing helpers.

Lint is split into CKR-level checks (`ckr.lint`) and Obsidian-specific checks (`adapters.obsidian.lint_obsidian`). Apply uses CKR operations and commits through `ObsidianStore.apply_ops()` after the audit-first staging and pending-audit write are complete.

## Retrieval Path

Every retrieval operation should prefer the persistent wiki first:

`schema -> index -> concept -> raw source`

This keeps answers grounded in the accumulated synthesis while still allowing raw verification.

## Maintenance Path

Every maintenance operation should treat the vault as a living graph:

`schema -> impacted pages -> frontmatter -> wikilinks -> index/log -> lint`

The goal is to keep metadata, links, and concept pages moving together.
