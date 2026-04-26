# FlowGuard Agent v0.3 测试指南

本文档说明如何通过 Swagger 和 pytest 验证 FlowGuard Agent v0.3 的 workflow-first / multi-agent event runtime。

---

## 前置准备

```bash
cd flowguard-agent
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

默认配置为 mock planner：

```json
{
  "runtime": {
    "plannerMode": "mock"
  }
}
```

mock 模式不需要 API Key。

启动服务：

```bash
uvicorn backend.main:app --reload --port 8000
```

打开 Swagger：

```text
http://localhost:8000/docs
```

---

## Swagger 测试流程

### 1. 健康检查

接口：

```text
GET /health
```

期望：

```json
{
  "status": "ok",
  "service": "FlowGuard Agent",
  "version": "0.2.0"
}
```

说明：当前 app version 仍来自配置文件，文档版本为 v0.3.0。

---

### 2. 读取 test.md

接口：

```text
POST /agent/run
```

Body：

```json
{
  "message": "读取 test.md"
}
```

期望：

- 返回 `status: "completed"`
- 返回 `task_id`
- `executed_actions` 中有 `file.read`
- summary 中 `successful == 1`

随后调用：

```text
GET /agent/events/{task_id}
```

期望事件链包含：

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

---

### 3. 回家模式：触发确认

接口：

```text
POST /agent/run
```

Body：

```json
{
  "message": "回家模式"
}
```

期望：

- 返回 `status: "confirmation_required"`
- 返回 `task_id`
- `pending_actions` 中包含 door_lock unlock
- 此时不执行任何工具

查看事件：

```text
GET /agent/events/{task_id}
```

期望事件链包含：

```text
task.received
planner.started
planner.completed
safety.started
safety.flagged
confirmation.required
```

此时不应出现：

```text
executor.step_started
reporter.started
task.completed
```

---

### 4. confirm=true

接口：

```text
POST /agent/confirm
```

Body：

```json
{
  "task_id": "<task_id>",
  "confirm": true
}
```

期望：

- 返回 `status: "completed"`
- 多个 executor step 事件出现
- door_lock unlock 对应 step 成功

事件链新增：

```text
confirmation.approved
executor.step_started
executor.step_completed
reporter.started
reporter.summary_created
task.completed
```

---

### 5. confirm=false

重新提交一次“回家模式”，获取新的 `task_id`。

接口：

```text
POST /agent/confirm
```

Body：

```json
{
  "task_id": "<task_id>",
  "confirm": false
}
```

期望：

- 返回 `status: "cancelled"`
- 不出现 executor 事件
- 不出现 reporter summary
- 不出现 `task.completed`

事件链新增：

```text
confirmation.cancelled
task.cancelled
```

---

## 事件接口

### 查看全部事件

```text
GET /agent/events
```

返回：

```json
{
  "events": []
}
```

实际运行时会返回事件数组。文档不展示本地真实 `data/events.json` 内容。

### 查看指定任务事件

```text
GET /agent/events/{task_id}
```

用于 dashboard / 调试工具按任务展示时间线。

---

## pytest

推荐命令：

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

v0.3.0 当前测试结果：

```text
53 passed
```

测试覆盖：

- `AgentEvent` schema
- `EventLogManager`
- `EventBus`
- planner 事件
- safety / confirmation 事件
- executor 事件
- reporter / task final 事件
- planner JSON 解析和参数规范化

---

## model planner 测试

如需测试真实模型：

1. 在 `.env` 中配置环境变量
2. 在 `agent.config.json` 中设置：

```json
{
  "runtime": {
    "plannerMode": "model"
  }
}
```

注意：

- 不要把真实 API Key 写进文档或提交到 Git
- model planner 只生成计划
- Runtime 仍会独立做 schema validation、safety check 和 confirmation gate

---

## 常见问题

### 为什么回家模式第一次不会执行低风险步骤？

当前设计是整体确认：一旦 plan 中含高风险步骤，Runtime 保存完整 plan 并返回 `confirmation_required`。确认前不执行任何工具，避免“部分执行后用户拒绝”的状态不一致。

### 为什么事件里没有完整工具结果？

Executor event 只保存摘要，完整工具结果保存在 `data/execution_log.json`。这样事件流更适合 dashboard 消费。

### 为什么说 multi-agent，但没有多个 Agent 类？

v0.3 是 multi-agent event runtime。Planner / Reviewer / Executor / Reporter 是逻辑角色，先通过事件协议稳定边界；v0.5 再考虑模块拆分。
