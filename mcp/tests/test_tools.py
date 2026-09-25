from __future__ import annotations

from pathlib import Path

from octopus_kb_mcp.tools import export_graph, ingest, retrieve_bundle


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_VAULT = ROOT / "examples" / "expanded-vault"


def test_export_graph_returns_nodes_and_edges_json():
    graph = export_graph(EXAMPLE_VAULT)

    assert graph["nodes"]
    assert graph["edges"]
    assert set(graph["nodes"][0]) == {"id", "title", "type", "role", "layer", "aliases"}
    assert set(graph["edges"][0]) == {"source", "target", "relation_type"}


def test_retrieve_bundle_returns_resolved_capped_text():
    result = retrieve_bundle(EXAMPLE_VAULT, "RAG Operations", max_tokens=2000, max_text_chars=600)

    assert result["items"]
    first = result["items"][0]
    assert {"path", "title", "reason", "text", "tokenEstimate"}.issubset(first)
    assert first["text"].strip()
    assert len(first["text"]) <= 600
    assert first["tokenEstimate"] >= 1


def test_ingest_writes_raw_page(tmp_path):
    vault = tmp_path / "vault"
    result = ingest(vault, "# Source Title\n\nBody text", title="Source Title", tags=["demo"])

    written = vault / result["path"]
    assert result["path"].startswith("raw/")
    assert written.exists()
    assert "Source Title" in written.read_text(encoding="utf-8")
