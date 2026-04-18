# Changelog

## Unreleased

### Fixed

- fix: gate canonical identity for raw sources; add wiki path-stem fallback.

### Added

- Roadmap implementation execution plan and CLI baseline regression guard.
- Structured page metadata helpers for concept, entity, comparison, timeline, and changelog pages.
- Lint checks for duplicate canonical pages, unresolved frontmatter aliases, and canonical alias collisions.
- `vault-summary` CLI command for deterministic vault counts, entry presence, and lint finding summaries.
- `impacted-pages` CLI command for deterministic maintenance impact discovery.
- Version bump to `0.2.0` for the expanded public CLI and metadata/lint contract.
- Deterministic retrieval bundle helpers for schema, index, concept, entity, and raw-source traversal.
- Non-mutating maintenance planner and `plan-maintenance` CLI command for follow-up actions.
- Vault migration inspection and staged frontmatter normalization commands with conservative safety defaults.
- Graph export artifacts and `export-graph` CLI command for nodes, edges, manifests, and aliases.
- Expanded example vault and operator documentation for team workflows.

## v0.1.0 - 2026-04-05

First public release of `octopus-kb-compound`.

### Added

- `kb-retrieve` skill for schema-first, evidence-backed retrieval
- `kb-maintain` skill for ingest, metadata, links, and lint workflows
- Obsidian graph prompt pack with canonical linking policy
- Deterministic Python helpers for frontmatter, links, linting, vault scanning, and profile loading
- `octopus-kb` CLI with `lint` and `suggest-links`
- Minimal example vault with schema, index, log, concept, entity, and raw source pages
- Production-vault bootstrap script and production profile documentation
- GitHub Actions CI for pytest and CLI smoke checks

### Changed

- Link resolution now understands aliases, file stems, and relative path-style wikilinks
- Lint ignores folder-like targets and code-block pseudo links
- Vault scanning supports root profile excludes via `.octopus-kb.yml`

### Fixed

- CRLF frontmatter parsing
- Single-quoted frontmatter values
- Backslash escaping in rendered YAML
- Whitespace-only summaries emitting invalid YAML
- CLI handling for missing vault/page paths
