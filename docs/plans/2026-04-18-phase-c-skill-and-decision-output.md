# Phase C: Skill Shelf and Decision-Level Output Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make octopus-kb-compound's CLI output *decisions* (not data), ship an opinionated skill that tells agents to use the tool instead of grepping, and add a Claude Code PreToolUse hook that enforces the operating procedure. No LLM work in this phase. Builds on Phase 0.

**Architecture:** The CLI already has `impacted-pages` and `suggest-links`. Phase C adds three decision-first verbs (`lookup`, `retrieve-bundle`, `neighbors`), all emitting schema-validated JSON. A skill file + three slash-command recipes + a PreToolUse hook form the behavior-capture layer. Every JSON output contract is published as a JSON Schema under `schemas/cli/` and enforced by tests.

**Tech Stack:** Python 3.11, `jsonschema>=4.18` (required dep from Phase 0), existing `pytest` suite.

---

## Delivery Rules

- Phase 0 must be on `main` first. `jsonschema` is already a required dependency by that point.
- TDD every task. Every Step 1 shows the complete test body (no "similar shape" placeholders, no `Step 1-7` shortcuts).
- Every new command ships its JSON Schema in the same task that introduces the command.
- Every schema gains a round-trip test asserting that the CLI output validates against it.
- Version bump to `0.4.0` at the end of Phase C. Do not bump earlier.

## Coverage

| Gap | Task |
|---|---|
| No `lookup` verb | Task 1 |
| No `retrieve-bundle` CLI verb | Task 2 |
| No `neighbors` CLI verb | Task 3 |
| `impacted-pages` prints lines, not structured output | Task 4 |
| No skill file / slash recipes | Task 5 |
| No PreToolUse hook with deterministic trigger | Task 6 |
| README does not frame the SOP | Task 7 |

---

### Task 1: `lookup` CLI verb

**Files:**
- Create: `src/octopus_kb_compound/lookup.py`
- Create: `schemas/cli/lookup.json`
- Create: `tests/test_lookup.py`
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `src/octopus_kb_compound/__init__.py`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**Output schema (`schemas/cli/lookup.json`):**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "octopus-kb/cli/lookup",
  "type": "object",
  "required": ["term", "canonical", "aliases", "ambiguous", "collisions", "next"],
  "additionalProperties": false,
  "properties": {
    "term": {"type": "string"},
    "canonical": {
      "oneOf": [
        {"type": "null"},
        {
          "type": "object",
          "required": ["path", "title"],
          "additionalProperties": false,
          "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "source_of_truth": {"type": ["string", "null"]}
          }
        }
      ]
    },
    "aliases": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["text", "resolves_to"],
        "additionalProperties": false,
        "properties": {
          "text": {"type": "string"},
          "resolves_to": {"type": "string"}
        }
      }
    },
    "ambiguous": {"type": "boolean"},
    "collisions": {"type": "array", "items": {"type": "string"}},
    "next": {"type": "array", "items": {"type": "string"}}
  }
}
```

- [ ] **Step 1: Write the failing tests**

```python
import io
import json
import sys
from pathlib import Path

import pytest


def _seed_vault(root: Path) -> None:
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "concepts" / "RAG Operations.md").write_text(
        '---\ntitle: "RAG Operations"\ntype: concept\nlang: en\n'
        'role: concept\nlayer: wiki\nsource_of_truth: canonical\n'
        'aliases:\n  - "RAG Ops"\ntags: []\nsummary: "Ops wrapper."\n---\n',
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (root / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")


def test_cli_lookup_returns_canonical_and_next_commands(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["lookup", "RAG Ops", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["canonical"]["path"] == "wiki/concepts/RAG Operations.md"
    assert data["aliases"][0]["text"] == "RAG Ops"
    assert data["ambiguous"] is False
    assert any("retrieve-bundle" in hint for hint in data["next"])


def test_cli_lookup_reports_ambiguity_when_alias_resolves_to_multiple_pages(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (vault / "wiki" / "concepts" / "A.md").write_text(
        '---\ntitle: "A"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\n'
        'aliases:\n  - "Shared"\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    (vault / "wiki" / "concepts" / "B.md").write_text(
        '---\ntitle: "B"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\n'
        'aliases:\n  - "Shared"\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["lookup", "Shared", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["ambiguous"] is True
    assert set(data["collisions"]) == {
        "wiki/concepts/A.md", "wiki/concepts/B.md"
    }
    assert data["canonical"] is None


def test_cli_lookup_returns_null_canonical_for_unknown_term(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["lookup", "nonexistent-term", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["canonical"] is None
    assert data["ambiguous"] is False
    assert any("suggest-links" in hint for hint in data["next"])


def test_lookup_output_matches_schema(tmp_path):
    import jsonschema

    vault = tmp_path / "vault"
    _seed_vault(vault)

    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "cli" / "lookup.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["lookup", "RAG Ops", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    jsonschema.validate(json.loads(buf.getvalue()), schema)
```

- [ ] **Step 2: Run tests — FAIL** (`lookup` command missing).

- [ ] **Step 3: Implement `src/octopus_kb_compound/lookup.py`**

Core function signature:

```python
@dataclass(frozen=True, slots=True)
class LookupResult:
    term: str
    canonical: dict | None
    aliases: list[dict]
    ambiguous: bool
    collisions: list[str]
    next: list[str]

    def to_dict(self) -> dict: ...


def lookup_term(term: str, vault: Path) -> LookupResult: ...
```

Reuses `links.build_alias_index`, `links.normalize_page_name`, `lint._canonical_key` (extract `_canonical_key` and `_canonical_pages_by_key` to a shared private module `canonical.py` so both `lint` and `lookup` import from the same source; update `lint.py` to re-export for backward compatibility — no behavior change).

- [ ] **Step 4: Wire into `cli.py`**

Add subparser `lookup` with positional `term`, required `--vault`, optional `--json`. Without `--json`, print tab-separated lines (`canonical\t<path>`, `alias\t<text>\t<path>`, `next\t<command>`). Exit `0` on any valid lookup (including term-not-found), `2` for invalid vault.

- [ ] **Step 5: Run tests**

```
PYTHONPATH=src python -m pytest tests/test_lookup.py tests/test_cli.py -q
```

Expected: `3 new tests passing`, existing tests unchanged.

- [ ] **Step 6: Full suite**

```
PYTHONPATH=src python -m pytest -q
```

Expected: `100 passed` (97 from Phase 0 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add src/octopus_kb_compound/cli.py src/octopus_kb_compound/lookup.py \
        src/octopus_kb_compound/__init__.py schemas/cli/lookup.json \
        tests/test_lookup.py tests/test_cli.py CHANGELOG.md \
        src/octopus_kb_compound/canonical.py src/octopus_kb_compound/lint.py
git commit -m "feat: add lookup CLI verb with decision-level JSON output"
```

---

### Task 2: `retrieve-bundle` CLI verb

**Files:**
- Modify: `src/octopus_kb_compound/retrieve.py`
- Modify: `src/octopus_kb_compound/cli.py`
- Create: `schemas/cli/retrieve-bundle.json`
- Modify: `tests/test_retrieve.py`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**Token estimation contract:** `token_estimate` is a **character-based heuristic**: `(total_chars_of_bundled_page_bodies + 3) // 4` (ceil-div by 4). Document this verbatim in `schemas/cli/retrieve-bundle.json` description so callers know it is not a real tokenizer. Trimming with `--max-tokens` drops pages in fixed order: `raw_sources` first, then `entities`, never `concepts`, `schema`, or `index`. Each drop recomputes the estimate; stop when estimate ≤ max_tokens or no more droppable pages remain.

**Output schema (`schemas/cli/retrieve-bundle.json`):** defines `query`, `bundle` (with the five ordered keys), `warnings`, `token_estimate`, `next`. Top-level `additionalProperties: false`. Required: all five top-level. `bundle.{schema,index}` are `array<string>`; `bundle.{concepts,entities,raw_sources}` are `array<{path, title, reason}>` (with `additionalProperties: false` inside each item).

All CLI output schemas in `schemas/cli/` use `additionalProperties: false` at the top level so extra accidental fields fail loudly in tests.

- [ ] **Step 1: Write the failing tests** (complete bodies below)

```python
import io
import json
import sys
from pathlib import Path


def _seed_vault(root: Path) -> None:
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "entities").mkdir(parents=True)
    (root / "raw").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (root / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (root / "wiki" / "concepts" / "RAG Operations.md").write_text(
        '---\ntitle: "RAG Operations"\ntype: concept\nlang: en\n'
        'role: concept\nlayer: wiki\nsource_of_truth: canonical\n'
        'tags: []\nsummary: "Ops wrapper."\n'
        'related_entities:\n  - "Vector Store"\n---\n',
        encoding="utf-8",
    )
    (root / "wiki" / "entities" / "Vector Store.md").write_text(
        '---\ntitle: "Vector Store"\ntype: entity\nlang: en\nrole: entity\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\n'
        'summary: "An ANN index."\n---\n',
        encoding="utf-8",
    )
    (root / "raw" / "rag-source.md").write_text(
        '---\ntitle: "RAG Source"\ntype: raw_source\nlang: en\n'
        'role: raw_source\nlayer: source\ntags: []\n---\n'
        'See [[RAG Operations]].\n',
        encoding="utf-8",
    )


def test_cli_retrieve_bundle_orders_evidence_by_contract(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["retrieve-bundle", "rag operations", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["bundle"]["schema"] == ["AGENTS.md"]
    assert data["bundle"]["index"] == ["wiki/INDEX.md"]
    concept_paths = [c["path"] for c in data["bundle"]["concepts"]]
    assert "wiki/concepts/RAG Operations.md" in concept_paths
    assert data["token_estimate"] > 0
    assert any("impacted-pages" in hint for hint in data["next"])


def test_cli_retrieve_bundle_warns_when_index_missing(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    (vault / "wiki" / "INDEX.md").unlink()

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    data = json.loads(buf.getvalue())
    warning_codes = [w["code"] for w in data["warnings"]]
    assert "NO_INDEX" in warning_codes


def test_cli_retrieve_bundle_trims_drops_raw_sources_first(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    # Untrimmed run: prove raw_sources is populated when no cap is set.
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original
    full = json.loads(buf.getvalue())
    assert full["bundle"]["raw_sources"], "baseline must contain raw_sources"

    # Trim below raw-sources contribution: raw_sources must be the first thing dropped.
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag", "--vault", str(vault),
              "--max-tokens", "50", "--json"])
    finally:
        sys.stdout = original
    trimmed = json.loads(buf.getvalue())
    assert trimmed["bundle"]["raw_sources"] == []
    assert trimmed["bundle"]["concepts"] == full["bundle"]["concepts"]
    assert trimmed["token_estimate"] < full["token_estimate"]


def test_cli_retrieve_bundle_trims_entities_after_raw_sources(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    # Delete raw sources so entities become the next drop target.
    for raw in (vault / "raw").glob("*.md"):
        raw.unlink()

    from octopus_kb_compound.cli import main

    # Baseline with no trim.
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original
    full = json.loads(buf.getvalue())
    assert full["bundle"]["entities"], "baseline must contain entities"
    assert full["bundle"]["raw_sources"] == []

    # Trim forces dropping entities since raw_sources is already empty.
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag", "--vault", str(vault),
              "--max-tokens", "20", "--json"])
    finally:
        sys.stdout = original
    trimmed = json.loads(buf.getvalue())
    assert trimmed["bundle"]["entities"] == []
    assert trimmed["bundle"]["concepts"] == full["bundle"]["concepts"]


def test_retrieve_bundle_output_matches_schema(tmp_path):
    import jsonschema

    vault = tmp_path / "vault"
    _seed_vault(vault)

    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "cli" / "retrieve-bundle.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag operations", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    jsonschema.validate(json.loads(buf.getvalue()), schema)
```

- [ ] **Step 2: Run tests — FAIL** (`retrieve-bundle` command missing, no schema file).

- [ ] **Step 3: Implement**

Extend `retrieve.py`:
- `build_retrieval_bundle(query, vault)` returns a dataclass `RetrievalBundle` with `query`, ordered lists for each bucket, `warnings: list[Warning]`, and a `token_estimate: int` computed as `(total_chars_of_all_bundled_markdown_bodies + 3) // 4` (ceiling division by 4). This matches the contract in `schemas/cli/retrieve-bundle.json` exactly.
- Trim policy: if caller supplies `max_tokens`, drop `raw_sources` first, then `entities`, recomputing estimate after each drop. Never drop `schema`, `index`, or `concepts`.
- Reason strings: per-page `reason` ∈ `{title_match, alias_match, related_entities, backlink, schema_anchor, index_anchor, log_anchor}`.

CLI: add subparser with `query` (positional), `--vault` (required), `--max-tokens` (int, default `0` = no limit), `--json` (flag).

- [ ] **Step 4: Write `schemas/cli/retrieve-bundle.json`** as described above.

- [ ] **Step 5: Run tests — PASS.**

- [ ] **Step 6: Full suite — PASS** (`104 passed`).

- [ ] **Step 7: Commit**

```bash
git add src/octopus_kb_compound/retrieve.py src/octopus_kb_compound/cli.py \
        schemas/cli/retrieve-bundle.json tests/test_retrieve.py \
        tests/test_cli.py CHANGELOG.md
git commit -m "feat: add retrieve-bundle CLI verb with ordered evidence schema"
```

---

### Task 3: `neighbors` CLI verb

**Files:**
- Create: `src/octopus_kb_compound/neighbors.py`
- Create: `schemas/cli/neighbors.json`
- Create: `tests/test_neighbors.py`
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**Output schema (`schemas/cli/neighbors.json`):** `page` (string), `inbound` (array of `{path, via, count}`), `outbound` (array of `{path, via}`), `aliases` (array of strings), `canonical_identity` (string | null), `next` (array of strings).

`via` enum: `wikilink`, `related_entities`.

- [ ] **Step 1: Write the failing tests**

```python
import io
import json
import sys
from pathlib import Path


def _seed_vault(root: Path) -> None:
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "entities").mkdir(parents=True)
    (root / "raw").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (root / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (root / "wiki" / "concepts" / "RAG Operations.md").write_text(
        '---\ntitle: "RAG Operations"\ntype: concept\nlang: en\n'
        'role: concept\nlayer: wiki\nsource_of_truth: canonical\n'
        'tags: []\nsummary: "s"\naliases:\n  - "RAG Ops"\n'
        'related_entities:\n  - "Vector Store"\n---\n'
        'See [[Knowledge Graph]].\n',
        encoding="utf-8",
    )
    (root / "wiki" / "entities" / "Vector Store.md").write_text(
        '---\ntitle: "Vector Store"\ntype: entity\nlang: en\nrole: entity\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    (root / "wiki" / "entities" / "Knowledge Graph.md").write_text(
        '---\ntitle: "Knowledge Graph"\ntype: entity\nlang: en\nrole: entity\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    (root / "raw" / "src.md").write_text(
        '---\ntitle: "src"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\n'
        'Inbound: [[RAG Operations]] [[RAG Operations]].\n',
        encoding="utf-8",
    )


def test_cli_neighbors_returns_inbound_outbound_aliases(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["neighbors", "wiki/concepts/RAG Operations.md",
                   "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["page"] == "wiki/concepts/RAG Operations.md"

    inbound_paths = {i["path"]: i for i in data["inbound"]}
    assert "raw/src.md" in inbound_paths
    assert inbound_paths["raw/src.md"]["count"] == 2

    outbound_pairs = {(o["path"], o["via"]) for o in data["outbound"]}
    assert ("wiki/entities/Vector Store.md", "related_entities") in outbound_pairs
    assert ("wiki/entities/Knowledge Graph.md", "wikilink") in outbound_pairs

    assert "RAG Ops" in data["aliases"]
    assert data["canonical_identity"] == "rag operations"


def test_neighbors_output_matches_schema(tmp_path):
    import jsonschema

    vault = tmp_path / "vault"
    _seed_vault(vault)

    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "cli" / "neighbors.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["neighbors", "wiki/concepts/RAG Operations.md",
              "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    jsonschema.validate(json.loads(buf.getvalue()), schema)


def test_cli_neighbors_rejects_path_outside_vault(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    outside = tmp_path / "outside.md"
    outside.write_text(
        '---\ntitle: "x"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main
    rc = main(["neighbors", str(outside.resolve()),
               "--vault", str(vault), "--json"])
    assert rc == 2


def test_cli_neighbors_returns_empty_when_page_has_no_links(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (vault / "wiki" / "orphan.md").write_text(
        '---\ntitle: "orphan"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["neighbors", "wiki/orphan.md", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["inbound"] == []
    assert data["outbound"] == []
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement**

`neighbors.py` with `compute_neighbors(page_rel_path, vault) -> NeighborsResult`. Walks all pages once, builds inbound index by scanning every body for wikilinks, and constructs outbound from the target page's body wikilinks + `related_entities` frontmatter. Dedupe and count.

- [ ] **Step 4: Write `schemas/cli/neighbors.json`** matching the contract.

- [ ] **Step 5: Wire into `cli.py`** — subparser with `page`, `--vault`, `--json`. Exit `2` if `page` is not a file or not inside vault.

- [ ] **Step 6: Run full suite — PASS** (`108 passed`).

- [ ] **Step 7: Commit**

```bash
git add src/octopus_kb_compound/cli.py src/octopus_kb_compound/neighbors.py \
        schemas/cli/neighbors.json tests/test_cli.py tests/test_neighbors.py CHANGELOG.md
git commit -m "feat: add neighbors CLI verb with graph context"
```

---

### Task 3b: `lint --json` output

**Files:**
- Modify: `src/octopus_kb_compound/cli.py`
- Create: `schemas/cli/lint.json`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**Rationale:** The Phase C skill (Task 5) tells agents to run `octopus-kb lint . --json` as the final check. That contract must exist before the skill ships or agents will hit a flag that does not parse. `lint` currently prints TSV only.

**Output schema (`schemas/cli/lint.json`):** top-level object with `additionalProperties: false`. `findings` is an array of objects, each with `code`, `path`, `message` (strings, all required) and `additionalProperties: false`.

- [ ] **Step 1: Write the failing test**

```python
def test_cli_lint_json_output(tmp_path):
    import io, json, sys, jsonschema
    from pathlib import Path

    vault = tmp_path / "vault"
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (vault / "wiki" / "concepts" / "Bad.md").write_text(
        '---\ntitle: "Bad"\ntype: concept\nlang: en\nrole: not-a-real-role\n'
        'layer: wiki\nsummary: "s"\ntags: []\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main
    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["lint", str(vault), "--json"])
    finally:
        sys.stdout = original
    assert rc == 1
    data = json.loads(buf.getvalue())
    assert "findings" in data and isinstance(data["findings"], list)
    codes = {f["code"] for f in data["findings"]}
    assert "SCHEMA_INVALID_FIELD" in codes

    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "cli" / "lint.json"
    jsonschema.validate(data, json.loads(schema_path.read_text(encoding="utf-8")))
```

- [ ] **Step 2: Run — FAIL** (flag not parsed).
- [ ] **Step 3: Add `--json` flag to `lint` subparser; emit the schema-shaped object when set.**
- [ ] **Step 4: Run — PASS. Full suite — PASS.**
- [ ] **Step 5: Commit.**

```bash
git add src/octopus_kb_compound/cli.py schemas/cli/lint.json tests/test_cli.py CHANGELOG.md
git commit -m "feat: add --json flag to lint for agent consumers"
```

---

### Task 4: `impacted-pages` JSON output + schema

**Files:**
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `src/octopus_kb_compound/impact.py`
- Create: `schemas/cli/impacted-pages.json`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_impact.py`
- Modify: `CHANGELOG.md`

**Output schema:**

```json
{
  "$id": "octopus-kb/cli/impacted-pages",
  "type": "object",
  "required": ["page", "impacted", "next"],
  "additionalProperties": false,
  "properties": {
    "page": {"type": "string"},
    "impacted": {"type": "array", "items": {"type": "string"}},
    "next": {"type": "array", "items": {"type": "string"}}
  }
}
```

- [ ] **Step 1: Write the failing test**

```python
def test_cli_impacted_pages_json_output(tmp_path):
    import io, json, sys, jsonschema
    from pathlib import Path

    vault = tmp_path / "vault"
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    target = vault / "wiki" / "concepts" / "Topic.md"
    target.write_text(
        '---\ntitle: "Topic"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["impacted-pages", str(target), "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["page"] == "wiki/concepts/Topic.md"
    assert isinstance(data["impacted"], list)
    assert "impacted" in data and "next" in data

    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "cli" / "impacted-pages.json"
    jsonschema.validate(data, json.loads(schema_path.read_text(encoding="utf-8")))
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement** — add `--json` flag to `impacted-pages`, emit the object with `next` suggesting `lookup` and `neighbors` on the page.

- [ ] **Step 4: Run tests — PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/octopus_kb_compound/cli.py src/octopus_kb_compound/impact.py \
        schemas/cli/impacted-pages.json tests/test_cli.py \
        tests/test_impact.py CHANGELOG.md
git commit -m "feat: add JSON output and schema for impacted-pages"
```

---

### Task 5: Skill shelf + slash recipes

**Files:**
- Create: `skills/kb/SKILL.md`
- Create: `skills/kb/recipes/kb-retrieve.md`
- Create: `skills/kb/recipes/kb-lookup.md`
- Create: `skills/kb/recipes/kb-impact.md`
- Create: `tests/test_skill_assets.py`
- Modify: `CHANGELOG.md`

**SKILL.md content:**

```markdown
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
```

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_kb_skill_file_has_required_sections():
    path = Path(__file__).resolve().parent.parent / "skills" / "kb" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "name: kb" in content
    assert "# Operating Procedure" in content
    assert "## Forbidden" in content
    for phrase in (
        "octopus-kb retrieve-bundle",
        "octopus-kb lookup",
        "octopus-kb impacted-pages",
        "octopus-kb neighbors",
        "octopus-kb lint",
    ):
        assert phrase in content, f"missing command reference: {phrase}"


def test_kb_recipes_exist():
    recipes = Path(__file__).resolve().parent.parent / "skills" / "kb" / "recipes"
    for name in ("kb-retrieve.md", "kb-lookup.md", "kb-impact.md"):
        path = recipes / name
        assert path.exists(), f"missing recipe {name}"
        content = path.read_text(encoding="utf-8")
        assert content.strip().startswith("#")
        assert "octopus-kb" in content
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Write `SKILL.md` and the three recipe files.** Each recipe is a short markdown: header + 1-sentence description + exact command + one example input → output stub.

- [ ] **Step 4: Run tests — PASS.**

- [ ] **Step 5: Commit**

```bash
git add skills/kb/SKILL.md skills/kb/recipes/ tests/test_skill_assets.py CHANGELOG.md
git commit -m "feat: add kb skill with SOP and slash recipes"
```

---

### Task 6: Claude Code PreToolUse hook

**Files:**
- Create: `examples/hooks/kb-grep-guard.sh`
- Create: `examples/hooks/kb_pretool_extract.py`
- Create: `examples/.claude/settings.json.sample`
- Create: `docs/hooks/claude-code-pretooluse.md`
- Create: `tests/test_hook_script.py`
- Modify: `src/octopus_kb_compound/retrieve.py` (add `_touch_marker` helper; CLI uses it)
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Hook trigger rule (deterministic, not heuristic):** Claude Code's PreToolUse hook contract passes a JSON payload on stdin with fields `{tool_name, tool_input: {...}}`. The hook reads stdin, extracts `tool_input.path` when `tool_name == "Grep"`, and inspects that path. If the path *starts with* `wiki/` or `raw/` and `$OCTOPUS_KB_MARKER` (default `.octopus-kb/.retrieve-bundle-marker`) is absent, emit a stderr reminder and exit `0` (soft block).

The marker is "per-turn" because `octopus-kb retrieve-bundle` touches the file unconditionally on success. Turn boundaries are delimited by the user — no time-based heuristic. The sample `settings.json` demonstrates a UserPromptSubmit hook that deletes the marker to reset the guard per turn.

**Documented side effect:** `octopus-kb retrieve-bundle` writes (`touch`) `$VAULT/.octopus-kb/.retrieve-bundle-marker` as a side effect of a successful run. The CLI contract in `schemas/cli/retrieve-bundle.json` description calls this out. If the marker write fails (read-only filesystem, permission denied), the command still returns the bundle JSON and prints a warning to stderr; exit code stays `0`. This is the only "read command with write side effect" in the CLI; the behavior-capture contract justifies it.

- [ ] **Step 1: Write the failing test**

```python
import os
import stat
import subprocess
from pathlib import Path


def test_hook_script_exists_and_is_executable():
    path = Path(__file__).resolve().parent.parent / "examples" / "hooks" / "kb-grep-guard.sh"
    assert path.exists(), "kb-grep-guard.sh missing"
    mode = path.stat().st_mode
    assert mode & stat.S_IXUSR, "kb-grep-guard.sh must be executable"


def _pretool_payload(tool_name, path):
    import json as _json
    return _json.dumps({"tool_name": tool_name, "tool_input": {"path": path}})


def test_hook_warns_when_marker_missing_and_path_is_vault(tmp_path):
    path = Path(__file__).resolve().parent.parent / "examples" / "hooks" / "kb-grep-guard.sh"
    env = os.environ.copy()
    env["OCTOPUS_KB_MARKER"] = str(tmp_path / ".octopus-kb" / ".retrieve-bundle-marker")
    result = subprocess.run(
        [str(path)], env=env, capture_output=True, text=True,
        input=_pretool_payload("Grep", "wiki/concepts/foo.md"),
    )
    assert result.returncode == 0
    assert "retrieve-bundle" in result.stderr


def test_hook_stays_silent_when_marker_present(tmp_path):
    path = Path(__file__).resolve().parent.parent / "examples" / "hooks" / "kb-grep-guard.sh"
    marker = tmp_path / ".octopus-kb" / ".retrieve-bundle-marker"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env["OCTOPUS_KB_MARKER"] = str(marker)
    result = subprocess.run(
        [str(path)], env=env, capture_output=True, text=True,
        input=_pretool_payload("Grep", "wiki/x.md"),
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_hook_ignores_non_vault_paths(tmp_path):
    path = Path(__file__).resolve().parent.parent / "examples" / "hooks" / "kb-grep-guard.sh"
    env = os.environ.copy()
    env["OCTOPUS_KB_MARKER"] = str(tmp_path / "no-marker")
    result = subprocess.run(
        [str(path)], env=env, capture_output=True, text=True,
        input=_pretool_payload("Grep", "src/file.py"),
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_hook_ignores_non_grep_tools(tmp_path):
    path = Path(__file__).resolve().parent.parent / "examples" / "hooks" / "kb-grep-guard.sh"
    env = os.environ.copy()
    env["OCTOPUS_KB_MARKER"] = str(tmp_path / "no-marker")
    result = subprocess.run(
        [str(path)], env=env, capture_output=True, text=True,
        input=_pretool_payload("Read", "wiki/x.md"),
    )
    assert result.returncode == 0
    assert result.stderr == ""
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Write the hook script** (`examples/hooks/kb-grep-guard.sh`) and a tiny Python helper (`examples/hooks/kb_pretool_extract.py`). The bash wrapper pipes its own stdin into the Python helper via a regular pipe — NOT a heredoc — because a heredoc would rebind the Python process's stdin to the script source and starve it of the caller payload.

**`examples/hooks/kb-grep-guard.sh`:**

```bash
#!/usr/bin/env bash
# kb-grep-guard.sh: Claude Code PreToolUse hook for Grep.
# Stdin: JSON {tool_name, tool_input: {path, ...}} forwarded from Claude Code.
# Env: OCTOPUS_KB_MARKER overrides default marker path (for tests).

set -u
marker="${OCTOPUS_KB_MARKER:-.octopus-kb/.retrieve-bundle-marker}"
here="$(cd "$(dirname "$0")" && pwd)"

# Pipe caller stdin into the helper so `json.load(sys.stdin)` sees the real payload.
target="$(python3 "$here/kb_pretool_extract.py" || true)"

[ -n "$target" ] || exit 0

case "$target" in
  wiki/*|raw/*)
    if [ ! -e "$marker" ]; then
      echo "octopus-kb: run 'octopus-kb retrieve-bundle \"<task>\" --vault .' before grepping $target" >&2
    fi
    ;;
esac
exit 0
```

**`examples/hooks/kb_pretool_extract.py`:**

```python
#!/usr/bin/env python3
"""Reads a Claude Code PreToolUse JSON payload on stdin. Prints tool_input.path
when tool_name == 'Grep', else prints nothing. Fail-safe on parse errors."""
import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Grep":
        return 0
    path = payload.get("tool_input", {}).get("path", "")
    if path:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Both files are marked executable (`chmod +x`). The bash wrapper pipes its caller-provided stdin through the regular `python3 <script>` invocation, which preserves stdin correctly. If the payload is malformed or the tool is not `Grep`, the helper emits nothing and the hook exits silently.

Make it executable: `chmod +x examples/hooks/kb-grep-guard.sh`.

Also extend `octopus-kb retrieve-bundle` (in Task 2) to touch `.octopus-kb/.retrieve-bundle-marker` on successful run. Add a small test that asserts this side effect (add to `tests/test_retrieve.py` during this task, not Task 2, to avoid dep-ordering issues):

```python
def test_retrieve_bundle_touches_marker_file(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")

    from octopus_kb_compound.cli import main

    rc = main(["retrieve-bundle", "anything", "--vault", str(vault), "--json"])
    assert rc == 0
    marker = vault / ".octopus-kb" / ".retrieve-bundle-marker"
    assert marker.exists()


def test_retrieve_bundle_still_succeeds_when_marker_write_fails(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")

    import octopus_kb_compound.retrieve as retrieve_mod

    def always_fail(_path):
        raise OSError("permission denied")

    monkeypatch.setattr(retrieve_mod, "_touch_marker", always_fail)

    from octopus_kb_compound.cli import main
    rc = main(["retrieve-bundle", "x", "--vault", str(vault), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "marker" in captured.err.lower() or "warning" in captured.err.lower()
```

- [ ] **Step 4: Write `examples/.claude/settings.json.sample`** showing a complete PreToolUse + UserPromptSubmit config that (a) invokes the hook on Grep and (b) removes the marker when a new user prompt arrives.

- [ ] **Step 5: Document in `docs/hooks/claude-code-pretooluse.md`** — installation steps, how to customize, how to opt out.

- [ ] **Step 6: Run tests — PASS.**

- [ ] **Step 7: Commit**

```bash
git add examples/hooks/ examples/.claude/ docs/hooks/ \
        src/octopus_kb_compound/retrieve.py tests/test_retrieve.py \
        tests/test_hook_script.py README.md CHANGELOG.md
git commit -m "feat: add PreToolUse hook with deterministic marker-file trigger"
```

---

### Task 7: README SOP rewrite + `0.4.0` release

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml` (version → `0.4.0`)
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

**README opens with (verbatim in the final file):**

1. One-paragraph pitch: "octopus-kb is the agent's operating procedure for Obsidian-style knowledge bases. Instead of letting agents grep your vault, the CLI returns decisions: canonical identity, ordered evidence bundles, graph context, and impact plans."
2. A 5-line bash example: `retrieve-bundle → lookup → neighbors → impacted-pages → lint`.
3. "Install as a skill" with one line per platform (Claude Code, Codex — Phase C scope covers these two).
4. Link to full CLI reference under `docs/cli-reference.md`.

- [ ] **Step 1: Rewrite README top half.** Keep existing reference material lower in the file.

- [ ] **Step 2: Version bump + CHANGELOG move Unreleased under `## [0.4.0] - 2026-04-18`.**

- [ ] **Step 3: Update `docs/roadmap.md`** with `## 0.4.0 Decision-Output and Skill Shelf (2026-04-18)`.

- [ ] **Step 4: Smoke test**

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli --help
PYTHONPATH=src python -m octopus_kb_compound.cli lookup "Vector Store" --vault examples/minimal-vault --json
PYTHONPATH=src python -m octopus_kb_compound.cli retrieve-bundle "example" --vault examples/minimal-vault --json
PYTHONPATH=src python -m octopus_kb_compound.cli neighbors "wiki/INDEX.md" --vault examples/minimal-vault --json
```

All exit `0`, all JSON outputs validate against their schemas.

- [ ] **Step 5: Commit**

```bash
git add README.md pyproject.toml CHANGELOG.md docs/roadmap.md
git commit -m "chore: cut 0.4.0 with SOP-first README"
```

---

## Execution Notes

- Phase 0 must be merged before Phase C starts. `jsonschema` must already be a required dep.
- `--json` is the agent-facing format. Human-readable output stays line-based for terminal users.
- Do not rewrite existing test fixtures; extend them with new pages when needed.
- The hook is "soft block" by design: exit `0` + stderr reminder. Hard block (non-zero exit) is a future option once behavior data shows it is needed.

## Final Verification

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli --help
```

All tests pass. Help lists `lookup`, `retrieve-bundle`, `neighbors`, `impacted-pages`, `validate-frontmatter`, `lint`, `suggest-links`, `ingest-url`, `ingest-file`, `vault-summary`, `plan-maintenance`, `inspect-vault`, `normalize-vault`, `export-graph`.
