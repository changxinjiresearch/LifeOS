from __future__ import annotations

from typing import Any

from . import server_v11 as v11
from . import server_v6 as v6
from .cloud_classifier_v6 import classify_turn as classify_turn_v6


def _target_from_action_v12(action: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten action target mapping at the production composition root.

    Older phase composition used dynamic fall-through references to
    ``v6._target_from_action``. Once later phases replaced that same global, an
    ordinary task action could recurse through v11 -> v10 -> v9 -> v6 forever.
    Stage IV owns one explicit, non-recursive mapping for every currently
    supported canonical action family.
    """
    action = action or {}
    op = str(action.get("action") or "").strip()

    if op in {"create_project", "update_project_snapshot", "update_project", "delete_project"}:
        entity_id = action.get("project_id")
        return {"entity_type": "project", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op in {"create_task", "update_milestone", "complete_task", "delete_task"}:
        entity_id = action.get("task_id") or action.get("milestone_id")
        return {"entity_type": "task", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op == "set_deadline":
        entity_id = action.get("deadline_id")
        return {"entity_type": "deadline", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op in {"upsert_calendar_event", "remove_calendar_event"}:
        entity_id = action.get("calendar_event_id")
        return {"entity_type": "calendar_event", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op in {"add_note", "update_note", "remove_note"}:
        entity_id = action.get("note_id")
        return {"entity_type": "note", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op in {"add_resource", "update_resource", "remove_resource"}:
        entity_id = action.get("resource_id")
        return {"entity_type": "resource", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op in {"upsert_automation_rule", "remove_automation_rule"}:
        entity_id = action.get("rule_id")
        return {"entity_type": "automation_rule", **({"entity_id": str(entity_id)} if entity_id else {})}

    if op in {"upsert_agent_policy", "remove_agent_policy"}:
        entity_id = action.get("policy_id")
        return {"entity_type": "agent_policy", **({"entity_id": str(entity_id)} if entity_id else {})}

    return {"entity_type": "unknown"}


# Stage IV keeps the proven Stage III production app and replaces only the cloud
# turn classifier plus the target mapper used by candidate normalization.
v6.classify_turn = classify_turn_v6
v6._target_from_action = _target_from_action_v12

app = v11.app
mcp = v11.mcp
