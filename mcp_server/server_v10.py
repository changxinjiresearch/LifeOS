from __future__ import annotations

from datetime import datetime
from typing import Any

from . import server_v9 as v9
from . import server_v6 as v6
from .cloud_classifier_v5 import classify_turn as classify_turn_v5
from .phase_d_engine import evaluate_automations, plan_state

base = v9.base
_LEGACY_EXECUTE = v9._phase_c_action
_LEGACY_APP = v9.app


def _target_from_action_v10(action: dict[str, Any] | None) -> dict[str, Any]:
    action = action or {}
    op = str(action.get("action", "")).strip()
    if op in {"upsert_automation_rule", "remove_automation_rule"}:
        rid = str(action.get("rule_id") or "").strip()
        return {"entity_type": "automation_rule", **({"entity_id": rid} if rid else {})}
    return v9._target_from_action_v9(action)


async def _phase_d_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "upsert_automation_rule":
        rid = str(payload.get("rule_id", "")).strip()
        if not rid:
            raise ValueError("rule_id is required")
        rule: dict[str, Any] = {"id": rid}
        if "enabled" in payload:
            rule["enabled"] = bool(payload.get("enabled"))
        if "threshold_days" in payload:
            rule["threshold_days"] = max(1, min(365, int(payload.get("threshold_days"))))
        if "weekday" in payload:
            rule["weekday"] = max(0, min(6, int(payload.get("weekday"))))
        if str(payload.get("name", "")).strip():
            rule["name"] = str(payload.get("name")).strip()
        event = {
            "type": "automation_rule_upserted",
            "project_id": "project-item-daed6c",
            "automation_rule": rule,
            "summary": f"Updated automation rule: {rid}",
        }
        result = await base._emit(event, via="nextplan-phase-d")
        return {**result, "automation_rule_id": rid, "summary": event["summary"]}

    if action == "remove_automation_rule":
        rid = str(payload.get("rule_id", "")).strip()
        if not rid:
            raise ValueError("rule_id is required")
        state = await base._state()
        if not any(str(r.get("id")) == rid for r in state.get("automation_rules", [])):
            return {"status": "already_absent", "automation_rule_id": rid, "summary": "Automation rule already absent"}
        event = {
            "type": "automation_rule_removed",
            "project_id": "project-item-daed6c",
            "automation_rule_id": rid,
            "summary": f"Removed automation rule override: {rid}",
        }
        result = await base._emit(event, via="nextplan-phase-d")
        return {**result, "automation_rule_id": rid, "summary": event["summary"]}

    return await _LEGACY_EXECUTE(payload)


v6._EXECUTE_ACTION = _phase_d_action
v6.classify_turn = classify_turn_v5
v6._target_from_action = _target_from_action_v10


def _parse_now(client: dict[str, Any]) -> datetime | None:
    raw = str(client.get("now") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def app(scope, receive, send):
    if scope.get("type") == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path in {"/extension/ai-plan", "/extension/automation/preview", "/extension/automation/run"} and method == "POST":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if not base.EXTENSION_TOKEN:
                return await base._send_json(send, 503, {"error": "extension_auth_not_configured"})
            if not v6._authorized(headers):
                return await base._send_json(send, 401, {"error": "unauthorized"})
            try:
                payload = await base._read_json_body(receive)
                client = payload.get("client") or {}
                now = _parse_now(client)
                state = await base._state()
                if path == "/extension/ai-plan":
                    return await base._send_json(send, 200, {"status": "ok", "plan": plan_state(state, now)})
                snapshot = evaluate_automations(state, now)
                if path == "/extension/automation/preview":
                    return await base._send_json(send, 200, {"status": "ok", "automation": snapshot})
                event = {
                    "type": "automation_snapshot_refreshed",
                    "project_id": "project-item-daed6c",
                    "automation_snapshot": snapshot,
                    "summary": f"Automation evaluation refreshed: {snapshot.get('finding_count', 0)} finding(s).",
                }
                result = await base._emit(event, via="nextplan-phase-d")
                return await base._send_json(send, 200, {"status": "ok", "automation": snapshot, "write": result})
            except ValueError as exc:
                return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except Exception as exc:
                return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})
    return await _LEGACY_APP(scope, receive, send)


mcp = base.mcp
