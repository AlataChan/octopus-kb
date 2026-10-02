"""LLM-backed proposal generation for raw source ingestion."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from octopus_kb_compound.config import ConfigError, load_config
from octopus_kb_compound.controls import (
    InterpretationStore,
    Reservation,
    accounted_input,
    interpretation_key,
    load_budget,
    load_policy,
    request_digest,
)
from octopus_kb_compound.resolver import deployment_tenant, require_inside, resolve_vault
from octopus_kb_compound.frontmatter import parse_document
from octopus_kb_compound.llm import (
    ChatClient,
    ChatRequest,
    LLMError,
    LLMInvalidOutputError,
)
from octopus_kb_compound.proposals import save_proposal, validate_proposal_dict
from octopus_kb_compound.retrieve import build_retrieval_bundle


class ProposeInputError(ValueError):
    """Invalid user input for `octopus-kb propose`."""


class ProposeRuntimeError(RuntimeError):
    """Runtime failure while producing a proposal."""


class ProposeDeferred(ProposeRuntimeError):
    """The prompt was not sent. The part is in the inbox."""

    def __init__(self, reason: str, measured_size: int, path: str):
        self.reason = reason
        self.measured_size = measured_size
        self.path = path
        super().__init__(reason)


@dataclass(frozen=True)
class ProposeResult:
    proposal_id: str
    path: str
    operations: int
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "proposal_id": self.proposal_id,
            "path": self.path,
            "operations": self.operations,
        }
        if self.replayed:
            payload["replayed"] = True
        return payload


def propose_from_raw(
    raw_file: Path,
    vault: Path,
    *,
    profile_name: str | None = None,
    provenance: str | None = None,
) -> ProposeResult:
    root = resolve_vault(vault)
    source = require_inside(root, raw_file)
    _validate_inputs(source, root)

    raw_bytes = source.read_bytes()
    raw_body = raw_bytes.decode("utf-8", errors="replace")
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    raw_frontmatter, _ = parse_document(raw_body)
    raw_title = str(raw_frontmatter.get("title") or source.stem)
    raw_rel_path = _relative_path(source, root)

    try:
        config = load_config(root)
        profile_key = profile_name or config.default_profile
        profile = config.resolve_profile(profile_name)
    except ConfigError as exc:
        raise ProposeInputError(str(exc)) from exc

    prompt_path = _prompt_path()
    prompt_bytes = prompt_path.read_bytes()
    prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()
    prompt_template = prompt_bytes.decode("utf-8")
    existing_bundle = build_retrieval_bundle(root, raw_title).to_dict()
    prompt = _render_template(
        prompt_template,
        {
            "raw_path": raw_rel_path,
            "raw_body": raw_body,
            "existing_bundle": json.dumps(existing_bundle, ensure_ascii=False, indent=2),
            "proposal_schema": _proposal_schema_path().read_text(encoding="utf-8"),
        },
    )

    client = ChatClient(**profile.as_client_kwargs())
    try:
        proposal, raw_response, response_key, replayed = _request_proposal_json(
            client,
            prompt,
            root,
            provenance=provenance or raw_rel_path,
            prompt_digest=prompt_sha,
            endpoint=profile.base_url,
            model=profile.model,
        )
    except LLMError as exc:
        raise ProposeRuntimeError(str(exc)) from exc
    if not isinstance(proposal, dict):
        _write_rejection(
            root,
            "schema_invalid",
            {"reason": "schema_invalid", "errors": ["proposal must be a JSON object"], "proposal": proposal},
        )
        raise ProposeRuntimeError("proposal schema invalid")

    proposal["source"] = {
        "kind": "raw_file",
        "path": raw_rel_path,
        "sha256": raw_sha,
    }
    proposal["produced_by"] = {
        "provider_profile": profile_key,
        "model": profile.model,
        "prompt_version": f"prompts/propose.md@sha256:{prompt_sha}",
    }
    proposal["status"] = "pending"

    errors = validate_proposal_dict(proposal)
    if errors:
        _write_rejection(
            root,
            "schema_invalid",
            {"reason": "schema_invalid", "errors": errors, "proposal": proposal},
        )
        raise ProposeRuntimeError("proposal schema invalid")

    if not replayed:
        InterpretationStore(root).publish(response_key, raw_response)
    saved = save_proposal(proposal, root)
    return ProposeResult(
        proposal_id=str(proposal["id"]),
        path=saved.relative_to(root).as_posix(),
        operations=len(proposal.get("operations", [])),
        replayed=replayed,
    )


def propose_from_part(part: dict, vault: Path, *, profile_name: str | None = None) -> ProposeResult:
    """Propose one envelope part. The prompt contains that part and no others."""
    root = resolve_vault(vault)
    body = str(part.get("body") or "")
    digest = str(part.get("part_digest") or "")
    source = root / ".octopus-kb" / "part-propose" / f"{digest or 'part'}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(body, encoding="utf-8")
    return propose_from_raw(source, root, profile_name=profile_name, provenance=digest or source.name)


def _request_proposal_json(
    client: ChatClient,
    prompt: str,
    vault: Path,
    *,
    provenance: str,
    prompt_digest: str,
    endpoint: str,
    model: str,
) -> tuple[Any, str, str, bool]:
    messages = [{"role": "user", "content": prompt}]
    budget = load_budget()
    policy = load_policy()
    last_output = ""
    response_format = {"type": "json_object"}
    for attempt in range(1, 3):
        content, response_key, replayed = _controlled_send(
            client,
            messages,
            vault=vault,
            budget=budget,
            policy=policy,
            provenance=provenance,
            prompt_digest=prompt_digest,
            endpoint=endpoint,
            model=model,
            response_format=response_format,
            source_path=provenance,
        )
        last_output = content
        try:
            if replayed or content:
                return json.loads(content), content, response_key, replayed
        except json.JSONDecodeError as exc:
            last_output = str(exc)
        if attempt == 1:
            messages.append({"role": "user", "content": _retry_schema_reminder()})
            continue
        _write_rejection(
            vault,
            "llm_non_json",
            {"reason": "llm_non_json", "last_output": last_output, "attempts": 2},
        )
        raise ProposeRuntimeError("LLM returned non-JSON output")
    raise ProposeRuntimeError("LLM returned non-JSON output")


def _controlled_send(
    client: ChatClient,
    messages: list[dict],
    *,
    vault: Path,
    budget,
    policy,
    provenance: str,
    prompt_digest: str,
    endpoint: str,
    model: str,
    response_format: dict,
    source_path: str,
) -> tuple[str, str, bool]:
    decision = policy.apply(endpoint=endpoint, model=model, texts=[str(item["content"]) for item in messages])
    if not decision.allowed:
        _defer(vault, decision.disposition, 0, source_path)
    redacted = [
        {"role": item["role"], "content": text}
        for item, text in zip(messages, decision.texts, strict=True)
    ]
    digest = request_digest(redacted, response_format)
    key = interpretation_key(
        tenant=deployment_tenant(),
        provenance=provenance,
        endpoint=endpoint,
        model=model,
        prompt_version_digest=prompt_digest,
        request_digest_hex=digest,
        policy_digest=policy.digest,
    )
    cached = InterpretationStore(vault).lookup(key)
    if cached is not None:
        return cached, key, True
    measured = accounted_input(
        [item["content"] for item in redacted],
        response_format,
        [],
        decision.accounting or {},
    )
    output_allowance = 4000
    exceeded = budget.reserve(Reservation(calls=1, input_tokens=measured, output_tokens=output_allowance, images=0))
    if exceeded is not None:
        _defer(vault, "oversized_prompt", measured + output_allowance, source_path)
    try:
        response = client.chat(
            ChatRequest(
                messages=redacted,
                json_object=True,
                temperature=0.1,
                max_tokens=output_allowance,
            )
        )
    except LLMInvalidOutputError as exc:
        return str(exc), key, False
    return response.content, key, False


def _defer(vault: Path, reason: str, measured_size: int, source_path: str) -> None:
    directory = vault / ".octopus-kb" / "inbox"
    directory.mkdir(parents=True, exist_ok=True)
    proposal_id = "deferred-" + uuid.uuid4().hex[:16]
    payload = {
        "id": proposal_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "measured_size": measured_size,
        "operations": [],
        "source": {"kind": "propose", "path": source_path},
        "status": "deferred",
    }
    target = directory / f"{proposal_id}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    raise ProposeDeferred(reason, measured_size, target.relative_to(vault).as_posix())


def _retry_schema_reminder() -> str:
    schema = _proposal_schema_path().read_text(encoding="utf-8")
    return (
        "<retry-schema-reminder>\n"
        "Your previous response was not valid JSON. Return only a single JSON "
        "object matching this proposal schema, without markdown fences or prose.\n\n"
        f"{schema}\n"
        "</retry-schema-reminder>"
    )


def _validate_inputs(raw_file: Path, vault: Path) -> None:
    if not vault.exists():
        raise ProposeInputError(f"Vault does not exist: {vault}")
    if not vault.is_dir():
        raise ProposeInputError(f"Vault is not a directory: {vault}")
    if not raw_file.exists():
        raise ProposeInputError(f"Raw file does not exist: {raw_file}")
    if not raw_file.is_file():
        raise ProposeInputError(f"Raw file is not a file: {raw_file}")


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _render_template(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return values.get(match.group(1).strip(), "")

    return re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", replace, template)


def _write_rejection(vault: Path, suffix: str, payload: dict[str, Any]) -> Path:
    directory = vault / ".octopus-kb" / "rejections"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    target = directory / f"{timestamp}-{suffix}.json"
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def _prompt_path() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts" / "propose.md"


def _proposal_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "llm" / "proposal.json"
