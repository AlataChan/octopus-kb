"""Ed25519 approval checks over a revision manifest.

The signature covers the canonical JSON of the approval with ``signature``
removed. The subject digest is recomputed from the manifest. Document text
is not an input. The fixture key shipped with the vectors is test-only.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from octopus_kb_compound.jsoncanon import canonical_bytes, sha256_canonical

SCHEMA_VERSION = "revision-manifest/0.1.0"
RANKED_STATUS = ("consistent_unverified", "completed_partial")
_APPROVAL_FIELDS = (
    "approval_id",
    "tenant",
    "action",
    "subject_digest",
    "vault_id",
    "access_label",
    "scope",
    "reviewer",
    "issued_at",
    "expires_at",
    "key_id",
    "signature",
)


@dataclass(frozen=True)
class ApprovalVerdict:
    ok: bool
    reason: str


def manifest_digest(manifest: dict) -> str:
    """SHA-256 of the canonical manifest without ``revision_id``."""
    body = {key: value for key, value in manifest.items() if key != "revision_id"}
    return sha256_canonical(body)


def part_digest(envelope: dict) -> str:
    """SHA-256 of the canonical envelope without ``part_digest``."""
    body = {key: value for key, value in envelope.items() if key != "part_digest"}
    return sha256_canonical(body)


def logical_document_id(tenant: str, vault_id: str, placement: str, access_label: str) -> str:
    return sha256_canonical({
        "access_label": access_label,
        "placement": placement,
        "tenant": tenant,
        "vault_id": vault_id,
    })


def load_approval_keys() -> dict[str, str]:
    raw = os.environ.get("OCTOPUS_KB_APPROVAL_KEYS", "")
    if not raw.strip():
        return {}
    parsed = json_loads(raw)
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def parse_private_key(material: str) -> Ed25519PrivateKey:
    text = material.strip()
    if "BEGIN" in text:
        key = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
    else:
        raw = _b64decode(text)
        key = Ed25519PrivateKey.from_private_bytes(raw)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("approval signing key")
    return key


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def sign_approval(record: dict, private_key: Ed25519PrivateKey) -> str:
    signature = private_key.sign(canonical_bytes(_signed_body(record)))
    return base64.b64encode(signature).decode("ascii")


def verify_approval(
    approval: dict,
    manifest: dict,
    trusted_keys: dict[str, str],
    *,
    tenant: str,
    vault_id: str,
    access_label: str,
    now: datetime,
) -> ApprovalVerdict:
    """Pure check. Tenant, vault, and access label come from trusted config."""
    if not isinstance(approval, dict) or not isinstance(manifest, dict):
        return ApprovalVerdict(False, "malformed")
    if any(name not in approval for name in _APPROVAL_FIELDS):
        return ApprovalVerdict(False, "malformed")
    key_id = approval.get("key_id")
    if not isinstance(key_id, str) or key_id not in trusted_keys:
        return ApprovalVerdict(False, "unknown_key")
    try:
        public = _public_key_from_b64(trusted_keys[key_id])
        signature = _b64decode(str(approval.get("signature") or ""))
        public.verify(signature, canonical_bytes(_signed_body(approval)))
    except (InvalidSignature, ValueError, TypeError):
        return ApprovalVerdict(False, "bad_signature")
    try:
        expires = _parse_time(approval.get("expires_at"))
        moment = _as_utc(now)
    except (TypeError, ValueError):
        return ApprovalVerdict(False, "malformed")
    if expires <= moment:
        return ApprovalVerdict(False, "expired")
    if approval.get("tenant") != tenant or manifest.get("tenant") != tenant:
        return ApprovalVerdict(False, "tenant_mismatch")
    if approval.get("action") != "publish":
        return ApprovalVerdict(False, "wrong_action")
    try:
        digest = manifest_digest(manifest)
    except (TypeError, ValueError):
        return ApprovalVerdict(False, "malformed")
    if approval.get("subject_digest") != digest:
        return ApprovalVerdict(False, "subject_mismatch")
    if approval.get("vault_id") != vault_id or manifest.get("vault_id") != vault_id:
        return ApprovalVerdict(False, "vault_mismatch")
    if approval.get("access_label") != access_label or manifest.get("access_label") != access_label:
        return ApprovalVerdict(False, "access_label_mismatch")
    scope = approval.get("scope")
    status = manifest.get("status")
    if scope not in {"partial", "full"} or status not in RANKED_STATUS:
        return ApprovalVerdict(False, "malformed" if status in RANKED_STATUS or status is None else "unranked_status")
    if status == "completed_partial" and scope != "partial":
        return ApprovalVerdict(False, "scope_mismatch")
    return ApprovalVerdict(True, "ok")


def _signed_body(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "signature"}


def _public_key_from_b64(value: str) -> Ed25519PublicKey:
    raw = _b64decode(value)
    if len(raw) != 32:
        raise ValueError("public key")
    return Ed25519PublicKey.from_public_bytes(raw)


def _b64decode(value: str) -> bytes:
    text = value.strip()
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.b64decode(padded, validate=False)
    except Exception:
        return base64.urlsafe_b64decode(padded)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("time")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def json_loads(raw: str) -> object:
    import json

    return json.loads(raw)

