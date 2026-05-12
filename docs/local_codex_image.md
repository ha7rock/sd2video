# 本地 Codex OAuth 生图临时方案

这是本地开发入口，不是生产 API。浏览器只访问本机 bridge，不持有 Codex OAuth token。

## 开启

```bash
PYTHONPATH=src python3 -m sd2video.local_image_server auth-login
SD2VIDEO_ENABLE_CODEX_IMAGE=1 PYTHONPATH=src python3 -m sd2video.local_image_server serve --host 127.0.0.1 --port 8765
```

然后打开 `frontend_current/frontend/canvas.html`。工具栏会在
`GET http://127.0.0.1:8765/api/v1/local-images/status` 返回 enabled 后显示“本地生图”。

## 本地文件

- Token store: `~/.sd2video/codex_oauth.json`
- 图片缓存: `~/.sd2video/local-images/`
- 可用环境变量:
  - `SD2VIDEO_CODEX_AUTH_PATH`
  - `SD2VIDEO_LOCAL_IMAGE_CACHE`
  - `SD2VIDEO_CODEX_BASE_URL`
  - `SD2VIDEO_CODEX_CHAT_MODEL`
  - `SD2VIDEO_LOCAL_IMAGE_ENDPOINT` or `window.SD2VIDEO_LOCAL_IMAGE_ENDPOINT` for the frontend endpoint override

## 清理

```bash
PYTHONPATH=src python3 -m sd2video.local_image_server auth-clear
rm -rf ~/.sd2video/local-images
```

## 风险

Codex/ChatGPT OAuth 和 `chatgpt.com/backend-api/codex` 不是稳定公开 API。模型名、header 要求、Responses `image_generation` tool schema 都可能漂移。该入口默认关闭，CI 和默认 mock 测试不会触发真实登录或真实生图。
