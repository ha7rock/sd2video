// ── Frame sizing: depends on aspect ratio AND resolution ───────────────
const FRAME_AR = { "16:9": [16, 9], "9:16": [9, 16], "1:1": [1, 1], "4:3": [4, 3], "3:4": [3, 4], "21:9": [21, 9], adaptive: [16, 9] };
const RES_SCALE = { "480p": 0.62, "720p": 0.82, "1080p": 1.0 };
const MAX_DIM = 240;
function frameSize(ar, res) {
  const [a, b] = FRAME_AR[ar] || [16, 9];
  const f = RES_SCALE[res] || 0.82;
  let w, h;
  if (a >= b) {w = MAX_DIM;h = MAX_DIM * b / a;} else
  {h = MAX_DIM;w = MAX_DIM * a / b;}
  return [Math.round(w * f), Math.round(h * f)];
}
window.frameSize = frameSize;
function aspectValue(ar) {
  const [a, b] = FRAME_AR[ar] || [16, 9];
  return `${a}/${b}`;
}

// ── VNode ────────────────────────────────────────────────────────────
function VNode({ node, sel, zoom, onClickNode, onMove, onAction }) {
  const [w, h] = frameSize(node.ar, node.resolution);
  const movedRef = React.useRef(false);

  function onMouseDown(e) {
    if (e.button !== 0) return;
    e.stopPropagation();
    movedRef.current = false;
    const sx = e.clientX,sy = e.clientY,ox = node.x,oy = node.y;
    function mv(ev) {
      const dx = ev.clientX - sx,dy = ev.clientY - sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) movedRef.current = true;
      if (movedRef.current) onMove(node.id, { x: ox + dx / zoom, y: oy + dy / zoom });
    }
    function up() {
      window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
      if (!movedRef.current) onClickNode(node.id, sel);
    }
    window.addEventListener("mousemove", mv);
    window.addEventListener("mouseup", up);
  }

  const videoUrl = node.video_url || node.videoUrl;
  const sc = { idle: "#ccc", generating: "#f59e0b", done: "#22c55e", error: "#ef4444", cancelled: "#8b8b8b" }[node.status] || "#ccc";
  const tbBtn = (icon, label, act, disabled) =>
  <button className="ntb-btn" title={label} disabled={disabled}
  onClick={(e) => {e.stopPropagation();if (!disabled) onAction(act);}}
  style={disabled ? { opacity: .35, cursor: "not-allowed" } : {}}>
      {icon}
    </button>;


  return (
    <div className={"vnode" + (sel ? " sel" : "")} style={{ left: node.x, top: node.y, width: w }}
    onMouseDown={onMouseDown}
    onDoubleClick={(e) => {e.stopPropagation();onClickNode(node.id, true);}}>
      {sel &&
      <div className="ntb" onMouseDown={(e) => e.stopPropagation()}>
          {tbBtn(<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>, "预览", "preview", node.status !== "done" || !videoUrl)}
          {tbBtn(<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>, "下载", "download", node.status !== "done" || !videoUrl)}
          {tbBtn(<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg>, "信息", "info")}
          <div className="ntb-sep" />
          {node.status === "generating" &&
          tbBtn(<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M9 9l6 6M15 9l-6 6" /></svg>, "取消生成任务", "cancel")}
          {tbBtn(<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6M14 11v6" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>, "从画布删除", "delete")}
        </div>
      }
      <div className="vnode-card" style={{ width: w, height: h }}>
        {node.status === "generating" &&
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
            <div style={{ display: "flex", gap: 5 }}>
              {[0, 1, 2].map((i) =>
            <div key={i} style={{ width: 6, height: 6, borderRadius: 3, background: "rgba(0,0,0,0.3)", animation: `blink 1.2s ${i * 0.2}s ease-in-out infinite` }} />
            )}
            </div>
            {node.progress != null &&
          <div style={{ width: 80, height: 2, background: "#e0e0e0", borderRadius: 2 }}>
                <div style={{ width: node.progress + "%", height: "100%", background: "#555", borderRadius: 2, transition: "width .3s" }} />
              </div>
          }
            <span style={{ fontSize: 10, color: "rgba(0,0,0,0.4)", maxWidth: "90%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {node.taskId ? `任务 ${node.taskId}` : `生成中 ${node.progress || 0}%`}
            </span>
          </div>
        }
        {node.status === "done" &&
        <div style={{ position: "absolute", inset: 0, background: "#111", display: "flex", alignItems: "center", justifyContent: "center" }}>
            {videoUrl && <video src={videoUrl} muted playsInline preload="metadata" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />}
            <div style={{ width: Math.min(40, h * 0.3), height: Math.min(40, h * 0.3), borderRadius: "50%", background: "rgba(255,255,255,0.18)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width={Math.min(18, h * 0.14)} height={Math.min(18, h * 0.14)} viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z" /></svg>
            </div>
          </div>
        }
        {node.status === "error" && <span style={{ fontSize: 11, color: "#ef4444", padding: "0 12px", textAlign: "center" }}>{node.statusText || node.error_message || node.errorMessage || "生成失败"}</span>}
        {node.status === "cancelled" && <span style={{ fontSize: 11, color: "#666" }}>{node.statusText || "已取消"}</span>}
        <div style={{ position: "absolute", top: 7, right: 7, width: 6, height: 6, borderRadius: 3, background: sc }} />
        {sel && <>
          <div className="sel-dot" style={{ top: -4, left: -4 }} />
          <div className="sel-dot" style={{ top: -4, right: -4 }} />
          <div className="sel-dot" style={{ bottom: -4, left: -4 }} />
          <div className="sel-dot" style={{ bottom: -4, right: -4 }} />
        </>}
      </div>
      <div className="vnode-lbl" style={{ maxWidth: w }}>{node.modelLabel} · {node.ar} · {node.resolution} · {node.duration}s</div>
    </div>);

}

// ── Models / constants ───────────────────────────────────────────────
const MODELS = [
{ id: "doubao-seedance-2-0-260128", label: "Seedance 2.0", maxResolution: "1080p", supportsReference: true },
{ id: "doubao-seedance-2-0-fast-260128", label: "Seedance 2.0 Fast", maxResolution: "720p", supportsReference: true }];

const MODE_OPTIONS = [
["t2v", "文生视频"],
["first_frame", "首帧"],
["first_last", "首尾帧"],
["reference", "参考生成"],
["edit", "编辑视频"],
["extend", "延长视频"]];
const MODE_LABELS = Object.fromEntries(MODE_OPTIONS);
const ARS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"];
const RESS = ["480p", "720p", "1080p"];
const BACKEND_CONFIG_KEY = "sd2video:backend-config";
const BACKEND_MODES = new Set(["mock", "dev", "real"]);
const CREATE_PATH = "/api/v1/tasks";

function readBackendConfig() {
  let saved = {};
  try { saved = JSON.parse(window.localStorage.getItem(BACKEND_CONFIG_KEY) || "{}"); } catch (_) {}
  const inline = window.SD2VIDEO_BACKEND || {};
  const metaBase = document.querySelector('meta[name="sd2video-api-base"]')?.content || "";
  const mode = inline.mode || saved.mode || "dev";
  const apiBase = window.__SD2VIDEO_API_BASE__ || inline.apiBase || metaBase || saved.apiBase || "";
  const createPath = inline.createPath || saved.createPath || CREATE_PATH;
  return {
    mode: BACKEND_MODES.has(mode) ? mode : "mock",
    apiBase: String(apiBase || "").replace(/\/+$/, ""),
    createPath: createPath.startsWith("/") ? createPath : "/" + createPath
  };
}

function createEndpoint(config) {
  return `${config.apiBase || ""}${config.createPath || CREATE_PATH}`;
}

function mediaUrlOf(item) {
  return typeof item === "string" ? item : item?.url;
}

function isBackendUsableUrl(url, config) {
  return /^https?:\/\//.test(url) || /^asset:\/\//.test(url) || /^data:image\/[^;]+;base64,/.test(url);
}

function firstInvalidMedia(items, config) {
  return (items || []).map(mediaUrlOf).find((url) => !url || !isBackendUsableUrl(url, config));
}

function validateCreateTaskParams(params, config = readBackendConfig()) {
  const errors = [];
  const model = MODELS.find((m) => m.id === params.model);
  const prompt = (params.prompt || "").trim();
  const seed = params.seed == null || params.seed === "" ? null : Number(params.seed);
  const hasVisualRef = (params.refImages || []).length > 0 || (params.refVideos || []).length > 0;

  if (!prompt && params.mode === "t2v") {
    errors.push({ field: "prompt", message: "提示词不能为空" });
  }
  if (!model) errors.push({ field: "model", message: "请选择有效模型" });
  if (!ARS.includes(params.ar || params.ratio)) errors.push({ field: "ratio", message: "请选择有效画面比例" });
  if (!RESS.includes(params.resolution)) errors.push({ field: "resolution", message: "请选择有效分辨率" });
  if (model?.maxResolution === "720p" && params.resolution === "1080p") {
    errors.push({ field: "resolution", message: "Seedance 2.0 Fast 不支持 1080p" });
  }
  if (!Number.isInteger(params.duration) || params.duration < 4 || params.duration > 15) {
    errors.push({ field: "duration", message: "时长必须在 4-15 秒之间" });
  }
  if (seed !== null && (!Number.isInteger(seed) || seed < -1 || seed > 2 ** 32 - 1)) {
    errors.push({ field: "seed", message: "随机种子必须是 -1 到 2^32-1 的整数" });
  }
  if (params.mode === "first_frame" && !params.startImg) {
    errors.push({ field: "startImg", message: "首帧模式需要上传首帧图片" });
  }
  if (params.mode === "first_last") {
    if (!params.startImg) errors.push({ field: "startImg", message: "首尾帧模式需要首帧图片" });
    if (!params.endImg) errors.push({ field: "endImg", message: "首尾帧模式需要尾帧图片" });
  }
  if (params.mode === "reference" && !hasVisualRef) {
    errors.push({ field: "reference", message: "参考生成至少需要 1 个参考图或参考视频" });
  }
  if (params.mode === "edit" && (params.editVideo || []).length !== 1) {
    errors.push({ field: "editVideo", message: "编辑视频需要且只能选择 1 个待编辑视频" });
  }
  if (params.mode === "extend" && ((params.refVideos || []).length < 1 || (params.refVideos || []).length > 3)) {
    errors.push({ field: "refVideos", message: "延长视频需要 1-3 个视频片段" });
  }
  if ((params.refAudios || []).length > 0 && !hasVisualRef && params.mode === "reference") {
    errors.push({ field: "refAudios", message: "音频参考必须搭配图片或视频素材" });
  }
  if (params.webSearch && params.mode !== "t2v") {
    errors.push({ field: "web_search", message: "联网搜索仅支持文生视频模式" });
  }
  for (const [field, value] of [
    ["startImg", params.startImg],
    ["endImg", params.endImg],
    ["refImages", firstInvalidMedia(params.refImages, config)],
    ["refVideos", firstInvalidMedia(params.refVideos, config)],
    ["refAudios", firstInvalidMedia(params.refAudios, config)],
    ["editVideo", firstInvalidMedia(params.editVideo, config)]
  ]) {
    if (value && !isBackendUsableUrl(value, config)) {
      errors.push({ field, message: "素材必须先上传为 http(s)、asset:// 或图片 base64 地址，不能直接提交本地 blob 地址" });
    }
  }
  return errors;
}

function mediaUrls(items) {
  return (items || []).map(mediaUrlOf).filter(Boolean);
}

function buildAssets(params) {
  return {
    first_frame: params.startImg || null,
    last_frame: params.endImg || null,
    reference_images: mediaUrls(params.refImages),
    reference_videos: mediaUrls(params.refVideos),
    reference_audios: mediaUrls(params.refAudios),
    edit_video: mediaUrls(params.editVideo)[0] || null
  };
}

function createClientRequestId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return "panel-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

function buildCreateTaskPayload(params) {
  const seed = params.seed == null || params.seed === "" ? null : Number(params.seed);
  return {
    mode: params.mode,
    model: params.model,
    prompt: (params.prompt || "").trim(),
    ratio: params.ratio || params.ar,
    resolution: params.resolution,
    duration: params.duration,
    seed,
    camera_fixed: !!params.camera_fixed,
    watermark: !!params.watermark,
    generate_audio: !!params.generate_audio,
    return_last_frame: !!params.return_last_frame,
    web_search: !!params.webSearch,
    assets: buildAssets(params),
    client_request_id: params.client_request_id || createClientRequestId()
  };
}

function extractTaskId(data) {
  return data?.task_id || data?.id || data?.task?.id || data?.data?.task_id || data?.data?.id || null;
}

function formatCreateError(error) {
  if (error?.field && error?.message) return `${error.field}: ${error.message}`;
  return error?.message || "创建任务失败，请稍后重试";
}

async function createVideoTask(payload, config = readBackendConfig(), options = {}) {
  const res = await fetch(createEndpoint(config), {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "X-Client-Request-Id": payload.client_request_id
    },
    signal: options.signal,
    body: JSON.stringify(payload)
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!res.ok) {
    if (res.status === 409 && data?.error?.code === "duplicate_request" && data?.existing?.task_id) {
      return {
        task_id: data.existing.task_id,
        status: data.existing.status || "queued",
        duplicate: true,
        backend_mode: config.mode
      };
    }
    const msg = data?.message || data?.error?.message || data?.detail || `后端返回 ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    err.field = data?.error?.field;
    err.code = data?.error?.code;
    err.response = data || text;
    throw err;
  }
  const taskId = extractTaskId(data);
  if (!taskId) throw new Error("后端创建任务响应缺少 task_id");
  return { ...(data || {}), task_id: taskId, backend_mode: config.mode };
}

// ── Task API / polling -------------------------------------------------
const TERMINAL_TASK_STATUSES = new Set(["succeeded", "failed", "cancelled", "deleted", "expired", "timeout"]);

function taskStatusLabel(status) {
  return ({
    queued: "排队中",
    running: "生成中",
    succeeded: "已完成",
    failed: "生成失败",
    cancelled: "已取消",
    deleted: "已删除",
    expired: "已过期",
    timeout: "等待超时",
    auth_error: "鉴权失败",
    network_error: "网络异常",
    error: "请求失败"
  })[status] || status || "未知状态";
}

function tasksEndpoint(config = readBackendConfig()) {
  return createEndpoint(config).replace(/\/+$/, "");
}

function extractVideoUrl(data) {
  const src = data?.data || data || {};
  if (typeof src.video_url === "string") return src.video_url;
  if (typeof src.videoUrl === "string") return src.videoUrl;
  const content = Array.isArray(src.content) ? src.content : [];
  for (const item of content) {
    if (item?.type !== "video_url") continue;
    if (typeof item.video_url === "string") return item.video_url;
    if (typeof item.video_url?.url === "string") return item.video_url.url;
  }
  return null;
}

function normalizeTask(data) {
  const src = data?.data || data || {};
  const status = String(src.status || data?.status || "queued").toLowerCase();
  const error = src.error || data?.error || {};
  const errorMessage =
    src.error_message || src.errorMessage || src.message || src.status_message ||
    (typeof error === "string" ? error : error.message || error.msg) || null;
  const model = src.model;
  const modelId = typeof model === "object" ? (model.id || model.name) : model;
  const taskId = src.task_id || src.taskId || src.id || data?.task_id || data?.taskId || data?.id || null;
  return {
    taskId,
    task_id: taskId,
    status,
    statusLabel: taskStatusLabel(status),
    videoUrl: extractVideoUrl(data),
    video_url: extractVideoUrl(data),
    errorMessage,
    error_message: errorMessage,
    progress: Number.isFinite(src.progress) ? src.progress : null,
    model: modelId || null,
    modelLabel: MODELS.find(m => m.id === modelId)?.label || (modelId ? String(modelId).replace(/doubao-seedance-/, "Seedance ").replace(/-\d+$/, "") : null),
    prompt: src.prompt || (Array.isArray(src.content) ? src.content.find(c => c.type === "text")?.text : null) || null,
    ratio: src.ratio || src.ar || null,
    resolution: src.resolution || null,
    duration: src.duration || null,
    createdAt: src.created_at || src.createdAt || null,
    updatedAt: src.updated_at || src.updatedAt || null,
    raw: data
  };
}

async function requestCreateVideoTask(params, { signal, config = readBackendConfig() } = {}) {
  const validationErrors = validateCreateTaskParams(params, config);
  if (validationErrors.length) {
    const err = new Error(validationErrors[0].message);
    err.field = validationErrors[0].field;
    throw err;
  }
  const payload = buildCreateTaskPayload(params);
  return normalizeTask(await createVideoTask(payload, config, { signal }));
}

async function requestTaskStatus(taskId, { signal, config = readBackendConfig() } = {}) {
  const res = await fetch(`${tasksEndpoint(config)}/${encodeURIComponent(taskId)}`, {
    headers: { "Accept": "application/json" },
    signal
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!res.ok) {
    const msg = data?.message || data?.error?.message || text || "查询任务失败";
    const err = new Error(msg);
    err.status = res.status;
    err.code = data?.error?.code;
    throw err;
  }
  return normalizeTask(data);
}

async function requestListTasks({ pageNum = 1, pageSize = 10, statusFilter, signal, config = readBackendConfig() } = {}) {
  const params = new URLSearchParams({ page_num: String(pageNum), page_size: String(pageSize) });
  if (statusFilter && statusFilter !== "all") params.set("status", statusFilter);
  const res = await fetch(`${tasksEndpoint(config)}?${params}`, {
    headers: { "Accept": "application/json" },
    signal
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!res.ok) {
    const msg = data?.message || data?.error?.message || text || "查询任务列表失败";
    const err = new Error(msg);
    err.status = res.status;
    err.code = data?.error?.code;
    throw err;
  }
  return normalizeListResult(data, pageNum, pageSize);
}

async function requestDeleteTask(taskId, { currentStatus, signal, config = readBackendConfig() } = {}) {
  const res = await fetch(`${tasksEndpoint(config)}/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({ current_status: currentStatus || null })
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!res.ok) {
    const msg = data?.message || data?.error?.message || text || "更新任务失败";
    const err = new Error(msg);
    err.status = res.status;
    err.code = data?.error?.code;
    throw err;
  }
  return normalizeTask(data);
}

function normalizeListResult(data, pageNum, pageSize) {
  const src = data?.data || data || {};
  const itemsRaw = Array.isArray(src.items) ? src.items : Array.isArray(src.data) ? src.data : [];
  const total = typeof src.total === "number" ? src.total : Number(src.total) || itemsRaw.length;
  return {
    items: itemsRaw.map(normalizeTask),
    total,
    pageNum,
    pageSize,
    hasMore: src.has_more ?? (pageNum * pageSize < total)
  };
}

function classifyTaskError(err) {
  if (err?.name === "AbortError") return null;
  if (err?.status === 401 || err?.status === 403) return { status: "auth_error", errorMessage: "后端鉴权失败，请检查服务端密钥配置。" };
  if (err?.status) return { status: "error", errorMessage: err.message || "后端返回错误，请稍后重试。" };
  return { status: "network_error", errorMessage: "网络请求失败，请检查连接后重试。" };
}

function nodePatchFromTask(task) {
  const status = task.status;
  const videoUrl = task.videoUrl || task.video_url || null;
  const errorMessage = task.errorMessage || task.error_message || null;
  if (status === "succeeded") {
    return { status: "done", taskStatus: status, task_status: status, statusText: task.statusLabel, progress: 100, videoUrl, video_url: videoUrl, errorMessage: null, error_message: null, completedAt: Date.now() };
  }
  if (status === "queued" || status === "running") {
    return { status: "generating", taskStatus: status, task_status: status, statusText: task.statusLabel, progress: task.progress ?? (status === "queued" ? 12 : 55) };
  }
  if (status === "cancelled" || status === "deleted") {
    return { status: "cancelled", taskStatus: status, task_status: status, statusText: task.statusLabel, progress: null, errorMessage: errorMessage || task.statusLabel, error_message: errorMessage || task.statusLabel, completedAt: Date.now() };
  }
  return { status: "error", taskStatus: status, task_status: status, statusText: task.statusLabel, progress: null, errorMessage: errorMessage || task.statusLabel, error_message: errorMessage || task.statusLabel, completedAt: Date.now() };
}

function startTaskPolling({ taskId, signal, config = readBackendConfig(), onUpdate, onDone, timeoutMs = 600000, initialDelay = 1200, maxDelay = 5000 }) {
  let stopped = false;
  let timer = null;
  let delay = initialDelay;
  const startedAt = Date.now();
  const stop = () => { stopped = true;if (timer) clearTimeout(timer); };
  if (signal) signal.addEventListener("abort", stop, { once: true });
  async function tick() {
    if (stopped) return;
    if (Date.now() - startedAt >= timeoutMs) {
      const timeoutTask = { taskId, status: "timeout", statusLabel: taskStatusLabel("timeout"), errorMessage: "等待时间过长，已停止轮询。可稍后从历史任务恢复。" };
      onUpdate(timeoutTask);
      onDone?.(timeoutTask);
      stop();
      return;
    }
    try {
      const task = await requestTaskStatus(taskId, { signal, config });
      if (stopped) return;
      onUpdate(task);
      if (TERMINAL_TASK_STATUSES.has(task.status)) {
        onDone?.(task);
        stop();
        return;
      }
      delay = Math.min(maxDelay, Math.round(delay * 1.35));
      timer = setTimeout(tick, delay);
    } catch (err) {
      const task = classifyTaskError(err);
      if (!task || stopped) return;
      onUpdate({ taskId, status: task.status, statusLabel: taskStatusLabel(task.status), errorMessage: task.errorMessage });
      onDone?.(task);
      stop();
    }
  }
  timer = setTimeout(tick, 0);
  return { stop };
}

function Pill({ label, on, onClick, disabled }) {
  return <button onClick={disabled ? undefined : onClick} disabled={disabled} className={"pill" + (on ? " on" : "") + (disabled ? " off" : "")}>{label}</button>;
}
function Toggle({ on, onChange }) {
  return (
    <button onClick={() => onChange(!on)} className="tgl" style={{ background: on ? "#111" : "#ccc" }}>
      <div className="tgl-k" style={{ left: on ? 18 : 2 }} />
    </button>);

}

function MediaPicker({ label, accept, kind, items, onChange, max = 1 }) {
  const ref = React.useRef();
  const list = items || [];
  function add(files) {
    const next = [...list];
    for (const f of Array.from(files || [])) {
      if (next.length >= max) break;
      next.push({ url: URL.createObjectURL(f), name: f.name, kind });
    }
    onChange(next);
  }
  function remove(i) {
    onChange(list.filter((_, idx) => idx !== i));
  }
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: "#888" }}>{label}</span>
        <span style={{ fontSize: 10, color: "#bbb", fontVariantNumeric: "tabular-nums" }}>{list.length}/{max}</span>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {list.map((it, i) =>
        <div key={it.url + i} className="asset-chip">
          {kind === "image" && <img src={it.url} />}
          {kind === "video" && <video src={it.url} muted />}
          {kind === "audio" && <div className="audio-chip">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.5A4 4 0 1 1 10 10V5h10v3H12z" /></svg>
          </div>}
          <span>{kind === "image" ? "图片" : kind === "video" ? "视频" : "音频"}{i + 1}</span>
          <button onClick={(e) => {e.stopPropagation();remove(i);}}>×</button>
        </div>
        )}
        {list.length < max &&
        <button className="add-asset" onClick={() => ref.current?.click()}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
          {label}
        </button>}
      </div>
      <input ref={ref} type="file" accept={accept} multiple={max > 1} style={{ display: "none" }}
      onChange={(e) => {add(e.target.files);e.target.value = "";}} />
    </div>
  );
}

const PANEL_POS_KEY = "sd2video:create-panel-position";
function defaultPanelPos() {
  return {
    x: typeof window === "undefined" ? 16 : Math.max(16, window.innerWidth - 326),
    y: 56
  };
}
function clampPanelPos(pos, w = 310, h = 520) {
  if (typeof window === "undefined") return pos;
  return {
    x: Math.max(8, Math.min(window.innerWidth - w - 8, pos.x)),
    y: Math.max(8, Math.min(window.innerHeight - h - 8, pos.y))
  };
}
function readPanelPos() {
  if (typeof window === "undefined") return defaultPanelPos();
  try {
    const saved = JSON.parse(window.localStorage.getItem(PANEL_POS_KEY) || "null");
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) return clampPanelPos(saved);
  } catch (_) {}
  return defaultPanelPos();
}
function savePanelPos(pos) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(PANEL_POS_KEY, JSON.stringify(pos)); } catch (_) {}
}

// ── CreatePanel ──────────────────────────────────────────────────────
function CreatePanel({ node, onClose, onGenerate, backendConfig }) {
  const { useState: us, useRef: ur, useEffect: ue } = React;
  const [mode, setMode] = us(node?.mode || "t2v");
  const [model, setModel] = us(node?.model || MODELS[0].id);
  const [prompt, setPrompt] = us(node?.prompt || "");
  const [neg, setNeg] = us(node?.neg || "");
  const [showNeg, setShowNeg] = us(false);
  const [ar, setAr] = us(node?.ar || "16:9");
  const [res, setRes] = us(node?.resolution || "720p");
  const [dur, setDur] = us(node?.duration || 5);
  const [startImg, setStart] = us(node?.startImg || null);
  const [endImg, setEnd] = us(node?.endImg || null);
  const [refImages, setRefImages] = us(node?.refImages || []);
  const [refVideos, setRefVideos] = us(node?.refVideos || (node?.refVideo ? [{ url: node.refVideo, kind: "video" }] : []));
  const [refAudios, setRefAudios] = us(node?.refAudios || []);
  const [editVideo, setEditVideo] = us(node?.editVideo || []);
  const [seed, setSeed] = us(node?.seed || "");
  const [watermark, setWM] = us(node?.watermark || false);
  const [fixedCam, setFixedCam] = us(node?.fixedCam || node?.camera_fixed || false);
  const [generateAudio, setGenerateAudio] = us(node?.generateAudio || node?.generate_audio || false);
  const [returnLastFrame, setReturnLastFrame] = us(node?.returnLastFrame || node?.return_last_frame || false);
  const [webSearch, setWebSearch] = us(!!node?.webSearch || !!node?.tools?.some((t) => t.type === "web_search"));
  const [submitting, setSubmitting] = us(false);
  const [submitError, setSubmitError] = us("");
  const sRef = ur(),eRef = ur(),dragRef = ur(null);
  const [panelPos, setPanelPos] = us(readPanelPos);

  const selectedModel = MODELS.find((m) => m.id === model) || MODELS[0];
  const isFast = selectedModel.maxResolution === "720p";

  ue(() => {if (isFast && res === "1080p") setRes("720p");}, [isFast, res]);

  const hasPrompt = !!prompt.trim();
  const hasVisualRef = refImages.length > 0 || refVideos.length > 0;
  const panelParams = {
    mode, model, prompt, neg, ar, ratio: ar, resolution: res, duration: dur,
    startImg, endImg, refImages, refVideos, refAudios, editVideo,
    seed: seed || null, watermark, fixedCam, camera_fixed: fixedCam,
    generateAudio, generate_audio: generateAudio,
    returnLastFrame, return_last_frame: returnLastFrame,
    webSearch,
    modelLabel: selectedModel.label
  };
  const validationErrors = validateCreateTaskParams(panelParams, backendConfig || readBackendConfig());
  const firstError = validationErrors[0];
  const ok =
    mode === "t2v" ? hasPrompt :
    mode === "first_frame" ? !!startImg :
    mode === "first_last" ? !!startImg && !!endImg :
    mode === "reference" ? hasVisualRef :
    mode === "edit" ? editVideo.length === 1 :
    mode === "extend" ? refVideos.length > 0 :
    false;

  async function go() {
    if (submitting) return;
    if (!ok || firstError) {
      setSubmitError(firstError?.message || "请补齐必填参数");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    try {
      await onGenerate(panelParams);
    } catch (err) {
      setSubmitError(formatCreateError(err));
    } finally {
      setSubmitting(false);
    }
  }

  function startDrag(e) {
    if (e.button !== 0 || e.target.closest("button")) return;
    e.preventDefault();
    const panel = dragRef.current;
    const w = panel?.offsetWidth || 310;
    const h = panel?.offsetHeight || 520;
    const sx = e.clientX,sy = e.clientY,ox = panelPos.x,oy = panelPos.y;
    function mv(ev) {
      const next = clampPanelPos({ x: ox + ev.clientX - sx, y: oy + ev.clientY - sy }, w, h);
      setPanelPos(next);
      savePanelPos(next);
    }
    function up() {
      window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", mv);
    window.addEventListener("mouseup", up);
  }

  return (
    <div ref={dragRef} className="panel" style={{ left: panelPos.x, top: panelPos.y, right: "auto" }}>
      <div className="ph ph-drag" onMouseDown={startDrag}>
        <div><div className="pt">生成视频</div><div className="ps">Seedance · 火山方舟</div></div>
        <button className="pc" onMouseDown={(e) => e.stopPropagation()} onClick={onClose}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6L6 18M6 6l12 12" /></svg>
        </button>
      </div>
      <div className="pb">
        {/* mode */}
        <div>
          <div className="fl">生成模式</div>
          <div className="mode-grid">
            {MODE_OPTIONS.map(([v, l]) =>
            <button key={v} onClick={() => setMode(v)} className={"mode-tab" + (mode === v ? " on" : "")}>{l}</button>
            )}
          </div>
        </div>

        {/* model */}
        <div>
          <div className="fl">模型</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{MODELS.map((m) => <Pill key={m.id} label={m.label} on={model === m.id} onClick={() => setModel(m.id)} />)}</div>
        </div>

        {/* reference material */}
        {(mode === "first_frame" || mode === "first_last") &&
        <div>
            <div className="fl">关键帧</div>
          <div style={{ display: "flex", gap: 8 }}>
              {[[startImg, setStart, sRef, "首帧"], ...(mode === "first_last" ? [[endImg, setEnd, eRef, "尾帧"]] : [])].map(([src, set, ref, lbl]) =>
            <div key={lbl} className="imgslot" onClick={() => ref.current?.click()}>
                    {src ? <img src={src} /> : <>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ccc" strokeWidth="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
                      <span style={{ fontSize: 9, color: "#bbb", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{lbl}</span>
                    </>}
                    <input ref={ref} type="file" accept="image/*" style={{ display: "none" }}
              onChange={(e) => {const f = e.target.files[0];if (f) set(URL.createObjectURL(f));}} />
                  </div>
            )}
              </div>
          </div>
        }
        {mode === "reference" &&
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="fl">参考素材</div>
          <MediaPicker label="参考图" accept="image/*" kind="image" items={refImages} onChange={setRefImages} max={9} />
          <MediaPicker label="参考视频" accept="video/*" kind="video" items={refVideos} onChange={setRefVideos} max={3} />
          <MediaPicker label="参考音频" accept="audio/*" kind="audio" items={refAudios} onChange={setRefAudios} max={3} />
        </div>}
        {mode === "edit" &&
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="fl">编辑素材</div>
          <MediaPicker label="待编辑视频" accept="video/*" kind="video" items={editVideo} onChange={setEditVideo} max={1} />
          <MediaPicker label="参考图" accept="image/*" kind="image" items={refImages} onChange={setRefImages} max={9} />
          <MediaPicker label="参考音频" accept="audio/*" kind="audio" items={refAudios} onChange={setRefAudios} max={3} />
        </div>}
        {mode === "extend" &&
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="fl">延长素材</div>
          <MediaPicker label="视频片段" accept="video/*" kind="video" items={refVideos} onChange={setRefVideos} max={3} />
        </div>}

        {/* prompt */}
        <div>
          <div className="fl">提示词</div>
          <textarea className="ta" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="描述你想生成的视频内容…" />
          <div onClick={() => setShowNeg((v) => !v)} style={{ fontSize: 11, color: "#bbb", cursor: "pointer", marginTop: 5, display: "flex", alignItems: "center", gap: 3 }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d={showNeg ? "M18 15l-6-6-6 6" : "M6 9l6 6 6-6"} /></svg>
            {showNeg ? "收起" : "添加负向提示词"}
          </div>
          {showNeg && <textarea className="ta" value={neg} onChange={(e) => setNeg(e.target.value)} placeholder="不希望出现的内容…" style={{ marginTop: 7, minHeight: 50 }} />}
        </div>

        {/* params */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>画面比例</div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>{ARS.map((r) => <Pill key={r} label={r} on={ar === r} onClick={() => setAr(r)} />)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>分辨率</div>
            <div style={{ display: "flex", gap: 5 }}>{RESS.map((r) => <Pill key={r} label={r} on={res === r} disabled={isFast && r === "1080p"} onClick={() => setRes(r)} />)}</div>
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: "#888" }}>时长</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: "#111", fontVariantNumeric: "tabular-nums" }}>{dur}s</span>
            </div>
            <input type="range" min="4" max="15" step="1" value={dur}
            onChange={(e) => setDur(parseInt(e.target.value))} className="slider" />
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "#bbb", marginTop: 3, fontVariantNumeric: "tabular-nums" }}>
              <span>4s</span><span>15s</span>
            </div>
          </div>
        </div>

        {/* options */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "#444", fontWeight: 500 }}>添加水印</span>
            <Toggle on={watermark} onChange={setWM} />
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "#444", fontWeight: 500 }}>生成音频</span>
            <Toggle on={generateAudio} onChange={setGenerateAudio} />
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "#444", fontWeight: 500 }}>返回尾帧</span>
            <Toggle on={returnLastFrame} onChange={setReturnLastFrame} />
          </div>
          {mode === "t2v" &&
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "#444", fontWeight: 500 }}>联网搜索</span>
            <Toggle on={webSearch} onChange={setWebSearch} />
          </div>}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span style={{ fontSize: 12, color: "#444", fontWeight: 500 }}>固定镜头</span>
              <div style={{ fontSize: 10.5, color: "#aaa", marginTop: 1 }}>禁用画面镜头运动</div>
            </div>
            <Toggle on={fixedCam} onChange={setFixedCam} />
          </div>
        </div>

        {/* seed */}
        <div>
          <div className="fl">随机种子（可选）</div>
          <div style={{ display: "flex", gap: 6 }}>
            <input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="留空则随机"
            style={{ flex: 1, height: 32, borderRadius: 8, border: "1.5px solid #eee", background: "#fafafa", padding: "0 10px", fontSize: 12, outline: "none" }} />
            <button onClick={() => setSeed(String(Math.floor(Math.random() * 9999999)))}
            style={{ height: 32, padding: "0 10px", borderRadius: 8, border: "1.5px solid #eee", background: "#f5f5f5", fontSize: 11, cursor: "pointer", color: "#666" }}>
              随机
            </button>
          </div>
        </div>

      </div>
      <div className="panel-footer">
        {(submitError || firstError) && (
          <div style={{ fontSize: 11, color: "#b91c1c", lineHeight: 1.45, marginBottom: 8 }}>
            {submitError || firstError.message}
          </div>
        )}
        {backendConfig?.mode && (
          <div style={{ fontSize: 10.5, color: "#aaa", marginBottom: 7, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            后端：{backendConfig.mode}{backendConfig.mode !== "mock" ? ` · ${createEndpoint(backendConfig)}` : ""}
          </div>
        )}
        <button onClick={go} disabled={!ok || !!firstError || submitting} className={"btn-gen" + (ok && !firstError && !submitting ? " ok" : " no")}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z" /></svg>
          {submitting ? "提交中…" : "生成视频"}
        </button>
      </div>
    </div>);

}

// ── DetailPanel ───────────────────────────────────────────────────────
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts);const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function DetailPanel({ node, onClose, onPreview, onDownload, onRegen, onCancel, onDelete }) {
  const refs = [];
  if (node.startImg) refs.push({ src: node.startImg, label: "首帧", kind: "image" });
  if (node.endImg) refs.push({ src: node.endImg, label: "尾帧", kind: "image" });
  if (node.editVideo) node.editVideo.forEach((r, i) => refs.push({ src: r.url, label: "编辑视频" + (i + 1), kind: "video" }));
  if (node.refImages) node.refImages.forEach((r, i) => refs.push({ src: r.url, label: "图片" + (i + 1), kind: "image" }));
  if (node.refVideos) node.refVideos.forEach((r, i) => refs.push({ src: r.url, label: "视频" + (i + 1), kind: "video" }));
  if (node.refAudios) node.refAudios.forEach((r, i) => refs.push({ src: r.url, label: "音频" + (i + 1), kind: "audio" }));
  const videoUrl = node.video_url || node.videoUrl;
  const errorMessage = node.error_message || node.errorMessage;
  const taskStatus = node.task_status || node.taskStatus || node.status;

  return (
    <div className="panel">
      <div className="ph">
        <div><div className="pt">视频详情</div><div className="ps">{node.modelLabel}</div></div>
        <button className="pc" onClick={onClose}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6L6 18M6 6l12 12" /></svg>
        </button>
      </div>
      <div className="pb">
        {/* Thumbnail / preview */}
        <div onClick={node.status === "done" && videoUrl ? onPreview : undefined}
        style={{ borderRadius: 10, overflow: "hidden", background: "#111", aspectRatio: aspectValue(node.ar), display: "flex", alignItems: "center", justifyContent: "center", position: "relative", cursor: node.status === "done" && videoUrl ? "pointer" : "default" }}>
          {node.status === "done" && videoUrl && !videoUrl.startsWith("blob:") ? (
            <video src={videoUrl} muted playsInline preload="metadata" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
          ) : node.status === "done" ? (
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(135deg,#1a1a2e,#16213e,#0f3460)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <div style={{ width: 44, height: 44, borderRadius: 22, background: "rgba(255,255,255,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z" /></svg>
              </div>
            </div>
          ) : node.status === "error" ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: 12 }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              <span style={{ color: "#ef4444", fontSize: 11, textAlign: "center" }}>{errorMessage || "生成失败"}</span>
            </div>
          ) : node.status === "cancelled" ? (
            <span style={{ color: "rgba(255,255,255,.55)", fontSize: 12 }}>{node.statusText || "已取消"}</span>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
              <div style={{ display: "flex", gap: 5 }}>{[0,1,2].map(i=><div key={i} style={{width:6,height:6,borderRadius:3,background:"rgba(255,255,255,.3)",animation:"blink 1.2s "+(i*0.2)+"s ease-in-out infinite"}}/>)}</div>
              <span style={{ color: "rgba(255,255,255,.4)", fontSize: 11 }}>生成中…</span>
            </div>
          )}
          {node.status === "done" && videoUrl && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <div style={{ width: 44, height: 44, borderRadius: 22, background: "rgba(0,0,0,.35)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z" /></svg>
              </div>
            </div>
          )}
        </div>

        {/* Title */}
        <div>
          <div className="fl">标题</div>
          <div style={{ fontSize: 13.5, color: "#111", fontWeight: 500, lineHeight: 1.4 }}>{node.title || node.prompt?.slice(0, 30) || "未命名视频"}</div>
        </div>

        {/* Reference materials */}
        {refs.length > 0 &&
        <div>
            <div className="fl">参考素材</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {refs.map((r, i) =>
            <div key={i} style={{ position: "relative", width: 64, height: 64, borderRadius: 8, overflow: "hidden", background: "#f0f0f0", border: "1px solid #e8e8e8" }}>
                  {r.kind === "image" ?
              <img src={r.src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> :
              r.kind === "video" ?
              <video src={r.src} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} /> :
              <div className="audio-chip" style={{ width: "100%", height: "100%" }}><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.5A4 4 0 1 1 10 10V5h10v3H12z" /></svg></div>}
                  <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, background: "linear-gradient(transparent,rgba(0,0,0,.6))", color: "#fff", fontSize: 9, padding: "6px 4px 3px", textAlign: "center", fontWeight: 500 }}>{r.label}</div>
                </div>
            )}
            </div>
          </div>
        }

        {/* Prompt */}
        {node.prompt &&
        <div>
            <div className="fl">提示词</div>
            <div style={{ background: "#f7f7f7", borderRadius: 8, padding: "9px 11px", fontSize: 12, color: "#333", lineHeight: 1.55 }}>{node.prompt}</div>
            {node.neg && <div style={{ background: "#fdf6f6", borderRadius: 8, padding: "7px 11px", fontSize: 11, color: "#a06060", lineHeight: 1.5, marginTop: 5 }}><span style={{ fontWeight: 600, marginRight: 4 }}>负向：</span>{node.neg}</div>}
          </div>
        }

        {/* Params */}
        <div>
          <div className="fl">参数</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {[
            ["比例", node.ar],
            ["分辨率", node.resolution],
            ["时长", node.duration + "s"],
            ...(node.taskId ? [["任务 ID", node.taskId]] : []),
            ...(node.backendMode ? [["后端", node.backendMode]] : []),
            ["模式", MODE_LABELS[node.mode] || "视频生成"],
            ["水印", node.watermark ? "开" : "关"],
            ["固定镜头", node.fixedCam ? "开" : "关"],
            ["生成音频", node.generateAudio ? "开" : "关"],
            ["返回尾帧", node.returnLastFrame ? "开" : "关"],
            ...(node.webSearch ? [["联网搜索", "开"]] : []),
            ...(node.seed ? [["种子", node.seed]] : [])].
            map(([k, v]) =>
            <div key={k} style={{ background: "#f7f7f7", borderRadius: 7, padding: "7px 9px" }}>
                <div style={{ fontSize: 9.5, color: "#999", fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 1 }}>{k}</div>
                <div style={{ fontSize: 12, color: "#111", fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{v}</div>
              </div>
            )}
          </div>
        </div>

        {/* Error message */}
        {errorMessage && (
          <div>
            <div className="fl">错误信息</div>
            <div style={{ background: "#fef2f2", borderRadius: 8, padding: "9px 11px", fontSize: 12, color: "#dc2626", lineHeight: 1.5 }}>{errorMessage}</div>
          </div>
        )}

        {/* Task status */}
        {taskStatus && (
          <div>
            <div className="fl">任务状态</div>
            <div style={{ background: "#f7f7f7", borderRadius: 8, padding: "9px 11px", fontSize: 12, color: "#333", lineHeight: 1.5 }}>
              <b style={{ marginRight: 6 }}>{node.statusText || taskStatusLabel(taskStatus)}</b>
              {node.taskId && <span style={{ color: "#888", fontVariantNumeric: "tabular-nums" }}>{node.taskId}</span>}
            </div>
          </div>
        )}

        {/* Video URL */}
        {videoUrl && node.status === "done" && (
          <div>
            <div className="fl">视频链接</div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input readOnly value={videoUrl} style={{ flex: 1, fontSize: 11, color: "#555", background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 7, padding: "6px 10px", outline: "none", overflow: "hidden", textOverflow: "ellipsis" }} />
              <button onClick={() => {navigator.clipboard.writeText(videoUrl).then(()=>alert("已复制"))}} style={{ padding: "6px 10px", borderRadius: 7, border: "1px solid #e5e5e5", background: "#fafafa", fontSize: 11, color: "#666", cursor: "pointer", whiteSpace: "nowrap" }}>复制</button>
            </div>
            <div style={{ fontSize: 10, color: "#aaa", marginTop: 4 }}>链接 24 小时内有效，请及时下载</div>
          </div>
        )}

        {/* Generation time */}
        <div>
          <div className="fl">生成时间</div>
          <div style={{ fontSize: 12, color: "#555", fontVariantNumeric: "tabular-nums" }}>{fmtTime(node.createdAt)}</div>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={onDownload} disabled={node.status !== "done"} style={{ flex: 1, padding: "9px 0", borderRadius: 9, border: "1.5px solid #e0e0e0", background: "#fff", fontSize: 12.5, fontWeight: 500, cursor: node.status === "done" ? "pointer" : "not-allowed", color: node.status === "done" ? "#111" : "#bbb", display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
            下载
          </button>
          <button onClick={onRegen} style={{ flex: 1, padding: "9px 0", borderRadius: 9, border: "1.5px solid #e0e0e0", background: "#fff", fontSize: 12.5, fontWeight: 500, cursor: "pointer", color: "#111" }}>重新生成</button>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {node.status === "generating" && (
            <button onClick={onCancel} style={{ flex: 1, padding: "9px 0", borderRadius: 9, border: "1.5px solid #f59e0b", background: "#fffbeb", fontSize: 12.5, fontWeight: 600, cursor: "pointer", color: "#b45309" }}>
              取消任务
            </button>
          )}
          {(node.status === "done" || node.status === "error" || node.status === "cancelled") && (
            <button onClick={onDelete} style={{ flex: 1, padding: "9px 0", borderRadius: 9, border: "1.5px solid #fecaca", background: "#fff", fontSize: 12.5, fontWeight: 600, cursor: "pointer", color: "#b91c1c" }}>
              删除记录
            </button>
          )}
        </div>
      </div>
    </div>);

}

// ── PreviewModal ─────────────────────────────────────────────────────
function PreviewModal({ node, onClose }) {
  const [a, b] = FRAME_AR[node.ar] || [16, 9];
  const videoUrl = node.video_url || node.videoUrl;
  const isRealVideo = videoUrl && !videoUrl.startsWith("blob:");
  React.useEffect(() => {
    function onKey(e) {if (e.key === "Escape") onClose();}
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal-frame" style={{ aspectRatio: `${a}/${b}` }} onClick={(e) => e.stopPropagation()}>
        {isRealVideo ? (
          <video src={videoUrl} controls autoPlay style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", borderRadius: 12, background: "#000" }} />
        ) : (
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(135deg,#1a1a2e,#16213e,#0f3460)", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: 72, height: 72, borderRadius: 36, background: "rgba(255,255,255,0.2)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
              <svg width="30" height="30" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z" /></svg>
            </div>
          </div>
        )}
        <div style={{ position: "absolute", bottom: -32, left: 0, right: 0, textAlign: "center", color: "rgba(255,255,255,.6)", fontSize: 11.5 }}>
          {node.modelLabel} · {node.ar} · {node.resolution} · {node.duration}s
        </div>
      </div>
      <button className="modal-x" onClick={onClose}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
      </button>
    </div>);

}

// ── AgentPanel ────────────────────────────────────────────────────────
function AgentPanel({ onClose, nodes }) {
  const { useState: us } = React;
  const [msg, setMsg] = us("");
  const recentDone = nodes.filter((n) => n.status === "done").slice(-5);
  return (
    <div className="floatp">
      <div className="fp-hd">
        <div className="fp-ttl">
          <span>无声漫画叙事生成</span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 9l6 6 6-6" /></svg>
        </div>
        <button className="fp-min" onClick={onClose} title="收起">
          <svg width="14" height="2" viewBox="0 0 14 2"><rect width="14" height="2" rx="1" fill="#666" /></svg>
        </button>
      </div>
      <div className="fp-bd">
        <p className="ag-msg">该开始生成画面并组装页面了。</p>

        <div className="plan-blk">
          <div className="plan-hd">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#999" strokeWidth="1.8"><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 9h6M9 13h6M9 17h4" /></svg>
            <span>更新计划</span><span className="plan-prog">1/3</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#999" strokeWidth="2.5"><path d="M6 9l6 6 6-6" /></svg>
          </div>
          <div className="plan-items">
            {[
            ["done", "所有角色与场景参考的一致性检查"],
            ["doing", "顺序生成各漫画分镜（共 6 格），保持画风一致"],
            ["todo", "组装最终漫画页 — 全页网格，自右向左阅读"]].
            map(([s, t], i) =>
            <div key={i} className={"plan-item s-" + s}>
                {s === "done" ?
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#666" strokeWidth="3" strokeLinecap="round"><path d="M5 12l5 5 9-11" /></svg> :
              <svg width="9" height="9" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="none" stroke="#999" strokeWidth="1.5" /></svg>}
                <span>{t}</span>
              </div>
            )}
          </div>
        </div>

        <div className="task-card">
          <div className="tc-hd">
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ width: 7, height: 7, borderRadius: 4, background: "#111", display: "inline-block" }} />
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "#111" }}>分镜画面与组装</span>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="#f59e0b"><path d="M12 2L1 21h22L12 2zm0 6l7.5 13h-15L12 8zm-1 4v4h2v-4h-2zm0 6v2h2v-2h-2z" /></svg>
          </div>
          <div style={{ fontSize: 12, color: "#666", margin: "6px 0 8px" }}>生成失败</div>
          <a className="tc-link">查看过程</a>
          <div className="tc-thumbs">
            {recentDone.length > 0 ? recentDone.map((n) =>
            <div key={n.id} className="tc-thumb" style={{ background: "linear-gradient(135deg,#1a1a2e,#16213e,#0f3460)" }}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="rgba(255,255,255,0.7)"><path d="M8 5v14l11-7z" /></svg>
              </div>
            ) : [0, 1, 2, 3, 4].map((i) =>
            <div key={i} className="tc-thumb" style={{ background: `linear-gradient(135deg,hsl(${i * 40 + 30},6%,${88 - i * 3}%),hsl(${i * 40 + 50},6%,${94 - i * 2}%))` }} />
            )}
          </div>
        </div>

        <p className="ag-msg">画面正在按顺序逐一生成 — 每一帧都基于前一帧，以保持统一的笔触风格。从空荡的狗屋开始，到女孩的寻找、父亲的抚慰，最后展开广阔的天空，狗在其中奔跑。</p>
        <p className="ag-msg" style={{ color: "#888" }}>这会花点时间，每个分镜逐帧生成以确保一致。完成后我会再通知你。</p>
      </div>

      <div className="fp-ft">
        <textarea className="ag-in" placeholder="想做点什么？" value={msg} onChange={(e) => setMsg(e.target.value)} style={{ padding: "10px 14px 0px" }} />
        <div className="ag-bar" style={{ padding: "0px 8px 6px 12px", lineHeight: "0" }}>
          <button className="ag-mode">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.4 4.6L18 8l-4.6 1.4L12 14l-1.4-4.6L6 8l4.6-1.4z" /></svg>
            <span>创建</span>
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <div style={{ flex: 1 }} />
          <button className="ag-mic" title="语音">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="2" width="6" height="13" rx="3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" /></svg>
          </button>
          <button className="ag-send" title="发送">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
          </button>
        </div>
      </div>
    </div>);

}

// ── AssetsPanel ────────────────────────────────────────────────────────
const MOCK_ASSETS = [
{ kind: "image", title: "漫画风格的安静狗屋庭院", grad: "linear-gradient(135deg,#eaeaea,#f8f8f8)", sketch: "house" },
{ kind: "image", title: "短发男人与他的女儿站在一起", grad: "linear-gradient(135deg,#f0ede5,#fafafa)", sketch: "two" },
{ kind: "image", title: "漫画风格——女孩在寻找小狗", grad: "linear-gradient(135deg,#ececec,#fcfcfc)", sketch: "girl" },
{ kind: "text", title: "环境参考指南 — 漫画页", body: "位置1：狗屋区域\n风格：黑白漫画墨线艺术，细腻线条、交叉阴影、网点处理。受谷口治郎启发。" },
{ kind: "text", title: "父亲角色参考集", body: "黑白日式漫画墨线画风\n谷口治郎风格的柔和现实主义\n\n角色描述：温和的父亲，35 岁左右，略高于平均…" },
{ kind: "image", title: "铅笔素描风格的小狗屋", grad: "linear-gradient(135deg,#e8e8e6,#f6f6f4)", sketch: "house" },
{ kind: "image", title: "素描风格庭院与狗屋", grad: "linear-gradient(135deg,#e6e6e8,#f4f4f6)", sketch: "house" },
{ kind: "image", title: "穿格子裙的小女孩", grad: "linear-gradient(135deg,#e8ebe8,#f6f8f6)", sketch: "girl" },
{ kind: "text", title: "角色参考集 — 漫画女孩", body: "角色：5–6 岁小女孩。短乱发与刘海。大而富有表现力的漫画眼睛…" },
{ kind: "image", title: "图形小说风格男性肖像", grad: "linear-gradient(135deg,#ededed,#f9f9f9)", sketch: "two" }];

function Sketch({ kind }) {
  const com = <g stroke="#999" strokeWidth="0.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />;
  if (kind === "house") return <svg viewBox="0 0 100 100" style={{ width: "100%", height: "100%" }}>
    <g stroke="#a0a0a0" strokeWidth="0.6" fill="none">
      <path d="M30 60 L50 42 L70 60 L70 80 L30 80 Z" />
      <path d="M45 80 L45 65 L55 65 L55 80" />
      <path d="M10 80 L90 80" />
      <path d="M15 78 Q25 73 35 76" />
      <circle cx="80" cy="35" r="4" /><path d="M75 32 Q80 28 85 33" />
    </g>
  </svg>;
  if (kind === "girl") return <svg viewBox="0 0 100 100" style={{ width: "100%", height: "100%" }}>
    <g stroke="#a0a0a0" strokeWidth="0.6" fill="none">
      <ellipse cx="50" cy="28" rx="9" ry="11" />
      <path d="M41 22 Q45 16 50 18 Q55 16 59 22" />
      <path d="M44 40 L42 70 L58 70 L56 40 Z" />
      <path d="M44 50 L56 50 M44 55 L56 55 M44 60 L56 60" />
      <path d="M42 70 L40 92 M58 70 L60 92" />
    </g>
  </svg>;
  if (kind === "two") return <svg viewBox="0 0 100 100" style={{ width: "100%", height: "100%" }}>
    <g stroke="#a0a0a0" strokeWidth="0.6" fill="none">
      <ellipse cx="35" cy="32" rx="7" ry="9" />
      <path d="M30 50 L25 88 M40 50 L42 88" />
      <path d="M30 50 L42 50 L42 65 L30 65 Z" />
      <ellipse cx="65" cy="42" rx="5" ry="6" />
      <path d="M62 55 L60 88 M68 55 L70 88" />
      <path d="M62 55 L70 55 L70 70 L62 70 Z" />
    </g>
  </svg>;
  return null;
}
function AssetsPanel({ onClose, nodes }) {
  const { useState: us } = React;
  const [q, setQ] = us("");
  // mix mock + completed video nodes as "video" asset
  const videos = nodes.filter((n) => n.status === "done").map((n) => ({
    kind: "video", title: n.title || n.prompt?.slice(0, 24) || "视频", grad: "linear-gradient(135deg,#1a1a2e,#16213e,#0f3460)", node: n
  }));
  const all = [...videos, ...MOCK_ASSETS].filter((a) => !q || a.title.includes(q));
  const cols = [[], []];
  all.forEach((a, i) => cols[i % 2].push({ ...a, _i: i }));
  return (
    <div className="floatp ap">
      <div className="fp-hd">
        <div className="fp-ttl"><span>资产库</span></div>
        <button className="fp-min" onClick={onClose} title="收起">
          <svg width="14" height="2" viewBox="0 0 14 2"><rect width="14" height="2" rx="1" fill="#666" /></svg>
        </button>
      </div>
      <div className="ap-search-row">
        <div className="ap-search">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索资产…" />
          <span className="ap-kbd">⌘F</span>
        </div>
        <button className="ap-filter" title="筛选">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#666" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6" /><line x1="6" y1="12" x2="18" y2="12" /><line x1="10" y1="18" x2="14" y2="18" /></svg>
        </button>
      </div>
      <div className="ap-grid">
        {cols.map((col, ci) =>
        <div key={ci} className="ap-col">
            {col.map((a, i) =>
          <div key={a._i} className="ap-card">
                {a.kind === "image" || a.kind === "video" ?
            <div className="ap-thumb" style={{ background: a.grad, aspectRatio: i % 3 === 0 ? "4/5" : i % 3 === 1 ? "1/1" : "3/4" }}>
                    {a.kind === "image" && <Sketch kind={a.sketch} />}
                    {a.kind === "video" && <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}><div style={{ width: 24, height: 24, borderRadius: 12, background: "rgba(255,255,255,0.22)", display: "flex", alignItems: "center", justifyContent: "center" }}><svg width="10" height="10" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z" /></svg></div></div>}
                  </div> :

            <div className="ap-text">
                    <div className="ap-text-title">{a.title}</div>
                    <div className="ap-text-body">{a.body}</div>
                  </div>
            }
                <div className="ap-name">{a.title.length > 14 ? a.title.slice(0, 14) + "…" : a.title}</div>
                <div className="ap-kind">{a.kind === "image" ? "图片" : a.kind === "text" ? "文本" : "视频"}</div>
              </div>
          )}
          </div>
        )}
      </div>
    </div>);

}

// ── HistoryPanel ──────────────────────────────────────────────────────
const HISTORY_STATUS_OPTIONS = [
  ["all", "全部"],
  ["queued", "排队中"],
  ["running", "生成中"],
  ["succeeded", "已完成"],
  ["failed", "失败"],
  ["cancelled", "已取消"]
];
const HISTORY_STATUS_COLORS = {
  queued: { bg: "#f3f0ff", fg: "#7c3aed", dot: "#a78bfa" },
  running: { bg: "#fffbeb", fg: "#b45309", dot: "#f59e0b" },
  succeeded: { bg: "#ecfdf5", fg: "#047857", dot: "#10b981" },
  failed: { bg: "#fef2f2", fg: "#b91c1c", dot: "#ef4444" },
  cancelled: { bg: "#f5f5f5", fg: "#6b7280", dot: "#9ca3af" },
  deleted: { bg: "#f5f5f5", fg: "#9ca3af", dot: "#d1d5db" }
};

function fmtRelativeTime(ts) {
  if (!ts) return "—";
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return Math.floor(diff / 60000) + " 分钟前";
  if (diff < 86400000) return Math.floor(diff / 3600000) + " 小时前";
  if (diff < 604800000) return Math.floor(diff / 86400000) + " 天前";
  return fmtTime(ts);
}

function HistoryTaskCard({ task, onResume, onViewResult, onCancel, onDelete, onSelect, actionBusy, actionError }) {
  const [copied, setCopied] = React.useState(false);
  const sc = HISTORY_STATUS_COLORS[task.status] || HISTORY_STATUS_COLORS.cancelled;
  const isPending = task.status === "queued" || task.status === "running";
  const isDone = task.status === "succeeded" && (task.videoUrl || task.video_url);
  function handleCopy(e) {
    e.stopPropagation();
    navigator.clipboard.writeText(task.taskId).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }
  return (
    <div onClick={() => onSelect?.(task)} style={{ background: "#fff", borderRadius: 12, border: "1px solid #eee", padding: "12px 14px", cursor: "pointer" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 9px", borderRadius: 12, fontSize: 11, fontWeight: 600, background: sc.bg, color: sc.fg }}>
            <span style={{ width: 6, height: 6, borderRadius: 3, background: sc.dot }} />
            {task.statusLabel || taskStatusLabel(task.status)}
          </span>
          <span style={{ fontSize: 11, color: "#999", fontWeight: 500 }}>{task.modelLabel || "Seedance"}</span>
        </div>
        <span style={{ fontSize: 10.5, color: "#bbb", fontVariantNumeric: "tabular-nums" }}>{fmtRelativeTime(task.createdAt)}</span>
      </div>
      <div style={{ fontSize: 13, color: "#222", fontWeight: 500, lineHeight: 1.45, marginBottom: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {task.prompt || "（无提示词）"}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {[
          ["ID", (task.taskId || "").slice(0, 12) + "…"],
          task.ratio && ["比例", task.ratio],
          task.resolution && ["分辨率", task.resolution],
          task.duration && ["时长", task.duration + "s"],
          isDone && ["有结果", "✓"]
        ].filter(Boolean).map(([k, v]) => (
          <span key={k} style={{ fontSize: 10, color: "#888", background: "#f7f7f7", borderRadius: 5, padding: "2px 7px", fontVariantNumeric: "tabular-nums" }}>{k}: {v}</span>
        ))}
      </div>
      {(task.errorMessage || task.error_message) && (
        <div style={{ fontSize: 11.5, color: "#dc2626", background: "#fef2f2", borderRadius: 7, padding: "6px 10px", marginBottom: 10, lineHeight: 1.4 }}>{task.errorMessage || task.error_message}</div>
      )}
      {actionError && <div style={{ fontSize: 11.5, color: "#b91c1c", background: "#fff1f2", borderRadius: 7, padding: "6px 10px", marginBottom: 10, lineHeight: 1.4 }}>{actionError}</div>}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <button onClick={handleCopy} style={{ padding: "5px 10px", borderRadius: 7, border: "1px solid #e5e5e5", background: "#fafafa", fontSize: 11, color: "#666", cursor: "pointer" }}>
          {copied ? "已复制" : "复制 ID"}
        </button>
        {isPending && <button onClick={e => { e.stopPropagation(); onResume?.(task); }} style={{ padding: "5px 10px", borderRadius: 7, border: "1px solid #f59e0b", background: "#fffbeb", fontSize: 11, color: "#b45309", cursor: "pointer", fontWeight: 600 }}>恢复轮询</button>}
        {isPending && <button disabled={!!actionBusy} onClick={e => { e.stopPropagation(); onCancel?.(task); }} style={{ padding: "5px 10px", borderRadius: 7, border: "1px solid #f59e0b", background: "#fff7ed", fontSize: 11, color: "#b45309", cursor: actionBusy ? "not-allowed" : "pointer", fontWeight: 600, opacity: actionBusy ? .55 : 1 }}>{actionBusy === "cancel" ? "取消中…" : "取消"}</button>}
        {isDone && <button onClick={e => { e.stopPropagation(); onViewResult?.(task); }} style={{ padding: "5px 10px", borderRadius: 7, border: "none", background: "#111", fontSize: 11, color: "#fff", cursor: "pointer", fontWeight: 600 }}>查看结果</button>}
        {!isPending && task.status !== "deleted" && <button disabled={!!actionBusy} onClick={e => { e.stopPropagation(); onDelete?.(task); }} style={{ padding: "5px 10px", borderRadius: 7, border: "1px solid #fecaca", background: "#fff", fontSize: 11, color: "#b91c1c", cursor: actionBusy ? "not-allowed" : "pointer", fontWeight: 600, opacity: actionBusy ? .55 : 1 }}>{actionBusy === "delete" ? "删除中…" : "删除"}</button>}
      </div>
    </div>
  );
}

function HistoryPanel({ onClose, onResumeTask, onViewResult, onCancelTask, onDeleteTask, backendConfig }) {
  const { useState: us, useEffect: ue, useMemo: um, useRef: ur } = React;
  const [statusFilter, setStatusFilter] = us("all");
  const [page, setPage] = us(1);
  const [loading, setLoading] = us(false);
  const [error, setError] = us(null);
  const [searchQuery, setSearchQuery] = us("");
  const [listResult, setListResult] = us({ items: [], total: 0 });
  const [detailTask, setDetailTask] = us(null);
  const [actionBusy, setActionBusy] = us(null);
  const [actionErrors, setActionErrors] = us({});
  const abortRef = ur(null);
  const pageSize = 10;

  async function fetchList(p = page, status = statusFilter) {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const result = await requestListTasks({ pageNum: p, pageSize, statusFilter: status, signal: controller.signal, config: backendConfig });
      if (!controller.signal.aborted) {
        setListResult(result);
        setLoading(false);
      }
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (!controller.signal.aborted) {
        setError(classifyTaskError(err)?.errorMessage || "加载失败，请重试");
        setLoading(false);
      }
    }
  }

  ue(() => { fetchList(1, statusFilter); setPage(1); }, [statusFilter]);
  ue(() => () => { if (abortRef.current) abortRef.current.abort(); }, []);

  const filtered = um(() => {
    if (!searchQuery.trim()) return listResult.items;
    const q = searchQuery.trim().toLowerCase();
    return listResult.items.filter(t => (t.taskId && t.taskId.toLowerCase().includes(q)) || (t.prompt && t.prompt.toLowerCase().includes(q)));
  }, [listResult.items, searchQuery]);
  const totalPages = Math.max(1, Math.ceil(listResult.total / pageSize));
  function handlePageChange(newPage) {
    setPage(newPage);
    fetchList(newPage, statusFilter);
  }

  function setTaskActionError(taskId, message) {
    setActionErrors(prev => ({ ...prev, [taskId]: message }));
  }
  function clearTaskActionError(taskId) {
    setActionErrors(prev => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
  }
  async function runHistoryAction(task, action) {
    if (!task?.taskId || actionBusy) return;
    const isCancel = action === "cancel";
    if (isCancel && task.status !== "queued" && task.status !== "running") {
      setTaskActionError(task.taskId, "当前状态不可取消。");
      return;
    }
    if (!isCancel && (task.status === "queued" || task.status === "running")) {
      setTaskActionError(task.taskId, "任务仍在进行中，请先取消后再删除。");
      return;
    }
    const confirmed = window.confirm(isCancel ? `确认取消任务 ${task.taskId}？` : `确认删除任务 ${task.taskId}？删除后会从历史列表隐藏。`);
    if (!confirmed) return;
    setActionBusy({ taskId: task.taskId, action });
    clearTaskActionError(task.taskId);
    try {
      const nextTask = await requestDeleteTask(task.taskId, { currentStatus: task.status, config: backendConfig });
      if (isCancel) {
        setListResult(result => ({ ...result, items: result.items.map(t => t.taskId === task.taskId ? { ...t, ...nextTask } : t) }));
        setDetailTask(current => current && current.taskId === task.taskId ? { ...current, ...nextTask } : current);
        onCancelTask?.(nextTask);
      } else {
        setListResult(result => ({ ...result, items: result.items.filter(t => t.taskId !== task.taskId), total: Math.max(0, result.total - 1) }));
        setDetailTask(current => current && current.taskId === task.taskId ? null : current);
        onDeleteTask?.(task);
      }
    } catch (err) {
      setTaskActionError(task.taskId, err?.message || (isCancel ? "取消任务失败。" : "删除任务失败。"));
    } finally {
      setActionBusy(null);
    }
  }

  if (detailTask) {
    const detailBusy = actionBusy?.taskId === detailTask.taskId ? actionBusy.action : null;
    const detailActionError = actionErrors[detailTask.taskId];
    return (
      <div className="floatp" style={{ width: 380 }}>
        <div className="fp-hd">
          <div className="fp-ttl" style={{ cursor: "pointer" }} onClick={() => setDetailTask(null)}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6"/></svg>
            <span>任务详情</span>
          </div>
          <button className="fp-min" onClick={onClose} title="关闭"><svg width="14" height="2" viewBox="0 0 14 2"><rect width="14" height="2" rx="1" fill="#666"/></svg></button>
        </div>
        <div className="fp-bd">
          <div style={{ marginBottom: 14 }}>
            <div className="fl">任务 ID</div>
            <code style={{ display: "block", fontSize: 12, color: "#333", background: "#f5f5f5", padding: "5px 10px", borderRadius: 7, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{detailTask.taskId}</code>
          </div>
          <div style={{ marginBottom: 14 }}>
            <div className="fl">状态</div>
            {(() => { const sc = HISTORY_STATUS_COLORS[detailTask.status] || HISTORY_STATUS_COLORS.cancelled; return (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 12px", borderRadius: 14, fontSize: 12, fontWeight: 600, background: sc.bg, color: sc.fg }}>
                <span style={{ width: 7, height: 7, borderRadius: 4, background: sc.dot }} />
                {detailTask.statusLabel || taskStatusLabel(detailTask.status)}
              </span>
            ); })()}
          </div>
          {detailTask.prompt && <div style={{ marginBottom: 14 }}><div className="fl">提示词</div><div style={{ background: "#f7f7f7", borderRadius: 8, padding: "9px 11px", fontSize: 12.5, color: "#333", lineHeight: 1.55 }}>{detailTask.prompt}</div></div>}
          {(detailTask.errorMessage || detailTask.error_message) && <div style={{ marginBottom: 14 }}><div className="fl">错误信息</div><div style={{ background: "#fef2f2", borderRadius: 8, padding: "9px 11px", fontSize: 12, color: "#dc2626", lineHeight: 1.5 }}>{detailTask.errorMessage || detailTask.error_message}</div></div>}
          {detailActionError && <div style={{ marginBottom: 14, background: "#fff1f2", borderRadius: 8, padding: "9px 11px", fontSize: 12, color: "#b91c1c", lineHeight: 1.5 }}>{detailActionError}</div>}
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            {(detailTask.status === "queued" || detailTask.status === "running") && <button onClick={() => onResumeTask?.(detailTask)} style={{ flex: 1, padding: "10px 0", borderRadius: 9, border: "none", background: "#f59e0b", fontSize: 13, fontWeight: 600, cursor: "pointer", color: "#fff" }}>恢复轮询</button>}
            {(detailTask.status === "queued" || detailTask.status === "running") && <button disabled={!!detailBusy} onClick={() => runHistoryAction(detailTask, "cancel")} style={{ flex: 1, padding: "10px 0", borderRadius: 9, border: "1.5px solid #f59e0b", background: "#fffbeb", fontSize: 13, fontWeight: 600, cursor: detailBusy ? "not-allowed" : "pointer", color: "#b45309", opacity: detailBusy ? .55 : 1 }}>{detailBusy === "cancel" ? "取消中…" : "取消任务"}</button>}
            {detailTask.status === "succeeded" && (detailTask.videoUrl || detailTask.video_url) && <button onClick={() => onViewResult?.(detailTask)} style={{ flex: 1, padding: "10px 0", borderRadius: 9, border: "none", background: "#111", fontSize: 13, fontWeight: 600, cursor: "pointer", color: "#fff" }}>查看结果</button>}
            {detailTask.status !== "queued" && detailTask.status !== "running" && detailTask.status !== "deleted" && <button disabled={!!detailBusy} onClick={() => runHistoryAction(detailTask, "delete")} style={{ flex: 1, padding: "10px 0", borderRadius: 9, border: "1.5px solid #fecaca", background: "#fff", fontSize: 13, fontWeight: 600, cursor: detailBusy ? "not-allowed" : "pointer", color: "#b91c1c", opacity: detailBusy ? .55 : 1 }}>{detailBusy === "delete" ? "删除中…" : "删除记录"}</button>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="floatp" style={{ width: 400 }}>
      <div className="fp-hd">
        <div className="fp-ttl"><span>历史任务</span></div>
        <button className="fp-min" onClick={onClose} title="关闭"><svg width="14" height="2" viewBox="0 0 14 2"><rect width="14" height="2" rx="1" fill="#666"/></svg></button>
      </div>
      <div style={{ padding: "0 18px 10px" }}>
        <div style={{ display: "flex", alignItems: "center", background: "#fff", border: "1px solid #e2e2e2", borderRadius: 18, padding: "7px 14px", height: 34, boxSizing: "border-box" }}>
          <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="搜索任务 ID 或提示词…" style={{ flex: 1, border: "none", background: "none", outline: "none", fontSize: 13, color: "#222", fontFamily: "inherit" }} />
        </div>
      </div>
      <div style={{ padding: "0 18px 10px", display: "flex", gap: 5, flexWrap: "wrap" }}>
        {HISTORY_STATUS_OPTIONS.map(([val, label]) => (
          <button key={val} onClick={() => setStatusFilter(val)} style={{ padding: "4px 11px", borderRadius: 20, fontSize: 11.5, fontWeight: 600, cursor: "pointer", border: statusFilter === val ? "1.5px solid #111" : "1.5px solid #e5e5e5", background: statusFilter === val ? "#111" : "#fff", color: statusFilter === val ? "#fff" : "#777" }}>{label}</button>
        ))}
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 18px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
        {loading && <div style={{ padding: 40, textAlign: "center", fontSize: 12, color: "#999" }}>加载中…</div>}
        {error && !loading && <div style={{ padding: 40, textAlign: "center", fontSize: 12.5, color: "#666" }}>{error}<br/><button onClick={() => fetchList(page)} style={{ marginTop: 10, padding: "6px 14px", borderRadius: 8, border: "1px solid #ddd", background: "#fff", fontSize: 12, cursor: "pointer", color: "#333" }}>重试</button></div>}
        {!loading && !error && filtered.length === 0 && <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#bbb" }}>{searchQuery ? "没有匹配的任务" : "暂无历史任务"}</div>}
        {!loading && !error && filtered.map(task => <HistoryTaskCard key={task.taskId} task={task} onSelect={setDetailTask} onResume={onResumeTask} onViewResult={onViewResult} onCancel={(t)=>runHistoryAction(t,"cancel")} onDelete={(t)=>runHistoryAction(t,"delete")} actionBusy={actionBusy?.taskId === task.taskId ? actionBusy.action : null} actionError={actionErrors[task.taskId]} />)}
      </div>
      {!loading && !error && listResult.total > 0 && (
        <div style={{ padding: "10px 18px 14px", borderTop: "1px solid #f0f0f0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 11, color: "#999" }}>共 {listResult.total} 条</span>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button disabled={page <= 1} onClick={() => handlePageChange(page - 1)} style={{ width: 28, height: 28, borderRadius: 7, border: "1px solid #e5e5e5", background: page <= 1 ? "#f9f9f9" : "#fff", cursor: page <= 1 ? "not-allowed" : "pointer", color: page <= 1 ? "#ccc" : "#666" }}>‹</button>
            <span style={{ fontSize: 11.5, color: "#666", fontVariantNumeric: "tabular-nums", minWidth: 40, textAlign: "center" }}>{page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => handlePageChange(page + 1)} style={{ width: 28, height: 28, borderRadius: 7, border: "1px solid #e5e5e5", background: page >= totalPages ? "#f9f9f9" : "#fff", cursor: page >= totalPages ? "not-allowed" : "pointer", color: page >= totalPages ? "#ccc" : "#666" }}>›</button>
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, {
  VNode,
  CreatePanel,
  DetailPanel,
  PreviewModal,
  AgentPanel,
  AssetsPanel,
  HistoryPanel,
  HistoryTaskCard,
  frameSize,
  FRAME_AR,
  readBackendConfig,
  createEndpoint,
  validateCreateTaskParams,
  buildCreateTaskPayload,
  buildAssets,
  createVideoTask,
  formatCreateError,
  taskStatusLabel,
  requestListTasks,
  requestTaskStatus,
  requestCreateVideoTask,
  requestDeleteTask,
  startTaskPolling,
  nodePatchFromTask,
  classifyTaskError,
  TERMINAL_TASK_STATUSES
});
