# octopus-kb-compound

Open-source framework for building self-growing, self-maintaining LLM knowledge bases and Obsidian knowledge graphs.

`octopus-kb-compound` is for teams and individuals who want something stronger than ad-hoc RAG. Instead of re-deriving knowledge from raw documents on every query, the LLM maintains a persistent wiki with frontmatter, wikilinks, concept pages, and health checks.

This repository packages three operator-facing assets:

- `kb-retrieve`: a retrieval skill for evidence-backed question answering
- `kb-maintain`: a maintenance skill for ingest, updates, links, and lint
- `obsidian-graph`: a prompt pack and policy set for stable wikilinks and graph hygiene

The Python package provides deterministic helpers for frontmatter, wikilinks, linting, and vault inspection.

## Design Principles

- Treat the wiki as a persistent synthesis layer, not as disposable RAG context.
- Keep raw sources as evidence, not as the primary interface for every query.
- Use frontmatter for structure, tags for topic semantics, and wikilinks for graph navigation.
- Keep aliases explicit in frontmatter so retrieval and lint stay deterministic.
- Make maintenance observable with lint findings instead of hidden drift.

## Core Model

The repository assumes a three-layer vault:

- `raw sources`: immutable evidence and source documents
- `wiki`: generated concept, entity, comparison, and overview pages
- `schema`: rules that tell the LLM how to retrieve, maintain, and evolve the wiki

## Repository Layout

```text
octopus-kb-compound/
├── skills/
│   ├── kb-retrieve/
│   └── kb-maintain/
├── prompts/
│   └── obsidian-graph/
├── src/octopus_kb_compound/
├── examples/minimal-vault/
├── docs/
└── tests/
```

## Quickstart

```bash
cd octopus-kb-compound
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python3 -m pytest -q
python3 -m octopus_kb_compound.cli --help
python3 -m octopus_kb_compound.cli lint examples/minimal-vault
```

For a zero-install smoke check, you can also run:

```bash
PYTHONPATH=src python3 -m octopus_kb_compound.cli --help
```

## What The Skills Do

### `kb-retrieve`

Use when the LLM should answer from the knowledge base by following:

`schema -> index -> concept -> raw source`

The skill keeps answers evidence-backed and gap-aware.

### `kb-maintain`

Use when ingesting sources, updating concept pages, refreshing frontmatter, adding links, or linting the graph.

The skill treats the wiki as a living artifact, not a pile of notes.

## What The CLI Does

- `lint <vault>`: find broken links, orphan concept pages, and missing metadata
- `suggest-links <page> --vault <vault>`: propose canonical wikilinks for an existing page

## Example Vault

`examples/minimal-vault/` shows the intended shape of a vault:

- `AGENTS.md` as schema
- `wiki/INDEX.md` as the navigation hub
- `wiki/LOG.md` as the maintenance trail
- `wiki/concepts/*.md` as synthesized knowledge pages
- `wiki/entities/*.md` as canonical graph nodes
- `raw/*.md` as evidence

## Open Source Docs

- `CONTRIBUTING.md`: contribution workflow and standards
- `docs/roadmap.md`: next milestones for the framework
- `docs/architecture.md`: operating model and layer boundaries

## Status

Initial open-source scaffold is complete and tested.
