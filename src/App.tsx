import { useState } from "react";
import "./App.css";

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

export default function App() {
  const [description, setDescription] = useState("");
  const [qualityTier, setQualityTier] = useState("high");
  const [outputLanguage, setOutputLanguage] = useState("en");
  const [optLoading, setOptLoading] = useState(false);
  const [optError, setOptError] = useState("");
  const [optResult, setOptResult] = useState<OptimizeResponse | null>(null);

  const [imagePrompt, setImagePrompt] = useState("");
  const [imageNegativePrompt, setImageNegativePrompt] = useState("");
  const [imageAspectRatio, setImageAspectRatio] = useState("1:1");
  const [imgLoading, setImgLoading] = useState(false);
  const [imgError, setImgError] = useState("");
  const [imgResult, setImgResult] = useState<TextToImageResponse | null>(null);

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
      if (!data || typeof data !== "object") throw new Error("后端返回了非JSON结果");
      setOptResult(data as OptimizeResponse);
    } catch (err) {
      if (err instanceof TypeError && /fetch/i.test(err.message)) {
        setOptError("无法连接后端 API，请确认 FastAPI 已启动。\n先访问 http://127.0.0.1:8000/api/health");
      } else {
        setOptError(err instanceof Error ? err.message : "请求失败");
      }
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
        }),
      });

      const data = await parseApi(resp);
      if (!resp.ok) {
        const obj = (data || {}) as Record<string, unknown>;
        throw new Error(String(obj.detail || obj.error || `HTTP ${resp.status}`));
      }
      if (!data || typeof data !== "object") throw new Error("后端返回了非JSON结果");
      setImgResult(data as TextToImageResponse);
    } catch (err) {
      setImgError(err instanceof Error ? err.message : "文生图请求失败");
    } finally {
      setImgLoading(false);
    }
  }

  function useOptimizedPrompt() {
    if (!optResult?.optimized_prompt) return;
    setImagePrompt(optResult.optimized_prompt);
    setImageNegativePrompt(optResult.negative_prompt || "");
  }

  return (
    <main className="page">
      <header className="hero">
        <p className="eyebrow">AIR STUDIO</p>
        <h1>Air</h1>
        <p>Prompt 优化与文生图并行工作流</p>
      </header>

      <section className="split-grid">
        <article className="panel">
          <h2>Prompt 优化</h2>
          <label>
            描述
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="例：一个高端品牌logo设计，要求平面、二维、专业、视觉高级感"
            />
          </label>

          <div className="row">
            <label>
              画质
              <select value={qualityTier} onChange={(e) => setQualityTier(e.target.value)}>
                <option value="standard">standard</option>
                <option value="high">high</option>
                <option value="ultra">ultra</option>
              </select>
            </label>

            <label>
              输出语言
              <select value={outputLanguage} onChange={(e) => setOutputLanguage(e.target.value)}>
                <option value="en">英文</option>
                <option value="zh">中文</option>
              </select>
            </label>

            <button disabled={optLoading || !description.trim()} onClick={runOptimize}>
              {optLoading ? "优化中..." : "开始优化"}
            </button>
          </div>

          {optError && <p className="error">{optError}</p>}

          {optResult && (
            <div className="result-block">
              <h3>Optimized Prompt</h3>
              <pre>{optResult.optimized_prompt}</pre>
              <h3>Negative Prompt</h3>
              <pre>{optResult.negative_prompt}</pre>
              <div className="tags">
                {optResult.style_tags?.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
              <p className="meta">比例: {optResult.aspect_ratio} | 画质: {optResult.quality_tier}</p>
              <p className="meta">说明: {optResult.reasoning}</p>
              <div className="tags">
                <span>构图词: {optResult.structure_report?.has_composition_terms ? "OK" : "缺失"}</span>
                <span>光影词: {optResult.structure_report?.has_lighting_terms ? "OK" : "缺失"}</span>
                <span>风格匹配: {optResult.structure_report?.style_matches_category ? "OK" : "风险"}</span>
                <span>负向针对性: {optResult.structure_report?.negative_prompt_specific ? "OK" : "不足"}</span>
              </div>
              <button className="secondary" onClick={useOptimizedPrompt}>
                添加到文生图 Prompt
              </button>
            </div>
          )}
        </article>

        <article className="panel">
          <h2>文生图</h2>
          <label>
            Prompt
            <textarea
              value={imagePrompt}
              onChange={(e) => setImagePrompt(e.target.value)}
              placeholder="在这里输入或粘贴优化后的Prompt"
            />
          </label>
          <label>
            Negative Prompt
            <textarea
              value={imageNegativePrompt}
              onChange={(e) => setImageNegativePrompt(e.target.value)}
              placeholder="在这里输入或自动带入负面提示词"
            />
          </label>

          <div className="row">
            <label>
              图片比例
              <select value={imageAspectRatio} onChange={(e) => setImageAspectRatio(e.target.value)}>
                <option value="1:1">1:1</option>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
                <option value="4:3">4:3</option>
                <option value="3:4">3:4</option>
              </select>
            </label>
            <div />
            <div />
          </div>

          <div className="row single">
            <button disabled={imgLoading || !imagePrompt.trim()} onClick={runTextToImage}>
              {imgLoading ? "出图中..." : "开始文生图"}
            </button>
          </div>

          {imgError && <p className="error">{imgError}</p>}

          {imgResult && (
            <div className="result-block">
              <img src={imgResult.image_url} alt="generated" />
              <p className="meta">比例: {imgResult.aspect_ratio}</p>
              <p className="meta">R2 Key: {imgResult.r2_key}</p>
              <a href={imgResult.image_url} target="_blank" rel="noreferrer">
                打开原图
              </a>
            </div>
          )}
        </article>
      </section>
    </main>
  );
}
