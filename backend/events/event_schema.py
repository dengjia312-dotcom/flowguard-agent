"""
AgentEvent — the canonical event record for FlowGuard's v0.3 event runtime.

Design notes:
  - `agent` and `status` are validated against allow-lists so the dashboard /
    pixel-office layer can rely on a stable vocabulary.
  - `event_type` is intentionally a free-form string so new agent roles can
    introduce new event types without a schema migration.
  - `payload` uses default_factory=dict to avoid the classic mutable-default
    aliasing bug between event instances.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


# Allowed values for `agent`. Kept as a frozenset (not Enum) so adding a new
# role in a later release does not invalidate previously persisted events.
ALLOWED_AGENTS = frozenset({
    "planner",
    "executor",
    "reviewer",
    "reporter",
    "user",
    "system",
})

ALLOWED_STATUSES = frozenset({
    "pending",
    "running",
    "success",
    "failed",
    "waiting_confirmation",
    "skipped",
    "cancelled",
})


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentEvent(BaseModel):
    """A single event emitted by some agent role within a task's lifecycle."""

    # Required
    event_id: str = Field(default_factory=_new_event_id)
    task_id: str
    timestamp: str = Field(default_factory=_utc_now_iso)
    agent: str
    event_type: str
    status: str

    # Optional
    message: Optional[str] = None
    step_id: Optional[str] = None
    tool_name: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None

    @field_validator("agent")
    @classmethod
    def _check_agent(cls, v: str) -> str:
        if v not in ALLOWED_AGENTS:
            raise ValueError(
                f"agent must be one of {sorted(ALLOWED_AGENTS)}, got {v!r}"
            )
        return v

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALLOWED_STATUSES)}, got {v!r}"
            )
        return v
