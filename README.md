# FlowGuard Agent v0.2.0

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
| 模型输出不可靠 | Parser 支持普通 JSON、代码块包裹、双重转义、前后夹杂说明文字，解析失败则拒绝执行 |

---

## 快速启动

```bash
# 1. 克隆项目
git clone <repo-url>
cd flowguard-agent

# 2. 创建虚拟环境
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量（仅 model 模式需要）
cp .env.example .env
# 编辑 .env，填入 MODEL_API_KEY=your-api-key-here

# 5. 启动服务（默认 mock 模式，无需 API Key）
uvicorn backend.main:app --reload --port 8000

# 6. 打开交互式文档
# http://localhost:8000/docs

# 7. 运行单元测试
pytest tests/ -v
```

---

## 两种 Planner 模式

| 模式 | 配置 | 说明 |
|------|------|------|
| **mock** | `"plannerMode": "mock"` | 默认。基于关键词匹配返回固定计划，无需 API Key |
| **model** | `"plannerMode": "model"` | 调用真实 LLM 生成计划，需要 `.env` 中配置 `MODEL_API_KEY` |

切换模式只需修改 `agent.config.json` 中 `runtime.plannerMode` 的值。

**切换到 model 模式：**

1. 在 `.env` 中填入 `MODEL_API_KEY=your-real-key`
2. 在 `agent.config.json` 中修改供应商和模型：

```json
"providers": {
  "openai_compatible": {
    "baseUrl": "https://api.openai.com/v1",
    "apiKeyEnvVar": "MODEL_API_KEY"
  }
},
"models": {
  "planner": {
    "model": "gpt-4o"
  }
},
"runtime": {
  "plannerMode": "model"
}
```

常用供应商：

| 供应商 | baseUrl | model 示例 |
|--------|---------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-72B-Instruct` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o` |

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
│   │   └── openai_compatible.py  # OpenAI-compatible 实现（懒加载 API Key）
│   ├── tools/
│   │   ├── file_tools.py    # file.read / file.write / file.list
│   │   ├── device_tools.py  # device.get_state / device.set_state
│   │   ├── rag_tools.py     # rag.search（关键词检索）
│   │   └── web_tools.py     # web.search（mock）
│   ├── state/
│   │   ├── state_manager.py # 任务状态管理 → data/state.json
│   │   └── log_manager.py   # 执行日志管理 → data/execution_log.json
│   └── schemas/
│       ├── plan_schema.py   # ExecutionPlan / PlanStep
│       └── tool_schema.py   # ToolCallRecord
├── tests/
│   └── test_parse_plan_json.py  # Parser 和字段规范化单元测试
├── workspace/
│   ├── device_state.json    # 设备状态数据源
│   └── test.md              # 测试文档
├── data/
│   ├── state.json           # 任务状态持久化
│   └── execution_log.json   # 执行日志（append-only）
├── docs/
│   ├── testing-guide.md     # Swagger 测试操作手册
│   └── demo-script.md       # 面试/作品集演示脚本
├── agent.config.json        # 主配置文件
├── .env.example             # 环境变量模板
├── .gitignore
├── requirements.txt
└── README.md
```

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/agent/run` | 提交任务（自然语言 → 计划 → 执行） |
| `POST` | `/agent/confirm` | 确认或取消高风险动作 |
| `GET` | `/agent/state` | 查看所有任务状态 |
| `GET` | `/agent/logs` | 查看工具调用执行日志 |

---

## 验收用例

### 用例 1：文件读取总结

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message": "读取 test.md"}'
```

期望：`status: "completed"`，`file.read` 返回真实文件内容。

### 用例 2：多设备任务编排（回家模式）

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message": "回家模式"}'
```

期望：`status: "confirmation_required"`，`pending_actions` 中有 door_lock unlock。

```bash
curl -X POST http://localhost:8000/agent/confirm \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "confirm": true}'
```

期望：`status: "completed"`，5 步全部执行成功。

---

## v0.1 验收结果

以下接口测试均在 `plannerMode = "mock"` 模式下通过，无需 API Key。

| 接口 | 测试场景 | 结果 |
|------|----------|------|
| `GET /health` | 服务在线检查 | 通过 |
| `GET /agent/state` | 返回任务状态字典 | 通过 |
| `GET /agent/logs` | 返回工具调用日志数组 | 通过 |
| `POST /agent/run` | 文件读取总结 | 通过，`status: completed`，file.read 返回文件内容 |
| `POST /agent/run` | 回家模式 | 通过，`status: confirmation_required`，door_lock 进入 pending_actions |
| `POST /agent/confirm` | 确认执行 | 通过，5 步全部执行，door_lock → unlocked |
| `POST /agent/confirm` | 拒绝执行 | 通过，`status: cancelled`，无动作执行 |

---

## v0.2 验收结果

### mock planner 回归

v0.1 所有测试在 v0.2 代码上回归通过，mock planner 行为不变。

### model planner（真实模型）

| 测试场景 | 结果 | 说明 |
|----------|------|------|
| file.read 读取 test.md | 通过 | 真实模型生成 `file.read` 计划，Runtime 执行后返回 `completed` |
| 回家模式（高风险拦截） | 通过 | 模型生成含 door_lock unlock 的计划，Runtime 独立拦截为 `confirmation_required` |
| confirm 后继续执行 | 通过 | 确认后 5 步全部执行，`completed` |
| state/logs 追踪 | 通过 | `GET /agent/state` 和 `GET /agent/logs` 均记录完整执行链路 |

### Parser 鲁棒性

| 输入格式 | 结果 |
|----------|------|
| 普通 JSON | 通过 |
| ` ```json ... ``` ` 代码块包裹 | 通过 |
| 双重转义 JSON 字符串 | 通过 |
| JSON 前后夹杂说明文字 | 通过 |
| 纯文本（无法解析） | 返回 `plan_parse_failed`，不执行任何工具 |

### 安全规则

- door_lock unlock 始终被 Runtime `_check_safety` 独立拦截为 `confirmation_required`，不依赖模型标记
- 未知 action 名返回 `plan_validation_failed`
- 解析失败返回 `plan_parse_failed`，绝不执行工具

### 单元测试

```
tests/test_parse_plan_json.py — 7 passed
```

详细操作步骤见 [docs/testing-guide.md](docs/testing-guide.md)。
演示脚本见 [docs/demo-script.md](docs/demo-script.md)。

---

## 执行日志格式

每条日志记录格式：

```json
{
  "task_id": "abc12345",
  "step_id": "step_1",
  "tool_name": "device.get_state",
  "args": {},
  "result": {"status": "success", "devices": {"...": "..."}},
  "status": "success",
  "timestamp": "2026-04-25T10:30:00.123456+00:00"
}
```

---

## 后续扩展方向

### v0.3 — 检索与执行增强
- [ ] RAG 升级为 embedding 向量检索
- [ ] web.search 接入真实搜索 API
- [ ] vision 模型角色 — 图像理解
- [ ] 步骤重试机制（可配置次数）

### v0.4 — 可观测性
- [ ] 结构化日志（JSON Lines，支持 ELK / Loki）
- [ ] Prometheus metrics 接口
- [ ] WebSocket 实时推送执行进度

### v0.5 — 多 Agent
- [ ] SubAgent 调度器
- [ ] Agent 间通信协议
- [ ] 共享状态锁

### v1.0 — 前端与部署
- [ ] React 前端 — 任务提交、状态追踪、确认弹窗
- [ ] Docker Compose 部署方案
- [ ] 多用户认证（JWT）
