import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import InfiniteCanvas from "./InfiniteCanvas";

type OptimizeResponse = {
  optimized_prompt: string;
  negative_prompt: string;
  style_tags: string[];
  aspect_ratio: string;
  quality_tier: string;
  reasoning: string;
  category?: string;
  structure_report?: {
    has_composition_terms?: boolean;
    has_lighting_terms?: boolean;
    style_matches_category?: boolean;
    negative_prompt_specific?: boolean;
  };
};

type TextToImageResponse = {
  r2_key: string;
  image_url: string;
  aspect_ratio: string;
};

type ImageModelOption = {
  label: string;
  value: string;
  speed: string;
  cost: string;
  note: string;
};

const IMAGE_MODEL_OPTIONS: ImageModelOption[] = [
  { label: "Nano Banana", value: "gemini-2.5-flash-image", speed: "快", cost: "$0.02/次", note: "测试优先" },
  { label: "Nano Banana Pro", value: "gemini-3-pro-image-preview", speed: "较慢", cost: "$0.05/次", note: "最高画质" },
  { label: "Nano Banana 2", value: "gemini-3.1-flash-image-preview", speed: "最快", cost: "$0.045/次", note: "综合最佳" },
  { label: "ARK Seedream 4.0", value: "ark-seedream-4.0", speed: "快", cost: "ARK计费", note: "火山方舟" },
];

const DESCRIPTION_PRESETS = [
  "高端品牌logo，二维平面，简洁专业，视觉高级感",
  "食品海报，暖色氛围，蒸汽感，近景构图",
  "科技产品KV，未来感，硬朗材质，强对比灯光",
  "中国风视觉，水墨留白，现代国潮审美",
];

const IMAGE_SIZE_OPTIONS = ["1K", "2K", "4K"];

const API_BASE = (import.meta.env.VITE_API_BASE || "").trim();

function buildApiUrl(path: string): string {
  if (!API_BASE) return path;
  return `${API_BASE.replace(/\/$/, "")}${path}`;
}

async function parseApi(resp: Response): Promise<unknown> {
  const raw = await resp.text();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    if (!resp.ok) throw new Error(raw || `HTTP ${resp.status}`);
    return null;
  }
}

function prettyError(raw: string): string {
  const text = raw.toLowerCase();
  if (text.includes("insufficient_quota")) return "额度不足：请检查 API 余额、令牌倍率或计费方式。";
  if (text.includes("missing environment variable")) return "后端环境变量缺失：请检查 .env 并重启后端。";
  if (text.includes("failed to fetch") || text.includes("networkerror")) return "无法连接后端：请确认 FastAPI 正在运行。";
  return raw;
}

export default function App() {
  const [workspaceMode, setWorkspaceMode] = useState<"pipeline" | "canvas">("pipeline");
  const [description, setDescription] = useState("");
  const [qualityTier, setQualityTier] = useState("high");
  const [outputLanguage, setOutputLanguage] = useState("en");
  const [optLoading, setOptLoading] = useState(false);
  const [optError, setOptError] = useState("");
  const [optResult, setOptResult] = useState<OptimizeResponse | null>(null);

  const [imagePrompt, setImagePrompt] = useState("");
  const [imageNegativePrompt, setImageNegativePrompt] = useState("");
  const [imageAspectRatio, setImageAspectRatio] = useState("1:1");
  const [imageSize, setImageSize] = useState("1K");
  const [imageModel, setImageModel] = useState("gemini-2.5-flash-image");
  const [referenceImageDataUrl, setReferenceImageDataUrl] = useState("");
  const [referenceImageName, setReferenceImageName] = useState("");
  const [imgLoading, setImgLoading] = useState(false);
  const [imgError, setImgError] = useState("");
  const [imgResult, setImgResult] = useState<TextToImageResponse | null>(null);

  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null);
  const [copiedKey, setCopiedKey] = useState("");
  const refImageInputRef = useRef<HTMLInputElement | null>(null);

  const selectedModel = useMemo(
    () => IMAGE_MODEL_OPTIONS.find((m) => m.value === imageModel) ?? IMAGE_MODEL_OPTIONS[0],
    [imageModel],
  );

  useEffect(() => {
    let cancelled = false;
    async function checkHealth() {
      try {
        const resp = await fetch(buildApiUrl("/api/health"));
        if (!cancelled) setApiHealthy(resp.ok);
      } catch {
        if (!cancelled) setApiHealthy(false);
      }
    }
    void checkHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  async function copyText(key: string, text: string) {
    if (!text) return;
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(""), 1200);
  }

  async function runOptimize() {
    if (!description.trim()) return;
    setOptLoading(true);
    setOptError("");
    setOptResult(null);

    try {
      const resp = await fetch(buildApiUrl("/api/optimize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description,
          quality_tier: qualityTier,
          output_language: outputLanguage,
        }),
      });

      const data = await parseApi(resp);
      if (!resp.ok) {
        const obj = (data || {}) as Record<string, unknown>;
        throw new Error(String(obj.detail || obj.error || `HTTP ${resp.status}`));
      }
      if (!data || typeof data !== "object") throw new Error("后端返回了非 JSON 结果");
      setOptResult(data as OptimizeResponse);
      setApiHealthy(true);
    } catch (err) {
      setOptError(prettyError(err instanceof Error ? err.message : "优化请求失败"));
      setApiHealthy(false);
    } finally {
      setOptLoading(false);
    }
  }

  async function runTextToImage() {
    if (!imagePrompt.trim()) return;
    setImgLoading(true);
    setImgError("");
    setImgResult(null);

    try {
      const resp = await fetch(buildApiUrl("/api/text-to-image"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: imagePrompt,
          negative_prompt: imageNegativePrompt,
          aspect_ratio: imageAspectRatio,
          image_size: imageSize,
          reference_image_data_url: referenceImageDataUrl,
          image_model: imageModel,
        }),
      });

      const data = await parseApi(resp);
      if (!resp.ok) {
        const obj = (data || {}) as Record<string, unknown>;
        throw new Error(String(obj.detail || obj.error || `HTTP ${resp.status}`));
      }
      if (!data || typeof data !== "object") throw new Error("后端返回了非 JSON 结果");
      setImgResult(data as TextToImageResponse);
      setApiHealthy(true);
    } catch (err) {
      setImgError(prettyError(err instanceof Error ? err.message : "文生图请求失败"));
      setApiHealthy(false);
    } finally {
      setImgLoading(false);
    }
  }

  function applyOptimized() {
    if (!optResult?.optimized_prompt) return;
    setImagePrompt(optResult.optimized_prompt);
    setImageNegativePrompt(optResult.negative_prompt || "");
  }

  async function handleReferenceImageChange(file: File | null) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setImgError("参考图必须是图片文件（jpg/png/webp 等）。");
      return;
    }

    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("读取参考图失败"));
        reader.readAsDataURL(file);
      });
      setReferenceImageDataUrl(dataUrl);
      setReferenceImageName(file.name);
      setImgError("");
    } catch (err) {
      setImgError(err instanceof Error ? err.message : "读取参考图失败");
    }
  }

  function clearReferenceImage() {
    setReferenceImageDataUrl("");
    setReferenceImageName("");
    if (refImageInputRef.current) {
      refImageInputRef.current.value = "";
    }
  }

  if (workspaceMode === "canvas") {
    return <InfiniteCanvas onBack={() => setWorkspaceMode("pipeline")} />;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AIR STUDIO</p>
          <h1>AIR</h1>
          <p className="subtitle">输入描述 → 提示词优化 → 文生图</p>
        </div>
        <div className="status-box">
          <p>后端状态</p>
          <strong className={apiHealthy === false ? "down" : "up"}>
            {apiHealthy === null ? "检测中" : apiHealthy ? "在线" : "离线"}
          </strong>
          <button className="status-action" onClick={() => setWorkspaceMode("canvas")} type="button">
            进入 Infinite Canvas
          </button>
        </div>
      </header>

      <section className="pipeline-strip" aria-label="工作流阶段">
        <span className="stage active">1. 描述输入</span>
        <span className="stage active">2. Prompt 优化</span>
        <span className="stage">3. 模型选择</span>
        <span className="stage">4. 出图与导出</span>
      </section>

      <section className="workspace">
        <article className="card">
          <div className="card-head">
            <h2>Prompt 优化</h2>
            <p>先把需求转成更稳定的生成语句</p>
          </div>

          <label className="field">
            <span>描述</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="例：一个高端品牌logo设计，要求平面、二维、专业、视觉高级感"
            />
            <small>{description.length} 字</small>
          </label>

          <div className="preset-row">
            {DESCRIPTION_PRESETS.map((preset) => (
              <button key={preset} className="chip" onClick={() => setDescription(preset)} type="button">
                {preset.slice(0, 14)}...
              </button>
            ))}
          </div>

          <div className="controls three">
            <label className="field">
              <span>画质</span>
              <select value={qualityTier} onChange={(e) => setQualityTier(e.target.value)}>
                <option value="standard">standard</option>
                <option value="high">high</option>
                <option value="ultra">ultra</option>
              </select>
            </label>

            <label className="field">
              <span>输出语言</span>
              <select value={outputLanguage} onChange={(e) => setOutputLanguage(e.target.value)}>
                <option value="en">英文</option>
                <option value="zh">中文</option>
              </select>
            </label>

            <button className="primary" disabled={optLoading || !description.trim()} onClick={runOptimize}>
              {optLoading ? "优化中..." : "开始优化"}
            </button>
          </div>

          {optError && <p className="error">{optError}</p>}

          {optResult && (
            <section className="result-card" aria-live="polite">
              <h3>优化结果</h3>
              <pre>{optResult.optimized_prompt}</pre>
              <h4>Negative Prompt</h4>
              <pre>{optResult.negative_prompt}</pre>

              <div className="tags">
                {optResult.style_tags?.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>

              <p className="meta">
                比例 {optResult.aspect_ratio} · 画质 {optResult.quality_tier}
              </p>
              <p className="meta">{optResult.reasoning}</p>

              <div className="quality-check">
                <span>{optResult.structure_report?.has_composition_terms ? "构图词 OK" : "构图词缺失"}</span>
                <span>{optResult.structure_report?.has_lighting_terms ? "光影词 OK" : "光影词缺失"}</span>
                <span>{optResult.structure_report?.style_matches_category ? "风格匹配 OK" : "风格匹配风险"}</span>
                <span>{optResult.structure_report?.negative_prompt_specific ? "负向词 OK" : "负向词不足"}</span>
              </div>

              <div className="actions">
                <button className="secondary" onClick={applyOptimized}>添加到文生图</button>
                <button className="ghost" onClick={() => void copyText("prompt", optResult.optimized_prompt)}>
                  {copiedKey === "prompt" ? "已复制 Prompt" : "复制 Prompt"}
                </button>
                <button className="ghost" onClick={() => void copyText("negative", optResult.negative_prompt)}>
                  {copiedKey === "negative" ? "已复制 Negative" : "复制 Negative"}
                </button>
              </div>
            </section>
          )}
        </article>

        <article className="card">
          <div className="card-head">
            <h2>文生图</h2>
            <p>选择模型、比例，直接生成并预览</p>
          </div>

          <div className="model-grid" role="radiogroup" aria-label="模型选择">
            {IMAGE_MODEL_OPTIONS.map((m) => (
              <button
                key={m.value}
                className={`model-tile ${imageModel === m.value ? "active" : ""}`}
                onClick={() => setImageModel(m.value)}
                type="button"
              >
                <strong>{m.label}</strong>
                <span>{m.cost}</span>
                <small>{m.note}</small>
              </button>
            ))}
          </div>

          <p className="model-summary">
            当前：{selectedModel.label}（{selectedModel.value}） · 速度 {selectedModel.speed} · 成本 {selectedModel.cost}
          </p>

          <label className="field">
            <span>Prompt</span>
            <textarea
              value={imagePrompt}
              onChange={(e) => setImagePrompt(e.target.value)}
              placeholder="在这里输入或粘贴优化后的 Prompt"
            />
          </label>

          <label className="field">
            <span>Negative Prompt</span>
            <textarea
              value={imageNegativePrompt}
              onChange={(e) => setImageNegativePrompt(e.target.value)}
              placeholder="在这里输入或自动带入负面提示词"
            />
          </label>

          <div className="controls three-image">
            <label className="field">
              <span>图片比例</span>
              <select value={imageAspectRatio} onChange={(e) => setImageAspectRatio(e.target.value)}>
                <option value="1:1">1:1</option>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
                <option value="4:3">4:3</option>
                <option value="3:4">3:4</option>
              </select>
            </label>

            <label className="field">
              <span>分辨率</span>
              <select value={imageSize} onChange={(e) => setImageSize(e.target.value)}>
                {IMAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </label>

            <button className="primary" disabled={imgLoading || !imagePrompt.trim()} onClick={runTextToImage}>
              {imgLoading ? "生成中..." : "开始文生图"}
            </button>
          </div>

          <div className="reference-box">
            <div className="reference-head">
              <strong>参考图（可选）</strong>
              {referenceImageName && <span>{referenceImageName}</span>}
            </div>
            <div className="reference-controls">
              <input
                ref={refImageInputRef}
                type="file"
                accept="image/*"
                onChange={(e) => void handleReferenceImageChange(e.target.files?.[0] ?? null)}
              />
              {referenceImageDataUrl && (
                <button className="ghost" type="button" onClick={clearReferenceImage}>
                  清空参考图
                </button>
              )}
            </div>
            {referenceImageDataUrl && (
              <img className="reference-preview" src={referenceImageDataUrl} alt="reference preview" />
            )}
          </div>

          {imgError && <p className="error">{imgError}</p>}

          {imgResult && (
            <section className="result-card" aria-live="polite">
              <h3>生成结果</h3>
              <img src={imgResult.image_url} alt="generated" />

              <div className="actions">
                <a href={imgResult.image_url} target="_blank" rel="noreferrer">
                  打开原图
                </a>
                <button className="ghost" onClick={() => void copyText("image-url", imgResult.image_url)}>
                  {copiedKey === "image-url" ? "已复制链接" : "复制图片链接"}
                </button>
              </div>
            </section>
          )}
        </article>
      </section>
    </main>
  );
}


