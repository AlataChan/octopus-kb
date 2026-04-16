import json
from pathlib import Path

from octopus_kb_compound.export import export_graph_artifacts


def test_export_graph_artifacts_emits_nodes_and_edges(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "export"

    export_graph_artifacts(repo_root / "examples" / "minimal-vault", out_dir)

    nodes = json.loads((out_dir / "nodes.json").read_text(encoding="utf-8"))
    edges = json.loads((out_dir / "edges.json").read_text(encoding="utf-8"))

    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "aliases.json").exists()
    assert any(node["id"] == "page:wiki/concepts/RAG and Knowledge Augmentation.md" for node in nodes)
    assert all({"id", "title", "type", "role", "layer", "aliases"} <= set(node) for node in nodes)
    assert any(edge["relation_type"] == "wikilink" for edge in edges)
    assert all({"source", "target", "relation_type"} <= set(edge) for edge in edges)
