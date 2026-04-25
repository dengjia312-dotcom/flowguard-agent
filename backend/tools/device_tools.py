import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Device + status combinations that require explicit user confirmation before execution.
# Format: {device_id: [status_values_requiring_confirmation]}
HIGH_RISK_STATES: Dict[str, list] = {
    "door_lock": ["unlock", "unlocked", "open"],
    "camera": ["off", "disabled", "stopped"],
}


class DeviceTools:
    """
    Simulates smart home device state management.
    Reads/writes workspace/device_state.json as the source of truth.
    """

    def __init__(self, workspace_path: str) -> None:
        self.device_state_path = Path(workspace_path) / "device_state.json"

    def _read_state(self) -> Dict[str, Any]:
        if not self.device_state_path.exists():
            return {}
        with open(self.device_state_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_state(self, state: Dict[str, Any]) -> None:
        with open(self.device_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def get_state(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            state = self._read_state()
            if device_id:
                if device_id not in state:
                    return {"status": "failed", "error": f"Device not found: '{device_id}'"}
                return {"status": "success", "device_id": device_id, "state": state[device_id]}
            return {"status": "success", "devices": state, "count": len(state)}
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def set_state(
        self,
        device_id: str,
        new_status: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            state = self._read_state()
            if device_id not in state:
                return {"status": "failed", "error": f"Device not found: '{device_id}'"}

            device = state[device_id]
            old_status = device.get("status")
            device["status"] = new_status
            device["lastUpdated"] = datetime.now(timezone.utc).isoformat()
            if properties:
                device.update(properties)

            self._write_state(state)
            return {
                "status": "success",
                "device_id": device_id,
                "old_status": old_status,
                "new_status": new_status,
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def needs_confirmation(self, device_id: str, new_status: str) -> bool:
        """Returns True if this state change requires user confirmation."""
        high_risk = HIGH_RISK_STATES.get(device_id, [])
        return new_status.lower() in [s.lower() for s in high_risk]

    def detect_conflicts(self) -> list:
        """
        Detect known conflicting device states.
        Returns a list of conflict description strings.
        """
        try:
            state = self._read_state()
            conflicts = []

            window = state.get("window", {}).get("status", "closed")
            ac = state.get("air_conditioner", {}).get("status", "off")
            if window in ("open", "on") and ac in ("on", "cooling", "heating"):
                conflicts.append(
                    "Energy conflict: window is open while air conditioner is running"
                )

            camera = state.get("camera", {}).get("status", "on")
            door = state.get("door_lock", {}).get("status", "locked")
            if camera in ("off", "disabled") and door in ("unlock", "unlocked", "open"):
                conflicts.append(
                    "Security conflict: camera is disabled while door lock is unlocked"
                )

            vacuum = state.get("robot_vacuum", {}).get("status", "idle")
            if vacuum in ("cleaning", "on") and door in ("unlock", "unlocked", "open"):
                conflicts.append(
                    "State conflict: robot vacuum is running while home entry is being activated"
                )

            return conflicts
        except Exception:
            return []
