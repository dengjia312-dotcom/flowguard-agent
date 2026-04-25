# FlowGuard Agent — v0.1 Project Handoff

## 项目目标

FlowGuard Agent 的核心命题是：**AI Agent 不能只是聊天，它必须是可校验、可确认、可追溯的任务执行引擎。**

具体目标：
- 验证 workflow-first 架构的可行性：模型只负责生成计划，Runtime 负责执行
- 解决 Agent 假完成问题：工具未返回成功时，摘要不允许声明"已完成"
- 解决高风险动作失控问题：门锁解锁、摄像头关闭等必须暂停等待人工确认
- 解决执行不可追溯问题：每一次工具调用都写入结构化日志
- 验证无真实 API Key 时，完整工作流仍可通过 mock planner 端到端测试

---

## 当前架构

```
用户输入 (message)
    │
    ▼
AgentRuntime.run_task()          ← 核心工作流，11 步
    │
    ├─ load_current_state        ← 读取 workspace/device_state.json
    │
    ├─ call_planner              ← mock 模式: _mock_planner(message)
    │                               live 模式: ModelRouter → ProviderAdapter → LLM API
    │
    ├─ validate_plan             ← Pydantic schema 校验 (ExecutionPlan)
    │
    ├─ check_safety_rules        ← 逐步检查 requires_confirmation + 设备风险表
    │
    ├─ [confirmation_required?]  ← 有高风险步骤 → 返回 pending_actions，停止执行
    │
    ├─ execute_low_risk_tools    ← 逐步 dispatch → FileTools / DeviceTools / ...
    │
    ├─ write_execution_log       ← 每步结果追加写入 data/execution_log.json
    │
    └─ update_state              ← 任务状态写入 data/state.json
```

**关键分层原则：**
- 模型层（ModelRouter / ProviderAdapter）只负责文本生成，不接触任何工具
- 工具层（FileTools / DeviceTools 等）只执行，不做决策
- Runtime 是唯一决策者：它读取计划、校验安全、决定执行或暂停

---

## 已完成能力

### 核心工作流
- [x] 11 步工作流完整实现（receive → plan → validate → safety → execute → log → state）
- [x] mock planner 模式（`agent.config.json` 中 `runtime.plannerMode = "mock"`）
- [x] 高风险动作拦截 + `confirmation_required` 状态机
- [x] `POST /agent/confirm` 恢复执行或取消任务
- [x] 全部工具调用写入 `execution_log.json`（tool_name / args / result / status / timestamp）
- [x] 任务状态持久化到 `state.json`

### 工具层（Tool Layer）
- [x] `file.read` — 读取 workspace/ 下的文件
- [x] `file.write` — 写入 workspace/ 下的文件
- [x] `file.list` — 列出 workspace/ 文件
- [x] `device.get_state` — 读取 device_state.json
- [x] `device.set_state` — 修改设备状态并持久化
- [x] `rag.search` — 关键词检索（v0.1 无向量化）
- [x] `web.search` — mock 实现（v0.1 占位）
- [x] `shell.exec` — 已禁用，强制拦截

### 安全层
- [x] `HIGH_RISK_STATES` 表：door_lock unlock / camera off 等自动触发确认
- [x] `forbidden_tools` 列表：shell.exec 永久封锁
- [x] Runtime 双重检查：planner 标记 + Runtime 独立校验，两者都能触发 confirmation
- [x] 假完成防护：任何步骤 status != success → 摘要状态降级为 `completed_with_errors` / `failed`

### 模型层
- [x] `ModelRouter` — 按角色路由（planner / vision / embedding 等）
- [x] `OpenAICompatibleAdapter` — 支持 OpenAI / DeepSeek / SiliconFlow 等兼容接口
- [x] `BaseProviderAdapter` — 抽象接口，便于扩展新供应商

### API 层
- [x] `GET  /health`
- [x] `GET  /agent/state`
- [x] `GET  /agent/logs`
- [x] `POST /agent/run`
- [x] `POST /agent/confirm`

---

## 已通过的接口测试

| 测试项 | 输入 | 期望结果 | 状态 |
|--------|------|----------|------|
| 健康检查 | `GET /health` | `{"status":"ok"}` | ✅ |
| 任务状态查询 | `GET /agent/state` | 返回 tasks 字典 | ✅ |
| 执行日志查询 | `GET /agent/logs` | 返回 logs 数组 | ✅ |
| 文件读取总结 | `POST /agent/run {"message":"读取 test.md"}` | `status: completed`，file.read 成功 | ✅ |
| 回家模式（触发确认） | `POST /agent/run {"message":"回家模式"}` | `status: confirmation_required`，door_lock 在 pending_actions | ✅ |
| 高风险确认执行 | `POST /agent/confirm {"task_id":"...","confirm":true}` | 5 步全部执行，door_lock 状态变为 unlocked | ✅ |
| 高风险确认拒绝 | `POST /agent/confirm {"task_id":"...","confirm":false}` | `status: cancelled`，无任何动作执行 | ✅ |

---

## mock planner 的作用

**问题背景：** 在没有真实 API Key 的环境（CI、演示、本地开发）中，调用真实模型会失败，无法测试 Runtime 本身的逻辑。

**解决方案：** 在 `agent.config.json` 中设置 `runtime.plannerMode = "mock"`，`AgentRuntime` 会跳过模型调用，直接用 `_mock_planner(message)` 方法根据关键词匹配返回固定的 `ExecutionPlan` JSON。

**关键设计决策：**
- mock planner 返回的计划格式与真实 planner 完全相同（同一个 Pydantic schema）
- Runtime 后续的 validate_plan / check_safety / execute / log / state 流程完全不感知 planner 是 mock 还是 live
- 这意味着：mock 模式测试的是 Runtime 真实行为，不是桩测试

**两个内置场景：**
- 场景 A（文件读取）：输入包含"读取 test.md"或"总结 test.md" → 返回 file_summary 计划
- 场景 B（回家模式）：输入包含"回家模式"或"我快到家了" → 返回含 door_lock 高风险步骤的 device_orchestration 计划

**切换回 live 模式：**
```json
// agent.config.json
"runtime": {
  "plannerMode": "live"
}
```

---

## 当前文件结构

```
flowguard-agent/
├── backend/
│   ├── main.py                  # FastAPI 入口，5 个路由
│   ├── config_loader.py         # 加载 agent.config.json
│   ├── agent_runtime.py         # 核心执行引擎（11步工作流 + mock planner）
│   ├── model_router.py          # 模型角色路由
│   ├── providers/
│   │   ├── base.py              # BaseProviderAdapter 抽象接口
│   │   └── openai_compatible.py # OpenAI-compatible HTTP 实现
│   ├── tools/
│   │   ├── file_tools.py        # file.read / file.write / file.list
│   │   ├── device_tools.py      # device.get_state / device.set_state + 冲突检测
│   │   ├── rag_tools.py         # rag.search（关键词）
│   │   └── web_tools.py         # web.search（mock）
│   ├── state/
│   │   ├── state_manager.py     # 任务状态 CRUD → data/state.json
│   │   └── log_manager.py       # 执行日志追加写入 → data/execution_log.json
│   └── schemas/
│       ├── plan_schema.py       # ExecutionPlan / PlanStep
│       └── tool_schema.py       # ToolCallRecord
├── docs/
│   ├── testing-guide.md         # Swagger 测试操作手册
│   └── architecture.md          # 架构设计说明
├── workspace/
│   ├── device_state.json        # 智能家居设备状态（模拟数据源）
│   └── test.md                  # 文件读取测试用的示例文档
├── data/
│   ├── state.json               # 任务状态持久化
│   └── execution_log.json       # 工具调用日志（append-only）
├── agent.config.json            # 主配置（含 runtime.plannerMode）
├── .env                         # API Key（不提交）
├── .env.example                 # 环境变量模板
├── requirements.txt
├── README.md
└── PROJECT_HANDOFF.md           # 本文件
```

---

## 下一步计划

### v0.2 — 接通真实模型（优先级最高）
- [ ] 将 `runtime.plannerMode` 改为 `"live"`，配置真实 API Key
- [ ] 用真实模型测试场景 A 和 B，验证 planner prompt 的输出质量
- [ ] 修正 system prompt 中 `file.read` 参数名（当前 live 模式用 `filename`，mock 用 `path`，需统一）
- [ ] 添加 planner 输出的 JSON schema 约束（OpenAI response_format: json_object）

### v0.2 — 更多供应商适配
- [ ] `providers/deepseek.py` — DeepSeek（流式输出）
- [ ] `providers/gemini.py` — Google Gemini
- [ ] `providers/openrouter.py` — OpenRouter 多模型聚合

### v0.3 — 执行能力增强
- [ ] `rag_tools.py` 升级为 embedding 向量检索
- [ ] `web_tools.py` 接入真实搜索 API（Tavily / Brave）
- [ ] 步骤失败重试机制（可配置重试次数）
- [ ] `shell.exec` 受限沙箱（白名单命令）

### v0.4 — 可观测性
- [ ] JSON Lines 结构化日志，支持 ELK / Loki
- [ ] Prometheus metrics 接口
- [ ] WebSocket 实时推送执行进度

### v0.5 — 多 Agent
- [ ] SubAgent 调度器
- [ ] 共享状态锁（防多 Agent 冲突写设备状态）

### v1.0 — 前端与部署
- [ ] React 任务面板（提交、状态追踪、确认弹窗）
- [ ] Docker Compose 一键部署
- [ ] 多用户 JWT 认证
