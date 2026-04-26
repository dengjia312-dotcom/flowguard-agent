"""
Integration tests for AgentRuntime -> EventBus executor events (v0.3 stage B-3).

Run with:
    cd flowguard-agent
    pytest tests/test_runtime_executor_events.py -v
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# tests/test_parse_plan_json.py installs lightweight stubs into sys.modules.
# Remove them so these integration tests use the real backend implementations.
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


def _make_config(tmp_path: Path, planner_mode: str = "mock") -> dict:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "test.md").write_text("hello flowguard", encoding="utf-8")
    (workspace / "device_state.json").write_text(
        json.dumps({
            "light": {"status": "off"},
            "air_conditioner": {"status": "off"},
            "robot_vacuum": {"status": "idle"},
            "door_lock": {"status": "locked"},
            "camera": {"status": "on"},
            "window": {"status": "closed"},
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


def _events_of_type(bus: EventBus, task_id: str, event_type: str):
    return [
        e for e in bus.read_events(task_id)
        if e["event_type"] == event_type
    ]


def _event_types(bus: EventBus, task_id: str):
    return [e["event_type"] for e in bus.read_events(task_id)]


def test_low_risk_task_emits_executor_events(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("读取 test.md"))
    assert result["status"] == "completed"

    started = _events_of_type(bus, result["task_id"], "executor.step_started")
    completed = _events_of_type(bus, result["task_id"], "executor.step_completed")
    assert len(started) == 1
    assert len(completed) == 1
    assert completed[0]["status"] == "success"
    assert completed[0]["step_id"] == "step_1"
    assert completed[0]["tool_name"] == "file.read"
    assert completed[0]["payload"]["result_status"] == "success"


def test_high_risk_task_before_confirm_emits_no_executor_events(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("回家模式"))
    assert result["status"] == "confirmation_required"

    types = _event_types(bus, result["task_id"])
    assert "executor.step_started" not in types
    assert "executor.step_completed" not in types


def test_high_risk_task_after_confirm_emits_executor_events(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    pending = _run(runtime.run_task("回家模式"))
    task_id = pending["task_id"]
    assert pending["status"] == "confirmation_required"

    confirm_result = _run(runtime.confirm_task(task_id, True))
    assert confirm_result["status"] in ("completed", "completed_with_errors")

    started = _events_of_type(bus, task_id, "executor.step_started")
    completed = _events_of_type(bus, task_id, "executor.step_completed")
    assert len(started) >= 5
    assert len(completed) >= 5

    door_lock_events = [
        e for e in completed
        if e["tool_name"] == "device.set_state"
        and e["payload"]["args"].get("device_id") == "door_lock"
        and e["payload"]["args"].get("status") == "unlocked"
    ]
    assert len(door_lock_events) == 1
    assert door_lock_events[0]["status"] == "success"


def test_failed_tool_emits_failed_executor_completed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    runtime._mock_planner = lambda _message: {
        "task_type": "file_summary",
        "goal": "Read a missing file",
        "steps": [
            {
                "id": "step_missing",
                "action": "file.read",
                "args": {"path": "missing.md"},
                "risk": "low",
                "requires_confirmation": False,
            }
        ],
        "conflicts": [],
        "need_user_confirmation": False,
    }

    result = _run(runtime.run_task("read missing file"))
    assert result["status"] == "failed"

    completed = _events_of_type(bus, result["task_id"], "executor.step_completed")
    assert len(completed) == 1
    assert completed[0]["status"] == "failed"
    assert completed[0]["step_id"] == "step_missing"
    assert completed[0]["payload"]["result_status"] == "failed"
    assert completed[0]["payload"]["error"]
    assert "result" not in completed[0]["payload"]
