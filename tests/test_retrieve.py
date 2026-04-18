from pathlib import Path

from octopus_kb_compound.retrieve import build_retrieval_bundle


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


def test_build_retrieval_bundle_prefers_concepts_then_raw():
    repo_root = Path(__file__).resolve().parents[1]

    bundle = build_retrieval_bundle(repo_root / "examples" / "minimal-vault", "RAG")

    assert bundle.schema == "AGENTS.md"
    assert bundle.index == "wiki/INDEX.md"
    assert bundle.concepts == ["wiki/concepts/RAG and Knowledge Augmentation.md"]
    assert bundle.entities == ["wiki/entities/Chunking.md", "wiki/entities/Vector Store.md"]
    assert bundle.raw_sources == ["raw/example-source.md"]
    assert bundle.ordered_pages[:2] == ["AGENTS.md", "wiki/INDEX.md"]


def test_cli_retrieve_bundle_orders_evidence_by_contract(tmp_path):
    import io
    import json
    import sys

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
    import io
    import json
    import sys

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
    import io
    import json
    import sys

    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(["retrieve-bundle", "rag", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original
    full = json.loads(buf.getvalue())
    assert full["bundle"]["raw_sources"], "baseline must contain raw_sources"

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(
            [
                "retrieve-bundle",
                "rag",
                "--vault",
                str(vault),
                "--max-tokens",
                "50",
                "--json",
            ]
        )
    finally:
        sys.stdout = original
    trimmed = json.loads(buf.getvalue())
    assert trimmed["bundle"]["raw_sources"] == []
    assert trimmed["bundle"]["concepts"] == full["bundle"]["concepts"]
    assert trimmed["token_estimate"] < full["token_estimate"]


def test_cli_retrieve_bundle_trims_entities_after_raw_sources(tmp_path):
    import io
    import json
    import sys

    vault = tmp_path / "vault"
    _seed_vault(vault)
    for raw in (vault / "raw").glob("*.md"):
        raw.unlink()

    from octopus_kb_compound.cli import main

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

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(
            [
                "retrieve-bundle",
                "rag",
                "--vault",
                str(vault),
                "--max-tokens",
                "20",
                "--json",
            ]
        )
    finally:
        sys.stdout = original
    trimmed = json.loads(buf.getvalue())
    assert trimmed["bundle"]["entities"] == []
    assert trimmed["bundle"]["concepts"] == full["bundle"]["concepts"]


def test_retrieve_bundle_output_matches_schema(tmp_path):
    import io
    import json
    import sys

    import jsonschema

    vault = tmp_path / "vault"
    _seed_vault(vault)

    schema_path = (
        Path(__file__).resolve().parent.parent
        / "schemas"
        / "cli"
        / "retrieve-bundle.json"
    )
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
