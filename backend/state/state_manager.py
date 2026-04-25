import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class StateManager:
    """
    Manages task lifecycle state in data/state.json.

    Each task has a status lifecycle:
      planning → confirmation_required → completed | cancelled | failed
    """

    def __init__(self, state_path: str) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write({"tasks": {}})

    def _read(self) -> Dict[str, Any]:
        with open(self.state_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        state = self._read()
        return state.get("tasks", {}).get(task_id)

    def save_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        state = self._read()
        if "tasks" not in state:
            state["tasks"] = {}
        state["tasks"][task_id] = {
            **task_data,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        self._write(state)

    def update_task_status(
        self, task_id: str, status: str, extra: Optional[Dict[str, Any]] = None
    ) -> None:
        state = self._read()
        if "tasks" not in state:
            state["tasks"] = {}
        task = state["tasks"].setdefault(task_id, {})
        task["status"] = status
        task["updatedAt"] = datetime.now(timezone.utc).isoformat()
        if extra:
            task.update(extra)
        self._write(state)

    def get_all(self) -> Dict[str, Any]:
        return self._read()
