"""
Unit tests for backend/events/event_schema.py — the AgentEvent model.

Run with:
    cd flowguard-agent
    pytest tests/test_event_schema.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.events.event_schema import (  # noqa: E402
    ALLOWED_AGENTS,
    ALLOWED_STATUSES,
    AgentEvent,
)


# ---------------------------------------------------------------------------
# Test 1: minimal required fields can construct an event
# ---------------------------------------------------------------------------
def test_minimal_fields_can_create():
    e = AgentEvent(
        task_id="t1",
        agent="planner",
        event_type="planner.started",
        status="running",
    )
    assert e.task_id == "t1"
    assert e.agent == "planner"
    assert e.event_type == "planner.started"
    assert e.status == "running"


# ---------------------------------------------------------------------------
# Test 2: event_id is auto-generated and unique per instance
# ---------------------------------------------------------------------------
def test_event_id_auto_generated():
    e1 = AgentEvent(task_id="t1", agent="planner", event_type="x", status="running")
    e2 = AgentEvent(task_id="t1", agent="planner", event_type="x", status="running")
    assert e1.event_id and e2.event_id
    assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------------
# Test 3: timestamp is auto-generated as a non-empty ISO-like string
# ---------------------------------------------------------------------------
def test_timestamp_auto_generated():
    e = AgentEvent(task_id="t1", agent="planner", event_type="x", status="running")
    assert e.timestamp
    # ISO 8601 always contains 'T' between date and time
    assert "T" in e.timestamp


# ---------------------------------------------------------------------------
# Test 4: payload defaults are independent per instance (no shared mutable)
# ---------------------------------------------------------------------------
def test_payload_default_independent():
    e1 = AgentEvent(task_id="t1", agent="planner", event_type="x", status="running")
    e2 = AgentEvent(task_id="t2", agent="planner", event_type="x", status="running")
    e1.payload["foo"] = "bar"
    assert "foo" not in e2.payload


# ---------------------------------------------------------------------------
# Test 5: model_dump contains every documented field and is JSON-serialisable
# ---------------------------------------------------------------------------
def test_model_dump_contains_core_fields():
    e = AgentEvent(
        task_id="t1",
        agent="executor",
        event_type="executor.step_completed",
        status="success",
        message="step ok",
        step_id="step_1",
        tool_name="file.read",
        payload={"k": "v"},
        seq=1,
    )
    d = e.model_dump()
    for f in [
        "event_id", "task_id", "timestamp", "agent", "event_type", "status",
        "message", "step_id", "tool_name", "payload", "seq",
    ]:
        assert f in d, f"model_dump missing field: {f}"
    # Round-trip through JSON to prove it serialises cleanly
    serialised = json.dumps(d, ensure_ascii=False)
    assert "executor.step_completed" in serialised


# ---------------------------------------------------------------------------
# Test 6: invalid `agent` value is rejected (vocabulary stability)
# ---------------------------------------------------------------------------
def test_invalid_agent_rejected():
    with pytest.raises(Exception):
        AgentEvent(
            task_id="t1",
            agent="not_a_real_role",
            event_type="x",
            status="running",
        )


# ---------------------------------------------------------------------------
# Test 7: invalid `status` value is rejected
# ---------------------------------------------------------------------------
def test_invalid_status_rejected():
    with pytest.raises(Exception):
        AgentEvent(
            task_id="t1",
            agent="planner",
            event_type="x",
            status="banana",
        )


# ---------------------------------------------------------------------------
# Test 8: every documented agent + status value is accepted
# ---------------------------------------------------------------------------
def test_all_allowed_agents_and_statuses_accepted():
    for agent in ALLOWED_AGENTS:
        for status in ALLOWED_STATUSES:
            AgentEvent(
                task_id="t1",
                agent=agent,
                event_type="x",
                status=status,
            )
