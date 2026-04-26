# FlowGuard Agent v0.3 架构说明

## 核心原则

FlowGuard Agent 是 workflow-first / multi-agent event runtime。

它的核心原则是：

> 模型只生成计划，Runtime 负责校验、确认、执行、记录和汇报。

这不是 ReAct 循环，也不是聊天机器人自动调用工具。每个任务都经过固定 Runtime 流水线，每个关键阶段都会写入事件，后续 dashboard 可以直接复用这些事件。

---

## 系统分层

```text
API Layer (FastAPI)
  ├─ POST /agent/run
  ├─ POST /agent/confirm
  ├─ GET  /agent/state
  ├─ GET  /agent/logs
  ├─ GET  /agent/events
  └─ GET  /agent/events/{task_id}

AgentRuntime
  ├─ Planner phase
  ├─ Safety Reviewer phase
  ├─ Confirmation phase
  ├─ Executor phase
  ├─ Reporter phase
  └─ Task final phase

Support Layers
  ├─ ModelRouter / ProviderAdapter
  ├─ Tool Layer
  ├─ StateManager / LogManager
  └─ EventBus / EventLogManager
```

---

## Runtime 主流程

```text
receive_user_task
load_current_state
call_planner
parse_plan_json
validate_plan
check_safety_rules
[confirmation_required? stop]
execute_steps
write_execution_log
update_state
build_summary
emit_task_final_event
```

关键保证：

- `confirmation_required` 之前不会执行任何工具
- `confirm=false` 不会执行任何工具
- 工具失败不会被 summary 伪装成成功
- 事件失败不会影响主流程，因为 `_emit_event` 是 best-effort

---

## 逻辑 Agent 角色

| 角色 | agent | 事件职责 |
|------|-------|----------|
| System | `system` | `task.received`、任务终态 |
| Planner | `planner` | `planner.started`、`planner.completed`、`planner.failed` |
| Safety Reviewer | `reviewer` | `safety.started`、`safety.passed`、`safety.flagged` |
| User Confirmation | `user` | `confirmation.required`、`confirmation.approved`、`confirmation.cancelled` |
| Executor | `executor` | `executor.step_started`、`executor.step_completed` |
| Reporter | `reporter` | `reporter.started`、`reporter.summary_created` |

这些是 v0.3 的逻辑角色，不代表当前已经有多个独立 Agent 类或多个模型并发运行。

---

## Event Runtime

v0.3 新增事件底座：

- `AgentEvent`：统一事件 schema
- `EventLogManager`：append-only 事件持久化
- `EventBus`：同步 emit + subscriber callback
- `GET /agent/events`
- `GET /agent/events/{task_id}`

事件存储结构为：

```json
{
  "events": [
    {
      "event_id": "uuid",
      "task_id": "task-id",
      "timestamp": "iso-time",
      "agent": "planner",
      "event_type": "planner.started",
      "status": "running",
      "message": "Planner started",
      "step_id": null,
      "tool_name": null,
      "payload": {}
    }
  ]
}
```

文档示例只展示结构，不展示本地真实 `data/*.json` 内容。

---

## 完整事件链

### 低风险成功任务

```text
task.received
planner.started
planner.completed
safety.started
safety.passed
executor.step_started
executor.step_completed
reporter.started
reporter.summary_created
task.completed
```

### 高风险任务，等待确认

```text
task.received
planner.started
planner.completed
safety.started
safety.flagged
confirmation.required
```

此时没有 executor / reporter / task.completed，因为任务没有真正结束。

### 高风险任务，confirm=true

```text
confirmation.approved
executor.step_started
executor.step_completed
reporter.started
reporter.summary_created
task.completed
```

### 高风险任务，confirm=false

```text
confirmation.cancelled
task.cancelled
```

### Planner 或 model 失败

```text
planner.failed
task.failed
```

### 工具部分失败

```text
executor.step_completed(status=failed)
reporter.summary_created
task.completed_with_errors
```

---

## Planner

Planner 有两种模式：

| 模式 | 说明 |
|------|------|
| `mock` | 根据关键词返回固定 `ExecutionPlan`，无需 API Key |
| `model` | 通过 `ModelRouter` 调用真实 LLM，输出计划 JSON |

无论使用哪种 planner，后续 validate / safety / execute / report 流程都一致。

---

## Safety Reviewer

Safety Reviewer 负责两类检查：

- Planner 标记：`requires_confirmation`
- Runtime 独立规则：`forbidden_tools` 和高风险设备状态表

典型高风险动作：

- `door_lock` -> `unlock` / `unlocked` / `open`
- `camera` -> `off` / `disabled` / `stopped`
- `shell.exec` 默认禁用

---

## Executor

Executor 不做决策，只逐步执行通过安全检查的工具调用。

每步执行前：

```text
executor.step_started
```

每步日志写入后：

```text
executor.step_completed
```

`executor.step_completed` 的 payload 只保存摘要，不保存完整工具结果。完整工具结果仍在 `data/execution_log.json`。

---

## Reporter

Reporter 负责最终 summary 阶段：

```text
reporter.started
reporter.summary_created
```

Reporter 之后由 System 发出任务终态：

- `task.completed`
- `task.completed_with_errors`
- `task.failed`
- `task.cancelled`

---

## 状态与日志

| 文件 | 用途 |
|------|------|
| `data/state.json` | 任务状态 |
| `data/execution_log.json` | 工具调用日志 |
| `data/events.json` | v0.3 事件流 |

这些是本地运行态文件，不应该把真实内容写进文档或提交到 Git。

---

## 后续架构路线

| 版本 | 方向 |
|------|------|
| v0.4 | 最小 dashboard，消费 `/agent/events/{task_id}` |
| v0.5 | 将逻辑角色拆成 Planner / Reviewer / Executor / Reporter 模块 |
| v0.6 | 像素办公室可视化，用事件驱动角色状态 |
| v0.7 | 多模型 / 多工具权限，每个角色有独立权限边界 |
