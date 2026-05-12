// CreateVideoPanel component
const MODELS = [
  { id: "doubao-seedance-2-0-260128", label: "Seedance 2.0", maxResolution: "1080p" },
  { id: "doubao-seedance-2-0-fast-260128", label: "Seedance 2.0 Fast", maxResolution: "720p" },
];
const MODES = [["t2v","文生视频"],["first_frame","首帧"],["first_last","首尾帧"]];
const ASPECT_RATIOS = ["16:9","9:16","1:1","4:3","3:4","21:9","adaptive"];
const RESOLUTIONS   = ["480p","720p","1080p"];

function Pill({ label, selected, onClick, disabled }) {
  return (
    <button onClick={disabled ? undefined : onClick} disabled={disabled} style={{
      padding:"4px 11px", borderRadius:20, fontSize:12, fontWeight:500, cursor:disabled ? "not-allowed" : "pointer",
      border: selected ? "1.5px solid #111" : "1.5px solid #e0e0e0",
      background: selected ? "#111" : "#fff", color: selected ? "#fff" : "#555",
      transition:"all .12s", opacity:disabled ? .35 : 1, textDecoration:disabled ? "line-through" : "none",
    }}>{label}</button>
  );
}

function ToggleSwitch({ on, onChange }) {
  return (
    <button onClick={() => onChange(!on)} style={{
      width:36, height:20, borderRadius:10, border:"none",
      background: on ? "#111" : "#ccc", cursor:"pointer",
      position:"relative", transition:"background .2s", flexShrink:0,
    }}>
      <div style={{
        position:"absolute", top:2, left: on ? 18 : 2,
        width:16, height:16, borderRadius:8, background:"#fff",
        boxShadow:"0 1px 3px rgba(0,0,0,.2)", transition:"left .2s",
      }}/>
    </button>
  );
}

function FieldLabel({ children }) {
  return <div style={{ fontSize:10, fontWeight:600, color:"#999", letterSpacing:"0.06em", textTransform:"uppercase", marginBottom:6 }}>{children}</div>;
}

function ImageSlot({ label, src, onUpload }) {
  const ref = React.useRef();
  return (
    <div onClick={() => ref.current.click()} style={{
      flex:1, height:72, borderRadius:10, border:"1.5px dashed #ddd",
      background:"#f8f8f8", display:"flex", flexDirection:"column", alignItems:"center",
      justifyContent:"center", gap:4, cursor:"pointer", position:"relative", overflow:"hidden",
      transition:"border-color .15s, background .15s",
    }}>
      {src
        ? <img src={src} style={{ position:"absolute", inset:0, width:"100%", height:"100%", objectFit:"cover" }} />
        : <>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#bbb" strokeWidth="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
            <span style={{ fontSize:9, color:"#bbb", fontWeight:600, letterSpacing:"0.05em", textTransform:"uppercase" }}>{label}</span>
          </>
      }
      <input ref={ref} type="file" accept="image/*" style={{ display:"none" }}
        onChange={e => { const f = e.target.files[0]; if (f) onUpload(URL.createObjectURL(f)); }} />
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

function CreateVideoPanel({ node, onClose, onGenerate, onNodeUpdate }) {
  const { useState: us, useEffect: ue, useRef: ur } = React;
  const [mode, setMode]         = us(node?.mode || "t2v");
  const [model, setModel]       = us(node?.model || MODELS[0].id);
  const [prompt, setPrompt]     = us(node?.prompt || "");
  const [negPrompt, setNeg]     = us(node?.negPrompt || "");
  const [showNeg, setShowNeg]   = us(false);
  const [ar, setAr]             = us(node?.ar || "16:9");
  const [resolution, setRes]    = us(node?.resolution || "720p");
  const [duration, setDur]      = us(node?.duration || 5);
  const [startImg, setStartImg] = us(node?.startImg || null);
  const [endImg, setEndImg]     = us(node?.endImg || null);
  const [seed, setSeed]         = us(node?.seed || "");
  const [watermark, setWM]      = us(node?.watermark || false);
  const [cameraCtrl, setCC]     = us(node?.camera_fixed || node?.cameraCtrl || false);
  const [generateAudio, setGA]  = us(node?.generate_audio || node?.generateAudio || false);
  const [returnLastFrame, setRLF] = us(node?.return_last_frame || node?.returnLastFrame || false);
  const [webSearch, setWS]      = us(!!node?.tools?.some(t => t.type === "web_search"));
  const [selectedPresets, setSelectedPresets] = us(node?.selectedPresets || []);
  const panelRef = ur(null);
  const [panelPos, setPanelPos] = us(readPanelPos);

  function syncCamTags(nextIds) {
    const ids = nextIds || [];
    const tags = ids.map(id => CAMERA_PRESETS.find(p => p.id === id)).filter(Boolean).map(p => "《" + p.tag + "》");
    const cleaned = prompt.replace(CAM_TAG_RE, "").trim();
    const next = tags.length ? tags.join("") + " " + cleaned : cleaned;
    setPrompt(next);
    return ids;
  }
  function togglePreset(id) {
    if (id === null) { setSelectedPresets([]); return; }
    setSelectedPresets(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id];
      return syncCamTags(next);
    });
  }

  const selectedModel = MODELS.find(m => m.id === model) || MODELS[0];
  const isFast = selectedModel.maxResolution === "720p";

  ue(() => {
    if (isFast && resolution === "1080p") setRes("720p");
  }, [isFast, resolution]);

  const canGenerate =
    mode === "t2v" ? prompt.trim() :
    mode === "first_frame" ? startImg :
    mode === "first_last" ? startImg && endImg :
    false;

  function handleGenerate() {
    const content = [];
    if (prompt.trim()) content.push({ type:"text", text:prompt.trim() });
    if (mode === "first_frame" && startImg) content.push({ type:"image_url", image_url:{ url:startImg }, role:"first_frame" });
    if (mode === "first_last") {
      if (startImg) content.push({ type:"image_url", image_url:{ url:startImg }, role:"first_frame" });
      if (endImg) content.push({ type:"image_url", image_url:{ url:endImg }, role:"last_frame" });
    }
    onGenerate({
      mode, model, prompt, negPrompt, ar, ratio:ar, resolution,
      duration: parseInt(duration), startImg, endImg,
      seed: seed || null, watermark, cameraCtrl, camera_fixed:cameraCtrl,
      generateAudio, generate_audio:generateAudio,
      returnLastFrame, return_last_frame:returnLastFrame,
      tools: webSearch ? [{ type:"web_search" }] : [],
      content,
      selectedPresets,
      modelLabel: selectedModel?.label || "Seedance",
    });
  }

  function startDrag(e) {
    if (e.button !== 0 || e.target.closest("button")) return;
    e.preventDefault();
    const panel = panelRef.current;
    const w = panel?.offsetWidth || 310;
    const h = panel?.offsetHeight || 520;
    const sx = e.clientX, sy = e.clientY, ox = panelPos.x, oy = panelPos.y;
    function move(ev) {
      const next = clampPanelPos({ x: ox + ev.clientX - sx, y: oy + ev.clientY - sy }, w, h);
      setPanelPos(next);
      savePanelPos(next);
    }
    function up() {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  return (
    <div ref={panelRef} style={{
      position:"fixed", top:panelPos.y, left:panelPos.x, width:310, maxHeight:"calc(100vh - 72px)",
      background:"#fff", borderRadius:16,
      boxShadow:"0 8px 40px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,.06)",
      zIndex:100, overflow:"hidden", display:"flex", flexDirection:"column",
      fontFamily:"-apple-system,'SF Pro Text',sans-serif",
    }}>
      {/* Header */}
      <div onMouseDown={startDrag} style={{ padding:"14px 16px 10px", borderBottom:"1px solid #f0f0f0", display:"flex", alignItems:"flex-start", justifyContent:"space-between", cursor:"move", userSelect:"none" }}>
        <div>
          <div style={{ fontSize:15, fontWeight:600, color:"#111", letterSpacing:-0.02 }}>生成视频</div>
          <div style={{ fontSize:11, color:"#999", marginTop:2 }}>Seedance · 即梦</div>
        </div>
        <button onMouseDown={e => e.stopPropagation()} onClick={onClose} style={{ width:26, height:26, borderRadius:13, border:"none", background:"#f0f0f0", cursor:"pointer", display:"flex", alignItems:"center", justifyContent:"center", color:"#666" }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
      </div>

      <div style={{ padding:"14px 16px 18px", display:"flex", flexDirection:"column", gap:14, overflowY:"auto", minHeight:0, flex:1 }}>
        {/* Mode */}
        <div>
          <FieldLabel>生成模式</FieldLabel>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:5 }}>
            {MODES.map(([m, label]) => (
              <button key={m} onClick={() => setMode(m)} style={{
                flex:1, padding:"6px 0", borderRadius:7, border:"none", fontSize:12, fontWeight:500, cursor:"pointer",
                background: mode===m ? "#111" : "#f3f3f3", color: mode===m ? "#fff" : "#777",
                transition:"all .15s",
              }}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Model */}
        <div>
          <FieldLabel>模型</FieldLabel>
          <div style={{ display:"flex", gap:6, flexWrap:"wrap" }}>
            {MODELS.map(m => (
              <Pill key={m.id} label={m.label} selected={model===m.id} onClick={() => setModel(m.id)} />
            ))}
          </div>
        </div>

        {/* Image upload for I2V */}
        {mode !== "t2v" && (
          <div>
            <FieldLabel>参考帧</FieldLabel>
            <div style={{ display:"flex", gap:8 }}>
              <ImageSlot label="首帧" src={startImg} onUpload={setStartImg} />
              {mode === "first_last" && <ImageSlot label="尾帧" src={endImg} onUpload={setEndImg} />}
            </div>
          </div>
        )}

        {/* Prompt */}
        <div>
          <FieldLabel>提示词</FieldLabel>
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)}
            placeholder="描述你想生成的视频内容…"
            style={{
              width:"100%", minHeight:80, padding:"10px 12px", fontSize:13, lineHeight:1.5,
              border:"1.5px solid #eee", borderRadius:10, background:"#fafafa",
              resize:"none", outline:"none", color:"#222", fontFamily:"inherit",
              transition:"border-color .15s",
            }}
            onFocus={e => e.target.style.borderColor="#aaa"}
            onBlur={e => e.target.style.borderColor="#eee"}
          />
          <div onClick={() => setShowNeg(v => !v)} style={{ fontSize:11, color:"#aaa", cursor:"pointer", marginTop:4, display:"flex", alignItems:"center", gap:3 }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d={showNeg ? "M18 15l-6-6-6 6" : "M6 9l6 6 6-6"}/>
            </svg>
            {showNeg ? "收起" : "添加负向提示词"}
          </div>
          {showNeg && (
            <textarea value={negPrompt} onChange={e => setNeg(e.target.value)}
              placeholder="不希望出现的内容…"
              style={{
                width:"100%", minHeight:52, padding:"8px 12px", fontSize:12, lineHeight:1.5, marginTop:8,
                border:"1.5px solid #eee", borderRadius:8, background:"#fafafa",
                resize:"none", outline:"none", color:"#555", fontFamily:"inherit",
              }}
            />
          )}
        </div>

        {/* Format params */}
        <div>
          <FieldLabel>输出参数</FieldLabel>
          <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
            <div>
              <div style={{ fontSize:11, color:"#888", marginBottom:5 }}>画面比例</div>
              <div style={{ display:"flex", gap:5, flexWrap:"wrap" }}>
                {ASPECT_RATIOS.map(r => <Pill key={r} label={r} selected={ar===r} onClick={() => setAr(r)} />)}
              </div>
            </div>
            <div>
              <div style={{ fontSize:11, color:"#888", marginBottom:5 }}>分辨率</div>
              <div style={{ display:"flex", gap:5 }}>
                {RESOLUTIONS.map(r => <Pill key={r} label={r} selected={resolution===r} disabled={isFast && r === "1080p"} onClick={() => setRes(r)} />)}
              </div>
            </div>
            <div>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"baseline", marginBottom:5 }}>
                <span style={{ fontSize:11, color:"#888" }}>时长</span>
                <span style={{ fontSize:12, fontWeight:600, color:"#111", fontVariantNumeric:"tabular-nums" }}>{duration}s</span>
              </div>
              <input type="range" min="4" max="15" step="1" value={duration} onChange={e => setDur(parseInt(e.target.value))}
                style={{ width:"100%", accentColor:"#111" }} />
            </div>
          </div>
        </div>

        {/* Options */}
        <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
            <div style={{ fontSize:12, color:"#444", fontWeight:500 }}>水印</div>
            <ToggleSwitch on={watermark} onChange={setWM} />
          </div>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
            <div style={{ fontSize:12, color:"#444", fontWeight:500 }}>生成音频</div>
            <ToggleSwitch on={generateAudio} onChange={setGA} />
          </div>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
            <div style={{ fontSize:12, color:"#444", fontWeight:500 }}>返回尾帧</div>
            <ToggleSwitch on={returnLastFrame} onChange={setRLF} />
          </div>
          {mode === "t2v" && <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
            <div style={{ fontSize:12, color:"#444", fontWeight:500 }}>联网搜索</div>
            <ToggleSwitch on={webSearch} onChange={setWS} />
          </div>}
          <CameraPresets selected={selectedPresets} onChange={togglePreset} fixedCam={cameraCtrl} onFixedCamChange={setCC} />
        </div>

        {/* Seed */}
        <div>
          <FieldLabel>随机种子</FieldLabel>
          <div style={{ display:"flex", gap:6 }}>
            <input value={seed} onChange={e => setSeed(e.target.value)} placeholder="留空则随机"
              style={{ flex:1, height:32, borderRadius:8, border:"1.5px solid #eee", background:"#fafafa", padding:"0 10px", fontSize:12, outline:"none", color:"#333", fontFamily:"monospace" }}
            />
            <button onClick={() => setSeed(Math.floor(Math.random()*9999999).toString())}
              style={{ height:32, padding:"0 10px", borderRadius:8, border:"1.5px solid #eee", background:"#f5f5f5", fontSize:11, color:"#666", cursor:"pointer" }}>
              随机
            </button>
          </div>
        </div>

      </div>
      <div style={{ position:"relative", flexShrink:0, padding:"12px 16px 14px", background:"#fff", borderTop:"1px solid #f4f4f4" }}>
        <div style={{ position:"absolute", left:0, right:0, top:-28, height:28, background:"linear-gradient(to bottom,rgba(255,255,255,0),#fff)", pointerEvents:"none" }} />
        {/* Generate */}
        <button onClick={handleGenerate} disabled={!canGenerate} style={{
          width:"100%", padding:"11px 0", borderRadius:10, border:"none",
          background: canGenerate ? "#111" : "#e0e0e0",
          color: canGenerate ? "#fff" : "#aaa",
          fontSize:14, fontWeight:600, cursor: canGenerate ? "pointer" : "not-allowed",
          transition:"all .15s", display:"flex", alignItems:"center", justifyContent:"center", gap:7,
          fontFamily:"inherit",
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill={canGenerate ? "#fff" : "#bbb"} stroke="none">
            <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/>
          </svg>
          生成视频
        </button>
      </div>
    </div>
  );
}

const CAMERA_PRESETS = [
  { id: "dolly_in",    label: "推镜头",   en: "Dolly in",        tag: "镜头缓缓推近" },
  { id: "dolly_out",   label: "拉镜头",   en: "Dolly out",       tag: "镜头缓缓拉远" },
  { id: "orbit",       label: "环绕运镜", en: "Orbit shot",      tag: "360度环绕运镜" },
  { id: "pan",         label: "横摇",     en: "Pan shot",        tag: "镜头缓慢横摇" },
  { id: "tilt",        label: "俯仰",     en: "Tilt shot",       tag: "镜头缓慢俯仰" },
  { id: "tracking",    label: "跟拍",     en: "Tracking shot",   tag: "镜头跟拍主体" },
  { id: "dive",        label: "俯冲",     en: "Dive shot",       tag: "第一视角俯冲" },
  { id: "close_up",    label: "特写",     en: "Close-up",        tag: "微距特写镜头" },
  { id: "wide",        label: "远景",     en: "Wide shot",       tag: "镜头拉远展现全景" },
  { id: "static_shot", label: "固定机位", en: "Static shot",     tag: "固定机位拍摄" },
  { id: "slow_motion", label: "慢动作",   en: "Slow motion",     tag: "慢动作镜头" },
  { id: "aerial",      label: "航拍",     en: "Aerial shot",     tag: "航拍俯瞰镜头" },
];

const CAM_TAG_RE = /《[^》]+》\s*/g;

function CameraPresets({ selected, onChange, fixedCam, onFixedCamChange }) {
  const { useState: us2 } = React;
  const [open, setOpen] = us2(true);
  return (
    <div>
      <div onClick={() => setOpen(v => !v)} style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        cursor: "pointer", userSelect: "none", marginBottom: open ? 8 : 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#666" strokeWidth="1.8">
            <path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
          </svg>
          <span style={{ fontSize: 11, fontWeight: 600, color: "#888", letterSpacing: "0.04em" }}>镜头控制</span>
          {selected.length > 0 && <span style={{
            fontSize: 10, color: "#fff", background: "#111", borderRadius: 9,
            padding: "1px 6px", fontWeight: 600, lineHeight: "16px",
          }}>{selected.length}</span>}
        </div>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#aaa" strokeWidth="2.5">
          <path d={open ? "M18 15l-6-6-6 6" : "M6 9l6 6 6-6"}/>
        </svg>
      </div>
      {open && <>
        <div style={{
          display: "flex", gap: 5, flexWrap: "wrap",
          opacity: fixedCam ? .35 : 1, pointerEvents: fixedCam ? "none" : "auto",
        }}>
          {CAMERA_PRESETS.map(p => (
            <button key={p.id} onClick={() => onChange(p.id)} title={p.en} style={{
              padding: "4px 10px", borderRadius: 14, fontSize: 11, fontWeight: 500, cursor: "pointer",
              border: selected.includes(p.id) ? "1.5px solid #111" : "1.5px solid #e0e0e0",
              background: selected.includes(p.id) ? "#111" : "#fff",
              color: selected.includes(p.id) ? "#fff" : "#666",
              transition: "all .12s", display: "flex", alignItems: "center", gap: 4,
            }}>
              {p.label}
              {selected.includes(p.id) && <span style={{ fontSize: 13, lineHeight: 1, marginLeft: 1 }}>×</span>}
            </button>
          ))}
        </div>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginTop: 10, paddingTop: 8, borderTop: "1px solid #f4f4f4",
        }}>
          <div>
            <span style={{ fontSize: 12, color: "#444", fontWeight: 500 }}>固定镜头</span>
            <div style={{ fontSize: 10.5, color: "#aaa", marginTop: 1 }}>禁用所有镜头运动</div>
          </div>
          <ToggleSwitch on={fixedCam} onChange={v => { onFixedCamChange(v); if (v) onChange(null); }} />
        </div>
      </>}
    </div>
  );
}

Object.assign(window, { CreateVideoPanel, CAMERA_PRESETS, CameraPresets, MODELS, MODES, ASPECT_RATIOS, RESOLUTIONS });
