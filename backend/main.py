"""
FlowGuard Agent — FastAPI application entry point.

Run from the flowguard-agent/ directory:
  uvicorn backend.main:app --reload --port 8000

Endpoints:
  GET  /health          — liveness check
  POST /agent/run       — submit a task
  GET  /agent/state     — view all task states
  GET  /agent/logs      — view execution log
  POST /agent/confirm   — confirm or reject a pending high-risk task
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load .env before importing anything that reads env vars
load_dotenv()

from .config_loader import ConfigLoader
from .agent_runtime import AgentRuntime

# Resolve config path relative to project root (flowguard-agent/)
_CONFIG_PATH = Path(__file__).parent.parent / "agent.config.json"
config = ConfigLoader.load(str(_CONFIG_PATH))

app = FastAPI(
    title="FlowGuard Agent",
    version="0.1.0",
    description="Workflow-first AI Agent Runtime for multi-device task orchestration",
)
runtime = AgentRuntime(config)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    task_id: str
    confirm: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness check."""
    return {
        "status": "ok",
        "service": config["app"]["name"],
        "version": config["app"]["version"],
    }


@app.post("/agent/run")
async def agent_run(req: RunRequest):
    """
    Submit a natural language task to the agent.

    If the plan contains high-risk actions (e.g. door unlock), returns:
      {"status": "confirmation_required", "task_id": "...", "pending_actions": [...]}

    Call POST /agent/confirm with task_id to proceed or cancel.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return await runtime.run_task(req.message)


@app.get("/agent/state")
def agent_state():
    """Return all task states from data/state.json."""
    return runtime.state_manager.get_all()


@app.get("/agent/logs")
def agent_logs():
    """Return all execution log entries from data/execution_log.json."""
    return {"logs": runtime.log_manager.get_all()}


@app.post("/agent/confirm")
async def agent_confirm(req: ConfirmRequest):
    """
    Confirm or reject a task that is waiting for user approval.

    Body: {"task_id": "abc12345", "confirm": true}

    confirm=true  → execute all pending high-risk steps
    confirm=false → cancel the task, no actions executed
    """
    return await runtime.confirm_task(req.task_id, req.confirm)
