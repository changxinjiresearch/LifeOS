from __future__ import annotations

from typing import Any

from .cloud_classifier import classify_turn as legacy_classify_turn
from .conversation_capture import capture_conversational_fact


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Stage IV classifier composition.

    Ordinary, high-confidence user facts are evaluated before the legacy explicit
    command classifier. Explicit NextPlan commands deliberately fall through to
    legacy behavior so Stage I-III command semantics remain stable.
    """
    captured = capture_conversational_fact(turn, state)
    if captured is not None:
        return captured
    return legacy_classify_turn(turn, state, client or {})
