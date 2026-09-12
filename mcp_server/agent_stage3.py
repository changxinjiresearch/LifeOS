from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import hashlib
import json
import uuid

from .action_gateway_v1 import decide_permission, make_action_envelope, make_execution_receipt
from .connectors_v1 import ConnectorRegistry, ConnectorError


SENSITIVE_KEYS = {
    "authorization", "token", "access_token", "refresh_token", "password", "secret",
    "api_key", "apikey", "cookie", "set-cookie", "private_key", "credential",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).strip().lower() in SENSITIVE_KEYS:
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(x) for x in value]
    return value


def _stable_signal_id(provider: str, event_type: str, provider_event_id: str, payload: Dict[str, Any]) -> str:
    source = json.dumps(
        {"provider": provider, "event_type": event_type, "provider_event_id": provider_event_id, "payload": _redact(payload)},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "signal-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def normalize_external_signal(
    provider: str,
    event_type: str,
    payload: Dict[str, Any],
    *,
    provider_event_id: str = "",
    verified_source: bool = False,
    project_id: str = "",
) -> Dict[str, Any]:
    provider = provider.strip()
    event_type = event_type.strip()
    if not provider or not event_type:
        raise ValueError("provider and event_type are required")
    safe_payload = _redact(dict(payload or {}))
    sid = _stable_signal_id(provider, event_type, provider_event_id, safe_payload)
    return {
        "id": sid,
        "provider": provider,
        "event_type": event_type,
        "provider_event_id": provider_event_id or None,
        "verified_source": bool(verified_source),
        "received_at": now_iso(),
        "project_id": project_id or None,
        "payload": safe_payload,
        "status": "observed",
    }


def standing_policy_match(
    state: Dict[str, Any],
    *,
    provider: str,
    capability: str,
    project_id: str = "",
) -> Optional[Dict[str, Any]]:
    for policy in state.get("agent_policies", []):
        if not bool(policy.get("enabled", True)):
            continue
        if str(policy.get("kind") or "") != "standing_authorization":
            continue
        if str(policy.get("provider") or "") != provider:
            continue
        capabilities = policy.get("capabilities") or []
        if capability not in capabilities:
            continue
        policy_project = str(policy.get("project_id") or "")
        if policy_project and policy_project != project_id:
            continue
        return policy
    return None


def prepare_external_action(
    registry: ConnectorRegistry,
    state: Dict[str, Any],
    *,
    provider: str,
    capability: str,
    payload: Dict[str, Any],
    project_id: str = "",
    user_explicitly_requested: bool = False,
    explicit_confirmation: bool = False,
    dry_run: bool = False,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    connector = registry.get(provider)
    spec = connector.capability(capability)
    policy = standing_policy_match(state, provider=provider, capability=capability, project_id=project_id)
    permission = decide_permission(
        spec.risk_class,
        user_explicitly_requested=bool(user_explicitly_requested),
        explicit_confirmation=bool(explicit_confirmation),
        standing_policy_allows=policy is not None,
    )
    envelope = make_action_envelope(
        provider,
        capability,
        spec.risk_class,
        _redact(dict(payload or {})),
        dry_run=dry_run,
        standing_policy_id=str(policy.get("id")) if policy else None,
        idempotency_key=idempotency_key or None,
    )
    return {
        "agent_protocol_version": "1.0",
        "project_id": project_id or None,
        "capability": {
            "provider": provider,
            "name": capability,
            "risk_class": spec.risk_class,
            "rollback_supported": bool(spec.rollback_supported),
            "description": spec.description,
        },
        "permission": permission,
        "standing_policy": _redact(policy) if policy else None,
        "envelope": envelope,
    }


async def execute_external_action(
    registry: ConnectorRegistry,
    state: Dict[str, Any],
    *,
    provider: str,
    capability: str,
    payload: Dict[str, Any],
    project_id: str = "",
    user_explicitly_requested: bool = False,
    explicit_confirmation: bool = False,
    dry_run: bool = False,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    plan = prepare_external_action(
        registry,
        state,
        provider=provider,
        capability=capability,
        payload=payload,
        project_id=project_id,
        user_explicitly_requested=user_explicitly_requested,
        explicit_confirmation=explicit_confirmation,
        dry_run=dry_run,
        idempotency_key=idempotency_key,
    )
    permission = plan["permission"]
    envelope = plan["envelope"]
    spec = plan["capability"]

    if dry_run:
        return {
            "status": "preview",
            "plan": plan,
            "receipt": make_execution_receipt(
                envelope,
                status="preview",
                verified=False,
                summary="Dry-run only; no provider action executed.",
                rollback_supported=bool(spec["rollback_supported"]),
            ),
        }

    if not permission.get("allowed"):
        return {
            "status": "needs_confirmation" if permission.get("requires_confirmation") else "rejected",
            "plan": plan,
            "receipt": make_execution_receipt(
                envelope,
                status="needs_confirmation" if permission.get("requires_confirmation") else "rejected",
                verified=False,
                summary=str(permission.get("reason") or "Permission denied"),
                rollback_supported=bool(spec["rollback_supported"]),
            ),
        }

    connector = registry.get(provider)
    result = await connector.execute(capability, dict(payload or {}))
    verification = await connector.verify(capability, dict(payload or {}), result)
    verified = bool(verification.get("verified"))
    receipt = make_execution_receipt(
        envelope,
        status="verified" if verified else "executed_unverified",
        provider_result_id=str(result.get("provider_result_id") or "") or None,
        verified=verified,
        summary=("Provider action executed and verified." if verified else "Provider action executed but verification did not pass."),
        rollback_supported=bool(spec["rollback_supported"]),
    )
    receipt["at"] = now_iso()
    receipt["project_id"] = project_id or None
    receipt["verification"] = _redact(verification)
    receipt["provider_result"] = _redact({k: v for k, v in result.items() if k not in {"previous", "content"}})
    # Rollback metadata is retained only in the immediate server response, not intended for canonical state.
    return {
        "status": receipt["status"],
        "plan": plan,
        "receipt": receipt,
        "_rollback_result": result,
    }


async def rollback_external_action(
    registry: ConnectorRegistry,
    *,
    provider: str,
    capability: str,
    payload: Dict[str, Any],
    execution_result: Dict[str, Any],
    explicit_confirmation: bool,
) -> Dict[str, Any]:
    if not explicit_confirmation:
        return {"status": "needs_confirmation", "verified": False, "summary": "Rollback requires explicit confirmation."}
    connector = registry.get(provider)
    spec = connector.capability(capability)
    if not spec.rollback_supported:
        return {"status": "rollback_not_supported", "verified": False, "summary": "Connector does not support rollback for this capability."}
    result = await connector.rollback(capability, dict(payload or {}), execution_result)
    return _redact(result)


def make_reconciliation(
    *,
    signal_id: str = "",
    action_id: str = "",
    project_id: str = "",
    summary: str,
    verified: bool,
    canonical_changes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not verified:
        raise ValueError("Unverified external results cannot be reconciled into canonical truth")
    return {
        "id": f"reconcile-{uuid.uuid4()}",
        "signal_id": signal_id or None,
        "action_id": action_id or None,
        "project_id": project_id or None,
        "verified": True,
        "summary": summary.strip(),
        "canonical_changes": _redact(canonical_changes or {}),
        "at": now_iso(),
    }


def evaluate_proactive_policies(state: Dict[str, Any], now: Optional[datetime] = None) -> list[Dict[str, Any]]:
    """Return bounded proposed actions. This function never executes them."""
    now = now or datetime.now(timezone.utc)
    proposals: list[Dict[str, Any]] = []

    for finding in state.get("automation_feed", []):
        rule_id = str(finding.get("rule_id") or "")
        project_id = str(finding.get("project_id") or "")
        if rule_id == "waiting-followup":
            proposals.append({
                "id": f"proposal-followup-{project_id or finding.get('id')}",
                "policy": "draft-waiting-followup",
                "project_id": project_id or None,
                "risk_class": "read_only",
                "action": "prepare_followup_draft",
                "reason": finding.get("reason"),
                "requires_external_write": False,
            })
        elif rule_id == "preparation-window":
            proposals.append({
                "id": f"proposal-prep-{project_id or finding.get('id')}",
                "policy": "prepare-upcoming-commitment",
                "project_id": project_id or None,
                "risk_class": "read_only",
                "action": "prepare_commitment_plan",
                "reason": finding.get("reason"),
                "requires_external_write": False,
            })
        elif rule_id == "stale-active":
            proposals.append({
                "id": f"proposal-stale-{project_id or finding.get('id')}",
                "policy": "review-stale-project",
                "project_id": project_id or None,
                "risk_class": "read_only",
                "action": "review_project_state",
                "reason": finding.get("reason"),
                "requires_external_write": False,
            })

    for policy in state.get("agent_policies", []):
        if not bool(policy.get("enabled", True)) or str(policy.get("kind") or "") != "proactive":
            continue
        proposals.append({
            "id": f"proposal-policy-{policy.get('id')}",
            "policy": policy.get("id"),
            "project_id": policy.get("project_id"),
            "provider": policy.get("provider"),
            "capability": policy.get("capability"),
            "risk_class": policy.get("risk_class") or "read_only",
            "action": policy.get("action") or policy.get("capability"),
            "reason": policy.get("reason") or "Standing proactive policy is enabled.",
            "requires_external_write": (policy.get("risk_class") or "read_only") != "read_only",
        })

    return proposals[:100]
