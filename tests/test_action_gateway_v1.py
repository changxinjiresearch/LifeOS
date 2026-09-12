from mcp_server.action_gateway_v1 import decide_permission, make_action_envelope, make_execution_receipt


def test_read_only_explicit_request_allowed():
    d = decide_permission("read_only", user_explicitly_requested=True)
    assert d["allowed"] is True
    assert d["requires_confirmation"] is False


def test_reversible_write_requires_confirmation_without_policy():
    d = decide_permission("reversible_write", user_explicitly_requested=True)
    assert d["allowed"] is False
    assert d["requires_confirmation"] is True


def test_reversible_write_standing_policy_allowed():
    d = decide_permission(
        "reversible_write",
        user_explicitly_requested=False,
        standing_policy_allows=True,
    )
    assert d["allowed"] is True


def test_consequential_write_requires_confirmation():
    d = decide_permission("consequential_write", user_explicitly_requested=True)
    assert d["allowed"] is False
    assert d["requires_confirmation"] is True


def test_destructive_always_needs_per_execution_confirmation():
    d = decide_permission(
        "destructive",
        user_explicitly_requested=True,
        standing_policy_allows=True,
    )
    assert d["allowed"] is False
    assert d["requires_confirmation"] is True
    d2 = decide_permission(
        "destructive",
        user_explicitly_requested=True,
        explicit_confirmation=True,
        standing_policy_allows=True,
    )
    assert d2["allowed"] is True


def test_envelope_and_receipt_contract():
    env = make_action_envelope(
        "calendar",
        "create_event",
        "reversible_write",
        {"title": "Supervisor meeting", "date": "2026-09-16"},
        dry_run=True,
    )
    assert env["provider"] == "calendar"
    assert env["risk_class"] == "reversible_write"
    assert env["idempotency_key"]
    receipt = make_execution_receipt(
        env,
        status="previewed",
        verified=False,
        summary="Preview only",
        rollback_supported=True,
    )
    assert receipt["receipt_version"] == "agent-action-1.0"
    assert receipt["action_id"] == env["action_id"]
    assert receipt["rollback_supported"] is True
