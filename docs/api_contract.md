# 前后端接入契约与运行架构（HOM-23）

> 适用范围：HOM-22 视频生成画布前端 ↔ `sd2video` Python SDK。
>
> 这是给 HOM-24（后端服务）和 HOM-26 / HOM-27 / HOM-28 / HOM-29（前端真实工作流）的开发契约。
> 任何字段、错误码、状态枚举的修改都要回到本文件更新，再修代码。

---

## 0. TL;DR

- 运行架构：**前端 SPA + 本机/局域网内薄 HTTP 服务**，HTTP 服务用 FastAPI（或等价）封装 `sd2video` Python SDK。
- 通信协议：**JSON over HTTP**，前缀 `/api/v1`，所有响应字段使用 `snake_case`，与 SDK 一致。
- 密钥隔离：`ARK_API_KEY` **只在后端进程**读取，前端 bundle、`localStorage`、网络响应、错误信息中绝不出现。
- 关键端点（共 7 个）：
  - `GET /api/v1/health`
  - `GET /api/v1/capabilities`
  - `POST /api/v1/assets`
  - `POST /api/v1/tasks`
  - `GET /api/v1/tasks/{id}`
  - `GET /api/v1/tasks`
  - `DELETE /api/v1/tasks/{id}`
- 任务状态枚举：`queued | running | succeeded | failed | cancelled | deleted`。
- 错误统一格式：`{ "error": { "code": "...", "message": "...", "field": "...", "request_id": "..." } }`。

---

## 1. 运行架构

### 1.1 选定方案：薄 HTTP 服务

```
+----------------+     fetch (CORS)     +---------------------+     HTTPS     +-------------------+
|  Browser SPA   |  <----------------->  |  Backend HTTP API   |  --------->   |  Volcengine Ark   |
|  (canvas.html) |   JSON, snake_case   |  FastAPI + sd2video |   Bearer key  |  Seedance 2.0     |
+----------------+                       +---------------------+               +-------------------+
                                                   |
                                                   +-- ARK_API_KEY (env only)
                                                   +-- Local mock / dev mode
```

理由：

1. 现有 `sd2video` SDK 是同步 Python 实现（`ArkClient`、`VideoGenerationWorkflow`），最自然的包装是同步 HTTP service。
2. 前端是浏览器 SPA（`canvas.html` 内联 React/Babel），不是 Electron / Tauri 壳，没有 Node bridge 可用，必须走 HTTP。
3. 火山方舟 API Key 是**长期密钥**，不能下发到浏览器，必须由后端代持。

### 1.2 非选项（暂不做）

- **桌面壳 IPC**：当前 `canvas.html` 是纯浏览器 React，不必为桌面打包改架构。如果后续要做 Electron / Tauri，复用同一份 HTTP 契约即可（壳进程直连后端或 in-process 调 SDK）。
- **浏览器直连 Ark**：禁止。会泄露 `ARK_API_KEY`，并且 Ark 不下发 CORS 头。
- **WebSocket / SSE 推任务状态**：暂不引入。轮询 `GET /api/v1/tasks/{id}` 已经足够（SDK 默认 5s 间隔，参考 `WorkflowConfig.poll_interval_seconds`）。

### 1.3 部署形态

| 环境 | 后端 | 前端 | CORS |
| --- | --- | --- | --- |
| dev | `uvicorn app:app --reload --port 8787` | 本地静态 server（如 `python -m http.server 5173`）或直接打开 `canvas.html` | 允许 `http://localhost:5173`, `http://127.0.0.1:5173`, `file://` |
| mock | 同上 + `SD2VIDEO_MOCK=1` 启用 mock transport | 同上 | 同上 |
| prod | 反向代理后端到 `https://<host>/api/v1/...`，与前端同源 | 同源静态托管 | same-origin，无需 CORS |

前端通过 `window.__SD2VIDEO_API_BASE__`（启动注入）或 `<meta name="sd2video-api-base" content="...">` 拿到 base URL，**不允许从 query string / URL 拼接 API Key**。

### 1.4 配置（仅后端读取）

| 环境变量 | 必填 | 默认 | 说明 |
| --- | :---: | --- | --- |
| `ARK_API_KEY` | ✅ | — | 火山方舟密钥，**只在后端进程内存在**。 |
| `ARK_BASE_URL` | ❌ | `https://ark.cn-beijing.volces.com` | Ark API 根地址。 |
| `ARK_DEFAULT_MODEL_ID` | ❌ | `doubao-seedance-2-0-fast-260128` | 默认模型。 |
| `ARK_TIMEOUT_SECONDS` | ❌ | `30.0` | 上游单次 HTTP 超时。 |
| `SD2VIDEO_MOCK` | ❌ | `0` | `1` 启用 mock，**不会**调用真实 Ark。 |
| `SD2VIDEO_CORS_ORIGINS` | ❌ | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔白名单。 |
| `SD2VIDEO_BIND` | ❌ | `127.0.0.1:8787` | 监听地址。默认绑回环，避免无意暴露。 |

**契约硬约束**：

- 后端**禁止**通过任何响应字段（包括 `capabilities`、`debug`、错误信息）回显 `ARK_API_KEY`。
- 前端**禁止**接收、保存、转发任何形式的 API Key（含 base64、masked 后几位）。
- 前端 `localStorage` / `sessionStorage` / `IndexedDB` 不得包含与密钥相关的字段。
- 后端日志格式化错误时复用 SDK 的 `_sanitize`（见 `src/sd2video/ark/client.py`），把 API Key 替换为 `<redacted>`。

---

## 2. 通用约定

### 2.1 请求

- 方法与路径见各端点。所有请求 / 响应均为 `application/json; charset=utf-8`。
- 客户端必须发送 `Accept: application/json`。
- 客户端**可选**发送 `X-Client-Request-Id: <uuid>`，后端原样回写到响应头和错误对象的 `request_id` 字段，便于排错。
- 所有时间字段统一为 **RFC 3339 / ISO 8601 UTC 字符串**（如 `"2026-05-12T03:38:39Z"`）。

### 2.2 成功响应

成功响应总是返回 **HTTP 2xx**，body 是端点定义的资源对象（不再包一层 `{data: ...}`，避免和 SDK 转译层重复）。

### 2.3 错误响应

任何 4xx / 5xx 都使用统一形状：

```json
{
  "error": {
    "code": "parameter_invalid",
    "message": "ratio '21:10' is not supported",
    "field": "ratio",
    "request_id": "21000000-...-...",
    "retryable": false
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | :---: | --- |
| `code` | ✅ | 见 §6 错误码表，前端**用 code 判断分支**，不要解析 `message`。 |
| `message` | ✅ | 面向开发者的英文 / 中文短句，可直接展示给用户。 |
| `field` | ❌ | 关联到出错的请求字段名（snake_case），驱动前端表单高亮。 |
| `request_id` | ❌ | 后端生成或来自客户端的请求 id，便于排错。 |
| `retryable` | ❌ | `true` 表示按下"重试"是有意义的（如 5xx、超时、Ark 限流）。 |

### 2.4 状态枚举（task status）

后端**只回这 6 个值**，覆盖 SDK 的 `STATUS_LABELS`：

| status | 终态？ | 说明 |
| --- | :---: | --- |
| `queued` | ❌ | 排队中，已落 Ark 任务列表。 |
| `running` | ❌ | 生成中。 |
| `succeeded` | ✅ | 成功，`video_url` 可用（24h 有效）。 |
| `failed` | ✅ | 生成失败，看 `error_message`。 |
| `cancelled` | ✅ | 用户主动取消 / Ark 远端为 cancelled。 |
| `deleted` | ✅ | 已删除（本地 / 远端 404）。 |

前端展示的中文 label 由前端做映射，不要依赖后端返回。

### 2.5 分页

列表统一使用 `page_num`（1-based）+ `page_size`（1-50，默认 10），与 SDK / Ark 上游一致。响应携带 `total` 和 `has_more`。

---

## 3. 端点

### 3.1 `GET /api/v1/health`

存活探针。

**Response 200**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "mock": false,
  "uptime_seconds": 1234
}
```

- `mock`: 当前进程是否处于 mock 模式。
- 不返回任何上游 Ark 信息（不需要、且会拖慢健康检查）。

---

### 3.2 `GET /api/v1/capabilities`

前端启动时调用一次，**用响应填充模型/分辨率/比例/时长的 UI 选项**。前端不要再硬编码这些值（HOM-22 当前 `MODELS` / `RESOLUTIONS` / `ASPECT_RATIOS` 应改读这里）。

**Response 200**

```json
{
  "models": [
    {
      "id": "doubao-seedance-2-0-260128",
      "label": "Seedance 2.0",
      "max_resolution": "1080p",
      "supports_audio": true,
      "supports_web_search": true,
      "supports_modes": ["t2v", "first_frame", "first_last", "reference", "edit", "extend"]
    },
    {
      "id": "doubao-seedance-2-0-fast-260128",
      "label": "Seedance 2.0 Fast",
      "max_resolution": "720p",
      "supports_audio": true,
      "supports_web_search": true,
      "supports_modes": ["t2v", "first_frame", "first_last", "reference", "edit", "extend"]
    }
  ],
  "ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
  "resolutions": ["480p", "720p", "1080p"],
  "duration": { "min": 4, "max": 15, "step": 1, "unit": "second" },
  "limits": {
    "max_reference_images": 9,
    "max_reference_videos": 3,
    "max_reference_audios": 3,
    "max_total_video_seconds": 15,
    "image_max_bytes": 31457280,
    "video_max_bytes": 52428800,
    "audio_max_bytes": 15728640,
    "request_body_max_bytes": 67108864
  },
  "default_model": "doubao-seedance-2-0-fast-260128",
  "poll_interval_seconds": 5,
  "poll_timeout_seconds": 600
}
```

- 后端从 `ArkConfig.default_model_id` 和 `sd2video.ark.task_models` 的常量（`VALID_RATIOS`、`VALID_RESOLUTIONS`、`_DURATION_RANGES`、`FRAMES_*`）派生这份能力声明。
- 任何新模型上线只改 SDK + capabilities，不动前端。

---

### 3.3 `POST /api/v1/tasks`

创建视频生成任务。

**Request body**

```json
{
  "mode": "t2v",
  "model": "doubao-seedance-2-0-fast-260128",
  "prompt": "一只猫在跳舞",
  "ratio": "16:9",
  "resolution": "720p",
  "duration": 5,
  "seed": null,
  "camera_fixed": false,
  "generate_audio": false,
  "return_last_frame": false,
  "watermark": true,
  "web_search": false,
  "assets": {
    "first_frame": null,
    "last_frame": null,
    "reference_images": [],
    "reference_videos": [],
    "reference_audios": [],
    "edit_video": null
  },
  "client_request_id": "panel-2026-05-12-001"
}
```

字段定义：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | :---: | --- |
| `mode` | enum | ✅ | `t2v` / `first_frame` / `first_last` / `reference` / `edit` / `extend` |
| `model` | string | ✅ | 来自 `capabilities.models[].id` |
| `prompt` | string | 见 §5 | UTF-8，前后端各自 `trim`。`t2v` 必填非空；其他模式可选 |
| `ratio` | enum | ❌ | 默认 `"16:9"` |
| `resolution` | enum | ❌ | 默认 `"720p"`。后端校验模型支持 |
| `duration` | int | ❌ | 秒，范围由 capabilities 决定 |
| `frames` | int | ❌ | `duration` / `frames` 二选一 |
| `seed` | int \| null | ❌ | -1 表示随机，等价于 null |
| `camera_fixed` | bool | ❌ | 默认 `false` |
| `generate_audio` | bool | ❌ | 默认 `false` |
| `return_last_frame` | bool | ❌ | 默认 `false` |
| `watermark` | bool | ❌ | 默认 `true` |
| `web_search` | bool | ❌ | 仅 `t2v` 允许 `true`（与 Ark 一致） |
| `service_tier` | enum | ❌ | `default` / `flex` |
| `assets` | object | 见 §5 | 各模式所需素材，统一传 URL 或 `asset://<id>` |
| `client_request_id` | string | ❌ | 幂等键，见 §3.3.3 |

> **关键约束**：前端 **不再发送 `content` 数组**。`content` 由后端从 `mode + prompt + assets` 拼装（直接复用 `CreateTaskRequest.text_to_video` / `image_to_video` / 手工构建 reference/edit/extend）。这样前端不需要懂 Ark 的 content schema。

**Response 201**

```json
{
  "task_id": "cgt-2024xxxxxxxxxxxxxxxxxxx",
  "status": "queued",
  "model": "doubao-seedance-2-0-fast-260128",
  "created_at": "2026-05-12T03:38:39Z",
  "submitted_payload_digest": "sha256:..."
}
```

- `submitted_payload_digest` 是后端对规范化请求体的 SHA-256，前端可用于幂等 UI（"刚才那条已提交"）。

**错误**

| HTTP | code | 触发 |
| --- | --- | --- |
| 400 | `parameter_invalid` | 字段格式 / 取值非法（含 SDK `ArkParameterError`） |
| 401 | `upstream_unauthorized` | 后端 `ARK_API_KEY` 无效（**不要让前端弹"请输入 API Key"，应提示运维**） |
| 409 | `duplicate_request` | 见 §3.3.3 幂等 |
| 413 | `payload_too_large` | 单个 asset 或总 body 超限 |
| 429 | `rate_limited` | Ark 限流，`retryable: true` |
| 502 | `upstream_failed` | Ark 5xx |
| 504 | `upstream_timeout` | Ark 超时 |

#### 3.3.1 素材（assets）

| 模式 | 必填 assets | 允许 assets |
| --- | --- | --- |
| `t2v` | — | `web_search` 可开 |
| `first_frame` | `first_frame` | — |
| `first_last` | `first_frame`, `last_frame` | — |
| `reference` | 至少 1 项 `reference_images` / `reference_videos`（不允许"纯音频+文本"） | `reference_images` (≤9), `reference_videos` (≤3), `reference_audios` (≤3) |
| `edit` | `edit_video` | `reference_images` (≤9), `reference_audios` (≤3) |
| `extend` | `reference_videos` ≥1 | `reference_videos` (≤3)，总时长 ≤ 15s |

asset URL 三种形式（与 SDK `MediaResolver` / `validate_image_url` 一致，video/audio 同理）：

1. `https://...` / `http://...`（公网或后端可达的内网 URL）
2. `data:image/<fmt>;base64,<payload>` —— 仅限图片，且不超过单图大小上限
3. `asset://<asset-id>` —— 由 `POST /api/v1/assets` 上传后获得

前端选择本地文件后，先用浏览器 `blob:` URL 做预览，同时上传到 `POST /api/v1/assets`。上传完成前，生成按钮必须保持不可用；任务 payload 只能使用上传接口返回的 `asset_url` / `asset://...`，不能使用 `blob:` URL 或本地路径。

#### 3.3.1.1 `POST /api/v1/assets`

上传本地图片、视频或音频，返回后端可解析的资产 URL。请求为 `multipart/form-data`。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | :---: | --- |
| `file` | file | ✅ | 原始本地文件。 |
| `kind` | enum | ✅ | `image` / `video` / `audio`。 |
| `role` | enum | ❌ | `first_frame` / `last_frame` / `reference_image` / `reference_video` / `reference_audio` / `edit_video` / `extend_video`。 |
| `client_asset_id` | string | ❌ | 前端临时 ID，响应原样返回。 |

**Response 201**

```json
{
  "asset_id": "01900000-abcd-ef01-2345-6789abcdef01",
  "asset_url": "asset://01900000-abcd-ef01-2345-6789abcdef01",
  "preview_url": "https://local-assets.example/assets/01900000-abcd.png",
  "kind": "image",
  "role": "first_frame",
  "size_bytes": 240183,
  "width": 1280,
  "height": 720,
  "duration_seconds": null,
  "expires_at": "2026-05-13T05:00:00Z",
  "client_asset_id": "panel-asset-1"
}
```

上传失败使用 §6 错误结构。典型 code：`unsupported_media_type`、`payload_too_large`、`parameter_invalid`、`internal_error`。

完整生命周期、清理策略和 Ark payload 示例见 `docs/asset_input_strategy.md`。

#### 3.3.2 字段映射：HOM-22 面板 → 后端 payload

> 以 `app-components.jsx` 的 `CreatePanel` 与 `panel.jsx` 的 `CreateVideoPanel` 为准。
> 凡是面板把同一个值用驼峰 + snake 双写（如 `cameraCtrl` / `camera_fixed`）的，前端**只发 snake，可以一次性把驼峰版从 generate payload 里删掉**。

| 面板 state | 后端字段 | 备注 |
| --- | --- | --- |
| `mode` | `mode` | 同名 |
| `model` | `model` | 同名 |
| `prompt` | `prompt` | trim 后传 |
| `negPrompt` / `neg` | — | **Ark 不接受 negative prompt**，前端可保留 UI 但**不能发**给后端；如需保留，加入到 prompt 末尾用自然语言表达 |
| `ar` | `ratio` | `panel.jsx:133` 已有 `ratio:ar` |
| `resolution` / `res` | `resolution` | — |
| `duration` / `dur` | `duration` | 数字，已 `parseInt` |
| `seed` | `seed` | 空串 → `null` |
| `watermark` | `watermark` | — |
| `cameraCtrl` / `fixedCam` | `camera_fixed` | 统一 snake |
| `generateAudio` | `generate_audio` | — |
| `returnLastFrame` | `return_last_frame` | — |
| `webSearch` | `web_search` | 不要再发 `tools: [{type:"web_search"}]`，后端按 `web_search:true` 自己塞 `tools` |
| `startImg` | `assets.first_frame` | `t2v` 模式忽略 |
| `endImg` | `assets.last_frame` | 仅 `first_last` |
| `refImages[].url` | `assets.reference_images[]` | string 数组，注意去掉 `kind` / `name` |
| `refVideos[].url` | `assets.reference_videos[]` | 同上 |
| `refAudios[].url` | `assets.reference_audios[]` | 同上 |
| `editVideo[].url` | `assets.edit_video`（取第一个） | `edit` 模式必填 |
| `content` | — | **不再发**。详见上文 |

**示例 1：`t2v`**

```json
{
  "mode": "t2v",
  "model": "doubao-seedance-2-0-260128",
  "prompt": "云朵在山顶缓缓移动，镜头缓慢推近",
  "ratio": "16:9",
  "resolution": "720p",
  "duration": 5,
  "generate_audio": false,
  "web_search": false
}
```

**示例 2：`first_last`**

```json
{
  "mode": "first_last",
  "model": "doubao-seedance-2-0-260128",
  "prompt": "平滑过渡",
  "ratio": "adaptive",
  "duration": 5,
  "assets": {
    "first_frame": "https://cdn.example.com/start.png",
    "last_frame": "asset://01900000-abcd-ef01-2345-6789abcdef01"
  }
}
```

**示例 3：`reference`**

```json
{
  "mode": "reference",
  "model": "doubao-seedance-2-0-260128",
  "prompt": "参考图片1的主体动作，全程使用音频1作为背景音乐",
  "ratio": "9:16",
  "duration": 6,
  "generate_audio": true,
  "assets": {
    "reference_images": ["asset://img-1", "asset://img-2"],
    "reference_videos": [],
    "reference_audios": ["asset://aud-1"]
  }
}
```

**示例 4：`edit`**

```json
{
  "mode": "edit",
  "model": "doubao-seedance-2-0-260128",
  "prompt": "将 视频1 中的桌面物品替换为咖啡杯",
  "duration": 5,
  "assets": {
    "edit_video": "asset://vid-orig",
    "reference_images": ["asset://cup-ref"]
  }
}
```

**示例 5：`extend`**

```json
{
  "mode": "extend",
  "model": "doubao-seedance-2-0-260128",
  "prompt": "生成 视频1 之后的内容，镜头继续向前",
  "duration": 5,
  "assets": {
    "reference_videos": ["asset://vid-base"]
  }
}
```

#### 3.3.3 幂等

为避免快速连点导致重复创建（HOM-29 关注点）：

- 前端**应**为每次提交生成一次性 `client_request_id`，并在按钮变 enable 之前不复用。
- 后端**应**对最近 5 分钟同 `client_request_id` 直接返回 **409 `duplicate_request`**，body 包含已存在的 `task_id`：

```json
{
  "error": {
    "code": "duplicate_request",
    "message": "A task with the same client_request_id already exists.",
    "request_id": "...",
    "retryable": false
  },
  "existing": { "task_id": "cgt-...", "status": "running" }
}
```

未带 `client_request_id` 时，后端不做幂等，仅依赖前端按钮锁。

---

### 3.4 `GET /api/v1/tasks/{id}`

查询单个任务。

**Response 200**

```json
{
  "task_id": "cgt-2024xxxxxxxxxxxxxxxxxxx",
  "status": "succeeded",
  "model": "doubao-seedance-2-0-fast-260128",
  "video_url": "https://ark-content.../video.mp4",
  "video_url_expires_at": "2026-05-13T03:38:39Z",
  "last_frame_url": null,
  "created_at": "2026-05-12T03:38:39Z",
  "updated_at": "2026-05-12T03:40:11Z",
  "usage": {
    "total_tokens": 0,
    "duration_seconds": 5,
    "resolution": "720p"
  },
  "error_message": null,
  "request_summary": {
    "mode": "t2v",
    "ratio": "16:9",
    "resolution": "720p",
    "duration": 5,
    "generate_audio": false
  }
}
```

字段说明：

- `video_url`：仅 `status == "succeeded"` 时非空。**24h 内有效**（Ark 限制），前端展示时需要提示用户尽快下载。
- `video_url_expires_at`：由后端基于 `updated_at + 24h` 估算；若 Ark 在 raw 中给出确定值，优先用确定值。
- `last_frame_url`：开启 `return_last_frame` 且模型返回了尾帧时填充。
- `error_message`：失败的人类可读原因（SDK `TaskState._extract_error_message` 已经做了提取）。
- `request_summary`：后端从原始 Ark `content` / params 反推出来的回显字段，便于前端在"历史详情"里展示原始参数，无需自己存储。

**错误**

| HTTP | code | 触发 |
| --- | --- | --- |
| 400 | `parameter_invalid` | `task_id` 包含空白 / 路径分隔符（SDK `_validate_task_id`） |
| 404 | `task_not_found` | Ark 返回 404 |
| 401 | `upstream_unauthorized` | 同 §3.3 |

---

### 3.5 `GET /api/v1/tasks`

任务列表 / 历史。

**Query**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `page_num` | int | 1 | 1-based |
| `page_size` | int | 10 | 1–50 |
| `status` | enum 或 csv | — | 例：`status=running` 或 `status=succeeded,failed` |
| `task_ids` | csv | — | 例：`task_ids=cgt-aaa,cgt-bbb` |

**Response 200**

```json
{
  "items": [
    {
      "task_id": "cgt-...",
      "status": "running",
      "model": "doubao-seedance-2-0-fast-260128",
      "video_url": null,
      "created_at": "2026-05-12T03:38:39Z",
      "updated_at": "2026-05-12T03:39:01Z",
      "request_summary": {
        "mode": "first_frame",
        "ratio": "9:16",
        "resolution": "720p",
        "duration": 5,
        "generate_audio": false
      }
    }
  ],
  "total": 23,
  "page_num": 1,
  "page_size": 10,
  "has_more": true
}
```

- 列表项是 §3.4 单任务响应的子集（不含 `usage` 详细字段；前端要详细就再 `GET /tasks/{id}`）。
- 后端禁止把 Ark raw response 透传出去，否则容易把上游字段名 / 内部结构暴露给前端。

**错误**

| HTTP | code |
| --- | --- |
| 400 | `parameter_invalid`（分页越界 / status 取值非法） |

---

### 3.6 `DELETE /api/v1/tasks/{id}`

取消（`queued` / `running`）或删除（终态）任务。

**Request body（可选）**

```json
{ "current_status": "running", "reason": "user_cancel" }
```

`current_status` 若提供，后端透传给 SDK 的 `delete_task(current_status=...)`，由 SDK 校验本地状态合法性。

**Response 200**

```json
{
  "task_id": "cgt-...",
  "status": "cancelled",
  "deleted": true,
  "message": null
}
```

- `status` 为 `"cancelled"` 或 `"deleted"`，对应 SDK `ArkTaskDeleteResult.status`。
- `deleted: true` 表示后端已经确认任务在 Ark 侧不再活跃。

**错误**

| HTTP | code | 备注 |
| --- | --- | --- |
| 404 | `task_not_found` | 任务不存在 / 已删（前端可静默刷新历史） |
| 409 | `task_state_conflict` | 当前远端状态不允许该动作 |
| 401 | `upstream_unauthorized` | 同上 |

前端**必须**在调用前显示二次确认（HOM-29 验收点）。

---

## 4. 轮询策略（HOM-27）

为了让前后端对轮询节奏达成一致：

| 维度 | 推荐值 | 来源 |
| --- | --- | --- |
| 初始间隔 | 3s | 前端首次拿到 `task_id` 后等 3s 再轮询 |
| 稳态间隔 | 5s | `capabilities.poll_interval_seconds` |
| 最大等待 | 600s | `capabilities.poll_timeout_seconds`，到点提示"任务未完成，可稍后回到历史查看" |
| 终止条件 | `status ∈ {succeeded, failed, cancelled, deleted}` | 同 SDK `TaskState.is_terminal` |
| 面板关闭 | 取消轮询 | 任务仍在 Ark 队列里，下次打开历史可恢复 |
| 页面切换 | 暂停 → 恢复（`document.visibilitychange`） | 避免后台浏览器节流让 setInterval 漂移 |

实现要点：

- **不要用 `setInterval(..., 0)`**，用 `setTimeout` 链 + 当前 status 自适应。
- **不要并发轮询同一个 task**：组件卸载时清理 timer。
- 失败 / 取消 / 超时分支由前端 UI 提供"重试"按钮，重试时**重新生成 `client_request_id`**。

---

## 5. 校验（前端先做，后端再做一遍）

前端做这些是为了交互体验（错误可定位字段、避免无意义请求），后端做这些是为了安全（前端可绕过）。**两端校验语义必须一致**，参考 SDK `CreateTaskRequest.validate` 与 `validate_image_url`。

### 5.1 必填

| 模式 | 必填字段 |
| --- | --- |
| `t2v` | `prompt`（非空） |
| `first_frame` | `assets.first_frame` |
| `first_last` | `assets.first_frame`, `assets.last_frame` |
| `reference` | `reference_images` 或 `reference_videos` 至少 1 项 |
| `edit` | `assets.edit_video` |
| `extend` | `assets.reference_videos` ≥ 1 |

### 5.2 取值范围

- `model ∈ capabilities.models[*].id`
- `ratio ∈ capabilities.ratios`
- `resolution ∈ capabilities.resolutions`，并且要 ≤ `model.max_resolution`（前端 Fast 选 1080p 应禁用，HOM-22 已实现）
- `duration ∈ [capabilities.duration.min, max]`
- 素材数量 ≤ `capabilities.limits.max_reference_*`
- 单文件大小 ≤ 对应 `limits.*_max_bytes`
- 总 body ≤ `limits.request_body_max_bytes`

### 5.3 互斥

- `web_search: true` 只在 `mode == "t2v"` 允许。
- `duration` 与 `frames` 互斥，前端默认走 `duration`，`frames` 不开放。
- `generate_audio: true` 在 `reference` 模式下要求至少一个图片或视频（Ark 限制）。

---

## 6. 错误码表

| code | HTTP | 含义 / 触发 | 前端典型动作 |
| --- | :---: | --- | --- |
| `parameter_invalid` | 400 | 字段缺失 / 取值非法 / 格式错误。`field` 指明字段 | 在表单项下显红字 |
| `mode_constraint_violation` | 400 | 模式所需素材缺失 / 多余 | 切换模式提示 |
| `payload_too_large` | 413 | asset 或 body 超限 | 提示压缩 / 改用 URL |
| `unsupported_media_type` | 415 | 图片 / 视频 / 音频格式不在白名单 | 提示支持的格式 |
| `duplicate_request` | 409 | 同 `client_request_id` 已提交，body 含 `existing.task_id` | 跳到已有任务，不再创建 |
| `task_not_found` | 404 | 任务不存在 / 已删 | 静默刷新历史 |
| `task_state_conflict` | 409 | 当前状态不允许该动作（如终态再 cancel） | 刷新单任务状态后再决定 |
| `upstream_unauthorized` | 401 | 后端 `ARK_API_KEY` 无效 / 无权限 | **告诉用户找运维**，不要让用户输 Key |
| `upstream_failed` | 502 | Ark 5xx | 显示"上游异常"，`retryable: true` |
| `upstream_timeout` | 504 | Ark 超时 | 同上 |
| `rate_limited` | 429 | Ark 限流 | 退避重试 |
| `internal_error` | 500 | 后端未捕获异常 | 联系运维，附 `request_id` |

后端 SDK 异常 → HTTP 映射：

| SDK 异常 | HTTP | code |
| --- | --- | --- |
| `ArkParameterError`（无 status_code） | 400 | `parameter_invalid` |
| `ArkParameterError`（status_code=400/422） | 400 | `parameter_invalid` |
| `ArkAuthenticationError` | 401 | `upstream_unauthorized` |
| `ArkTaskDeleteError`（404） | 404 | `task_not_found` |
| `ArkTaskDeleteError`（409） | 409 | `task_state_conflict` |
| `ArkAPIError`（429） | 429 | `rate_limited` |
| `ArkAPIError`（5xx） | 502 | `upstream_failed` |
| `ArkTimeoutError` | 504 | `upstream_timeout` |
| `ArkNetworkError` | 502 | `upstream_failed` |

后端在拿到 `ArkAPIError` 时**必须**做 `_sanitize` 后才能写入响应或日志（SDK 已经在 `ArkClient._sanitize` 里做了 API Key 抹除，复用即可）。

---

## 7. 安全契约（硬约束）

1. `ARK_API_KEY` 不进入：
   - 前端 bundle（不写到 `window`、不写到 `index.html` `<meta>`）
   - `localStorage` / `sessionStorage` / cookie
   - 任何 API 响应（含 `health`、`capabilities`、错误）
   - 浏览器开发者面板的 network 请求头 / 响应头
2. 后端日志在格式化错误时调用 `_sanitize`（已在 SDK 实现），任何来源的字符串里若包含 `ARK_API_KEY` 必须替换为 `<redacted>`。
3. 上传 / 引用素材时，后端要校验 URL scheme：仅允许 `https://`、`http://`（限内网 / 白名单域）、`data:image/...`、`asset://...`；禁止把 `blob:`、`file:` 或本地路径传给 Ark。
4. CORS：白名单由 `SD2VIDEO_CORS_ORIGINS` 控制，默认绑回环 + 本地开发地址。
5. `DELETE` 必须前端二次确认 + 后端不需要鉴权头以外的额外凭证（密钥已在后端持有）。
6. `data:image/*;base64,...` 仅限单图 ≤ `image_max_bytes`，且不进入日志。

---

## 8. Mock 模式

启用方式：`SD2VIDEO_MOCK=1` 或在测试中注入 mock transport（参考 `tests/test_create_task.py`、`tests/test_workflow.py`）。

Mock 模式下：

- `POST /tasks` 立即返回伪 `task_id`（如 `cgt-mock-<uuid>`）和 `status: "queued"`。
- 首次 `GET /tasks/{id}` 返回 `running`，再次返回 `succeeded`，并附带固定的可访问 video_url（项目内 `tests/fixtures/sample.mp4` 或 1px GIF data URL）。
- `DELETE` 直接返回 `cancelled` / `deleted`。
- **不调用真实 Ark**，不读取真实 API Key（缺 `ARK_API_KEY` 也能跑）。

这是 HOM-26 / HOM-27 / HOM-28 / HOM-29 / HOM-31 的默认开发态，CI 默认开启。

---

## 9. 不在本契约范围内的事

下面这些**故意不在 v1 契约里**，避免过度设计，留到具体子任务里再补：

- 用户/账号鉴权：当前是单用户本机服务，没有登录态。
- 多 workspace / 项目隔离：同上。
- WebSocket / SSE 状态推送。
- 任务批量取消、批量重试。
- 跨设备同步历史：依赖 Ark 自身的任务列表即可。

需要这些能力时，按补充协议加端点（`/api/v2/...` 或独立路径），但**不改本文件已定义的字段语义**。

---

## 10. 版本与变更

- 当前版本：`v1`，路径前缀 `/api/v1`。
- 任何**破坏性变更**（删字段、改字段类型、改 status 枚举）都要发 `v2`。
- 增字段（不影响旧客户端）可以直接在 v1 加，并在本文档 changelog 写明。

### Changelog

| 日期 | 变更 | 关联 |
| --- | --- | --- |
| 2026-05-12 | 补充 `POST /api/v1/assets`、本地文件上传状态、`blob:` 禁止传入任务和素材生命周期文档链接 | HOM-25 |
| 2026-05-12 | 初版契约，覆盖 health / capabilities / tasks CRUD / 删除；映射 HOM-22 面板字段；锁定密钥隔离与错误码表 | HOM-23 |
