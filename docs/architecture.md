# Architecture

`octopus-kb-compound` is designed around three layers:

- raw sources
- generated wiki pages
- schema and workflow rules

The Python package provides deterministic helpers. Skills and prompts provide the LLM-facing operating model.

## Retrieval Path

Every retrieval operation should prefer the persistent wiki first:

`schema -> index -> concept -> raw source`

This keeps answers grounded in the accumulated synthesis while still allowing raw verification.

## Maintenance Path

Every maintenance operation should treat the vault as a living graph:

`schema -> impacted pages -> frontmatter -> wikilinks -> index/log -> lint`

The goal is to keep metadata, links, and concept pages moving together.
