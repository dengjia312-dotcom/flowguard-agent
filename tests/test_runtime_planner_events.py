"""
Integration tests for AgentRuntime ↔ EventBus wiring (v0.3 first cut).

Covers only task.* and planner.* events. Reviewer / executor / reporter
events are introduced in subsequent iterations.

Run with:
    cd flowguard-agent
    pytest tests/test_runtime_planner_events.py -v
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# tests/test_parse_plan_json.py installs lightweight stubs into sys.modules so
# it can construct AgentRuntime without the real tool / state / model layers.
# Those stubs persist within the same pytest session and would replace our
# backend.* imports here. Pop them so we reload the real implementations.
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
    # Provide test.md so the file_summary mock plan can succeed end-to-end.
    (workspace / "test.md").write_text("hello flowguard", encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Test 1: mock-mode happy path emits task.received + planner.started + planner.completed
# ---------------------------------------------------------------------------
def test_mock_planner_emits_task_and_planner_events(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("读取 test.md"))
    assert result["status"] == "completed", result

    events = bus.read_events()
    types = [e["event_type"] for e in events]
    assert "task.received" in types
    assert "planner.started" in types
    assert "planner.completed" in types

    # Order check: task.received must come before planner.* events
    assert types.index("task.received") < types.index("planner.started")
    assert types.index("planner.started") < types.index("planner.completed")


# ---------------------------------------------------------------------------
# Test 2: planner.completed payload carries the documented fields
# ---------------------------------------------------------------------------
def test_planner_completed_payload_fields(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    _run(runtime.run_task("读取 test.md"))

    completed = [e for e in bus.read_events() if e["event_type"] == "planner.completed"]
    assert len(completed) == 1
    payload = completed[0]["payload"]
    assert payload["planner_mode"] == "mock"
    assert payload["task_type"] == "file_summary"
    assert isinstance(payload["goal"], str) and payload["goal"]
    assert payload["steps_count"] == 1


# ---------------------------------------------------------------------------
# Test 3: every emitted event carries the same task_id as the run
# ---------------------------------------------------------------------------
def test_events_carry_task_id(tmp_path: Path):
    cfg = _make_config(tmp_path)
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    result = _run(runtime.run_task("读取 test.md"))
    task_id = result["task_id"]

    scoped = bus.read_events(task_id)
    assert len(scoped) >= 3
    assert all(e["task_id"] == task_id for e in scoped)


# ---------------------------------------------------------------------------
# Test 4: planner.failed is emitted when the model returns un-parseable text
# ---------------------------------------------------------------------------
def test_planner_parse_failed_emits_planner_failed(tmp_path: Path):
    cfg = _make_config(tmp_path, planner_mode="model")
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    # Stub the model call to return non-JSON output. No real API key involved.
    async def fake_call(role, messages):
        return "Sorry, I cannot generate a plan."
    runtime.model_router.call = fake_call  # type: ignore[assignment]

    result = _run(runtime.run_task("anything"))
    assert result["status"] == "plan_parse_failed"

    failed = [e for e in bus.read_events() if e["event_type"] == "planner.failed"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert failed[0]["payload"]["reason"] == "plan_parse_failed"

    # planner.completed must NOT be emitted on the failure path
    types = [e["event_type"] for e in bus.read_events()]
    assert "planner.completed" not in types


# ---------------------------------------------------------------------------
# Test 5: planner.failed is emitted when the model call itself raises
# ---------------------------------------------------------------------------
def test_planner_model_call_failed_emits_planner_failed(tmp_path: Path):
    cfg = _make_config(tmp_path, planner_mode="model")
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    async def boom(role, messages):
        raise RuntimeError("simulated network error")
    runtime.model_router.call = boom  # type: ignore[assignment]

    result = _run(runtime.run_task("anything"))
    assert result["status"] == "model_call_failed"

    failed = [e for e in bus.read_events() if e["event_type"] == "planner.failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["reason"] == "model_call_failed"


# ---------------------------------------------------------------------------
# Test 6: planner.failed is emitted when ModelRouter signals api_key_missing
# ---------------------------------------------------------------------------
def test_planner_api_key_missing_emits_planner_failed(tmp_path: Path):
    cfg = _make_config(tmp_path, planner_mode="model")
    bus = EventBus(event_log_path=tmp_path / "events.json")
    runtime = AgentRuntime(cfg, event_bus=bus)

    async def missing_key(role, messages):
        # Mirrors the OpenAICompatibleAdapter behaviour when env var is unset.
        raise ValueError("api_key_missing: MODEL_API_KEY is not set")
    runtime.model_router.call = missing_key  # type: ignore[assignment]

    result = _run(runtime.run_task("anything"))
    assert result["status"] == "api_key_missing"

    failed = [e for e in bus.read_events() if e["event_type"] == "planner.failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["reason"] == "api_key_missing"


# ---------------------------------------------------------------------------
# Test 7: runtime works fine without an EventBus (backwards compatibility)
# ---------------------------------------------------------------------------
def test_run_task_works_without_event_bus(tmp_path: Path):
    cfg = _make_config(tmp_path)
    runtime = AgentRuntime(cfg)  # no event_bus kwarg
    result = _run(runtime.run_task("读取 test.md"))
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 8: _emit_event silently swallows EventBus exceptions
# ---------------------------------------------------------------------------
def test_emit_event_swallows_bus_exceptions(tmp_path: Path):
    cfg = _make_config(tmp_path)

    class BrokenBus:
        def emit(self, **kwargs):
            raise RuntimeError("bus is on fire")

    runtime = AgentRuntime(cfg, event_bus=BrokenBus())  # type: ignore[arg-type]
    # Must not raise even though every emit on this bus blows up
    result = _run(runtime.run_task("读取 test.md"))
    assert result["status"] == "completed"
