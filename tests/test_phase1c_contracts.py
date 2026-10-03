"""Pinned copies of the parser's phase 1c contracts. Bytes are not imported."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIGESTS = ROOT / "tests" / "fixtures" / "phase1c" / "DIGESTS.json"


def test_copied_contracts_match_pinned_digests():
    pinned = json.loads(DIGESTS.read_text(encoding="utf-8"))
    assert pinned, "DIGESTS.json is empty"
    for relative, expected in pinned.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected, relative
