# FlowGuard Agent — Swagger 测试操作手册

本文档说明如何在 `http://localhost:8000/docs` 中完整测试所有接口，覆盖 mock 和 model 两种 planner 模式。

---

## 前置准备

```bash
cd flowguard-agent
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Part 1 — mock 模式测试（无需 API Key）

确认 `agent.config.json` 中：
```json
"runtime": { "plannerMode": "mock" }
```

启动服务：
```bash
uvicorn backend.main:app --reload --port 8000
# 打开 http://localhost:8000/docs
```

### 测试顺序

1. 健康检查（确认服务在线）
2. 文件读取总结（最简单路径，无确认）
3. 查看 state（验证任务已记录）
4. 查看 logs（验证工具调用已记录）
5. 回家模式（触发高风险确认流程）
6. 高风险确认（完成确认流程）
7. 再次查看 logs（验证所有步骤已记录）

---

### 1. GET /health — 健康检查

点击 **Try it out** → **Execute**

**期望响应（200）：**
```json
{
  "status": "ok",
  "service": "FlowGuard Agent",
  "version": "0.2.0"
}
```

---

### 2. POST /agent/run — 文件读取总结

Request body：
```json
{ "message": "读取 test.md" }
```

**期望响应：**
```json
{
  "status": "completed",
  "task_id": "xxxxxxxx",
  "goal": "读取并总结 test.md",
  "summary": {
    "total_steps": 1,
    "successful": 1,
    "failed": 0,
    "pending_confirmation": 0,
    "skipped": 0
  },
  "executed_actions": [
    {
      "step_id": "step_1",
      "tool": "file.read",
      "status": "success",
      "result": {
        "status": "success",
        "filename": "test.md",
        "content": "..."
      }
    }
  ]
}
```

**验证点：**
- `status` 为 `"completed"`
- `result.content` 包含 test.md 的真实内容

---

### 3. GET /agent/state — 查看任务状态

**验证点：** 可以看到刚才的任务，`status` 为 `"completed"`

---

### 4. GET /agent/logs — 查看执行日志

**验证点：** 每条记录都有 `task_id / step_id / tool_name / args / result / status / timestamp`

---

### 5. POST /agent/run — 回家模式（触发确认）

```json
{ "message": "回家模式" }
```

**记录响应中的 `task_id`（下一步需要用到）**

**期望响应：**
```json
{
  "status": "confirmation_required",
  "task_id": "yyyyyyyy",
  "message": "检测到 1 个高风险动作...",
  "pending_actions": [
    {
      "step_id": "step_5",
      "action": "device.set_state",
      "args": {"device_id": "door_lock", "status": "unlocked"},
      "risk": "high"
    }
  ],
  "safe_steps_preview": [...]
}
```

**验证点：**
- `status` 为 `"confirmation_required"`
- `pending_actions` 中有且仅有 door_lock unlock
- 此时**任何动作都还未执行**

---

### 6. POST /agent/confirm — 确认高风险动作

#### 6a. 确认执行

```json
{ "task_id": "yyyyyyyy", "confirm": true }
```

**期望：** `status: "completed"`，全部 5 步 `success`

#### 6b. 拒绝执行

先重新提交"回家模式"获取新 task_id，然后：
```json
{ "task_id": "zzzzzzzz", "confirm": false }
```

**期望：** `status: "cancelled"`，`GET /agent/logs` 中无该 task_id 的记录

---

### 7. 再次 GET /agent/logs

**验证点：** 回家模式确认后的 5 条日志完整记录（device.get_state x1, device.set_state x4）

---

## Part 2 — model 模式测试（需要 API Key）

### 配置步骤

**步骤 1：** 配置 `.env`

```bash
cp .env.example .env
# 编辑 .env：
# MODEL_API_KEY=your-api-key-here
```

**步骤 2：** 修改 `agent.config.json`

根据你的供应商修改以下字段：

```json
"providers": {
  "openai_compatible": {
    "baseUrl": "https://api.openai.com/v1",
    "apiKeyEnvVar": "MODEL_API_KEY"
  }
},
"models": {
  "planner": {
    "provider": "openai_compatible",
    "model": "gpt-4o",
    "temperature": 0.1,
    "maxTokens": 2048
  }
},
"runtime": {
  "plannerMode": "model"
}
```

**常用供应商配置：**

| 供应商 | baseUrl | model 示例 |
|--------|---------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-72B-Instruct` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o` |

**步骤 3：** 重启服务

```bash
uvicorn backend.main:app --reload --port 8000
```

---

### model 模式：测试文件读取

```json
{ "message": "帮我读取 test.md 并总结内容" }
```

**期望：** 真实模型生成 `file.read` 步骤，Runtime 执行后返回 `status: "completed"`。

**说明：** model 模式下，模型可能使用 `filename` 或 `path` 作为参数名，Runtime 的 `_normalize_step_args` 会在执行前统一规范化为 `filename`。

---

### model 模式：测试回家模式（高风险拦截）

```json
{ "message": "我快到家了，帮我开启回家模式" }
```

**期望：** 模型生成含 door_lock unlock 的计划，Runtime 独立校验后返回 `status: "confirmation_required"`。

**安全验证：** 即使模型没有正确设置 `requires_confirmation: true`，Runtime 的 `_check_safety` 会独立检测到 door_lock unlock，强制进入确认流程。这是 workflow-first 的核心保障。

确认后用 `POST /agent/confirm` 完成执行。

---

### 错误码排查

| 返回的 status | 原因 | 解决方法 |
|--------------|------|----------|
| `api_key_missing` | `.env` 中没有设置 `MODEL_API_KEY` | 检查 `.env` 文件，确认 key 存在且非空 |
| `model_call_failed` | 网络超时或 API 返回非 200 | 检查 baseUrl 是否正确；检查 key 是否有效；查看终端日志 |
| `plan_parse_failed` | 模型输出了非 JSON 内容 | 尝试 temperature 调低到 0.1；换用 JSON 能力更强的模型 |
| `plan_validation_failed` | 计划 JSON 缺少必填字段或包含未知 action | 查看返回的 `message` 和 `unknown_actions` 字段 |
| `confirmation_required` | 计划包含高风险动作（正常行为） | 用 `POST /agent/confirm` 确认或取消 |

---

## Part 3 — 单元测试

```bash
cd flowguard-agent
pytest tests/ -v
```

**期望输出：**
```
tests/test_parse_plan_json.py::test_plain_json PASSED
tests/test_parse_plan_json.py::test_json_code_fence PASSED
tests/test_parse_plan_json.py::test_double_encoded_json PASSED
tests/test_parse_plan_json.py::test_unparseable_returns_none PASSED
tests/test_parse_plan_json.py::test_json_embedded_in_prose PASSED
tests/test_parse_plan_json.py::test_normalize_new_status_to_status PASSED
tests/test_parse_plan_json.py::test_normalize_path_to_filename PASSED

7 passed
```

---

## 常见问题

**Q: POST /agent/run 返回 `status: "error"`，提示 Planner call failed**

检查 `agent.config.json`，确认 `plannerMode` 值为 `"mock"`：
```json
"runtime": { "plannerMode": "mock" }
```

**Q: POST /agent/confirm 返回 Task not found**

task_id 已过期或输入有误。重新提交"回家模式"获取新的 task_id。

**Q: POST /agent/confirm 返回 Task is not awaiting confirmation**

该任务已经被确认/取消过了。重新提交一次"回家模式"。

**Q: file.read 返回 `status: "failed"`, error: "File not found"**

确认 `workspace/test.md` 文件存在。从项目根目录运行 `uvicorn`（不是从 `backend/` 目录）。
