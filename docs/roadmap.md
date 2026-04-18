# Roadmap

## Near Term

- Expand `kb-ingest` with local file conversion through an optional dependency while keeping the core package standard-library only.
- Add richer frontmatter helpers for entities, aliases, and change logs.
- Expand lint to catch duplicate canonical pages and unresolved aliases.
- Add CLI support for vault summaries and impacted-page reporting.
- Publish a larger example vault with entity, comparison, and timeline pages.

## Mid Term

- Add graph-oriented retrieval helpers for concept-to-entity traversal.
- Add deterministic maintenance planners for ingest and wiki updates.
- Provide packaging instructions for installing the skills into local agent environments.
- Add CI so tests and smoke checks run on every push.

## Longer Term

- Support knowledge-base migration and normalization from existing Obsidian vaults.
- Add export paths for graph-aware retrieval systems and GraphRAG pipelines.
- Offer templates for team workflows, not just solo vaults.

## 0.5.0 Propose / Validate / Inbox Loop (2026-04-18)

Phase A-min adds the smallest credible agent-assisted KB maintenance loop:

- LLM client: OpenAI-compatible via `httpx`, with no vendor SDK and config-driven profiles in `.octopus-kb/config.toml`.
- Proposal schema: `schemas/llm/proposal.json` uses per-operation `oneOf` constraints and a strict op enum for `create_page`, `add_alias`, and `append_log`.
- Declarative YAML validator chain: 7 whitelisted primitives, never executes user Python, and composes with worst-verdict-wins semantics.
- CLI: `propose` turns raw sources into structured proposals, `validate` runs the rule chain and staged apply, `recover` rolls back pending-audit crashes, and `inbox` handles human exception review with tombstoning.
- Audit-first two-phase commit: audit entries are written as `pending` before file replacements and flipped to `applied` after success or `rolled_back` after recovery.
- Provenance override: the CLI computes source SHA locally and never trusts LLM-supplied source metadata.
- Full product-loop integration coverage lives under `tests/integration/`.

### Deferred to v0.6+

- `update_body` op, because it can rewrite existing knowledge too broadly.
- `delete_page` and `rename_page` ops, because they are destructive.
- `kb stale` command for source drift detection, planned for Phase B.
- `kb rules learn` for rejection-pattern sedimentation.

## 0.4.0 Decision-Output and Skill Shelf (2026-04-18)

Phase C makes the CLI usable as an agent operating procedure instead of a loose collection of terminal helpers:

- Added decision-first CLI verbs for `lookup`, `retrieve-bundle`, and `neighbors`.
- Added `--json` output to `lint` and `impacted-pages` for agent consumers.
- Agent-facing CLI commands now have JSON Schemas under `schemas/cli/` with `additionalProperties: false`.
- Added `skills/kb/SKILL.md` with an opinionated Operating Procedure that requires retrieval, lookup, impact checks, graph context, and lint before edits finish.
- Added a Claude Code PreToolUse hook under `examples/hooks/` that soft-blocks grep on `wiki/` and `raw/` until `retrieve-bundle` has run in the current turn.

## 0.3.0 Frontmatter Schema (2026-04-18)

Phase 0 adds a shared PageMeta validation floor for humans, agents, and third-party tooling:

- PageMeta is now defined by a JSON Schema document and shipped as package data from `src/octopus_kb_compound/_schemas/`.
- The runtime validator module exposes `validate_frontmatter()` and `SchemaFinding` for schema-only checks.
- `lint_pages` now emits `SCHEMA_MISSING_FIELD`, `SCHEMA_INVALID_FIELD`, and `SCHEMA_INVALID_CONDITIONAL` alongside existing lint codes.
- The CLI includes `octopus-kb validate-frontmatter <path> [--json]` for strict frontmatter validation of files or vaults.
- `jsonschema>=4.18` is now a required runtime dependency.

## 0.2.1 Remediation (2026-04-17)

Applied the Codex 2026-04-17 review findings on the 0.2.0 roadmap release:

- lint: raw sources no longer canonicalize on `canonical_name` alone; wiki pages without a title now fall back to their path stem.
- frontmatter: user-content scalars (`tags`, `related_entities`, `workflow`, `status`, `source_of_truth`, `original_format`, `ingest_method`) are quoted for safe YAML round-trips.
- export: alias nodes deduplicated by id, `related_entities` resolved as page-to-page `wikilink` edges, artifact directory writes are atomic with backup/restore.
- migrate: in-place apply uses two-phase commit with an explicit `_replace_staged_file` boundary, rolls back modified *and* created files, and cleans up staged temp files on failure.
- migrate preflight: malformed frontmatter (opening fence without closing) is reported as `parse_failures` and blocks `--apply`.
- cli: exit codes match the plan contract (`0`/`2`/`1`). Validation factored into `_validate_vault_dir` and `_validate_page_file`.

### Deferred follow-ups

- Vault sandbox (`Path.resolve().is_relative_to(vault.resolve())`) for vault-scoped CLI commands. Requires a policy decision on whether the tool may operate on paths outside the vault.
- SSRF hardening by DNS resolution in `ingest.py`. Currently rejects literal private IPs; hostnames that resolve to private addresses are still accepted. Requires a policy decision on adding DNS to the ingest hot path.
