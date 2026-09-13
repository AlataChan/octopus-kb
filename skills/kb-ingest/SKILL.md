---
name: kb-ingest
description: Use when acquiring a public URL or local file and converting it into a new raw source page for the knowledge base.
---

# KB Ingest

## Overview

Acquire external content and stop at the raw layer.

The goal is to turn a public URL or a local file into a new `raw/*.md` evidence page with complete frontmatter and provenance. `kb-ingest` does not update wiki concept pages, indexes, or logs.

## Workflow

1. Ingest with the matching command:
   - Public URL: `octopus-kb ingest-url <url> --vault . [--tags t1,t2] [--lang zh]` fetches markdown through Jina Reader.
   - Local file: `octopus-kb ingest-file <path> --vault . [--tags t1,t2] [--lang zh]` converts with `markitdown` (install with `pip install 'octopus-kb[ingest]'`).
   - `--lang` defaults to `zh`; set it explicitly for other languages.
2. Check the new page under `raw/`. The file name is a slug of the title, with a numeric suffix when that name is taken.
3. Hand off to `kb-maintain` if the wiki needs to be updated afterward.

Both commands write `title`, `type: raw_source`, `lang`, `role: raw_source`, `layer: source`, `tags`, and `summary`, plus provenance: `source_url`, `ingest_method`, `fetched_at` for URLs, or `source_file`, `original_format`, `ingest_method`, `converted_at` for files. A raw page written by hand must use the same fields.

## Rules

- Never overwrite an existing raw file.
- Keep provenance in frontmatter, not in ad hoc inline notes.
- Reject localhost and private-network URLs. `ingest-url` blocks `localhost` and literal private or loopback IPs, but not hostnames that resolve to private addresses.
- Stop after creating the raw source. Wiki maintenance belongs to `kb-maintain`.

## Output Contract

- created raw page path
- extracted or fallback title
- provenance fields written
- follow-up note when `kb-maintain` should run next

See `references/ingest-checklist.md` when you need the compact acquisition checklist.
