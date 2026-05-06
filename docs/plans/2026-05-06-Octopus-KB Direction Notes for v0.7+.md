# Octopus-KB: Direction Notes for v0.7+

> **Audience:** Codex (AI code review), with full read access to the `octopus-kb` repository.
> **Purpose:** capture findings about the current state of `octopus-kb`, the proposed direction, and the open questions worth pushing back on.
> **Context source:** full repository read of the `main` branch as of v0.6.0 (54 commits). Fresh local verification on 2026-05-06 collected 203 tests and all passed; README still advertises 200.
> **Implementation status:** completed in the v0.7 CKR/adapter implementation branch. The final implementation includes CKR models/ops, `KnowledgeStore`, `ObsidianStore`, read-flow adapter migration, layered lint, adapter-driven apply, JSON snapshot round-trip tests, architecture docs, and full-suite verification (`215 passed`).

---

## 0. How to Review This Document

This document is structured to be **directly verifiable against the codebase**. Codex, please use the following as the review contract:

1. **§3 (What's Strong) is fact-checkable.** Every row cites specific files (`apply.py`, `audit.py`, `validators/declarative.py`, etc.). Please open them and confirm that the claimed property actually holds. If any claim is overstated, flag it — that affects whether the corresponding item in §7 ("Lock In") is actually safe to lock in.

2. **§9 (Open Questions) is where reviewer input mattered most.** The rest of the document represents converged thinking; §9 now includes grounded reviewer answers on those seven points.

3. **§4–§5 (the architectural argument) needs structural sanity-checking.** The claim is that "Canonical Knowledge Representation = Obsidian vault format" is the largest coupling blocking multi-endpoint support. The review checked whether the modules listed (`vault.py`, `links.py`, `frontmatter.py`, `lint.py`, `retrieve.py`, `apply.py`, `export.py`) really do read/write Obsidian-shaped data directly, with no abstraction in between.

4. **§8 (the proposed refactor) needs a feasibility check.** The acceptance criterion is "all currently collected tests pass after adaptation, no behavior change visible to a CLI user." Please assess whether that is realistic given the actual coupling depth — and if not, identify specifically which test files or modules will resist a clean lift. A list of the top 3 expected friction points is more valuable than a global thumbs-up or thumbs-down.

5. **§12 records the explicit verdict:** `approve with adjustments`, grounded in §3 / §8 / §9 findings.

Out of scope for this review:
- Performance / scale (no benchmarks claimed).
- Security beyond the existing safety boundaries (declarative rules, write-boundary check, audit-first commit). A dedicated security pass is a separate document.
- Specific endpoint adapter designs (Notion, Logseq, etc.) — those land *after* the refactor.

---

## 1. Executive Summary

`octopus-kb` is currently positioned as "the agent's operating procedure for Obsidian-style knowledge bases." The owner's stated goal is broader: a **universal knowledge management tool / skill** whose endpoint can be Obsidian *or other tools* (Notion, Logseq, plain Markdown, JSON, etc.). The owner has explicitly **deferred Graph RAG** to a future phase and identified **knowledge pre-treatment quality** as the most important near-term investment.

After reading the actual code (not just the README), my recommendation is:

1. **The engineering quality of the current implementation is high enough to weaponize.** The audit-first commit protocol, declarative-only rule DSL, locally-computed provenance, and JSON-Schema-first CLI contracts are all production-grade.
2. **The largest architectural gap blocking the multi-endpoint goal is that the canonical knowledge representation is currently identical to the Obsidian vault format.** Most read/write paths use markdown files, frontmatter, paths, and wikilinks directly. `canonical.py` is useful identity-normalization logic, but it is not yet a storage or content abstraction.
3. **The right next step is a staged internal refactor** that introduces a Canonical Knowledge Representation (CKR) projection and an Obsidian adapter boundary without changing CLI behavior. No new user-facing features, no visible output changes, and the current test suite should still pass after each slice. This unblocks adapter pluggability without finalizing external endpoint decisions.
4. **Pre-treatment quality investments should land in the pipeline + CKR layers, never in adapters.** Concrete suggestions in §6.

This document is meant to be challenged. §9 lists the open questions that most warrant pushback.

---

## 2. Project Positioning (Corrected)

The README frames `octopus-kb` as Obsidian-shaped, which I think undersells it. Looking at the code, it is more accurately a **knowledge pre-treatment pipeline with a single shipping adapter**. The pipeline (ingest → propose → declarative-rule gate → audit-first staged apply → eval harness) is endpoint-agnostic in spirit; the storage layer happens to be Obsidian-shaped because that's where it grew up.

Two reframings I considered and rejected:

- **"Graph RAG platform."** Wrong. The owner has explicitly deferred this. The current `retrieve-bundle` does deterministic ordered lookup across `schema → index → concepts → entities → raw_sources`, including one-hop expansion through `related_entities` and wikilinks. There is no learned graph retrieval, embedding index, multi-hop traversal, or relation extraction, and pushing toward those would conflict with the stated near-term goal.
- **"Wiki-LLM."** Closer, but still too narrow. It implies the wiki structure (Obsidian's wikilink graph) is the product. Under the multi-endpoint goal, the wiki structure is a serialization choice, not the product.

The most accurate one-line framing I have today: **a curation pipeline that turns raw inputs into a canonical, audited knowledge representation, and serializes that representation to a chosen endpoint format.** Obsidian is endpoint #1.

---

## 3. What's Strong in the Current Implementation

These are the parts I think should be locked in (see §7), based on direct code reading:

| Capability | Where it lives | Why it's strong |
|---|---|---|
| Audit-first two-phase commit | `src/octopus_kb_compound/apply.py`, `audit.py` | The `pending` audit entry is written *before* file replacement, with a deterministic timestamped filename. `recover_proposal()` uses the pending entry as the authoritative in-flight marker and is idempotent. Most prototypes leave a "files replaced but no audit" crash window; this one does not. |
| Provenance override | `propose.py` | Source SHA and `prompt_version` are computed locally and unconditionally overwrite whatever the LLM put in `source` / `produced_by`. The model is never trusted with provenance. |
| Declarative-only rule DSL | `validators/declarative.py`, `validators/builtins.yaml`, `schemas/rules/v1.json` | 7 fixed primitives, no `exec()`, no regex execution, unknown primitive → load fails. User-extensible via YAML only. The "schema.proposal_invalid runs first regardless of `applies_to`" detail correctly closes the unsupported-op bypass. |
| JSON Schema as a contract surface | `schemas/cli/*.json`, `schemas/page-meta.json`, `schemas/llm/proposal.json`, `schemas/rules/v1.json`, `schemas/eval/tasks-v1.json`, `schemas/config/v1.json` | CLI/proposal/rules/eval/config schemas are strict (`additionalProperties: false`) where they define machine contracts. `page-meta.json` intentionally remains a validation floor (`additionalProperties: true`) for legacy/custom frontmatter. The dual-copy schema-package-data pattern (with byte-identical drift test) is a thoughtful production detail. |
| Deterministic eval harness | `src/octopus_kb_compound/eval/`, `eval/runs/2026-04-18-baseline/` | Pure-Python grep baseline (no shell-out, bit-identical across platforms). Per-task JSON is committed; latency lives in a separate ignored `*.metrics.json`. The `summary.md` format is explicitly frozen. This is rare. |
| Append-only proposals + inbox tombstoning | `proposals.py`, `inbox.py` | `ProposalCollisionError` on duplicate id; `--accept` / `--reject` both delete the inbox copy after the terminal decision so `inbox --list` cannot resurface a decided proposal. |
| Write-boundary path enforcement | `apply.py:_write_boundary_error` | Defense-in-depth duplicate of `safety.path_escape` and `safety.forbidden_area` rules. Runs unconditionally even if rules are misconfigured. |

The phase plans (`docs/plans/`) are also notable: every behavior change is RED-test-first, every commit boundary is documented, deferred items are explicitly listed in `docs/roadmap.md` rather than dropped on the floor.

---

## 4. The Core Architectural Gap

The fundamental coupling preventing the multi-endpoint goal:

> **Today, the Canonical Knowledge Representation *is* the Obsidian vault format.**

`PageMeta` is defined as a dataclass in `models.py`, but its serialization is exclusively markdown frontmatter (`frontmatter.py`). The graph is wikilinks (`links.py`). Storage is folder hierarchy (`vault.py`). Every downstream module checked here — `lint`, `retrieve`, `propose`, `apply`, `export`, `neighbors`, `lookup`, and `impact` — reads Obsidian-shaped data directly, and `apply` writes it directly.

This means:

- Adding a Notion or Logseq endpoint directly would be closer to a rewrite than a feature.
- The `propose` loop produces operations like `create_page` and `add_alias` whose semantics are tied to "markdown file with frontmatter" — they don't translate cleanly to a Notion page with structured properties.
- The validator chain checks paths like `wiki/concepts/Foo.md` and forbidden areas like `.git/` and `.octopus-kb/`. Half of those checks are Obsidian-vault-specific assumptions about filesystem layout.
- `export-graph` already produces a partial CKR artifact (`nodes.json`, `edges.json`), but it's a one-way escape hatch rather than a layer the rest of the system runs on.

---

## 5. Proposed Three-Layer Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Curation pipeline (endpoint-agnostic)                         │
│  propose · validate · apply · retrieve-bundle · lint · ...     │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  Canonical Knowledge Representation (CKR)                      │
│  CanonicalPage · CanonicalEntity · CanonicalOp                 │
│  pure domain data, plus explicit endpoint/storage annotations  │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  Adapters                                                      │
│  ObsidianAdapter (today) · future endpoint adapters            │
│  serialize CKR → endpoint, parse endpoint → CKR                │
└────────────────────────────────────────────────────────────────┘
```

CKR is what `PageMeta` and the proposal `op` types *should* become once they are freed from frontmatter serialization as their only representation. Important adjustment: CKR v1 should not pretend that markdown, paths, and wikilinks disappear. Existing behavior depends on markdown body fidelity, path-shaped CLI/audit outputs, alias ordering, and original wikilink text. CKR v1 should model those explicitly instead:

- `CanonicalPage` carries endpoint-neutral fields (`id`, `title`, `kind`, `language`, `summary`, `aliases`, `related_refs`, `body`) and a declared `body_format` such as `markdown`.
- `CanonicalRef` is the domain identity. Adapter-specific storage identity (`wiki/concepts/Foo.md`, Notion block id, etc.) lives in a separate `StorageRef` / `EndpointRef`.
- Wikilinks are parsed into canonical references where possible, while the original body text remains available for lossless Obsidian round-trips.

The interfaces the layer above and below CKR speak to it through:

- `KnowledgeStore` protocol on the adapter side: list/read pages, resolve aliases, map `StorageRef` ↔ `CanonicalRef`, and apply the current safe op set with a `WriteReceipt` that preserves CLI/audit paths.
- The pipeline above operates on `CanonicalPage` and `CanonicalOp`, but the v0.7 refactor should keep compatibility shims for current CLI contracts. `apply.py` becomes adapter-driven only after the audit ledger, staging directory, and write-boundary checks have tests proving the path-backed behavior is unchanged.

The Obsidian adapter encapsulates everything that today lives in `vault.py`, `links.py`, `frontmatter.py`, plus the path-aware bits of `apply.py` and `export.py`.

---

## 6. Pre-Treatment Quality Investments

These are the things I think are genuinely valuable to add **without** crossing into Graph RAG territory. All four live in the pipeline + CKR, never in adapters.

### 6.1 Per-claim provenance, not per-page

Today, provenance is proposal/audit-level: `propose.py` overwrites `source.sha256` and `produced_by.prompt_version`, and audit entries copy that source metadata for drift detection. Proposal ops already carry `source_span` / `confidence` in some cases, but applied pages do not retain per-claim evidence. The next step is per-claim: each statement (paragraph, list item, table row) inside a CKR page can carry its own `source_span` and `confidence`. This should wait until CKR has a real body/block model; otherwise it will become ad hoc metadata bolted onto markdown strings.

### 6.2 Cross-source entity normalization (not relation extraction)

Current alias resolution works at the page level via `links.build_alias_index()`. The next step is cross-source: when raw sources A and B both mention "RAG Operations" with different surface forms, the propose pipeline reconciles them into one CKR entity before the apply step. This is dedup, not graph extraction. The infrastructure (alias normalization, canonical key resolution in `canonical.py`) already exists; it just needs to be lifted from page → entity scope.

### 6.3 Versioned CKR with explicit migration paths

`PageMeta` is schema-managed via `schemas/page-meta.json`, but records do not carry an explicit in-document version. CKR should be more explicit: include `ckr_version` in serialized CKR snapshots, keep migration helpers beside the model, and make adapters declare which CKR versions they support. This is the difference between a single-endpoint tool that ships and a multi-endpoint platform that survives.

### 6.4 Reverse adapters as a correctness test

The cheapest v0.7 correctness test is a JSON snapshot codec for CKR: `Obsidian → CKR → JSON → CKR → Obsidian` should round-trip without losing frontmatter fields, alias order, markdown body text, or wikilink text on fixture pages. This proves CKR serialization fidelity, not endpoint independence.

The stronger endpoint-agnostic test comes later: write a reverse adapter that reads an existing Logseq or Notion export and emits CKR. If that adapter forces CKR to grow fields that Obsidian never needed, the abstraction is doing useful work.

---

## 7. Lock In vs Keep Open

| Lock in (weaponize) | Keep open (don't finalize) |
|---|---|
| Audit / recovery contract — already correct | Graph model — no typed edges, no edge weights, no relation extraction |
| 7 declarative rule primitives + YAML-only stance | Embedding / vector storage — adapters that need vectors compute them at write time |
| Current v1 proposal op vocabulary (`create_page`, `add_alias`, `append_log`) during the refactor; destructive ops stay deferred | CKR field set — v1 preserves Obsidian behavior, expect Notion/Logseq to expand it |
| JSON Schema on every CLI output, `additionalProperties: false` as contract | Cross-document linking semantics — wikilinks are an Obsidian feature, CKR cannot assume them |
| Provenance override (local SHA wins; LLM source fields ignored) | Retrieval strategy — current deterministic ordered lookup with one-hop relation expansion is sufficient; do not chase RAG trends |
| Eval harness reproducibility (bit-identical reruns) | Endpoint-specific sync / conflict-resolution protocols — let adapters own these |

---

## 8. Recommended Next Step: The CKR + Adapters Refactor

Not a new feature. A pure refactor, but it should be executed as a compatibility-preserving extraction rather than a wholesale module move.

### Target file structure

```
src/octopus_kb_compound/
├── ckr/                       # NEW
│   ├── __init__.py
│   ├── models.py              # CanonicalPage, CanonicalRef, StorageRef, SourceSpan
│   ├── operations.py          # CanonicalOp = create_page | add_alias | append_log
│   └── json_codec.py          # CKR snapshot serialization for tests/tools
│
├── adapters/                  # NEW
│   ├── __init__.py
│   ├── base.py                # KnowledgeStore protocol, WriteReceipt, etc.
│   └── obsidian/
│       ├── __init__.py
│       ├── store.py           # ObsidianStore implements KnowledgeStore
│       ├── codec.py           # PageRecord <-> CanonicalPage projection
│       ├── lint_obsidian.py   # Obsidian-specific lint rules (BROKEN_LINK, etc.)
│       └── paths.py           # StorageRef/path safety helpers
│
├── frontmatter.py             # compatibility shim or delegated helper during v0.7
├── links.py                   # compatibility shim or delegated helper during v0.7
├── vault.py                   # compatibility shim or delegated helper during v0.7
├── propose.py                 # unchanged CLI contract; gradually projects ops to CKR
├── apply.py                   # eventually calls store.apply_ops(ops, audit_ctx)
├── audit.py                   # unchanged
├── validators/                # unchanged in interface until CKR op tests exist
├── lint.py                    # may delegate Obsidian-specific rules behind current API
└── retrieve.py                # may delegate store reads behind current API
```

Treat this as the end-state shape, not the first commit. The first commits should add CKR models, projection tests, and adapter wrappers while leaving old import paths valid.

### Acceptance criteria

- All currently collected tests pass after each migration slice (203 in the 2026-05-06 review run). No behavior change visible to a CLI user.
- Existing JSON output schemas, exit codes, `next` command strings, audit ledger paths, and proposal schema remain unchanged.
- `KnowledgeStore` protocol is documented in `docs/architecture.md`, including how path-backed CLI inputs map to `StorageRef` and `CanonicalRef`.
- `ObsidianStore` is the only adapter that ships in this refactor.
- A `ckr/json_codec.py` snapshot serializer is committed for fixtures/tests. Do not present it as a real endpoint adapter.
- A new test `tests/integration/test_ckr_round_trip.py` exercises `Obsidian fixture → CKR → JSON snapshot → CKR → Obsidian render` and asserts no information loss for frontmatter fields, alias order, markdown body text, and wikilink text.

### Recommended sequencing

1. Add `ckr/models.py` and `ckr/operations.py` with tests only. No production callers.
2. Add `adapters/base.py` and `adapters/obsidian/codec.py` to project `PageRecord` ↔ `CanonicalPage`. Keep `frontmatter.py`, `links.py`, and `vault.py` import paths working.
3. Move read-only flows behind the adapter boundary one at a time: `lookup`, `neighbors`, `impact`, then `retrieve`. Keep CLI JSON outputs byte-for-byte compatible.
4. Move lint in two layers: CKR-level identity/schema checks first, Obsidian-specific wikilink/path checks second.
5. Move `apply.py` last. Preserve audit-first ordering, staging layout, `_write_boundary_error`, and recovery behavior before touching internals.
6. Add the CKR JSON snapshot round-trip and update `docs/architecture.md`.

### Expected friction points

- `apply.py` is path- and filesystem-transaction-heavy. The audit ledger records created/modified paths and staging paths, so the adapter boundary must preserve those as `StorageRef`s rather than replacing them with abstract ids too early.
- `lint.py`, `retrieve.py`, `neighbors.py`, and `impact.py` all mix alias resolution, wikilinks, `related_entities`, roles, paths, and title lookup. These should be split by behavior, not by file movement.
- CLI tests and schemas assert path-shaped outputs and command suggestions. CKR ids must not leak into public JSON unless a later version explicitly changes the contract.

### Why this scope is right

This is the smallest change that proves the abstraction without breaking the product surface. It avoids speculative Notion/Logseq work, but it does force the current Obsidian behavior through a protocol seam and a lossless projection test. That is a better signal than designing CKR in isolation and discovering during adapter #2 that the model cannot preserve the current vault.

### Why not bigger

I considered (and rejected) doing CKR + per-claim provenance + cross-source normalization in one phase. Reasons:
- Each is independently valuable and independently testable.
- Bundling them risks designing CKR around features that aren't yet stress-tested in real use.
- The refactor alone is already a non-trivial diff; adding semantic enrichments on top compounds review burden.

§6.1–6.4 are post-refactor work, except the JSON snapshot codec needed to test CKR serialization. v0.7 = staged CKR/Obsidian adapter extraction. v0.8+ = pre-treatment quality and real non-Obsidian adapters.

---

## 9. Open Questions (Worth Pushing Back On)

These are the points where I am least certain. A reviewer's most useful contribution would be on these.

1. **Is the refactor scope right?** Could a smaller initial step — e.g., extracting only `CanonicalPage` while leaving `KnowledgeStore` for later — be enough to unblock multi-endpoint thinking, without committing to the protocol shape too early?
2. **Have I missed Obsidian-specific assumptions that don't translate?** Wikilinks, frontmatter ordering, folder-as-namespace, alias-as-string — I have flagged these, but there are likely more buried in `lint.py` and `retrieve.py`.
3. **Is per-claim provenance (§6.1) premature?** It is useful, but not cheap until CKR has a real body/block model. Counterargument: proposal/audit-level provenance was also "designed for an imagined future" early in the project, and now it is load-bearing for drift detection.
4. **Is the "no Graph RAG" boundary clean enough?** Some endpoints (Notion databases, Logseq blocks) have built-in relational structure. Honoring that in CKR isn't Graph RAG, but the line is fuzzy. Where exactly does it sit?
5. **Are there endpoint candidates I'm not considering?** I have listed Obsidian, Notion, Logseq, plain Markdown, JSON. What about GitHub Issues, Linear docs, Slack canvases, Confluence, Roam, Anytype? Some of these would stress CKR very differently.
6. **Should the propose op vocabulary expand before the refactor?** `update_body`, `delete_page`, `rename_page` are already deferred (per the v0.5.0 plan). After the refactor, they will need CKR-level semantics — which means designing them up front, even if they ship later.
7. **Is the Obsidian adapter the "reference adapter" or just "the first adapter"?** Different framings imply different test obligations. If reference: every other adapter must round-trip with it. If just first: the round-trip property is symmetric across adapter pairs.

### Reviewer answers before v0.7 starts

- Q1: approve the CKR direction, but only with staged extraction and compatibility shims. Do not start by moving `frontmatter.py`, `links.py`, and `vault.py` wholesale.
- Q2: additional Obsidian assumptions to track are path-as-public-identity, path-shaped audit ledgers, frontmatter field/order preservation, markdown body fidelity, original wikilink text, CLI `next` command strings, and raw source paths.
- Q3: per-claim provenance is premature for v0.7. Keep existing proposal/audit provenance and defer claim/block evidence until CKR has a real content model.
- Q4: the Graph RAG boundary is clean enough if CKR only stores explicit references and deterministic one-hop expansion. Do not add learned edges, weights, embeddings, or multi-hop graph ranking in this phase.
- Q5: endpoint candidates should inform CKR naming, not scope. JSON is a snapshot codec; a real second endpoint can wait.
- Q6: do not expand the op vocabulary before the refactor. Reserve CKR operation types so `update_body`, `delete_page`, and `rename_page` can be added later without changing the protocol shape.
- Q7: treat Obsidian as the compatibility/reference fixture for v0.7, not as the normative model every future endpoint must mimic.

---

## 10. Risks

- **Refactor blast radius.** 203 tests pass in the 2026-05-06 review run; the refactor will touch `vault.py`, `links.py`, `frontmatter.py`, `lint.py`, `retrieve.py`, `apply.py`, plus most CLI subparsers. Test breakage is likely temporary but real. Mitigation: do it in staged commits with the full suite running after each slice.
- **CKR purity trap.** A CKR v1 that bans markdown, paths, or wikilink text will force a content-model redesign and break CLI/audit compatibility. Mitigation: model `body_format`, `StorageRef`, and parsed references explicitly, then document v1 limitations.
- **CKR v1 baking in Obsidian assumptions.** Even with care, the first version will have markdown-shaped corners. Mitigation: the round-trip test against the CKR JSON snapshot codec, plus an explicit `# v1 limitations` section in `ckr/models.py`.
- **Endpoint surface explosion.** Each new endpoint has its own auth, sync, conflict resolution, and rate-limit story. Mitigation: do not promise endpoint coverage; ship the protocol and let adapters land one at a time, each with its own scope doc.
- **Pre-treatment investments competing with adapter coverage.** The two work streams pull on the same engineering time. Mitigation: explicit sequencing — refactor first (v0.7), then alternate adapter and pre-treatment quality phases.
- **The "weaponize but don't finalize" stance is fragile under user pressure.** Once a real user lands, they will ask for a feature that requires committing to something the project wanted to keep open. Mitigation: keep `docs/roadmap.md` as the canonical "what's deferred and why" document, and update it every time a deferral is challenged.

---

## 11. What This Document Does Not Cover

- Detailed CKR field-by-field schema. That belongs in a follow-up `docs/ckr-v1.md` after the refactor's design phase.
- `KnowledgeStore` protocol method signatures. Same — sketch is enough for now; the binding form should come from the implementation.
- Specific endpoint adapter design (Notion, Logseq, etc.). Out of scope until the protocol stabilizes.
- Performance / scale targets. The vault sizes I see in `examples/` and `eval/corpora/` are small; performance work belongs to a later phase.
- Security review of the propose / apply path beyond what is already in the codebase. The current safety boundaries (declarative rules, write-boundary check, audit-first) appear sound, but a dedicated security pass is its own document.

---

## 12. Reviewer Verdict

> **Approve with adjustments.**

The v0.7 direction is correct if it means "staged CKR projection + Obsidian adapter extraction, no user-facing behavior change." It is not correct if it means "pure CKR with no markdown, no paths, no wikilinks" or a large first-pass module move.

Required adjustments before implementation starts:

- Define CKR v1 around lossless preservation of current Obsidian behavior: markdown body text, original wikilink text, aliases, frontmatter fields, and path-backed audit/CLI outputs.
- Keep `frontmatter.py`, `links.py`, and `vault.py` as compatibility shims until all callers are migrated and tests prove no behavior drift.
- Treat JSON as a CKR snapshot codec, not a second endpoint adapter.
- Defer per-claim provenance, op vocabulary expansion, and real non-Obsidian adapters until after the CKR/Obsidian boundary is stable.

Whichever path is chosen, the **lock-in vs keep-open table in §7** should be the contract for what does and does not get touched in the next phase.
