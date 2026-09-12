from __future__ import annotations

from typing import Any

from .cloud_classifier_v6 import classify_turn as classify_existing_state
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
    """Local v0.1 conversational intelligence composition.

    Proven Stage IV existing-entity/state capture has priority. If no existing
    state change or explicit command is found, Stage 5 may propose a new project
    or project-growth change. User evidence is propagated into structured local
    actions so the canonical event can retain provenance without trusting the
    assistant as factual authority.
    """
    existing = classify_existing_state(turn, state, client or {})
    if existing is not None:
        return _attach_action_provenance(existing)
    return _attach_action_provenance(discover_project_change(turn, state))
