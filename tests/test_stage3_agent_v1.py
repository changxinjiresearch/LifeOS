import asyncio

from mcp_server.agent_stage3 import (
    evaluate_proactive_policies,
    execute_external_action,
    make_reconciliation,
    normalize_external_signal,
    prepare_external_action,
)
from mcp_server.connectors_v1 import CapabilitySpec, Connector, ConnectorRegistry


class FakeConnector(Connector):
    provider = "fake"

    def __init__(self):
        self.executed = []

    def capabilities(self):
        return (
            CapabilitySpec("read", "read_only", "read"),
            CapabilitySpec("write", "reversible_write", "write", True),
            CapabilitySpec("send", "consequential_write", "send"),
            CapabilitySpec("destroy", "destructive", "destroy"),
        )

    async def execute(self, capability, payload):
        self.executed.append((capability, payload))
        return {"provider_result_id": "result-1", "value": payload.get("value")}

    async def verify(self, capability, payload, result):
        return {"verified": True, "evidence": {"id": result.get("provider_result_id")}}

    async def rollback(self, capability, payload, result):
        return {"status": "rolled_back", "verified": True}


def registry():
    r = ConnectorRegistry()
    r.register(FakeConnector())
    return r


def test_connector_risk_is_authoritative():
    plan = prepare_external_action(
        registry(), {}, provider="fake", capability="send", payload={},
        user_explicitly_requested=True,
    )
    assert plan["capability"]["risk_class"] == "consequential_write"
    assert plan["permission"]["allowed"] is False
    assert plan["permission"]["requires_confirmation"] is True


def test_read_only_explicit_request_executes_and_verifies():
    result = asyncio.run(execute_external_action(
        registry(), {}, provider="fake", capability="read", payload={"value": 1},
        user_explicitly_requested=True,
    ))
    assert result["status"] == "verified"
    assert result["receipt"]["verified"] is True


def test_reversible_write_needs_confirmation_without_policy():
    result = asyncio.run(execute_external_action(
        registry(), {}, provider="fake", capability="write", payload={"value": 1},
        user_explicitly_requested=True,
    ))
    assert result["status"] == "needs_confirmation"


def test_reversible_write_can_use_narrow_standing_policy():
    state = {
        "agent_policies": [{
            "id": "allow-write",
            "kind": "standing_authorization",
            "enabled": True,
            "provider": "fake",
            "capabilities": ["write"],
            "project_id": "p1",
        }]
    }
    result = asyncio.run(execute_external_action(
        registry(), state, provider="fake", capability="write", payload={"value": 1},
        project_id="p1",
    ))
    assert result["status"] == "verified"
    assert result["plan"]["standing_policy"]["id"] == "allow-write"


def test_standing_policy_scope_does_not_leak_to_other_project():
    state = {
        "agent_policies": [{
            "id": "allow-write",
            "kind": "standing_authorization",
            "enabled": True,
            "provider": "fake",
            "capabilities": ["write"],
            "project_id": "p1",
        }]
    }
    result = asyncio.run(execute_external_action(
        registry(), state, provider="fake", capability="write", payload={}, project_id="p2",
    ))
    assert result["status"] == "needs_confirmation"


def test_consequential_write_executes_only_after_confirmation():
    denied = asyncio.run(execute_external_action(
        registry(), {}, provider="fake", capability="send", payload={},
        user_explicitly_requested=True,
    ))
    assert denied["status"] == "needs_confirmation"
    allowed = asyncio.run(execute_external_action(
        registry(), {}, provider="fake", capability="send", payload={},
        user_explicitly_requested=True, explicit_confirmation=True,
    ))
    assert allowed["status"] == "verified"


def test_destructive_action_requires_confirmation_even_when_requested():
    denied = asyncio.run(execute_external_action(
        registry(), {}, provider="fake", capability="destroy", payload={},
        user_explicitly_requested=True,
    ))
    assert denied["status"] == "needs_confirmation"
    allowed = asyncio.run(execute_external_action(
        registry(), {}, provider="fake", capability="destroy", payload={},
        user_explicitly_requested=True, explicit_confirmation=True,
    ))
    assert allowed["status"] == "verified"


def test_signal_intake_redacts_secrets_and_is_stable():
    a = normalize_external_signal(
        "github", "repo_head_changed", {"repository": "a/b", "head_sha": "abc", "token": "secret"},
        provider_event_id="abc", verified_source=True,
    )
    b = normalize_external_signal(
        "github", "repo_head_changed", {"repository": "a/b", "head_sha": "abc", "token": "secret"},
        provider_event_id="abc", verified_source=True,
    )
    assert a["id"] == b["id"]
    assert a["payload"]["token"] == "[REDACTED]"
    assert a["verified_source"] is True


def test_unverified_result_cannot_reconcile():
    try:
        make_reconciliation(summary="no", verified=False)
    except ValueError as exc:
        assert "Unverified" in str(exc)
    else:
        raise AssertionError("unverified reconciliation must fail")


def test_verified_reconciliation_has_audit_identity():
    rec = make_reconciliation(
        action_id="act-1", project_id="p1", summary="verified", verified=True,
        canonical_changes={"next_action": "continue"},
    )
    assert rec["verified"] is True
    assert rec["id"].startswith("reconcile-")
    assert rec["canonical_changes"]["next_action"] == "continue"


def test_proactive_policies_only_propose_actions():
    state = {
        "automation_feed": [
            {"id": "f1", "rule_id": "waiting-followup", "project_id": "p1", "reason": "waiting"},
            {"id": "f2", "rule_id": "preparation-window", "project_id": "p2", "reason": "soon"},
        ],
        "agent_policies": [],
    }
    proposals = evaluate_proactive_policies(state)
    assert len(proposals) == 2
    assert {p["action"] for p in proposals} == {"prepare_followup_draft", "prepare_commitment_plan"}
    assert all(p["requires_external_write"] is False for p in proposals)
