# FlowGuard Agent — 演示脚本

面试 / 作品集展示用。预计演示时间：5-8 分钟。

---

## 一句话介绍

> FlowGuard Agent 是一个 workflow-first 的 AI Agent Runtime：
> 模型只负责生成计划，Runtime 独立校验安全规则、执行工具、记录日志。
> 高风险动作必须经过用户确认，模型无法绕过 Runtime 直接执行任何操作。

---

## 演示路径

### 第一步：项目架构（30 秒）

打开 `agent.config.json`，快速展示：
- 11 步工作流定义（`workflow.steps`）
- 安全规则配置（`safety.require_confirmation` / `safety.forbidden_tools`）
- 模型与供应商分离（`providers` + `models`，切换供应商只改配置不改代码）

**话术：** "这个项目的核心不是模型能力，而是 Runtime 如何约束模型行为。配置文件定义了哪些动作是高风险的、哪些工具是禁用的，Runtime 在执行前会独立校验。"

---

### 第二步：健康检查（15 秒）

Swagger 中调用 `GET /health`

**话术：** "先确认服务在线。"

---

### 第三步：文件读取（1 分钟）

Swagger 中调用 `POST /agent/run`：
```json
{ "message": "读取 test.md" }
```

**展示要点：**
- `status: "completed"` — 任务成功
- `executed_actions[0].tool: "file.read"` — 调用了真实工具
- `result.content` — 返回了文件的真实内容，不是模型编造的

**话术：** "注意这里的 content 是工具真正读取的文件内容，不是模型自己编的。如果文件不存在，返回的是 `status: failed`，最终摘要也不会声称任务完成 — 这就是防止假完成。"

---

### 第四步：回家模式 — 高风险拦截（2 分钟，核心）

```json
{ "message": "回家模式" }
```

**展示要点：**
1. `status: "confirmation_required"` — 不是 completed，任务被暂停了
2. `pending_actions` — 精确显示哪个动作被拦截（door_lock unlock）
3. `safe_steps_preview` — 低风险步骤也还没有执行，等整体确认

**话术：** "这是项目最核心的设计。模型说 '解锁门锁'，但 Runtime 不会直接执行。它独立检测到 door_lock unlock 是高风险动作，强制进入确认流程。即使模型没有标记 `requires_confirmation`，Runtime 的安全表也会拦截。模型无法绕过这一层。"

---

### 第五步：确认执行（1 分钟）

记下上一步的 `task_id`，然后调用 `POST /agent/confirm`：
```json
{ "task_id": "<task_id>", "confirm": true }
```

**展示要点：**
- `status: "completed"`
- `summary.successful: 5` — 全部 5 步成功

**话术：** "用户确认后，Runtime 才执行全部步骤。每一步都有独立的 status 和 result。"

---

### 第六步：执行日志（30 秒）

调用 `GET /agent/logs`

**展示要点：**
- 每条记录：`task_id / step_id / tool_name / args / result / status / timestamp`
- door_lock 的记录：`old_status: locked → new_status: unlocked`

**话术：** "所有工具调用都有完整的审计日志。在生产环境中，这是合规和故障排查的基础。"

---

### 第七步（可选）：model 模式快速展示

如果时间允许，切换到 `plannerMode: "model"` 重复第三、四步，展示真实模型生成的计划也走同一套校验和执行流程。

---

## 关键问答准备

### "这个项目和普通聊天机器人有什么区别？"

> 聊天机器人的输出是文本 — 它说 "已帮你开灯" 不代表灯真的开了。
> FlowGuard Agent 的输出是结构化执行结果 — 每个动作都经过 plan → validate → safety → execute → log 五步，工具返回 `status: failed` 时摘要不允许声称完成。
> 模型在这个架构中只是 planner，不是 executor。

### "模型如果生成错误的计划怎么办？"

> 三层防护：
> 1. **Parser** — 模型输出非 JSON 则 `plan_parse_failed`，拒绝执行
> 2. **Validator** — 未知 action 名则 `plan_validation_failed`，拒绝执行
> 3. **Safety check** — Runtime 独立检查高风险状态变更，不依赖模型标记

### "confirmation_required 是谁决定的？"

> 不是模型决定的。Runtime 的 `_check_safety` 方法有一张独立的高风险状态表（`HIGH_RISK_STATES`）。
> 即使模型把 door_lock unlock 标记为 `risk: "low"`，Runtime 也会强制拦截。
> 这是 workflow-first 的核心：安全规则在 Runtime 层执行，不信任模型输出。

### "为什么 v0.2 要做 Parser 鲁棒化？"

> 真实模型的输出不可控。有的模型会在 JSON 前后加解释文字，有的会用 markdown 代码块包裹，有的 API 会对 JSON 做二次转义。
> Parser 支持四级降级解析：plain JSON → code fence → double-encoded → embedded in prose。
> 解析失败则返回 `plan_parse_failed`，绝不执行工具。

### "这个项目用了什么技术栈？"

> Python + FastAPI + Pydantic。模型调用通过 OpenAI-compatible HTTP API，支持任何兼容供应商。
> 没有用 LangChain / AutoGen 等框架 — Runtime 的 11 步工作流是手写的，每一步的行为完全可控。
