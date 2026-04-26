"""
FlowGuard Agent v0.3 — Multi-Agent Event Runtime foundation.

This package provides the event-stream substrate that future Planner /
Executor / Safety Reviewer / Reporter agent classes will plug into. It is
intentionally minimal in v0.3.0:

  - AgentEvent     : the canonical event record
  - EventLogManager: append-only persistent log (data/events.json)
  - EventBus       : central emit + subscribe surface

It does NOT yet wire into AgentRuntime. That happens in a later step.
"""
from .event_bus import EventBus
from .event_log import EventLogManager
from .event_schema import (
    ALLOWED_AGENTS,
    ALLOWED_STATUSES,
    AgentEvent,
)

__all__ = [
    "AgentEvent",
    "EventBus",
    "EventLogManager",
    "ALLOWED_AGENTS",
    "ALLOWED_STATUSES",
]
