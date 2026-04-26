"""
EventLogManager — append-only persistent storage for AgentEvent records.

Stored at `data/events.json` by default, with structure:

    {"events": [ {...AgentEvent...}, ... ]}

Independent of `data/state.json` and `data/execution_log.json` so the v0.2
behaviour stays untouched.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .event_schema import AgentEvent


class EventLogManager:
    DEFAULT_PATH = "./data/events.json"

    def __init__(self, log_path: Union[str, Path, None] = None) -> None:
        self.log_path = Path(log_path) if log_path else Path(self.DEFAULT_PATH)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self._write({"events": []})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, event: Union[AgentEvent, Dict[str, Any]]) -> Dict[str, Any]:
        """Append one event. Accepts either an AgentEvent or a plain dict.

        Plain dicts are validated through AgentEvent so defaults
        (event_id, timestamp) are filled in consistently.
        """
        if isinstance(event, AgentEvent):
            record = event.model_dump()
        elif isinstance(event, dict):
            record = AgentEvent(**event).model_dump()
        else:
            raise TypeError(
                f"event must be AgentEvent or dict, got {type(event).__name__}"
            )

        data = self._read()
        data["events"].append(record)
        self._write(data)
        return record

    def read_events(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all events, or only those matching task_id if given."""
        events = self._read().get("events", [])
        if task_id is None:
            return events
        return [e for e in events if e.get("task_id") == task_id]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read(self) -> Dict[str, Any]:
        """Read the events file. Returns a safe empty shell on any read error."""
        if not self.log_path.exists():
            return {"events": []}
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                return {"events": []}
            data = json.loads(content)
        except (json.JSONDecodeError, OSError):
            return {"events": []}

        if not isinstance(data, dict):
            return {"events": []}
        events = data.get("events")
        if not isinstance(events, list):
            return {"events": []}
        return {"events": events}

    def _write(self, data: Dict[str, Any]) -> None:
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
