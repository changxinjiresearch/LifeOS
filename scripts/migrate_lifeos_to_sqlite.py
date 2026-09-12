#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.local_projector import semantic_projection
from mcp_server.storage_v1 import SQLiteCanonicalStore


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_events(event_dir: Path) -> list[dict]:
    if not event_dir.exists():
        return []
    events: list[dict] = []
    for path in sorted(event_dir.glob("*.json")):
        event = load_json(path)
        if isinstance(event, dict) and event.get("id"):
            events.append(event)
    return events


def migrate(state_path: Path, event_dir: Path, db_path: Path) -> dict:
    source = load_json(state_path)
    events = load_events(event_dir)
    store = SQLiteCanonicalStore(db_path)
    store.bootstrap_state(source, events)
    migrated = store.get_state()

    source_semantics = semantic_projection(source)
    migrated_semantics = semantic_projection(migrated)
    if source_semantics != migrated_semantics:
        raise RuntimeError("semantic parity check failed after SQLite bootstrap")

    return {
        "status": "PASS",
        "db": str(db_path),
        "projects": len(migrated.get("projects", [])),
        "imported_events": len(events),
        "activity_rows": len(store.list_activity(1000)),
        "semantic_parity": True,
        "canonical_store": migrated.get("system", {}).get("canonical_store"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate LifeOS canonical state to NextPlan Local SQLite")
    parser.add_argument("--state", type=Path, default=ROOT / "state.json")
    parser.add_argument("--events", type=Path, default=ROOT / "events" / "inbox")
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.state, args.events, args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
