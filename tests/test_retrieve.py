from pathlib import Path

from octopus_kb_compound.retrieve import build_retrieval_bundle


def test_build_retrieval_bundle_prefers_concepts_then_raw():
    repo_root = Path(__file__).resolve().parents[1]

    bundle = build_retrieval_bundle(repo_root / "examples" / "minimal-vault", "RAG")

    assert bundle.schema == "AGENTS.md"
    assert bundle.index == "wiki/INDEX.md"
    assert bundle.concepts == ["wiki/concepts/RAG and Knowledge Augmentation.md"]
    assert bundle.entities == ["wiki/entities/Chunking.md", "wiki/entities/Vector Store.md"]
    assert bundle.raw_sources == ["raw/example-source.md"]
    assert bundle.ordered_pages[:2] == ["AGENTS.md", "wiki/INDEX.md"]
