import hashlib
import io
import json
import sys


def _seed_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir()
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    return vault


def test_cli_propose_writes_proposal_file_when_llm_returns_valid_json(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path)
    raw = vault / "raw" / "demo.md"
    raw.write_text(
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nBody text.\n',
        encoding="utf-8",
    )

    fake_proposal = {
        "id": "2026-04-18T10-00-00-xyz",
        "created_at": "2026-04-18T10:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/WRONG.md", "sha256": "0" * 64},
        "produced_by": {
            "provider_profile": "MODEL_LIES",
            "model": "MODEL_LIES",
            "prompt_version": "MODEL_LIES",
        },
        "operations": [
            {
                "op": "append_log",
                "path": "wiki/LOG.md",
                "entry": "2026-04-18: added demo",
                "rationale": "r",
                "confidence": 1.0,
            }
        ],
        "status": "pending",
    }

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {
            "choices": [{"message": {"content": json.dumps(fake_proposal)}}],
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
    assert out["operations"] == 1
    written = vault / ".octopus-kb" / "proposals" / (fake_proposal["id"] + ".json")
    assert written.exists()
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["source"]["path"] == "raw/demo.md"
    assert saved["produced_by"]["provider_profile"] == "default"


def test_cli_propose_overrides_llm_provenance_with_local_sha(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path)
    raw = vault / "raw" / "demo.md"
    raw_body = (
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nBody text.\n'
    )
    raw.write_text(raw_body, encoding="utf-8")
    expected_sha = hashlib.sha256(raw.read_bytes()).hexdigest()

    model_supplied_lies = {
        "id": "test-provenance",
        "created_at": "2026-04-18T10:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/WRONG.md", "sha256": "0" * 64},
        "produced_by": {
            "provider_profile": "MODEL_LIES",
            "model": "MODEL_LIES",
            "prompt_version": "MODEL_LIES",
        },
        "operations": [
            {
                "op": "append_log",
                "path": "wiki/LOG.md",
                "entry": "2026-04-18: x",
                "rationale": "r",
                "confidence": 1.0,
            }
        ],
        "status": "pending",
    }

    import octopus_kb_compound.llm as llm_mod

    def fake_transport(method, url, headers, json_body, timeout):
        return 200, {
            "choices": [{"message": {"content": json.dumps(model_supplied_lies)}}],
            "model": "qwen2.5:7b-instruct",
            "usage": {},
        }

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main

    rc = main(["propose", str(raw), "--vault", str(vault), "--json"])
    assert rc == 0

    saved_path = vault / ".octopus-kb" / "proposals" / "test-provenance.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))

    assert saved["source"]["sha256"] == expected_sha
    assert saved["source"]["path"] == "raw/demo.md"
    assert saved["produced_by"]["provider_profile"] != "MODEL_LIES"
    assert saved["produced_by"]["provider_profile"] == "default"
    assert saved["produced_by"]["prompt_version"].startswith("prompts/propose.md@sha256:")


def test_cli_propose_exits_1_on_persistent_non_json_output(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path)
    raw = vault / "raw" / "demo.md"
    raw.write_text(
        '---\ntitle: "demo"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\nBody.\n',
        encoding="utf-8",
    )

    import octopus_kb_compound.llm as llm_mod

    calls = {"n": 0}

    def fake_transport(method, url, headers, json_body, timeout):
        calls["n"] += 1
        return 200, {
            "choices": [{"message": {"content": "not json"}}],
            "model": "qwen2.5:7b-instruct",
            "usage": {},
        }

    monkeypatch.setattr(llm_mod, "_default_transport", lambda: fake_transport)

    from octopus_kb_compound.cli import main

    rc = main(["propose", str(raw), "--vault", str(vault)])
    assert rc == 1
    assert calls["n"] == 2
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*.json"))
    assert len(rejections) == 1
    rejection = json.loads(rejections[0].read_text(encoding="utf-8"))
    assert rejection["reason"] == "llm_non_json"
    assert rejection["attempts"] == 2
