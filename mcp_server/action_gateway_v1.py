"""NextPlan Action Gateway v1.

Cloud-side policy layer for permissioned external side effects.
Stage III milestone 13 foundation.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional
import hashlib
import json
import uuid


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    CONSEQUENTIAL_WRITE = "consequential_write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str


@dataclass(frozen=True)
class ActionEnvelope:
    action_id: str
    provider: str
    capability: str
    risk_class: str
    payload: Dict[str, Any]
    idempotency_key: str
    dry_run: bool = False
    standing_policy_id: Optional[str] = None


def _stable_payload_hash(provider: str, capability: str, payload: Dict[str, Any]) -> str:
    encoded = json.dumps(
        {"provider": provider, "capability": capability, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def make_action_envelope(
    provider: str,
    capability: str,
    risk_class: str,
    payload: Dict[str, Any],
    *,
    dry_run: bool = False,
    standing_policy_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a normalized external-action envelope.

    The caller may supply an idempotency key from an upstream operation; otherwise
    a deterministic key is derived from provider/capability/payload.
    """
    risk = RiskClass(risk_class)
    env = ActionEnvelope(
        action_id=f"act-{uuid.uuid4()}",
        provider=provider.strip(),
        capability=capability.strip(),
        risk_class=risk.value,
        payload=dict(payload or {}),
        idempotency_key=idempotency_key or _stable_payload_hash(provider, capability, payload or {}),
        dry_run=bool(dry_run),
        standing_policy_id=standing_policy_id,
    )
    return asdict(env)


def decide_permission(
    risk_class: str,
    *,
    user_explicitly_requested: bool,
    explicit_confirmation: bool = False,
    standing_policy_allows: bool = False,
) -> Dict[str, Any]:
    """Apply Stage III v1 permission policy without performing the action."""
    risk = RiskClass(risk_class)

    if risk is RiskClass.READ_ONLY:
        if user_explicitly_requested or standing_policy_allows:
            decision = PermissionDecision(True, False, "Read-only action is within an explicit request/policy.")
        else:
            decision = PermissionDecision(False, True, "Read-only action lacks an explicit request or standing policy.")

    elif risk is RiskClass.REVERSIBLE_WRITE:
        if explicit_confirmation:
            decision = PermissionDecision(True, False, "Reversible write explicitly confirmed.")
        elif standing_policy_allows:
            decision = PermissionDecision(True, False, "Reversible write is covered by a standing authorization.")
        else:
            decision = PermissionDecision(False, True, "Reversible write requires confirmation or a standing authorization.")

    elif risk is RiskClass.CONSEQUENTIAL_WRITE:
        if explicit_confirmation:
            decision = PermissionDecision(True, False, "Consequential write explicitly confirmed.")
        elif standing_policy_allows:
            decision = PermissionDecision(True, False, "Consequential write is covered by a narrowly scoped standing authorization.")
        else:
            decision = PermissionDecision(False, True, "Consequential write requires explicit confirmation.")

    else:  # destructive / irreversible
        if explicit_confirmation:
            decision = PermissionDecision(True, False, "Destructive/irreversible action explicitly confirmed for this execution.")
        else:
            decision = PermissionDecision(False, True, "Destructive/irreversible actions always require explicit confirmation.")

    return asdict(decision)


def make_execution_receipt(
    envelope: Dict[str, Any],
    *,
    status: str,
    provider_result_id: Optional[str] = None,
    verified: bool = False,
    summary: str = "",
    rollback_supported: bool = False,
) -> Dict[str, Any]:
    return {
        "receipt_version": "agent-action-1.0",
        "action_id": envelope.get("action_id"),
        "provider": envelope.get("provider"),
        "capability": envelope.get("capability"),
        "risk_class": envelope.get("risk_class"),
        "idempotency_key": envelope.get("idempotency_key"),
        "status": status,
        "provider_result_id": provider_result_id,
        "verified": bool(verified),
        "rollback_supported": bool(rollback_supported),
        "summary": summary,
    }
