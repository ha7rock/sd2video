# 参考素材上传与 URL 处理策略（HOM-25）

本文补充 `docs/api_contract.md` 的素材输入部分。核心原则：

- 前端只向任务接口提交 `mode + prompt + assets + params + client_request_id`。
- 前端不得提交 Ark 原始 `content` 数组，也不得把浏览器 `blob:` 预览 URL 或本地文件路径传给 Ark。
- 后端必须先解析并校验所有素材；任一素材失败时，直接返回 4xx，不创建 Ark 任务。
- Ark 任务 payload 只使用后端确认可访问的 `http(s)://`、`data:image/...;base64,...` 或 `asset://<id>`。

## 1. 支持的素材来源

| 来源 | 前端提交值 | 后端处理 |
| --- | --- | --- |
| 远程 URL | `https://cdn.example.com/a.png` | 校验 scheme、角色、数量、大小/尺寸元数据后直接用于 Ark content。 |
| 已上传资产 | `asset://019...` | 视为后端已托管或 Ark 可识别资产，校验 ID 非空后使用。 |
| 本地文件上传 | 先 `POST /api/v1/assets`，任务只提交返回的 `asset://...` 或 URL | 后端校验文件类型/大小/尺寸/时长，上传到对象存储或临时静态服务后返回可访问 URL/ID。 |
| 已生成任务复用 | `{ "task_id": "cgt-...", "result_url": "https://..." }` 或保存成 `asset://...` | 后端校验 result URL 或资产 ID；复用任务 ID 只作为审计/展示元数据。 |
| 图片 data URI | `data:image/png;base64,...` | 仅图片允许；后端校验 base64 与大小上限。 |

禁止值：

- `blob:http://...`：仅浏览器预览可用，必须先上传。
- `file:///...` 或 `/Users/...`：仅允许后端内部接收 multipart 文件后通过 uploader 转换；不能从前端任务 JSON 直传。
- `ftp://...`、裸相对路径、空字符串。

## 2. 上传接口

`POST /api/v1/assets`

请求使用 `multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | :---: | --- |
| `file` | file | yes | 图片、视频或音频文件。 |
| `kind` | enum | yes | `image` / `video` / `audio`。 |
| `role` | enum | no | `first_frame` / `last_frame` / `reference_image` / `reference_video` / `reference_audio` / `edit_video` / `extend_video`。 |
| `client_asset_id` | string | no | 前端临时 ID，响应原样返回，方便合并进 UI 状态。 |

成功响应：

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

错误响应沿用 `docs/api_contract.md` 的错误结构：

- `unsupported_media_type`：扩展名、MIME 或文件头不在白名单。
- `payload_too_large`：单文件超过 capabilities limit。
- `parameter_invalid`：`kind` / `role` / 图片尺寸 / 视频时长非法。
- `internal_error` 或 `upstream_failed`：对象存储/临时静态服务不可用。

## 3. 校验规则

后端默认限制与 `sd2video.ark.assets.AssetValidationConfig` 保持一致：

| 类型 | 格式 | 单文件上限 |
| --- | --- | --- |
| 图片 | jpg/jpeg/png/webp/bmp/gif/tiff/heic/heif | 30 MiB |
| 视频 | mp4/mov/mpeg/mpg/webm/m4v | 50 MiB |
| 音频 | mp3/wav/m4a/aac/ogg/flac | 15 MiB |

数量与模式约束：

| 模式 | 必填素材 | Ark role 映射 |
| --- | --- | --- |
| `t2v` | 无 | 只生成 `text` content。 |
| `first_frame` | `assets.first_frame` | `image_url` + `role: first_frame`。 |
| `first_last` | `assets.first_frame`, `assets.last_frame` | 两个 `image_url`，分别为 `first_frame` / `last_frame`。 |
| `reference` | 至少 1 个图片或视频 | 图片 `reference_image`，视频 `reference_video`，音频 `reference_audio`。 |
| `edit` | `assets.edit_video` | 待编辑视频按 `reference_video` 传入，参考图/音频按对应 role 传入。 |
| `extend` | 至少 1 个 `reference_videos` | 视频按 `reference_video` 传入，总时长不超过 15s。 |

图片尺寸默认必须在 `64x64` 到 `8192x8192` 范围内。视频时长如果上传层能解析，必须写入 `duration_seconds` 并参与总时长校验；解析不到时仍可上传，但 extend 模式建议前端显示“时长未知，后端可能拒绝”。

## 4. Ark payload 示例

文生视频：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "云层掠过山脊，镜头缓慢推近" }
  ],
  "ratio": "16:9",
  "resolution": "720p",
  "duration": 5
}
```

首帧生成：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "让画面中的人向镜头挥手" },
    {
      "type": "image_url",
      "image_url": { "url": "asset://first-frame-1" },
      "role": "first_frame"
    }
  ]
}
```

首尾帧生成：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "从清晨平滑过渡到夜晚" },
    {
      "type": "image_url",
      "image_url": { "url": "https://cdn.example.com/start.png" },
      "role": "first_frame"
    },
    {
      "type": "image_url",
      "image_url": { "url": "asset://last-frame-1" },
      "role": "last_frame"
    }
  ]
}
```

参考生成：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "参考图片1的角色，使用音频1作为背景音乐" },
    {
      "type": "image_url",
      "image_url": { "url": "asset://ref-image-1" },
      "role": "reference_image"
    },
    {
      "type": "audio_url",
      "audio_url": { "url": "asset://ref-audio-1" },
      "role": "reference_audio"
    }
  ],
  "generate_audio": true
}
```

编辑视频：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "把视频1里的杯子替换为红色马克杯" },
    {
      "type": "video_url",
      "video_url": { "url": "asset://edit-video-1" },
      "role": "reference_video"
    },
    {
      "type": "image_url",
      "image_url": { "url": "asset://cup-ref" },
      "role": "reference_image"
    }
  ]
}
```

延长视频：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "生成视频1之后的内容，镜头继续向前" },
    {
      "type": "video_url",
      "video_url": { "url": "asset://base-video-1" },
      "role": "reference_video"
    }
  ],
  "duration": 5
}
```

## 5. 生命周期与清理

- 上传资产默认是临时资产，TTL 为 24 小时；如果对象存储支持 lifecycle rule，应按 `expires_at` 自动清理。
- 本地临时文件应在上传成功后立即删除；上传失败保留不超过 1 小时用于重试，然后后台清理。
- 任务创建成功后，后端只保存 asset ID、可访问 URL、元数据和 payload digest，不保存原始文件字节。
- 如果同一 `client_asset_id` 重试上传，后端可覆盖旧临时资产，但必须返回新的 `asset_id` / `asset_url`。
- 日志只记录 asset ID、kind、size、尺寸/时长和 request_id；不得记录 data URI 全量内容。

## 6. 代码入口

后端 SDK 已提供：

- `sd2video.ark.MediaResolver`：解析 URL、`asset://`、data image、任务结果复用和本地文件。
- `sd2video.ark.AssetValidationConfig`：集中保存大小、数量、尺寸和时长限制。
- `sd2video.ark.build_task_request_from_payload(payload, resolver=...)`：按 HOM-23 payload 构建 Ark `CreateTaskRequest`。
- `VideoGenerationWorkflow.submit_payload(payload, resolver=...)`：先完成素材校验，再调用 Ark create task。

本地文件必须配置 `AssetUploader`。没有 uploader 时，`MediaResolver` 会拒绝本地路径，确保不会把浏览器路径或服务器路径误传给 Ark。
