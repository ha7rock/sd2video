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
