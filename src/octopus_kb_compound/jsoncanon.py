"""Canonical JSON used for digests and approval signatures.

This is a local reimplementation of the parser's rules. Nothing is imported
from the parser.
"""

from __future__ import annotations

import hashlib
import json


def canonical_bytes(value: object) -> bytes:
    """UTF-8 JSON, keys sorted, no insignificant whitespace. Every field is kept."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json(value: object) -> str:
    return canonical_bytes(value).decode("utf-8")


def sha256_canonical(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
