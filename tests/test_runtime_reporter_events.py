"""
Integration tests for AgentRuntime -> EventBus reporter and task final events.

Run with:
    cd flowguard-agent
    pytest tests/test_runtime_reporter_events.py -v
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


def test_low_risk_task_emits_reporter_and_task_completed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("读取 test.md"))
    assert result["status"] == "completed"

    task_id = result["task_id"]
    types = _event_types(bus, task_id)
    assert "reporter.started" in types
    assert "reporter.summary_created" in types
    assert "task.completed" in types

    completed = _events_of_type(bus, task_id, "task.completed")
    assert len(completed) == 1
    assert completed[0]["status"] == "success"
    assert completed[0]["payload"] == {
        "final_status": "completed",
        "successful": 1,
        "failed": 0,
    }


def test_high_risk_task_before_confirm_has_no_reporter_or_completed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("回家模式"))
    assert result["status"] == "confirmation_required"

    types = _event_types(bus, result["task_id"])
    assert "reporter.started" not in types
    assert "reporter.summary_created" not in types
    assert "task.completed" not in types


def test_high_risk_task_after_confirm_emits_reporter_and_completed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    pending = _run(runtime.run_task("回家模式"))
    task_id = pending["task_id"]
    assert pending["status"] == "confirmation_required"

    result = _run(runtime.confirm_task(task_id, True))
    assert result["status"] == "completed"

    types = _event_types(bus, task_id)
    assert "reporter.started" in types
    assert "reporter.summary_created" in types
    assert "task.completed" in types


def test_confirm_false_emits_task_cancelled_without_executor_or_completed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    pending = _run(runtime.run_task("回家模式"))
    task_id = pending["task_id"]
    assert pending["status"] == "confirmation_required"

    result = _run(runtime.confirm_task(task_id, False))
    assert result["status"] == "cancelled"

    types = _event_types(bus, task_id)
    assert "confirmation.cancelled" in types
    assert "task.cancelled" in types
    assert "executor.step_started" not in types
    assert "task.completed" not in types

    cancelled = _events_of_type(bus, task_id, "task.cancelled")
    assert len(cancelled) == 1
    assert cancelled[0]["status"] == "cancelled"
    assert cancelled[0]["payload"] == {"final_status": "cancelled"}


def test_tool_partial_failure_emits_reporter_and_completed_with_errors(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    runtime._mock_planner = lambda _message: {
        "task_type": "file_summary",
        "goal": "Read one existing file and one missing file",
        "steps": [
            {
                "id": "step_ok",
                "action": "file.read",
                "args": {"path": "test.md"},
                "risk": "low",
                "requires_confirmation": False,
            },
            {
                "id": "step_missing",
                "action": "file.read",
                "args": {"path": "missing.md"},
                "risk": "low",
                "requires_confirmation": False,
            },
        ],
        "conflicts": [],
        "need_user_confirmation": False,
    }

    result = _run(runtime.run_task("read mixed files"))
    assert result["status"] == "completed_with_errors"

    task_id = result["task_id"]
    assert _events_of_type(bus, task_id, "reporter.summary_created")
    final_events = _events_of_type(bus, task_id, "task.completed_with_errors")
    assert len(final_events) == 1
    assert final_events[0]["status"] == "failed"
    assert final_events[0]["payload"]["final_status"] == "completed_with_errors"
    assert final_events[0]["payload"]["successful"] == 1
    assert final_events[0]["payload"]["failed"] == 1


def test_planner_parse_failure_emits_task_failed_without_reporter(tmp_path: Path):
    cfg = _make_config(tmp_path, planner_mode="model")
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    async def fake_call(_role, _messages):
        return "not json"

    runtime.model_router.call = fake_call  # type: ignore[assignment]

    result = _run(runtime.run_task("anything"))
    assert result["status"] == "plan_parse_failed"

    task_id = result["task_id"]
    types = _event_types(bus, task_id)
    assert "task.failed" in types
    assert "reporter.started" not in types
    assert "reporter.summary_created" not in types

    failed = _events_of_type(bus, task_id, "task.failed")
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert failed[0]["payload"] == {
        "reason": "plan_parse_failed",
        "final_status": "failed",
    }
