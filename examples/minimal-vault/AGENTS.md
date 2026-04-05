---
title: "AGENTS"
type: meta
lang: en
role: schema
layer: wiki
tags:
  - AI/Wiki
summary: |
  Example schema for retrieval and maintenance in the minimal vault.
---

# Example Vault Schema

This schema defines how the LLM should operate on the vault.

## Retrieval

Always read:

1. `wiki/INDEX.md`
2. relevant `wiki/concepts/*.md`
3. raw sources only for verification

## Maintenance

- Keep raw sources immutable
- Update concept pages before creating duplicates
- Add wikilinks to canonical pages
- Update `wiki/INDEX.md` when a durable page is added
- Run lint after meaningful edits
