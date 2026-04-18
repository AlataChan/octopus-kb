import json

import pytest


def _valid_proposal():
    return {
        "id": "2026-04-18T10-05-33-abc",
        "created_at": "2026-04-18T10:05:33+00:00",
        "source": {"kind": "raw_file", "path": "raw/new.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "local", "model": "m", "prompt_version": "p@abc"},
        "operations": [
            {
                "op": "append_log",
                "path": "wiki/LOG.md",
                "entry": "2026-04-18: x",
                "rationale": "r",
                "confidence": 1.0,
            },
        ],
        "status": "pending",
    }


def test_proposal_schema_accepts_valid_minimal_proposal():
    from octopus_kb_compound.proposals import validate_proposal_dict

    errors = validate_proposal_dict(_valid_proposal())
    assert errors == []


def test_proposal_schema_rejects_unknown_op():
    from octopus_kb_compound.proposals import validate_proposal_dict

    bad = _valid_proposal()
    bad["operations"][0]["op"] = "delete_page"
    errors = validate_proposal_dict(bad)
    assert errors, "schema must reject unsupported op values"


def test_proposal_schema_rejects_confidence_out_of_range():
    from octopus_kb_compound.proposals import validate_proposal_dict

    bad = _valid_proposal()
    bad["operations"][0]["confidence"] = 1.5
    errors = validate_proposal_dict(bad)
    assert errors


def test_proposal_schema_rejects_create_page_without_frontmatter():
    from octopus_kb_compound.proposals import validate_proposal_dict

    bad = _valid_proposal()
    bad["operations"] = [
        {
            "op": "create_page",
            "path": "wiki/concepts/Late Chunking.md",
            "body": "# Late Chunking\n",
            "rationale": "r",
            "confidence": 0.9,
            "source_span": {"path": "raw/new.md", "start_line": 1, "end_line": 2},
        }
    ]
    errors = validate_proposal_dict(bad)
    assert errors


def test_proposal_schema_rejects_add_alias_without_alias():
    from octopus_kb_compound.proposals import validate_proposal_dict

    bad = _valid_proposal()
    bad["operations"] = [
        {
            "op": "add_alias",
            "target_page": "wiki/concepts/Late Chunking.md",
            "rationale": "r",
            "confidence": 0.8,
        }
    ]
    errors = validate_proposal_dict(bad)
    assert errors


def test_proposal_save_is_atomic_and_returns_path(tmp_path):
    from octopus_kb_compound.proposals import save_proposal

    path = save_proposal(_valid_proposal(), vault_root=tmp_path)
    assert path.parent == tmp_path / ".octopus-kb" / "proposals"
    assert path.name.endswith(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "2026-04-18T10-05-33-abc"


def test_proposal_load_returns_same_bytes(tmp_path):
    from octopus_kb_compound.proposals import load_proposal, save_proposal

    path = save_proposal(_valid_proposal(), vault_root=tmp_path)
    loaded = load_proposal(path)
    assert loaded["id"] == "2026-04-18T10-05-33-abc"


def test_save_proposal_rejects_collision_with_existing_id(tmp_path):
    """Append-only storage: a duplicate id must not silently overwrite."""
    from octopus_kb_compound.proposals import ProposalCollisionError, save_proposal

    save_proposal(_valid_proposal(), vault_root=tmp_path)
    with pytest.raises(ProposalCollisionError):
        save_proposal(_valid_proposal(), vault_root=tmp_path)
