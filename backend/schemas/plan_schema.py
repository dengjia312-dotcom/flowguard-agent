from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict


class PlanStep(BaseModel):
    id: str
    action: str
    args: Dict[str, Any] = Field(default_factory=dict)
    risk: str = "low"  # low | medium | high
    requires_confirmation: bool = False
    description: Optional[str] = None


class ExecutionPlan(BaseModel):
    task_type: str
    goal: str
    steps: List[PlanStep]
    conflicts: List[str] = Field(default_factory=list)
    need_user_confirmation: bool = False
