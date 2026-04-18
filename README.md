# octopus-kb-compound

> The agent's operating procedure for Obsidian-style knowledge bases.

Instead of letting agents grep your vault, octopus-kb returns **decisions**: canonical identity, ordered evidence bundles, graph context, impact plans, and rule-gated LLM-assisted maintenance.

**Version:** 0.6.0 · **Tests:** 200 · **Python:** 3.11+ · **License:** see repo

---

## What It Does

1. **Deterministic core** — canonical pages, alias resolution, wikilink graph, frontmatter schema, atomic migration.
2. **Agent-facing decision CLI** — every command returns schema-validated JSON so agents don't fall back to grep.
3. **Rule-gated LLM propose loop** — LLMs *propose* changes, declarative YAML rules gate what auto-applies, the inbox handles exceptions.
4. **Deterministic eval harness** — pure-Python grep vs octopus-kb baseline, bit-identical across platforms.

No LLM vendor lock-in. Any OpenAI-compatible endpoint works (local Ollama, DeepSeek, Gemini, Anthropic via compat, etc.).

---

## Install

```bash
git clone <this-repo>
cd octopus-kb-compound
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q                                          # 200 passed
octopus-kb --help
```

No-install smoke check:

```bash
PYTHONPATH=src python3 -m octopus_kb_compound.cli --help
```

---

## Quickstart (5-command Agent Loop)

```bash
# 1. Before grepping the vault, ask for an ordered evidence bundle
octopus-kb retrieve-bundle "how does RAG ops handle stale indexes" --vault . --json

# 2. Before creating a page or alias, resolve the canonical identity
octopus-kb lookup "RAG Ops" --vault . --json

# 3. Understand a page's graph neighborhood before editing it
octopus-kb neighbors wiki/concepts/RAG\ Operations.md --vault . --json

# 4. Before editing, find all pages that would be affected
octopus-kb impacted-pages wiki/concepts/RAG\ Operations.md --vault . --json

# 5. Lint before finishing
octopus-kb lint . --json
```

---

## Command Reference

All agent-facing commands accept `--json` for structured output validated against schemas under `schemas/cli/`.
Exit codes: `0` success · `1` runtime error (or findings for `lint`) · `2` invalid user input.

### Agent Decision Verbs

Commands designed to be the first call an agent makes, before `grep`/`read`.

| Command | Purpose |
|---|---|
| `octopus-kb lookup <term> --vault <v> [--json]` | Resolve a term to canonical page + aliases; report ambiguity |
| `octopus-kb retrieve-bundle <query> --vault <v> [--max-tokens N] [--json]` | Ordered evidence: `schema → index → concepts → entities → raw_sources`. Trim drops `raw_sources` first, then `entities` |
| `octopus-kb neighbors <page> --vault <v> [--json]` | Inbound/outbound wikilinks + `related_entities`, aliases, canonical identity |
| `octopus-kb impacted-pages <page> --vault <v> [--json]` | Pages likely affected by a change (including INDEX/LOG) |

### Propose Loop (LLM-assisted maintenance)

```
raw source ──propose──▶ .proposals/<id>.json
                │
                ▼
     declarative YAML rule chain
     ├─ reject → .rejections/    (hard fail, with rule_id)
     ├─ defer  → .inbox/         (human triage)
     └─ pass   → staged apply → vault + .audit/
```

| Command | Purpose |
|---|---|
| `octopus-kb propose <raw.md> --vault <v> [--profile name] [--json]` | LLM proposes structured diff; provenance (SHA + prompt version) computed locally, never trusted from model |
| `octopus-kb validate <proposal.json> --vault <v> [--apply] [--json]` | Run rule chain; with `--apply`, stage + atomic-commit + audit entry |
| `octopus-kb recover <proposal_id> --vault <v>` | Roll back an apply interrupted mid-commit (uses pending-audit marker) |
| `octopus-kb inbox --vault <v> --list [--json]` | List deferred proposals |
| `octopus-kb inbox --vault <v> --review <id> [--accept \| --reject --reason "…"] [--json]` | Human triage: accept re-runs chain with override; hard rejects still block |

Supported ops in v1: `create_page`, `add_alias`, `append_log`. Risky ops (`update_body`, `delete_page`, `rename_page`) deferred to v0.7+.

### Maintenance

| Command | Purpose |
|---|---|
| `octopus-kb lint <vault> [--json]` | Schema findings + broken links + alias collisions + orphans |
| `octopus-kb validate-frontmatter <path> [--json]` | Strict parse + PageMeta JSON Schema findings (file or directory) |
| `octopus-kb vault-summary <vault>` | Page counts by role/layer, entry-file presence, lint summary |
| `octopus-kb plan-maintenance <page> --vault <v>` | Non-mutating follow-up actions after a page change |
| `octopus-kb suggest-links <page> --vault <v>` | Propose canonical wikilinks for an existing page |

### Ingestion

| Command | Purpose |
|---|---|
| `octopus-kb ingest-url <url> --vault <v> [--tags t1,t2] [--lang zh]` | Fetch a public URL via Jina Reader → `raw/*.md`. Rejects localhost and private IPs |
| `octopus-kb ingest-file <path> --vault <v> [--tags t1,t2] [--lang zh]` | Convert a local file via `markitdown` → `raw/*.md` |

### Migration / Export

| Command | Purpose |
|---|---|
| `octopus-kb inspect-vault <vault>` | Read-only migration preview: malformed frontmatter, missing entry files |
| `octopus-kb normalize-vault <vault> [--apply] [--in-place]` | Staged-by-default migration. `--in-place` requires `--apply` and uses backup+rollback |
| `octopus-kb export-graph <vault> --out <dir>` | Atomic export: `nodes.json` + `edges.json` + `manifest.json` + `aliases.json` |

### Eval Harness

Deterministic benchmark: pure-Python grep vs `octopus-kb` path, no subprocess, bit-identical across platforms.

| Command | Purpose |
|---|---|
| `octopus-kb eval run --tasks <tasks.yaml> --out <dir> [--json]` | Execute a task suite; writes per-task deterministic JSON + `summary.md`; ephemeral `*.metrics.json` (gitignored) carry latency |
| `octopus-kb eval report --run <dir> [--format markdown]` | Re-render `summary.md` from prior run artifacts |

See `docs/benchmarks/v1.md` for the committed v1 baseline under `eval/runs/2026-04-18-baseline/`.

---

## Configuration

LLM provider is config-driven. `.octopus-kb/config.toml` in the vault root:

```toml
version = 1

[llm]
default_profile = "local-large"

[llm.profiles.local-small]
base_url = "http://localhost:11434/v1"
model = "qwen2.5:7b-instruct"
# api_key_env = ""    # empty / omitted → no auth

[llm.profiles.local-large]
base_url = "http://localhost:11434/v1"
model = "qwen2.5:32b-instruct"
timeout = 180

[llm.profiles.cloud-cheap]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"

[llm.profiles.cloud-strong]
base_url = "https://api.anthropic.com/v1"
model = "claude-haiku-4-5"
api_key_env = "ANTHROPIC_API_KEY"
```

Override per-call: `octopus-kb propose raw/foo.md --vault . --profile cloud-cheap`.

Prompts are files — edit `prompts/propose.md` to change the proposer's instructions.

---

## Validator Rules (declarative, YAML only)

Rules in `src/octopus_kb_compound/validators/builtins.yaml` + optional user rules in `.octopus-kb/rules.yaml`. **Never** executable Python. v1 primitives:

| Primitive | Fires when |
|---|---|
| `op_count.gt: N` | Total ops > N |
| `any_op_confidence_below: X` | Any op confidence < X |
| `vault_has_canonical_key_for_new_page: true` | `create_page` duplicates an existing canonical identity |
| `proposal_schema_invalid: true` | Proposal fails JSON Schema (runs first, before `applies_to` filter) |
| `new_frontmatter_schema_invalid: true` | `create_page` frontmatter fails PageMeta schema |
| `op_target_outside_vault: true` | Target is absolute, contains `..`, or starts with `.` |
| `op_target_in_forbidden_area: true` | Target under `.octopus-kb/`, `.git/`, `.venv/` |

Worst verdict wins: `reject > defer > downgrade > pass`. Rules tagged `human_overridable: true` can be demoted via `inbox --accept`; hard rejects cannot.

See `docs/validators.md`.

---

## Agent Skill Integration

### Claude Code

1. Copy or reference `skills/kb/SKILL.md` (opinionated SOP, not a menu).
2. Optional: install the PreToolUse grep guard — see `docs/hooks/claude-code-pretooluse.md`. It reminds agents to run `retrieve-bundle` before grepping `wiki/` or `raw/` by checking a marker file that `retrieve-bundle` touches.
3. Sample `settings.json` under `examples/.claude/`.

### Codex / others

Point your skill directory at `skills/kb/SKILL.md` and use recipes in `skills/kb/recipes/`.

The skill tells agents:

- Before `Grep`/`Read` on `wiki/` or `raw/` → run `retrieve-bundle`.
- Before creating a page/alias → run `lookup`.
- Before editing a page → run `impacted-pages`.
- To ingest a raw source → `propose` then `validate --apply`.
- Weekly → `inbox --list` to triage.

---

## Vault Layout

```
my-vault/
├── AGENTS.md              # schema anchor (operator SOP)
├── wiki/
│   ├── INDEX.md           # navigation hub
│   ├── LOG.md             # maintenance trail
│   ├── concepts/          # synthesized knowledge pages
│   ├── entities/          # canonical graph nodes
│   ├── comparisons/       # A-vs-B pages
│   └── timelines/         # chronological pages
├── raw/                   # immutable evidence (raw sources)
├── .octopus-kb/
│   ├── config.toml        # LLM provider profiles
│   ├── rules.yaml         # (optional) user validator rules
│   ├── proposals/         # LLM-proposed diffs
│   ├── audit/             # stateful per-proposal record (pending→applied|rolled_back)
│   ├── inbox/             # deferred proposals
│   ├── rejections/        # hard-rejected proposals with rule_id
│   └── staging/           # in-flight apply workspace
```

`examples/minimal-vault/` and `examples/expanded-vault/` ship as reference shapes.

---

## Design Principles

- **Curation over extraction.** The wiki is a persistent synthesis layer, not disposable RAG context.
- **Decisions over data.** CLI returns canonical identity, ordered bundles, next-command hints — not grep-style match lines.
- **Deterministic gates, LLM proposals.** LLMs propose; declarative rules decide; humans see exceptions.
- **Never trust LLM provenance.** `source.sha256` and `prompt_version` computed locally, always.
- **Audit-first commit.** Pending audit written *before* file replacements. Crash recovery reads the pending audit as authoritative.
- **No vendor lock-in.** OpenAI-compat HTTP only. Swap providers by editing `config.toml`.

---

## Release History

| Version | Focus | Tests |
|---|---|---|
| 0.6.0 | Deterministic eval harness | 200 |
| 0.5.0 | Propose / validate / inbox / recover loop | 180 |
| 0.4.0 | Skill shelf + decision-level JSON outputs + PreToolUse hook | 129 |
| 0.3.0 | PageMeta JSON Schema + validate-frontmatter | 104 |
| 0.2.1 | Remediation batch (atomicity, rollback, alias dedup) | 85 |
| 0.2.0 | Operator CLI expansion + metadata & lint model | 70 |
| 0.1.0 | Initial scaffold | — |

See `CHANGELOG.md` and `docs/roadmap.md` for details.

---

## Docs

- `docs/roadmap.md` — release-by-release roadmap
- `docs/architecture.md` — operating model and layer boundaries
- `docs/validators.md` — rule chain primitives reference
- `docs/benchmarks/v1.md` — v1 deterministic benchmark
- `docs/hooks/claude-code-pretooluse.md` — grep-guard hook install
- `docs/production-vault.md` — adopt the framework in an existing vault
- `CONTRIBUTING.md` — contribution workflow

---

## Status

0.6.0 delivered: deterministic core + agent decision CLI + rule-gated LLM propose loop + eval baseline.

Contributions welcome. Issues and PRs on the upstream repo.
