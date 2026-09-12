from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_v1 import CanonicalStore


CAPABILITIES: dict[str, dict[str, Any]] = {
    "artifact.open": {"risk": "R1", "reversible": False},
    "folder.open": {"risk": "R1", "reversible": False},
    "file.copy": {"risk": "R1", "reversible": True},
    "application.open": {"risk": "R2", "reversible": False},
}
RISK_RANK = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _workspace(state: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    return next((x for x in state.get("workspace_bindings", []) if str(x.get("project_id") or "") == project_id and x.get("authorized")), None)


def _artifact(state: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    return next((x for x in state.get("artifacts", []) if str(x.get("id") or "") == artifact_id), None)


def _path_is_authorized(state: dict[str, Any], path: Path) -> bool:
    if any(Path(str(a.get("path"))).resolve() == path.resolve() for a in state.get("artifacts", []) if a.get("path")):
        return True
    for binding in state.get("workspace_bindings", []):
        if binding.get("authorized") and binding.get("path") and _is_within(path, Path(str(binding["path"]))):
            return True
    return False


def _permission_requires_confirmation(state: dict[str, Any], risk: str) -> bool:
    mode = str((state.get("local_permissions") or {}).get("mode") or "balanced")
    rank = RISK_RANK[risk]
    if risk == "R3":
        return True
    if mode == "conservative":
        return rank >= 1
    if mode == "autonomous":
        return False
    return rank >= 2


def _open_path(path: Path) -> None:
    system = platform.system().lower()
    if system == "windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.Popen(["open", str(path)], close_fds=True)
    else:
        subprocess.Popen(["xdg-open", str(path)], close_fds=True)


def _open_application(path: Path) -> None:
    system = platform.system().lower()
    if system == "windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.Popen(["open", "-a", str(path)], close_fds=True)
    else:
        subprocess.Popen([str(path)], close_fds=True)


class LocalExecutionGateway:
    def __init__(self, store: CanonicalStore, *, dry_run: bool = False):
        self.store = store
        self.dry_run = dry_run

    def preview(self, action: dict[str, Any]) -> dict[str, Any]:
        capability = str(action.get("capability") or "").strip()
        spec = CAPABILITIES.get(capability)
        if not spec:
            raise ValueError("unsupported local capability")
        state = self.store.get_state()
        target: dict[str, Any] = {}

        if capability == "artifact.open":
            artifact_id = str(action.get("artifact_id") or "").strip()
            artifact = _artifact(state, artifact_id)
            if not artifact:
                raise ValueError("unknown artifact_id")
            path = Path(str(artifact.get("path") or ""))
            if not path.exists() or not path.is_file():
                raise ValueError("artifact is not available")
            target = {"artifact_id": artifact_id, "path": str(path.resolve())}

        elif capability == "folder.open":
            project_id = str(action.get("project_id") or "").strip()
            if project_id:
                binding = _workspace(state, project_id)
                if not binding:
                    raise PermissionError("project has no authorized workspace")
                path = Path(str(binding["path"]))
            else:
                path = Path(str(action.get("path") or ""))
                if not path.is_absolute() or not _path_is_authorized(state, path):
                    raise PermissionError("folder is outside authorized workspaces")
            if not path.exists() or not path.is_dir():
                raise ValueError("folder does not exist")
            target = {"project_id": project_id or None, "path": str(path.resolve())}

        elif capability == "file.copy":
            source_artifact_id = str(action.get("source_artifact_id") or "").strip()
            if source_artifact_id:
                artifact = _artifact(state, source_artifact_id)
                if not artifact:
                    raise ValueError("unknown source_artifact_id")
                source = Path(str(artifact.get("path") or ""))
            else:
                source = Path(str(action.get("source_path") or ""))
                if not source.is_absolute() or not _path_is_authorized(state, source):
                    raise PermissionError("source is outside authorized scope")
            if not source.exists() or not source.is_file():
                raise ValueError("source file does not exist")
            destination_project_id = str(action.get("destination_project_id") or "").strip()
            binding = _workspace(state, destination_project_id)
            if not binding:
                raise PermissionError("destination project has no authorized workspace")
            name = str(action.get("destination_name") or source.name).strip()
            if not name or Path(name).name != name:
                raise ValueError("destination_name must be a file name")
            destination = Path(str(binding["path"])) / name
            if destination.exists():
                raise FileExistsError("overwrite is not supported in NextPlan Local v0.1")
            if not _is_within(destination, Path(str(binding["path"]))):
                raise PermissionError("destination escapes authorized workspace")
            target = {
                "source": str(source.resolve()),
                "destination": str(destination.resolve()),
                "destination_project_id": destination_project_id,
            }

        elif capability == "application.open":
            path = Path(str(action.get("application_path") or "")).expanduser()
            if not path.is_absolute() or not path.exists():
                raise ValueError("application_path must be an existing absolute path")
            if action.get("args"):
                raise ValueError("application.open does not accept arbitrary args")
            target = {"application_path": str(path.resolve())}

        risk = str(spec["risk"])
        return {
            "status": "preview",
            "capability": capability,
            "risk": risk,
            "reversible": bool(spec["reversible"]),
            "requires_confirmation": _permission_requires_confirmation(state, risk),
            "target": target,
        }

    def execute(self, action: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        preview = self.preview(action)
        if preview["requires_confirmation"] and not confirmed:
            return {**preview, "status": "confirmation_required"}

        capability = preview["capability"]
        target = preview["target"]
        receipt: dict[str, Any] = {
            "id": f"local-action-{uuid.uuid4().hex}",
            "capability": capability,
            "risk": preview["risk"],
            "reversible": preview["reversible"],
            "confirmed": bool(confirmed),
            "started_at": _now_iso(),
            "status": "success",
            "target": target,
            "verification": {"status": "pending"},
        }
        try:
            if capability == "artifact.open":
                path = Path(target["path"])
                if not self.dry_run:
                    _open_path(path)
                receipt["verification"] = {"status": "accepted", "source_exists": path.exists(), "dispatch": "dry_run" if self.dry_run else "started"}

            elif capability == "folder.open":
                path = Path(target["path"])
                if not self.dry_run:
                    _open_path(path)
                receipt["verification"] = {"status": "accepted", "folder_exists": path.is_dir(), "dispatch": "dry_run" if self.dry_run else "started"}

            elif capability == "file.copy":
                source = Path(target["source"])
                destination = Path(target["destination"])
                before_hash = _sha256(source)
                if not self.dry_run:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                verified = self.dry_run or (destination.exists() and destination.is_file() and _sha256(destination) == before_hash)
                receipt["verification"] = {
                    "status": "verified" if verified else "failed",
                    "source_sha256": before_hash,
                    "destination_exists": self.dry_run or destination.exists(),
                    "content_match": verified,
                }
                if not verified:
                    receipt["status"] = "failed"
                if verified and not self.dry_run:
                    receipt["rollback"] = {"capability": "file.copy.rollback", "path": str(destination), "expected_sha256": before_hash}

            elif capability == "application.open":
                path = Path(target["application_path"])
                if not self.dry_run:
                    _open_application(path)
                receipt["verification"] = {"status": "accepted", "application_exists": path.exists(), "dispatch": "dry_run" if self.dry_run else "started"}

        except Exception as exc:
            receipt["status"] = "failed"
            receipt["verification"] = {"status": "failed", "error": type(exc).__name__}

        receipt["finished_at"] = _now_iso()
        event = {
            "id": f"evt-local-execution-{uuid.uuid4().hex}",
            "at": receipt["finished_at"],
            "type": "local_execution_recorded",
            "summary": f"Local execution {capability}: {receipt['status']}",
            "source": {"kind": "local", "via": "nextplan-local-execution-v1"},
            "receipt": receipt,
        }
        stored = self.store.append_event(event)
        receipt["event_id"] = stored["event_id"]
        return receipt
