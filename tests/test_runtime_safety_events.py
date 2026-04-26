"""
Integration tests for AgentRuntime ↔ EventBus — safety reviewer + user
confirmation events (v0.3 stage B-2).

Covers:
  - safety.started / safety.passed / safety.flagged
  - confirmation.required / confirmation.approved / confirmation.cancelled

Reviewer / user events MUST never break the existing high-risk gate:
  - low-risk task still completes
  - high-risk task still returns confirmation_required and executes nothing
    until POST /agent/confirm is called

Run with:
    cd flowguard-agent
    pytest tests/test_runtime_safety_events.py -v
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Strip stubs that test_parse_plan_json.py may have planted in sys.modules
# so we reload the real backend.* implementations for these integration tests.
for _stubbed in [
    "backend.model_router",
    "backend.state.state_manager",
    "backend.state.log_manager",
    "backend.tools.device_tools",
    "backend.tools.file_tools",
    "backend.tools.rag_tools",
    "backend.tools.web_tools",
    "backend.agent_runtime",
]:
    sys.modules.pop(_stubbed, None)

from backend.agent_runtime import AgentRuntime  # noqa: E402
from backend.events import EventBus  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixture: build a self-contained config rooted in tmp_path
# ---------------------------------------------------------------------------
def _make_config(tmp_path: Path, planner_mode: str = "mock") -> dict:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "test.md").write_text("hello flowguard", encoding="utf-8")
    # device_state.json — populated so the home-arrival mock plan can complete
    # all five steps after confirmation. door_lock starts locked, etc.
    (workspace / "device_state.json").write_text(
        json.dumps({
            "light":           {"status": "off"},
            "air_conditioner": {"status": "off"},
            "robot_vacuum":    {"status": "idle"},
            "door_lock":       {"status": "locked"},
            "camera":          {"status": "on"},
            "window":          {"status": "closed"},
        }),
        encoding="utf-8",
    )
    return {
        "app": {"name": "FlowGuard Test", "version": "0.3.0"},
        "providers": {},
        "models": {},
        "runtime": {"plannerMode": planner_mode},
        "tools": {
            "enabled": [
                "file.read", "file.write", "file.list",
                "device.get_state", "device.set_state",
                "rag.search", "web.search",
            ],
            "disabled": ["shell.exec"],
        },
        "safety": {
            "require_confirmation": ["door_lock:unlock"],
            "forbidden_tools": ["shell.exec"],
        },
        "paths": {
            "workspace": str(workspace),
            "state": str(tmp_path / "state.json"),
            "execution_log": str(tmp_path / "execution_log.json"),
            "events": str(tmp_path / "events.json"),
        },
    }


def _run(coro):
    return asyncio.run(coro)


def _types(events):
    return [e["event_type"] for e in events]


# ---------------------------------------------------------------------------
# Test 1: home-arrival (high-risk) emits safety.started + safety.flagged + confirmation.required
# ---------------------------------------------------------------------------
def test_home_arrival_emits_safety_flagged_and_confirmation_required(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("回家模式"))
    assert result["status"] == "confirmation_required"

    types = _types(bus.read_events(result["task_id"]))
    assert "safety.started" in types
    assert "safety.flagged" in types
    assert "confirmation.required" in types

    # Order check: started → flagged → required
    assert types.index("safety.started") < types.index("safety.flagged")
    assert types.index("safety.flagged") < types.index("confirmation.required")

    # safety.passed must NOT appear on the high-risk path
    assert "safety.passed" not in types


# ---------------------------------------------------------------------------
# Test 2: home-arrival safety.flagged carries pending_count and pending_actions
# ---------------------------------------------------------------------------
def test_safety_flagged_payload(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("回家模式"))
    flagged = [
        e for e in bus.read_events(result["task_id"])
        if e["event_type"] == "safety.flagged"
    ]
    assert len(flagged) == 1
    payload = flagged[0]["payload"]
    assert payload["pending_count"] >= 1
    assert isinstance(payload["pending_actions"], list)
    # The mock plan's high-risk step is the door_lock unlock
    assert any(
        a.get("action") == "device.set_state"
        and a.get("args", {}).get("device_id") == "door_lock"
        for a in payload["pending_actions"]
    )


# ---------------------------------------------------------------------------
# Test 3: file_summary (low-risk) emits safety.started + safety.passed
# ---------------------------------------------------------------------------
def test_file_summary_emits_safety_passed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("读取 test.md"))
    assert result["status"] == "completed"

    types = _types(bus.read_events(result["task_id"]))
    assert "safety.started" in types
    assert "safety.passed" in types
    # On the low-risk path, none of the user-confirmation events should fire
    assert "safety.flagged" not in types
    assert "confirmation.required" not in types
    assert "confirmation.approved" not in types
    assert "confirmation.cancelled" not in types


# ---------------------------------------------------------------------------
# Test 4: confirm=True emits confirmation.approved
# ---------------------------------------------------------------------------
def test_confirm_true_emits_confirmation_approved(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    pending = _run(runtime.run_task("回家模式"))
    task_id = pending["task_id"]
    assert pending["status"] == "confirmation_required"

    confirm_result = _run(runtime.confirm_task(task_id, True))
    # The original confirm response shape must be preserved
    assert confirm_result["status"] in ("completed", "completed_with_errors")

    approved = [
        e for e in bus.read_events(task_id)
        if e["event_type"] == "confirmation.approved"
    ]
    assert len(approved) == 1
    assert approved[0]["agent"] == "user"
    assert approved[0]["status"] == "success"
    assert approved[0]["payload"] == {"confirmed": True}


# ---------------------------------------------------------------------------
# Test 5: confirm=False emits confirmation.cancelled
# ---------------------------------------------------------------------------
def test_confirm_false_emits_confirmation_cancelled(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    pending = _run(runtime.run_task("回家模式"))
    task_id = pending["task_id"]

    confirm_result = _run(runtime.confirm_task(task_id, False))
    assert confirm_result["status"] == "cancelled"

    cancelled = [
        e for e in bus.read_events(task_id)
        if e["event_type"] == "confirmation.cancelled"
    ]
    assert len(cancelled) == 1
    assert cancelled[0]["agent"] == "user"
    assert cancelled[0]["status"] == "cancelled"
    assert cancelled[0]["payload"] == {"confirmed": False}

    # confirmation.approved must NOT have fired
    types = _types(bus.read_events(task_id))
    assert "confirmation.approved" not in types


# ---------------------------------------------------------------------------
# Test 6: full confirm=True lifecycle has the events in the correct order
# ---------------------------------------------------------------------------
def test_full_confirm_lifecycle_event_order(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    pending = _run(runtime.run_task("回家模式"))
    task_id = pending["task_id"]
    _run(runtime.confirm_task(task_id, True))

    types = _types(bus.read_events(task_id))
    expected = [
        "task.received",
        "planner.started",
        "planner.completed",
        "safety.started",
        "safety.flagged",
        "confirmation.required",
        "confirmation.approved",
    ]
    # Each expected event appears in increasing positions (subsequence check —
    # other event types may interleave once we wire executor / reporter).
    last_idx = -1
    for et in expected:
        assert et in types, f"missing event: {et}"
        idx = types.index(et)
        assert idx > last_idx, f"{et} out of order (idx={idx}, prev={last_idx})"
        last_idx = idx
