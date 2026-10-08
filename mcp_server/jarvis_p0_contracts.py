"""P0 contracts for safe NextPlan/Jarvis state sync and context interchange.

This module has no network, filesystem, database or model side effects.
It does NOT connect to ChatGPT internal memory or perform a state write.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

CONTRACT_VERSION = "jarvis-p0-v1"
VALID_CONTEXT_TYPES = frozenset({"decision", "observation", "hypothesis", "preference", "handoff"})
VALID_SOURCES = frozenset({"chatgpt_user_turn", "jarvis_verified_receipt", "manual_import"})
PRIVATE_STORAGE = frozenset({"local_encrypted", "private_authenticated_service"})
SECRET_PATTERN = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9_.~+/-]{8,}|"
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,})|"
    r"\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]{6,})",
    re.IGNORECASE,
)


class JarvisContractError(ValueError):
    """A request violates the planned P0 authority/privacy boundary."""


def _text(value: Any, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str):
        raise JarvisContractError(f"{name} must be a string")
    out = value.strip()
    if not out or len(out) > limit:
        raise JarvisContractError(f"{name} missing or too long")
    if SECRET_PATTERN.search(out):
        raise JarvisContractError(f"{name} contains possible credentials")
    return out


def make_sync_intent(
    *,
    operation_id: str,
    device_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    expected_revision: int,
    authority: str = "user_confirmed",
) -> dict[str, Any]:
    """Build a requested mutation, NOT an applied mutation.

    The authoritative service must evaluate revision and idempotency before writing.
    A model prediction or assistant-only response cannot be the authority.
    """
    if authority not in {"user_confirmed", "provider_verified"}:
        raise JarvisContractError("authoritative user or provider evidence required")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        raise JarvisContractError("expected_revision must be a non-negative integer")
    return {
        "protocol_version": CONTRACT_VERSION,
        "operation_id": _text(operation_id, "operation_id", 128),
        "device_id": _text(device_id, "device_id", 128),
        "target": {
            "entity_type": _text(entity_type, "entity_type", 64),
            "entity_id": _text(entity_id, "entity_id", 256),
        },
        "action": _text(action, "action", 128),
        "expected_revision": expected_revision,
        "authority": authority,
        "status": "proposed",
    }


def check_sync_intent(
    intent: Mapping[str, Any],
    *,
    canonical_revision: int,
    applied_operation_ids: Iterable[str],
) -> dict[str, Any]:
    """Non-mutating sync preflight. Duplicate wins before stale-revision conflicts."""
    if intent.get("protocol_version") != CONTRACT_VERSION or intent.get("status") != "proposed":
        raise JarvisContractError("invalid intent protocol or status")
    op_id = _text(intent.get("operation_id"), "operation_id", 128)
    if not isinstance(canonical_revision, int) or canonical_revision < 0:
        raise JarvisContractError("invalid canonical revision")
    if op_id in set(applied_operation_ids):
        return {"status": "already_applied", "operation_id": op_id, "canonical_revision": canonical_revision}
    if intent.get("expected_revision") != canonical_revision:
        return {"status": "conflict", "operation_id": op_id, "canonical_revision": canonical_revision}
    if intent.get("authority") not in {"user_confirmed", "provider_verified"}:
        raise JarvisContractError("untrusted authority")
    if not isinstance(intent.get("target"), Mapping):
        raise JarvisContractError("missing target")
    _text(intent["target"].get("entity_id"), "entity_id", 256)
    return {"status": "ready_for_policy_check", "operation_id": op_id, "canonical_revision": canonical_revision}


def build_context_candidate(
    *,
    context_type: str,
    project_id: str,
    summary: str,
    source_kind: str,
    source_ref: str,
    user_authorized: bool,
    confirmed_by_user: bool = False,
    verified_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a private minimal summary; never read or save full chat automatically."""
    if not user_authorized:
        raise JarvisContractError("context capture requires user authorization")
    if context_type not in VALID_CONTEXT_TYPES:
        raise JarvisContractError("unsupported context type")
    if source_kind not in VALID_SOURCES:
        raise JarvisContractError("unsupported context source")
    if not confirmed_by_user and source_kind != "jarvis_verified_receipt":
        raise JarvisContractError("assistant interpretation is not a confirmed user fact")
    if source_kind == "jarvis_verified_receipt":
        if not isinstance(verified_receipt, Mapping):
            raise JarvisContractError("verified receipt is required")
        # 'accepted', 'started' and 'executed' are NOT proof of completion.
        verification = verified_receipt.get("verification")
        if verified_receipt.get("status") != "verified" or not isinstance(verification, Mapping) or (
            verification.get("status") not in {"verified", "passed"}
        ):
            raise JarvisContractError("verified receipt and postcondition are both required")
    cleaned = _text(summary, "summary", 2000)
    pointer = _text(source_ref, "source_ref", 1024)
    project = _text(project_id, "project_id", 256)
    if context_type == "handoff" and source_kind != "jarvis_verified_receipt" and not confirmed_by_user:
        raise JarvisContractError("handoff needs a confirmed user action or verified result")
    fingerprint = hashlib.sha256(
        (context_type + "\x00" + project + "\x00" + pointer + "\x00" + cleaned).encode("utf-8")
    ).hexdigest()
    return {
        "protocol_version": CONTRACT_VERSION,
        "record_type": "jarvis_context_candidate",
        "context_type": context_type,
        "project_id": project,
        "summary": cleaned,
        "source": {"kind": source_kind, "ref": pointer},
        "confirmed": bool(confirmed_by_user or source_kind == "jarvis_verified_receipt"),
        "epistemic_status": (
            "reported_hypothesis" if context_type == "hypothesis"
            else "provider_verified" if source_kind == "jarvis_verified_receipt"
            else "user_confirmed"
        ),
        "privacy": "private",
        "storage_status": "not_persisted",
        "fingerprint": fingerprint,
    }


def check_storage_policy(record: Mapping[str, Any], *, destination: str) -> dict[str, str]:
    """Never persist Jarvis memory/context to any public GitHub/web destination."""
    if record.get("record_type") != "jarvis_context_candidate" or record.get("privacy") != "private":
        raise JarvisContractError("unsupported or unclassified Jarvis data")
    if destination not in PRIVATE_STORAGE:
        raise JarvisContractError("private Jarvis context cannot be saved to this destination")
    if record.get("storage_status") != "not_persisted" or record.get("confirmed") is not True:
        raise JarvisContractError("record requires confirmed provenance and an original candidate")
    for field in ("summary", "project_id"):
        _text(record.get(field), field)
    source = record.get("source")
    if not isinstance(source, Mapping):
        raise JarvisContractError("missing source provenance")
    _text(source.get("ref"), "source_ref", 1024)
    return {"status": "approved_for_private_storage", "destination": destination}
