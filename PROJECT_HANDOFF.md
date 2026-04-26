# FlowGuard Agent v0.3.0 Project Handoff

## 当前状态

FlowGuard Agent v0.3.0 已完成并推送：

- 分支：`v0.3-multi-agent-events`
- commit：`9c9952a`
- tag：`v0.3.0`
- 测试：`53 passed`
- 核心能力：Multi-Agent Event Runtime 后端闭环

本项目不是普通聊天机器人，而是一个 workflow-first / multi-agent event runtime。当前“多 Agent”指 Runtime 内部的多逻辑角色和事件协议，不是多个独立模型并发协作。

---

## 项目目标

FlowGuard Agent 的核心命题：

> AI Agent 不能只会聊天。它必须能把自然语言目标转成可校验、可确认、可追溯的执行流程。

当前目标：

- 验证 workflow-first 架构：模型生成计划，Runtime 执行计划
- 防止 Agent 假完成：工具失败时最终状态必须降级
- 防止高风险动作失控：门锁解锁、摄像头关闭等必须人工确认
- 保留完整执行证据：工具日志和事件日志都可追踪
- 为 dashboard / 像素办公室可视化提供稳定事件流

---

## 版本演进

### v0.1：基础 Runtime

已完成：

- `POST /agent/run`
- `POST /agent/confirm`
- `GET /agent/state`
- `GET /agent/logs`
- mock planner
- 高风险 confirmation gate
- `data/state.json`
- `data/execution_log.json`

### v0.2：Model Planner

已完成：

- `ModelRouter`
- `OpenAICompatibleAdapter`
- planner role 配置
- model planner 模式
- planner JSON 解析鲁棒性
- mock planner / model planner 共用 Runtime 后续流程

### v0.3：Multi-Agent Event Runtime

已完成：

- `backend/events/event_schema.py`
- `backend/events/event_log.py`
- `backend/events/event_bus.py`
- `EventBus` 注入 `AgentRuntime`
- `GET /agent/events`
- `GET /agent/events/{task_id}`
- Planner / Safety / Confirmation / Executor / Reporter / Task final 事件闭环

---

## 当前逻辑 Agent 角色

| 角色 | agent 字段 | 责任 |
|------|------------|------|
| System | `system` | 接收任务、发出任务终态 |
| Planner | `planner` | 生成或解析执行计划 |
| Safety Reviewer | `reviewer` | 检查安全规则和高风险步骤 |
| User Confirmation | `user` | 表示用户确认或取消 |
| Executor | `executor` | 逐步调用工具并记录 step 事件 |
| Reporter | `reporter` | 生成最终 summary |

这些角色目前仍在 `AgentRuntime` 内部实现。后续 v0.5 可以再拆成独立模块。

---

## 完整事件链

正常低风险任务：

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

高风险任务 confirm=true：

```text
task.received
planner.started
planner.completed
safety.started
safety.flagged
confirmation.required
confirmation.approved
executor.step_started
executor.step_completed
reporter.started
reporter.summary_created
task.completed
```

高风险任务 confirm=false：

```text
task.received
planner.started
planner.completed
safety.started
safety.flagged
confirmation.required
confirmation.cancelled
task.cancelled
```

失败路径：

```text
planner.failed
task.failed
```

或执行后部分失败：

```text
executor.step_completed(status=failed)
reporter.summary_created
task.completed_with_errors
```

---

## API 入口

| API | 作用 |
|-----|------|
| `POST /agent/run` | 提交任务 |
| `POST /agent/confirm` | 确认或取消高风险任务 |
| `GET /agent/state` | 查看任务状态 |
| `GET /agent/logs` | 查看工具执行日志 |
| `GET /agent/events` | 查看全部事件 |
| `GET /agent/events/{task_id}` | 查看单个任务事件链 |

---

## 测试方式

推荐命令：

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

v0.3.0 当前结果：

```text
53 passed
```

手动测试见：

- [docs/testing-guide.md](docs/testing-guide.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/visual-runtime-design.md](docs/visual-runtime-design.md)

---

## 接手注意事项

- 不要提交 `.env`
- 不要提交本地运行态 `data/*.json`
- 不要把真实 API Key 写进文档或示例
- 不要把 v0.3 描述成“多个独立模型并发协作”
- 当前准确表述是：multi-agent event runtime / 多角色 Agent Runtime
- 后续拆 Agent 类之前，保持 Runtime 行为和 API 响应兼容

---

## 后续路线

| 版本 | 目标 |
|------|------|
| v0.4 | 最小 dashboard：事件时间线、任务详情、确认入口 |
| v0.5 | 多 Agent 角色模块拆分 |
| v0.6 | 像素办公室可视化 |
| v0.7 | 多模型 / 多工具权限 |
