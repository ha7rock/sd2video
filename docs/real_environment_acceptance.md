# 真实环境联调与端到端验收 Runbook (HOM-30)

本文档描述如何在 mock 测试通过之后，用真实火山方舟账号跑一次端到端验收，确认前端、后端、Ark API 三者真的打通。**默认 CI 与 `unittest discover` 不会触发真实生成，所有真实调用都必须显式打开开关。**

> ⚠️ 实跑会产生真实费用。请始终用最低成本参数（480p、16:9、4s），跑完后到火山方舟控制台确认任务状态和费用，并按需要取消/删除测试任务。

---

## 0. 前置依赖

| Issue | 内容 | 必需性 |
| --- | --- | --- |
| HOM-12 ～ HOM-18 | Python SDK（client/workflow/mock 测试/smoke 测试钩子） | ✅ 已完成 |
| HOM-22 | Seedance 2.0 前端面板 | ✅ 已完成 |
| HOM-23 | 前后端 API 契约 | ⏳ 完成后才能定 payload |
| HOM-24 | HTTP 后端服务（包 SDK） | ⏳ **必需**，否则没有可被前端调用的入口 |
| HOM-25 | 参考素材上传/URL 策略 | ⏳ 决定 image/video 素材怎么进 Ark |
| HOM-26 | 前端面板 → 后端 create task | ⏳ **必需** |
| HOM-27 | 状态轮询 / 结果预览 / 错误展示 | ⏳ **必需** |
| HOM-28 | 历史任务列表 | ⏳ 验收里有列表查询步骤 |
| HOM-29 | 取消/删除 + 成本保护 | ⏳ 验收要清理任务 |
| HOM-31 | mock 集成测试与 CI 门禁 | ⏳ 真实验收前 mock 必须全绿 |

只要 HOM-24、HOM-26、HOM-27 任一未完成，**前端 → 后端 → Ark 的端到端闭环不存在**，跳到下面的 "Stage A：SDK-only" 也只能验证 SDK 与 Ark 的两段联通，不算完整验收。

---

## 1. 配置准备

1. `cp .env.example .env`
2. 填入 `ARK_API_KEY=...`。Key 来自控制台 → API Key 页签，要确认账号已开通 Seedance 2.0 模型且额度够本次测试。
3. 如有需要再填：
   - `ARK_BASE_URL`（一般保留默认）
   - `ARK_DEFAULT_MODEL_ID`（默认 `doubao-seedance-2-0-fast-260128`）
   - `ARK_TIMEOUT_SECONDS`
4. **不要** 把 `.env` 或其中任何值贴到 issue、PR、日志或前端打包目录。`.env` 已在 `.gitignore` 里。
5. 后端进程的启动入口（HOM-24 落地后）应该是 `python -m sd2video.server`（或 README 指定的命令），并从环境变量读取上述配置。前端只通过后端 HTTP 调用 Ark，不能直接读取 `ARK_API_KEY`。

---

## 2. 验收前确认 mock 全绿

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src tests
```

- SDK 默认 97 个 mock 测试要全部 OK（live smoke 默认 skip）。
- HOM-31 落地后还应该跑前端单元测试、后端服务测试和 mock-backend 端到端测试。

只要 mock 没全绿，**不要** 进入下面的真实步骤。

---

## 3. Stage A：SDK + Ark 鉴权 / 网络 smoke（非生成、零费用）

目的：确认 `ARK_API_KEY`、Base URL、网络出口可用。

```bash
set -a; source .env; set +a
export ARK_RUN_SMOKE_TESTS=1
PYTHONPATH=src python3 -m unittest tests.test_smoke_ark_video_api.ArkVideoApiSmokeTest.test_list_tasks_live
```

预期：
- 测试 OK，`list_tasks` 返回 `total >= 0`，没有抛 `ArkAuthenticationError` / `ArkNetworkError`。
- 终端不会打印明文 `ARK_API_KEY`（异常路径会自动 `<redacted>`）。

记录证据：
- 命令
- 运行日期 / 总耗时
- 控制台 → 任务列表页是否能看到本次拉到的任务 ID（如果账号有历史任务）

> 如果这一步失败，先不要进入 Stage B/C，先排查鉴权或网络问题。

---

## 4. Stage B：SDK + Ark 真实生成（低成本、产生费用）

目的：在没有前端/后端的情况下，验证 SDK 与 Ark 的 create → poll → result 闭环。

```bash
set -a; source .env; set +a
export ARK_RUN_SMOKE_TESTS=1
export ARK_SMOKE_CREATE_TASK=1
export ARK_SMOKE_MODEL_ID=doubao-seedance-2-0-fast-260128
export ARK_SMOKE_RATIO=16:9
export ARK_SMOKE_RESOLUTION=480p
export ARK_SMOKE_DURATION=4
export ARK_SMOKE_PROMPT="A single red ball rolling slowly across a plain white floor."
PYTHONPATH=src python3 -m unittest tests.test_smoke_ark_video_api.ArkVideoApiSmokeTest.test_create_task_live_explicit_cost_opt_in
```

预期：
- 返回任务 ID 形如 `cgt-...`，`get_task` 返回的 status 落在 `{queued, running, succeeded, failed, cancelled}` 之一。
- 测试本身只断言"状态合法"，不会等到 succeeded。要拿到 `video_url` 需要再手动跑一次 `workflow.run(...)` 或 `workflow.wait(task_id)`，例如：

  ```bash
  PYTHONPATH=src python3 - <<'PY'
  import os
  from sd2video import VideoGenerationWorkflow, WorkflowConfig
  wf = VideoGenerationWorkflow.from_env(
      config=WorkflowConfig(poll_interval_seconds=5, poll_timeout_seconds=600),
  )
  state = wf.run(
      os.environ.get("ARK_SMOKE_PROMPT", "A single red ball rolling slowly across a plain white floor."),
      model=os.environ["ARK_SMOKE_MODEL_ID"],
      ratio=os.environ.get("ARK_SMOKE_RATIO", "16:9"),
      resolution=os.environ.get("ARK_SMOKE_RESOLUTION", "480p"),
      duration=int(os.environ.get("ARK_SMOKE_DURATION", "4")),
  )
  print("status:", state.status, "video_url:", state.video_url, "error:", state.error_message)
  PY
  ```

记录证据：
- 任务 ID
- 状态流转：`queued → running → succeeded`（或失败原因）
- `video_url` 是否能在浏览器或 `ffprobe` 里播放
- 控制台对应任务的截图 / 状态摘要
- 用量（duration、resolution）和实际计费

> 如果 succeed 拿不到 `video_url`，记录 Ark 侧错误信息和返回体（已隐藏 key 的版本），并把"修复项"作为新的 issue 挂在 HOM-22 下。

---

## 5. Stage C：前端 → 后端 → Ark 端到端（HOM-24/26/27 落地后才可执行）

> ❗ 在 HOM-24 / HOM-26 / HOM-27 没有 in_review 之前，跳过这一节。强行执行只会暴露还未实现的接口。

约定（与 HOM-23 契约一致；正式契约以 HOM-23 文档为准）：
1. 后端启动：
   ```bash
   set -a; source .env; set +a
   python -m sd2video.server --host 127.0.0.1 --port 8787
   ```
2. 前端启动指向 `http://127.0.0.1:8787`（在前端 zip 的 dev 配置里切换 mock → real）。
3. 浏览器打开前端，按以下流程演练：

   1. **健康检查**：进入页面，确认顶栏/调试面板显示后端 `health` 与 `capabilities`（模型列表、比例、分辨率、时长）正常拉取。
   2. **文生视频低成本生成**：
      - 模型：`doubao-seedance-2-0-fast-260128`
      - 比例：16:9 / 分辨率：480p / 时长：4s
      - prompt：与 Stage B 同款（便于横向对比）
      - 提交后记录任务 ID。
   3. **状态轮询**：前端面板应展示 `queued → running → succeeded` 的状态流转，不卡在 loading。
   4. **结果预览**：成功后面板显示 `video_url` 预览，且支持复制链接 / 打开新窗 / 下载。
   5. **历史列表**：进入历史任务列表，能筛选刚才的 succeeded 任务，点击恢复详情。
   6. **取消/删除**：在历史里对当前测试任务执行取消或删除，按 HOM-29 的确认弹窗逐项确认；列表状态同步刷新。

记录证据（截图或 GIF + 文字描述）：
- 命令与端口
- 任务 ID 与状态流转截图
- 浏览器 DevTools → Network：
  - 任意一次后端请求 header 不能包含 `Authorization: Bearer ...ARK_API_KEY...`
  - 响应体不能包含 `ARK_API_KEY` 明文
  - JS bundle / `localStorage` / `sessionStorage` 也不能存 key（搜索 `sk-` 前缀或自填 key 的前 6 位）
- 后端日志：grep 一遍当次运行日志，确认 key 已被 `<redacted>` 替换

---

## 6. 验收后的清理

- Stage B / Stage C 创建的任务，按需要在前端取消/删除入口，或后端：
  ```bash
  PYTHONPATH=src python3 - <<'PY'
  from sd2video import ArkClient
  c = ArkClient.from_env()
  c.delete_task("cgt-...")  # 替换为本次任务 ID
  PY
  ```
- 关闭已经不需要的环境变量：
  ```bash
  unset ARK_RUN_SMOKE_TESTS ARK_SMOKE_CREATE_TASK ARK_SMOKE_MODEL_ID \
        ARK_SMOKE_PROMPT ARK_SMOKE_RATIO ARK_SMOKE_RESOLUTION ARK_SMOKE_DURATION
  ```
- `.env` 留在本地，不进版本控制；如需轮换 Key，在控制台撤销旧 Key 后再覆盖文件。
- 确认仓库 `git status` 没有 `.env`、密钥日志或截图泄露。

---

## 7. 验收结论模板

把以下信息以评论形式贴回 HOM-30：

```
- 命令 / 环境变量名（值脱敏）：
- Stage A list_tasks 是否通过：
- Stage B create_task 任务 ID / 状态流转 / video_url：
- Stage C 端到端：是否走通 + 关键截图链接：
- 密钥审计：DevTools 与日志检查结果
- 已清理的任务 ID：
- 后续修复项（如有）→ 已开 issue 链接：
```

只要至少有一次 Stage B（或 Stage C）的 `create → poll → succeeded` 闭环成功（或者明确记录失败原因与下一步），且 mock/CI 默认仍不触发真实生成，本验收即可视为通过。
