from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from . import server_v10 as v10
from . import server_v6 as v6
from .agent_stage3 import (
    evaluate_proactive_policies,
    execute_external_action,
    make_reconciliation,
    normalize_external_signal,
    prepare_external_action,
    rollback_external_action,
)
from .connectors_v1 import ConnectorRegistry, GitHubConnector, ConnectorError

base = v10.base
_LEGACY_EXECUTE = v10._phase_d_action
_LEGACY_APP = v10.app


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(GitHubConnector(base.GITHUB_TOKEN, base.REPO, base.BRANCH))
    return registry


def _target_from_action_v11(action: dict[str, Any] | None) -> dict[str, Any]:
    action = action or {}
    op = str(action.get("action", "")).strip()
    if op in {"upsert_agent_policy", "remove_agent_policy"}:
        pid = str(action.get("policy_id") or "").strip()
        return {"entity_type": "agent_policy", **({"entity_id": pid} if pid else {})}
    return v10._target_from_action_v10(action)


async def _stage3_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "upsert_agent_policy":
        pid = str(payload.get("policy_id") or "").strip()
        if not pid:
            raise ValueError("policy_id is required")
        kind = str(payload.get("kind") or "proactive").strip()
        if kind not in {"proactive", "standing_authorization"}:
            raise ValueError("kind must be proactive or standing_authorization")
        policy: dict[str, Any] = {
            "id": pid,
            "kind": kind,
            "enabled": bool(payload.get("enabled", True)),
        }
        for key in ("name", "provider", "capability", "project_id", "risk_class", "action", "reason"):
            value = str(payload.get(key) or "").strip()
            if value:
                policy[key] = value
        if isinstance(payload.get("capabilities"), list):
            policy["capabilities"] = [str(x).strip() for x in payload["capabilities"] if str(x).strip()][:30]
        event = {
            "type": "agent_policy_upserted",
            "project_id": str(payload.get("project_id") or "project-item-daed6c"),
            "agent_policy": policy,
            "summary": f"Updated agent policy: {pid}",
        }
        result = await base._emit(event, via="nextplan-agent-stage3")
        return {**result, "agent_policy_id": pid, "summary": event["summary"]}

    if action == "remove_agent_policy":
        pid = str(payload.get("policy_id") or "").strip()
        if not pid:
            raise ValueError("policy_id is required")
        state = await base._state()
        if not any(str(p.get("id")) == pid for p in state.get("agent_policies", [])):
            return {"status": "already_absent", "agent_policy_id": pid, "summary": "Agent policy already absent"}
        event = {
            "type": "agent_policy_removed",
            "project_id": "project-item-daed6c",
            "agent_policy_id": pid,
            "summary": f"Removed agent policy: {pid}",
        }
        result = await base._emit(event, via="nextplan-agent-stage3")
        return {**result, "agent_policy_id": pid, "summary": event["summary"]}

    return await _LEGACY_EXECUTE(payload)


v6._EXECUTE_ACTION = _stage3_action
v6._target_from_action = _target_from_action_v11


async def _authenticated_payload(scope, receive, send):
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    if not base.EXTENSION_TOKEN:
        await base._send_json(send, 503, {"error": "extension_auth_not_configured"})
        return None
    if not v6._authorized(headers):
        await base._send_json(send, 401, {"error": "unauthorized"})
        return None
    return await base._read_json_body(receive)


def _find_verified_idempotent_action(state: dict[str, Any], provider: str, capability: str, key: str) -> dict[str, Any] | None:
    if not key:
        return None
    for receipt in reversed(state.get("agent_actions", [])):
        if (
            str(receipt.get("provider") or "") == provider
            and str(receipt.get("capability") or "") == capability
            and str(receipt.get("idempotency_key") or "") == key
            and bool(receipt.get("verified"))
        ):
            return receipt
    return None


async def _record_action(receipt: dict[str, Any], project_id: str = "") -> dict[str, Any]:
    action_id = str(receipt.get("action_id") or f"act-{uuid.uuid4()}")
    event = {
        "type": "agent_action_recorded",
        "project_id": project_id or str(receipt.get("project_id") or "project-item-daed6c"),
        "agent_action": {**receipt, "id": action_id},
        "summary": f"Agent action {receipt.get('provider')}:{receipt.get('capability')} -> {receipt.get('status')}",
    }
    return await base._emit(event, via="nextplan-agent-stage3")


async def _record_reconciliation(reconciliation: dict[str, Any]) -> dict[str, Any]:
    event = {
        "type": "agent_reconciliation_recorded",
        "project_id": str(reconciliation.get("project_id") or "project-item-daed6c"),
        "agent_reconciliation": reconciliation,
        "summary": str(reconciliation.get("summary") or "Verified external result reconciled"),
    }
    return await base._emit(event, via="nextplan-agent-stage3")


async def _record_run(run: dict[str, Any]) -> dict[str, Any]:
    event = {
        "type": "agent_run_recorded",
        "project_id": str(run.get("project_id") or "project-item-daed6c"),
        "agent_run": run,
        "summary": str(run.get("summary") or f"Agent run {run.get('id')} -> {run.get('status')}"),
    }
    return await base._emit(event, via="nextplan-agent-stage3")


async def app(scope, receive, send):
    if scope.get("type") == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        agent_paths = {
            "/extension/agent/capabilities",
            "/extension/agent/preview",
            "/extension/agent/execute",
            "/extension/agent/rollback",
            "/extension/agent/trigger",
            "/extension/agent/reconcile",
            "/extension/agent/run",
            "/extension/agent/policies/evaluate",
        }
        if path in agent_paths and method == "POST":
            try:
                payload = await _authenticated_payload(scope, receive, send)
                if payload is None:
                    return
                state = await base._state()
                registry = _registry()

                if path == "/extension/agent/capabilities":
                    return await base._send_json(send, 200, {"status": "ok", "connectors": registry.describe()})

                if path == "/extension/agent/policies/evaluate":
                    return await base._send_json(send, 200, {"status": "ok", "proposals": evaluate_proactive_policies(state)})

                if path == "/extension/agent/trigger":
                    signal = normalize_external_signal(
                        str(payload.get("provider") or ""),
                        str(payload.get("event_type") or ""),
                        dict(payload.get("payload") or {}),
                        provider_event_id=str(payload.get("provider_event_id") or ""),
                        verified_source=bool(payload.get("verified_source", False)),
                        project_id=str(payload.get("project_id") or ""),
                    )
                    existing = next((s for s in state.get("external_signals", []) if s.get("id") == signal["id"]), None)
                    if existing:
                        return await base._send_json(send, 200, {"status": "already_exists", "signal": existing})
                    event = {
                        "type": "external_signal_recorded",
                        "project_id": str(signal.get("project_id") or "project-item-daed6c"),
                        "external_signal": signal,
                        "summary": f"External signal: {signal.get('provider')} {signal.get('event_type')}",
                    }
                    write = await base._emit(event, via="nextplan-agent-stage3")
                    return await base._send_json(send, 200, {"status": "recorded", "signal": signal, "write": write})

                if path == "/extension/agent/run":
                    status = str(payload.get("status") or "completed").strip().lower()
                    if status not in {"started", "completed", "failed", "partial"}:
                        raise ValueError("status must be started, completed, failed, or partial")
                    project_id = str(payload.get("project_id") or "").strip()
                    action_ids = [str(x).strip() for x in (payload.get("action_ids") or []) if str(x).strip()][:100]
                    reconciliation_ids = [str(x).strip() for x in (payload.get("reconciliation_ids") or []) if str(x).strip()][:100]
                    signal_ids = [str(x).strip() for x in (payload.get("signal_ids") or []) if str(x).strip()][:100]
                    run = {
                        "id": str(payload.get("run_id") or f"run-{uuid.uuid4()}"),
                        "project_id": project_id or None,
                        "status": status,
                        "verified": bool(payload.get("verified", False)),
                        "signal_ids": signal_ids,
                        "action_ids": action_ids,
                        "reconciliation_ids": reconciliation_ids,
                        "summary": str(payload.get("summary") or f"Stage III agent run {status}").strip()[:500],
                        "at": _now_iso(),
                    }
                    write = await _record_run(run)
                    return await base._send_json(send, 200, {"status": "recorded", "run": run, "write": write})

                provider = str(payload.get("provider") or "").strip()
                capability = str(payload.get("capability") or "").strip()
                action_payload = dict(payload.get("payload") or {})
                project_id = str(payload.get("project_id") or "").strip()
                explicit_request = bool(payload.get("user_explicitly_requested", False))
                explicit_confirmation = bool(payload.get("explicit_confirmation", False))
                idempotency_key = str(payload.get("idempotency_key") or "").strip()

                if path == "/extension/agent/preview":
                    plan = prepare_external_action(
                        registry,
                        state,
                        provider=provider,
                        capability=capability,
                        payload=action_payload,
                        project_id=project_id,
                        user_explicitly_requested=explicit_request,
                        explicit_confirmation=explicit_confirmation,
                        dry_run=True,
                        idempotency_key=idempotency_key,
                    )
                    return await base._send_json(send, 200, {"status": "preview", "plan": plan})

                if path == "/extension/agent/execute":
                    if idempotency_key:
                        previous = _find_verified_idempotent_action(state, provider, capability, idempotency_key)
                        if previous:
                            return await base._send_json(send, 200, {"status": "already_applied", "receipt": previous})
                    execution = await execute_external_action(
                        registry,
                        state,
                        provider=provider,
                        capability=capability,
                        payload=action_payload,
                        project_id=project_id,
                        user_explicitly_requested=explicit_request,
                        explicit_confirmation=explicit_confirmation,
                        dry_run=bool(payload.get("dry_run", False)),
                        idempotency_key=idempotency_key,
                    )
                    receipt = execution.get("receipt") or {}
                    if execution.get("status") in {"needs_confirmation", "rejected", "preview"}:
                        status_code = 409 if execution.get("status") == "needs_confirmation" else 200
                        return await base._send_json(send, status_code, {k: v for k, v in execution.items() if not str(k).startswith("_")})

                    write = await _record_action(receipt, project_id)
                    response: dict[str, Any] = {"status": execution.get("status"), "receipt": receipt, "write": write}

                    reconcile = payload.get("reconcile")
                    if reconcile and bool(receipt.get("verified")):
                        reconcile = dict(reconcile)
                        canonical_changes = dict(reconcile.get("canonical_changes") or {})
                        if canonical_changes and not explicit_confirmation:
                            response["reconciliation"] = {"status": "needs_confirmation", "reason": "Canonical project changes require explicit confirmation."}
                        else:
                            rec = make_reconciliation(
                                action_id=str(receipt.get("action_id") or ""),
                                project_id=project_id,
                                summary=str(reconcile.get("summary") or receipt.get("summary") or "Verified external action"),
                                verified=True,
                                canonical_changes=canonical_changes,
                            )
                            rec_write = await _record_reconciliation(rec)
                            response["reconciliation"] = {"status": "recorded", "record": rec, "write": rec_write}
                            if canonical_changes and project_id:
                                allowed = {k: v for k, v in canonical_changes.items() if k in {"status", "next_action", "priority"}}
                                if allowed:
                                    project_event = {
                                        "type": "project_updated",
                                        "project_id": project_id,
                                        "changes": allowed,
                                        "summary": f"Applied verified agent reconciliation to project: {project_id}",
                                    }
                                    response["project_write"] = await base._emit(project_event, via="nextplan-agent-reconciliation")
                    return await base._send_json(send, 200, response)

                if path == "/extension/agent/rollback":
                    action_id = str(payload.get("action_id") or "").strip()
                    receipt = next((a for a in state.get("agent_actions", []) if str(a.get("action_id") or a.get("id") or "") == action_id), None)
                    if not receipt:
                        return await base._send_json(send, 404, {"error": "unknown_agent_action"})
                    provider = str(receipt.get("provider") or "")
                    capability = str(receipt.get("capability") or "")
                    provider_result = dict(receipt.get("provider_result") or {})
                    rollback_payload: dict[str, Any] = {}
                    if provider == "github" and capability == "file.create":
                        rollback_payload["path"] = provider_result.get("path")
                    elif provider == "github" and capability == "issue.create":
                        provider_result["issue_number"] = provider_result.get("issue_number") or receipt.get("provider_result_id")
                    result = await rollback_external_action(
                        registry,
                        provider=provider,
                        capability=capability,
                        payload=rollback_payload,
                        execution_result=provider_result,
                        explicit_confirmation=bool(payload.get("explicit_confirmation", False)),
                    )
                    rollback_receipt = {
                        "id": f"rollback-{uuid.uuid4()}",
                        "action_id": f"rollback-{action_id}",
                        "provider": provider,
                        "capability": f"rollback:{capability}",
                        "risk_class": "reversible_write",
                        "status": result.get("status"),
                        "verified": bool(result.get("verified")),
                        "rollback_of": action_id,
                        "provider_result": result,
                        "summary": f"Rollback of {action_id}: {result.get('status')}",
                    }
                    write = await _record_action(rollback_receipt, str(receipt.get("project_id") or ""))
                    return await base._send_json(send, 200, {"status": result.get("status"), "receipt": rollback_receipt, "write": write})

                if path == "/extension/agent/reconcile":
                    verified = bool(payload.get("verified", False))
                    canonical_changes = dict(payload.get("canonical_changes") or {})
                    if canonical_changes and not explicit_confirmation:
                        return await base._send_json(send, 409, {"status": "needs_confirmation", "reason": "Canonical project changes require explicit confirmation."})
                    rec = make_reconciliation(
                        signal_id=str(payload.get("signal_id") or ""),
                        action_id=str(payload.get("action_id") or ""),
                        project_id=project_id,
                        summary=str(payload.get("summary") or "Verified external result reconciled"),
                        verified=verified,
                        canonical_changes=canonical_changes,
                    )
                    write = await _record_reconciliation(rec)
                    response: dict[str, Any] = {"status": "recorded", "reconciliation": rec, "write": write}
                    if canonical_changes and project_id:
                        allowed = {k: v for k, v in canonical_changes.items() if k in {"status", "next_action", "priority"}}
                        if allowed:
                            response["project_write"] = await base._emit({
                                "type": "project_updated",
                                "project_id": project_id,
                                "changes": allowed,
                                "summary": f"Applied verified reconciliation to project: {project_id}",
                            }, via="nextplan-agent-reconciliation")
                    return await base._send_json(send, 200, response)

            except (ValueError, ConnectorError) as exc:
                return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except Exception as exc:
                return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})

    return await _LEGACY_APP(scope, receive, send)


mcp = base.mcp
