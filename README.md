# sd2video
视频生成工具

## 火山方舟配置

客户端从环境变量读取火山方舟配置，不要把真实密钥写入代码或提交到仓库。

```bash
export ARK_API_KEY="<your-api-key>"
export ARK_BASE_URL="https://ark.cn-beijing.volces.com"
export ARK_DEFAULT_MODEL_ID="doubao-seedance-2-0-fast-260128"
export ARK_TIMEOUT_SECONDS="30"
```

如果账号开通的是其他视频生成模型，直接覆盖 `ARK_DEFAULT_MODEL_ID`。

统一入口位于 `sd2video.ark.ArkClient`：

```python
from sd2video.ark import ArkClient

client = ArkClient.from_env()
response = client.request_tasks(
    "POST",
    json={
        "model": client.config.default_model_id,
        "content": [],
    },
)
```

`ArkClient` 会统一拼接 `/api/v3/contents/generations/tasks`，并自动添加
`Authorization: Bearer <ARK_API_KEY>` 与 `Content-Type: application/json`。
调用方可以通过 mock `ArkTransport` 单元测试创建、查询、列表和删除任务流程。
