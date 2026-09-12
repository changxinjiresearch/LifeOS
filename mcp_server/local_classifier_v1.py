from __future__ import annotations

from typing import Any

from .cloud_classifier_v6 import classify_turn as classify_existing_state
from .project_intelligence_v1 import discover_project_change


def classify_local_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Local v0.1 conversational intelligence composition.

    Proven Stage IV existing-entity/state capture has priority. If no existing
    state change or explicit command is found, Stage 5 may propose a new project
    or project-growth change. New structure is confirm-first by default.
    """
    existing = classify_existing_state(turn, state, client or {})
    if existing is not None:
        return existing
    return discover_project_change(turn, state)
