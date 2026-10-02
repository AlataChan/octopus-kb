# Phase 1c Batch D build report

Branch `feature/kb-ingest-envelope`. Base `079ff4a`. Builder stopped after S7.
The parser repo was not modified. Digest and verification rules were
reimplemented here. Nothing imports the parser.

## Commits

| Item | Commit | Tests |
|---|---|---|
| Shared contracts and `cryptography` | `403448a` | `tests/test_phase1c_contracts.py` |
| S0 response goldens, before behavior changes | `200bfd6` | `tests/test_phase1c_s0_goldens.py` |
| S6 tenant-root resolver | `bb1365e` | `tests/test_phase1c_resolver.py` |
| S6 `kb_ingest_envelope`, staging, transition table, fsync | `1a2ba33` | `tests/test_phase1c_approvals.py`, `tests/test_phase1c_envelope.py`, `tests/test_mcp_contract_snapshot.py` |
| S6 active-aware reads and read-time provenance | `98ce708` | `tests/test_phase1c_reads.py` |
| S7 propose policy, replay, budget, deferral | `8342ff7` | `tests/test_phase1c_controls.py` |
| This report | this commit | none |

## Config formats

No values are recorded here.

- `OCTOPUS_KB_TENANT`: the deployment tenant string. Unset means `default`. It is never taken from an envelope.
- `OCTOPUS_KB_VAULTS`: JSON object, `vault_id` to `{root, allowed_access_labels}`. `root` is a filesystem path. `allowed_access_labels` is a non-empty list of strings.
- `OCTOPUS_KB_APPROVAL_KEYS`: JSON object, `key_id` to the base64 Ed25519 public key. The key in `tests/fixtures/phase1c/approvals/` is test-only.
- `OCTOPUS_KB_MODEL_POLICY`: optional JSON `{endpoints, budget}`. Each endpoint is `{base_url, model, accounting}` and may name `text_f4`. `accounting` carries `byte_bounded`, `per_message_overhead`, `per_request_overhead`, `image_cost`, and `max_image_dimension`. `budget` carries `family` (`kb.propose`), `calls`, `input_tokens`, `output_tokens`, `images`, and `gpu_seconds`.

When `OCTOPUS_KB_MODEL_POLICY` is unset, propose allows `http://localhost:11434/v1` with `qwen2.5:7b-instruct`, text F4 in enforce mode, and a wide `kb.propose` budget. That keeps the existing single-model CLI path working.

## Unset `OCTOPUS_KB_VAULTS`

The caller-supplied vault path is the only root. Existing single-vault CLI usage keeps working, including `ingest-file` of a source outside that vault. A raw path, proposal path, or page path that realpath-escapes the given vault is still refused as `outside_root`.

When `OCTOPUS_KB_VAULTS` is set, enforcement is strict. `realpath` must land inside a configured root. `..`, absolute paths, and symlinks are resolved before the check. `kb_ingest_envelope` addresses a vault by `vault_id` and refuses `vault_unconfigured` when the map is unset or the id is absent.

## Transition precedence

Evaluated under a per-(tenant, vault, logical document) lock, after the call's parts have passed the pre-staging checks. The states are mutually exclusive:

1. Invalid input → `rejected:<reason>`. Nothing from that call is staged.
2. This revision is already active → `active`. This holds for an expired or absent approval.
3. Parts still missing → `staged_incomplete`, with `missing_indexes`.
4. The staged aggregate differs from the manifest status → `rejected:status_mismatch`. Staged parts are kept.
5. No valid approval, or a full approval of a partial revision → `staged_awaiting_approval`.
6. The approval is valid and `parent_revision_id` equals the current active revision, or both are null → `activated`.
7. The approval is valid and the parent differs → `revision_conflict`.

Status order, used only as the aggregate: `consistent_unverified` < `completed_partial`. The aggregate is the maximum. Other statuses are rejected.

## Fsync order for `activated`

1. Render the pages and `bindings.json` under `.octopus-kb/revisions/<revision_id>/`. fsync each file, then the revision directory.
2. Append the activation record (revision, `approval_id`, parent, time, ledger status, access label) and fsync it.
3. Write the `active` pointer to a temp file, fsync it, rename it, and fsync the active directory.

The pointer is not durable without the record. A crash after the record and before the rename leaves the record inert. The next attempt reconciles the leftover files and completes the pointer. Readers trust only the record whose `revision_id` matches the current pointer.

## Goldens and snapshot

S0 goldens in `tests/fixtures/phase1c/s0/` were captured before any behavior change. Later reads may add fields. The golden test requires every captured value to stay equal and allows added keys. It passed.

`kb_ingest` return JSON and written page bytes are unchanged on the golden fixture.

The MCP signature snapshot gained exactly `kb_ingest_envelope` (`vault_id`, `manifest`, `parts`, `approval`). The previous seven tools are unchanged.

Copied fixtures match `tests/fixtures/phase1c/DIGESTS.json`.

## Verification

```text
/opt/homebrew/bin/python3.13 -m pytest -q
240 passed in 2.05s

cd mcp && /opt/homebrew/bin/python3.13 -m pytest -q tests
3 passed in 0.24s
```

That run includes the S0 goldens, the digest pins, the six revision cases, both mixed-status orders, the transition precedence, both crash points, the approval vectors, and the control vectors. No live model calls.

## Not done

- S8, S9, and the rest of phase 1c are outside this batch.
- The D10 store-root tenant marker is not implemented. Tenant checks here use `OCTOPUS_KB_TENANT` and the vault map.
- `kb_ingest` and `kb_validate --apply` stay ungated. Pages they write are `unledgered` at read time.
- A replayed propose does not call the transport. If the previous proposal file is still there, saving the same proposal id raises `ProposalCollisionError` after the replay hit. The replay test deletes that file first.
- Asset bytes are not copied. Pages keep `octopus-asset://<asset_id>#sha256=<hash>` references only.
