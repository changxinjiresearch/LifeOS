#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state.json"
EVENTS = ROOT / "events" / "inbox"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "NextPlan-Agent-Poller/1.0",
    }
    response = httpx.get(
        f"https://api.github.com/repos/{repo}/commits",
        headers=headers,
        params={"sha": branch, "per_page": 30},
        timeout=30,
    )
    response.raise_for_status()
    commits = response.json()

    selected = None
    for item in commits:
        author_login = str((item.get("author") or {}).get("login") or "")
        message = str(((item.get("commit") or {}).get("message") or ""))
        if author_login.endswith("[bot]"):
            continue
        if message.startswith("NextPlan agent observation:"):
            continue
        selected = item
        break
    if not selected:
        print("No non-bot commit found; no signal emitted.")
        return 0

    sha = str(selected.get("sha") or "")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    cursor_key = f"github:{repo}:head"
    previous = str((state.get("agent_meta") or {}).get("provider_cursors", {}).get(cursor_key) or "")
    if sha and sha == previous:
        print(f"No meaningful GitHub head change: {sha[:12]}")
        return 0

    commit = selected.get("commit") or {}
    message = str(commit.get("message") or "").splitlines()[0][:240]
    author = commit.get("author") or {}
    signal_id = f"signal-github-head-{sha[:24]}"
    event_id = f"evt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-agent-github-head-{sha[:8]}"
    event = {
        "id": event_id,
        "at": now_iso(),
        "project_id": "project-item-daed6c",
        "type": "external_signal_recorded",
        "summary": f"Observed verified GitHub repository head change: {sha[:12]}",
        "source": {"kind": "automation", "via": "nextplan-agent-github-poll"},
        "external_signal": {
            "id": signal_id,
            "provider": "github",
            "event_type": "repo_head_changed",
            "provider_event_id": sha,
            "verified_source": True,
            "received_at": now_iso(),
            "project_id": "project-item-daed6c",
            "status": "observed",
            "payload": {
                "repository": repo,
                "head_sha": sha,
                "branch": branch,
                "message": message,
                "author_name": str(author.get("name") or "")[:120],
                "committed_at": str((commit.get("committer") or {}).get("date") or ""),
            },
        },
    }
    EVENTS.mkdir(parents=True, exist_ok=True)
    path = EVENTS / f"{event_id}.json"
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"NEXTPLAN_AGENT_SIGNAL={path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
