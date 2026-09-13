---
name: kb-maintain
description: Use when ingesting sources, updating wiki pages, fixing metadata, adding wikilinks, or running health checks on a markdown knowledge base.
---

# KB Maintain

## Overview

Maintain the wiki as a living artifact. Every change should improve structure, evidence quality, and graph navigability at the same time.

## Workflow

1. Read the schema before changing pages.
2. Inspect the index and affected concept pages.
3. Ingest the new source or maintenance request. Acquire new sources with `kb-ingest` first.
4. Plan impacted pages before editing: `octopus-kb impacted-pages "{page_path}" --vault . --json`, then `octopus-kb plan-maintenance "{page_path}" --vault .`.
5. Update frontmatter, summaries, wikilinks, and index/log entries together.
6. Run `octopus-kb lint . --json` to catch broken links, orphans, and missing metadata.

`plan-maintenance` does not mutate the vault; treat its output as guidance.

To turn a raw source into wiki changes through the rule gate, run `octopus-kb propose raw/<file> --vault . --json`, then `octopus-kb validate .octopus-kb/proposals/<id>.json --vault . --apply --json`. Without `--apply`, `validate` is not a pure dry run: a reject verdict is written to `.octopus-kb/rejections/` and a defer verdict to `.octopus-kb/inbox/`.

For health checks, use `octopus-kb vault-summary .` and `octopus-kb validate-frontmatter <path> --json`.

## Rules

- Never edit raw-source files beyond frontmatter normalization unless explicitly requested.
- Prefer updating existing concept pages over creating duplicates.
- Add wikilinks only when the target page is canonical and useful.
- Avoid overlinking. A dense graph is not automatically a useful graph.
- If a concept deserves a page but does not exist, create a stub or record the gap explicitly.

## Maintenance Output

- changed pages
- new pages
- new or removed wikilinks
- metadata changes
- lint findings and follow-up actions

See `references/maintenance-checklist.md` when you need the compact update checklist.
