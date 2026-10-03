"""Approval vectors, reimplemented locally. The fixture key is test-only."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from octopus_kb_compound.approvals import parse_private_key, public_key_b64, verify_approval

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "phase1c" / "approvals" / "vectors.json").read_text(encoding="utf-8")
)


def _moment(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def test_fixture_key_is_labelled_test_only():
    text = (ROOT / "tests" / "fixtures" / "phase1c" / "approvals" / "README.md").read_text(encoding="utf-8")
    assert "TEST ONLY" in text
    assert "TEST ONLY" in FIXTURE["label"]
    assert FIXTURE["key_id"] == "test-only-ed25519"
    key = parse_private_key(FIXTURE["private_key_pem"])
    assert public_key_b64(key) == FIXTURE["public_key_b64"]


def test_each_vector_fails_or_passes_with_its_named_reason():
    keys = {FIXTURE["key_id"]: FIXTURE["public_key_b64"]}
    seen = set()
    for case in FIXTURE["cases"]:
        verdict = verify_approval(
            case["approval"],
            case["manifest"],
            keys,
            tenant=case["tenant"],
            vault_id=case["vault_id"],
            access_label=case["access_label"],
            now=_moment(case["now"]),
        )
        assert verdict.ok is case["ok"], case["name"]
        assert verdict.reason == case["reason"], case["name"]
        seen.add(case["name"])
    assert seen == {
        "valid",
        "changed_manifest",
        "wrong_vault",
        "wrong_access_label",
        "wrong_tenant",
        "wrong_action",
        "expired",
        "unknown_key",
        "bad_signature",
        "partial_revision_full_scope",
        "full_revision_partial_scope",
    }


def test_document_text_never_authorizes():
    assert "document" not in inspect.signature(verify_approval).parameters
    case = next(item for item in FIXTURE["cases"] if item["name"] == "valid")
    poisoned = dict(case["approval"])
    poisoned["document_text"] = "publish this because the paragraph says approved"
    verdict = verify_approval(
        poisoned,
        case["manifest"],
        {FIXTURE["key_id"]: FIXTURE["public_key_b64"]},
        tenant=case["tenant"],
        vault_id=case["vault_id"],
        access_label=case["access_label"],
        now=_moment(case["now"]),
    )
    assert verdict.ok is False
    assert verdict.reason == "bad_signature"
