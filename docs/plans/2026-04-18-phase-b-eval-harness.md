# Phase B-slim: Deterministic Eval Harness

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quantify octopus-kb's value with a deterministic evaluation harness that compares `grep` vs `octopus-kb` on three task classes over a committed reference corpus. Emit a reproducible benchmark report that the project can regenerate on every PR. No human rating, no multi-provider matrix, no graphify comparison — those are v0.7+ extensions.

**Architecture:** A small `eval` subsystem reads a YAML task suite, runs each task through two paths in-process (no network), and emits per-task JSON + a markdown summary. The corpus is a committed small vault under `eval/corpora/small-vault/`. Scoring is deterministic: exact match for fact lookup, F1 for set retrieval, precision/recall for drift detection. LLM-involving tasks are deferred.

**Tech Stack:** Python 3.11, existing `pytest`, `pyyaml` for task files, pure-Python substring scan for the `grep` path, in-process calls to `octopus-kb` CLI via `main()`. No `subprocess`, no shell-out, no `httpx` in the harness.

---

## Delivery Rules

- Phase 0, Phase C, and Phase A-min must be on `main` first.
- TDD every task with complete RED test bodies.
- The harness must be deterministic: same corpus + same seed + same commit → bit-identical output.
- No network calls in any test or the harness itself. The `octopus-kb propose` path is **not** in the Phase B matrix (it requires LLM). Only deterministic CLI verbs participate.
- Version bump to `0.6.0` at the end. Do not bump earlier.

## Coverage — task classes

| Class | Example | Deterministic scoring |
|---|---|---|
| `fact_lookup` | "What is the canonical path for alias 'RAG Ops'?" | Exact string match on canonical path |
| `relationship_trace` | "What entities relate to RAG Operations?" | F1 over expected set of entity paths |
| `drift_detection` | "Which pages have audit entries with out-of-date source SHA?" | Precision + recall over expected page paths |

The `drift_detection` class depends on `.octopus-kb/audit/` from Phase A-min. The harness reads audit entries and recomputes SHAs against `source.path` — no LLM needed.

## Out of Scope (explicit v0.7+ items)

- Graphify path adapter
- Human rating (`eval rate`) subcommand
- Multi-provider benchmarking (local-small / local-large / cloud-cheap / cloud-strong)
- Answer-quality measurement via LLM judge
- Benchmark CI integration

---

### Task 1: Reference corpus

**Files:**
- Create: `eval/corpora/small-vault/` (15-20 markdown files covering all page types)
- Create: `eval/corpora/small-vault/.octopus-kb/audit/` (pre-seeded audit entries for drift_detection)
- Create: `eval/corpora/README.md`
- Create: `tests/test_eval_corpus.py`
- Modify: `CHANGELOG.md`

The corpus is checked into git. It must lint-clean (zero high-severity lint findings) so that eval runs start from a valid baseline. At least one page's audit entry points at a raw file whose current SHA differs (engineered drift for the stale test).

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def _corpus_root() -> Path:
    return Path(__file__).resolve().parent.parent / "eval" / "corpora" / "small-vault"


def test_eval_corpus_exists_and_contains_required_entry_files():
    root = _corpus_root()
    assert root.is_dir()
    assert (root / "AGENTS.md").exists()
    assert (root / "wiki" / "INDEX.md").exists()
    assert (root / "wiki" / "LOG.md").exists()


def test_eval_corpus_has_at_least_one_page_per_primary_type():
    root = _corpus_root()
    expected = {"concept", "entity", "comparison", "timeline", "raw_source"}
    found = set()
    for md in root.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        if "\ntype: concept" in text: found.add("concept")
        if "\ntype: entity" in text: found.add("entity")
        if "\ntype: comparison" in text: found.add("comparison")
        if "\ntype: timeline" in text: found.add("timeline")
        if "\ntype: raw_source" in text: found.add("raw_source")
    assert expected <= found, f"missing types: {expected - found}"


def test_eval_corpus_lint_clean():
    from octopus_kb_compound.frontmatter import FrontmatterError, parse_document
    from octopus_kb_compound.lint import lint_pages
    from octopus_kb_compound.profile import load_vault_profile
    from octopus_kb_compound.vault import scan_markdown_files

    root = _corpus_root()

    # Strict parse sweep — catches malformed frontmatter, which lint_pages cannot.
    parse_failures = []
    for md in sorted(root.rglob("*.md")):
        rel = md.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            parse_document(md.read_text(encoding="utf-8", errors="replace"), strict=True)
        except FrontmatterError as exc:
            parse_failures.append((str(rel), str(exc)))
    assert parse_failures == [], f"malformed frontmatter in eval corpus: {parse_failures}"

    # lint_pages sweep — canonical/alias/schema/link rules.
    profile = load_vault_profile(root)
    pages = scan_markdown_files(root, profile)
    findings = lint_pages(pages)
    high = [f for f in findings if f.code in {
        "DUPLICATE_CANONICAL_PAGE", "CANONICAL_ALIAS_COLLISION",
        "SCHEMA_INVALID_FIELD", "SCHEMA_MISSING_FIELD",
        "SCHEMA_INVALID_CONDITIONAL", "BROKEN_LINK", "ALIAS_COLLISION",
        "UNRESOLVED_ALIAS",
    }]
    assert high == [], f"eval corpus has high-severity lint findings: {high}"


def test_eval_corpus_has_detectable_drift_case():
    import hashlib
    import json

    root = _corpus_root()
    audit_dir = root / ".octopus-kb" / "audit"
    assert audit_dir.is_dir(), "corpus must ship pre-seeded audit entries"
    any_audit = list(audit_dir.glob("*.json"))
    assert any_audit, "at least one audit entry must exist"

    drift_count = 0
    for entry_path in any_audit:
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
        source = entry.get("source") or {}
        raw = root / source.get("path", "")
        if not raw.exists():
            continue
        current = hashlib.sha256(raw.read_bytes()).hexdigest()
        if current != source.get("sha256"):
            drift_count += 1
    assert drift_count >= 1, (
        "corpus must include at least one audit entry whose raw source SHA differs from "
        "the recorded audit SHA, to exercise drift_detection"
    )
```

- [ ] **Step 2: Run — FAIL** (corpus missing).

- [ ] **Step 3: Build the corpus.**

15-20 markdown files covering all page types. One engineered drift: write an audit entry pointing at a raw file, then modify the raw file's body so SHA differs.

- [ ] **Step 4: Run — PASS. Full suite — PASS.**

- [ ] **Step 5: Commit**

```bash
git add eval/corpora/ tests/test_eval_corpus.py CHANGELOG.md
git commit -m "test: add committed reference corpus for eval harness"
```

---

### Task 2: Task suite format + loader

**Files:**
- Create: `src/octopus_kb_compound/eval/__init__.py`
- Create: `src/octopus_kb_compound/eval/tasks.py`
- Create: `schemas/eval/tasks-v1.json`
- Create: `eval/tasks.yaml`
- Create: `tests/test_eval_tasks.py`
- Modify: `pyproject.toml` (no dep additions — `pyyaml` was already added by Phase A-min)
- Modify: `CHANGELOG.md`

**Task suite YAML:**

```yaml
version: 1
corpus: eval/corpora/small-vault
tasks:
  - id: fact-001
    type: fact_lookup
    query: "RAG Ops"
    expected:
      canonical_path: "wiki/concepts/RAG Operations.md"

  - id: rel-001
    type: relationship_trace
    query: "wiki/concepts/RAG Operations.md"
    expected:
      related_paths:
        - "wiki/entities/Vector Store.md"
        - "wiki/entities/Knowledge Graph.md"

  - id: drift-001
    type: drift_detection
    expected:
      stale_paths:
        - "wiki/concepts/RAG Operations.md"
```

`schemas/eval/tasks-v1.json` validates the YAML. Unknown `type` → `EvalError` at load.

- [ ] **Step 1: Write the failing tests** (full bodies)

```python
import pytest
import yaml
from pathlib import Path


def test_load_task_suite_parses_valid_yaml(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text("""
version: 1
corpus: eval/corpora/small-vault
tasks:
  - id: f1
    type: fact_lookup
    query: "RAG Ops"
    expected:
      canonical_path: "wiki/concepts/RAG Operations.md"
""", encoding="utf-8")
    from octopus_kb_compound.eval.tasks import load_task_suite
    suite = load_task_suite(path)
    assert len(suite.tasks) == 1
    assert suite.tasks[0].type == "fact_lookup"


def test_load_task_suite_rejects_unknown_type(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text("""
version: 1
corpus: eval/corpora/small-vault
tasks:
  - id: x
    type: nonsense
    query: "q"
    expected: {}
""", encoding="utf-8")
    from octopus_kb_compound.eval.tasks import EvalError, load_task_suite
    with pytest.raises(EvalError):
        load_task_suite(path)


def test_load_task_suite_rejects_missing_required_field(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text("""
version: 1
tasks:
  - id: x
    type: fact_lookup
    expected: {}
""", encoding="utf-8")
    from octopus_kb_compound.eval.tasks import EvalError, load_task_suite
    with pytest.raises(EvalError):
        load_task_suite(path)
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement `tasks.py` loader with JSON Schema validation.**
- [ ] **Step 4: Run — PASS. Full suite — PASS.**
- [ ] **Step 5: Commit**

```bash
git add src/octopus_kb_compound/eval/ schemas/eval/ eval/tasks.yaml \
        tests/test_eval_tasks.py pyproject.toml CHANGELOG.md
git commit -m "feat: add eval task suite format and loader"
```

---

### Task 3: Path runners — `grep` and `octopus-kb`

**Files:**
- Create: `src/octopus_kb_compound/eval/paths.py`
- Create: `tests/test_eval_paths.py`
- Modify: `CHANGELOG.md`

**Runner interface (deterministic result; metrics collected externally):**

```python
@dataclass(frozen=True)
class PathResult:
    path_name: str                   # "grep" or "octopus-kb"
    answer: str                      # deterministic: exact text
    answer_json: dict | None         # deterministic: structured form
    input_size_chars: int            # deterministic: total chars returned
    sources: tuple[str, ...]         # deterministic: files inspected/cited, sorted

def run_grep_path(task: Task, corpus: Path) -> PathResult: ...
def run_octopus_path(task: Task, corpus: Path) -> PathResult: ...
```

The runner (Task 4) measures wall time with `time.perf_counter_ns()` around each `run_*_path` call and records it in a *separate* metrics collection. The path functions themselves never touch time; their output is fully deterministic given the same input.

Two separate output files per task: `<task_id>.json` (deterministic, committed, bit-identical across runs) and `<task_id>.metrics.json` (ephemeral, git-ignored, contains `latency_ms` per path — milliseconds as a float derived from the `perf_counter_ns` measurement).

**Deterministic grep via pure Python (no shell):** The `grep` path does not shell out. It uses a pure-Python substring scan over sorted markdown files under the corpus (`pathlib.Path.rglob("*.md")` with `sorted(...)` applied to the iterable, scanning each file body for the query with `str.find`). This removes cross-platform divergence from GNU vs BusyBox vs Windows grep and makes the baseline diff-stable anywhere. It is still a "dumb" path (no semantics, no canonical resolution) — the point of comparison is preserved. The name `grep` in results is retained for readability.

**`grep` path (pure-Python, deterministic):** iterate `sorted(corpus.rglob("*.md"))`, skipping hidden directories, and use `str.find` on each file's body (decoded utf-8 errors=replace) to locate occurrences of the query. `answer` is a newline-joined string of `<relpath>:<line>:<matched-line>` entries. `sources` is the sorted tuple of file paths with at least one hit. No semantics — this is the "string grep" baseline.

**`drift_detection` tasks have no query** (grep cannot do drift detection). For those tasks, `run_grep_path` returns a `PathResult` with `answer=""`, `answer_json={"stale_paths": []}`, `sources=()`. Scoring then reports precision+recall against the expected set — grep always scores 0.0 on drift tasks, which is the intended comparison (grep literally cannot do it; octopus-kb can).

**`octopus-kb` path:**
- `fact_lookup` → in-process call to `octopus-kb lookup "<term>" --vault <corpus> --json`. `answer_json` is the raw lookup response.
- `relationship_trace` → in-process call to `octopus-kb neighbors "<page>" --vault <corpus> --json`, then **normalize**: `answer_json = {"related_paths": sorted({n["path"] for n in raw["inbound"] + raw["outbound"]})}`. This gives scoring a stable shape for F1 computation.
- `drift_detection` → walk `.octopus-kb/audit/` entries, recompute SHAs against each `source.path`, emit `answer_json = {"stale_paths": sorted(list_of_stale_pages)}`.

The third sub-path is a **new helper** (`src/octopus_kb_compound/eval/drift.py`) — its scope is read-only audit inspection; no changes to audit/, apply, or proposal storage.

**Audit schema consumed (restated):** Drift detection reads `.octopus-kb/audit/*.json` entries produced by Phase A-min. The fields this harness relies on:

```json
{
  "proposal_id": "...",
  "applied_at": "...",
  "source": {"kind": "raw_file", "path": "raw/<relpath>", "sha256": "<64 hex>"},
  "applied_pages": ["wiki/concepts/<title>.md", ...]
}
```

Drift fires when `sha256(vault/<source.path>.read_bytes())` differs from the recorded `source.sha256`. All pages in `applied_pages` are reported as stale. If an audit entry omits `source` or `applied_pages`, it is skipped with a warning (not an error).

- [ ] **Step 1: Write the failing tests**

```python
import time
from pathlib import Path


def _corpus():
    return Path(__file__).resolve().parent.parent / "eval" / "corpora" / "small-vault"


def test_grep_path_returns_matches_for_fact_lookup():
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_grep_path, PathResult

    task = Task(id="x", type="fact_lookup", query="RAG Ops",
                expected={"canonical_path": "wiki/concepts/RAG Operations.md"})
    result = run_grep_path(task, _corpus())
    assert isinstance(result, PathResult)
    assert result.path_name == "grep"
    assert "RAG Ops" in result.answer
    assert result.sources
    # Must be sorted for determinism.
    assert list(result.sources) == sorted(result.sources)


def test_octopus_path_fact_lookup_returns_canonical():
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_octopus_path

    task = Task(id="x", type="fact_lookup", query="RAG Ops",
                expected={"canonical_path": "wiki/concepts/RAG Operations.md"})
    result = run_octopus_path(task, _corpus())
    assert result.path_name == "octopus-kb"
    assert result.answer_json is not None
    assert result.answer_json["canonical"]["path"] == "wiki/concepts/RAG Operations.md"


def test_octopus_path_drift_detection_returns_engineered_stale():
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_octopus_path

    task = Task(id="d", type="drift_detection", query=None,
                expected={"stale_paths": ["wiki/concepts/RAG Operations.md"]})
    result = run_octopus_path(task, _corpus())
    assert result.answer_json is not None
    assert "wiki/concepts/RAG Operations.md" in result.answer_json["stale_paths"]


def test_grep_path_is_bit_identical_across_invocations():
    """Pure-Python grep must be deterministic regardless of host platform."""
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_grep_path

    task = Task(id="x", type="fact_lookup", query="RAG Ops",
                expected={"canonical_path": "wiki/concepts/RAG Operations.md"})
    a = run_grep_path(task, _corpus())
    b = run_grep_path(task, _corpus())
    assert a == b
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement `paths.py` and `drift.py`.**

- [ ] **Step 4-5: Run tests — PASS. Full suite — PASS.**

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/eval/paths.py src/octopus_kb_compound/eval/drift.py \
        tests/test_eval_paths.py CHANGELOG.md
git commit -m "feat: add grep and octopus-kb eval path runners"
```

---

### Task 4: Scoring + runner orchestration

**Files:**
- Create: `src/octopus_kb_compound/eval/scoring.py`
- Create: `src/octopus_kb_compound/eval/runner.py`
- Create: `tests/test_eval_scoring.py`
- Create: `tests/test_eval_runner.py`
- Modify: `CHANGELOG.md`

**Scoring:**

```python
def score(task: Task, result: PathResult) -> dict:
    # returns {"deterministic_score": float 0..1, "rationale": str}
```

- `fact_lookup`: extract the canonical path from `result.answer_json`. Score is `1.0` if it matches expected, else `0.0`. For `grep` path, attempt to detect if the expected path appears in `sources`.
- `relationship_trace`: compute F1 over the `related_paths` set vs expected.
- `drift_detection`: precision+recall averaged.

**Runner:**

```python
def run_suite(tasks_file: Path, out_dir: Path) -> RunSummary: ...
```

Writes per-task JSON under `out_dir/<task_id>.json` and a summary `out_dir/summary.md`.

**`summary.md` deterministic format (frozen):**

```
# Eval Summary

Tasks file: <relative path>
Corpus: <relative path>
Total tasks: N

| task_id | type | grep_score | octopus_score |
|---|---|---|---|
| fact-001 | fact_lookup | 0.50 | 1.00 |
...
```

Rules:
- No timestamp in the summary.
- Rows sorted by `task_id` ASCII ascending.
- Scores formatted `"%.2f"`.
- No conditional text (no "skipped on this platform", no host info).

The pure-Python grep path always runs (it has no external deps). Platform notes belong in the benchmark report (`docs/benchmarks/v1.md`), not in `summary.md`.

- [ ] **Step 1: Write the failing tests** (full bodies)

```python
# tests/test_eval_scoring.py
from octopus_kb_compound.eval.tasks import Task
from octopus_kb_compound.eval.paths import PathResult
from octopus_kb_compound.eval.scoring import score


def _mk(path_name, answer_json, sources=()):
    return PathResult(
        path_name=path_name, answer="", answer_json=answer_json,
        input_size_chars=0, sources=tuple(sources),
    )


def test_score_fact_lookup_exact_match():
    task = Task(id="t", type="fact_lookup", query="x",
                expected={"canonical_path": "wiki/concepts/Topic.md"})
    result = _mk("octopus-kb",
                 {"canonical": {"path": "wiki/concepts/Topic.md"}})
    assert score(task, result)["deterministic_score"] == 1.0


def test_score_fact_lookup_mismatch_is_zero():
    task = Task(id="t", type="fact_lookup", query="x",
                expected={"canonical_path": "wiki/concepts/Topic.md"})
    result = _mk("octopus-kb", {"canonical": {"path": "wiki/concepts/Other.md"}})
    assert score(task, result)["deterministic_score"] == 0.0


def test_score_relationship_trace_f1():
    task = Task(id="t", type="relationship_trace", query="p",
                expected={"related_paths": ["a", "b"]})
    result = _mk("octopus-kb", {"related_paths": ["a", "c"]})  # TP=1, FP=1, FN=1
    s = score(task, result)["deterministic_score"]
    # precision=0.5, recall=0.5, F1=0.5
    assert abs(s - 0.5) < 1e-6


def test_score_drift_detection_precision_recall():
    task = Task(id="t", type="drift_detection", query=None,
                expected={"stale_paths": ["a", "b"]})
    result = _mk("octopus-kb", {"stale_paths": ["a"]})  # precision=1.0, recall=0.5
    s = score(task, result)["deterministic_score"]
    # average = 0.75
    assert abs(s - 0.75) < 1e-6
```

```python
# tests/test_eval_runner.py
import json
from pathlib import Path


def test_run_suite_writes_per_task_json_and_summary(tmp_path):
    from octopus_kb_compound.eval.runner import run_suite
    tasks_file = Path("eval/tasks.yaml")  # committed by prior task
    out = tmp_path / "run"
    summary = run_suite(tasks_file, out)
    assert (out / "fact-001.json").exists()
    assert (out / "summary.md").exists()
    data = json.loads((out / "fact-001.json").read_text(encoding="utf-8"))
    assert "results" in data and isinstance(data["results"], list)
    for r in data["results"]:
        assert "path_name" in r and "deterministic_score" in r
        assert "latency_ms" not in r, "latency must not appear in deterministic JSON"
        assert "latency_ns" not in r


def test_run_suite_produces_separate_metrics_file_with_latency_ms(tmp_path):
    from octopus_kb_compound.eval.runner import run_suite
    tasks_file = Path("eval/tasks.yaml")
    out = tmp_path / "run2"
    run_suite(tasks_file, out)
    metrics = out / "fact-001.metrics.json"
    assert metrics.exists()
    data = json.loads(metrics.read_text(encoding="utf-8"))
    assert "metrics" in data and isinstance(data["metrics"], list)
    assert any("latency_ms" in entry for entry in data["metrics"])
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement `scoring.py` and `runner.py`.**
- [ ] **Step 4: Run — PASS. Full suite — PASS.**
- [ ] **Step 5: Commit**

```bash
git add src/octopus_kb_compound/eval/scoring.py src/octopus_kb_compound/eval/runner.py \
        tests/test_eval_scoring.py tests/test_eval_runner.py CHANGELOG.md
git commit -m "feat: add deterministic scoring and suite runner"
```

---

### Task 5: `kb eval` CLI

**Files:**
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**CLI:**

```
octopus-kb eval run --tasks eval/tasks.yaml --out eval/runs/<label> [--json]
octopus-kb eval report --run eval/runs/<label> [--format markdown]
```

- `eval run`: executes the suite, writes per-task JSON + summary.
- `eval report`: re-renders summary from a prior run's JSON artifacts.

Exit codes: `0` on successful run regardless of scores. `2` on invalid inputs. `1` on unexpected runtime failure.

- [ ] **Step 1: Write the failing tests** (full bodies)

```python
def test_cli_eval_run_produces_summary_and_deterministic_json(tmp_path):
    import json
    from pathlib import Path
    from octopus_kb_compound.cli import main

    out = tmp_path / "run"
    rc = main(["eval", "run",
               "--tasks", "eval/tasks.yaml",
               "--out", str(out)])
    assert rc == 0
    assert (out / "summary.md").exists()
    task_files = list(out.glob("*.json"))
    assert any(p.stem.startswith("fact-") for p in task_files)
    sample = next(p for p in task_files if not p.name.endswith(".metrics.json"))
    data = json.loads(sample.read_text(encoding="utf-8"))
    assert "results" in data


def test_cli_eval_report_rerenders_summary_from_prior_run(tmp_path):
    import json
    from pathlib import Path
    from octopus_kb_compound.cli import main

    out = tmp_path / "run"
    assert main(["eval", "run", "--tasks", "eval/tasks.yaml", "--out", str(out)]) == 0

    # Remove summary, re-generate from task files.
    (out / "summary.md").unlink()
    rc = main(["eval", "report", "--run", str(out), "--format", "markdown"])
    assert rc == 0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    # Frozen format: lowercase header columns, no timestamps.
    assert "| task_id | type | grep_score | octopus_score |" in summary
    assert "Total tasks:" in summary
    # No ISO timestamp lines.
    import re as _re
    assert not _re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", summary)
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement CLI wiring.**
- [ ] **Step 4: Run — PASS. Full suite — PASS.**
- [ ] **Step 5: Commit**

```bash
git add src/octopus_kb_compound/cli.py tests/test_cli.py CHANGELOG.md
git commit -m "feat: add eval run/report CLI commands"
```

---

### Task 6: First benchmark + `0.6.0` release

**Files:**
- Create: `eval/runs/2026-04-18-baseline/*.json` (deterministic, committed)
- Create: `eval/runs/2026-04-18-baseline/summary.md` (deterministic, committed)
- Create: `docs/benchmarks/v1.md`
- Modify: `.gitignore` (add `eval/runs/**/*.metrics.json` line)
- Modify: `README.md`
- Modify: `pyproject.toml` (version → `0.6.0`)
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

Run: `octopus-kb eval run --tasks eval/tasks.yaml --out eval/runs/2026-04-18-baseline/`

The committed artifacts are bit-identical outputs of that run against the committed corpus. A CI test can re-run this and diff against the committed results — divergence means the harness is non-deterministic or the corpus/code changed unaccounted.

**`docs/benchmarks/v1.md` structure:**

```markdown
# v1 Benchmark (2026-04-18)

Corpus: eval/corpora/small-vault (15 pages, 3 raw files)
Task suite: eval/tasks.yaml (10 tasks)

## Results

| Task | Class | grep score | octopus-kb score | grep chars | octopus chars |
|---|---|---|---|---|---|
| fact-001 | fact_lookup | ... | ... | ... | ... |
...

## Where octopus-kb wins

- Returns canonical decisions directly; grep forces the caller to parse N match lines.
- Drift detection: grep cannot do it at all.

## Where grep wins

- Raw string search on unstructured prose that has no frontmatter.

## Reproduction

The baseline is bit-identical on every platform because all paths (grep, octopus-kb) run pure Python — no shell-outs, no platform-specific binaries. Run:

```
octopus-kb eval run --tasks eval/tasks.yaml --out /tmp/my-run
diff -r --exclude='*.metrics.json' eval/runs/2026-04-18-baseline /tmp/my-run
```

Expected: empty diff for `<task_id>.json` and `summary.md`. `*.metrics.json` files vary by run (latency) and are excluded.
```

- [ ] **Step 1: Expand `eval/tasks.yaml` to 10 tasks** (≥3 per class) and add coverage test

```python
# tests/test_eval_suite_coverage.py
def test_task_suite_has_expected_class_coverage():
    from octopus_kb_compound.eval.tasks import load_task_suite
    suite = load_task_suite("eval/tasks.yaml")
    counts = {"fact_lookup": 0, "relationship_trace": 0, "drift_detection": 0}
    for t in suite.tasks:
        counts[t.type] = counts.get(t.type, 0) + 1
    assert counts["fact_lookup"] >= 3
    assert counts["relationship_trace"] >= 3
    assert counts["drift_detection"] >= 3
    assert sum(counts.values()) >= 10
```

- [ ] **Step 2: Run the harness manually; commit `<task_id>.json` files (deterministic) and `summary.md`. Do NOT commit `*.metrics.json`; add to `.gitignore`.**

- [ ] **Step 3: Write the benchmark report.**

- [ ] **Step 4: Link from README.**

- [ ] **Step 5: Version bump + CHANGELOG.**

- [ ] **Step 6: Commit**

```bash
# Update .gitignore first so metrics do not sneak in with the baseline add.
git add .gitignore
git commit -m "chore: ignore eval metrics files"

git add eval/tasks.yaml tests/test_eval_suite_coverage.py eval/runs/2026-04-18-baseline \
        docs/benchmarks/ README.md pyproject.toml CHANGELOG.md docs/roadmap.md
git commit -m "chore: cut 0.6.0 with v1 deterministic benchmark"
```

---

## Execution Notes

- The harness is deterministic by design. Any non-determinism observed in CI is a bug (likely unordered set → list conversion somewhere). Fix it before promoting the benchmark.
- Human rating, multi-provider LLM matrix, graphify comparison, and LLM-judge answer quality are all explicitly deferred to v0.7+.
- `grep` is available on all supported platforms. If `grep` is absent (e.g., Windows without Git Bash), the runner marks the grep path as `skipped` but still runs octopus-kb.

## Final Verification

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli eval run \
  --tasks eval/tasks.yaml --out /tmp/octopus-eval-check
diff -r --exclude='*.metrics.json' eval/runs/2026-04-18-baseline /tmp/octopus-eval-check
```

Expected: all tests pass; diff empty for deterministic files (`<task_id>.json`, `summary.md`) on the baseline platform. Non-GNU-grep platforms see empty diff for octopus-kb-path fields only. Exit `0`.
