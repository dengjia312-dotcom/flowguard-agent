"""
Unit tests for backend/events/event_log.py — the EventLogManager.

Run with:
    cd flowguard-agent
    pytest tests/test_event_log_manager.py -v

Tests use pytest's tmp_path fixture so they never touch real data/events.json.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.events.event_log import EventLogManager  # noqa: E402
from backend.events.event_schema import AgentEvent  # noqa: E402


def _make_event(task_id: str = "t1", **overrides) -> AgentEvent:
    base = dict(
        task_id=task_id,
        agent="planner",
        event_type="planner.started",
        status="running",
    )
    base.update(overrides)
    return AgentEvent(**base)


# ---------------------------------------------------------------------------
# Test 1: append auto-creates the file when missing
# ---------------------------------------------------------------------------
def test_append_creates_file_when_missing(tmp_path: Path):
    p = tmp_path / "events.json"
    mgr = EventLogManager(p)
    # __init__ creates an empty shell, so the file already exists
    assert p.exists()
    mgr.append(_make_event())
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["events"] and data["events"][0]["task_id"] == "t1"


# ---------------------------------------------------------------------------
# Test 2: read_events returns appended events
# ---------------------------------------------------------------------------
def test_read_after_append(tmp_path: Path):
    p = tmp_path / "events.json"
    mgr = EventLogManager(p)
    mgr.append(_make_event(task_id="t1"))
    events = mgr.read_events()
    assert len(events) == 1
    assert events[0]["task_id"] == "t1"
    assert events[0]["agent"] == "planner"


# ---------------------------------------------------------------------------
# Test 3: read_events(task_id) filters correctly
# ---------------------------------------------------------------------------
def test_filter_by_task_id(tmp_path: Path):
    p = tmp_path / "events.json"
    mgr = EventLogManager(p)
    mgr.append(_make_event(task_id="t1"))
    mgr.append(_make_event(task_id="t2"))
    mgr.append(_make_event(task_id="t1"))
    assert len(mgr.read_events()) == 3
    assert len(mgr.read_events("t1")) == 2
    assert len(mgr.read_events("t2")) == 1
    assert len(mgr.read_events("does-not-exist")) == 0


# ---------------------------------------------------------------------------
# Test 4: append never overwrites prior history (append-only invariant)
# ---------------------------------------------------------------------------
def test_append_does_not_overwrite(tmp_path: Path):
    p = tmp_path / "events.json"
    mgr = EventLogManager(p)
    for i in range(5):
        mgr.append(_make_event(task_id=f"t{i}"))
    events = mgr.read_events()
    assert len(events) == 5
    assert {e["task_id"] for e in events} == {f"t{i}" for i in range(5)}


# ---------------------------------------------------------------------------
# Test 5: corrupt JSON does not crash; manager keeps working
# ---------------------------------------------------------------------------
def test_handles_corrupt_json(tmp_path: Path):
    p = tmp_path / "events.json"
    p.write_text("{not valid json", encoding="utf-8")
    mgr = EventLogManager(p)
    # Reading corrupt content yields an empty list rather than raising
    assert mgr.read_events() == []
    # Append still works and rewrites the file as valid JSON
    mgr.append(_make_event())
    assert len(mgr.read_events()) == 1
    # File is now well-formed
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "events" in data and len(data["events"]) == 1


# ---------------------------------------------------------------------------
# Test 6: empty file is treated as "no events yet"
# ---------------------------------------------------------------------------
def test_handles_empty_file(tmp_path: Path):
    p = tmp_path / "events.json"
    p.write_text("", encoding="utf-8")
    mgr = EventLogManager(p)
    assert mgr.read_events() == []
    mgr.append(_make_event())
    assert len(mgr.read_events()) == 1


# ---------------------------------------------------------------------------
# Test 7: append accepts both AgentEvent and plain dicts (validated)
# ---------------------------------------------------------------------------
def test_append_accepts_dict(tmp_path: Path):
    p = tmp_path / "events.json"
    mgr = EventLogManager(p)
    record = mgr.append({
        "task_id": "t1",
        "agent": "system",
        "event_type": "task.received",
        "status": "pending",
    })
    # AgentEvent defaults filled in
    assert record["event_id"]
    assert record["timestamp"]
    assert record["payload"] == {}
