import hashlib
import io
import json
import sys


def test_full_loop_propose_validate_apply_creates_page_and_is_idempotent(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "raw").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    raw = vault / "raw" / "demo.md"
    raw_body = (
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nA document about Late Chunking.\n'
    )
    raw.write_text(raw_body, encoding="utf-8")

    proposal_payload = {
        "id": "loop-001",
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "WRONG", "sha256": "WRONG"},
        "produced_by": {
            "provider_profile": "WRONG",
            "model": "WRONG",
            "prompt_version": "WRONG",
        },
        "operations": [
            {
                "op": "create_page",
                "path": "wiki/concepts/Late Chunking.md",
                "frontmatter": {
                    "title": "Late Chunking",
                    "type": "concept",
                    "lang": "en",
                    "role": "concept",
                    "layer": "wiki",
                    "source_of_truth": "canonical",
                    "tags": [],
                    "summary": "Token-level late chunking.",
                },
                "body": "# Late Chunking\n\nBody.\n",
                "rationale": "r",
                "source_span": {"path": "raw/demo.md", "start_line": 1, "end_line": 3},
                "confidence": 0.9,
            },
            {
                "op": "append_log",
                "path": "wiki/LOG.md",
                "entry": "2026-04-18: added Late Chunking from raw/demo.md",
                "rationale": "r",
                "confidence": 1.0,
            },
        ],
        "status": "pending",
    }

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {
            "choices": [{"message": {"content": json.dumps(proposal_payload)}}],
            "model": "qwen2.5:7b-instruct",
            "usage": {},
        }

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["propose", str(raw), "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original
    assert rc == 0
    out = json.loads(buf.getvalue())
    proposal_path = vault / ".octopus-kb" / "proposals" / f"{out['proposal_id']}.json"
    assert proposal_path.exists()

    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    expected_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    assert saved["source"]["sha256"] == expected_sha
    assert saved["source"]["path"] == "raw/demo.md"

    rc = main(["validate", str(proposal_path), "--vault", str(vault), "--apply"])
    assert rc == 0
    created = vault / "wiki" / "concepts" / "Late Chunking.md"
    assert created.exists()
    assert "Late Chunking" in (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    audit_dir = vault / ".octopus-kb" / "audit"
    audit_before = list(audit_dir.glob("*.json"))
    assert len(audit_before) == 1

    staging = vault / ".octopus-kb" / "staging"
    assert not staging.exists() or not any(staging.iterdir())

    log_after_first = (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    rc = main(["validate", str(proposal_path), "--vault", str(vault), "--apply", "--json"])
    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == log_after_first
    audit_after = list(audit_dir.glob("*.json"))
    assert len(audit_after) == 1
