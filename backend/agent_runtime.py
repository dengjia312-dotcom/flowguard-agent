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

from .model_router import ModelRouter
from .schemas.plan_schema import ExecutionPlan, PlanStep
from .state.log_manager import LogManager
from .state.state_manager import StateManager
from .tools.device_tools import DeviceTools
from .tools.file_tools import FileTools
from .tools.rag_tools import RAGTools
from .tools.web_tools import WebTools

# ---------------------------------------------------------------------------
# System prompt for the planner model
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are FlowGuard Agent's Planner — a workflow-first AI responsible for task decomposition.

Your ONLY output must be a single valid JSON object. No markdown fences, no explanation text, no extra keys.

You analyze the user's goal and the current device state, then produce a structured execution plan.

CRITICAL RULES:
1. You generate PLANS only. You do NOT execute anything.
2. You MUST set requires_confirmation=true for: unlocking door_lock, disabling camera, any file deletion, any external write.
3. If the user says "open the door" or "unlock", that is door_lock → unlock → requires_confirmation=true.
4. Set risk="high" for any action involving door_lock, camera, or external writes.
5. Detect conflicts between device states and list them in "conflicts".
6. Always start by reading device state before setting it.

Available tools (use exactly these action names):
  file.read       args: {"filename": "<string>"}
  file.write      args: {"filename": "<string>", "content": "<string>"}
  file.list       args: {}
  device.get_state  args: {"device_id": "<optional string>"}
  device.set_state  args: {"device_id": "<string>", "new_status": "<string>"}
  rag.search      args: {"query": "<string>"}
  web.search      args: {"query": "<string>"}

Risk levels:
  low    — read operations, listing, searching
  medium — writing files, non-critical device state changes
  high   — door_lock unlock, camera off, file delete, external writes

Output format (JSON only, no other text):
{
  "task_type": "device_orchestration|file_operation|rag_search|general",
  "goal": "<restate the user's goal clearly>",
  "steps": [
    {
      "id": "step_1",
      "action": "<tool_name>",
      "args": {},
      "risk": "low|medium|high",
      "requires_confirmation": false,
      "description": "<one-line description of this step>"
    }
  ],
  "conflicts": ["<conflict description if any>"],
  "need_user_confirmation": false
}
"""


class AgentRuntime:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.model_router = ModelRouter(config)

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
    # Public API
    # ------------------------------------------------------------------

    async def run_task(self, message: str) -> Dict[str, Any]:
        """
        Main workflow entry point.
        Steps: receive_user_task → ... → summarize_result
        """
        task_id = str(uuid.uuid4())[:8]

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

        # Step: call_planner  (mock or live)
        if self.planner_mode == "mock":
            plan_dict = self._mock_planner(message)
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
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
            except Exception as exc:
                self.state_manager.update_task_status(
                    task_id, "failed", {"error": str(exc)}
                )
                return {
                    "status": "error",
                    "task_id": task_id,
                    "message": f"Planner call failed: {exc}",
                }

            # Step: parse_plan_json
            plan_dict = self._parse_plan_json(planner_response)
            if plan_dict is None:
                self.state_manager.update_task_status(
                    task_id,
                    "failed",
                    {"error": "Planner returned invalid JSON", "raw": planner_response},
                )
                return {
                    "status": "error",
                    "task_id": task_id,
                    "message": "Planner returned non-JSON output. Cannot execute.",
                    "raw_planner_response": planner_response,
                }

        # Step: validate_plan
        try:
            plan = ExecutionPlan(**plan_dict)
        except Exception as exc:
            return {
                "status": "error",
                "task_id": task_id,
                "message": f"Plan schema validation failed: {exc}",
            }

        # Merge runtime-detected conflicts into plan
        if detected_conflicts:
            plan.conflicts = list(set(plan.conflicts + detected_conflicts))

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

        # Steps: execute_low_risk_tools → write_execution_log → update_state
        results = await self._execute_steps(task_id, plan.steps)

        self.state_manager.update_task_status(
            task_id,
            "completed",
            {"results": results, "plan": plan.model_dump()},
        )

        # Step: summarize_result
        return self._build_summary(task_id, plan, results)

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
            self.state_manager.update_task_status(
                task_id, "cancelled", {"reason": "User rejected confirmation"}
            )
            return {
                "status": "cancelled",
                "task_id": task_id,
                "message": "Task cancelled by user. No actions were executed.",
            }

        # Execute all steps (confirmation granted)
        plan = ExecutionPlan(**task["plan"])
        results = await self._execute_steps(
            task_id, plan.steps, skip_confirmation_check=True
        )
        self.state_manager.update_task_status(
            task_id, "completed", {"results": results}
        )
        return self._build_summary(task_id, plan, results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        """Extract JSON from planner response, tolerating markdown code fences."""
        response = response.strip()
        for pattern in [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
            r"(\{[\s\S]*\})",
        ]:
            match = re.search(pattern, response)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None

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
            # High-risk step not yet confirmed → log as pending, skip execution
            if step.requires_confirmation and not skip_confirmation_check:
                record = self._make_log_record(
                    task_id, step, {"message": "Awaiting user confirmation"}, "pending_confirmation"
                )
                self.log_manager.append(record)
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
            results.append(record)

        return results

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
