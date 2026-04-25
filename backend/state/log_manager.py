import json
from pathlib import Path
from typing import Any, Dict, List


class LogManager:
    """
    Append-only execution log in data/execution_log.json.

    Every tool call is written here with:
      task_id, step_id, tool_name, args, result, status, timestamp
    """

    def __init__(self, log_path: str) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self._write({"logs": []})

    def _read(self) -> Dict[str, Any]:
        with open(self.log_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def append(self, record: Dict[str, Any]) -> None:
        data = self._read()
        data["logs"].append(record)
        self._write(data)

    def get_all(self) -> List[Dict[str, Any]]:
        return self._read().get("logs", [])

    def get_by_task(self, task_id: str) -> List[Dict[str, Any]]:
        return [log for log in self.get_all() if log.get("task_id") == task_id]
