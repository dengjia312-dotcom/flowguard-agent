from pydantic import BaseModel
from typing import Any, Dict, Optional


class ToolCallRecord(BaseModel):
    """Represents a single tool call recorded in execution_log.json."""
    task_id: str
    step_id: Optional[str] = None
    tool_name: str
    args: Dict[str, Any]
    result: Any
    status: str  # success | failed | skipped | pending_confirmation
    timestamp: str
    error: Optional[str] = None
