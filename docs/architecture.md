# FlowGuard Agent — 架构设计说明

## 核心设计原则

FlowGuard Agent 的架构围绕一个核心命题构建：

> **模型只生成计划，Runtime 负责执行。模型永远不能绕过 Runtime 直接调用工具。**

这不是一个 ReAct 循环，也不是让模型自主决定下一步。每一次任务执行都是一条固定的单向流水线，可以在任何节点审计、暂停或回滚。

---

## 整体分层

```
┌─────────────────────────────────────────────┐
│              API Layer (FastAPI)             │
│  /health  /agent/run  /agent/confirm  ...   │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│           AgentRuntime (核心引擎)            │
│  workflow: plan → validate → safety →       │
│           execute → log → state             │
└──────┬──────────────┬──────────────┬────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼─────┐ ┌────▼────────┐
│ ModelRouter │ │ Tool Layer│ │ State Layer │
│ + Providers │ │           │ │             │
└─────────────┘ └───────────┘ └─────────────┘
```

---

## AgentRuntime

**文件：** `backend/agent_runtime.py`

AgentRuntime 是整个系统的调度中心，实现 11 步工作流。它是唯一一个同时持有模型层、工具层和状态层引用的组件。

### 11 步工作流

```
receive_user_task   → 接收 message，生成 task_id
load_config         → 从 __init__ 注入的 config 读取配置
load_current_state  → DeviceTools.get_state() + detect_conflicts()
call_planner        → mock 模式直接返回 dict；live 模式调用 ModelRouter
parse_plan_json     → 从 LLM 响应中提取 JSON（容忍 markdown fences）
validate_plan       → Pydantic ExecutionPlan(**plan_dict) 校验
check_safety_rules  → 逐步检查 requires_confirmation 和高风险设备表
[confirmation_required?] → 有高风险步骤则保存 pending 状态并返回，终止执行
execute_low_risk_tools → _dispatch_tool() 逐步调用实际工具
write_execution_log → LogManager.append() 追加写入每步结果
update_state        → StateManager.update_task_status() 更新最终状态
summarize_result    → 组装响应，禁止在有失败步骤时声称"已完成"
```

### mock planner

`_mock_planner(message)` 是一个纯函数，根据关键词匹配返回固定的 plan dict，格式与真实 LLM 输出完全一致。这使得整个 Runtime 流水线（validate → safety → execute → log）可以在没有 API Key 的环境中完整运行和测试。

通过 `agent.config.json` 中的 `runtime.plannerMode` 字段控制：
- `"mock"` — 使用 `_mock_planner`
- `"live"` — 使用 `ModelRouter`

### 假完成防护

`_build_summary()` 中有明确的降级逻辑：
- 有失败步骤 → `"completed_with_errors"`
- 全部失败且无成功 → `"failed"`
- 有 pending_confirmation → 计入 summary 但不算完成

---

## ModelRouter

**文件：** `backend/model_router.py`

ModelRouter 是业务层与模型供应商之间的唯一桥梁。AgentRuntime 只调用：

```python
await self.model_router.call("planner", messages)
```

ModelRouter 根据 `agent.config.json` 中的 `models.planner` 配置：
1. 查找角色对应的 provider 名称（`"openai_compatible"`）
2. 实例化或复用对应的 ProviderAdapter
3. 传入 model name、temperature、maxTokens 等参数
4. 返回纯文本响应字符串

**设计意图：** 切换模型供应商不需要改任何业务代码，只改 `agent.config.json`。

```
AgentRuntime
    │
    └─ ModelRouter.call("planner", messages)
            │
            └─ 查找 models.planner.provider = "openai_compatible"
                    │
                    └─ OpenAICompatibleAdapter.complete(model, messages, ...)
                            │
                            └─ HTTP POST → LLM API
```

---

## ProviderAdapter

**文件：** `backend/providers/base.py`，`backend/providers/openai_compatible.py`

### BaseProviderAdapter（抽象接口）

```python
class BaseProviderAdapter:
    async def complete(self, model: str, messages: list, ...) -> str:
        raise NotImplementedError
```

定义了所有 Provider 必须实现的接口。新增供应商只需继承此类并实现 `complete` 方法。

### OpenAICompatibleAdapter

支持所有遵循 OpenAI Chat Completions API 格式的供应商：
- OpenAI（默认）
- DeepSeek（`api.deepseek.com/v1`）
- SiliconFlow（`api.siliconflow.cn/v1`）
- Moonshot、Yi 等国内模型

配置示例（`agent.config.json`）：
```json
"providers": {
  "openai_compatible": {
    "baseUrl": "https://api.deepseek.com/v1",
    "apiKeyEnvVar": "DEEPSEEK_API_KEY"
  }
}
```

API Key 从环境变量读取，不硬编码在配置文件中。

---

## Tool Layer

**目录：** `backend/tools/`

工具层是纯执行组件，每个工具只做一件事，不做决策、不访问模型、不读取 config。

### FileTools（`file_tools.py`）

操作 `workspace/` 目录下的文件，路径强制限制在 workspace 内（防止路径穿越）。

| 方法 | 对应 action | 说明 |
|------|-------------|------|
| `read(filename)` | `file.read` | 读取文件内容，文件不存在返回 `status: failed` |
| `write(filename, content)` | `file.write` | 写入/覆盖文件 |
| `list_files(pattern)` | `file.list` | 列出匹配的文件名 |

### DeviceTools（`device_tools.py`）

以 `workspace/device_state.json` 作为设备状态数据源，模拟智能家居设备管理。

| 方法 | 对应 action | 说明 |
|------|-------------|------|
| `get_state(device_id?)` | `device.get_state` | 读取单个或所有设备状态 |
| `set_state(device_id, new_status, properties?)` | `device.set_state` | 更新设备状态并持久化 |
| `needs_confirmation(device_id, new_status)` | — | 安全检查：是否需要确认 |
| `detect_conflicts()` | — | 检测设备状态冲突（窗开着开空调等）|

**HIGH_RISK_STATES 表：**
```python
{
    "door_lock": ["unlock", "unlocked", "open"],
    "camera":    ["off", "disabled", "stopped"],
}
```

任何对这些设备的这些状态变更，Runtime 会强制进入 `confirmation_required`。

### RAGTools（`rag_tools.py`）

v0.1 实现关键词检索，扫描 workspace 下的 .md / .txt 文件。v0.2 计划升级为 embedding 向量检索。

### WebTools（`web_tools.py`）

v0.1 为 mock 实现，返回固定占位响应。v0.2 计划接入 Tavily / Brave Search API。

### 工具调用的 dispatch 逻辑

`AgentRuntime._dispatch_tool(step)` 是工具的统一调度点，接受 `PlanStep`，根据 `step.action` 分发到对应工具。

**参数兼容性：** 为兼容 mock planner（使用 `path` / `status`）和 live planner（使用 `filename` / `new_status`），dispatch 层对两种参数名都做了处理：
```python
filename = args.get("filename") or args.get("path", "")
new_status = args.get("new_status") or args.get("status", "")
```

---

## StateManager

**文件：** `backend/state/state_manager.py`

管理任务生命周期状态，持久化到 `data/state.json`。

**任务状态流转：**
```
planning
    │
    ├─→ confirmation_required  ─→ cancelled (confirm=false)
    │           │
    │           └─→ completed (confirm=true)
    │
    └─→ completed
    └─→ completed_with_errors
    └─→ failed
```

**主要方法：**
- `save_task(task_id, data)` — 创建或覆写任务记录
- `get_task(task_id)` — 读取单个任务
- `get_all()` — 返回所有任务（用于 `GET /agent/state`）
- `update_task_status(task_id, status, extra)` — 更新状态并合并额外字段

---

## LogManager

**文件：** `backend/state/log_manager.py`

管理工具调用执行日志，持久化到 `data/execution_log.json`。

**设计原则：** append-only（只追加，不修改），每条记录包含：

```json
{
  "task_id":   "工具所属任务的 ID",
  "step_id":   "计划中的步骤 ID（如 step_1）",
  "tool_name": "实际调用的工具名（如 device.set_state）",
  "args":      "传入参数",
  "result":    "工具返回值（原始）",
  "status":    "success | failed | pending_confirmation | skipped",
  "timestamp": "UTC ISO8601 时间戳"
}
```

每次工具调用（包括失败、跳过、等待确认）都会产生一条日志，确保执行过程完全可追溯。

---

## Safety Confirmation（安全确认机制）

安全机制分为两层，**任意一层触发都会进入确认流程**：

### 第一层：Planner 标记

Planner（mock 或 live）在生成计划时，对高风险步骤设置：
```json
{
  "risk": "high",
  "requires_confirmation": true
}
```

### 第二层：Runtime 独立校验（`_check_safety`）

Runtime 不信任 Planner 的标记，独立检查两个条件：

1. **forbidden_tools 列表：** 如果 `step.action` 在 `agent.config.json` 的 `safety.forbidden_tools` 中（如 `shell.exec`），强制设置 `requires_confirmation = true`

2. **HIGH_RISK_STATES 表：** 如果是 `device.set_state` 动作，调用 `device_tools.needs_confirmation(device_id, new_status)` 检查设备+状态组合是否在高风险表中

**为什么需要双重检查？**

Planner（尤其是 LLM）可能遗漏标记某个高风险动作。Runtime 的独立校验是最后一道防线，确保即使 Planner 输出有误，高风险动作仍然被拦截。

### 确认流程

```
Runtime 发现高风险步骤
    │
    ▼
保存任务状态为 "confirmation_required"
保存完整 plan + pending_actions 到 state.json
    │
    ▼
返回给用户：pending_actions 列表 + safe_steps_preview
（此时零动作被执行）
    │
    ├─→ POST /agent/confirm {"confirm": true}
    │       └─ 重新执行全部步骤（skip_confirmation_check=True）
    │
    └─→ POST /agent/confirm {"confirm": false}
            └─ 状态更新为 "cancelled"，无任何执行
```

**关键保证：** 从收到任务到用户确认之间，没有任何工具被调用、没有任何设备状态被修改。
