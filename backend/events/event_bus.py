"""
EventBus — central emitter for FlowGuard Agent events.

v0.3.0 keeps this deliberately simple:
  - Synchronous emit (no async queue, no SSE, no WebSocket).
  - Persists every event via EventLogManager.
  - Calls all registered subscriber callbacks; subscriber failures are
    swallowed so a misbehaving consumer cannot break the runtime.

Future evolution paths (NOT implemented in v0.3.0):
  - Per-agent subclasses (PlannerAgent / ExecutorAgent / ReviewerAgent /
    ReporterAgent) that own the emit calls for their lifecycle stage.
  - Async queue + SSE/WebSocket fan-out for the dashboard.
  - Optional in-memory ring buffer for fast tail reads.

The public API (emit / subscribe / unsubscribe / read_events) is shaped to
support all of the above without breaking callers.
"""
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path

from .event_log import EventLogManager
from .event_schema import AgentEvent


EventCallback = Callable[[Dict[str, Any]], None]


class EventBus:
    def __init__(
        self,
        event_log: Optional[EventLogManager] = None,
        event_log_path: Union[str, Path, None] = None,
    ) -> None:
        """
        Args:
            event_log: a pre-built EventLogManager. Takes precedence.
            event_log_path: file path; used to construct an EventLogManager
                            if `event_log` is not supplied. Useful in tests.
        """
        if event_log is not None:
            self.event_log = event_log
        else:
            self.event_log = EventLogManager(event_log_path)
        self._subscribers: List[EventCallback] = []

    # ------------------------------------------------------------------
    # Emit / read
    # ------------------------------------------------------------------

    def emit(
        self,
        task_id: str,
        agent: str,
        event_type: str,
        status: str,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build, persist, and broadcast a single AgentEvent.

        Returns the persisted event dict (with auto-filled event_id / timestamp).
        """
        event = AgentEvent(
            task_id=task_id,
            agent=agent,
            event_type=event_type,
            status=status,
            message=message,
            payload=dict(payload) if payload else {},
            step_id=step_id,
            tool_name=tool_name,
        )
        record = self.event_log.append(event)

        # Iterate over a snapshot so subscribers can unsubscribe themselves
        # mid-broadcast without mutating the live list.
        for cb in list(self._subscribers):
            try:
                cb(record)
            except Exception:
                # Subscribers must never break the runtime.
                # In production we'd log this; for v0.3.0 we swallow silently
                # since the runtime has no logger wired in yet.
                pass

        return record

    def read_events(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.event_log.read_events(task_id)

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, callback: EventCallback) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)
