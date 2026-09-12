from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_actions_v2 import execute_action as execute_action_v2
from .storage_v1 import CanonicalStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _event(kind: str, summary: str, **payload: Any) -> dict[str, Any]:
    return {
        "id": f"evt-local-{kind}-{uuid.uuid4().hex}",
        "at": _now_iso(),
        "type": kind,
        "summary": summary,
        "source": {"kind": "local", "via": "nextplan-local-core-v3"},
        **payload,
    }


def _project(state: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    return next((p for p in state.get("projects", []) if str(p.get("id")) == project_id), None)


def _milestone(project: dict[str, Any], milestone_id: str) -> dict[str, Any] | None:
    return next((m for m in project.get("milestones", []) if str(m.get("id")) == milestone_id), None)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def execute_action(store: CanonicalStore, action: dict[str, Any]) -> dict[str, Any]:
    op = str(action.get("action") or "").strip()
    if op not in {"bind_workspace", "unbind_workspace", "attach_artifact", "verify_artifact", "remove_artifact", "update_local_permissions"}:
        return execute_action_v2(store, action)

    state = store.get_state()

    if op == "bind_workspace":
        pid = str(action.get("project_id") or "").strip()
        project = _project(state, pid)
        if not project:
            raise ValueError(f"Unknown project_id: {pid}")
        path = Path(str(action.get("path") or "")).expanduser()
        if not path.is_absolute():
            raise ValueError("workspace path must be absolute")
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError("workspace directory does not exist")
        binding = {
            "project_id": pid,
            "path": str(resolved),
            "label": str(action.get("label") or project.get("name") or resolved.name),
            "authorized": True,
            "bound_at": _now_iso(),
        }
        result = store.append_event(_event("workspace_bound", f"Bound workspace for {project.get('name', pid)}", project_id=pid, binding=binding))
        return {"status": result["status"], "project_id": pid, "binding": binding, "event_id": result["event_id"]}

    if op == "unbind_workspace":
        pid = str(action.get("project_id") or "").strip()
        result = store.append_event(_event("workspace_unbound", f"Unbound workspace: {pid}", project_id=pid))
        return {"status": result["status"], "project_id": pid, "event_id": result["event_id"]}

    if op == "attach_artifact":
        pid = str(action.get("project_id") or "").strip()
        project = _project(state, pid)
        if not project:
            raise ValueError(f"Unknown project_id: {pid}")
        milestone_id = str(action.get("milestone_id") or action.get("task_id") or "").strip()
        if milestone_id and not _milestone(project, milestone_id):
            raise ValueError(f"Unknown milestone_id {milestone_id} in {pid}")
        path = Path(str(action.get("path") or "")).expanduser()
        if not path.is_absolute():
            raise ValueError("artifact path must be absolute")
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_file():
            raise ValueError("artifact file does not exist")
        stat = resolved.stat()
        aid = str(action.get("artifact_id") or "").strip() or f"artifact-{uuid.uuid4().hex[:12]}"
        artifact = {
            "id": aid,
            "project_id": pid,
            "milestone_id": milestone_id or None,
            "path": str(resolved),
            "display_name": str(action.get("display_name") or resolved.name),
            "mime_type": mimetypes.guess_type(str(resolved))[0] or "application/octet-stream",
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sha256": _sha256(resolved),
            "availability": "available",
            "verification_status": "verified",
            "authorization_scope": "explicit_artifact",
            "attached_at": _now_iso(),
        }
        result = store.append_event(_event("artifact_attached", f"Attached artifact: {artifact['display_name']}", project_id=pid, artifact=artifact))
        return {"status": result["status"], "artifact": artifact, "event_id": result["event_id"]}

    if op == "verify_artifact":
        aid = str(action.get("artifact_id") or "").strip()
        artifact = next((a for a in state.get("artifacts", []) if str(a.get("id")) == aid), None)
        if not artifact:
            raise ValueError(f"Unknown artifact_id: {aid}")
        path = Path(str(artifact.get("path") or ""))
        changes: dict[str, Any]
        if not path.exists() or not path.is_file():
            changes = {"availability": "missing", "verification_status": "failed", "verified_at": _now_iso()}
        else:
            stat = path.stat()
            digest = _sha256(path)
            changes = {
                "availability": "available",
                "verification_status": "verified",
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "sha256": digest,
                "verified_at": _now_iso(),
            }
        result = store.append_event(_event("artifact_verified", f"Verified artifact: {aid}", project_id=str(artifact.get("project_id") or ""), artifact_id=aid, changes=changes))
        return {"status": result["status"], "artifact_id": aid, "verification": changes, "event_id": result["event_id"]}

    if op == "remove_artifact":
        aid = str(action.get("artifact_id") or "").strip()
        artifact = next((a for a in state.get("artifacts", []) if str(a.get("id")) == aid), None)
        if not artifact:
            return {"status": "already_absent", "artifact_id": aid}
        result = store.append_event(_event("artifact_removed", f"Removed artifact registration: {aid}", project_id=str(artifact.get("project_id") or ""), artifact_id=aid))
        return {"status": result["status"], "artifact_id": aid, "event_id": result["event_id"]}

    if op == "update_local_permissions":
        mode = str(action.get("mode") or "").strip()
        if mode not in {"conservative", "balanced", "autonomous"}:
            raise ValueError("mode must be conservative, balanced or autonomous")
        result = store.append_event(_event("local_permission_updated", f"Local permission mode -> {mode}", changes={"mode": mode}))
        return {"status": result["status"], "mode": mode, "event_id": result["event_id"]}

    raise ValueError(f"unsupported local action: {op}")
