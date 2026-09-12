from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class PairingSession:
    code: str
    expires_at: float
    used: bool = False


class LocalPairingManager:
    """In-memory one-time pairing for the local browser bridge.

    The pairing code is intentionally never exposed by an unauthenticated HTTP
    endpoint. The future Desktop shell will display the code to the local user;
    Stage 4 tests call ``issue_code`` directly to model that trusted surface.
    """

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = max(30, int(ttl_seconds))
        self._session: PairingSession | None = None

    def issue_code(self) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._session = PairingSession(code=code, expires_at=time.time() + self.ttl_seconds)
        return code

    def consume(self, code: str) -> bool:
        session = self._session
        if not session or session.used or time.time() > session.expires_at:
            return False
        if not secrets.compare_digest(str(code).strip(), session.code):
            return False
        session.used = True
        return True

    def status(self) -> dict[str, Any]:
        session = self._session
        return {
            "active": bool(session and not session.used and time.time() <= session.expires_at),
            "expires_in_seconds": max(0, int(session.expires_at - time.time())) if session else 0,
        }
