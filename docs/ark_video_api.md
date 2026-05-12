# 火山方舟视频生成 API 接入说明

本文档覆盖 `sd2video` 对火山方舟 Seedance 视频生成任务的创建、查询、列表、删除、轮询工作流和测试方式。

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `ARK_API_KEY` | 是 | 火山方舟 API Key。不要写入代码、日志或 issue 评论。 |
| `ARK_BASE_URL` | 否 | 默认 `https://ark.cn-beijing.volces.com`。 |
| `ARK_DEFAULT_MODEL_ID` | 否 | 默认模型 ID，默认 `doubao-seedance-2-0-fast-260128`。 |
| `ARK_TIMEOUT_SECONDS` | 否 | HTTP 请求超时秒数，默认 `30.0`。 |

## 安装和测试

```bash
pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m unittest discover
python3 -m compileall -q src tests
```

默认测试全部使用 mock transport，不访问外网，也不需要真实密钥。

## 创建任务

```python
from sd2video import ArkClient, ArkConfig, CreateTaskRequest

client = ArkClient.from_env()

request = CreateTaskRequest.text_to_video(
    "A cinematic shot of clouds moving over a mountain.",
    ratio="16:9",
    resolution="480p",
    duration=4,
)

task_id = client.create_task(request)
print(task_id)
```

图生视频：

```python
request = CreateTaskRequest.image_to_video(
    "https://example.com/first-frame.png",
    prompt="Animate the scene with a slow camera pan.",
    ratio="16:9",
    duration=4,
)
task_id = client.create_task(request)
```

首尾帧：

```python
request = CreateTaskRequest.image_to_video(
    "https://example.com/start.png",
    last_frame_url="https://example.com/end.png",
    prompt="Make a smooth transition between the two frames.",
)
task_id = client.create_task(request)
```

## 查询和轮询

单次查询：

```python
detail = client.get_task(task_id)
print(detail.status, detail.video_url)
```

完整工作流：

```python
from sd2video import VideoGenerationWorkflow, WorkflowConfig

workflow = VideoGenerationWorkflow.from_env(
    config=WorkflowConfig(
        poll_interval_seconds=5,
        poll_timeout_seconds=600,
    )
)

state = workflow.run(
    "A tiny robot watering a plant.",
    ratio="1:1",
    resolution="480p",
    duration=4,
)

if state.succeeded:
    print(state.video_url)
else:
    print(state.status, state.error_message)
```

轮询会在 `succeeded`、`failed`、`cancelled`、`deleted` 等终态停止；`queued` 和 `running` 不会被误判为失败。

## 列表和筛选

```python
result = client.list_tasks(page_num=1, page_size=10)
running = client.list_tasks(status_filter="running")
selected = client.list_tasks(task_ids=["cgt-xxx", "cgt-yyy"])
```

任务列表可用于历史记录、恢复本地状态、批量展示结果。历史窗口、结果 URL 有效期等限制以火山方舟官方文档和控制台说明为准。

## 取消或删除

```python
result = client.delete_task(task_id, current_status="running")
print(result.status)
```

工作流层默认支持确认回调：

```python
from sd2video import WorkflowCallbacks, VideoGenerationWorkflow

workflow = VideoGenerationWorkflow.from_env(
    callbacks=WorkflowCallbacks(
        on_confirm_cancel=lambda task_id, status: status in {"queued", "running"},
        on_confirm_delete=lambda task_id, status: status in {"succeeded", "failed", "cancelled"},
    )
)

# queued/running 任务走取消
workflow.cancel(task_id, confirm=True)

# 终态历史任务走删除；从列表拿到状态时可传入，避免先创建本地 queued 状态
workflow.delete(task_id, confirm=True, current_status="succeeded")
```

对空任务 ID、路径分隔符、未知本地状态、无权限、任务不存在、重复删除等情况会返回可读错误。

## 常见错误

- `ArkConfigError`：缺少 `ARK_API_KEY`、Base URL 无效、超时配置非法。
- `ArkParameterError`：任务 ID、分页参数、状态筛选、创建任务参数非法。
- `ArkAuthenticationError`：API Key 无效或无权限。
- `ArkTaskDeleteError`：删除/取消失败，通常是任务不存在、重复删除、无权限或远端状态不允许。
- `ArkTimeoutError` / `ArkNetworkError`：网络或超时问题。

异常消息会自动隐藏 API Key。

## 费用和 smoke test

默认测试不会创建真实视频。真实 smoke test 需要显式打开：

```bash
export ARK_RUN_SMOKE_TESTS=1
export ARK_API_KEY="..."
python3 -m unittest tests.test_smoke_ark_video_api.ArkVideoApiSmokeTest.test_list_tasks_live
```

创建真实任务可能产生费用，必须额外显式开启：

```bash
export ARK_RUN_SMOKE_TESTS=1
export ARK_SMOKE_CREATE_TASK=1
export ARK_API_KEY="..."
export ARK_SMOKE_MODEL_ID="doubao-seedance-2-0-fast-260128"
export ARK_SMOKE_DURATION=4
export ARK_SMOKE_RESOLUTION=480p
python3 -m unittest tests.test_smoke_ark_video_api.ArkVideoApiSmokeTest.test_create_task_live_explicit_cost_opt_in
```

建议使用最低可接受分辨率和最短时长，跑完后在控制台确认任务状态和费用。
