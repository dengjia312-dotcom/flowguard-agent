"""
AgentRuntime — the core execution engine of FlowGuard Agent.

Execution flow (all 11 steps):
  receive_user_task → load_config → load_current_state → call_planner →
  parse_plan_json → validate_plan → check_safety_rules →
  [confirmation_required? → stop] →
  execute_low_risk_tools → write_execution_log → update_state → summarize_result

Guarantees:
  - Model cannot bypass the Runtime to execute actions directly
  - High-risk actions (unlock door, disable camera) require user confirmation
  - Every tool call is logged with tool_name, args, result, status, timestamp
  - If a tool does not return status=success, the summary will NOT claim completion
"""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .events.event_bus import EventBus
from .model_router import ModelRouter
from .schemas.plan_schema import ExecutionPlan, PlanStep
from .state.log_manager import LogManager
from .state.state_manager import StateManager
from .tools.device_tools import DeviceTools
from .tools.file_tools import FileTools
from .tools.rag_tools import RAGTools
from .tools.web_tools import WebTools

# ---------------------------------------------------------------------------
# System prompt for the live planner model (plannerMode = "model")
# ---------------------------------------------------------------------------
PLANNER_SYSTEM_PROMPT = """\
You are FlowGuard Agent's Planner. Your ONLY job is to convert a natural-language user goal \
into a structured ExecutionPlan JSON object.

OUTPUT RULES — strictly enforced by the Runtime:
1. Output MUST be a single valid JSON object. No markdown, no code fences, no explanation.
2. You generate PLANS only. You cannot execute tools, cannot claim task completion.
3. Use ONLY the exact action names listed below. Any other action name will be rejected.
4. The Runtime independently enforces safety — but you must still flag high-risk steps correctly.

AVAILABLE ACTIONS (copy exactly):
  file.read          args: {"filename": "<string>"}
  file.write         args: {"filename": "<string>", "content": "<string>"}
  file.list          args: {}
  device.get_state   args: {"device_id": "<optional string>"}
  device.set_state   args: {"device_id": "<string>", "new_status": "<string>"}
  rag.search         args: {"query": "<string>"}
  web.search         args: {"query": "<string>"}

RISK LEVELS:
  low    — reads, lists, searches
  medium — file writes, non-critical device changes
  high   — door_lock unlock/open, camera off/disabled, file delete, external writes

SAFETY RULES (mandatory):
- door_lock → unlocked/unlock/open  →  risk="high", requires_confirmation=true
- camera    → off/disabled/stopped  →  risk="high", requires_confirmation=true
- file.delete (any)                 →  risk="high", requires_confirmation=true
- Always read device state before setting it when orchestrating devices.

TASK TYPES:
  device_orchestration — controlling smart home devices
  file_summary         — reading/summarising files
  rag_search           — knowledge base search
  general              — other tasks
  unknown              — cannot determine intent (return empty steps)

OUTPUT FORMAT (JSON only, no other text):
{
  "task_type": "device_orchestration|file_summary|rag_search|general|unknown",
  "goal": "<restate the user goal clearly in one sentence>",
  "steps": [
    {
      "id": "step_1",
      "action": "<exact action name from the list above>",
      "args": {},
      "risk": "low|medium|high",
      "requires_confirmation": false,
      "description": "<one-line description>"
    }
  ],
  "conflicts": [],
  "need_user_confirmation": false
}
"""

# All action names the Runtime can dispatch. Used for plan validation.
_KNOWN_ACTIONS: frozenset = frozenset({
    "file.read", "file.write", "file.list",
    "device.get_state", "device.set_state",
    "rag.search", "web.search",
    "shell.exec",   # known but disabled — blocked later in execute stage
})


class AgentRuntime:
    def __init__(
        self,
        config: Dict[str, Any],
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.config = config
        self.model_router = ModelRouter(config)
        self.event_bus = event_bus

        runtime_cfg = config.get("runtime", {})
        self.planner_mode: str = runtime_cfg.get("plannerMode", "live")

        paths = config.get("paths", {})
        workspace = paths.get("workspace", "./workspace")

        self.state_manager = StateManager(paths.get("state", "./data/state.json"))
        self.log_manager = LogManager(
            paths.get("execution_log", "./data/execution_log.json")
        )
        self.file_tools = FileTools(workspace)
        self.device_tools = DeviceTools(workspace)
        self.rag_tools = RAGTools(workspace)
        self.web_tools = WebTools()

        tools_cfg = config.get("tools", {})
        self.enabled_tools: set = set(tools_cfg.get("enabled", []))
        self.disabled_tools: set = set(tools_cfg.get("disabled", []))

    # ------------------------------------------------------------------
    # Event emission helper
    # ------------------------------------------------------------------

    def _emit_event(
        self,
        task_id: str,
        agent: str,
        event_type: str,
        status: str,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Best-effort emit through self.event_bus. Never raises.

        v0.3.0 only emits task.* and planner.* events from this method.
        Reviewer / executor / reporter events are added in later iterations.
        """
        if not self.event_bus:
            return None
        try:
            return self.event_bus.emit(
                task_id=task_id,
                agent=agent,
                event_type=event_type,
                status=status,
                message=message,
                payload=payload,
                step_id=step_id,
                tool_name=tool_name,
            )
        except Exception:
            # Event bus failures must never break the runtime.
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_task(self, message: str) -> Dict[str, Any]:
        """
        Main workflow entry point.
        Steps: receive_user_task → ... → summarize_result
        """
        task_id = str(uuid.uuid4())[:8]

        # Event: task.received
        self._emit_event(
            task_id=task_id,
            agent="system",
            event_type="task.received",
            status="pending",
            message="Task received",
            payload={"message": message},
        )

        # Step: load_current_state
        device_result = self.device_tools.get_state()
        device_state_str = json.dumps(
            device_result.get("devices", {}), ensure_ascii=False, indent=2
        )
        detected_conflicts = self.device_tools.detect_conflicts()

        # Step: call_planner
        self.state_manager.save_task(
            task_id,
            {
                "status": "planning",
                "message": message,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Event: planner.started
        self._emit_event(
            task_id=task_id,
            agent="planner",
            event_type="planner.started",
            status="running",
            message="Planner started",
            payload={"planner_mode": self.planner_mode},
        )

        # Step: call_planner  (mock or model)
        if self.planner_mode == "mock":
            plan_dict = self._mock_planner(message)
        else:
            # plannerMode = "model" — call real LLM
            messages = [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Current device states:\n{device_state_str}\n\n"
                        f"Pre-detected conflicts: {detected_conflicts}\n\n"
                        f"User goal: {message}"
                    ),
                },
            ]
            try:
                planner_response = await self.model_router.call("planner", messages)
            except ValueError as exc:
                err = str(exc)
                error_code = "api_key_missing" if "api_key_missing" in err else "model_call_failed"
                self.state_manager.update_task_status(
                    task_id, "failed", {"error_code": error_code, "detail": err}
                )
                self._emit_event(
                    task_id=task_id,
                    agent="planner",
                    event_type="planner.failed",
                    status="failed",
                    message=f"Planner failed: {error_code}",
                    payload={"reason": error_code},
                )
                self._emit_task_failed(task_id, error_code)
                return {
                    "status": error_code,
                    "task_id": task_id,
                    "message": err,
                }
            except Exception as exc:
                self.state_manager.update_task_status(
                    task_id, "failed", {"error_code": "model_call_failed", "detail": str(exc)}
                )
                self._emit_event(
                    task_id=task_id,
                    agent="planner",
                    event_type="planner.failed",
                    status="failed",
                    message="Planner failed: model_call_failed",
                    payload={"reason": "model_call_failed"},
                )
                self._emit_task_failed(task_id, "model_call_failed")
                return {
                    "status": "model_call_failed",
                    "task_id": task_id,
                    "message": f"Model API call failed: {exc}",
                }

            # Step: parse_plan_json
            plan_dict = self._parse_plan_json(planner_response)
            if plan_dict is None:
                self.state_manager.update_task_status(
                    task_id,
                    "failed",
                    {"error_code": "plan_parse_failed", "raw": planner_response},
                )
                self._emit_event(
                    task_id=task_id,
                    agent="planner",
                    event_type="planner.failed",
                    status="failed",
                    message="Planner failed: plan_parse_failed",
                    payload={"reason": "plan_parse_failed"},
                )
                self._emit_task_failed(task_id, "plan_parse_failed")
                return {
                    "status": "plan_parse_failed",
                    "task_id": task_id,
                    "message": (
                        "Model returned non-JSON output. "
                        "Cannot execute. Check model or retry."
                    ),
                    "raw_planner_response": planner_response,
                }

        # Step: validate_plan — Pydantic schema check
        try:
            plan = ExecutionPlan(**plan_dict)
        except Exception as exc:
            self.state_manager.update_task_status(
                task_id, "failed", {"error_code": "plan_validation_failed", "detail": str(exc)}
            )
            self._emit_event(
                task_id=task_id,
                agent="planner",
                event_type="planner.failed",
                status="failed",
                message="Planner failed: plan_validation_failed",
                payload={"reason": "plan_validation_failed", "detail": str(exc)},
            )
            self._emit_task_failed(task_id, "plan_validation_failed")
            return {
                "status": "plan_validation_failed",
                "task_id": task_id,
                "message": f"Plan schema validation failed: {exc}",
            }

        # Step: validate_plan — unknown action check
        unknown_actions = [
            s.action for s in plan.steps if s.action not in _KNOWN_ACTIONS
        ]
        if unknown_actions:
            self.state_manager.update_task_status(
                task_id,
                "failed",
                {"error_code": "plan_validation_failed", "unknown_actions": unknown_actions},
            )
            self._emit_event(
                task_id=task_id,
                agent="planner",
                event_type="planner.failed",
                status="failed",
                message="Planner failed: plan_validation_failed",
                payload={
                    "reason": "plan_validation_failed",
                    "unknown_actions": unknown_actions,
                },
            )
            self._emit_task_failed(task_id, "plan_validation_failed")
            return {
                "status": "plan_validation_failed",
                "task_id": task_id,
                "message": (
                    f"Plan contains unknown action(s): {unknown_actions}. "
                    "Only registered tool names are allowed."
                ),
                "unknown_actions": unknown_actions,
            }

        # Event: planner.completed (plan parsed and validated successfully)
        self._emit_event(
            task_id=task_id,
            agent="planner",
            event_type="planner.completed",
            status="success",
            message="Planner generated a valid execution plan",
            payload={
                "planner_mode": self.planner_mode,
                "task_type": plan.task_type,
                "goal": plan.goal,
                "steps_count": len(plan.steps),
            },
        )

        # Step: normalize args — canonical field names before safety check & execution
        self._normalize_step_args(plan)

        # Merge runtime-detected conflicts into plan
        if detected_conflicts:
            plan.conflicts = list(set(plan.conflicts + detected_conflicts))

        # Event: safety.started
        self._emit_event(
            task_id=task_id,
            agent="reviewer",
            event_type="safety.started",
            status="running",
            message="Safety reviewer started",
            payload={"steps_count": len(plan.steps)},
        )

        # Step: check_safety_rules
        confirmation_steps = self._check_safety(plan)

        # Step: if confirmation_required → stop
        if confirmation_steps:
            pending_actions = [
                {
                    "step_id": s.id,
                    "action": s.action,
                    "args": s.args,
                    "risk": s.risk,
                    "description": s.description,
                }
                for s in confirmation_steps
            ]
            safe_steps = [
                {
                    "step_id": s.id,
                    "action": s.action,
                    "risk": s.risk,
                    "description": s.description,
                }
                for s in plan.steps
                if not s.requires_confirmation
            ]

            # Event: safety.flagged
            self._emit_event(
                task_id=task_id,
                agent="reviewer",
                event_type="safety.flagged",
                status="waiting_confirmation",
                message=f"Safety reviewer flagged {len(confirmation_steps)} high-risk step(s)",
                payload={
                    "pending_count": len(confirmation_steps),
                    "pending_actions": pending_actions,
                },
            )

            self.state_manager.save_task(
                task_id,
                {
                    "status": "confirmation_required",
                    "message": message,
                    "plan": plan.model_dump(),
                    "pending_actions": pending_actions,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Event: confirmation.required
            self._emit_event(
                task_id=task_id,
                agent="user",
                event_type="confirmation.required",
                status="waiting_confirmation",
                message="User confirmation required",
                payload={"pending_actions": pending_actions},
            )

            return {
                "status": "confirmation_required",
                "task_id": task_id,
                "message": (
                    f"检测到 {len(confirmation_steps)} 个高风险动作，需要用户确认后才能执行。"
                    f"低风险步骤（{len(safe_steps)} 个）已就绪，等待整体确认后统一执行。"
                ),
                "pending_actions": pending_actions,
                "safe_steps_preview": safe_steps,
                "conflicts": plan.conflicts,
            }

        # Event: safety.passed
        self._emit_event(
            task_id=task_id,
            agent="reviewer",
            event_type="safety.passed",
            status="success",
            message="Safety reviewer passed all steps",
            payload={"pending_count": 0},
        )

        # Steps: execute_low_risk_tools → write_execution_log → update_state
        results = await self._execute_steps(task_id, plan.steps)

        self.state_manager.update_task_status(
            task_id,
            "completed",
            {"results": results, "plan": plan.model_dump()},
        )

        # Step: summarize_result
        return self._finalize_task_result(task_id, plan, results)

    async def confirm_task(self, task_id: str, confirmed: bool) -> Dict[str, Any]:
        """Handle POST /agent/confirm"""
        task = self.state_manager.get_task(task_id)
        if not task:
            return {"status": "error", "message": f"Task not found: {task_id}"}

        if task.get("status") != "confirmation_required":
            return {
                "status": "error",
                "message": (
                    f"Task '{task_id}' is not awaiting confirmation. "
                    f"Current status: {task.get('status')}"
                ),
            }

        if not confirmed:
            # Event: confirmation.cancelled
            self._emit_event(
                task_id=task_id,
                agent="user",
                event_type="confirmation.cancelled",
                status="cancelled",
                message="User rejected confirmation",
                payload={"confirmed": False},
            )
            self.state_manager.update_task_status(
                task_id, "cancelled", {"reason": "User rejected confirmation"}
            )
            self._emit_event(
                task_id=task_id,
                agent="system",
                event_type="task.cancelled",
                status="cancelled",
                message="Task cancelled",
                payload={"final_status": "cancelled"},
            )
            return {
                "status": "cancelled",
                "task_id": task_id,
                "message": "Task cancelled by user. No actions were executed.",
            }

        # Event: confirmation.approved
        self._emit_event(
            task_id=task_id,
            agent="user",
            event_type="confirmation.approved",
            status="success",
            message="User approved confirmation",
            payload={"confirmed": True},
        )

        # Execute all steps (confirmation granted)
        plan = ExecutionPlan(**task["plan"])
        results = await self._execute_steps(
            task_id, plan.steps, skip_confirmation_check=True
        )
        self.state_manager.update_task_status(
            task_id, "completed", {"results": results}
        )
        return self._finalize_task_result(task_id, plan, results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_task_failed(self, task_id: str, reason: str) -> None:
        self._emit_event(
            task_id=task_id,
            agent="system",
            event_type="task.failed",
            status="failed",
            message=f"Task failed: {reason}",
            payload={
                "reason": reason,
                "final_status": "failed",
            },
        )

    def _finalize_task_result(
        self,
        task_id: str,
        plan: ExecutionPlan,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        failed_count = len([r for r in results if r.get("status") == "failed"])
        skipped_count = len([r for r in results if r.get("status") == "skipped"])

        self._emit_event(
            task_id=task_id,
            agent="reporter",
            event_type="reporter.started",
            status="running",
            message="Reporter started",
            payload={
                "executed_count": len(results),
                "failed_count": failed_count,
                "skipped_count": skipped_count,
            },
        )

        summary = self._build_summary(task_id, plan, results)
        counts = self._extract_summary_counts(summary)

        self._emit_event(
            task_id=task_id,
            agent="reporter",
            event_type="reporter.summary_created",
            status="success",
            message="Reporter created final summary",
            payload=counts,
        )
        self._emit_task_final_event(task_id, summary, counts)
        return summary

    def _extract_summary_counts(self, result: Any) -> Dict[str, int]:
        if isinstance(result, dict):
            summary_obj = result.get("summary", {})
        else:
            summary_obj = getattr(result, "summary", {})

        def _get(field: str) -> int:
            if isinstance(summary_obj, dict):
                return int(summary_obj.get(field, 0))
            return int(getattr(summary_obj, field, 0))

        return {
            "total_steps": _get("total_steps"),
            "successful": _get("successful"),
            "failed": _get("failed"),
            "pending_confirmation": _get("pending_confirmation"),
            "skipped": _get("skipped"),
        }

    def _emit_task_final_event(
        self,
        task_id: str,
        result: Dict[str, Any],
        counts: Dict[str, int],
    ) -> None:
        final_status = result.get("status")
        if final_status == "completed" and counts["failed"] == 0:
            self._emit_event(
                task_id=task_id,
                agent="system",
                event_type="task.completed",
                status="success",
                message="Task completed",
                payload={
                    "final_status": "completed",
                    "successful": counts["successful"],
                    "failed": 0,
                },
            )
            return

        if final_status == "completed_with_errors":
            self._emit_event(
                task_id=task_id,
                agent="system",
                event_type="task.completed_with_errors",
                status="failed",
                message="Task completed with errors",
                payload={
                    "final_status": "completed_with_errors",
                    "successful": counts["successful"],
                    "failed": counts["failed"],
                },
            )
            return

        if final_status == "failed":
            self._emit_event(
                task_id=task_id,
                agent="system",
                event_type="task.failed",
                status="failed",
                message="Task failed",
                payload={
                    "reason": "execution_failed",
                    "final_status": "failed",
                    "successful": counts["successful"],
                    "failed": counts["failed"],
                },
            )

    def _mock_planner(self, message: str) -> Dict[str, Any]:
        """
        Returns a fixed ExecutionPlan dict based on keyword matching.
        Used when runtime.plannerMode == "mock" to test the full pipeline
        without a real API key.
        """
        # Scenario A: file summary
        if any(kw in message for kw in ["读取 test.md", "总结 test.md"]):
            return {
                "task_type": "file_summary",
                "goal": "读取并总结 test.md",
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

        # Scenario B: home arrival mode
        if any(kw in message for kw in ["回家模式", "我快到家了"]):
            return {
                "task_type": "device_orchestration",
                "goal": "开启回家模式",
                "steps": [
                    {
                        "id": "step_1",
                        "action": "device.get_state",
                        "args": {},
                        "risk": "low",
                        "requires_confirmation": False,
                    },
                    {
                        "id": "step_2",
                        "action": "device.set_state",
                        "args": {"device_id": "light", "status": "on"},
                        "risk": "low",
                        "requires_confirmation": False,
                    },
                    {
                        "id": "step_3",
                        "action": "device.set_state",
                        "args": {"device_id": "air_conditioner", "status": "on"},
                        "risk": "medium",
                        "requires_confirmation": False,
                    },
                    {
                        "id": "step_4",
                        "action": "device.set_state",
                        "args": {"device_id": "robot_vacuum", "status": "paused"},
                        "risk": "low",
                        "requires_confirmation": False,
                    },
                    {
                        "id": "step_5",
                        "action": "device.set_state",
                        "args": {"device_id": "door_lock", "status": "unlocked"},
                        "risk": "high",
                        "requires_confirmation": True,
                    },
                ],
                "conflicts": [],
                "need_user_confirmation": True,
            }

        # Default fallback
        return {
            "task_type": "general",
            "goal": message,
            "steps": [],
            "conflicts": [],
            "need_user_confirmation": False,
        }

    def _parse_plan_json(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Robustly extract a JSON dict from a planner response.

        Degradation order:
          1. Raw text — json.loads directly (happy path)
          2. Double-encoded — if json.loads returns a string, parse again
          3. Code fence stripped — ```json ... ``` or ``` ... ```
          4. Prose-embedded — extract first {...} block from surrounding text

        Never raises. Returns None only when all attempts fail.
        """
        text = response.strip()

        def _try_parse(s: str) -> Optional[Dict[str, Any]]:
            """Try to parse s as JSON dict, handling double-encoded strings."""
            s = s.strip()
            try:
                result = json.loads(s)
            except json.JSONDecodeError:
                return None
            if isinstance(result, dict):
                return result
            # Double-encoded: model returned a JSON-serialised string
            # e.g. the raw text is "\"{ \\\"task_type\\\": ...}\""
            if isinstance(result, str):
                try:
                    inner = json.loads(result)
                    if isinstance(inner, dict):
                        return inner
                except json.JSONDecodeError:
                    pass
            return None

        # 1. Happy path — model followed instructions and returned plain JSON
        parsed = _try_parse(text)
        if parsed is not None:
            return parsed

        # 2. Strip ```json ... ``` or ``` ... ``` code fences
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            m = re.search(pattern, text)
            if m:
                parsed = _try_parse(m.group(1))
                if parsed is not None:
                    return parsed

        # 3. Extract first complete {...} block (handles prose before/after JSON)
        m = re.search(r"(\{[\s\S]*\})", text)
        if m:
            parsed = _try_parse(m.group(1))
            if parsed is not None:
                return parsed

        return None

    def _normalize_step_args(self, plan: ExecutionPlan) -> None:
        """
        Normalize step args in-place to canonical field names before execution.

        Canonical fields:
          device.set_state : "status"   (live planner may produce "new_status")
          file.read/write  : "filename" (mock planner may produce "path")
        """
        for step in plan.steps:
            if step.action == "device.set_state":
                if "new_status" in step.args and "status" not in step.args:
                    step.args["status"] = step.args.pop("new_status")
            if step.action in ("file.read", "file.write"):
                if "path" in step.args and "filename" not in step.args:
                    step.args["filename"] = step.args.pop("path")

    def _check_safety(self, plan: ExecutionPlan) -> List[PlanStep]:
        """
        Enforce safety rules from agent.config.json + runtime checks.
        Returns the list of steps that require user confirmation.
        """
        confirmation_steps: List[PlanStep] = []
        safety_cfg = self.config.get("safety", {})
        forbidden = set(safety_cfg.get("forbidden_tools", []))

        for step in plan.steps:
            needs_confirm = step.requires_confirmation  # planner already flagged it

            # Runtime enforcement: forbidden tools always require confirm (or are blocked)
            if step.action in forbidden:
                step.requires_confirmation = True
                needs_confirm = True

            # Runtime enforcement: device-level high-risk state changes
            if step.action == "device.set_state":
                device_id = step.args.get("device_id", "")
                # Accept both "new_status" (live planner) and "status" (mock planner)
                new_status = step.args.get("new_status") or step.args.get("status", "")
                if self.device_tools.needs_confirmation(device_id, new_status):
                    step.requires_confirmation = True
                    needs_confirm = True

            if needs_confirm:
                confirmation_steps.append(step)

        return confirmation_steps

    async def _execute_steps(
        self,
        task_id: str,
        steps: List[PlanStep],
        skip_confirmation_check: bool = False,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for step in steps:
            self._emit_event(
                task_id=task_id,
                agent="executor",
                event_type="executor.step_started",
                status="running",
                step_id=step.id,
                tool_name=step.action,
                payload={
                    "args": dict(step.args),
                    "risk": step.risk,
                },
            )

            # High-risk step not yet confirmed → log as pending, skip execution
            if step.requires_confirmation and not skip_confirmation_check:
                record = self._make_log_record(
                    task_id, step, {"message": "Awaiting user confirmation"}, "pending_confirmation"
                )
                self.log_manager.append(record)
                self._emit_executor_step_completed(task_id, step, record)
                results.append(record)
                continue

            # Disabled tools → block execution
            if step.action in self.disabled_tools:
                record = self._make_log_record(
                    task_id,
                    step,
                    {"error": f"Tool '{step.action}' is disabled in agent.config.json"},
                    "skipped",
                )
                self.log_manager.append(record)
                self._emit_executor_step_completed(task_id, step, record)
                results.append(record)
                continue

            # Unknown tools → fail gracefully
            if step.action not in self.enabled_tools:
                record = self._make_log_record(
                    task_id,
                    step,
                    {"error": f"Unknown tool: '{step.action}'. Not in enabled list."},
                    "failed",
                )
                self.log_manager.append(record)
                self._emit_executor_step_completed(task_id, step, record)
                results.append(record)
                continue

            # Execute
            try:
                result = await self._dispatch_tool(step)
                status = "success" if result.get("status") == "success" else "failed"
            except Exception as exc:
                result = {"error": str(exc)}
                status = "failed"

            record = self._make_log_record(task_id, step, result, status)
            self.log_manager.append(record)
            self._emit_executor_step_completed(task_id, step, record)
            results.append(record)

        return results

    def _emit_executor_step_completed(
        self,
        task_id: str,
        step: PlanStep,
        record: Dict[str, Any],
    ) -> None:
        result = record.get("result")
        result_status = result.get("status") if isinstance(result, dict) else None
        error = result.get("error") if isinstance(result, dict) else None
        event_status = {
            "success": "success",
            "failed": "failed",
            "skipped": "skipped",
            "pending_confirmation": "waiting_confirmation",
        }.get(record.get("status"), "failed")

        self._emit_event(
            task_id=task_id,
            agent="executor",
            event_type="executor.step_completed",
            status=event_status,
            step_id=step.id,
            tool_name=step.action,
            payload={
                "args": dict(step.args),
                "result_status": result_status,
                "error": error,
            },
        )

    async def _dispatch_tool(self, step: PlanStep) -> Dict[str, Any]:
        action = step.action
        args = step.args

        if action == "file.read":
            # Accept both "filename" (live planner) and "path" (mock planner)
            filename = args.get("filename") or args.get("path", "")
            return self.file_tools.read(filename)
        if action == "file.write":
            filename = args.get("filename") or args.get("path", "")
            return self.file_tools.write(filename, args.get("content", ""))
        if action == "file.list":
            return self.file_tools.list_files(args.get("pattern", "*"))
        if action == "device.get_state":
            return self.device_tools.get_state(args.get("device_id"))
        if action == "device.set_state":
            # Accept both "new_status" (live planner) and "status" (mock planner)
            new_status = args.get("new_status") or args.get("status", "")
            return self.device_tools.set_state(
                args.get("device_id", ""),
                new_status,
                args.get("properties"),
            )
        if action == "rag.search":
            return self.rag_tools.search(
                args.get("query", ""), args.get("top_k", 3)
            )
        if action == "web.search":
            return self.web_tools.search(args.get("query", ""))
        if action == "shell.exec":
            return {
                "status": "failed",
                "error": "shell.exec is disabled in v0.1 for safety. Enable with extreme caution.",
            }

        return {"status": "failed", "error": f"Unhandled tool: '{action}'"}

    def _make_log_record(
        self,
        task_id: str,
        step: PlanStep,
        result: Any,
        status: str,
    ) -> Dict[str, Any]:
        return {
            "task_id": task_id,
            "step_id": step.id,
            "tool_name": step.action,
            "args": step.args,
            "result": result,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _build_summary(
        self,
        task_id: str,
        plan: ExecutionPlan,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") == "failed"]
        pending = [r for r in results if r.get("status") == "pending_confirmation"]
        skipped = [r for r in results if r.get("status") == "skipped"]

        # Guard: never claim "completed" if there are failures
        overall_status = "completed"
        if failed:
            overall_status = "completed_with_errors"
        if len(successful) == 0 and len(failed) > 0:
            overall_status = "failed"

        return {
            "status": overall_status,
            "task_id": task_id,
            "goal": plan.goal,
            "summary": {
                "total_steps": len(plan.steps),
                "successful": len(successful),
                "failed": len(failed),
                "pending_confirmation": len(pending),
                "skipped": len(skipped),
            },
            "executed_actions": [
                {
                    "step_id": r["step_id"],
                    "tool": r["tool_name"],
                    "status": r["status"],
                    "result": r.get("result"),
                }
                for r in results
            ],
            "conflicts": plan.conflicts,
            "note": (
                "Some steps failed — task is NOT fully completed."
                if failed
                else "All steps executed successfully."
            ),
        }
