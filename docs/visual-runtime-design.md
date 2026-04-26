# FlowGuard Agent Visual Runtime Design

本文档描述 FlowGuard Agent 后续 dashboard / 像素办公室可视化的设计方向。它不是当前 v0.3 已实现的前端说明，而是基于 v0.3 事件流的产品与技术设计草案。

---

## 设计目标

FlowGuard Agent 的可视化不应该只是聊天记录面板，而应该展示一个任务如何在 workflow-first Runtime 中流动：

```text
System -> Planner -> Safety Reviewer -> User Confirmation -> Executor -> Reporter -> Task Final
```

用户应该能看见：

- 当前任务处于哪个阶段
- 哪个逻辑 Agent 正在工作
- 哪一步正在调用哪个工具
- 哪些动作被安全拦截
- 哪些步骤成功、失败或跳过
- 任务最终是完成、部分失败、失败还是取消

---

## v0.3 可视化数据源

v0.3 已提供事件 API：

```text
GET /agent/events
GET /agent/events/{task_id}
```

前端可以先用轮询消费这些接口。v0.3 不包含 SSE / WebSocket。

事件基础字段：

| 字段 | 用途 |
|------|------|
| `task_id` | 关联一次任务 |
| `agent` | 显示逻辑角色 |
| `event_type` | 决定视觉状态 |
| `status` | success / failed / running / waiting_confirmation / cancelled 等 |
| `step_id` | 对应执行计划步骤 |
| `tool_name` | 显示工具调用 |
| `payload` | 展示摘要信息 |

---

## 逻辑角色到视觉角色

| agent | 像素办公室角色 | 视觉状态 |
|-------|----------------|----------|
| `system` | 前台 / 调度台 | 收到任务、任务结束 |
| `planner` | 规划员 | 生成计划、计划失败 |
| `reviewer` | 安全审核员 | 检查风险、举牌拦截 |
| `user` | 人类确认者 | 确认或取消 |
| `executor` | 执行员 | 调用工具、逐步完成 |
| `reporter` | 汇报员 | 生成总结 |

注意：这些是可视化角色，不代表 v0.3 中已经拆成多个独立 Agent 类。

---

## 事件到 UI 的映射

### Planner

| event_type | UI 表现 |
|------------|---------|
| `planner.started` | Planner 角色进入工作状态 |
| `planner.completed` | 计划卡片生成成功 |
| `planner.failed` | 计划卡片标红，显示失败原因 |

### Safety Reviewer

| event_type | UI 表现 |
|------------|---------|
| `safety.started` | Reviewer 开始检查 |
| `safety.passed` | 安全检查通过 |
| `safety.flagged` | 风险拦截，显示 pending actions |

### User Confirmation

| event_type | UI 表现 |
|------------|---------|
| `confirmation.required` | 弹出确认面板 |
| `confirmation.approved` | 确认通过，任务继续 |
| `confirmation.cancelled` | 任务取消 |

### Executor

| event_type | UI 表现 |
|------------|---------|
| `executor.step_started` | 当前步骤高亮，显示工具名 |
| `executor.step_completed` | 步骤状态更新为 success / failed / skipped |

### Reporter / Task Final

| event_type | UI 表现 |
|------------|---------|
| `reporter.started` | Reporter 生成总结 |
| `reporter.summary_created` | 展示 summary 计数 |
| `task.completed` | 任务完成 |
| `task.completed_with_errors` | 任务部分失败 |
| `task.failed` | 任务失败 |
| `task.cancelled` | 任务取消 |

---

## v0.4 最小 Dashboard

v0.4 可以先做传统 dashboard，不急着做像素办公室。

建议页面：

1. 任务提交区
2. 当前任务状态
3. 事件时间线
4. pending confirmation 面板
5. executor step 列表
6. reporter summary 区

建议数据流：

```text
POST /agent/run
GET /agent/events/{task_id}
POST /agent/confirm
GET /agent/events/{task_id}
```

v0.4 可以使用轮询，不需要 SSE / WebSocket。

---

## v0.6 像素办公室

像素办公室适合在事件协议稳定后实现。核心画面可以是一个小型办公室：

- Planner 在白板前写计划
- Safety Reviewer 在检查台审核风险
- Executor 在工作台调用工具
- Reporter 在终端前生成总结
- System 在调度台更新任务状态
- User Confirmation 以弹窗或门禁台表现

事件驱动动画：

```text
event_type -> role state -> animation/state badge
```

例如：

- `planner.started`：Planner 走到白板
- `safety.flagged`：Reviewer 举起警示牌
- `executor.step_started`：Executor 走向工具台
- `executor.step_completed(status=failed)`：步骤格子标红
- `task.completed`：办公室任务灯变绿

---

## 设计边界

当前不要把 v0.3 夸大为：

- 多个模型并发协作
- 真正自治的多 Agent 群体
- 已经具备实时 WebSocket 推送

当前准确表述：

- multi-agent event runtime
- 多角色 Agent Runtime
- 事件驱动的可观测执行引擎

---

## 后续路线

| 版本 | 可视化目标 |
|------|------------|
| v0.4 | 最小 dashboard，基于事件轮询 |
| v0.5 | 角色模块拆分后，按真实模块展示 Agent 生命周期 |
| v0.6 | 像素办公室可视化 |
| v0.7 | 多模型 / 多工具权限在 UI 中可配置和审计 |
