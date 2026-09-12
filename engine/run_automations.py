#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.phase_d_engine import evaluate_automations  # noqa: E402

STATE = ROOT / "state.json"
INBOX = ROOT / "events" / "inbox"


def main() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot = evaluate_automations(state, now)
    event_id = f"evt-{now.strftime('%Y%m%d')}-automation-daily"
    path = INBOX / f"{event_id}.json"
    if path.exists():
        print(json.dumps({"status": "already_ran_today", "event_id": event_id}))
        return
    event = {
        "id": event_id,
        "at": now.isoformat().replace("+00:00", "Z"),
        "type": "automation_snapshot_refreshed",
        "project_id": "project-item-daed6c",
        "summary": f"Daily automation evaluation: {snapshot.get('finding_count', 0)} finding(s).",
        "automation_snapshot": snapshot,
        "source": {"kind": "automation", "via": "github-actions-daily"},
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "created", "event_id": event_id, "findings": snapshot.get("finding_count", 0)}))


if __name__ == "__main__":
    main()
