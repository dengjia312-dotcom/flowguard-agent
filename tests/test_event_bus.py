"""
Unit tests for backend/events/event_bus.py — the EventBus.

Run with:
    cd flowguard-agent
    pytest tests/test_event_bus.py -v

Each test gets its own tmp_path-backed events.json so the real
data/events.json is never touched.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.events.event_bus import EventBus  # noqa: E402
from backend.events.event_log import EventLogManager  # noqa: E402


def _bus(tmp_path: Path) -> EventBus:
    return EventBus(event_log_path=tmp_path / "events.json")


# ---------------------------------------------------------------------------
# Test 1: emit persists an event
# ---------------------------------------------------------------------------
def test_emit_writes_event(tmp_path: Path):
    bus = _bus(tmp_path)
    record = bus.emit("t1", "planner", "planner.started", "running")
    assert record["task_id"] == "t1"
    assert record["agent"] == "planner"
    assert record["event_type"] == "planner.started"
    assert record["status"] == "running"
    assert record["event_id"]
    assert record["timestamp"]


# ---------------------------------------------------------------------------
# Test 2: read_events returns what was emitted, with task_id filter
# ---------------------------------------------------------------------------
def test_read_after_emit(tmp_path: Path):
    bus = _bus(tmp_path)
    bus.emit("t1", "planner", "planner.started", "running")
    bus.emit("t1", "planner", "planner.completed", "success")
    bus.emit("t2", "system", "task.received", "pending")
    assert len(bus.read_events()) == 3
    assert len(bus.read_events("t1")) == 2
    assert len(bus.read_events("t2")) == 1


# ---------------------------------------------------------------------------
# Test 3: subscribed callback receives every event
# ---------------------------------------------------------------------------
def test_subscribe_callback_receives_event(tmp_path: Path):
    bus = _bus(tmp_path)
    received = []
    bus.subscribe(received.append)
    bus.emit("t1", "planner", "planner.started", "running", message="hi")
    assert len(received) == 1
    assert received[0]["message"] == "hi"
    bus.emit("t1", "executor", "executor.step_started", "running", step_id="step_1")
    assert len(received) == 2
    assert received[1]["step_id"] == "step_1"


# ---------------------------------------------------------------------------
# Test 4: a callback that raises does NOT break emit or other callbacks
# ---------------------------------------------------------------------------
def test_callback_exception_does_not_break_emit(tmp_path: Path):
    bus = _bus(tmp_path)

    def bad_cb(_event):
        raise RuntimeError("boom")

    received = []
    bus.subscribe(bad_cb)
    bus.subscribe(received.append)

    record = bus.emit("t1", "planner", "planner.started", "running")
    assert record is not None
    # Healthy subscriber still received the event
    assert len(received) == 1
    # Event was persisted despite the bad callback
    assert len(bus.read_events()) == 1


# ---------------------------------------------------------------------------
# Test 5: unsubscribe stops further deliveries
# ---------------------------------------------------------------------------
def test_unsubscribe_stops_delivery(tmp_path: Path):
    bus = _bus(tmp_path)
    received = []

    def cb(event):
        received.append(event)

    bus.subscribe(cb)
    bus.emit("t1", "planner", "planner.started", "running")
    assert len(received) == 1

    bus.unsubscribe(cb)
    bus.emit("t2", "planner", "planner.started", "running")
    # Persistence still works (2 events on disk)
    assert len(bus.read_events()) == 2
    # But callback received only the first
    assert len(received) == 1


# ---------------------------------------------------------------------------
# Test 6: payload is copied into the event, not aliased
# ---------------------------------------------------------------------------
def test_payload_is_copied(tmp_path: Path):
    bus = _bus(tmp_path)
    payload = {"plan": ["step_1"]}
    bus.emit("t1", "planner", "planner.completed", "success", payload=payload)
    payload["plan"].append("MUTATED_AFTER_EMIT")
    stored = bus.read_events("t1")[0]
    assert stored["payload"]["plan"] == ["step_1"]


# ---------------------------------------------------------------------------
# Test 7: external EventLogManager can be injected
# ---------------------------------------------------------------------------
def test_inject_event_log_manager(tmp_path: Path):
    log = EventLogManager(tmp_path / "custom.json")
    bus = EventBus(event_log=log)
    bus.emit("t1", "system", "task.received", "pending")
    assert len(log.read_events()) == 1
    assert (tmp_path / "custom.json").exists()
