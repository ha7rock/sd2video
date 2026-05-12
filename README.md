# sd2video

视频生成工具 — 基于火山方舟 (Volcengine Ark) Seedance 视频生成 API。

## 安装

```bash
pip install -e .
```

## 环境变量

| 变量 | 说明 | 必填 | 默认值 |
|------|------|------|--------|
| `ARK_API_KEY` | 火山方舟 API Key | ✅ | — |
| `ARK_BASE_URL` | API 基础地址 | ❌ | `https://ark.cn-beijing.volces.com` |
| `ARK_DEFAULT_MODEL_ID` | 默认模型 ID | ❌ | `doubao-seedance-2-0-fast-260128` |
| `ARK_TIMEOUT_SECONDS` | 请求超时（秒） | ❌ | `30.0` |

后端服务相关：

| 变量 | 说明 | 必填 | 默认值 |
|------|------|------|--------|
| `SD2VIDEO_MOCK` | `1` 启用 mock/dev 模式，不访问火山方舟 | ❌ | `0` |
| `SD2VIDEO_CORS_ORIGINS` | 允许访问后端的前端 Origin，逗号分隔 | ❌ | `http://localhost:5173,http://127.0.0.1:5173,file://` |
| `SD2VIDEO_BIND` | 后端监听地址 | ❌ | `127.0.0.1:8787` |
| `SD2VIDEO_POLL_INTERVAL_SECONDS` | 暴露给前端的推荐轮询间隔 | ❌ | `5.0` |
| `SD2VIDEO_POLL_TIMEOUT_SECONDS` | 暴露给前端的推荐轮询超时 | ❌ | `600.0` |

`ARK_API_KEY` 只在 `SD2VIDEO_MOCK=0` 的真实后端模式下读取，不会返回给前端、写入浏览器存储或包含在普通接口响应中。

## 本地后端服务

安装服务运行依赖：

```bash
pip install -e '.[server]'
```

启动 mock/dev 后端（不需要 `ARK_API_KEY`）：

```bash
export SD2VIDEO_MOCK=1
sd2video-server
# 或
python3 -m sd2video.server
```

启动真实火山方舟后端：

```bash
unset SD2VIDEO_MOCK
export ARK_API_KEY=你的火山方舟 API Key
sd2video-server
```

前端可调用的主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/health` | 服务健康状态 |
| `GET` | `/api/v1/capabilities` | 支持的模型、比例、分辨率、时长、资源数量等能力边界 |
| `POST` | `/api/v1/tasks` | 创建视频任务 |
| `GET` | `/api/v1/tasks` | 列表，支持 `page_num`、`page_size`、`status`、`task_ids` 查询参数 |
| `GET` | `/api/v1/tasks/{task_id}` | 查询单个任务 |
| `DELETE` | `/api/v1/tasks/{task_id}` | 删除或取消任务 |

mock 流程示例：

```bash
curl http://127.0.0.1:8787/api/v1/capabilities
curl -X POST http://127.0.0.1:8787/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"mode":"t2v","model":"doubao-seedance-2-0-fast-260128","prompt":"一只猫在跳舞","ratio":"16:9","duration":5}'
curl http://127.0.0.1:8787/api/v1/tasks
```

错误响应统一为：

```json
{
  "error": {
    "code": "parameter_invalid",
    "message": "...",
    "request_id": "..."
  }
}
```

常见错误码包括 `parameter_invalid`、`mode_constraint_violation`、`duplicate_request`、`task_not_found`、`task_state_conflict`、`upstream_unauthorized`、`upstream_failed`、`upstream_timeout`、`rate_limited`。

完整前后端契约见 `docs/api_contract.md`。

## 前端面板联调

HOM-22 面板快照在 `frontend_current/frontend/`。启动 mock/dev 后端后，可用静态文件服务打开画布：

```bash
export SD2VIDEO_MOCK=1
python3 -m sd2video.server --port 8787

cd frontend_current/frontend
python3 -m http.server 5173
```

如后端不在同源地址，可在页面加载前注入：

```html
<script>window.__SD2VIDEO_API_BASE__ = "http://127.0.0.1:8787";</script>
```

或在 HTML 里设置：

```html
<meta name="sd2video-api-base" content="http://127.0.0.1:8787">
```

前端提交统一调用 `POST /api/v1/tasks`，payload 只包含 `mode + prompt + assets` 等 contract 字段，并为每次提交生成 `client_request_id`。前端不发送 Ark 原始 `content` 数组，不发送 `negative_prompt`，也不接触 `ARK_API_KEY`。

## 快速使用

### 完整工作流（推荐）

```python
from sd2video import VideoGenerationWorkflow

wf = VideoGenerationWorkflow.from_env()

# 一步完成：提交 → 等待 → 获取结果
result = wf.run("一只猫在跳舞", ratio="16:9", duration=5)

if result.succeeded:
    print(f"视频地址: {result.video_url}")
else:
    print(f"状态: {result.status_label}, 错误: {result.error_message}")
```

### 分步操作

```python
from sd2video import VideoGenerationWorkflow, WorkflowCallbacks, WorkflowConfig

# 自定义轮询间隔和超时
config = WorkflowConfig(
    poll_interval_seconds=3,   # 每 3 秒轮询一次
    poll_timeout_seconds=300,  # 最长等待 5 分钟
)

# 可选回调
callbacks = WorkflowCallbacks(
    on_task_created=lambda tid: print(f"任务已创建: {tid}"),
    on_status_change=lambda tid, label: print(f"状态变更: {label}"),
    on_succeeded=lambda s: print(f"成功! 视频: {s.video_url}"),
    on_failed=lambda s: print(f"失败: {s.error_message}"),
    on_confirm_cancel=lambda tid, status: True,  # 自动确认取消
    on_confirm_delete=lambda tid, status: True,  # 自动确认删除终态任务
)

wf = VideoGenerationWorkflow.from_env(config=config, callbacks=callbacks)

# 1. 提交任务
state = wf.submit("一只猫在跳舞", ratio="16:9")
print(f"任务 ID: {state.task_id}")

# 2. 手动刷新状态
state = wf.refresh(state.task_id)
print(f"当前状态: {state.status_label}")

# 3. 轮询等待结果
result = wf.wait(state.task_id)
print(f"最终状态: {result.status_label}")
```

### 图生视频

```python
# 单图生视频（首帧）
result = wf.run(
    "让这只猫动起来",
    image_url="https://example.com/cat.png",
    ratio="1:1",
    duration=5,
)

# 首尾帧生视频
result = wf.run(
    "平滑过渡",
    image_url="https://example.com/start.png",
    last_frame_url="https://example.com/end.png",
    ratio="16:9",
    duration=8,
)
```

### 任务列表（历史记录）

```python
# 查看所有任务
result = wf.list(page_num=1, page_size=10)

# 按状态筛选
result = wf.list(status_filter="running")
result = wf.list(status_filter=["succeeded", "failed"])

for task in result.items:
    print(f"{task.task_id}: {task.status_label} - {task.video_url or '无视频'}")
```

### 取消/删除任务

```python
# queued/running 任务只能取消
state = wf.cancel(task_id, confirm=True)

# succeeded/failed/cancelled 等终态任务才能删除或隐藏
state = wf.delete(task_id, confirm=True, current_status="succeeded")
```

## 状态说明

| 状态 | 中文 | 说明 |
|------|------|------|
| `queued` | 排队中 | 任务已创建，等待执行 |
| `running` | 生成中 | 正在生成视频 |
| `succeeded` | 已完成 | 视频生成成功，可获取 video_url |
| `failed` | 生成失败 | 生成出错，查看 error_message |
| `cancelled` | 已取消 | 用户取消了任务 |
| `deleted` | 已删除 | 任务已被删除 |

## 支持的参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `ratio` | str | 比例：`16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9`, `adaptive` |
| `resolution` | str | 分辨率：`480p`, `720p`, `1080p` |
| `duration` | int | 时长（秒），按模型不同有范围限制 |
| `frames` | int | 帧数，范围 29-289 |
| `seed` | int | 随机种子，-1 为随机 |
| `camera_fixed` | bool | 固定镜头 |
| `watermark` | bool | 是否加水印 |
| `generate_audio` | bool | 是否生成音频 |
| `service_tier` | str | 服务等级：`default`, `flex` |

## 安全说明

- API Key 通过环境变量传入，**不会**出现在日志、错误信息或代码中
- 所有错误输出中的 API Key 会被自动替换为 `<redacted>`
- 删除操作默认需要确认，防止误操作

## 接入文档

更完整的创建、查询、列表、删除、轮询、错误处理和 smoke test 说明见：

```text
docs/ark_video_api.md
```

## 测试

```bash
pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m unittest discover
python3 -m compileall -q src tests
```

CI 默认只跑 mock 测试，不依赖外网或真实 API Key。
