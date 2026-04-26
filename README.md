# FlowGuard Agent v0.3.0

**Workflow-first multi-agent event runtime for auditable task execution.**

FlowGuard Agent 不是普通聊天机器人。它验证的是一种 workflow-first Agent 架构：模型只生成结构化计划，Runtime 负责校验、安全拦截、执行工具、记录日志和发出事件。v0.3.0 在 v0.2 执行引擎之上补齐了 Multi-Agent Event Runtime 后端闭环，为后续 dashboard 和像素办公室可视化打底。

当前实现是“多角色 Agent Runtime”，不是多个独立模型并发协作。Planner / Safety Reviewer / Executor / Reporter 等角色现在是 Runtime 中的逻辑角色，并通过事件流暴露给前端和调试工具。

---

## 版本演进

| 版本 | 重点 | 状态 |
|------|------|------|
| v0.1 | workflow-first 基础执行流：`/agent/run`、`/agent/confirm`、state/log 持久化、mock planner、高风险确认 | 已完成 |
| v0.2 | model planner：接入 `ModelRouter`、OpenAI-compatible provider、planner JSON 解析和参数规范化 | 已完成 |
| v0.3 | Multi-Agent Event Runtime：事件 schema、事件日志、EventBus、事件查询 API、Planner/Safety/Executor/Reporter/task 事件闭环 | 已完成 |

---

## 核心理念

FlowGuard Agent 的边界很明确：

- 模型不能直接调用工具，只能输出 `ExecutionPlan`
- Runtime 必须校验 plan schema 和 action 白名单
- Runtime 必须独立检查高风险动作，不信任模型标记
- 高风险动作必须等待用户确认
- 工具结果必须写入执行日志
- 最终 summary 不能在工具失败时声称任务完全完成
- 所有关键阶段都通过事件流记录，方便 dashboard / pixel-office 可视化

---

## 逻辑 Agent 角色

| 角色 | 说明 |
|------|------|
| System | 接收任务、发出任务终态事件 |
| Planner | mock 或 model planner，生成结构化执行计划 |
| Safety Reviewer | 检查 forbidden tools 和高风险设备状态 |
| User Confirmation | 表示用户确认或取消高风险动作 |
| Executor | 逐步执行工具，并发出 step started / completed 事件 |
| Reporter | 根据执行结果生成最终 summary，并触发 task 终态事件 |

---

## v0.3 事件链

完整事件流：

```text
task.received
planner.started
planner.completed | planner.failed
safety.started
safety.passed | safety.flagged
confirmation.required
confirmation.approved | confirmation.cancelled
executor.step_started
executor.step_completed
reporter.started
reporter.summary_created
task.completed | task.completed_with_errors | task.failed | task.cancelled
```

事件字段统一由 `AgentEvent` 表示，核心字段包括：

- `event_id`
- `task_id`
- `timestamp`
- `agent`
- `event_type`
- `status`
- `message`
- `step_id`
- `tool_name`
- `payload`

事件默认持久化到 `data/events.json`，但文档示例不会包含本地真实运行数据。

---

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/agent/run` | 提交自然语言任务，Runtime 生成/执行计划 |
| `POST` | `/agent/confirm` | 确认或取消等待中的高风险任务 |
| `GET` | `/agent/state` | 查看任务状态 |
| `GET` | `/agent/logs` | 查看工具执行日志 |
| `GET` | `/agent/events` | 查看全部事件 |
| `GET` | `/agent/events/{task_id}` | 查看指定任务事件链 |

### 运行任务

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message": "读取 test.md"}'
```

### 确认高风险任务

```bash
curl -X POST http://localhost:8000/agent/confirm \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "confirm": true}'
```

### 查看事件

```bash
curl http://localhost:8000/agent/events
curl http://localhost:8000/agent/events/<task_id>
```

---

## 快速启动

```bash
cd flowguard-agent
python -m venv .venv

# Windows
.\.venv\Scripts\activate

pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

默认 `runtime.plannerMode = "mock"`，不需要 API Key。

如需 model planner，请在 `.env` 中配置环境变量，并在 `agent.config.json` 中切换到 `"plannerMode": "model"`。不要把真实 API Key 写入文档、代码或 Git。

---

## Swagger 手动测试

打开：

```text
http://localhost:8000/docs
```

建议顺序：

1. `POST /agent/run`，body：`{"message": "读取 test.md"}`
2. 查看返回 `status == "completed"`
3. `GET /agent/events/{task_id}`，确认出现 planner / safety / executor / reporter / task.completed 事件
4. `POST /agent/run`，body：`{"message": "回家模式"}`
5. 查看返回 `status == "confirmation_required"`
6. `GET /agent/events/{task_id}`，确认出现 `safety.flagged` 和 `confirmation.required`，但没有 executor/reporter 终态
7. `POST /agent/confirm`，body：`{"task_id": "<task_id>", "confirm": true}`
8. 确认出现 executor / reporter / `task.completed`
9. 重新运行“回家模式”，再 `confirm=false`
10. 确认出现 `confirmation.cancelled` 和 `task.cancelled`

详细步骤见 [docs/testing-guide.md](docs/testing-guide.md)。

---

## 测试

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

v0.3.0 稳定版本测试结果：

```text
53 passed
```

---

## 项目结构

```text
flowguard-agent/
├── backend/
│   ├── main.py
│   ├── agent_runtime.py
│   ├── events/
│   │   ├── event_schema.py
│   │   ├── event_log.py
│   │   └── event_bus.py
│   ├── model_router.py
│   ├── providers/
│   ├── schemas/
│   ├── state/
│   └── tools/
├── docs/
│   ├── architecture.md
│   ├── testing-guide.md
│   └── visual-runtime-design.md
├── tests/
├── workspace/
├── agent.config.json
└── README.md
```

---

## 后续路线

| 版本 | 目标 |
|------|------|
| v0.4 | 最小 dashboard：任务列表、事件时间线、确认入口 |
| v0.5 | 多 Agent 角色模块拆分：Planner / Reviewer / Executor / Reporter 从 Runtime 中逐步抽出 |
| v0.6 | 像素办公室可视化：用事件驱动角色移动、状态变化和任务看板 |
| v0.7 | 多模型 / 多工具权限：不同角色可配置不同模型和工具权限边界 |
