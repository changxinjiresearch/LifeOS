from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

import httpx


class ConnectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    risk_class: str
    description: str
    rollback_supported: bool = False


class Connector:
    provider: str = "unknown"

    def capabilities(self) -> Iterable[CapabilitySpec]:
        raise NotImplementedError

    def capability(self, name: str) -> CapabilitySpec:
        for item in self.capabilities():
            if item.name == name:
                return item
        raise ConnectorError(f"Unsupported capability for {self.provider}: {name}")

    async def execute(self, capability: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def verify(self, capability: str, payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def rollback(self, capability: str, payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(f"Rollback is not supported for {self.provider}:{capability}")


class ConnectorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._items[connector.provider] = connector

    def get(self, provider: str) -> Connector:
        if provider not in self._items:
            raise ConnectorError(f"Unknown connector provider: {provider}")
        return self._items[provider]

    def describe(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for provider, connector in sorted(self._items.items()):
            out.append({
                "provider": provider,
                "capabilities": [asdict(c) for c in connector.capabilities()],
            })
        return out


class GitHubConnector(Connector):
    provider = "github"

    def __init__(self, token: str, repository: str, branch: str = "main", api_base: str = "https://api.github.com") -> None:
        self.token = token.strip()
        self.repository = repository.strip()
        self.branch = branch.strip() or "main"
        self.api_base = api_base.rstrip("/")
        if not self.repository or "/" not in self.repository:
            raise ValueError("repository must be owner/name")

    def capabilities(self) -> Iterable[CapabilitySpec]:
        return (
            CapabilitySpec("repo.get", "read_only", "Read repository metadata."),
            CapabilitySpec("file.get", "read_only", "Read a UTF-8 repository file."),
            CapabilitySpec("file.create", "reversible_write", "Create a UTF-8 repository file.", True),
            CapabilitySpec("file.update", "reversible_write", "Replace a UTF-8 repository file.", True),
            CapabilitySpec("file.delete", "destructive", "Delete a repository file."),
            CapabilitySpec("issue.create", "consequential_write", "Create a GitHub issue.", True),
            CapabilitySpec("issue.comment", "consequential_write", "Add an issue comment."),
            CapabilitySpec("issue.set_state", "reversible_write", "Open or close a GitHub issue.", True),
        )

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ConnectorError("GitHub connector is not configured")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "NextPlan-Agent/1.0",
        }

    async def _raw_request(self, method: str, path: str, *, json_body: Any = None, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        url = f"{self.api_base}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.request(method, url, headers=self._headers(), json=json_body, params=params)

    async def _request(self, method: str, path: str, *, json_body: Any = None, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        response = await self._raw_request(method, path, json_body=json_body, params=params)
        if response.status_code >= 400:
            detail = response.text[:500]
            raise ConnectorError(f"GitHub {method} {path} failed ({response.status_code}): {detail}")
        return response

    def _repo_path(self, suffix: str = "") -> str:
        return f"/repos/{self.repository}{suffix}"

    async def _get_content_raw(self, path: str, ref: Optional[str] = None) -> dict[str, Any]:
        response = await self._request("GET", self._repo_path(f"/contents/{path}"), params={"ref": ref or self.branch})
        data = response.json()
        if not isinstance(data, dict):
            raise ConnectorError("Expected a file response from GitHub")
        return data

    async def _delete_path_with_retry(self, path: str, branch: str, message: str, attempts: int = 8) -> dict[str, Any]:
        last_detail = ""
        for attempt in range(1, attempts + 1):
            current = await self._get_content_raw(path, branch)
            body = {"message": message, "sha": current.get("sha"), "branch": branch}
            response = await self._raw_request("DELETE", self._repo_path(f"/contents/{path}"), json_body=body)
            if response.status_code < 400:
                data = response.json()
                return {"data": data, "deleted_sha": current.get("sha")}
            last_detail = response.text[:500]
            if response.status_code != 409 or attempt == attempts:
                raise ConnectorError(
                    f"GitHub DELETE {self._repo_path(f'/contents/{path}')} failed ({response.status_code}): {last_detail}"
                )
            await asyncio.sleep(min(0.15 * attempt, 0.8))
        raise ConnectorError(f"GitHub delete retry exhausted for {path}: {last_detail}")

    async def execute(self, capability: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.capability(capability)

        if capability == "repo.get":
            data = (await self._request("GET", self._repo_path())).json()
            return {
                "provider_result_id": str(data.get("id", "")),
                "full_name": data.get("full_name"),
                "default_branch": data.get("default_branch"),
                "private": data.get("private"),
                "updated_at": data.get("updated_at"),
            }

        if capability == "file.get":
            path = str(payload.get("path") or "").strip()
            if not path:
                raise ConnectorError("path is required")
            data = await self._get_content_raw(path, str(payload.get("ref") or self.branch))
            raw = base64.b64decode(str(data.get("content") or "")).decode("utf-8")
            return {
                "provider_result_id": str(data.get("sha") or ""),
                "path": path,
                "sha": data.get("sha"),
                "content": raw,
            }

        if capability in {"file.create", "file.update"}:
            path = str(payload.get("path") or "").strip()
            content = str(payload.get("content") if payload.get("content") is not None else "")
            message = str(payload.get("message") or f"NextPlan agent: {capability} {path}").strip()
            if not path:
                raise ConnectorError("path is required")
            body: dict[str, Any] = {
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": str(payload.get("branch") or self.branch),
            }
            previous: Optional[dict[str, Any]] = None
            if capability == "file.update":
                current = await self._get_content_raw(path, body["branch"])
                previous = {
                    "sha": current.get("sha"),
                    "content": base64.b64decode(str(current.get("content") or "")).decode("utf-8"),
                }
                body["sha"] = str(payload.get("sha") or current.get("sha") or "")
            response = await self._request("PUT", self._repo_path(f"/contents/{path}"), json_body=body)
            data = response.json()
            content_info = data.get("content") or {}
            commit_info = data.get("commit") or {}
            return {
                "provider_result_id": str(content_info.get("sha") or commit_info.get("sha") or ""),
                "path": path,
                "sha": content_info.get("sha"),
                "commit_sha": commit_info.get("sha"),
                "previous": previous,
            }

        if capability == "file.delete":
            path = str(payload.get("path") or "").strip()
            if not path:
                raise ConnectorError("path is required")
            branch = str(payload.get("branch") or self.branch)
            deleted = await self._delete_path_with_retry(
                path,
                branch,
                str(payload.get("message") or f"NextPlan agent: delete {path}"),
            )
            return {
                "provider_result_id": str((deleted["data"].get("commit") or {}).get("sha") or ""),
                "path": path,
                "deleted_sha": deleted.get("deleted_sha"),
            }

        if capability == "issue.create":
            title = str(payload.get("title") or "").strip()
            if not title:
                raise ConnectorError("title is required")
            body: dict[str, Any] = {"title": title, "body": str(payload.get("body") or "")}
            if isinstance(payload.get("labels"), list):
                body["labels"] = [str(x) for x in payload["labels"]]
            data = (await self._request("POST", self._repo_path("/issues"), json_body=body)).json()
            return {
                "provider_result_id": str(data.get("number") or ""),
                "issue_number": data.get("number"),
                "state": data.get("state"),
                "html_url": data.get("html_url"),
            }

        if capability == "issue.comment":
            number = int(payload.get("issue_number") or 0)
            body = str(payload.get("body") or "").strip()
            if number <= 0 or not body:
                raise ConnectorError("issue_number and body are required")
            data = (await self._request("POST", self._repo_path(f"/issues/{number}/comments"), json_body={"body": body})).json()
            return {
                "provider_result_id": str(data.get("id") or ""),
                "issue_number": number,
                "comment_id": data.get("id"),
                "html_url": data.get("html_url"),
            }

        if capability == "issue.set_state":
            number = int(payload.get("issue_number") or 0)
            state = str(payload.get("state") or "").strip().lower()
            if number <= 0 or state not in {"open", "closed"}:
                raise ConnectorError("issue_number and state=open|closed are required")
            before = (await self._request("GET", self._repo_path(f"/issues/{number}"))).json()
            data = (await self._request("PATCH", self._repo_path(f"/issues/{number}"), json_body={"state": state})).json()
            return {
                "provider_result_id": str(number),
                "issue_number": number,
                "state": data.get("state"),
                "previous_state": before.get("state"),
            }

        raise ConnectorError(f"Unhandled GitHub capability: {capability}")

    async def verify(self, capability: str, payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        if capability == "repo.get":
            ok = result.get("full_name") == self.repository
            return {"verified": bool(ok), "evidence": {"full_name": result.get("full_name")}}

        if capability in {"file.get", "file.create", "file.update"}:
            path = str(result.get("path") or payload.get("path") or "")
            try:
                current = await self._get_content_raw(path, str(payload.get("branch") or self.branch))
            except ConnectorError:
                return {"verified": False, "evidence": {"path": path}}
            expected_sha = result.get("sha") or result.get("provider_result_id")
            ok = bool(current.get("sha")) and (not expected_sha or current.get("sha") == expected_sha)
            return {"verified": bool(ok), "evidence": {"path": path, "sha": current.get("sha")}}

        if capability == "file.delete":
            path = str(result.get("path") or payload.get("path") or "")
            branch = str(payload.get("branch") or self.branch)
            last_status = 0
            # GitHub's contents endpoint can briefly serve the pre-delete branch
            # view immediately after a successful DELETE commit. Verification is
            # therefore bounded-retry rather than a single eventually-consistent GET.
            for attempt in range(1, 8):
                response = await self._request_allow_404(
                    "GET",
                    self._repo_path(f"/contents/{path}"),
                    params={"ref": branch},
                )
                last_status = response.status_code
                if last_status == 404:
                    return {"verified": True, "evidence": {"path": path, "status_code": 404, "attempt": attempt}}
                await asyncio.sleep(min(0.2 * attempt, 1.0))
            return {"verified": False, "evidence": {"path": path, "status_code": last_status, "attempts": 7}}

        if capability in {"issue.create", "issue.set_state", "issue.comment"}:
            number = int(result.get("issue_number") or payload.get("issue_number") or 0)
            if number <= 0:
                return {"verified": False, "evidence": {}}
            issue = (await self._request("GET", self._repo_path(f"/issues/{number}"))).json()
            if capability == "issue.set_state":
                ok = issue.get("state") == result.get("state")
            else:
                ok = bool(issue.get("number"))
            return {"verified": bool(ok), "evidence": {"issue_number": number, "state": issue.get("state")}}

        return {"verified": False, "evidence": {"reason": "no verifier"}}

    async def _request_allow_404(self, method: str, path: str, *, json_body: Any = None, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        response = await self._raw_request(method, path, json_body=json_body, params=params)
        if response.status_code >= 400 and response.status_code != 404:
            raise ConnectorError(f"GitHub {method} {path} failed ({response.status_code}): {response.text[:500]}")
        return response

    async def rollback(self, capability: str, payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        if capability == "file.create":
            path = str(result.get("path") or payload.get("path") or "")
            branch = str(payload.get("branch") or self.branch)
            deleted = await self._delete_path_with_retry(path, branch, f"NextPlan agent rollback: remove {path}")
            verify = await self.verify("file.delete", {"path": path, "branch": branch}, {"path": path})
            return {
                "status": "rolled_back" if verify.get("verified") else "rollback_unverified",
                "provider_result_id": str((deleted["data"].get("commit") or {}).get("sha") or ""),
                "verified": bool(verify.get("verified")),
                "path": path,
            }

        if capability == "file.update":
            previous = result.get("previous") or {}
            path = str(result.get("path") or payload.get("path") or "")
            if not previous or "content" not in previous:
                raise ConnectorError("Update rollback metadata is unavailable")
            current = await self._get_content_raw(path, str(payload.get("branch") or self.branch))
            body = {
                "message": f"NextPlan agent rollback: restore {path}",
                "content": base64.b64encode(str(previous["content"]).encode("utf-8")).decode("ascii"),
                "sha": current.get("sha"),
                "branch": str(payload.get("branch") or self.branch),
            }
            data = (await self._request("PUT", self._repo_path(f"/contents/{path}"), json_body=body)).json()
            return {
                "status": "rolled_back",
                "provider_result_id": str((data.get("commit") or {}).get("sha") or ""),
                "verified": True,
                "path": path,
            }

        if capability == "issue.create":
            number = int(result.get("issue_number") or 0)
            if number <= 0:
                raise ConnectorError("issue_number is unavailable for rollback")
            data = (await self._request("PATCH", self._repo_path(f"/issues/{number}"), json_body={"state": "closed"})).json()
            return {
                "status": "rolled_back",
                "provider_result_id": str(number),
                "verified": data.get("state") == "closed",
                "issue_number": number,
            }

        if capability == "issue.set_state":
            number = int(result.get("issue_number") or 0)
            previous_state = str(result.get("previous_state") or "")
            if number <= 0 or previous_state not in {"open", "closed"}:
                raise ConnectorError("Issue rollback metadata is unavailable")
            data = (await self._request("PATCH", self._repo_path(f"/issues/{number}"), json_body={"state": previous_state})).json()
            return {
                "status": "rolled_back",
                "provider_result_id": str(number),
                "verified": data.get("state") == previous_state,
                "issue_number": number,
            }

        raise ConnectorError(f"Rollback is not supported for github:{capability}")
