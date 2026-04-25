"""
Unit tests for AgentRuntime._parse_plan_json and _normalize_step_args.

Run with:
    cd flowguard-agent
    pytest tests/test_parse_plan_json.py -v

These tests do NOT require a real API key or any running service.
"""

import json
import sys
import os
import types

# ---------------------------------------------------------------------------
# Minimal stubs so AgentRuntime can be instantiated without the full stack
# ---------------------------------------------------------------------------

# Stub out heavy dependencies before importing agent_runtime
for mod_name in [
    "backend.model_router",
    "backend.state.state_manager",
    "backend.state.log_manager",
    "backend.tools.device_tools",
    "backend.tools.file_tools",
    "backend.tools.rag_tools",
    "backend.tools.web_tools",
]:
    sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

# Provide stub classes that AgentRuntime imports by name
sys.modules["backend.model_router"].ModelRouter = lambda cfg: None  # type: ignore
sys.modules["backend.state.state_manager"].StateManager = lambda p: None  # type: ignore
sys.modules["backend.state.log_manager"].LogManager = lambda p: None  # type: ignore
sys.modules["backend.tools.device_tools"].DeviceTools = lambda w: None  # type: ignore
sys.modules["backend.tools.file_tools"].FileTools = lambda w: None  # type: ignore
sys.modules["backend.tools.rag_tools"].RAGTools = lambda w: None  # type: ignore
sys.modules["backend.tools.web_tools"].WebTools = lambda: None  # type: ignore

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.agent_runtime import AgentRuntime  # noqa: E402
from backend.schemas.plan_schema import ExecutionPlan  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal config to construct AgentRuntime without crashing
# ---------------------------------------------------------------------------
_CFG = {
    "runtime": {"plannerMode": "mock"},
    "paths": {},
    "tools": {"enabled": [], "disabled": []},
}

_RUNTIME = AgentRuntime.__new__(AgentRuntime)
_RUNTIME.config = _CFG
# _parse_plan_json only uses self implicitly (it's a plain method), no other attrs needed


# ---------------------------------------------------------------------------
# Shared fixture: a valid plan dict
# ---------------------------------------------------------------------------
_VALID_PLAN = {
    "task_type": "file_summary",
    "goal": "Read test.md",
    "steps": [
        {
            "id": "step_1",
            "action": "file.read",
            "args": {"filename": "test.md"},
            "risk": "low",
            "requires_confirmation": False,
            "description": "Read the file",
        }
    ],
    "conflicts": [],
    "need_user_confirmation": False,
}


# ---------------------------------------------------------------------------
# Test 1: plain JSON — happy path
# ---------------------------------------------------------------------------
def test_plain_json():
    raw = json.dumps(_VALID_PLAN)
    result = _RUNTIME._parse_plan_json(raw)
    assert result is not None, "Should parse plain JSON"
    assert result["task_type"] == "file_summary"
    assert result["steps"][0]["action"] == "file.read"


# ---------------------------------------------------------------------------
# Test 2: ```json ... ``` code fence
# ---------------------------------------------------------------------------
def test_json_code_fence():
    raw = "```json\n" + json.dumps(_VALID_PLAN) + "\n```"
    result = _RUNTIME._parse_plan_json(raw)
    assert result is not None, "Should parse ```json fenced response"
    assert result["goal"] == "Read test.md"


# ---------------------------------------------------------------------------
# Test 3: double-encoded JSON string (escaped)
# ---------------------------------------------------------------------------
def test_double_encoded_json():
    # Simulate model wrapping JSON in an outer string:
    # raw = '"{\\"task_type\\": \\"file_summary\\", ...}"'
    inner = json.dumps(_VALID_PLAN)
    raw = json.dumps(inner)  # outer string-encode
    result = _RUNTIME._parse_plan_json(raw)
    assert result is not None, "Should handle double-encoded JSON"
    assert result["task_type"] == "file_summary"


# ---------------------------------------------------------------------------
# Test 4: unparseable — must return None, never execute
# ---------------------------------------------------------------------------
def test_unparseable_returns_none():
    raw = "Sorry, I cannot generate a plan for this request."
    result = _RUNTIME._parse_plan_json(raw)
    assert result is None, "Unparseable text must return None (triggers plan_parse_failed)"


# ---------------------------------------------------------------------------
# Test 5: JSON embedded in prose
# ---------------------------------------------------------------------------
def test_json_embedded_in_prose():
    raw = (
        "Sure! Here is the plan you requested:\n\n"
        + json.dumps(_VALID_PLAN)
        + "\n\nLet me know if you need changes."
    )
    result = _RUNTIME._parse_plan_json(raw)
    assert result is not None, "Should extract JSON from surrounding prose"
    assert result["task_type"] == "file_summary"


# ---------------------------------------------------------------------------
# Test 6: _normalize_step_args — new_status → status
# ---------------------------------------------------------------------------
def test_normalize_new_status_to_status():
    plan_dict = {
        "task_type": "device_orchestration",
        "goal": "Unlock door",
        "steps": [
            {
                "id": "step_1",
                "action": "device.set_state",
                "args": {"device_id": "door_lock", "new_status": "unlocked"},
                "risk": "high",
                "requires_confirmation": True,
            }
        ],
        "conflicts": [],
        "need_user_confirmation": True,
    }
    plan = ExecutionPlan(**plan_dict)
    _RUNTIME._normalize_step_args(plan)
    step_args = plan.steps[0].args
    assert "status" in step_args, "new_status should be renamed to status"
    assert step_args["status"] == "unlocked"
    assert "new_status" not in step_args, "new_status key should be removed after rename"


# ---------------------------------------------------------------------------
# Test 7: _normalize_step_args — path → filename for file.read
# ---------------------------------------------------------------------------
def test_normalize_path_to_filename():
    plan_dict = {
        "task_type": "file_summary",
        "goal": "Read test.md",
        "steps": [
            {
                "id": "step_1",
                "action": "file.read",
                "args": {"path": "test.md"},
                "risk": "low",
                "requires_confirmation": False,
            }
        ],
        "conflicts": [],
        "need_user_confirmation": False,
    }
    plan = ExecutionPlan(**plan_dict)
    _RUNTIME._normalize_step_args(plan)
    step_args = plan.steps[0].args
    assert "filename" in step_args, "path should be renamed to filename"
    assert step_args["filename"] == "test.md"
    assert "path" not in step_args, "path key should be removed after rename"
