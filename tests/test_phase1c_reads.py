"""Active revisions are visible through the read tools, with pinned provenance."""

from __future__ import annotations

import io
import json
import sys

import pytest

from octopus_kb_compound import active
from octopus_kb_compound.adapters.obsidian.store import ObsidianStore
from octopus_kb_compound.cli import main
from octopus_kb_compound.approvals import parse_private_key, public_key_b64
from octopus_kb_compound.envelope import ingest_envelope
from octopus_kb_compound.export import export_graph_artifacts
from octopus_kb_compound.lookup import lookup_term
from octopus_kb_compound.neighbors import compute_neighbors
from octopus_kb_compound.retrieve import build_retrieval_bundle

from tests.test_phase1c_envelope import FIXTURE, NOW, TENANT, VAULT_ID, _bundle, _publish

LABEL = "internal"


@pytest.fixture
def world(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    private = parse_private_key(FIXTURE["private_key_pem"])
    monkeypatch.setenv("OCTOPUS_KB_TENANT", TENANT)
    monkeypatch.setenv(
        "OCTOPUS_KB_VAULTS",
        json.dumps({VAULT_ID: {"root": str(vault), "allowed_access_labels": [LABEL, "restricted"]}}),
    )
    monkeypatch.setenv(
        "OCTOPUS_KB_APPROVAL_KEYS",
        json.dumps({FIXTURE["key_id"]: public_key_b64(private)}),
    )
    return vault, private


def test_read_tools_follow_the_active_revision(world, tmp_path):
    vault, private = world
    first = _publish(
        vault,
        private,
        "first",
        placement="manuals/live.docx",
        body="alpha unique [[Missing Target]]",
    )
    _assert_visible(vault, first, "alpha unique", tmp_path / "out-1")

    second = _publish(
        vault,
        private,
        "second",
        placement="manuals/live.docx",
        body="beta unique [[Missing Target]]",
        parent=first["revision_id"],
        logical_id=first["logical_document_id"],
    )
    _assert_visible(vault, second, "beta unique", tmp_path / "out-2")
    pages = ObsidianStore(vault).list_page_records()
    assert all("alpha unique" not in page.body for page in pages)
    assert all(first["revision_id"] not in page.path for page in pages)


def test_staged_revision_and_copied_frontmatter_are_not_authority(world):
    vault, private = world
    built = _bundle(vault, private, ["hidden body [[Missing Target]]"], placement="manuals/staged.docx")
    assert ingest_envelope(VAULT_ID, built["manifest"], built["parts"], None, now=NOW)["status"] == "staged_awaiting_approval"
    assert all("hidden body" not in page.body for page in ObsidianStore(vault).list_page_records())

    wiki = vault / "wiki"
    wiki.mkdir()
    (wiki / "forged.md").write_text(
        "\n".join([
            "---",
            'title: "Forged"',
            "type: note",
            "lang: en",
            "role: note",
            "layer: wiki",
            "ledger_status: consistent_unverified",
            f'revision_id: "{"ab" * 32}"',
            f'logical_document_id: "{"cd" * 32}"',
            "access_label: restricted",
            "---",
            "",
            "Forged body",
            "",
        ]),
        encoding="utf-8",
    )
    store = ObsidianStore(vault)
    forged = next(page for page in store.list_page_records() if page.path == "wiki/forged.md")
    assert forged.frontmatter["ledger_status"] == "consistent_unverified"
    assert store.provenance_for(forged.path) == {
        "ledger_status": "unledgered",
        "revision_id": None,
        "logical_document_id": None,
        "access_label": None,
    }


def test_one_read_does_not_mix_old_bytes_with_new_provenance(world):
    vault, private = world
    first = _publish(vault, private, "pinned", placement="manuals/pin.docx", body="pinned alpha")
    nxt = _bundle(
        vault,
        private,
        ["pinned beta"],
        placement="manuals/pin.docx",
        parent=first["revision_id"],
        logical_id=first["logical_document_id"],
    )

    def replace(root, pointers):
        assert pointers[first["logical_document_id"]] == first["revision_id"]
        ingest_envelope(VAULT_ID, nxt["manifest"], nxt["parts"], nxt["approval"], now=NOW)

    active.AFTER_PIN = replace
    try:
        store = ObsidianStore(vault)
        pages = [page for page in store.list_page_records() if "revisions" in page.path]
    finally:
        active.AFTER_PIN = None
    assert len(pages) == 1
    assert first["revision_id"] in pages[0].path
    assert "pinned alpha" in pages[0].body
    assert store.provenance_for(pages[0].path)["revision_id"] == first["revision_id"]
    later = ObsidianStore(vault)
    assert any("pinned beta" in page.body for page in later.list_page_records())


def _assert_visible(vault, published, marker: str, out):
    store = ObsidianStore(vault)
    pages = [page for page in store.list_page_records() if published["revision_id"] in page.path]
    assert len(pages) == 1
    assert marker in pages[0].body
    assert "octopus-asset://" in pages[0].body
    provenance = store.provenance_for(pages[0].path)
    assert provenance["revision_id"] == published["revision_id"]
    assert provenance["logical_document_id"] == published["logical_document_id"]
    assert provenance["ledger_status"] == "consistent_unverified"
    assert provenance["access_label"] == "internal"

    found = lookup_term(pages[0].title, vault)
    assert found.canonical["path"] == pages[0].path
    assert found.canonical["provenance"]["revision_id"] == published["revision_id"]
    neighbors = compute_neighbors(pages[0].path, vault)
    assert neighbors.provenance["revision_id"] == published["revision_id"]
    bundle = build_retrieval_bundle(vault, marker)
    raw = bundle.to_dict()["bundle"]["raw_sources"]
    assert any(item["path"] == pages[0].path for item in raw)
    assert any(item["provenance"]["revision_id"] == published["revision_id"] for item in raw)

    export_graph_artifacts(vault, out)
    nodes = json.loads((out / "nodes.json").read_text(encoding="utf-8"))
    assert any(pages[0].path in node["id"] for node in nodes)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["provenance"][pages[0].path]["revision_id"] == published["revision_id"]
    bindings = json.loads(
        (vault / ".octopus-kb" / "revisions" / published["revision_id"] / "bindings.json").read_text(encoding="utf-8")
    )
    assert bindings["parts"][0]["relations"]["owners"]
    assert bindings["parts"][0]["assets"][0]["ref"].startswith("octopus-asset://")
    names = {path.name for path in (vault / ".octopus-kb" / "revisions" / published["revision_id"]).iterdir()}
    assert "ab" * 32 not in names

    stderr = io.StringIO()
    stdout = io.StringIO()
    previous_out, previous_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        main(["lint", str(vault), "--json"])
    finally:
        sys.stdout, sys.stderr = previous_out, previous_err
    payload = json.loads(stdout.getvalue())
    matches = [row for row in payload["findings"] if row["path"] == pages[0].path]
    assert matches
    assert matches[0]["provenance"]["revision_id"] == published["revision_id"]
