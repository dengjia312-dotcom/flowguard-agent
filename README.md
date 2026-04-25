# FlowGuard Agent v0.1.0

**Workflow-first AI Agent Runtime for multi-device task orchestration and conflict handling.**

---

## 项目简介

FlowGuard Agent 是一个执行型 AI Agent 框架，核心理念是 **workflow-first**：  
Agent 不是聊天机器人，而是一个可校验、可确认、可追溯的任务执行引擎。

它面向「多设备 / 多系统任务编排与冲突处理」场景，验证 AI Agent 如何将自然语言目标转化为结构化执行流程。

---

## 项目解决的问题

| 问题 | 解决方案 |
|------|----------|
| Agent 假完成 | 工具未返回 `status=success` 时，摘要不允许写"已完成" |
| Agent 跳步 | 每步必须经过 planner → validate → safety check → execute → log |
| 高风险动作失控 | 门锁解锁、摄像头关闭等必须进入 `confirmation_required` 状态 |
| 多设备状态冲突 | 运行时检测冲突（窗开着开空调、安防开着解锁门），写入 conflicts 字段 |
| 执行不可追溯 | 所有工具调用写入 `data/execution_log.json`（tool_name/args/result/status/timestamp）|
| 模型强绑定 | 业务层只调用 `ModelRouter.call("planner", messages)`，不接触具体供应商 |

---

## 项目结构

```
flowguard-agent/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── config_loader.py     # 加载 agent.config.json
│   ├── agent_runtime.py     # 核心执行引擎（11步工作流）
│   ├── model_router.py      # 模型角色路由（业务层唯一调用点）
│   ├── providers/
│   │   ├── base.py          # BaseProviderAdapter 抽象接口
│   │   └── openai_compatible.py  # OpenAI-compatible 实现
│   ├── tools/
│   │   ├── file_tools.py    # file.read / file.write / file.list
│   │   ├── device_tools.py  # device.get_state / device.set_state
│   │   ├── rag_tools.py     # rag.search（v0.1: 关键词检索）
│   │   └── web_tools.py     # web.search（v0.1: mock）
│   ├── state/
│   │   ├── state_manager.py # 任务状态管理 → data/state.json
│   │   └── log_manager.py   # 执行日志管理 → data/execution_log.json
│   └── schemas/
│       ├── plan_schema.py   # ExecutionPlan / PlanStep
│       └── tool_schema.py   # ToolCallRecord
├── workspace/
│   ├── device_state.json    # 设备状态数据源
│   └── test.md              # 测试文档（验收用例 2）
├── data/
│   ├── state.json           # 任务状态持久化
│   └── execution_log.json   # 执行日志（append-only）
├── agent.config.json        # 主配置文件
├── .env.example             # 环境变量模板
├── requirements.txt
└── README.md
```

---

## 安装依赖

```bash
# 进入项目目录
cd flowguard-agent

# 创建虚拟环境（推荐）
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

---

## 配置 .env

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，填入你的 API Key
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 配置 agent.config.json

关键字段说明：

```json
{
  "providers": {
    "openai_compatible": {
      "baseUrl": "https://api.openai.com/v1",   // 修改为其他兼容供应商的 URL
      "apiKeyEnvVar": "OPENAI_API_KEY"           // 对应 .env 中的变量名
    }
  },
  "models": {
    "planner": {
      "provider": "openai_compatible",
      "model": "gpt-4o",                         // 修改为任意支持的模型名
      "temperature": 0.2,
      "maxTokens": 4096
    }
  }
}
```

**切换供应商示例（不改代码，只改配置）：**

```json
// 使用 DeepSeek（OpenAI-compatible）
"providers": {
  "openai_compatible": {
    "baseUrl": "https://api.deepseek.com/v1",
    "apiKeyEnvVar": "DEEPSEEK_API_KEY"
  }
},
"models": {
  "planner": {
    "provider": "openai_compatible",
    "model": "deepseek-chat"
  }
}
```

```json
// 使用 硅基流动 SiliconFlow
"providers": {
  "openai_compatible": {
    "baseUrl": "https://api.siliconflow.cn/v1",
    "apiKeyEnvVar": "SILICONFLOW_API_KEY"
  }
},
"models": {
  "planner": {
    "provider": "openai_compatible",
    "model": "Qwen/Qwen2.5-72B-Instruct"
  }
}
```

---

## 启动命令

```bash
# 确保在 flowguard-agent/ 目录下运行
cd flowguard-agent

# 启动服务（开发模式，自动重载）
uvicorn backend.main:app --reload --port 8000

# 访问交互式文档
http://localhost:8000/docs
```

---

## API 测试示例

### 健康检查

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "service": "FlowGuard Agent", "version": "0.1.0"}
```

### 提交任务

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我读取 test.md 并总结"}'
```

### 查看任务状态

```bash
curl http://localhost:8000/agent/state
```

### 查看执行日志

```bash
curl http://localhost:8000/agent/logs
```

### 确认高风险动作

```bash
# 先提交会触发确认的任务
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message": "我快到家了，帮我开启回家模式"}'

# 响应中获取 task_id，然后确认
curl -X POST http://localhost:8000/agent/confirm \
  -H "Content-Type: application/json" \
  -d '{"task_id": "abc12345", "confirm": true}'

# 或取消
curl -X POST http://localhost:8000/agent/confirm \
  -H "Content-Type: application/json" \
  -d '{"task_id": "abc12345", "confirm": false}'
```

---

## 验收用例

### 用例 1：多设备任务编排（回家模式）

**输入：**
```json
POST /agent/run
{"message": "我快到家了，帮我开启回家模式"}
```

**期望行为：**
1. Agent 读取 `workspace/device_state.json`
2. Planner 生成包含多步骤的执行计划
3. 低风险动作（开客厅灯、开空调、暂停扫地机器人）标记为可执行
4. 解锁门锁（`door_lock` → `unlock`）被标记为 `requires_confirmation=true`
5. 返回 `confirmation_required` 状态，列出 pending_actions
6. 调用 `POST /agent/confirm` 确认后，所有步骤执行并写入 `execution_log.json`

**期望响应（含门锁时）：**
```json
{
  "status": "confirmation_required",
  "task_id": "abc12345",
  "message": "检测到 1 个高风险动作，需要用户确认后才能执行",
  "pending_actions": [
    {
      "step_id": "step_4",
      "action": "device.set_state",
      "args": {"device_id": "door_lock", "new_status": "unlock"},
      "risk": "high",
      "description": "解锁门锁"
    }
  ],
  "safe_steps_preview": [...]
}
```

### 用例 2：文件读取总结

**输入：**
```json
POST /agent/run
{"message": "帮我读取 test.md 并总结"}
```

**期望行为：**
1. Planner 生成计划：`file.read` → 总结
2. `file.read` 调用 `FileTools.read("test.md")` 读取真实文件内容
3. 工具调用写入 `execution_log.json`（tool_name=file.read, status=success）
4. 返回基于真实文件内容的总结

**如果文件不存在：**
```json
{
  "status": "failed",
  "message": "无法完成任务：file.read 返回 status=failed",
  "executed_actions": [
    {
      "tool": "file.read",
      "status": "failed",
      "result": {"status": "failed", "error": "File not found: nonexistent.md"}
    }
  ]
}
```

注意：文件不存在时，最终回答不能假装总结成功。

---

## 执行日志格式

每条日志记录格式：

```json
{
  "task_id": "abc12345",
  "step_id": "step_1",
  "tool_name": "device.get_state",
  "args": {},
  "result": {"status": "success", "devices": {...}},
  "status": "success",
  "timestamp": "2026-04-25T10:30:00.123456+00:00"
}
```

---

## v0.1 验收结果

以下接口测试均在 `runtime.plannerMode = "mock"` 模式下通过，无需真实 API Key。

| 接口 | 测试场景 | 结果 |
|------|----------|------|
| `GET /health` | 服务在线检查 | ✅ 通过 |
| `GET /agent/state` | 返回任务状态字典 | ✅ 通过 |
| `GET /agent/logs` | 返回工具调用日志数组 | ✅ 通过 |
| `POST /agent/run` | 文件读取总结（`"读取 test.md"`） | ✅ 通过，`status: completed`，file.read 返回文件内容 |
| `POST /agent/run` | 回家模式（`"回家模式"`） | ✅ 通过，`status: confirmation_required`，door_lock 进入 pending_actions |
| `POST /agent/confirm` | 高风险确认（`confirm: true`） | ✅ 通过，5 步全部执行，door_lock 状态变为 unlocked |
| `POST /agent/confirm` | 高风险拒绝（`confirm: false`） | ✅ 通过，`status: cancelled`，无任何动作执行 |

**关键验收点：**
- Runtime 11 步工作流完整跑通（plan → validate → safety → execute → log → state）
- 高风险动作（door_lock unlock）被 Runtime 独立拦截，不依赖 Planner 标记
- 每次工具调用均写入 execution_log.json，包含 tool_name / args / result / status / timestamp
- 工具失败时，最终摘要不声称"已完成"（假完成防护有效）
- mock planner 产生的计划与 live planner 走同一套校验和执行流程

详细操作步骤见 [docs/testing-guide.md](docs/testing-guide.md)。

---

## 后续扩展方向

### v0.2 — 模型与检索增强
- [ ] `providers/deepseek.py` — DeepSeek 专属适配（流式输出）
- [ ] `providers/gemini.py` — Google Gemini 适配
- [ ] `providers/openrouter.py` — OpenRouter 多模型聚合
- [ ] `providers/siliconflow.py` — 硅基流动国内模型
- [ ] `rag_tools.py` — 升级为 embedding 向量检索（接通 embedding 模型角色）
- [ ] `web_tools.py` — 接入真实搜索 API（Tavily / Bing / Brave）

### v0.3 — 执行能力增强
- [ ] `vision` 模型角色 — 实现图像理解（设备摄像头截图分析）
- [ ] `imageGeneration` 模型角色 — 实现图像生成
- [ ] `shell.exec` — 受限沙箱执行（白名单命令）
- [ ] 步骤重试机制 — 失败步骤自动重试（可配置次数）

### v0.4 — 可观测性
- [ ] 结构化日志（JSON Lines 格式，支持 ELK / Loki）
- [ ] Prometheus metrics 接口（任务成功率、延迟分位数）
- [ ] WebSocket 实时推送执行进度

### v0.5 — 多 Agent
- [ ] SubAgent 调度器 — 主脑拆分子任务给专属 Agent
- [ ] Agent 间通信协议
- [ ] 共享状态锁（防止多 Agent 冲突写入设备状态）

### v1.0 — 前端与部署
- [ ] React 前端 — 任务提交、状态追踪、确认弹窗
- [ ] Docker Compose 部署方案
- [ ] 多用户认证（JWT）
- [ ] 配置热重载（不重启服务修改 agent.config.json）
