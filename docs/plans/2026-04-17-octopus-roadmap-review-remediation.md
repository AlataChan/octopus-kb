# Octopus Roadmap Review Remediation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the high and medium severity findings from the 2026-04-17 Codex code review of the roadmap implementation so the package's safety, schema, and CLI contracts match the plan document verbatim.

**Architecture:** Close contract gaps from the inside out. Start with correctness of the deterministic core (lint canonical rules, frontmatter YAML safety). Then fix migrate/export atomicity with real commit-phase tests. Then tighten the CLI exit-code contract while factoring shared validation helpers in the same pass. Each phase is independently testable and cannot start before the prior phase is green.

**Tech Stack:** Python 3.11, `pytest`, setuptools CLI entrypoints, existing markdown vault fixtures.

---

## Delivery Rules

- Execute phases in order. Do not start the next phase until the current phase is green.
- Use TDD for every behavior change: failing test first, verify failure against current code, minimal implementation, verify pass.
- Preserve existing CLI command names and current passing tests. When a test in another file must change because a shared behavior changes, list that test file in the task's Files section and update its assertions in the same commit.
- After each task, run the targeted test first, then `PYTHONPATH=src python -m pytest -q`.
- Update `CHANGELOG.md` in every task commit with a short `Unreleased` entry.
- Do not bump the package version in this plan until the last task; all changes ride on top of `0.2.0` as bug fixes and cut as `0.2.1` once remediation is green.

## Review Findings Coverage

Source: Codex review of `src/` diff `353cf68..HEAD` on 2026-04-17, followed by Codex plan review on 2026-04-17.

| Severity | Finding | Task |
|---|---|---|
| High | `migrate.py:57` rollback misses newly created files | Task 4 |
| High | `lint.py:85` raw-source `canonical_name` bypass | Task 1 |
| High | `export.py:44` alias node id duplicates | Task 3 |
| Medium | `migrate.py:88` non-transactional multi-file writes | Task 4 |
| Medium | `migrate.py:35` malformed frontmatter slips past preflight | Task 5 |
| Medium | `lint.py:93` title fallback ignores `layer == "wiki"` gate | Task 1 |
| Medium | `export.py:58` drops `related_entities` metadata edges | Task 3 |
| Medium | `export.py:97` non-atomic artifact directory writes | Task 3 |
| Medium | `cli.py:230` `export-graph --out` file collision = exit 1 | Task 6 |
| Medium | `cli.py:175` impacted-pages / plan-maintenance directory-as-page = exit 1 | Task 6 |
| Medium | `cli.py:150` ingest-file dependency error = exit 2 | Task 6 |
| Medium | `frontmatter.py:42` unquoted scalars in list fields | Task 2 |
| Low | `cli.py:67` repeated validation blocks | Task 6 (folded) |
| Deferred | `cli.py:175` vault sandbox (`is_relative_to(vault)`) — not contracted in original plan, decision deferred | `docs/roadmap.md` in Task 7 |
| Deferred | `ingest.py:25` SSRF DNS resolution — adds DNS to hot path, decision deferred | `docs/roadmap.md` in Task 7 |

---

### Task 1: Phase 1 Lint Canonical Identity Fix

**Files:**
- Modify: `src/octopus_kb_compound/lint.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_lint.py`

**Context:**
The plan's canonical-identity resolution order in `docs/plans/2026-04-14-octopus-roadmap-implementation.md` Task 3 is:

1. `frontmatter["canonical_name"]`
2. `frontmatter["title"]` when `frontmatter["source_of_truth"] == "canonical"`
3. `frontmatter["title"]` for non-raw wiki pages where `role != "raw_source"` and `type != "raw_source"`
4. The markdown path stem as a fallback for non-raw wiki pages only

"Raw source pages are not canonical pages unless they explicitly set `source_of_truth: canonical`."

Current `src/octopus_kb_compound/lint.py:85` returns a canonical key for any page with `canonical_name` set — including raw source pages that never set `source_of_truth: canonical`. Current `src/octopus_kb_compound/lint.py:93` also canonicalizes non-wiki non-raw pages via title, and never falls back to path stem when a wiki page has no title.

The three tests below each provoke a concrete contract violation against the current implementation: raw-source bypass, missing path-stem fallback, and the positive case where raw explicitly opts into canonical.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_lint.py`:

```python
def test_canonical_key_ignores_raw_source_with_canonical_name_only():
    raw_page = PageRecord(
        path="raw/example.md",
        title="Example",
        frontmatter={
            "title": "Example",
            "role": "raw_source",
            "layer": "source",
            "canonical_name": "Example",
        },
        body="",
    )
    wiki_page = PageRecord(
        path="wiki/concepts/example.md",
        title="Example",
        frontmatter={
            "title": "Example",
            "role": "concept",
            "layer": "wiki",
            "source_of_truth": "canonical",
        },
        body="",
    )
    findings = lint_pages([raw_page, wiki_page])
    assert not any(f.code == "DUPLICATE_CANONICAL_PAGE" for f in findings)


def test_canonical_key_path_stem_fallback_triggers_for_wiki_pages_without_title():
    titleless_wiki = PageRecord(
        path="wiki/concepts/example.md",
        title="",
        frontmatter={"role": "concept", "layer": "wiki"},
        body="",
    )
    named_wiki = PageRecord(
        path="wiki/concepts/other.md",
        title="example",
        frontmatter={"title": "example", "role": "concept", "layer": "wiki"},
        body="",
    )
    findings = lint_pages([titleless_wiki, named_wiki])
    assert any(f.code == "DUPLICATE_CANONICAL_PAGE" for f in findings), (
        "wiki page without title must canonicalize on its path stem and collide with a matching titled wiki page"
    )


def test_canonical_key_honors_raw_source_that_opts_into_canonical():
    raw_canonical = PageRecord(
        path="raw/example.md",
        title="Example",
        frontmatter={
            "title": "Example",
            "role": "raw_source",
            "layer": "source",
            "source_of_truth": "canonical",
        },
        body="",
    )
    wiki_page = PageRecord(
        path="wiki/concepts/example.md",
        title="Example",
        frontmatter={
            "title": "Example",
            "role": "concept",
            "layer": "wiki",
            "source_of_truth": "canonical",
        },
        body="",
    )
    findings = lint_pages([raw_canonical, wiki_page])
    assert any(f.code == "DUPLICATE_CANONICAL_PAGE" for f in findings), (
        "raw source explicitly marked source_of_truth: canonical must still participate in canonical identity"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_lint.py::test_canonical_key_ignores_raw_source_with_canonical_name_only tests/test_lint.py::test_canonical_key_path_stem_fallback_triggers_for_wiki_pages_without_title tests/test_lint.py::test_canonical_key_honors_raw_source_that_opts_into_canonical -v`

Expected: all three FAIL — first reports a spurious `DUPLICATE_CANONICAL_PAGE`, second and third expect duplicates that current code does not produce.

- [ ] **Step 3: Write minimal implementation**

Add to the top of `src/octopus_kb_compound/lint.py`:

```python
from pathlib import Path
```

Replace `_canonical_key` with:

```python
def _canonical_key(page: PageRecord) -> str | None:
    frontmatter = page.frontmatter
    role = frontmatter.get("role")
    page_type = frontmatter.get("type")
    layer = frontmatter.get("layer")
    source_of_truth = frontmatter.get("source_of_truth")
    is_raw = role == "raw_source" or page_type == "raw_source"

    if is_raw and source_of_truth != "canonical":
        return None

    canonical_name = frontmatter.get("canonical_name")
    if isinstance(canonical_name, str) and normalize_page_name(canonical_name):
        return normalize_page_name(canonical_name)

    title = str(frontmatter.get("title") or page.title or "")
    if source_of_truth == "canonical" and normalize_page_name(title):
        return normalize_page_name(title)

    if is_raw:
        return None

    if layer != "wiki":
        return None

    if normalize_page_name(title):
        return normalize_page_name(title)

    stem = Path(page.path).stem
    if normalize_page_name(stem):
        return normalize_page_name(stem)

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_lint.py -q`
Expected: PASS.

- [ ] **Step 5: Verify full suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/lint.py tests/test_lint.py CHANGELOG.md
git commit -m "fix: gate canonical identity for raw sources and wiki path fallback"
```

---

### Task 2: Phase 1 Frontmatter YAML Scalar Safety

**Files:**
- Modify: `src/octopus_kb_compound/frontmatter.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_frontmatter.py`
- Modify: `tests/test_ingest.py`

**Scope:**
Quote only the fields that accept free-form user or content-derived values and that are already known to accept characters requiring YAML quoting:

- Lists: `tags`, `related_entities`, `workflow`
- Scalars: `original_format`, `ingest_method`, `status`, `source_of_truth`

Controlled vocabulary fields that never contain special characters in practice (`role`, `layer`, `type`, `lang`) stay unquoted.

The `workflow`, `status`, and `source_of_truth` quoting are additive — no existing tests assert their unquoted form — but `tags`, `related_entities`, `original_format`, and `ingest_method` are exercised by `tests/test_frontmatter.py` and `tests/test_ingest.py`. Update those assertions in the same commit to the new quoted form.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_frontmatter.py`:

```python
def test_render_frontmatter_quotes_scalars_containing_special_characters():
    meta = PageMeta(
        title="t",
        page_type="note",
        lang="en",
        related_entities=["Vector: Store", "Foo # bar"],
        tags=["release: 2026", "api/v1"],
        original_format="md: variant",
        ingest_method="jina: reader",
        status="active",
        source_of_truth="canonical",
        workflow=["review: weekly"],
        summary="",
    )
    rendered = render_frontmatter(meta)
    assert '- "Vector: Store"' in rendered
    assert '- "Foo # bar"' in rendered
    assert '- "release: 2026"' in rendered
    assert '- "api/v1"' in rendered
    assert 'original_format: "md: variant"' in rendered
    assert 'ingest_method: "jina: reader"' in rendered
    assert 'status: "active"' in rendered
    assert 'source_of_truth: "canonical"' in rendered
    assert '- "review: weekly"' in rendered

    frontmatter, _ = parse_document(rendered + "\n")
    assert frontmatter["related_entities"] == ["Vector: Store", "Foo # bar"]
    assert frontmatter["tags"] == ["release: 2026", "api/v1"]
    assert frontmatter["original_format"] == "md: variant"
    assert frontmatter["ingest_method"] == "jina: reader"
    assert frontmatter["status"] == "active"
    assert frontmatter["source_of_truth"] == "canonical"
    assert frontmatter["workflow"] == ["review: weekly"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_frontmatter.py::test_render_frontmatter_quotes_scalars_containing_special_characters -v`
Expected: FAIL — current emission is unquoted, breaks round trip on colon-bearing values.

- [ ] **Step 3: Write minimal implementation**

In `src/octopus_kb_compound/frontmatter.py`, replace the emission blocks:

```python
    if meta.workflow:
        lines.append("workflow:")
        for item in meta.workflow:
            lines.append(f'  - "{_quote(item)}"')
```

```python
    if meta.status:
        lines.append(f'status: "{_quote(meta.status)}"')
    if meta.source_of_truth:
        lines.append(f'source_of_truth: "{_quote(meta.source_of_truth)}"')
```

```python
    if meta.related_entities:
        lines.append("related_entities:")
        for entity in meta.related_entities:
            lines.append(f'  - "{_quote(entity)}"')
```

```python
    if meta.tags:
        lines.append("tags:")
        for tag in meta.tags:
            lines.append(f'  - "{_quote(tag)}"')
    else:
        lines.append("tags: []")
```

```python
    if meta.original_format:
        lines.append(f'original_format: "{_quote(meta.original_format)}"')
    if meta.ingest_method:
        lines.append(f'ingest_method: "{_quote(meta.ingest_method)}"')
```

`parse_document()` already strips surrounding double quotes via `_strip_value`, so the round trip stays lossless.

- [ ] **Step 4: Update existing assertions that read unquoted forms**

Search both test files and update:

```bash
PYTHONPATH=src python -m pytest tests/test_frontmatter.py tests/test_ingest.py -v
```

For any failing assertion that checks for the unquoted prefix (for example `"ingest_method: jina-reader"`, `"original_format: html"`, `"- Chunking"` under `tags:` or `related_entities:`), change the expected string to the quoted form (`'ingest_method: "jina-reader"'`, `'original_format: "html"'`, `'  - "Chunking"'`). Do not change the values themselves, only the assertion form.

- [ ] **Step 5: Run test to verify everything passes**

Run: `PYTHONPATH=src python -m pytest tests/test_frontmatter.py tests/test_ingest.py -q`
Expected: PASS.

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/frontmatter.py tests/test_frontmatter.py tests/test_ingest.py CHANGELOG.md
git commit -m "fix: quote user-content scalars in frontmatter and align tests"
```

---

### Task 3: Phase 2 Export Alias Dedup, Metadata Edges, Directory-Atomic Writes

**Files:**
- Modify: `src/octopus_kb_compound/export.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_export.py`

**Context:**
Three gaps in `src/octopus_kb_compound/export.py`:

1. `_nodes()` appends an alias node every time a page declares an alias. Two pages sharing an alias produce two node objects with the same `id`.
2. `_edges()` only emits `wikilink` and `alias` relations. The plan lists `related_entities` in the metadata model and says "wikilinks and metadata references become edges." Emit page-to-page `wikilink` edges for each resolvable `related_entities` entry. `relation_type` remains in the allowed set `wikilink | alias | hierarchy`.
3. `export_graph_artifacts()` writes four JSON files into `output` directly. A failure partway through leaves a mixed state. Do directory-level atomicity: capture the existing artifact set in a sibling backup directory before writing, write new artifacts into a staging sibling directory, then swap files atomically via `os.replace`. On any failure after the first `os.replace`, restore the backup copies and delete artifacts that did not exist before.

Also address shared-alias edge correctness: when an alias node is shared across pages, each page-to-alias edge is still emitted distinctly, but alias collisions (one alias resolving to two canonical pages) are a lint-level concern, not an export suppression. Export simply records the resolved pairs it sees; `lint` is responsible for flagging the collision. The test below asserts both pages keep their alias edges.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_export.py`:

```python
import json
from pathlib import Path

from octopus_kb_compound.export import export_graph_artifacts


def _write_page(vault: Path, rel: str, frontmatter_lines: list[str], body: str = "") -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body
    path.write_text(content, encoding="utf-8")


def test_export_nodes_dedupe_alias_nodes(tmp_path):
    vault = tmp_path / "vault"
    _write_page(
        vault,
        "wiki/a.md",
        [
            'title: "A"',
            "type: concept",
            "lang: en",
            "role: concept",
            "layer: wiki",
            "aliases:",
            '  - "Shared"',
            "tags: []",
        ],
    )
    _write_page(
        vault,
        "wiki/b.md",
        [
            'title: "B"',
            "type: concept",
            "lang: en",
            "role: concept",
            "layer: wiki",
            "aliases:",
            '  - "Shared"',
            "tags: []",
        ],
    )
    out = tmp_path / "out"
    export_graph_artifacts(vault, out)

    nodes = json.loads((out / "nodes.json").read_text())
    alias_ids = [n["id"] for n in nodes if n["type"] == "alias"]
    assert len(alias_ids) == len(set(alias_ids)), "alias nodes must be unique by id"

    edges = json.loads((out / "edges.json").read_text())
    shared_targets = {e["target"] for e in edges if e["source"] == "alias:shared" and e["relation_type"] == "alias"}
    assert shared_targets == {"page:wiki/a.md", "page:wiki/b.md"}, (
        "shared alias nodes must still connect to every declaring page"
    )


def test_export_edges_include_related_entities(tmp_path):
    vault = tmp_path / "vault"
    _write_page(
        vault,
        "wiki/concept.md",
        [
            'title: "Concept"',
            "type: concept",
            "lang: en",
            "role: concept",
            "layer: wiki",
            "related_entities:",
            '  - "Entity"',
            "tags: []",
        ],
    )
    _write_page(
        vault,
        "wiki/entity.md",
        [
            'title: "Entity"',
            "type: entity",
            "lang: en",
            "role: entity",
            "layer: wiki",
            "tags: []",
        ],
    )
    out = tmp_path / "out"
    export_graph_artifacts(vault, out)
    edges = json.loads((out / "edges.json").read_text())
    assert any(
        e["source"] == "page:wiki/concept.md"
        and e["target"] == "page:wiki/entity.md"
        and e["relation_type"] == "wikilink"
        for e in edges
    )


def test_export_is_directory_atomic_when_commit_fails(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _write_page(
        vault,
        "wiki/a.md",
        ['title: "A"', "type: concept", "lang: en", "role: concept", "layer: wiki", "tags: []"],
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "nodes.json").write_text('"previous_nodes"', encoding="utf-8")
    (out / "edges.json").write_text('"previous_edges"', encoding="utf-8")

    import octopus_kb_compound.export as export_module
    real_commit = export_module._commit_artifact
    calls = {"count": 0}

    def failing(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated commit failure")
        real_commit(src, dst)

    monkeypatch.setattr(export_module, "_commit_artifact", failing)

    try:
        export_graph_artifacts(vault, out)
    except OSError:
        pass

    assert (out / "nodes.json").read_text() == '"previous_nodes"', "nodes.json must be restored"
    assert (out / "edges.json").read_text() == '"previous_edges"', "edges.json must be restored"
    assert not (out / "manifest.json").exists(), "manifest.json did not exist before, must be absent after rollback"
    assert not (out / "aliases.json").exists(), "aliases.json did not exist before, must be absent after rollback"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_export.py -v`
Expected: FAIL — duplicate alias nodes, missing metadata edges, `_commit_artifact` does not exist yet, rollback does not restore previous artifacts.

- [ ] **Step 3: Write minimal implementation**

Rewrite `src/octopus_kb_compound/export.py` to implement directory-level atomicity via an explicit `_commit_artifact` helper:

```python
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from octopus_kb_compound.links import build_alias_index, extract_wikilinks, frontmatter_aliases, normalize_page_name
from octopus_kb_compound.models import PageRecord
from octopus_kb_compound.profile import load_vault_profile
from octopus_kb_compound.vault import scan_markdown_files


ARTIFACT_NAMES = ("nodes.json", "edges.json", "manifest.json", "aliases.json")


def export_graph_artifacts(vault: str | Path, out_dir: str | Path) -> None:
    root = Path(vault)
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)

    pages = scan_markdown_files(root, load_vault_profile(root))
    alias_index = build_alias_index(pages)
    nodes = _nodes(pages)
    node_ids = {node["id"] for node in nodes}
    edges = _edges(pages, alias_index, node_ids)
    manifest = {"pages": [page.path for page in pages]}

    with tempfile.TemporaryDirectory(prefix="octopus-export-", dir=str(output.parent)) as workspace:
        staging = Path(workspace) / "staging"
        staging.mkdir()
        _write_json(staging / "nodes.json", nodes)
        _write_json(staging / "edges.json", edges)
        _write_json(staging / "manifest.json", manifest)
        _write_json(staging / "aliases.json", alias_index)

        backup_dir = Path(workspace) / "backup"
        backup_dir.mkdir()
        pre_existing: dict[str, bool] = {}
        for name in ARTIFACT_NAMES:
            target = output / name
            pre_existing[name] = target.exists()
            if target.exists():
                shutil.copy2(target, backup_dir / name)

        committed: list[str] = []
        try:
            for name in ARTIFACT_NAMES:
                _commit_artifact(staging / name, output / name)
                committed.append(name)
        except OSError:
            for name in committed:
                backup = backup_dir / name
                target = output / name
                if pre_existing.get(name) and backup.exists():
                    shutil.copy2(backup, target)
                else:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass
            raise


def _commit_artifact(src: Path, dst: Path) -> None:
    os.replace(src, dst)


def _nodes(pages: list[PageRecord]) -> list[dict]:
    page_nodes: list[dict] = []
    alias_nodes: dict[str, dict] = {}
    for page in pages:
        aliases = frontmatter_aliases(page)
        page_nodes.append(
            {
                "id": _page_id(page),
                "title": page.title,
                "type": str(page.frontmatter.get("type") or page.frontmatter.get("role") or "page"),
                "role": page.frontmatter.get("role"),
                "layer": page.frontmatter.get("layer"),
                "aliases": aliases,
            }
        )
        for alias in aliases:
            node = {
                "id": _alias_id(alias),
                "title": alias,
                "type": "alias",
                "role": None,
                "layer": None,
                "aliases": [],
            }
            alias_nodes.setdefault(node["id"], node)
    return page_nodes + list(alias_nodes.values())


def _edges(pages: list[PageRecord], alias_index: dict[str, str], node_ids: set[str]) -> list[dict]:
    by_title = {page.title: page for page in pages}
    edges: list[dict] = []
    for page in pages:
        source = _page_id(page)
        for link in extract_wikilinks(page.body):
            target_title = alias_index.get(normalize_page_name(link))
            target = by_title.get(target_title or "")
            if target is None:
                continue
            edges.append({"source": source, "target": _page_id(target), "relation_type": "wikilink"})

        related = page.frontmatter.get("related_entities") or []
        if isinstance(related, list):
            for entity in related:
                if not isinstance(entity, str):
                    continue
                target_title = alias_index.get(normalize_page_name(entity))
                target = by_title.get(target_title or "")
                if target is None or target.path == page.path:
                    continue
                edges.append({"source": source, "target": _page_id(target), "relation_type": "wikilink"})

        for alias in frontmatter_aliases(page):
            alias_node = _alias_id(alias)
            if alias_node in node_ids:
                edges.append({"source": alias_node, "target": source, "relation_type": "alias"})
    return _dedupe_edges(edges)


def _page_id(page: PageRecord) -> str:
    return f"page:{page.path}"


def _alias_id(alias: str) -> str:
    return f"alias:{normalize_page_name(alias)}"


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (edge["source"], edge["target"], edge["relation_type"])
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_export.py -q`
Expected: PASS.

- [ ] **Step 5: Verify full suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/export.py tests/test_export.py CHANGELOG.md
git commit -m "fix: dedupe alias nodes, emit related_entities edges, atomic export"
```

---

### Task 4: Phase 3 Migration Rollback and Multi-File Commit Phase

**Files:**
- Modify: `src/octopus_kb_compound/migrate.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_migrate.py`

**Context:**
Current in-place apply in `src/octopus_kb_compound/migrate.py`:

1. `_backup_files()` only copies files that exist. Required files (`AGENTS.md`, `wiki/INDEX.md`, `wiki/LOG.md`) that get *created* during apply are never tracked for rollback.
2. `_write_normalized_files()` replaces each target immediately. If the 3rd file fails, the first two are already replaced on disk while the rest are untouched — not transaction-safe across files.

The fix:

- Introduce an explicit commit-boundary helper `_replace_staged_file(tmp, target)` so tests can inject failures exactly where commits happen without depending on the internal structure of `_atomic_write`.
- Track a rollback ledger with two sets: `modified` (pre-existing files backed up) and `created` (new files that did not exist before apply).
- Two-phase design:
  1. **Stage:** for every write, create a unique temp sibling file using `tempfile.NamedTemporaryFile(dir=target.parent, delete=False, prefix=f".{target.name}.", suffix=".octopus-tmp")` and write the normalized content into it. Record the `(tmp, target, existed)` triple.
  2. **Commit:** for each staged triple, if the target existed, copy the live file into the backup tree first; otherwise record it as `created`. Then call `_replace_staged_file(tmp, target)`.
- **Cleanup on stage failure:** remove every already-staged temp file.
- **Rollback on commit failure:** restore `modified` files from backup, delete `created` files, delete any remaining staged temp files.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_migrate.py`:

```python
from pathlib import Path
import pytest

from octopus_kb_compound.migrate import normalize_vault


def _seed_vault(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "wiki").mkdir()
    (root / "wiki" / "existing.md").write_text("# Existing\n", encoding="utf-8")


def test_normalize_in_place_rolls_back_created_required_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    import octopus_kb_compound.migrate as migrate_module
    real = migrate_module._replace_staged_file
    calls = {"count": 0}

    def failing(tmp, target):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise OSError("simulated commit failure")
        real(tmp, target)

    monkeypatch.setattr(migrate_module, "_replace_staged_file", failing)

    with pytest.raises(OSError):
        normalize_vault(vault, apply=True, in_place=True)

    assert not (vault / "AGENTS.md").exists(), "created AGENTS.md must be rolled back"
    assert not (vault / "wiki" / "INDEX.md").exists()
    assert not (vault / "wiki" / "LOG.md").exists()


def test_normalize_in_place_rolls_back_modified_existing_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    (vault / "AGENTS.md").write_text("# Pre-existing schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Pre-existing index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Pre-existing log\n", encoding="utf-8")

    before = {
        rel: (vault / rel).read_text(encoding="utf-8")
        for rel in ("wiki/existing.md", "AGENTS.md", "wiki/INDEX.md", "wiki/LOG.md")
    }

    import octopus_kb_compound.migrate as migrate_module
    real = migrate_module._replace_staged_file
    calls = {"count": 0}

    def failing(tmp, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated commit failure")
        real(tmp, target)

    monkeypatch.setattr(migrate_module, "_replace_staged_file", failing)

    with pytest.raises(OSError):
        normalize_vault(vault, apply=True, in_place=True)

    for rel, expected in before.items():
        assert (vault / rel).read_text(encoding="utf-8") == expected, f"{rel} must be restored"


def test_normalize_in_place_cleans_up_staging_files_on_rollback(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    (vault / "AGENTS.md").write_text("# Pre-existing\n", encoding="utf-8")

    import octopus_kb_compound.migrate as migrate_module
    real = migrate_module._replace_staged_file
    calls = {"count": 0}

    def failing(tmp, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated commit failure")
        real(tmp, target)

    monkeypatch.setattr(migrate_module, "_replace_staged_file", failing)

    with pytest.raises(OSError):
        normalize_vault(vault, apply=True, in_place=True)

    stray = [p for p in vault.rglob("*.octopus-tmp")]
    assert stray == [], f"no staged .octopus-tmp files should remain, found: {stray}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_migrate.py -v`
Expected: FAIL — `_replace_staged_file` does not exist, created files linger, staged temp files linger.

- [ ] **Step 3: Write minimal implementation**

Rewrite the in-place branch of `normalize_vault` in `src/octopus_kb_compound/migrate.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
import shutil
import tempfile

from octopus_kb_compound.frontmatter import FrontmatterError, parse_document, render_frontmatter
from octopus_kb_compound.models import PageMeta


REQUIRED_FILES = ("AGENTS.md", "wiki/INDEX.md", "wiki/LOG.md")


@dataclass(slots=True)
class MigrationReport:
    missing_files: list[str] = field(default_factory=list)
    pages_missing_frontmatter: list[str] = field(default_factory=list)
    parse_failures: list[str] = field(default_factory=list)
    normalized_files: list[str] = field(default_factory=list)
    staging_dir: str | None = None
    backup_dir: str | None = None


@dataclass(slots=True)
class _RollbackLedger:
    backup_root: Path
    modified: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)


def normalize_vault(root: str | Path, *, apply: bool = False, in_place: bool = False) -> MigrationReport:
    root_path = Path(root)
    report = inspect_vault_for_migration(root_path)
    if not apply or report.parse_failures:
        return report

    timestamp = _timestamp()
    if in_place:
        backup_dir = root_path / ".octopus-kb-migration" / "backups" / timestamp
        report.backup_dir = str(backup_dir)
        ledger = _RollbackLedger(backup_root=backup_dir)
        try:
            _apply_in_place(root_path, report, ledger)
        except OSError:
            _rollback(root_path, ledger)
            raise
        return report

    staging_dir = root_path / ".octopus-kb-migration" / "staging" / timestamp
    report.staging_dir = str(staging_dir)
    _copy_markdown_tree(root_path, staging_dir)
    _write_normalized_files(root_path, staging_dir, report)
    return report


def _apply_in_place(root: Path, report: MigrationReport, ledger: _RollbackLedger) -> None:
    plans: list[tuple[Path, str, bool]] = []
    for rel in report.pages_missing_frontmatter:
        source = root / rel
        existed = source.exists()
        raw = source.read_text(encoding="utf-8", errors="replace") if existed else ""
        content = f"{render_frontmatter(_default_meta_for_path(Path(rel)))}\n{raw.rstrip()}\n"
        plans.append((source, content, existed))
    for rel in report.missing_files:
        target = root / rel
        plans.append((target, _default_required_file(rel), target.exists()))

    staged: list[tuple[Path, Path, bool]] = []
    try:
        for target, content, existed in plans:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".octopus-tmp",
                delete=False,
            )
            try:
                handle.write(content)
            finally:
                handle.close()
            staged.append((Path(handle.name), target, existed))
    except OSError:
        for tmp, _, _ in staged:
            _safe_unlink(tmp)
        raise

    try:
        for tmp, target, existed in staged:
            rel = target.relative_to(root).as_posix()
            if existed:
                backup = ledger.backup_root / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                ledger.modified.append(rel)
            else:
                ledger.created.append(rel)
            _replace_staged_file(tmp, target)
            report.normalized_files.append(rel)
    except OSError:
        for tmp, _, _ in staged:
            _safe_unlink(tmp)
        raise


def _replace_staged_file(tmp: Path, target: Path) -> None:
    os.replace(tmp, target)


def _rollback(root: Path, ledger: _RollbackLedger) -> None:
    for rel in ledger.modified:
        backup = ledger.backup_root / rel
        if backup.exists():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
    for rel in ledger.created:
        _safe_unlink(root / rel)
    for stray in root.rglob("*.octopus-tmp"):
        _safe_unlink(stray)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def inspect_vault_for_migration(root: str | Path) -> MigrationReport:
    root_path = Path(root)
    report = MigrationReport()
    report.missing_files = [path for path in REQUIRED_FILES if not (root_path / path).exists()]

    for path in sorted(root_path.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root_path).parts):
            continue
        rel = path.relative_to(root_path).as_posix()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            frontmatter, _ = parse_document(raw, strict=True)
        except (OSError, FrontmatterError):
            report.parse_failures.append(rel)
            continue
        if not frontmatter:
            report.pages_missing_frontmatter.append(rel)
    return report


def render_migration_report(report: MigrationReport) -> str:
    lines: list[str] = []
    for path in report.missing_files:
        lines.append(f"missing_file\t{path}")
    for path in report.pages_missing_frontmatter:
        lines.append(f"missing_frontmatter\t{path}")
    for path in report.parse_failures:
        lines.append(f"parse_failure\t{path}")
    for path in report.normalized_files:
        lines.append(f"normalized\t{path}")
    if report.staging_dir:
        lines.append(f"staging_dir\t{report.staging_dir}")
    if report.backup_dir:
        lines.append(f"backup_dir\t{report.backup_dir}")
    return "\n".join(lines)


def _write_normalized_files(source_root: Path, target_root: Path, report: MigrationReport) -> None:
    for rel in report.pages_missing_frontmatter:
        source = source_root / rel
        target = target_root / rel
        raw = source.read_text(encoding="utf-8", errors="replace")
        content = f"{render_frontmatter(_default_meta_for_path(Path(rel)))}\n{raw.rstrip()}\n"
        _atomic_write(target, content)
        report.normalized_files.append(rel)

    for rel in report.missing_files:
        target = target_root / rel
        content = _default_required_file(rel)
        _atomic_write(target, content)
        report.normalized_files.append(rel)


def _copy_markdown_tree(source_root: Path, target_root: Path) -> None:
    for source in sorted(source_root.rglob("*.md")):
        relative = source.relative_to(source_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _default_meta_for_path(path: Path) -> PageMeta:
    return PageMeta(
        title=path.stem,
        page_type="note",
        lang="en",
        role="note",
        layer="wiki",
        tags=[],
        summary="",
    )


def _default_required_file(rel: str) -> str:
    title = Path(rel).stem
    role = {"AGENTS.md": "schema", "wiki/INDEX.md": "index", "wiki/LOG.md": "log"}[rel]
    meta = PageMeta(title=title, page_type="meta", lang="en", role=role, layer="wiki", tags=[], summary="")
    return f"{render_frontmatter(meta)}\n# {title}\n"


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
```

The old `_backup_files` and `_restore_backup` helpers are removed because the new flow inlines per-file backup.

Note: `inspect_vault_for_migration` above already uses `parse_document(raw, strict=True)` — Task 5 introduces that `strict` parameter. If Task 4 lands before Task 5, leave `strict` out of this call and restore it in Task 5. Since this plan executes tasks in order, pass `strict=True` here only after Task 5 is merged. To keep this task self-contained, use the current lenient signature:

```python
            frontmatter, _ = parse_document(raw)
        except OSError:
            report.parse_failures.append(rel)
            continue
```

Task 5 will swap the call to `strict=True` and extend the `except` clause.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_migrate.py -q`
Expected: PASS.

- [ ] **Step 5: Verify full suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/migrate.py tests/test_migrate.py CHANGELOG.md
git commit -m "fix: stage migrate writes with rollback ledger and commit boundary helper"
```

---

### Task 5: Phase 3 Migration Preflight Malformed Frontmatter Detection

**Files:**
- Modify: `src/octopus_kb_compound/frontmatter.py`
- Modify: `src/octopus_kb_compound/migrate.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_migrate.py`

**Context:**
`parse_document()` returns `({}, raw)` both when no frontmatter block is present *and* when a block opens with `---\n` but never closes. The migration preflight currently treats the second case as "missing frontmatter" and lets `--apply` proceed. Introduce a `strict` mode that raises on malformed delimiters, and have `inspect_vault_for_migration` use it to populate `parse_failures`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migrate.py`:

```python
def test_inspect_vault_reports_malformed_frontmatter_as_parse_failure(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "broken.md").write_text(
        '---\ntitle: "broken"\nrole: concept\n# no closing fence\nbody here\n',
        encoding="utf-8",
    )
    from octopus_kb_compound.migrate import inspect_vault_for_migration
    report = inspect_vault_for_migration(vault)
    assert "wiki/broken.md" in report.parse_failures
    assert "wiki/broken.md" not in report.pages_missing_frontmatter
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_migrate.py::test_inspect_vault_reports_malformed_frontmatter_as_parse_failure -v`
Expected: FAIL — currently listed as missing frontmatter.

- [ ] **Step 3: Write minimal implementation**

Edit `src/octopus_kb_compound/frontmatter.py`:

```python
class FrontmatterError(ValueError):
    pass


def parse_document(raw: str, *, strict: bool = False) -> tuple[dict, str]:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return {}, raw

    lines = normalized.splitlines()
    fm_lines: list[str] = []
    end = None
    for idx, line in enumerate(lines[1:], start=1):
        if line == "---":
            end = idx
            break
        fm_lines.append(line)

    if end is None:
        if strict:
            raise FrontmatterError("frontmatter opened but never closed")
        return {}, raw

    frontmatter = _parse_frontmatter_lines(fm_lines)
    body = "\n".join(lines[end + 1 :])
    return frontmatter, body
```

Edit `src/octopus_kb_compound/migrate.py` to use strict parsing in preflight:

```python
from octopus_kb_compound.frontmatter import FrontmatterError, parse_document, render_frontmatter

# inside inspect_vault_for_migration:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            frontmatter, _ = parse_document(raw, strict=True)
        except (OSError, FrontmatterError):
            report.parse_failures.append(rel)
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_migrate.py tests/test_frontmatter.py -q`
Expected: PASS.

- [ ] **Step 5: Verify full suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/frontmatter.py src/octopus_kb_compound/migrate.py tests/test_migrate.py CHANGELOG.md
git commit -m "fix: report malformed frontmatter as migration parse failure"
```

---

### Task 6: Phase 4 CLI Exit Code Contract Fixes and Validation Helpers

**Files:**
- Modify: `src/octopus_kb_compound/cli.py`
- Modify: `src/octopus_kb_compound/ingest.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_cli.py`

**Context:**
Plan's exit code contract: `0` success, `2` invalid user input, `1` unexpected runtime error. Three drift points plus one long-standing DRY violation:

1. `export-graph --out` pointing at an existing *file* returns `1`. Should be `2`.
2. `impacted-pages` and `plan-maintenance` accept a directory as `args.page`, then crash. Should return `2` on non-file.
3. `ingest-file` maps every `RuntimeError` to exit 2. `convert_file_to_markdown()` raises `RuntimeError` when optional dep `markitdown` is missing — that is a runtime error, not user input. Introduce a distinct `OptionalDependencyMissing` exception class in `ingest.py` and map it to exit 1 in the CLI.
4. Every subcommand repeats the same `exists / is_dir / is_file` blocks. Factor two helpers — `_validate_vault_dir(vault)` and `_validate_page_file(page)` — while changing the branches, so the new `is_file` and `is_dir` rules apply uniformly.

Do the helper extraction in the same task because the behavior fixes already touch every branch; splitting it forces a second sweep through the same lines.

Out of scope: filesystem vault sandbox (`is_relative_to(vault)`). Plan's Task 5 did not require this. Record the decision in `docs/roadmap.md` during Task 7.

- [ ] **Step 1: Introduce `OptionalDependencyMissing` as a prep step**

In `src/octopus_kb_compound/ingest.py`, add the exception class near the top of the module:

```python
class OptionalDependencyMissing(RuntimeError):
    pass
```

Replace the `markitdown` import guard in `convert_file_to_markdown()`:

```python
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise OptionalDependencyMissing(
            "markitdown is required for file conversion. "
            "Install with: pip install octopus-kb-compound[ingest]"
        ) from exc
```

Run `PYTHONPATH=src python -m pytest tests/test_ingest.py -q`. Expected: PASS because `OptionalDependencyMissing` is a `RuntimeError` subclass, so existing exception checks remain valid.

- [ ] **Step 2: Write the failing CLI tests**

Add to `tests/test_cli.py`:

```python
def test_cli_export_graph_returns_2_when_out_collides_with_file(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    out_file = tmp_path / "out.json"
    out_file.write_text("{}", encoding="utf-8")

    from octopus_kb_compound.cli import main
    rc = main(["export-graph", str(vault), "--out", str(out_file)])
    assert rc == 2


def test_cli_impacted_pages_returns_2_when_page_is_directory(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)

    from octopus_kb_compound.cli import main
    rc = main(["impacted-pages", str(vault / "wiki"), "--vault", str(vault)])
    assert rc == 2


def test_cli_plan_maintenance_returns_2_when_page_is_directory(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)

    from octopus_kb_compound.cli import main
    rc = main(["plan-maintenance", str(vault / "wiki"), "--vault", str(vault)])
    assert rc == 2


def test_cli_ingest_file_returns_1_when_markitdown_missing(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "doc.txt"
    source.write_text("hello", encoding="utf-8")

    import octopus_kb_compound.ingest as ingest_module

    def raise_missing(_path):
        raise ingest_module.OptionalDependencyMissing("markitdown is required")

    monkeypatch.setattr(ingest_module, "convert_file_to_markdown", raise_missing)

    from octopus_kb_compound.cli import main
    rc = main(["ingest-file", str(source), "--vault", str(vault)])
    assert rc == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_cli.py -v`
Expected: 4 FAILs with wrong exit codes.

- [ ] **Step 4: Rewrite `cli.py` with helpers and the new rules**

Replace the body of `src/octopus_kb_compound/cli.py` validation blocks. Add at module level:

```python
from octopus_kb_compound.ingest import OptionalDependencyMissing


def _validate_vault_dir(vault: Path) -> int | None:
    if not vault.exists():
        print(f"Vault does not exist: {vault}", file=sys.stderr)
        return 2
    if not vault.is_dir():
        print(f"Vault is not a directory: {vault}", file=sys.stderr)
        return 2
    return None


def _validate_page_file(page: Path) -> int | None:
    if not page.exists():
        print(f"Page does not exist: {page}", file=sys.stderr)
        return 2
    if not page.is_file():
        print(f"Page is not a file: {page}", file=sys.stderr)
        return 2
    return None
```

Refactor each subcommand branch. For example:

```python
    if args.command == "lint":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        profile = load_vault_profile(args.vault)
        pages = scan_markdown_files(args.vault, profile)
        findings = lint_pages(pages)
        for finding in findings:
            print(f"{finding.code}\t{finding.path}\t{finding.message}")
        return 1 if findings else 0

    if args.command == "suggest-links":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.page)
        if rc is not None:
            return rc
        ...

    if args.command == "ingest-file":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.path)
        if rc is not None:
            return rc
        try:
            body, metadata = ingest.convert_file_to_markdown(str(args.path))
            output_path = ingest.generate_raw_page(
                body,
                metadata,
                args.vault / "raw",
                lang=args.lang,
                tags=_parse_tags(args.tags),
            )
        except OptionalDependencyMissing as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(output_path)
        return 0

    if args.command == "impacted-pages":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.page)
        if rc is not None:
            return rc
        for path in find_impacted_pages(args.page, args.vault):
            print(path)
        return 0

    if args.command == "plan-maintenance":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        rc = _validate_page_file(args.page)
        if rc is not None:
            return rc
        print(render_plan(plan_maintenance(args.page, args.vault)))
        return 0

    if args.command == "export-graph":
        rc = _validate_vault_dir(args.vault)
        if rc is not None:
            return rc
        if args.out.exists() and not args.out.is_dir():
            print(f"Out path is not a directory: {args.out}", file=sys.stderr)
            return 2
        try:
            export_graph_artifacts(args.vault, args.out)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(args.out)
        return 0
```

Apply `_validate_vault_dir` to `vault-summary`, `inspect-vault`, `normalize-vault`, `ingest-url` as well. Leave their success paths unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_cli.py -q`
Expected: PASS.

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/octopus_kb_compound/cli.py src/octopus_kb_compound/ingest.py tests/test_cli.py CHANGELOG.md
git commit -m "fix: align CLI exit codes with plan contract and centralize validation"
```

---

### Task 7: Phase 5 Roadmap Follow-ups and 0.2.1 Release

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

**Context:**
Refactor-only task, no new RED test. All behavior changes are already locked in by Tasks 1–6 and their tests. This task bumps the package version to `0.2.1`, records the remediation batch in the roadmap, and documents the two deferred review findings so they are not lost:

- **Deferred:** vault sandbox (`Path.resolve().is_relative_to(vault.resolve())`) for `impacted-pages` / `plan-maintenance`. Not contracted in original plan. Decision needed on whether the tool assumes vault-local paths.
- **Deferred:** SSRF DNS resolution. Current `ingest.py` rejects literal private IPs but not hostnames that resolve to them. Decision needed on whether to add DNS to the ingest hot path.

- [ ] **Step 1: Update version**

In `pyproject.toml`, bump:

```
version = "0.2.1"
```

- [ ] **Step 2: Update docs/roadmap.md**

Add to `docs/roadmap.md` under a new `## 0.2.1 Remediation (2026-04-17)` heading:

```markdown
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
```

- [ ] **Step 3: Update CHANGELOG.md**

Move the `Unreleased` entries accumulated in Tasks 1–6 into a new `## [0.2.1] - 2026-04-17` section.

- [ ] **Step 4: Smoke-test the release**

Run:

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli --help
PYTHONPATH=src python -m octopus_kb_compound.cli lint examples/minimal-vault
PYTHONPATH=src python -m octopus_kb_compound.cli vault-summary examples/minimal-vault
PYTHONPATH=src python -m octopus_kb_compound.cli export-graph examples/minimal-vault --out /tmp/octopus-export-0.2.1
```

Expected: all tests pass, CLI help lists 10 commands, and the three example commands exit `0`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docs/roadmap.md CHANGELOG.md
git commit -m "chore: cut 0.2.1 with review remediation batch"
```

---

## Execution Notes

- Every new test must be deterministic: no network calls, no wall-clock assertions, no reliance on filesystem ordering beyond `sorted()` iteration.
- Task 4 and Task 5 both edit `migrate.py`. Task 4 goes first and leaves `parse_document(raw)` lenient; Task 5 swaps it to `strict=True` and extends the except clause.
- Do not add the deferred items (vault sandbox, SSRF DNS) to this plan. They require product-level policy decisions and are tracked in `docs/roadmap.md`.

## Final Verification Command

Run after the plan completes:

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m octopus_kb_compound.cli --help
```

Expected: all tests pass, help output lists the same 10 subcommands.
