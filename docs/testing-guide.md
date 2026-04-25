# FlowGuard Agent — Swagger 测试操作手册

本文档说明如何在 `http://localhost:8000/docs` 中完整测试 v0.1 的所有接口。

**前提：** 服务已在 mock 模式下启动（`agent.config.json` 中 `runtime.plannerMode = "mock"`），无需配置 API Key。

```bash
cd flowguard-agent
uvicorn backend.main:app --reload --port 8000
# 然后打开浏览器访问 http://localhost:8000/docs
```

---

## 测试顺序建议

按以下顺序测试，每步都有明确的期望结果：

1. 健康检查（确认服务在线）
2. 文件读取总结（最简单路径，无确认）
3. 查看 state（验证任务已记录）
4. 查看 logs（验证工具调用已记录）
5. 回家模式（触发高风险确认流程）
6. 高风险确认（完成确认流程）
7. 再次查看 logs（验证所有步骤已记录）

---

## 1. GET /health — 健康检查

**目的：** 确认服务正常启动。

**操作：**
1. 在 Swagger 页找到 `GET /health`，点击 **Try it out**
2. 点击 **Execute**

**期望响应（200）：**
```json
{
  "status": "ok",
  "service": "FlowGuard Agent",
  "version": "0.1.0"
}
```

---

## 2. POST /agent/run — 文件读取总结

**目的：** 测试低风险任务的完整执行路径（无需确认）。

**操作：**
1. 找到 `POST /agent/run`，点击 **Try it out**
2. 在 Request body 中输入：

```json
{
  "message": "读取 test.md"
}
```

3. 点击 **Execute**

**期望响应（200）：**
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
  ],
  "conflicts": [],
  "note": "All steps executed successfully."
}
```

**验证点：**
- `status` 为 `"completed"`
- `executed_actions[0].tool` 为 `"file.read"`
- `executed_actions[0].status` 为 `"success"`
- `result.content` 包含 test.md 的真实内容

---

## 3. GET /agent/state — 查看任务状态

**目的：** 验证上一步的任务已被持久化到 state.json。

**操作：**
1. 找到 `GET /agent/state`，点击 **Try it out**
2. 点击 **Execute**

**期望响应（200）：**
```json
{
  "tasks": {
    "xxxxxxxx": {
      "status": "completed",
      "message": "读取 test.md",
      "createdAt": "2026-04-25T...",
      "results": [...],
      "plan": {...}
    }
  }
}
```

**验证点：**
- 可以看到刚才提交的任务，`status` 为 `"completed"`

---

## 4. GET /agent/logs — 查看执行日志

**目的：** 验证工具调用已被完整记录到 execution_log.json。

**操作：**
1. 找到 `GET /agent/logs`，点击 **Try it out**
2. 点击 **Execute**

**期望响应（200）：**
```json
{
  "logs": [
    {
      "task_id": "xxxxxxxx",
      "step_id": "step_1",
      "tool_name": "file.read",
      "args": {"path": "test.md"},
      "result": {"status": "success", "content": "..."},
      "status": "success",
      "timestamp": "2026-04-25T..."
    }
  ]
}
```

**验证点：**
- `tool_name`、`args`、`result`、`status`、`timestamp` 全部存在
- `status` 为 `"success"`

---

## 5. POST /agent/run — 回家模式（触发确认）

**目的：** 测试高风险动作拦截流程。door_lock 解锁必须进入 `confirmation_required`。

**操作：**
1. 找到 `POST /agent/run`，点击 **Try it out**
2. 输入：

```json
{
  "message": "回家模式"
}
```

3. 点击 **Execute**
4. **记录响应中的 `task_id`**（下一步需要用到）

**期望响应（200）：**
```json
{
  "status": "confirmation_required",
  "task_id": "yyyyyyyy",
  "message": "检测到 1 个高风险动作，需要用户确认后才能执行。低风险步骤（4 个）已就绪，等待整体确认后统一执行。",
  "pending_actions": [
    {
      "step_id": "step_5",
      "action": "device.set_state",
      "args": {"device_id": "door_lock", "status": "unlocked"},
      "risk": "high",
      "description": null
    }
  ],
  "safe_steps_preview": [
    {"step_id": "step_1", "action": "device.get_state", "risk": "low", ...},
    {"step_id": "step_2", "action": "device.set_state", "risk": "low", ...},
    {"step_id": "step_3", "action": "device.set_state", "risk": "medium", ...},
    {"step_id": "step_4", "action": "device.set_state", "risk": "low", ...}
  ],
  "conflicts": []
}
```

**验证点：**
- `status` 为 `"confirmation_required"`（不是 `completed`，任务被暂停）
- `pending_actions` 中有且仅有 step_5（door_lock unlock）
- `safe_steps_preview` 包含 4 个低/中风险步骤
- **此时任何动作都还未执行**（包括开灯、开空调）

---

## 6. POST /agent/confirm — 确认高风险动作

### 6a. 确认执行（confirm: true）

**操作：**
1. 找到 `POST /agent/confirm`，点击 **Try it out**
2. 将 `task_id` 替换为上一步记录的值：

```json
{
  "task_id": "yyyyyyyy",
  "confirm": true
}
```

3. 点击 **Execute**

**期望响应（200）：**
```json
{
  "status": "completed",
  "task_id": "yyyyyyyy",
  "goal": "开启回家模式",
  "summary": {
    "total_steps": 5,
    "successful": 5,
    "failed": 0,
    "pending_confirmation": 0,
    "skipped": 0
  },
  "executed_actions": [
    {"step_id": "step_1", "tool": "device.get_state", "status": "success", ...},
    {"step_id": "step_2", "tool": "device.set_state", "status": "success", ...},
    {"step_id": "step_3", "tool": "device.set_state", "status": "success", ...},
    {"step_id": "step_4", "tool": "device.set_state", "status": "success", ...},
    {"step_id": "step_5", "tool": "device.set_state", "status": "success", ...}
  ]
}
```

**验证点：**
- `status` 为 `"completed"`
- 全部 5 步 `status` 均为 `"success"`
- 可以在 `GET /agent/logs` 中看到 5 条新日志

### 6b. 拒绝执行（confirm: false）

如需测试取消流程，先重新提交一次"回家模式"，获取新 `task_id`，然后：

```json
{
  "task_id": "zzzzzzzz",
  "confirm": false
}
```

**期望响应：**
```json
{
  "status": "cancelled",
  "task_id": "zzzzzzzz",
  "message": "Task cancelled by user. No actions were executed."
}
```

**验证点：**
- `status` 为 `"cancelled"`
- `GET /agent/logs` 中没有该 task_id 的任何执行记录

---

## 7. 再次 GET /agent/logs — 验证完整执行记录

**操作：** 再次调用 `GET /agent/logs`

**验证点：**
- 可以看到"回家模式"任务的 5 条日志（device.get_state × 1，device.set_state × 4）
- 每条记录都有完整的 `task_id / step_id / tool_name / args / result / status / timestamp`
- door_lock 的 set_state 记录中，`result.new_status` 为 `"unlocked"`

---

## 常见问题

**Q: POST /agent/run 返回 `status: "error"`，提示 Planner call failed**

检查 `agent.config.json`：
```json
"runtime": {
  "plannerMode": "mock"
}
```
确认 `plannerMode` 值为 `"mock"` 而不是 `"live"`。

**Q: POST /agent/confirm 返回 Task not found**

task_id 已过期或输入有误。重新提交"回家模式"获取新的 task_id。

**Q: POST /agent/confirm 返回 Task is not awaiting confirmation**

该任务已经被确认/取消过了。重新提交一次"回家模式"。

**Q: file.read 返回 `status: "failed"`, error: "File not found"**

确认 `workspace/test.md` 文件存在。从项目根目录运行 `uvicorn`（不是从 `backend/` 目录）。
