"""Trusted tenant-root resolution.

``OCTOPUS_KB_TENANT`` is the deployment tenant. ``OCTOPUS_KB_VAULTS`` is JSON
mapping ``vault_id`` to ``{"root", "allowed_access_labels"}``.

When ``OCTOPUS_KB_VAULTS`` is unset, the path the caller gave is the only
root, and existing single-vault CLI usage keeps working. When the variable
is set, enforcement is strict: ``realpath`` must land inside a configured
root. ``..``, absolute paths, and symlinks are all resolved before that check.
The filesystem under those roots is trusted only for this service account.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class VaultRootError(Exception):
    """A path escaped the trusted roots. ``reason`` is the public name."""

    def __init__(self, reason: str = "outside_root") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ConfiguredVault:
    vault_id: str
    root: Path
    allowed_access_labels: tuple[str, ...]


def deployment_tenant() -> str:
    """Tenant from deployment config. Never taken from an envelope."""
    value = os.environ.get("OCTOPUS_KB_TENANT", "default")
    return value or "default"


def configured_vaults() -> dict[str, ConfiguredVault] | None:
    """``None`` means the variable is unset and single-vault mode is in force."""
    raw = os.environ.get("OCTOPUS_KB_VAULTS")
    if raw is None:
        return None
    if not raw.strip():
        raise VaultRootError("vaults_unconfigured")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VaultRootError("vaults_unconfigured") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise VaultRootError("vaults_unconfigured")
    table: dict[str, ConfiguredVault] = {}
    for vault_id, entry in parsed.items():
        if not isinstance(vault_id, str) or not vault_id:
            raise VaultRootError("vaults_unconfigured")
        if not isinstance(entry, dict):
            raise VaultRootError("vaults_unconfigured")
        root = entry.get("root")
        labels = entry.get("allowed_access_labels")
        if not isinstance(root, str) or not root:
            raise VaultRootError("vaults_unconfigured")
        if not isinstance(labels, list) or not labels or not all(isinstance(item, str) and item for item in labels):
            raise VaultRootError("vaults_unconfigured")
        table[vault_id] = ConfiguredVault(vault_id, Path(root).resolve(), tuple(labels))
    return table


def resolve_vault_id(vault_id: str) -> ConfiguredVault:
    table = configured_vaults()
    if table is None or vault_id not in table:
        raise VaultRootError("vault_unconfigured")
    return table[vault_id]


def resolve_vault(vault: str | Path) -> Path:
    """Return the real vault path, or raise ``VaultRootError``."""
    resolved = Path(vault).resolve()
    table = configured_vaults()
    if table is None:
        return resolved
    if any(_contained(resolved, item.root) for item in table.values()):
        return resolved
    raise VaultRootError("outside_root")


def require_inside(vault: str | Path, candidate: str | Path) -> Path:
    """Resolve ``candidate`` and require it to stay inside the vault root."""
    root = resolve_vault(vault)
    raw = Path(candidate)
    target = raw.resolve() if raw.is_absolute() else (Path(vault) / raw).resolve()
    boundary = root if configured_vaults() is not None else Path(vault).resolve()
    if not _contained(target, boundary):
        raise VaultRootError("outside_root")
    return target


def contained_leaf(root: str | Path, candidate: str | Path) -> Path:
    """Real path of one leaf that stays inside ``root``.

    Call this before reading the leaf. An escaping symlink, a broken link,
    and any other path whose realpath leaves ``root`` raise ``VaultRootError``
    and are not opened.
    """
    boundary = Path(root).resolve()
    try:
        target = Path(candidate).resolve(strict=True)
    except OSError as exc:
        raise VaultRootError("outside_root") from exc
    if not _contained(target, boundary):
        raise VaultRootError("outside_root")
    return target


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
