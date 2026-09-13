from __future__ import annotations

from typing import Any

from .cloud_classifier_v6 import classify_turn as classify_existing_state
from .local_command_compat_v1 import classify_compat_command, normalize_turn
from .project_intelligence_v1 import discover_project_change


def _attach_action_provenance(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    value = dict(candidate)
    action = value.get("action")
    if isinstance(action, dict):
        action = dict(action)
        cid = str(value.get("id") or "").strip()
        if cid:
            action.setdefault("operation_id", cid)
        provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
        if provenance.get("evidenceText"):
            action.setdefault("evidence_text", str(provenance["evidenceText"])[:500])
        value["action"] = action
    return value


def classify_local_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Local conversational intelligence composition.

    Explicit compatibility commands are resolved before the historic classifier,
    then normal existing-state and project-growth logic run unchanged.
    """
    normalized_turn = normalize_turn(turn)
    compat = classify_compat_command(normalized_turn, state)
    if compat is not None:
        return _attach_action_provenance(compat)
    existing = classify_existing_state(normalized_turn, state, client or {})
    if existing is not None:
        return _attach_action_provenance(existing)
    return _attach_action_provenance(discover_project_change(normalized_turn, state))
