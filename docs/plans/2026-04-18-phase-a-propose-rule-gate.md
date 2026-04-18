# Phase A-min: Propose + Declarative Rule-Gate + Exception Inbox (MVP)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the smallest credible version of the "agent-assisted, rule-gated KB maintenance loop". An LLM proposes structured changes via `kb propose`, a **declarative** validator chain (YAML rules, never executable user Python) gates what can auto-apply vs defer vs drop, an atomic apply path writes only three safe operation types, and `kb inbox` handles exceptions. Drops: `update_body`, `stale`, `rules learn`, `.octopus-kb/rules/*.py` code execution, `--edit` during review.

**Architecture:** The product loop lives under `.octopus-kb/`:

| Directory | Purpose |
|---|---|
| `.octopus-kb/proposals/` | Append-only LLM-proposed structured diffs, one JSON per proposal |
| `.octopus-kb/audit/` | Stateful per-proposal record of applied changes (pending → applied \| rolled_back), one file per proposal |
| `.octopus-kb/inbox/` | Deferred proposals awaiting human decision |
| `.octopus-kb/rejections/` | Dropped proposals with the rule_id that killed them |
| `.octopus-kb/rules.yaml` | Declarative user rules that gate proposals |

Flow:

```
raw_source ──kb propose──▶ .proposals/<id>.json
                               │
                   ┌───────────┴──────────────┐
                   ▼                          ▼
          kb validate --dry-run      kb validate --apply
                               │
                               ▼
               [declarative validator chain]
          ├ pass  ──▶ atomic apply ──▶ vault + .audit/ + LOG.md
          ├ defer ──▶ .inbox/
          └ reject ──▶ .rejections/
                               │
                               ▼
                   kb inbox --list / --review <id>
                         --accept / --reject
```

**Tech Stack:** Python 3.11, `httpx`>=0.27, `pydantic`>=2.5, `jsonschema` (already dep from Phase 0), `pyyaml` for declarative rules. No vendor LLM SDKs. Depends on a minimal LLM client (Task 0) — a small slice of Phase B's `llm.py`.

---

## Execution Order (authoritative)

**Phase 0 (v0.3.0) → Phase C (v0.4.0) → Phase A-min (v0.5.0) → Phase B-slim (v0.6.0).**

This plan assumes Phase 0 is merged (frontmatter schema + `jsonschema` dep) and Phase C is merged (`lookup`, `retrieve-bundle`, `neighbors`, `lint --json`, skill file). Phase A-min introduces LLM-backed propose on top of those deterministic building blocks.

## Delivery Rules

- Phase 0 and Phase C must be on `main` first. Do not start Task 0 until `git log main --oneline` shows the Phase C release commit (`chore: cut 0.4.0 with SOP-first README`).
- TDD every task with a complete RED test body in Step 1.
- Proposals are append-only: written once, never mutated. Status transitions are recorded by creating new files under `inbox/`, `audit/`, or `rejections/`.
- **Audit entries are stateful, not immutable.** A single audit entry per `proposal_id` goes through states `pending → applied` (success path) or `pending → rolled_back` (crash-recovery path). Only the `status` and finalization fields (`applied_at`, `vault_sha_after`) are mutated; the ledger and `proposal_id` are immutable. State transitions use `os.replace` for atomic file rewrites. This is a deliberate safety tradeoff to eliminate the "replaced files but no audit" crash window.
- Rules are **declarative YAML only**. No Python rule files. No `exec()`. No dynamic loading of user code.
- Atomic apply constraints (Task 4):
  - Operations are staged to a sibling temp directory.
  - Backup of every file about to be modified or created is captured before any target is touched.
  - Commit phase uses `os.replace` on each staged file.
  - **Recovery:** on crash partway through commit, `kb validate --apply` re-run detects a pending audit entry (the authoritative in-progress marker under `.octopus-kb/audit/<ts>-<id>.json` with `status: "pending"`) and refuses to proceed until `kb recover <proposal_id>` (also introduced in Task 4) completes rollback using the backup captured under `staging/backup/`. The staging directory is the workspace; the pending audit is the "something is in flight" signal.
  - `kb validate --apply` on a proposal with an existing `audit/` entry exits `0` with `status: already_applied` (idempotent).
- Exit code contract: `0` success (including defer/reject/already_applied as successful decisions), `2` invalid user input (bad vault, missing proposal file), `1` LLM non-JSON output or unexpected runtime after rollback.
- Version bump to `0.5.0` at the end of Phase A-min. Do not bump earlier.

## Coverage — what is and is **not** in scope

**In scope:**
- `kb propose <raw>` — LLM → proposal JSON
- `kb validate <proposal> [--apply]` — declarative validator chain + atomic apply
- `kb recover <proposal_id>` — resume/rollback a partial apply
- `kb inbox --list | --review <id> [--accept | --reject --reason "..."]`
- Supported operations: `create_page`, `add_alias`, `append_log`
- Declarative rule DSL: a fixed set of safe check primitives (op count, confidence threshold, vault-state preconditions, schema validity, path safety). No regex execution, no arbitrary expressions in v1 — the full primitive list is in Task 2.

**Out of scope (explicitly deferred to v0.6+):**
- `update_body` op
- `add_link`, `add_related_entity` ops
- `delete_page`, `rename_page` ops
- `kb stale` command
- `kb rules learn` command
- `.octopus-kb/rules/*.py` executable rules
- `--edit prompts/propose.md` during inbox review
- Multi-file transactional atomicity beyond the documented best-effort

---

### Task 0: Minimal LLM client (shared slice)

**Files:**
- Create: `src/octopus_kb_compound/llm.py`
- Create: `src/octopus_kb_compound/config.py`
- Create: `schemas/config/v1.json`
- Create: `tests/test_llm.py`
- Create: `tests/test_config.py`
- Modify: `pyproject.toml` (add `httpx>=0.27`, `pydantic>=2.5`, `pyyaml>=6.0`)
- Modify: `CHANGELOG.md`

This task introduces the minimum LLM integration needed by `kb propose`. Full Phase B extends it; this task is a strict subset.

**`llm.py` contract:**

```python
from octopus_kb_compound.llm import ChatClient, ChatRequest, ChatResponse, LLMError

client = ChatClient(
    base_url="http://localhost:11434/v1",
    api_key=None,
    default_model="qwen2.5:7b-instruct",
    timeout=60,
    max_retries=2,
    transport=None,              # httpx.post by default; tests inject a fake
)

resp: ChatResponse = client.chat(ChatRequest(
    messages=[{"role":"user","content":"..."}],
    json_object=True,            # request response_format={"type":"json_object"} when True
    temperature=0.1,
    max_tokens=2000,
))
resp.content                      # str
resp.model
resp.input_tokens                 # int | None
resp.output_tokens                # int | None
resp.finish_reason                # str | None
```

`LLMError` subclasses:
- `LLMNetworkError` (httpx errors, retried per `max_retries`)
- `LLMAuthError` (401/403 — no retry)
- `LLMRateLimitError` (429 after retries)
- `LLMInvalidOutputError` (caller used `json_object=True` but content did not parse as JSON)

**`config.py` contract:** loads `.octopus-kb/config.toml` with named profiles and a `default_profile`. If file is missing, returns default pointing at `http://localhost:11434/v1` with model `qwen2.5:7b-instruct`. Profile resolution reads `api_key_env` from environment at resolve time. Unknown `version` → raise `ConfigError`.

- [ ] **Step 1: Write the failing tests** (LLM)

```python
from octopus_kb_compound.llm import ChatClient, ChatRequest, LLMAuthError, LLMInvalidOutputError
import pytest


def _fake_transport(status, body):
    def _call(method, url, headers, json_body, timeout):
        return status, body
    return _call


def test_chat_success_returns_content(monkeypatch):
    client = ChatClient(
        base_url="http://x/v1", api_key=None, default_model="m",
        transport=_fake_transport(200, {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "model": "m", "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }),
    )
    resp = client.chat(ChatRequest(messages=[{"role":"user","content":"hi"}]))
    assert resp.content == "hi"
    assert resp.input_tokens == 3
    assert resp.finish_reason == "stop"


def test_chat_retries_on_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def transport(method, url, headers, json_body, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return 503, {"error": "overloaded"}
        return 200, {"choices": [{"message": {"content": "ok"}}], "model": "m", "usage": {}}

    import octopus_kb_compound.llm as llm_mod
    monkeypatch.setattr(llm_mod, "_sleep", lambda s: None)

    client = ChatClient(base_url="http://x/v1", api_key=None, default_model="m",
                        max_retries=2, transport=transport)
    resp = client.chat(ChatRequest(messages=[{"role":"user","content":"hi"}]))
    assert resp.content == "ok"
    assert calls["n"] == 2


def test_chat_raises_auth_error_on_401():
    client = ChatClient(base_url="http://x/v1", api_key="bad", default_model="m",
                        transport=_fake_transport(401, {"error": "unauthorized"}))
    with pytest.raises(LLMAuthError):
        client.chat(ChatRequest(messages=[{"role":"user","content":"hi"}]))


def test_chat_invalid_output_when_json_object_requested_but_content_not_json():
    client = ChatClient(base_url="http://x/v1", api_key=None, default_model="m",
                        transport=_fake_transport(200, {
                            "choices": [{"message": {"content": "not json"}}],
                            "model": "m", "usage": {},
                        }))
    with pytest.raises(LLMInvalidOutputError):
        client.chat(ChatRequest(messages=[{"role":"user","content":"hi"}], json_object=True))


def test_chat_sends_openai_compatible_body(monkeypatch):
    captured = {}

    def transport(method, url, headers, json_body, timeout):
        captured.update({"url": url, "body": json_body, "headers": headers})
        return 200, {"choices": [{"message": {"content": "ok"}}], "model": "m", "usage": {}}

    client = ChatClient(base_url="http://x/v1", api_key="k", default_model="m", transport=transport)
    client.chat(ChatRequest(
        messages=[{"role":"user","content":"hi"}],
        temperature=0.2, max_tokens=500, json_object=True,
    ))
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["model"] == "m"
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["max_tokens"] == 500
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"] == "Bearer k"
```

- [ ] **Step 2: Write the failing tests** (config)

```python
import os
from pathlib import Path

import pytest


def test_load_config_returns_defaults_when_file_missing(tmp_path):
    from octopus_kb_compound.config import load_config
    cfg = load_config(tmp_path)
    profile = cfg.resolve_profile()
    assert profile.base_url == "http://localhost:11434/v1"
    assert profile.model == "qwen2.5:7b-instruct"
    assert profile.api_key is None


def test_load_config_reads_toml_with_profiles(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".octopus-kb"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text("""
version = 1
[llm]
default_profile = "cloud-cheap"
[llm.profiles.cloud-cheap]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "MY_KEY"
""", encoding="utf-8")
    monkeypatch.setenv("MY_KEY", "sk-xyz")

    from octopus_kb_compound.config import load_config
    cfg = load_config(tmp_path)
    profile = cfg.resolve_profile()
    assert profile.base_url == "https://api.deepseek.com/v1"
    assert profile.model == "deepseek-chat"
    assert profile.api_key == "sk-xyz"


def test_load_config_raises_on_unknown_version(tmp_path):
    cfg_dir = tmp_path / ".octopus-kb"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text("version = 999\n", encoding="utf-8")

    from octopus_kb_compound.config import ConfigError, load_config
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_config_toml_validates_against_v1_json_schema(tmp_path):
    import json
    import tomllib
    from pathlib import Path

    import jsonschema

    schema_path = Path("schemas/config/v1.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    sample = tmp_path / "config.toml"
    sample.write_text("""
version = 1
[llm]
default_profile = "cloud-cheap"
[llm.profiles.cloud-cheap]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "MY_KEY"
""", encoding="utf-8")
    data = tomllib.loads(sample.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)

    bad = {"version": 999}
    import pytest as _pytest
    with _pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_resolve_profile_by_name(tmp_path):
    cfg_dir = tmp_path / ".octopus-kb"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text("""
version = 1
[llm]
default_profile = "a"
[llm.profiles.a]
base_url = "http://a/v1"
model = "a-model"
[llm.profiles.b]
base_url = "http://b/v1"
model = "b-model"
""", encoding="utf-8")
    from octopus_kb_compound.config import load_config
    cfg = load_config(tmp_path)
    assert cfg.resolve_profile().model == "a-model"
    assert cfg.resolve_profile("b").model == "b-model"
```

- [ ] **Step 3: Run — FAIL** (`llm.py`, `config.py` missing).

- [ ] **Step 4: Implement both modules.**

`llm.py` ~150 LOC using `httpx.post` via a pluggable `transport` callable (default: `httpx.post` + response `.json()`). `_sleep = time.sleep` module-level so tests monkeypatch.

`config.py` ~80 LOC using `tomllib` (stdlib 3.11). `Config` + `Profile` pydantic BaseModels. `Config.resolve_profile(name=None)` returns a `Profile` with `api_key` read from env.

- [ ] **Step 5: Run — PASS.** Full suite also PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/llm.py src/octopus_kb_compound/config.py \
        schemas/config/v1.json tests/test_llm.py tests/test_config.py \
        pyproject.toml CHANGELOG.md
git commit -m "feat: add minimal OpenAI-compatible LLM client and config loader"
```

---

### Task 1: Proposal schema and storage

**Files:**
- Create: `schemas/llm/proposal.json`
- Create: `src/octopus_kb_compound/proposals.py`
- Create: `tests/test_proposals.py`
- Modify: `src/octopus_kb_compound/__init__.py`
- Modify: `CHANGELOG.md`

**Proposal JSON shape (MVP):**

```json
{
  "id": "2026-04-18T10-05-33-a1b2c3",
  "created_at": "2026-04-18T10:05:33+09:00",
  "source": {"kind": "raw_file", "path": "raw/new.md", "sha256": "abc..."},
  "produced_by": {
    "provider_profile": "local-large",
    "model": "qwen2.5:32b",
    "prompt_version": "prompts/propose.md@sha256:..."
  },
  "operations": [
    {"op": "create_page", "path": "wiki/concepts/Late Chunking.md",
     "frontmatter": {...}, "body": "...", "rationale": "...",
     "source_span": {"path": "...", "start_line": 1, "end_line": 10}, "confidence": 0.9},
    {"op": "add_alias", "target_page": "wiki/concepts/Late Chunking.md",
     "alias": "LC", "rationale": "...", "confidence": 0.7},
    {"op": "append_log", "path": "wiki/LOG.md",
     "entry": "2026-04-18: added Late Chunking from raw/new.md", "confidence": 1.0}
  ],
  "status": "pending"
}
```

Supported `op` enum in v1: `create_page`, `add_alias`, `append_log`. Others are schema-rejected.

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path

import pytest


def _valid_proposal():
    return {
        "id": "2026-04-18T10-05-33-abc",
        "created_at": "2026-04-18T10:05:33+00:00",
        "source": {"kind": "raw_file", "path": "raw/new.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "local", "model": "m", "prompt_version": "p@abc"},
        "operations": [
            {"op": "append_log", "path": "wiki/LOG.md",
             "entry": "2026-04-18: x", "rationale": "r", "confidence": 1.0},
        ],
        "status": "pending",
    }


def test_proposal_schema_accepts_valid_minimal_proposal():
    from octopus_kb_compound.proposals import validate_proposal_dict
    errors = validate_proposal_dict(_valid_proposal())
    assert errors == []


def test_proposal_schema_rejects_unknown_op():
    from octopus_kb_compound.proposals import validate_proposal_dict
    bad = _valid_proposal()
    bad["operations"][0]["op"] = "delete_page"
    errors = validate_proposal_dict(bad)
    assert errors, "schema must reject unsupported op values"


def test_proposal_schema_rejects_confidence_out_of_range():
    from octopus_kb_compound.proposals import validate_proposal_dict
    bad = _valid_proposal()
    bad["operations"][0]["confidence"] = 1.5
    errors = validate_proposal_dict(bad)
    assert errors


def test_proposal_save_is_atomic_and_returns_path(tmp_path):
    from octopus_kb_compound.proposals import save_proposal
    path = save_proposal(_valid_proposal(), vault_root=tmp_path)
    assert path.parent == tmp_path / ".octopus-kb" / "proposals"
    assert path.name.endswith(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "2026-04-18T10-05-33-abc"


def test_proposal_load_returns_same_bytes(tmp_path):
    from octopus_kb_compound.proposals import save_proposal, load_proposal
    path = save_proposal(_valid_proposal(), vault_root=tmp_path)
    loaded = load_proposal(path)
    assert loaded["id"] == "2026-04-18T10-05-33-abc"


def test_save_proposal_rejects_collision_with_existing_id(tmp_path):
    """Append-only storage: a duplicate id must not silently overwrite."""
    from octopus_kb_compound.proposals import save_proposal, ProposalCollisionError
    import pytest as _pytest

    save_proposal(_valid_proposal(), vault_root=tmp_path)
    with _pytest.raises(ProposalCollisionError):
        save_proposal(_valid_proposal(), vault_root=tmp_path)
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement**

`schemas/llm/proposal.json`: strict JSON Schema with `operations[].op` enum restricted to the three supported values, `confidence` in [0,1].

`proposals.py`: `validate_proposal_dict(data) -> list[str]` returning `jsonschema` error messages. `save_proposal(data, vault_root)` writes atomically (staging + `os.replace`). `load_proposal(path) -> dict`.

- [ ] **Step 4: Run — PASS. Full suite — PASS.**

- [ ] **Step 5: Commit**

```bash
git add schemas/llm/proposal.json src/octopus_kb_compound/proposals.py \
        src/octopus_kb_compound/__init__.py tests/test_proposals.py CHANGELOG.md
git commit -m "feat: add proposal schema and atomic append-only storage"
```

---

### Task 2: Declarative YAML validator chain

**Files:**
- Create: `src/octopus_kb_compound/validators/__init__.py`
- Create: `src/octopus_kb_compound/validators/declarative.py`
- Create: `src/octopus_kb_compound/validators/builtins.yaml`
- Create: `schemas/rules/v1.json`
- Create: `docs/validators.md`
- Create: `tests/test_validators.py`
- Modify: `CHANGELOG.md`

**Rule file format (`builtins.yaml` and `.octopus-kb/rules.yaml`):**

```yaml
version: 1
rules:
  - id: safety.diff_size
    description: Reject proposals that touch too many pages.
    applies_to: [create_page, add_alias, append_log]
    check:
      op_count:
        gt: 20
    verdict: reject
    reason_template: "diff size {op_count} > 20"

  - id: safety.diff_size_downgrade
    applies_to: [create_page, add_alias, append_log]
    check:
      op_count:
        gt: 5
    verdict: downgrade
    downgrade_to: medium
    reason_template: "diff size {op_count} > 5"

  - id: confidence.tier_gate_reject
    applies_to: [create_page, add_alias, append_log]
    check:
      any_op_confidence_below: 0.4
    verdict: reject
    reason_template: "an operation has confidence < 0.4"

  - id: confidence.tier_gate_defer
    applies_to: [create_page, add_alias, append_log]
    check:
      any_op_confidence_below: 0.7
    verdict: defer
    reason_template: "an operation has confidence in [0.4, 0.7)"

  - id: conflict.canonical_overlap
    applies_to: [create_page]
    check:
      vault_has_canonical_key_for_new_page: true
    verdict: reject
    reason_template: "canonical identity already exists in vault"

  - id: schema.proposal_invalid
    applies_to: [create_page, add_alias, append_log]
    check:
      proposal_schema_invalid: true
    verdict: reject
    reason_template: "proposal JSON schema invalid"

  - id: schema.page_meta_invalid
    applies_to: [create_page]
    check:
      new_frontmatter_schema_invalid: true
    verdict: reject
    reason_template: "new page frontmatter fails page-meta schema"

  - id: safety.path_escape
    applies_to: [create_page, add_alias, append_log]
    check:
      op_target_outside_vault: true
    verdict: reject
    reason_template: "operation target path escapes vault"

  - id: safety.forbidden_area
    applies_to: [create_page, add_alias, append_log]
    check:
      op_target_in_forbidden_area: true
    verdict: reject
    reason_template: "operation target is in a forbidden area (.git/, .octopus-kb/, .venv/)"
```

Supported **check primitives** in v1 (no free-form expressions, no regex execution until v0.6). Each primitive evaluates to a boolean that is `true` when the rule should **fire** (i.e., its `verdict` should apply). Primitives are named so that `true` ↔ "something is wrong" — there is never negation in the rule body.

| Primitive | Fires when... |
|---|---|
| `op_count.gt: N` | total operations in the proposal > N |
| `any_op_confidence_below: X` | any op's `confidence < X` |
| `vault_has_canonical_key_for_new_page: true` | for any `create_page` op, compute the proposed canonical key from `frontmatter.canonical_name` (if present) else `frontmatter.title` (applying the same normalization as `lint.canonical._canonical_key`); if that key already exists in the vault's canonical index, fire |
| `proposal_schema_invalid: true` | the proposal fails `schemas/llm/proposal.json` validation |
| `new_frontmatter_schema_invalid: true` | any `create_page.frontmatter` fails `schemas/page-meta.json` validation |
| `op_target_outside_vault: true` | any op target path is absolute, contains `..`, starts with `.`, or resolves outside the vault after joining |
| `op_target_in_forbidden_area: true` | any op target path is inside `.octopus-kb/`, `.git/`, `.venv/`, or matches a user-configured `forbidden_paths` list |

All rules use *positive* primitives (true = fire). There is no negation and no boolean composition in v1. A rule with multiple check fields is an AND of all listed primitives — the rule fires only when every listed primitive is true.

Any primitive not in this list → the rule loader raises `RuleSchemaError`.

**Evaluation order (important):** `evaluate_chain()` runs `schema.proposal_invalid` **first**, regardless of any op's `applies_to` list. A proposal containing only an unsupported op (e.g., `delete_page`) fails the JSON Schema check and is rejected before any `applies_to` filtering. This guarantees unknown ops never reach the apply path even when no downstream rule's `applies_to` matches. Subsequent rules are then filtered by `applies_to` per op as before. Users cannot introduce new primitives without a code change — this keeps the engine deterministic and safe.

Chain resolution: all applicable rules evaluate. Worst verdict wins (`reject > defer > downgrade > pass`). Rules emit `rule_id` + `reason` for every non-pass verdict.

- [ ] **Step 1: Write the failing tests**

```python
import yaml
from pathlib import Path

import pytest


def _fake_proposal(ops_count=1, confidence=0.9):
    return {
        "id": "x", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a"*64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [
            {"op": "append_log", "path": "wiki/LOG.md", "entry": "x",
             "rationale": "r", "confidence": confidence}
            for _ in range(ops_count)
        ],
        "status": "pending",
    }


def _dummy_vault_state():
    from octopus_kb_compound.validators.declarative import VaultState
    return VaultState(canonical_keys=set(), page_titles=set())


def test_validator_chain_rejects_oversized_diff(tmp_path):
    from octopus_kb_compound.validators.declarative import load_rules, evaluate_chain

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    verdict = evaluate_chain(_fake_proposal(ops_count=25), _dummy_vault_state(), rules)
    assert verdict.final == "reject"
    assert any(v.rule_id == "safety.diff_size" for v in verdict.rule_results)


def test_validator_chain_downgrades_medium_diff():
    from octopus_kb_compound.validators.declarative import load_rules, evaluate_chain

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    verdict = evaluate_chain(_fake_proposal(ops_count=10), _dummy_vault_state(), rules)
    assert verdict.final == "downgrade"


def test_validator_chain_defers_medium_confidence():
    from octopus_kb_compound.validators.declarative import load_rules, evaluate_chain

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    verdict = evaluate_chain(_fake_proposal(confidence=0.5), _dummy_vault_state(), rules)
    assert verdict.final == "defer"


def test_validator_chain_passes_good_proposal():
    from octopus_kb_compound.validators.declarative import load_rules, evaluate_chain

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    verdict = evaluate_chain(_fake_proposal(ops_count=1, confidence=0.9),
                             _dummy_vault_state(), rules)
    assert verdict.final == "pass"


def test_rule_loader_rejects_unknown_primitive(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("""
version: 1
rules:
  - id: bad
    applies_to: [create_page]
    check:
      nonexistent_primitive: true
    verdict: reject
    reason_template: "x"
""", encoding="utf-8")
    from octopus_kb_compound.validators.declarative import RuleSchemaError, load_rules
    with pytest.raises(RuleSchemaError):
        load_rules(path)


def test_primitive_vault_has_canonical_key_for_new_page():
    from octopus_kb_compound.validators.declarative import (
        VaultState, load_rules, evaluate_chain,
    )

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    vault_state = VaultState(
        canonical_keys={"topic"}, page_titles={"Topic"},
    )
    proposal = {
        "id": "x", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "create_page",
            "path": "wiki/concepts/topic-new.md",
            "frontmatter": {
                "title": "Topic", "type": "concept", "lang": "en",
                "role": "concept", "layer": "wiki",
                "source_of_truth": "canonical", "tags": [], "summary": "s",
            },
            "body": "#\n", "rationale": "r", "confidence": 0.95,
            "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 1},
        }],
        "status": "pending",
    }
    verdict = evaluate_chain(proposal, vault_state, rules)
    assert verdict.final == "reject"
    assert any(r.rule_id == "conflict.canonical_overlap" for r in verdict.rule_results)


def test_primitive_op_target_outside_vault():
    from octopus_kb_compound.validators.declarative import (
        VaultState, load_rules, evaluate_chain,
    )

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    proposal = {
        "id": "x", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log", "path": "../escape/LOG.md",
            "entry": "x", "rationale": "r", "confidence": 1.0,
        }],
        "status": "pending",
    }
    verdict = evaluate_chain(proposal, VaultState(canonical_keys=set(), page_titles=set()), rules)
    assert verdict.final == "reject"
    assert any(r.rule_id == "safety.path_escape" for r in verdict.rule_results)


def test_primitive_op_target_in_forbidden_area():
    from octopus_kb_compound.validators.declarative import (
        VaultState, load_rules, evaluate_chain,
    )

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    proposal = {
        "id": "x", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log", "path": ".octopus-kb/proposals/injected.md",
            "entry": "x", "rationale": "r", "confidence": 1.0,
        }],
        "status": "pending",
    }
    verdict = evaluate_chain(proposal, VaultState(canonical_keys=set(), page_titles=set()), rules)
    assert verdict.final == "reject"
    assert any(r.rule_id == "safety.forbidden_area" for r in verdict.rule_results)


def test_user_rules_file_is_loaded_additively(tmp_path):
    user = tmp_path / "rules.yaml"
    user.write_text("""
version: 1
rules:
  - id: user.my_rule
    applies_to: [append_log]
    check:
      op_count:
        gt: 0
    verdict: reject
    reason_template: "no logs allowed"
""", encoding="utf-8")
    from octopus_kb_compound.validators.declarative import load_rules, evaluate_chain

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"),
                       user_rules_path=user)
    verdict = evaluate_chain(_fake_proposal(ops_count=1, confidence=0.9),
                             _dummy_vault_state(), rules)
    assert verdict.final == "reject"
    assert any(r.rule_id == "user.my_rule" for r in verdict.rule_results)
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement** `validators/declarative.py` with `load_rules`, `evaluate_chain`, `VaultState`, `Verdict`, `RuleSchemaError`. ~200 LOC. Also write `schemas/rules/v1.json` as the rule-file JSON Schema used by `load_rules` to validate incoming YAML.

- [ ] **Step 4: Write `docs/validators.md`** documenting each supported primitive and the worst-verdict-wins rule.

- [ ] **Step 5: Run — PASS. Full suite — PASS.**

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/validators/ schemas/rules/ docs/validators.md \
        tests/test_validators.py CHANGELOG.md
git commit -m "feat: add declarative YAML validator chain (no user code exec)"
```

---

### Task 3: `kb propose` command

**Files:**
- Create: `src/octopus_kb_compound/propose.py`
- Create: `prompts/propose.md`
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `tests/test_cli.py`
- Create: `tests/test_propose.py`
- Modify: `CHANGELOG.md`

**CLI:**

```
octopus-kb propose <raw_file> --vault <vault> [--profile <name>] [--json]
```

Flow:
1. Validate vault and file (exit 2 on invalid).
2. Load config, resolve profile, build `ChatClient`.
3. Read raw file, compute sha256 locally — this is the authoritative SHA.
4. Build a small context bundle in-process by calling `retrieve.build_retrieval_bundle(raw_title, vault)` from Phase C.
5. Render `prompts/propose.md` with `{raw_path, raw_body, existing_bundle}`. The prompt tells the model *not* to populate `source` — the CLI fills it.
6. Call `client.chat(..., json_object=True)` with `temperature=0.1`, `max_tokens=4000`.
7. Parse JSON. On `LLMInvalidOutputError`, retry **once** with an appended message containing the proposal schema. On second failure, write `.octopus-kb/rejections/<ts>-llm_non_json.json`, exit `1` (runtime failure — not user input).
8. **Provenance override:** unconditionally overwrite `proposal["source"]` with `{"kind": "raw_file", "path": <relative_raw_path>, "sha256": <locally_computed_sha>}` and `proposal["produced_by"]` with the actual provider profile name, model, and `prompt_version = "prompts/propose.md@" + sha256(prompt_template_bytes)`. LLM-supplied values for these fields are ignored entirely — never trusted.
9. Validate against proposal schema. If invalid, write to `rejections/` with reason `schema_invalid`, exit `1`.
10. Save proposal to `.octopus-kb/proposals/<id>.json`, status `pending`. Exit `0`.

Stdout `--json`: `{"proposal_id": "...", "path": ".octopus-kb/proposals/<id>.json", "operations": N}`.

- [ ] **Step 1: Write the failing test**

```python
import io
import json
import sys
from pathlib import Path


def test_cli_propose_writes_proposal_file_when_llm_returns_valid_json(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    raw = vault / "raw" / "demo.md"
    raw.write_text(
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nBody text.\n', encoding="utf-8",
    )

    fake_proposal = {
        "id": "2026-04-18T10-00-00-xyz",
        "created_at": "2026-04-18T10:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/demo.md", "sha256": "a"*64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [
            {"op": "append_log", "path": "wiki/LOG.md",
             "entry": "2026-04-18: added demo", "rationale": "r", "confidence": 1.0}
        ],
        "status": "pending",
    }

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {
            "choices": [{"message": {"content": json.dumps(fake_proposal)}}],
            "model": "m", "usage": {},
        }

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["propose", str(raw), "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["operations"] == 1
    written = vault / ".octopus-kb" / "proposals" / (fake_proposal["id"] + ".json")
    assert written.exists()


def test_cli_propose_overrides_llm_provenance_with_local_sha(tmp_path, monkeypatch):
    import hashlib

    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    raw = vault / "raw" / "demo.md"
    raw_body = (
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nBody text.\n'
    )
    raw.write_text(raw_body, encoding="utf-8")
    expected_sha = hashlib.sha256(raw.read_bytes()).hexdigest()

    model_supplied_lies = {
        "id": "test-provenance",
        "created_at": "2026-04-18T10:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/WRONG.md", "sha256": "0" * 64},
        "produced_by": {"provider_profile": "MODEL_LIES", "model": "MODEL_LIES",
                        "prompt_version": "MODEL_LIES"},
        "operations": [
            {"op": "append_log", "path": "wiki/LOG.md",
             "entry": "2026-04-18: x", "rationale": "r", "confidence": 1.0}
        ],
        "status": "pending",
    }

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {
            "choices": [{"message": {"content": json.dumps(model_supplied_lies)}}],
            "model": "m", "usage": {},
        }

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main
    rc = main(["propose", str(raw), "--vault", str(vault), "--json"])
    assert rc == 0

    saved_path = vault / ".octopus-kb" / "proposals" / "test-provenance.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))

    # Provenance override: CLI must discard model's values and fill truth.
    assert saved["source"]["sha256"] == expected_sha
    assert saved["source"]["path"] == "raw/demo.md"
    assert saved["produced_by"]["provider_profile"] != "MODEL_LIES"
    assert saved["produced_by"]["prompt_version"].startswith("prompts/propose.md@sha256:")


def test_cli_propose_exits_1_on_persistent_non_json_output(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    raw = vault / "raw" / "demo.md"
    raw.write_text(
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nBody.\n', encoding="utf-8",
    )

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {"choices": [{"message": {"content": "not json"}}],
                     "model": "m", "usage": {}}

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main
    rc = main(["propose", str(raw), "--vault", str(vault)])
    assert rc == 1
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*.json"))
    assert len(rejections) == 1
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement** `propose.py` + CLI wiring + `prompts/propose.md` with a real prompt that instructs the model to return only valid JSON matching the schema. Attach the proposal schema (condensed) at the end of the prompt.

- [ ] **Step 4: Run — PASS.**

- [ ] **Step 5: Full suite — PASS.**

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/propose.py src/octopus_kb_compound/cli.py \
        prompts/propose.md tests/test_cli.py tests/test_propose.py CHANGELOG.md
git commit -m "feat: add propose command with one-shot non-JSON retry"
```

---

### Task 4: `kb validate` + atomic apply + `kb recover`

**Files:**
- Create: `src/octopus_kb_compound/apply.py`
- Create: `src/octopus_kb_compound/audit.py`
- Modify: `src/octopus_kb_compound/cli.py`
- Create: `tests/test_apply.py`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**CLI:**

```
octopus-kb validate <proposal.json> --vault <vault> [--apply] [--json]
octopus-kb recover <proposal_id> --vault <vault>
```

**Atomic apply contract — audit-first protocol (closes crash window):**

Write the audit entry *before* commit, under a `pending` flag. On success, flip the flag. On retry after crash, the pending audit tells us where we were. This removes the "replaced files but no audit" crash window Codex flagged.

**Audit filename convention (canonical):** `.octopus-kb/audit/<ts>-<proposal_id>.json` where `<ts>` is a fixed-width `YYYYMMDDHHMMSS` UTC timestamp. Helper `audit.find_entry(vault, proposal_id) -> Path | None` resolves a proposal id to its entry path (there is at most one). All code must use this helper; do not glob for `<proposal_id>-*.json`.

**Audit entry fields (required):**
- `proposal_id: str`
- `status: "pending" | "applied" | "rolled_back"`
- `created_at`: UTC ISO8601 (when the pending entry was first written)
- `source: {kind, path, sha256}` — **copied verbatim from the proposal** so downstream consumers (Phase B drift_detection) do not have to re-open the proposal file
- `applied_pages: list[str]` — the relative page paths touched by this proposal (union of `modified` + `created`)
- `created: list[str]`
- `modified: list[str]`
- `staging_path: str`
- `override: {"overridden_rules": list[str]} | null` — nested object. `null` for normal applies; populated with an object when `--accept` on an inbox entry demoted one or more rules. Chose nested shape for extensibility (future fields: `accepted_by`, `reason`).
- `applied_at: str | null` (set when `status` flips to `applied`)
- `vault_sha_after: str | null` (set when `status` flips to `applied`)

1. Load proposal.
2. If `audit.find_entry(vault, proposal_id)` returns a path with `status: "applied"` → return `{status:"already_applied"}`, exit `0`.
3. If `audit.find_entry(vault, proposal_id)` returns a path with `status: "pending"` → refuse, exit `2`, instruct user to run `kb recover <proposal_id>`.
4. Evaluate chain → verdict.
5. On `reject` → copy proposal to `.octopus-kb/rejections/<proposal_id>.json`, exit `0`.
6. On `defer` → copy to `.octopus-kb/inbox/<proposal_id>.json`, exit `0`.
7. On `pass` (or `downgrade` with `--apply`):
   1. **Write-boundary path enforcement (defense in depth):** before creating any staging path, re-normalize every op target: resolve against vault root, reject if the resolved path is outside the vault, contains `..`, or begins with `.` (hidden directory). This check duplicates `safety.path_escape` and `safety.forbidden_area` from the rule chain and runs unconditionally even if rules are misconfigured.
   2. Create `staging = .octopus-kb/staging/<proposal_id>/`.
   3. For every target file: capture backup under `staging/backup/<relpath>` if it exists; record `created: []` and `modified: []`.
   4. Write each post-op file to `staging/new/<relpath>`.
   5. Run `lint_pages` on the overlaid post-op vault. Any *new* high-severity finding → delete staging, exit `0` with `status:"rejected_post_lint"` and move proposal to rejections.
   6. Write **audit entry with `status: "pending"`** to `.octopus-kb/audit/<ts>-<proposal_id>.json`, containing the full ledger (`created`, `modified`) and `staging_path`. This is the single committed record of "apply in progress".
   7. Commit phase: for each staged target, `os.replace(staging/new/<relpath>, vault/<relpath>)`.
   8. Atomically rewrite the audit entry's `status` to `"applied"` (`os.replace` over itself) and add `applied_at`, `vault_sha_after`.
   9. Delete staging.
8. **Crash recovery (`kb recover <proposal_id>`):**
   - Read the audit entry. If `status != "pending"`, exit `0` with `status:"nothing_to_recover"`.
   - Read the ledger from the audit entry.
   - For each `modified` path: restore from `staging/backup/<relpath>` (if still present — staged file may already be committed).
   - For each `created` path: delete the file in the vault if present.
   - Delete staging.
   - Move the audit entry to `.octopus-kb/rejections/<proposal_id>.json` with reason `"crash_recovered"`, or rewrite it with `status: "rolled_back"` — choose one and document in `audit.py`. Plan mandates `status: "rolled_back"` to preserve single-source audit.
9. **`kb recover` is idempotent.** Running twice on an already-recovered proposal is a no-op.

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path


def _seed(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _write_proposal(vault: Path, proposal: dict) -> Path:
    dest = vault / ".octopus-kb" / "proposals"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{proposal['id']}.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    return path


def _append_log_proposal(id_="p1"):
    return {
        "id": id_, "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a"*64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [
            {"op": "append_log", "path": "wiki/LOG.md",
             "entry": "2026-04-18: hello", "rationale": "r", "confidence": 1.0}
        ],
        "status": "pending",
    }


def test_validate_dry_run_returns_verdict_without_writing(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--json"])
    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == "# Log\n"


def test_validate_apply_appends_log_and_writes_audit(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 0
    assert "2026-04-18: hello" in (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    audit = list((vault / ".octopus-kb" / "audit").glob("*.json"))
    assert len(audit) == 1


def test_validate_apply_is_idempotent(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    from octopus_kb_compound.cli import main
    main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    log_after_first = (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == log_after_first


def test_validate_rejects_duplicate_canonical(tmp_path):
    vault = _seed(tmp_path)
    (vault / "wiki" / "concepts").mkdir()
    (vault / "wiki" / "concepts" / "Topic.md").write_text(
        '---\ntitle: "Topic"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    bad = _append_log_proposal("p-dupe")
    bad["operations"] = [{
        "op": "create_page",
        "path": "wiki/concepts/topic-duplicate.md",
        "frontmatter": {"title": "Topic", "type": "concept", "lang": "en",
                        "role": "concept", "layer": "wiki",
                        "source_of_truth": "canonical", "tags": [],
                        "summary": "s"},
        "body": "# Topic\n",
        "rationale": "r", "confidence": 0.95,
        "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 2},
    }]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply", "--json"])
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*.json"))
    assert len(rejections) == 1


def _pending_audit_entry(proposal_id, modified, created):
    return {
        "proposal_id": proposal_id,
        "status": "pending",
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "applied_pages": sorted(set(modified) | set(created)),
        "modified": list(modified),
        "created": list(created),
        "staging_path": f".octopus-kb/staging/{proposal_id}",
        "override": None,
        "applied_at": None,
        "vault_sha_after": None,
    }


def test_validate_apply_refuses_when_pending_audit_exists(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    # Simulate a prior apply that crashed after writing pending audit but before flipping to applied.
    audit_dir = vault / ".octopus-kb" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "20260418000000-p1.json").write_text(
        json.dumps(_pending_audit_entry("p1", modified=["wiki/LOG.md"], created=[])),
        encoding="utf-8",
    )
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 2


def test_validate_apply_rejects_absolute_path_target(tmp_path):
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-abs")
    bad["operations"] = [{
        "op": "append_log", "path": "/etc/passwd", "entry": "x",
        "rationale": "r", "confidence": 1.0,
    }]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*p-abs.json"))
    assert rejections


def test_validate_apply_rejects_hidden_control_path_target(tmp_path):
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-hidden")
    bad["operations"] = [{
        "op": "create_page", "path": ".octopus-kb/proposals/injected.json",
        "frontmatter": {
            "title": "x", "type": "concept", "lang": "en", "role": "concept",
            "layer": "wiki", "tags": [], "summary": "s",
        },
        "body": "x", "rationale": "r", "confidence": 1.0,
        "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 1},
    }]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*p-hidden.json"))
    assert rejections


def test_validate_apply_creates_new_concept_page_with_audit(tmp_path):
    vault = _seed(tmp_path)
    good = _append_log_proposal("p-create")
    good["operations"] = [{
        "op": "create_page",
        "path": "wiki/concepts/Late Chunking.md",
        "frontmatter": {
            "title": "Late Chunking",
            "type": "concept",
            "lang": "en",
            "role": "concept",
            "layer": "wiki",
            "source_of_truth": "canonical",
            "tags": [],
            "summary": "Token-level late chunking for retrieval.",
        },
        "body": "# Late Chunking\n\nIntroduced in recent work.\n",
        "rationale": "New concept from source.",
        "confidence": 0.9,
        "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 10},
    }]
    proposal = _write_proposal(vault, good)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 0
    created = vault / "wiki" / "concepts" / "Late Chunking.md"
    assert created.exists()
    assert "Late Chunking" in created.read_text(encoding="utf-8")
    audit = list((vault / ".octopus-kb" / "audit").glob("*.json"))
    assert len(audit) == 1

    # Audit schema: status + source + applied_pages populated for Phase B drift_detection.
    entry = json.loads(audit[0].read_text(encoding="utf-8"))
    assert entry["status"] == "applied"
    assert entry["proposal_id"] == "p-create"
    assert entry["source"]["sha256"] == "a" * 64
    assert entry["source"]["path"] == "raw/x.md"
    assert "wiki/concepts/Late Chunking.md" in entry["applied_pages"]
    assert entry["applied_at"] is not None
    assert entry["vault_sha_after"] is not None
    # Normal (non-override) apply has no override object.
    assert entry.get("override") is None


def test_validate_apply_adds_alias_to_existing_page(tmp_path):
    vault = _seed(tmp_path)
    (vault / "wiki" / "concepts").mkdir()
    target = vault / "wiki" / "concepts" / "Topic.md"
    target.write_text(
        '---\ntitle: "Topic"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    good = _append_log_proposal("p-alias")
    good["operations"] = [{
        "op": "add_alias",
        "target_page": "wiki/concepts/Topic.md",
        "alias": "topic-alias",
        "rationale": "Used in source abstract.",
        "confidence": 0.85,
    }]
    proposal = _write_proposal(vault, good)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    assert rc == 0
    updated = target.read_text(encoding="utf-8")
    assert "topic-alias" in updated


def test_validate_rejects_path_escaping_vault(tmp_path):
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-escape")
    bad["operations"] = [{
        "op": "append_log",
        "path": "../outside/LOG.md",
        "entry": "x",
        "rationale": "r",
        "confidence": 1.0,
    }]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply", "--json"])
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*.json"))
    assert len(rejections) == 1


def test_recover_restores_modified_and_removes_created(tmp_path):
    vault = _seed(tmp_path)
    # Recovery reads the PENDING audit entry as the authoritative in-flight marker.
    staging = vault / ".octopus-kb" / "staging" / "p1"
    backup = staging / "backup"
    backup.mkdir(parents=True)
    (backup / "wiki").mkdir()
    (backup / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")

    # Mid-apply state: some commits already flipped files, some not.
    (vault / "wiki" / "LOG.md").write_text("# Partial\n", encoding="utf-8")
    (vault / "wiki" / "concepts").mkdir(exist_ok=True)
    (vault / "wiki" / "concepts" / "NewPage.md").write_text("junk", encoding="utf-8")

    # Pending audit entry — the authoritative crash marker per the audit-first contract.
    audit_dir = vault / ".octopus-kb" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "20260418000000-p1.json").write_text(
        json.dumps(_pending_audit_entry(
            "p1",
            modified=["wiki/LOG.md"],
            created=["wiki/concepts/NewPage.md"],
        )),
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main
    rc = main(["recover", "p1", "--vault", str(vault)])
    assert rc == 0
    # Backup restored:
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == "# Log\n"
    # Created file deleted:
    assert not (vault / "wiki" / "concepts" / "NewPage.md").exists()
    # Staging cleaned up:
    assert not staging.exists()
    # Audit entry transitioned from pending to rolled_back:
    audit = json.loads((audit_dir / "20260418000000-p1.json").read_text(encoding="utf-8"))
    assert audit["status"] == "rolled_back"


def test_recover_is_idempotent_on_nothing_to_recover(tmp_path):
    vault = _seed(tmp_path)
    from octopus_kb_compound.cli import main
    rc = main(["recover", "nonexistent", "--vault", str(vault)])
    assert rc == 0


def test_validate_rejects_proposal_with_unsupported_op(tmp_path):
    """Schema validation must block an unknown op BEFORE any rule applies_to filtering."""
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-unknown-op")
    # delete_page is intentionally not in the v1 supported op enum.
    bad["operations"] = [{
        "op": "delete_page", "path": "wiki/concepts/Topic.md",
        "rationale": "r", "confidence": 1.0,
    }]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply", "--json"])
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*p-unknown-op.json"))
    assert rejections, "unsupported op must be rejected by schema.proposal_invalid"
    # No staging/apply side effects on the vault.
    assert not (vault / ".octopus-kb" / "audit").exists() or not any(
        (vault / ".octopus-kb" / "audit").glob("*p-unknown-op.json")
    )
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement** `apply.py` (staging + commit + rollback) and `audit.py` (append audit entries). Hook into `cli.py`.

- [ ] **Step 4: Run — PASS. Full suite — PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/octopus_kb_compound/apply.py src/octopus_kb_compound/audit.py \
        src/octopus_kb_compound/cli.py tests/test_apply.py tests/test_cli.py CHANGELOG.md
git commit -m "feat: add validate/apply/recover commands with staged atomic apply"
```

---

### Task 5: `kb inbox` command

**Files:**
- Create: `src/octopus_kb_compound/inbox.py`
- Modify: `src/octopus_kb_compound/apply.py` (extend `apply_proposal(...)` to accept `override: {overridden_rules: [...]} | None`; write it into the audit entry)
- Modify: `src/octopus_kb_compound/audit.py` (ensure `override` field is serialized; `null` for normal applies)
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `src/octopus_kb_compound/validators/builtins.yaml` (add `human_overridable: true` to `safety.diff_size_downgrade` and `confidence.tier_gate_defer`; default for all others remains `false`)
- Modify: `schemas/rules/v1.json` (add optional `human_overridable: boolean` field to each rule, defaulting to `false`)
- Modify: `src/octopus_kb_compound/validators/declarative.py` (thread the `human_overridable` flag from rule into `evaluate_chain(..., human_override=False)` behavior; expose `overridden_rules: list[str]` on the returned verdict)
- Create: `tests/test_inbox.py`
- Modify: `tests/test_validators.py` (add one test asserting `evaluate_chain(..., human_override=True)` demotes overridable defers to pass)
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**CLI:**

```
octopus-kb inbox --vault <vault> --list [--json]
octopus-kb inbox --vault <vault> --review <id> [--json]
octopus-kb inbox --vault <vault> --review <id> --accept
octopus-kb inbox --vault <vault> --review <id> --reject --reason "..."
```

**Human override contract (explicit):** Each rule in `builtins.yaml` is tagged with `human_overridable: true|false` (new optional field, defaults to `false`). `--accept` re-runs the chain in override mode: rules with `human_overridable: true` whose verdict is `downgrade` or `defer` are demoted to `pass`. All `reject` verdicts and any rule with `human_overridable: false` remain in force. The audit entry records `override: {overridden_rules: [...]}` so human intervention is traceable.

**Inbox tombstoning (no zombie entries):** `--accept` and `--reject` both remove the source file from `.octopus-kb/inbox/` after a terminal decision. `--accept` followed by successful apply writes the audit entry and deletes `inbox/<id>.json`. `--accept` followed by hard-reject moves the entry to `rejections/` and deletes the inbox copy. `--reject` always moves to `rejections/` and deletes the inbox copy. This guarantees `kb inbox --list` never re-surfaces a decided proposal.

Phase A-min default overridables: `safety.diff_size_downgrade` and `confidence.tier_gate_defer` are `human_overridable: true`. Everything else is `false`.

- [ ] **Step 1: Write the failing tests** (full bodies)

First, add a direct validator unit test to `tests/test_validators.py`:

```python
def test_evaluate_chain_human_override_demotes_overridable_defer():
    from pathlib import Path
    from octopus_kb_compound.validators.declarative import (
        VaultState, load_rules, evaluate_chain,
    )

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    state = VaultState(canonical_keys=set(), page_titles=set())
    proposal = {
        "id": "x", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log", "path": "wiki/LOG.md",
            "entry": "x", "rationale": "r", "confidence": 0.5,
        }],
        "status": "pending",
    }
    # Without override: defers.
    v_default = evaluate_chain(proposal, state, rules)
    assert v_default.final == "defer"
    # With override: overridable defer demotes to pass; verdict exposes overridden_rules list.
    v_override = evaluate_chain(proposal, state, rules, human_override=True)
    assert v_override.final == "pass"
    assert "confidence.tier_gate_defer" in v_override.overridden_rules
    # overridden_rules is a plain list so apply.py can pass it into the audit entry as
    # {"override": {"overridden_rules": v_override.overridden_rules}} without reshaping.


def test_evaluate_chain_human_override_cannot_demote_hard_reject():
    from pathlib import Path
    from octopus_kb_compound.validators.declarative import (
        VaultState, load_rules, evaluate_chain,
    )

    rules = load_rules(Path("src/octopus_kb_compound/validators/builtins.yaml"))
    state = VaultState(canonical_keys=set(), page_titles=set())
    proposal = {
        "id": "x", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log", "path": "../outside/LOG.md",
            "entry": "x", "rationale": "r", "confidence": 0.95,
        }],
        "status": "pending",
    }
    v = evaluate_chain(proposal, state, rules, human_override=True)
    assert v.final == "reject"
    assert any(r.rule_id == "safety.path_escape" for r in v.rule_results)
```

Then inbox CLI tests (also `tests/test_inbox.py`):

```python
import io
import json
import sys
from pathlib import Path


def _seed(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _medium_conf_proposal():
    return {
        "id": "pd1", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log", "path": "wiki/LOG.md",
            "entry": "2026-04-18: medium", "rationale": "r", "confidence": 0.5,
        }],
        "status": "pending",
    }


def _hard_reject_proposal():
    return {
        "id": "pe1", "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [{
            "op": "append_log", "path": "../escape.md",
            "entry": "x", "rationale": "r", "confidence": 0.95,
        }],
        "status": "pending",
    }


def _write_to_inbox(vault: Path, proposal: dict) -> Path:
    inbox = vault / ".octopus-kb" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{proposal['id']}.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    return path


def test_inbox_list_emits_deferred_proposals_json(tmp_path):
    vault = _seed(tmp_path)
    _write_to_inbox(vault, _medium_conf_proposal())
    from octopus_kb_compound.cli import main
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["inbox", "--vault", str(vault), "--list", "--json"])
    finally:
        sys.stdout = original
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["count"] == 1
    assert data["deferred"][0]["id"] == "pd1"


def test_inbox_review_shows_validator_verdicts(tmp_path):
    vault = _seed(tmp_path)
    _write_to_inbox(vault, _medium_conf_proposal())
    from octopus_kb_compound.cli import main
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["inbox", "--vault", str(vault), "--review", "pd1", "--json"])
    finally:
        sys.stdout = original
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert any(r["rule_id"] == "confidence.tier_gate_defer" for r in data["rule_results"])


def test_inbox_accept_applies_when_only_overridable_defers_block(tmp_path):
    vault = _seed(tmp_path)
    _write_to_inbox(vault, _medium_conf_proposal())
    from octopus_kb_compound.cli import main
    rc = main(["inbox", "--vault", str(vault), "--review", "pd1", "--accept"])
    assert rc == 0
    assert "2026-04-18: medium" in (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    audit = list((vault / ".octopus-kb" / "audit").glob("*pd1.json"))
    assert audit, "audit entry must be written after override-apply"
    entry = json.loads(audit[0].read_text(encoding="utf-8"))
    assert "confidence.tier_gate_defer" in entry["override"]["overridden_rules"]
    # Tombstoning: inbox copy removed after terminal decision.
    assert not (vault / ".octopus-kb" / "inbox" / "pd1.json").exists()


def test_inbox_accept_still_blocked_by_hard_reject(tmp_path):
    vault = _seed(tmp_path)
    _write_to_inbox(vault, _hard_reject_proposal())
    from octopus_kb_compound.cli import main
    rc = main(["inbox", "--vault", str(vault), "--review", "pe1", "--accept", "--json"])
    # rc stays 0 (successful decision); proposal moves to rejections, not applied.
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*pe1.json"))
    assert rejections
    assert "# Log" == (vault / "wiki" / "LOG.md").read_text(encoding="utf-8").rstrip()


def test_inbox_reject_moves_to_rejections_with_reason(tmp_path):
    vault = _seed(tmp_path)
    _write_to_inbox(vault, _medium_conf_proposal())
    from octopus_kb_compound.cli import main
    rc = main(["inbox", "--vault", str(vault), "--review", "pd1",
               "--reject", "--reason", "out of scope"])
    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*pd1.json"))
    assert rejections
    entry = json.loads(rejections[0].read_text(encoding="utf-8"))
    assert entry["reason"] == "out of scope"
    assert entry["source"] == "human_rejected"
    assert not (vault / ".octopus-kb" / "inbox" / "pd1.json").exists()
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement `inbox.py` and CLI wiring.**
- [ ] **Step 4: Run — PASS. Full suite — PASS.**
- [ ] **Step 5: Commit.**

```bash
git add src/octopus_kb_compound/inbox.py src/octopus_kb_compound/cli.py \
        src/octopus_kb_compound/apply.py src/octopus_kb_compound/audit.py \
        src/octopus_kb_compound/validators/builtins.yaml \
        src/octopus_kb_compound/validators/declarative.py \
        schemas/rules/v1.json \
        tests/test_inbox.py tests/test_cli.py tests/test_validators.py CHANGELOG.md
git commit -m "feat: add inbox command for human exception handling"
```

---

### Task 6: End-to-end integration test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_propose_to_audit_loop.py`
- Modify: `CHANGELOG.md`

A single pytest test that exercises the full loop: seed vault → write raw file → mock LLM transport → `propose` → `validate --apply` → assert page created and audit entry → re-run apply, assert idempotent.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_propose_to_audit_loop.py
import hashlib
import io
import json
import sys
from pathlib import Path


def test_full_loop_propose_validate_apply_creates_page_and_is_idempotent(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "raw").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    raw = vault / "raw" / "demo.md"
    raw_body = (
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nA document about Late Chunking.\n'
    )
    raw.write_text(raw_body, encoding="utf-8")

    # Build a proposal object whose source fields will be *overwritten* by the CLI.
    # The CLI trusts the local file SHA, not the model's.
    proposal_payload = {
        "id": "loop-001",
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "WRONG", "sha256": "WRONG"},
        "produced_by": {"provider_profile": "WRONG", "model": "WRONG", "prompt_version": "WRONG"},
        "operations": [
            {
                "op": "create_page",
                "path": "wiki/concepts/Late Chunking.md",
                "frontmatter": {
                    "title": "Late Chunking", "type": "concept", "lang": "en",
                    "role": "concept", "layer": "wiki",
                    "source_of_truth": "canonical", "tags": [],
                    "summary": "Token-level late chunking.",
                },
                "body": "# Late Chunking\n\nBody.\n",
                "rationale": "r",
                "source_span": {"path": "raw/demo.md", "start_line": 1, "end_line": 3},
                "confidence": 0.9,
            },
            {
                "op": "append_log",
                "path": "wiki/LOG.md",
                "entry": "2026-04-18: added Late Chunking from raw/demo.md",
                "rationale": "r",
                "confidence": 1.0,
            },
        ],
        "status": "pending",
    }

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {
            "choices": [{"message": {"content": json.dumps(proposal_payload)}}],
            "model": "m", "usage": {},
        }

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main

    # Step: propose
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["propose", str(raw), "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original
    assert rc == 0
    out = json.loads(buf.getvalue())
    proposal_path = vault / ".octopus-kb" / "proposals" / f"{out['proposal_id']}.json"
    assert proposal_path.exists()

    # Provenance was overridden: check the saved proposal has the real SHA.
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    expected_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    assert saved["source"]["sha256"] == expected_sha
    assert saved["source"]["path"] == "raw/demo.md"

    # Step: validate --apply
    rc = main(["validate", str(proposal_path), "--vault", str(vault), "--apply"])
    assert rc == 0
    created = vault / "wiki" / "concepts" / "Late Chunking.md"
    assert created.exists()
    assert "Late Chunking" in (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    audit_dir = vault / ".octopus-kb" / "audit"
    audit_before = list(audit_dir.glob("*.json"))
    assert len(audit_before) == 1

    # No stray staging files.
    staging = vault / ".octopus-kb" / "staging"
    assert not staging.exists() or not any(staging.iterdir())

    # Step: re-run apply → idempotent
    log_after_first = (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    rc = main(["validate", str(proposal_path), "--vault", str(vault), "--apply", "--json"])
    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == log_after_first
    audit_after = list(audit_dir.glob("*.json"))
    assert len(audit_after) == 1
```

- [ ] **Step 2: Run — FAIL** (depends on prior tasks being complete).
- [ ] **Step 3: Verify all prior tasks are merged; run test — PASS.**
- [ ] **Step 4: Commit.**

```bash
git add tests/integration/ CHANGELOG.md
git commit -m "test: add propose-to-audit loop integration test"
```

---

### Task 7: Skill update + `0.5.0` release

**Files:**
- Modify: `skills/kb/SKILL.md` (add 3 new steps)
- Create: `skills/kb/recipes/kb-propose.md`
- Create: `skills/kb/recipes/kb-inbox.md`
- Modify: `README.md`
- Modify: `pyproject.toml` (version → `0.5.0`)
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

Add to `SKILL.md` Operating Procedure (after step 5):

```
6. To ingest a raw source into the KB:
   octopus-kb propose raw/<file> --vault . --json
   octopus-kb validate .octopus-kb/proposals/<id>.json --vault . --apply --json

7. At least weekly, triage deferred proposals:
   octopus-kb inbox --vault . --list --json

8. If a `validate --apply` run is interrupted, recover before retrying:
   octopus-kb recover <proposal_id> --vault .
```

- [ ] **Step 1: Update `skills/kb/SKILL.md`** — append the 3 new steps (6, 7, 8) under Operating Procedure. Re-run the existing `test_kb_skill_file_has_required_sections` test to confirm the file still parses.

- [ ] **Step 2: Write the two new recipe files** (`kb-propose.md`, `kb-inbox.md`) each with: one-sentence description, exact command, one example input → output stub.

- [ ] **Step 3: Update `README.md`** to list `propose`, `validate`, `recover`, `inbox` in the command reference and add one-paragraph "How the propose loop works" section.

- [ ] **Step 4: Bump `pyproject.toml` to `0.5.0` and move Unreleased CHANGELOG entries under `## [0.5.0] - 2026-04-18`.**

- [ ] **Step 5: Update `docs/roadmap.md`** with a `## 0.5.0 Propose / Validate / Inbox Loop (2026-04-18)` section summarizing the new commands and the rule-gate model.

- [ ] **Step 6: Smoke test on the example vault:**

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest tests/integration -q
PYTHONPATH=src python -m octopus_kb_compound.cli --help
PYTHONPATH=src python -m octopus_kb_compound.cli inbox --vault examples/minimal-vault --list --json
```

All exit `0`. Integration test passes end-to-end (it mocks the LLM transport in-process — no external fixture file needed). CLI `--help` lists `propose`, `validate`, `recover`, `inbox`.

- [ ] **Step 7: Commit**

```bash
git add skills/kb/ README.md pyproject.toml CHANGELOG.md docs/roadmap.md
git commit -m "chore: cut 0.5.0 with propose/validate/inbox/recover loop"
```

---

## Execution Notes

- LLM output is never trusted for direct vault mutation. Only path: LLM → JSON schema → declarative chain → staged apply → atomic commit → audit.
- `.octopus-kb/` is not git-tracked by default. Document this choice in README.
- Rules can be user-extended by editing `.octopus-kb/rules.yaml`; unknown check primitives fail schema load (exit 2).
- Recovery is resume-safe: running `recover` on a non-existent staging is a no-op.

## Final Verification

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest tests/integration -q
PYTHONPATH=src python -m octopus_kb_compound.cli --help
```

Help lists: `propose`, `validate`, `recover`, `inbox`, plus everything from prior phases. All tests pass. Integration test asserts full loop works end-to-end with a mocked LLM.
