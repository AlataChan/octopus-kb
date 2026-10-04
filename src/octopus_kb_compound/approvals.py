"""Ed25519 approval and verification-attestation checks.

The signature covers the canonical JSON of the record with ``signature``
removed. The subject digest is recomputed from the manifest. Document text
is not an input. Fixture keys shipped with the vectors are test-only.

``manifest_digest`` dispatches on ``schema_version``. A 0.1.0 manifest
excludes ``revision_id``. A 0.2.0 manifest also excludes ``verification_ref``.
An unknown version is rejected and is never digested by a default rule.
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
MANIFEST_V1 = "revision-manifest/0.1.0"
MANIFEST_V2 = "revision-manifest/0.2.0"
ATTESTATION_VERSION = "verification-attestation/0.1.0"
DECISION_TABLE_VERSIONS = frozenset({"decision-table/0.1.0"})
RANKED_STATUS = ("succeeded", "consistent_unverified", "completed_partial")
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


class KeyConfigurationError(ValueError):
    """The approval key set and the verifier key set are not separate."""


def manifest_digest(manifest: dict) -> str:
    """SHA-256 of the canonical manifest, dispatched on ``schema_version``."""
    version = manifest.get("schema_version")
    if version == MANIFEST_V1:
        excluded = {"revision_id"}
    elif version == MANIFEST_V2:
        excluded = {"revision_id", "verification_ref"}
    else:
        raise ValueError("unknown_schema_version")
    body = {key: value for key, value in manifest.items() if key not in excluded}
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
    approval, verifier = _load_authority_keys()
    _refuse_overlapping_authorities(approval, verifier)
    return approval


def load_verifier_keys() -> dict[str, str]:
    approval, verifier = _load_authority_keys()
    _refuse_overlapping_authorities(approval, verifier)
    return verifier


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


def sign_attestation(record: dict, private_key: Ed25519PrivateKey) -> str:
    """Ed25519 over the canonical attestation with ``signature`` removed."""
    return sign_approval(record, private_key)


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


_ATTESTATION_FIELDS = (
    "schema_version",
    "role",
    "attestation_id",
    "key_id",
    "revision_id",
    "logical_document_id",
    "tenant",
    "vault_id",
    "access_label",
    "parts",
    "catalog_digest",
    "validator_registry_version",
    "probe_scorer_version",
    "decision_table_version",
    "issued_at",
    "expires_at",
    "signature",
)


def verify_attestation(
    attestation: dict,
    manifest: dict,
    trusted_keys: dict[str, str],
    *,
    tenant: str,
    vault_id: str,
    access_label: str,
    logical_document_id: str,
    staged_statuses: list[str],
    now: datetime,
) -> ApprovalVerdict:
    """Pure check. Destination fields come from trusted config, not the file."""
    if not isinstance(attestation, dict) or not isinstance(manifest, dict):
        return ApprovalVerdict(False, "malformed")
    if any(name not in attestation for name in _ATTESTATION_FIELDS):
        return ApprovalVerdict(False, "malformed")
    if attestation.get("schema_version") != ATTESTATION_VERSION:
        return ApprovalVerdict(False, "malformed")
    if not _hex(attestation.get("attestation_id"), 32):
        return ApprovalVerdict(False, "malformed")
    if not _hex(attestation.get("revision_id"), 64):
        return ApprovalVerdict(False, "malformed")
    if not _hex(attestation.get("logical_document_id"), 64):
        return ApprovalVerdict(False, "malformed")
    if not _hex(attestation.get("catalog_digest"), 64):
        return ApprovalVerdict(False, "malformed")
    if not _text(attestation.get("key_id")) or not _text(attestation.get("tenant")):
        return ApprovalVerdict(False, "malformed")
    if not _text(attestation.get("vault_id")) or not _text(attestation.get("access_label")):
        return ApprovalVerdict(False, "malformed")
    if not _text(attestation.get("validator_registry_version")):
        return ApprovalVerdict(False, "malformed")
    if not _text(attestation.get("probe_scorer_version")):
        return ApprovalVerdict(False, "malformed")
    if not _text(attestation.get("decision_table_version")):
        return ApprovalVerdict(False, "malformed")
    if not isinstance(attestation.get("role"), str) or not isinstance(attestation.get("signature"), str):
        return ApprovalVerdict(False, "malformed")
    if not _attestation_parts_well_formed(attestation.get("parts")):
        return ApprovalVerdict(False, "malformed")
    key_id = attestation.get("key_id")
    if not isinstance(key_id, str) or key_id not in trusted_keys:
        return ApprovalVerdict(False, "unknown_key")
    try:
        public = _public_key_from_b64(trusted_keys[key_id])
        signature = _b64decode(attestation.get("signature") or "")
        public.verify(signature, canonical_bytes(_signed_body(attestation)))
    except (InvalidSignature, ValueError, TypeError):
        return ApprovalVerdict(False, "bad_signature")
    if attestation.get("role") != "verifier":
        return ApprovalVerdict(False, "wrong_role")
    try:
        issued = _parse_time(attestation.get("issued_at"))
        expires = _parse_time(attestation.get("expires_at"))
        moment = _as_utc(now)
    except (TypeError, ValueError):
        return ApprovalVerdict(False, "malformed")
    if expires <= moment:
        return ApprovalVerdict(False, "expired")
    if issued > moment:
        return ApprovalVerdict(False, "not_yet_valid")
    if attestation.get("decision_table_version") not in DECISION_TABLE_VERSIONS:
        return ApprovalVerdict(False, "unknown_decision_table")
    if manifest.get("verification_ref") != attestation.get("attestation_id"):
        return ApprovalVerdict(False, "verification_ref_mismatch")
    if manifest.get("schema_version") != MANIFEST_V2:
        return ApprovalVerdict(False, "revision_mismatch")
    try:
        digest = manifest_digest(manifest)
    except (TypeError, ValueError):
        return ApprovalVerdict(False, "revision_mismatch")
    if attestation.get("revision_id") != digest or manifest.get("revision_id") != digest:
        return ApprovalVerdict(False, "revision_mismatch")
    if (
        attestation.get("logical_document_id") != logical_document_id
        or manifest.get("logical_document_id") != logical_document_id
    ):
        return ApprovalVerdict(False, "logical_document_mismatch")
    if attestation.get("tenant") != tenant or manifest.get("tenant") != tenant:
        return ApprovalVerdict(False, "tenant_mismatch")
    if attestation.get("vault_id") != vault_id or manifest.get("vault_id") != vault_id:
        return ApprovalVerdict(False, "vault_mismatch")
    if attestation.get("access_label") != access_label or manifest.get("access_label") != access_label:
        return ApprovalVerdict(False, "access_label_mismatch")
    if not _parts_bind(manifest, attestation):
        return ApprovalVerdict(False, "parts_mismatch")
    if manifest.get("status") != "succeeded":
        return ApprovalVerdict(False, "not_succeeded")
    if any(part.get("status") != "succeeded" for part in attestation["parts"]):
        return ApprovalVerdict(False, "not_succeeded")
    if len(staged_statuses) != len(manifest.get("parts") or []) or any(
        status != "succeeded" for status in staged_statuses
    ):
        return ApprovalVerdict(False, "not_succeeded")
    return ApprovalVerdict(True, "ok")


def _load_authority_keys() -> tuple[dict[str, str], dict[str, str]]:
    return _load_key_map("OCTOPUS_KB_APPROVAL_KEYS"), _load_key_map("OCTOPUS_KB_VERIFIER_KEYS")


def _load_key_map(name: str) -> dict[str, str]:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return {}
    parsed = json_loads(raw)
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def _refuse_overlapping_authorities(approval: dict[str, str], verifier: dict[str, str]) -> None:
    if not approval or not verifier:
        return
    if set(approval) & set(verifier):
        raise KeyConfigurationError("shared key id")
    if {_public_material(value) for value in approval.values()} & {
        _public_material(value) for value in verifier.values()
    }:
        raise KeyConfigurationError("shared public key")


def _public_material(value: str) -> bytes:
    try:
        return _b64decode(value)
    except Exception:
        return b"raw:" + value.encode("utf-8")


def _hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _attestation_parts_well_formed(parts: object) -> bool:
    if not isinstance(parts, list) or not parts:
        return False
    for part in parts:
        if not isinstance(part, dict):
            return False
        if not isinstance(part.get("index"), int) or isinstance(part.get("index"), bool):
            return False
        if part["index"] < 0 or not _hex(part.get("part_digest"), 64):
            return False
        if not isinstance(part.get("status"), str):
            return False
    return True


def _parts_bind(manifest: dict, attestation: dict) -> bool:
    manifest_parts = manifest.get("parts")
    if not isinstance(manifest_parts, list):
        return False
    try:
        left = [(part["index"], part["part_digest"]) for part in manifest_parts]
        right = [(part["index"], part["part_digest"]) for part in attestation["parts"]]
    except (KeyError, TypeError):
        return False
    return left == right


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

