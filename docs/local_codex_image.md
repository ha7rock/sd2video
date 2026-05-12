# 本地 Codex OAuth 生图临时方案

这是本地开发入口，不是生产 API。浏览器只访问本机 bridge，不持有 Codex OAuth token。

## 开启

```bash
PYTHONPATH=src python3 -m sd2video.local_image_server auth-login
SD2VIDEO_ENABLE_CODEX_IMAGE=1 PYTHONPATH=src python3 -m sd2video.local_image_server serve --host 127.0.0.1 --port 8765
```

然后打开 `frontend_current/frontend/canvas.html`。工具栏始终显示“本地生图”入口；
只有在 `/api/v1/local-images/status` 返回 enabled 后才允许生成。直接用文件方式打开
HTML 时会回退到 `http://127.0.0.1:8765`。

如果基于 HOM-41 的调试环境运行，优先走同源 `/api/v1/...` 代理：

```bash
python3 scripts/dev_frontend.py --mode mock
# 或真实/LAN 调试：
ARK_API_KEY=... python3 scripts/dev_frontend.py --mode real
```

此时页面访问的是 HOM-41 输出的 URL，本地生图请求也走同源代理，不会让局域网设备访问它自己的
`127.0.0.1`。如果要覆盖 endpoint，可在页面加载前设置
`window.SD2VIDEO_LOCAL_IMAGE_ENDPOINT`。

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
