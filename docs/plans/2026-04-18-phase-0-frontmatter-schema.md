# Phase 0: Frontmatter Schema Extraction

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the implicit PageMeta validation scattered across `models.py`, `frontmatter.py`, `lint.py`, and `page_types.py` with a single declarative JSON Schema that anyone (human, agent, third-party tool, future Phase A validator) can use to decide whether a frontmatter block is valid. Keep behavior identical. Zero LLM involvement.

**Architecture:** One new file `schemas/page-meta.json` becomes the source of truth for shape, field enums, and required-field rules. A thin runtime validator in `src/octopus_kb_compound/schema.py` exposes `validate_frontmatter(data) -> list[SchemaFinding]`. Existing `lint.py` absorbs these findings under new codes `SCHEMA_INVALID_FIELD` and `SCHEMA_MISSING_FIELD`, keeping all cross-page rules (canonical collisions, alias logic, orphans) as-is because they are not expressible in JSON Schema. A new CLI verb `octopus-kb validate-frontmatter` reports schema-only issues for a file or vault.

**Tech Stack:** Python 3.11, `jsonschema>=4.18` as a runtime dependency (not optional), existing pytest suite.

---

## Delivery Rules

- TDD for every task: Step 1 writes a real failing test with a complete test body, Step 2 confirms it fails against current code, Step 3 is minimal implementation, Step 4 verifies PASS, Step 5 runs the full suite, Step 6 commits.
- After this phase, existing `lint_pages()` output must be a strict superset of what it emitted before: every prior finding still emitted, plus new `SCHEMA_*` codes for cases that were silently accepted.
- The schema is a JSON Schema draft 2020-12 document. No custom meta-schema.
- Version bumps: Phase 0 is a minor feature bump to `0.3.0` at release, after all 5 tasks land. Do not bump earlier.

## Coverage — what current informal rules move into the schema

| Current rule location | New home |
|---|---|
| `models.PageMeta` field list (type hints) | `schemas/page-meta.json` `properties` |
| `page_types.make_*_meta` allowed values for `type`/`role`/`layer` | `schemas/page-meta.json` `enum` |
| `Task 2 Phase 1 plan`: `status` ∈ `{draft, active, deprecated, archived}` | schema enum |
| `Task 2 Phase 1 plan`: `source_of_truth` ∈ `{canonical, supporting, derived, external}` | schema enum |
| `lint.MISSING_ROLE` | schema `required` |
| `lint.MISSING_SUMMARY` (wiki layer only) | schema `if`/`then` (layer=wiki → summary required non-empty) |
| Ingest metadata: `source_url` is a URI string, `fetched_at`/`converted_at` are ISO-8601 | schema `format` |

Cross-page rules stay in `lint.py`:

- `DUPLICATE_CANONICAL_PAGE`
- `CANONICAL_ALIAS_COLLISION`
- `ALIAS_COLLISION`
- `UNRESOLVED_ALIAS`
- `BROKEN_LINK`
- `ORPHAN_PAGE`

---

### Task 1: Author `schemas/page-meta.json`

**Files:**
- Create: `src/octopus_kb_compound/_schemas/page-meta.json` (shipped as package data; top-level `schemas/` is a symlink or copy for doc discoverability, see below)
- Create: `schemas/page-meta.json` (dev-checkout convenience copy; authoritative source is the package-data file)
- Create: `schemas/README.md`
- Create: `tests/test_page_meta_schema.py`
- Modify: `pyproject.toml` (add `jsonschema>=4.18` to `[project] dependencies`; add `[tool.setuptools.package-data] octopus_kb_compound = ["_schemas/*.json"]` to ensure wheels include it)
- Modify: `CHANGELOG.md`

**Why two copies:** `src/octopus_kb_compound/_schemas/page-meta.json` is the canonical runtime resource — it ships with the installed wheel. `schemas/page-meta.json` is the dev-checkout mirror that humans browse. Task 1 Step 3 includes a CI-level test (below) that asserts the two files have byte-identical content; drift between them fails loudly.

**Schema shape (authoritative excerpt — full file should follow the same style):**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AlataChan/octopus-kb-compound/schemas/page-meta.json",
  "title": "PageMeta",
  "type": "object",
  "required": ["title", "type", "lang", "role"],
  "additionalProperties": true,
  "properties": {
    "title": {"type": "string", "minLength": 1},
    "type": {"type": "string", "enum": ["concept", "entity", "comparison", "timeline", "log", "note", "meta", "raw_source"]},
    "lang": {"type": "string", "minLength": 2},
    "role": {"type": "string", "enum": ["concept", "entity", "comparison", "timeline", "log", "index", "schema", "note", "raw_source"]},
    "layer": {"type": "string", "enum": ["wiki", "source", "archive"]},
    "canonical_name": {"type": "string", "minLength": 1},
    "status": {"type": "string", "enum": ["draft", "active", "deprecated", "archived"]},
    "source_of_truth": {"type": "string", "enum": ["canonical", "supporting", "derived", "external"]},
    "aliases": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": true},
    "related_entities": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": true},
    "tags": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "workflow": {"type": "array", "items": {"type": "string"}},
    "authors": {"type": "array", "items": {"type": "string"}},
    "publisher": {"type": "string"},
    "published": {"type": "string"},
    "source_url": {"type": "string", "format": "uri"},
    "source_file": {"type": "string"},
    "original_format": {"type": "string"},
    "ingest_method": {"type": "string"},
    "fetched_at": {"type": "string", "format": "date-time"},
    "converted_at": {"type": "string", "format": "date-time"},
    "changelog": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"}
  },
  "allOf": [
    {
      "if": {"properties": {"layer": {"const": "wiki"}}, "required": ["layer"]},
      "then": {
        "properties": {"summary": {"type": "string", "minLength": 1}},
        "required": ["summary"]
      }
    }
  ]
}
```

`additionalProperties: true` on purpose: legacy vaults may carry extra keys. The schema is a **validation floor** — it enforces shape and values of every field it declares, but does not exhaustively enumerate fields. Tighter schemas are a v0.6+ concern.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

import pytest


def _load_schema():
    path = Path(__file__).resolve().parent.parent / "schemas" / "page-meta.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_file_exists_and_is_valid_json_schema():
    from jsonschema import Draft202012Validator

    schema = _load_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["title"] == "PageMeta"
    assert "title" in schema["required"]
    assert "type" in schema["required"]
    assert "role" in schema["required"]


def test_schema_rejects_unknown_role_value():
    from jsonschema import Draft202012Validator

    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors({
        "title": "t", "type": "concept", "lang": "en", "role": "bogus-role"
    }))
    assert any("bogus-role" in str(e.message) for e in errors)


def test_schema_requires_summary_on_wiki_layer_pages():
    from jsonschema import Draft202012Validator

    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors({
        "title": "t", "type": "concept", "lang": "en", "role": "concept", "layer": "wiki"
    }))
    messages = " ".join(str(e.message) for e in errors)
    assert "summary" in messages


def test_schema_accepts_minimal_raw_source_page():
    from jsonschema import Draft202012Validator

    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors({
        "title": "t", "type": "raw_source", "lang": "en", "role": "raw_source", "layer": "source"
    }))
    assert errors == []


def test_package_data_schema_matches_dev_copy():
    """The shipped wheel resource and the dev-checkout copy must stay in sync."""
    import importlib.resources as resources

    package_bytes = (resources.files("octopus_kb_compound") / "_schemas" / "page-meta.json").read_bytes()
    dev_path = Path(__file__).resolve().parent.parent / "schemas" / "page-meta.json"
    dev_bytes = dev_path.read_bytes()
    assert package_bytes == dev_bytes, (
        "src/octopus_kb_compound/_schemas/page-meta.json and schemas/page-meta.json diverged; "
        "they must stay byte-identical"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
PYTHONPATH=src python -m pytest tests/test_page_meta_schema.py -v
```

Expected: FAIL because `schemas/page-meta.json` does not exist and `jsonschema` import may also fail if not installed.

- [ ] **Step 3: Minimal implementation**

1. Add `jsonschema>=4.18` to `pyproject.toml` under `[project] dependencies` (not optional).
2. Install it in the project venv: `pip install jsonschema`.
3. Write `schemas/page-meta.json` matching the excerpt above.
4. Write `schemas/README.md` with one paragraph: what the schema is for, how to use it, how to propose changes (PR against this file).

- [ ] **Step 4: Run test to verify it passes**

```
PYTHONPATH=src python -m pytest tests/test_page_meta_schema.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Full suite**

```
PYTHONPATH=src python -m pytest -q
```

Expected: `89 passed` (up from 85).

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/_schemas/page-meta.json schemas/page-meta.json \
        schemas/README.md tests/test_page_meta_schema.py pyproject.toml CHANGELOG.md
git commit -m "feat: add PageMeta JSON Schema as shared validation floor"
```

---

### Task 2: Runtime validator module

**Files:**
- Create: `src/octopus_kb_compound/schema.py`
- Modify: `src/octopus_kb_compound/__init__.py` (export `validate_frontmatter`)
- Create: `tests/test_schema_module.py`
- Modify: `CHANGELOG.md`

**Module contract:**

```python
from octopus_kb_compound.schema import (
    SchemaFinding,
    load_page_meta_schema,
    validate_frontmatter,
)

findings: list[SchemaFinding] = validate_frontmatter({
    "title": "x", "type": "concept", "lang": "en", "role": "bogus"
})
# SchemaFinding(code="SCHEMA_INVALID_FIELD", field="role", message="...", severity="error")
```

`SchemaFinding` is a frozen dataclass with fields `code`, `field`, `message`, `severity`.

`code` is one of:
- `SCHEMA_MISSING_FIELD` — a required field is absent
- `SCHEMA_INVALID_FIELD` — a field violates its enum/type/format/pattern
- `SCHEMA_INVALID_CONDITIONAL` — an `if`/`then` branch fails (e.g., wiki page missing non-empty summary)

The module loads the schema once at import time from `schemas/page-meta.json` (located relative to the package). Tests may override the path via `load_page_meta_schema(path)`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path


def test_validate_frontmatter_returns_empty_for_valid_concept():
    from octopus_kb_compound.schema import validate_frontmatter

    findings = validate_frontmatter({
        "title": "RAG Operations",
        "type": "concept",
        "lang": "en",
        "role": "concept",
        "layer": "wiki",
        "summary": "Ops wrapper around a retrieval-augmented generation stack.",
    })
    assert findings == []


def test_validate_frontmatter_reports_missing_required_field():
    from octopus_kb_compound.schema import SchemaFinding, validate_frontmatter

    findings = validate_frontmatter({"type": "concept", "lang": "en", "role": "concept"})
    codes = {f.code for f in findings}
    fields = {f.field for f in findings}
    assert "SCHEMA_MISSING_FIELD" in codes
    assert "title" in fields


def test_validate_frontmatter_reports_invalid_enum_value():
    from octopus_kb_compound.schema import validate_frontmatter

    findings = validate_frontmatter({
        "title": "x", "type": "concept", "lang": "en", "role": "not-a-real-role"
    })
    codes = {f.code for f in findings}
    assert "SCHEMA_INVALID_FIELD" in codes
    assert any(f.field == "role" for f in findings)


def test_validate_frontmatter_reports_wiki_summary_conditional():
    from octopus_kb_compound.schema import validate_frontmatter

    findings = validate_frontmatter({
        "title": "x", "type": "concept", "lang": "en", "role": "concept", "layer": "wiki"
    })
    assert any(
        f.code in {"SCHEMA_MISSING_FIELD", "SCHEMA_INVALID_CONDITIONAL"} and f.field == "summary"
        for f in findings
    )


def test_validate_frontmatter_accepts_additional_unknown_keys():
    from octopus_kb_compound.schema import validate_frontmatter

    findings = validate_frontmatter({
        "title": "x", "type": "note", "lang": "en", "role": "note",
        "custom_user_field": "future-proofing"
    })
    assert findings == []


def test_validate_frontmatter_enforces_uri_format_on_source_url():
    from octopus_kb_compound.schema import validate_frontmatter

    findings = validate_frontmatter({
        "title": "x", "type": "raw_source", "lang": "en", "role": "raw_source",
        "layer": "source", "source_url": "not-a-valid-uri-because-no-scheme",
    })
    assert any(f.field == "source_url" and f.code == "SCHEMA_INVALID_FIELD" for f in findings)


def test_validate_frontmatter_enforces_date_time_format_on_fetched_at():
    from octopus_kb_compound.schema import validate_frontmatter

    findings = validate_frontmatter({
        "title": "x", "type": "raw_source", "lang": "en", "role": "raw_source",
        "layer": "source", "fetched_at": "yesterday afternoon",
    })
    assert any(f.field == "fetched_at" and f.code == "SCHEMA_INVALID_FIELD" for f in findings)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL (`src/octopus_kb_compound/schema.py` does not exist).

- [ ] **Step 3: Minimal implementation**

```python
# src/octopus_kb_compound/schema.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator


Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class SchemaFinding:
    code: str
    field: str
    message: str
    severity: Severity = "error"


_SCHEMA_CACHE: dict[str, dict] = {}


def _load_builtin_schema() -> dict:
    """Load the shipped PageMeta schema via importlib.resources."""
    from importlib.resources import files
    resource = files("octopus_kb_compound").joinpath("_schemas").joinpath("page-meta.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_page_meta_schema(path: Path | None = None) -> dict:
    if path is not None:
        key = str(path)
        if key not in _SCHEMA_CACHE:
            _SCHEMA_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
        return _SCHEMA_CACHE[key]
    if "__builtin__" not in _SCHEMA_CACHE:
        _SCHEMA_CACHE["__builtin__"] = _load_builtin_schema()
    return _SCHEMA_CACHE["__builtin__"]


def validate_frontmatter(data: dict, *, schema_path: Path | None = None) -> list[SchemaFinding]:
    schema = load_page_meta_schema(schema_path)
    # FormatChecker enables enforcement of "format": "uri", "date-time", etc.
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    findings: list[SchemaFinding] = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        field = ".".join(str(p) for p in error.absolute_path) or _missing_required_field(error)
        code = _code_for(error)
        findings.append(SchemaFinding(code=code, field=field, message=error.message))
    return findings


def _code_for(error) -> str:
    if error.validator == "required":
        return "SCHEMA_MISSING_FIELD"
    if error.validator in {"if", "then", "else", "allOf"}:
        return "SCHEMA_INVALID_CONDITIONAL"
    return "SCHEMA_INVALID_FIELD"


def _missing_required_field(error) -> str:
    if error.validator == "required":
        marker = "'"
        msg = error.message
        if marker in msg:
            parts = msg.split(marker)
            if len(parts) >= 2:
                return parts[1]
    return ""
```

Adjust the `_default_schema_path()` logic if the package layout places the schemas directory differently; the test suite will catch misplacement.

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src python -m pytest tests/test_schema_module.py -q
```

Expected: `7 passed` (5 base tests + 2 format-checker tests).

- [ ] **Step 5: Full suite**

Expected: `96 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/schema.py src/octopus_kb_compound/__init__.py \
        tests/test_schema_module.py CHANGELOG.md
git commit -m "feat: add runtime frontmatter schema validator"
```

---

### Task 3: Integrate schema findings into `lint_pages`

**Files:**
- Modify: `src/octopus_kb_compound/lint.py`
- Modify: `tests/test_lint.py`
- Modify: `CHANGELOG.md`

**Pre-audit required (Step 0) — operational checklist:**

Run this exact command before touching `lint.py`:

```bash
PYTHONPATH=src python -m pytest tests/ -q 2>&1 | head -5
grep -rn "lint_pages\|PageRecord" tests/ | grep -v __pycache__ > /tmp/lint-fixture-audit.txt
wc -l /tmp/lint-fixture-audit.txt
```

Open `/tmp/lint-fixture-audit.txt` and classify every fixture:

| Fixture intent | Required frontmatter additions |
|---|---|
| Valid page, used to test cross-page rule (duplicate canonical, alias, orphan, broken link) | Add `title`, `type`, `lang`, `role`; add `summary` if `layer == "wiki"` |
| Exercising MISSING_ROLE/MISSING_SUMMARY directly | Leave as-is. Test now asserts BOTH the existing code AND its SCHEMA equivalent (strict superset). |
| Exercising schema-invalid values directly (intent post-Phase-0) | No change needed. |

**Policy:** no existing assertion may be weakened; additions only. Fixture updates are committed separately *before* any `lint.py` change. The task has 7 explicit steps below.

**Contract:** `lint_pages(pages)` now prepends schema findings for every page before cross-page rules run. Existing finding codes stay emitted; `SCHEMA_MISSING_FIELD` / `SCHEMA_INVALID_FIELD` / `SCHEMA_INVALID_CONDITIONAL` are new. Existing `MISSING_ROLE` and `MISSING_SUMMARY` become redundant with the schema versions — keep them for backward compatibility but mark as equivalent to the schema codes in the docstring.

- [ ] **Step 1: Audit fixtures using the checklist above; edit `tests/test_lint.py` fixtures to add missing schema-required fields (`title`, `type`, `lang`, `role`, and `summary` for wiki-layer pages). No lint.py changes yet.**

- [ ] **Step 2: Run full suite — still green** (no behavior change yet):

```
PYTHONPATH=src python -m pytest -q
```

- [ ] **Step 3: Commit fixture-only changes first** (clean separation from behavior change):

```bash
git add tests/test_lint.py
git commit -m "test: add schema-required fields to lint fixtures (pre-schema integration)"
```

- [ ] **Step 4: Write the failing integration test**

```python
def test_lint_emits_schema_findings_for_invalid_role_value():
    from octopus_kb_compound.models import PageRecord
    from octopus_kb_compound.lint import lint_pages

    page = PageRecord(
        path="wiki/x.md",
        title="x",
        frontmatter={
            "title": "x",
            "type": "concept",
            "lang": "en",
            "role": "not-a-real-role",
            "layer": "wiki",
            "summary": "s",
        },
        body="",
    )
    findings = lint_pages([page])
    codes = {f.code for f in findings}
    assert "SCHEMA_INVALID_FIELD" in codes


def test_lint_still_emits_existing_codes_unchanged():
    from octopus_kb_compound.models import PageRecord
    from octopus_kb_compound.lint import lint_pages

    a = PageRecord(
        path="wiki/a.md", title="Shared",
        frontmatter={
            "title": "Shared", "type": "concept", "lang": "en", "role": "concept",
            "layer": "wiki", "summary": "s", "source_of_truth": "canonical",
        },
        body="",
    )
    b = PageRecord(
        path="wiki/b.md", title="Shared",
        frontmatter={
            "title": "Shared", "type": "concept", "lang": "en", "role": "concept",
            "layer": "wiki", "summary": "s", "source_of_truth": "canonical",
        },
        body="",
    )
    findings = lint_pages([a, b])
    assert any(f.code == "DUPLICATE_CANONICAL_PAGE" for f in findings)
```

- [ ] **Step 5: Run tests — FAIL** (`SCHEMA_INVALID_FIELD` not emitted today).

- [ ] **Step 6: Minimal implementation**

Prepend the schema sweep at the start of `lint_pages`:

```python
from octopus_kb_compound.schema import validate_frontmatter
from octopus_kb_compound.models import LintFinding

def lint_pages(pages):
    findings: list[LintFinding] = []
    for page in pages:
        for sf in validate_frontmatter(page.frontmatter):
            findings.append(LintFinding(code=sf.code, path=page.path, message=f"{sf.field}: {sf.message}"))
    # ... existing cross-page logic stays below, unchanged ...
```

- [ ] **Step 7: Run tests — PASS. Full suite — PASS. Commit.**

```bash
git add src/octopus_kb_compound/lint.py tests/test_lint.py CHANGELOG.md
git commit -m "feat: emit schema findings from lint_pages"
```

---

### Task 4: CLI verb `validate-frontmatter`

**Files:**
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `CHANGELOG.md`

**CLI contract:**

```
octopus-kb validate-frontmatter <vault-or-file> [--json]
```

- Both single-file and directory modes use `parse_document(raw, strict=True)` directly (not `scan_markdown_files`, which is lenient). On `FrontmatterError` (malformed delimiter), emit a `PARSE_FAILURE` finding attributed to the file path and continue to the next file.
- Run schema validation against each parsed frontmatter. Print one line per finding (`<code>\t<path>\t<field>\t<message>`) or a JSON object with `findings: [...]`.
- For directories: walk all `.md` files under the root, excluding any path segment starting with `.` (hidden directories).
- Exit codes: `0` = no findings; `1` = at least one finding (schema or parse); `2` = invalid argument (missing path, unreadable file that cannot even be opened).

- [ ] **Step 1: Write the failing test**

```python
def test_cli_validate_frontmatter_reports_invalid_enum(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "bad.md").write_text(
        '---\ntitle: "bad"\ntype: concept\nlang: en\nrole: not-a-real-role\n'
        'layer: wiki\nsummary: "s"\ntags: []\n---\n',
        encoding="utf-8",
    )
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")

    import io
    import json
    import sys

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["validate-frontmatter", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 1
    data = json.loads(buf.getvalue())
    codes = {finding["code"] for finding in data["findings"]}
    assert "SCHEMA_INVALID_FIELD" in codes


def test_cli_validate_frontmatter_reports_malformed_as_parse_failure(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (vault / "wiki" / "broken.md").write_text(
        '---\ntitle: "b"\nrole: concept\n# no closing fence\nbody here\n',
        encoding="utf-8",
    )

    import io, json, sys
    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["validate-frontmatter", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 1
    data = json.loads(buf.getvalue())
    codes = {finding["code"] for finding in data["findings"]}
    assert "PARSE_FAILURE" in codes
    assert any(f["path"].endswith("broken.md") for f in data["findings"])


def test_cli_validate_frontmatter_exits_0_when_clean(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "good.md").write_text(
        '---\ntitle: "good"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsummary: "s"\ntags: []\n---\n',
        encoding="utf-8",
    )
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")

    from octopus_kb_compound.cli import main

    rc = main(["validate-frontmatter", str(vault)])
    assert rc == 0
```

- [ ] **Step 2: Run tests — FAIL** (command does not exist).

- [ ] **Step 3: Implementation**

Add a subparser in `cli.py` that accepts one positional path (file or directory). For both single-file and directory modes, call `parse_document(raw, strict=True)` **directly** for every `.md` file — do NOT use `scan_markdown_files`, which parses leniently and hides malformed frontmatter.

Directory mode implementation (~10 lines):

```python
for path in sorted(root.rglob("*.md")):
    rel = path.relative_to(root)
    if any(part.startswith(".") for part in rel.parts):
        continue
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, _ = parse_document(raw, strict=True)
    except FrontmatterError:
        findings.append({"code": "PARSE_FAILURE", "path": str(rel),
                         "field": "", "message": "frontmatter opened but never closed"})
        continue
    for sf in validate_frontmatter(frontmatter):
        findings.append({"code": sf.code, "path": str(rel),
                         "field": sf.field, "message": sf.message})
```

JSON output is `{"findings": [{"code": ..., "path": ..., "field": ..., "message": ...}]}`.

- [ ] **Step 4: Run tests — PASS.**

- [ ] **Step 5: Full suite — PASS.**

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/cli.py tests/test_cli.py CHANGELOG.md
git commit -m "feat: add validate-frontmatter CLI verb"
```

---

### Task 5: Version bump and docs

**Files:**
- Modify: `pyproject.toml` (version → `0.3.0`)
- Modify: `CHANGELOG.md` (move Unreleased entries into `## [0.3.0] - 2026-04-18`)
- Modify: `docs/roadmap.md`
- Modify: `README.md` (one paragraph under "Validation" pointing at the schema)

- [ ] **Step 1: Update files as above.**
- [ ] **Step 2: Smoke test**

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli validate-frontmatter examples/minimal-vault
PYTHONPATH=src python -m octopus_kb_compound.cli validate-frontmatter examples/expanded-vault --json
```

All must succeed.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml CHANGELOG.md docs/roadmap.md README.md
git commit -m "chore: cut 0.3.0 with frontmatter schema"
```

---

## Execution Notes

- `jsonschema>=4.18` is a new **required** runtime dep. Document this in README under install.
- Do not remove `MISSING_ROLE` or `MISSING_SUMMARY` codes; downstream consumers may depend on them. They become equivalents to schema codes for the same conditions.
- `additionalProperties: true` is deliberate. This schema acts as a floor, not a ceiling. We can tighten later once the ecosystem settles.
- No LLM involvement anywhere in this phase.

## Final Verification

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli validate-frontmatter examples/minimal-vault
```

Expected test counts by task:

| After task | Approximate passing count |
|---|---|
| Baseline (0.2.1) | 85 |
| Task 1 | 89 (4 new schema-file tests) |
| Task 2 | 96 (7 new runtime tests) |
| Task 3 | 98 (2 new lint integration tests) |
| Task 4 | 101 (3 new CLI tests) |

Task 3 fixture updates do not change the count; they adjust existing tests. `validate-frontmatter` on clean fixture returns exit 0.
