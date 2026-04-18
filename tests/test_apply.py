import json
from pathlib import Path


def _seed(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _write_proposal(vault: Path, proposal: dict) -> Path:
    dest = vault / ".octopus-kb" / "proposals"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{proposal['id']}.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    return path


def _append_log_proposal(id_="p1"):
    return {
        "id": id_,
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "produced_by": {"provider_profile": "p", "model": "m", "prompt_version": "p@x"},
        "operations": [
            {
                "op": "append_log",
                "path": "wiki/LOG.md",
                "entry": "2026-04-18: hello",
                "rationale": "r",
                "confidence": 1.0,
            }
        ],
        "status": "pending",
    }


def _pending_audit_entry(proposal_id, modified, created):
    return {
        "proposal_id": proposal_id,
        "status": "pending",
        "created_at": "2026-04-18T00:00:00+00:00",
        "source": {"kind": "raw_file", "path": "raw/x.md", "sha256": "a" * 64},
        "applied_pages": sorted(set(modified) | set(created)),
        "modified": list(modified),
        "created": list(created),
        "staging_path": f".octopus-kb/staging/{proposal_id}",
        "override": None,
        "applied_at": None,
        "vault_sha_after": None,
    }


def test_validate_dry_run_returns_verdict_without_writing(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--json"])

    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == "# Log\n"


def test_validate_apply_appends_log_and_writes_audit(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 0
    assert "2026-04-18: hello" in (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    audit = list((vault / ".octopus-kb" / "audit").glob("*.json"))
    assert len(audit) == 1
    entry = json.loads(audit[0].read_text(encoding="utf-8"))
    assert entry["status"] == "applied"


def test_validate_apply_creates_new_concept_page_with_audit(tmp_path):
    vault = _seed(tmp_path)
    good = _append_log_proposal("p-create")
    good["operations"] = [
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
                "summary": "Token-level late chunking for retrieval.",
            },
            "body": "# Late Chunking\n\nIntroduced in recent work.\n",
            "rationale": "New concept from source.",
            "confidence": 0.9,
            "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 10},
        }
    ]
    proposal = _write_proposal(vault, good)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 0
    created = vault / "wiki" / "concepts" / "Late Chunking.md"
    assert created.exists()
    assert "Late Chunking" in created.read_text(encoding="utf-8")
    audit = list((vault / ".octopus-kb" / "audit").glob("*.json"))
    assert len(audit) == 1

    entry = json.loads(audit[0].read_text(encoding="utf-8"))
    assert entry["status"] == "applied"
    assert entry["proposal_id"] == "p-create"
    assert entry["source"]["sha256"] == "a" * 64
    assert entry["source"]["path"] == "raw/x.md"
    assert "wiki/concepts/Late Chunking.md" in entry["applied_pages"]
    assert entry["applied_at"] is not None
    assert entry["vault_sha_after"] is not None
    assert entry.get("override") is None


def test_validate_apply_adds_alias_to_existing_page(tmp_path):
    vault = _seed(tmp_path)
    (vault / "wiki" / "concepts").mkdir()
    target = vault / "wiki" / "concepts" / "Topic.md"
    target.write_text(
        '---\ntitle: "Topic"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    good = _append_log_proposal("p-alias")
    good["operations"] = [
        {
            "op": "add_alias",
            "target_page": "wiki/concepts/Topic.md",
            "alias": "topic-alias",
            "rationale": "Used in source abstract.",
            "confidence": 0.85,
        }
    ]
    proposal = _write_proposal(vault, good)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 0
    updated = target.read_text(encoding="utf-8")
    assert "topic-alias" in updated


def test_validate_apply_is_idempotent(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    from octopus_kb_compound.cli import main

    main(["validate", str(proposal), "--vault", str(vault), "--apply"])
    log_after_first = (vault / "wiki" / "LOG.md").read_text(encoding="utf-8")
    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == log_after_first


def test_validate_rejects_duplicate_canonical(tmp_path):
    vault = _seed(tmp_path)
    (vault / "wiki" / "concepts").mkdir()
    (vault / "wiki" / "concepts" / "Topic.md").write_text(
        '---\ntitle: "Topic"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    bad = _append_log_proposal("p-dupe")
    bad["operations"] = [
        {
            "op": "create_page",
            "path": "wiki/concepts/topic-duplicate.md",
            "frontmatter": {
                "title": "Topic",
                "type": "concept",
                "lang": "en",
                "role": "concept",
                "layer": "wiki",
                "source_of_truth": "canonical",
                "tags": [],
                "summary": "s",
            },
            "body": "# Topic\n",
            "rationale": "r",
            "confidence": 0.95,
            "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 2},
        }
    ]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply", "--json"])

    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*.json"))
    assert len(rejections) == 1


def test_validate_apply_refuses_when_pending_audit_exists(tmp_path):
    vault = _seed(tmp_path)
    proposal = _write_proposal(vault, _append_log_proposal())
    audit_dir = vault / ".octopus-kb" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "20260418000000-p1.json").write_text(
        json.dumps(_pending_audit_entry("p1", modified=["wiki/LOG.md"], created=[])),
        encoding="utf-8",
    )
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 2


def test_validate_rejects_path_escaping_vault(tmp_path):
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-escape")
    bad["operations"] = [
        {
            "op": "append_log",
            "path": "../outside/LOG.md",
            "entry": "x",
            "rationale": "r",
            "confidence": 1.0,
        }
    ]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply", "--json"])

    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*.json"))
    assert len(rejections) == 1


def test_validate_apply_rejects_absolute_path_target(tmp_path):
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-abs")
    bad["operations"] = [
        {
            "op": "append_log",
            "path": "/etc/passwd",
            "entry": "x",
            "rationale": "r",
            "confidence": 1.0,
        }
    ]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*p-abs.json"))
    assert rejections


def test_validate_apply_rejects_hidden_control_path_target(tmp_path):
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-hidden")
    bad["operations"] = [
        {
            "op": "create_page",
            "path": ".octopus-kb/proposals/injected.json",
            "frontmatter": {
                "title": "x",
                "type": "concept",
                "lang": "en",
                "role": "concept",
                "layer": "wiki",
                "tags": [],
                "summary": "s",
            },
            "body": "x",
            "rationale": "r",
            "confidence": 1.0,
            "source_span": {"path": "raw/x.md", "start_line": 1, "end_line": 1},
        }
    ]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply"])

    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*p-hidden.json"))
    assert rejections


def test_validate_rejects_proposal_with_unsupported_op(tmp_path):
    """Schema validation must block an unknown op BEFORE any rule applies_to filtering."""
    vault = _seed(tmp_path)
    bad = _append_log_proposal("p-unknown-op")
    bad["operations"] = [
        {
            "op": "delete_page",
            "path": "wiki/concepts/Topic.md",
            "rationale": "r",
            "confidence": 1.0,
        }
    ]
    proposal = _write_proposal(vault, bad)
    from octopus_kb_compound.cli import main

    rc = main(["validate", str(proposal), "--vault", str(vault), "--apply", "--json"])

    assert rc == 0
    rejections = list((vault / ".octopus-kb" / "rejections").glob("*p-unknown-op.json"))
    assert rejections, "unsupported op must be rejected by schema.proposal_invalid"
    assert not (vault / ".octopus-kb" / "audit").exists() or not any(
        (vault / ".octopus-kb" / "audit").glob("*p-unknown-op.json")
    )


def test_recover_restores_modified_and_removes_created(tmp_path):
    vault = _seed(tmp_path)
    staging = vault / ".octopus-kb" / "staging" / "p1"
    backup = staging / "backup"
    backup.mkdir(parents=True)
    (backup / "wiki").mkdir()
    (backup / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")

    (vault / "wiki" / "LOG.md").write_text("# Partial\n", encoding="utf-8")
    (vault / "wiki" / "concepts").mkdir(exist_ok=True)
    (vault / "wiki" / "concepts" / "NewPage.md").write_text("junk", encoding="utf-8")

    audit_dir = vault / ".octopus-kb" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "20260418000000-p1.json").write_text(
        json.dumps(
            _pending_audit_entry(
                "p1",
                modified=["wiki/LOG.md"],
                created=["wiki/concepts/NewPage.md"],
            )
        ),
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main

    rc = main(["recover", "p1", "--vault", str(vault)])

    assert rc == 0
    assert (vault / "wiki" / "LOG.md").read_text(encoding="utf-8") == "# Log\n"
    assert not (vault / "wiki" / "concepts" / "NewPage.md").exists()
    assert not staging.exists()
    audit = json.loads((audit_dir / "20260418000000-p1.json").read_text(encoding="utf-8"))
    assert audit["status"] == "rolled_back"


def test_recover_is_idempotent_on_nothing_to_recover(tmp_path):
    vault = _seed(tmp_path)
    from octopus_kb_compound.cli import main

    rc = main(["recover", "nonexistent", "--vault", str(vault)])

    assert rc == 0
