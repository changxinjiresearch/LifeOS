from __future__ import annotations

from typing import Any

from .cloud_classifier_v5 import classify_turn as classify_explicit_and_contextual
from .conversation_capture import capture_conversational_fact


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Stage IV+ classifier composition.

    Ordinary, high-confidence conversational facts are evaluated first. Explicit
    NextPlan commands then flow through the full v5 classifier chain so local and
    cloud runtimes retain Calendar/Deadline, Notes/Resources, Automation, entity
    resolution, and legacy project/task semantics.
    """
    captured = capture_conversational_fact(turn, state)
    if captured is not None:
        return captured
    return classify_explicit_and_contextual(turn, state, client or {})
