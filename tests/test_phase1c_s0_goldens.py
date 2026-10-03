"""S0 response goldens. Later fields may be added; existing values stay put."""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

from octopus_kb_compound.cli import main
from octopus_kb_compound.export import export_graph_artifacts
from octopus_kb_compound.lookup import lookup_term
from octopus_kb_compound.neighbors import compute_neighbors
from octopus_kb_compound.retrieve import build_retrieval_bundle


ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "examples" / "minimal-vault"
FIXTURE = ROOT / "tests" / "fixtures" / "phase1c" / "s0"
PAGE = "wiki/concepts/RAG and Knowledge Augmentation.md"
INGEST_MARKDOWN = "# Golden Source\n\nFixed body.\n"


def test_read_tools_and_ingest_match_s0_goldens(tmp_path):
    golden = json.loads((FIXTURE / "responses.json").read_text(encoding="utf-8"))
    actual = _capture(tmp_path)
    _assert_covers(golden, _scrub(actual, str(VAULT)))


def _capture(tmp_path: Path) -> dict:
    mcp_root = str(ROOT / "mcp")
    if mcp_root not in sys.path:
        sys.path.insert(0, mcp_root)
    from octopus_kb_mcp.tools import export_graph, ingest, lookup, neighbors, retrieve_bundle

    buf = io.StringIO()
    previous = sys.stdout
    sys.stdout = buf
    try:
        lint_rc = main(["lint", str(VAULT), "--json"])
    finally:
        sys.stdout = previous
    export_dir = tmp_path / "export"
    export_graph_artifacts(VAULT, export_dir)
    copy = tmp_path / "vault"
    shutil.copytree(VAULT, copy)
    ingested = ingest(copy, INGEST_MARKDOWN, title="Golden Source", tags=["golden"])
    written = (copy / ingested["path"]).read_bytes()
    assert written == (FIXTURE / "ingest-bytes.bin").read_bytes()
    return {
        "mcp": {
            "export": export_graph(VAULT),
            "retrieve": retrieve_bundle(VAULT, "RAG", max_tokens=1500, max_text_chars=4000),
            "lookup": lookup(VAULT, "RAG"),
            "neighbors": neighbors(VAULT, PAGE),
            "ingest": ingested,
        },
        "cli": {
            "lookup": lookup_term("RAG", VAULT).to_dict(),
            "retrieve": build_retrieval_bundle(VAULT, "RAG", max_tokens=1500).to_dict(),
            "neighbors": compute_neighbors(PAGE, VAULT).to_dict(),
            "lint_rc": lint_rc,
            "lint": json.loads(buf.getvalue()),
            "export": {
                name: json.loads((export_dir / name).read_text(encoding="utf-8"))
                for name in ("nodes.json", "edges.json", "manifest.json", "aliases.json")
            },
        },
    }


def _scrub(value, vault_text: str):
    if isinstance(value, str):
        return value.replace(vault_text, "{vault}")
    if isinstance(value, list):
        return [_scrub(item, vault_text) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, vault_text) for key, item in value.items()}
    return value


def _assert_covers(golden, actual, path: str = "$") -> None:
    if isinstance(golden, dict):
        assert isinstance(actual, dict), path
        for key, value in golden.items():
            assert key in actual, f"{path}.{key} missing"
            _assert_covers(value, actual[key], f"{path}.{key}")
        return
    if isinstance(golden, list):
        assert isinstance(actual, list) and len(actual) == len(golden), path
        for index, (expected, found) in enumerate(zip(golden, actual)):
            _assert_covers(expected, found, f"{path}[{index}]")
        return
    assert actual == golden, path
