"""Propose controls: policy, interpretation key, replay, and budget.

The rules match the parser's control contract. This module does not import
the parser. ``propose`` sends, including the schema-reminder retry, reserve
budget before the call. Text F4 runs in enforce mode. An endpoint with no
accounting entry fails closed.

``OCTOPUS_KB_MODEL_POLICY`` is optional JSON::

    {"endpoints": [{"base_url", "model", "accounting"}], "budget": {...}}

When it is unset, the local default endpoint and a wide ``kb.propose``
budget are used, so existing single-model CLI usage keeps working.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
from contextlib import contextmanager
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from octopus_kb_compound.jsoncanon import canonical_json, sha256_canonical

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CN_ID_RE = re.compile(r"\b\d{15}\b|\b\d{17}[\dXx]\b")
_CN_MOBILE_RE = re.compile(r"\b1\d{10}\b")
_GENERIC_PHONE_RE = re.compile(r"(?<!\w)\d(?:[\s-]?\d){9,}(?!\w)")
_BANK_CARD_RE = re.compile(r"\b\d{13,19}\b")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}\b")
_API_KEY_RE = re.compile(r"\b(?:sk|rk)-[A-Za-z0-9]{16,}\b")
_SECRET_RES = (_PRIVATE_KEY_RE, _BEARER_RE, _API_KEY_RE)

_DEFAULT_POLICY = {
    "endpoints": [
        {
            "name": "default",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b-instruct",
            "text_f4": "enforce",
            "accounting": {
                "byte_bounded": True,
                "per_message_overhead": 8,
                "per_request_overhead": 16,
                "image_cost": 1105,
                "max_image_dimension": 2048,
            },
        }
    ],
    "budget": {
        "family": "kb.propose",
        "calls": 32,
        "input_tokens": 50_000_000,
        "output_tokens": 200_000,
        "images": 8,
        "gpu_seconds": 0,
    },
}


@dataclass
class Decision:
    allowed: bool
    disposition: str
    reason: str | None = None
    hits: int = 0
    texts: tuple[str, ...] = ()
    accounting: dict | None = None


@dataclass
class Reservation:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0


@dataclass
class RunBudget:
    family: str
    limits: dict
    used: Reservation = field(default_factory=Reservation)
    blocked: bool = False
    events: list = field(default_factory=list)

    def reserve(self, item: Reservation) -> str | None:
        """Check each limit on its own. Return the first limit that does not fit."""
        if self.blocked:
            return "blocked"
        pending = {
            "calls": self.used.calls + item.calls,
            "input_tokens": self.used.input_tokens + item.input_tokens,
            "output_tokens": self.used.output_tokens + item.output_tokens,
            "images": self.used.images + item.images,
        }
        for name in ("calls", "input_tokens", "output_tokens", "images"):
            if pending[name] > int(self.limits[name]):
                return name
        self.used = Reservation(
            calls=pending["calls"],
            input_tokens=pending["input_tokens"],
            output_tokens=pending["output_tokens"],
            images=pending["images"],
        )
        return None

    def settle(self, reserved: Reservation, observed: Reservation | None, *, timeout: bool = False) -> dict | None:
        """Missing usage or a timeout keeps the reservation. An overrun is stored unclipped and blocks the run."""
        if observed is None or timeout:
            return None
        input_delta = observed.input_tokens - reserved.input_tokens
        output_delta = observed.output_tokens - reserved.output_tokens
        self.used = Reservation(
            calls=self.used.calls,
            input_tokens=self.used.input_tokens + input_delta,
            output_tokens=self.used.output_tokens + output_delta,
            images=self.used.images,
        )
        if input_delta > 0 or output_delta > 0:
            self.blocked = True
            event = {
                "event": "overrun",
                "input_tokens": observed.input_tokens,
                "output_tokens": observed.output_tokens,
            }
            self.events.append(event)
            return event
        return None


class Policy:
    def __init__(self, document: dict):
        self.document = document
        self.digest = sha256_canonical(document)
        self.endpoints = list(document.get("endpoints") or [])

    def apply(
        self,
        *,
        endpoint: str,
        model: str,
        texts: list[str] | tuple[str, ...],
        endpoint_name: str | None = None,
    ) -> Decision:
        entry = self._entry(endpoint, model, endpoint_name)
        if entry is None:
            return Decision(False, "policy_denied", "endpoint_not_allowlisted")
        accounting = entry.get("accounting")
        if not isinstance(accounting, dict) or not accounting or accounting.get("byte_bounded") is not True:
            return Decision(False, "accounting_unavailable", "accounting_unavailable")
        mode = "enforce" if entry.get("text_f4", "enforce") == "enforce" else str(entry.get("text_f4") or "observe")
        redacted: list[str] = []
        hits = 0
        for text in texts:
            scanned, count = scan_text(text, mode)
            redacted.append(scanned)
            hits += count
        return Decision(True, "allowed", hits=hits, texts=tuple(redacted), accounting=dict(accounting))

    def _entry(self, endpoint: str, model: str, endpoint_name: str | None) -> dict | None:
        if endpoint_name is not None:
            for entry in self.endpoints:
                if entry.get("name") == endpoint_name:
                    return entry
            return None
        wanted = endpoint.rstrip("/")
        for entry in self.endpoints:
            if str(entry.get("base_url", "")).rstrip("/") == wanted and entry.get("model") == model:
                return entry
        return None


def load_policy() -> Policy:
    raw = os.environ.get("OCTOPUS_KB_MODEL_POLICY")
    if raw is None or not raw.strip():
        return Policy(_DEFAULT_POLICY)
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("model policy must be a mapping")
    return Policy(document)


def load_budget() -> RunBudget:
    policy = load_policy()
    raw = policy.document.get("budget") or _DEFAULT_POLICY["budget"]
    limits = {
        "calls": int(raw["calls"]),
        "input_tokens": int(raw["input_tokens"]),
        "output_tokens": int(raw["output_tokens"]),
        "images": int(raw["images"]),
        "gpu_seconds": int(raw.get("gpu_seconds", 0)),
    }
    return RunBudget(family=str(raw.get("family") or "kb.propose"), limits=limits)


def scan_text(value: str, mode: str) -> tuple[str, int]:
    """Count F4 hits. Enforce redacts; observe returns the original string."""
    hits = _count_hits(value)
    if mode != "enforce":
        return value, hits
    return _redact_secrets(_redact_pii(value)), hits


def accounted_input(texts, schema, images, accounting: dict) -> int:
    """UTF-8 content bytes, schema bytes, framing, and image cost. No tokenizer."""
    if accounting.get("byte_bounded") is not True:
        raise ValueError("accounting_unavailable")
    content = sum(len(str(text).encode("utf-8")) for text in texts)
    if schema is not None:
        content += len(canonical_json(schema).encode("utf-8"))
    framing = int(accounting["per_message_overhead"]) * len(texts) + int(accounting["per_request_overhead"])
    image_tokens = sum(_image_tokens(image, accounting) for image in images)
    return content + framing + image_tokens


def request_digest(messages: list[dict], response_format: dict) -> str:
    return sha256_canonical({"messages": messages, "response_format": response_format})


def interpretation_key(
    *,
    tenant: str,
    provenance: str,
    endpoint: str,
    model: str,
    prompt_version_digest: str,
    request_digest_hex: str,
    policy_digest: str,
) -> str:
    return sha256_canonical({
        "tenant": tenant,
        "provenance": provenance,
        "purpose": "propose",
        "endpoint": endpoint.rstrip("/"),
        "model": model,
        "prompt_version_digest": prompt_version_digest,
        "request_digest": request_digest_hex,
        "policy_digest": policy_digest,
    })


class ReplayUnavailable:
    """The index names a record that is no longer on disk."""

    def __init__(self, record_id: str):
        self.record_id = record_id
        self.reason = "replay_unavailable"


class InterpretationStore:
    """Immutable records plus a write-once index of accepted responses."""

    def __init__(self, vault: Path):
        self.root = Path(vault) / ".octopus-kb" / "interpretations"

    def lookup(self, key: str) -> str | ReplayUnavailable | None:
        with _lock(self.root):
            return self._lookup_unlocked(key)

    def publish(self, key: str, response_text: str) -> str:
        """Return the winning text. A missing record is replaced and linked."""
        with _lock(self.root):
            current = _read_json(self._index(key))
            regenerated_from = None
            if current and current.get("record_id"):
                existing = self._read_record(str(current["record_id"]))
                if existing is not None and existing.get("accepted") is True:
                    return str(existing.get("response_text") or "")
                regenerated_from = str(current["record_id"])
            record_id = uuid.uuid4().hex
            record = {
                "record_id": record_id,
                "key": key,
                "accepted": True,
                "response_text": response_text,
                "regenerated_from": regenerated_from,
            }
            directory = self.root / "records"
            directory.mkdir(parents=True, exist_ok=True)
            _write_exclusive(directory / f"{record_id}.json", record)
            index = self._index(key)
            index.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"record_id": record_id, "regenerated_from": regenerated_from},
                sort_keys=True,
            ) + "\n"
            fd, tmp_name = tempfile.mkstemp(prefix=f".{record_id}.", suffix=".tmp", dir=index.parent)
            tmp_path = Path(tmp_name)
            try:
                _write_all(fd, payload.encode("utf-8"))
                os.fsync(fd)
                os.close(fd)
                fd = -1
                if regenerated_from is not None:
                    os.replace(tmp_path, index)
                else:
                    try:
                        os.link(tmp_path, index)
                    except FileExistsError:
                        winner = self._lookup_unlocked(key)
                        return winner if isinstance(winner, str) else response_text
            finally:
                if fd >= 0:
                    os.close(fd)
                tmp_path.unlink(missing_ok=True)
            return response_text

    def _lookup_unlocked(self, key: str) -> str | ReplayUnavailable | None:
        current = _read_json(self._index(key))
        if not current or not current.get("record_id"):
            return None
        record = self._read_record(str(current["record_id"]))
        if record is None:
            return ReplayUnavailable(str(current["record_id"]))
        if record.get("accepted") is not True:
            return None
        return str(record.get("response_text") or "")

    def _read_record(self, record_id: str) -> dict | None:
        return _read_json(self.root / "records" / f"{record_id}.json")

    def _index(self, key: str) -> Path:
        return self.root / "index" / f"{key}.json"


@contextmanager
def _lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / ".lock", "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_exclusive(path: Path, record: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        _write_all(fd, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _count_hits(value: str) -> int:
    hits = len(_EMAIL_RE.findall(value))
    hits += len(_CN_ID_RE.findall(value))
    hits += len(_CN_MOBILE_RE.findall(value))
    hits += len(_BANK_CARD_RE.findall(value))
    for match in _GENERIC_PHONE_RE.finditer(value):
        if re.search(r"[\s-]", match.group(0)):
            hits += 1
    for pattern in _SECRET_RES:
        hits += len(pattern.findall(value))
    return hits


def _redact_pii(value: str) -> str:
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    redacted = _CN_ID_RE.sub("[REDACTED_ID]", redacted)
    redacted = _CN_MOBILE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _GENERIC_PHONE_RE.sub(_redact_phone, redacted)
    return _BANK_CARD_RE.sub("[REDACTED_CARD]", redacted)


def _redact_phone(match: re.Match[str]) -> str:
    if not re.search(r"[\s-]", match.group(0)):
        return match.group(0)
    return "[REDACTED_PHONE]"


def _redact_secrets(value: str) -> str:
    redacted = value
    for pattern in _SECRET_RES:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _image_tokens(image, accounting: dict) -> int:
    cost = int(accounting["image_cost"])
    if cost == 0:
        return 0
    width = image["width"] if isinstance(image, dict) else image.width
    height = image["height"] if isinstance(image, dict) else image.height
    if width is None or height is None:
        return cost
    long_side = max(int(width), int(height), 1)
    cap = max(int(accounting["max_image_dimension"]), 1)
    if long_side <= cap:
        return cost
    scale = long_side / cap
    return math.ceil(cost * scale * scale)
