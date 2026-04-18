---
name: kb
description: Operating procedure for octopus-kb knowledge bases. Use this skill EVERY TIME you are asked to find, edit, or explain information in a vault under `wiki/` or `raw/`. Grep is forbidden until you have run retrieve-bundle.
---

# Operating Procedure

1. Before any Grep or Read on `wiki/` or `raw/`, run:
   `octopus-kb retrieve-bundle "{task}" --vault . --json`
   Read pages in the returned order: schema → index → concepts → entities → raw_sources. Stop when you have enough context.

2. Before creating a new page or alias, run:
   `octopus-kb lookup "{term}" --vault . --json`
   If `canonical` is non-null and `ambiguous` is false, reuse that page.

3. Before editing an existing page, run:
   `octopus-kb impacted-pages "{page_path}" --vault . --json`
   Your edit must stay consistent with the returned impacted set.

4. To understand a page's graph context, run:
   `octopus-kb neighbors "{page_path}" --vault . --json`

5. To lint before finishing, run:
   `octopus-kb lint . --json`
   Fix every `DUPLICATE_CANONICAL_PAGE`, `CANONICAL_ALIAS_COLLISION`, `SCHEMA_INVALID_FIELD`, and `SCHEMA_MISSING_FIELD`.

## Forbidden

- Grep on `wiki/**` or `raw/**` without first running `retrieve-bundle`.
- Creating a concept page without first running `lookup`.
- Editing a page without first running `impacted-pages`.
- Pasting raw page bodies into prompts. Use `retrieve-bundle` JSON output.

## Why

Grep finds strings. `retrieve-bundle` finds decisions. A 3MB vault returns 200 grep matches; `retrieve-bundle` returns the 5 pages that matter. Skipping step 1 means re-learning the vault every turn.
