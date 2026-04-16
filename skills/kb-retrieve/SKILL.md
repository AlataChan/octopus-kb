---
name: kb-retrieve
description: Use when answering questions against a structured markdown knowledge base with schema, index, concept pages, and raw sources.
---

# KB Retrieve

## Overview

Retrieve answers from the knowledge base by walking the same chain every time:

`schema -> index -> concept -> raw source`

The goal is not generic RAG. The goal is to reuse the persistent wiki first, then open raw sources only when evidence or edge cases require it.

## Workflow

1. Read the schema page first and inherit its conventions.
2. Read the index to locate likely concept pages and recent changes.
3. Read the smallest set of concept pages that can answer the question.
4. Read raw sources only to verify claims, resolve conflicts, or gather direct evidence.
5. Answer in four parts:
   - conclusion
   - evidence
   - synthesis
   - open gaps

When available, use `octopus_kb_compound.retrieve.build_retrieval_bundle()` to produce the ordered schema, index, concept, entity, and raw-source page set before reading files manually.

## Rules

- Prefer concept pages over raw sources for orientation.
- Prefer raw sources over concept pages for disputed claims.
- Always state when evidence is single-source.
- Preserve uncertainty instead of smoothing it away.
- If a good answer reveals a durable insight, recommend filing it back into the wiki.

## Output Contract

- Include evidence, not just conclusions.
- Cite exact page names or files when possible.
- End with explicit knowledge gaps or follow-up questions.

See `references/retrieve-output-contract.md` when the answer format needs to be stricter.
