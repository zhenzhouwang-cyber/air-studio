import express from "express";
import cors from "cors";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const port = Number(process.env.PORT || 8787);

app.use(cors());
app.use(express.json({ limit: "1mb" }));

function buildPromptSystem(outputLanguage = "en") {
  const promptLang = outputLanguage === "zh" ? "中文" : "英文";

  return `你是一个专业的AI图像生成Prompt工程师，服务于品牌设计和内容创作场景。

你的任务是将用户的自然语言描述转化为高质量的图像生成Prompt。

请严格输出 JSON：
{
  "prompt": "完整${promptLang}正向Prompt",
  "negative_prompt": "${promptLang}负向Prompt",
  "style_tags": ["标签1", "标签2"],
  "aspect_ratio": "1:1 或 16:9 或 9:16 或 4:3",
  "quality_tier": "standard 或 high 或 ultra",
  "reasoning": "一句中文解释"
}

要求：
1) prompt 与 negative_prompt 必须输出为${promptLang}
2) 不要在Prompt中包含文字排版内容
3) 根据 quality_tier 自动补足画质词
4) 若用户描述模糊，优先选择商业化可落地方向`;
}

const REVIEW_SYSTEM = `你是图像生成Prompt评审员。你要审阅给定的prompt质量并给出可执行反馈。
只输出JSON，不要输出其他内容。格式如下：
{
  "score": 0-100的整数,
  "grade": "A|B|C|D",
  "issues": ["问题1", "问题2"],
  "strengths": ["优点1", "优点2"],
  "needs_human_review": true/false,
  "human_review_checklist": ["人工复核点1", "人工复核点2"],
  "suggestion": "一句话改进建议"
}

评分标准（0-100）：
1) 主体与场景清晰度
2) 风格与构图完整度
3) 画质词与可执行性
4) 负向词有效性
5) 与用户需求一致性

判定 needs_human_review=true 的情况：
- 需求有歧义或矛盾
- Prompt 存在明显缺项导致生成结果不稳定
- 可能涉及版权、敏感或高风险内容
`;

function cleanJson(rawText = "") {
  return String(rawText).replace(/```json|```/gi, "").trim();
}

function parsePromptOutput(rawText) {
  const clean = cleanJson(rawText);
  try {
    return JSON.parse(clean);
  } catch {
    const match = clean.match(/\{[\s\S]*\}/);
    if (match) return JSON.parse(match[0]);
    throw new Error("模型未返回可解析的 JSON");
  }
}

async function callArkChat({ endpointId, apiKey, system, user, temperature = 0.3 }) {
  const key = apiKey || process.env.ARK_API_KEY;
  const model = endpointId || process.env.ARK_ENDPOINT_ID;
  const baseUrl = process.env.ARK_BASE_URL || "https://ark.cn-beijing.volces.com/api/v3";

  if (!key) throw new Error("缺少 ARK_API_KEY");
  if (!model) throw new Error("缺少 ARK_ENDPOINT_ID（ep-...）");

  const resp = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
    },
    body: JSON.stringify({
      model,
      max_tokens: 1200,
      temperature,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
    }),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`ARK HTTP ${resp.status}: ${body}`);
  }

  const data = await resp.json();
  return String(data?.choices?.[0]?.message?.content ?? "").trim();
}

async function callArkPrompt({ description, qualityTier, endpointId, apiKey, outputLanguage }) {
  const raw = await callArkChat({
    endpointId,
    apiKey,
    system: buildPromptSystem(outputLanguage),
    user: `${description}\n\n[quality_tier要求: ${qualityTier}]`,
    temperature: 0.3,
  });

  return parsePromptOutput(raw);
}

async function callArkReview({
  description,
  prompt,
  negativePrompt,
  qualityTier,
  endpointId,
  apiKey,
}) {
  const raw = await callArkChat({
    endpointId,
    apiKey,
    system: REVIEW_SYSTEM,
    user: `用户需求:
${description}

正向Prompt:
${prompt}

负向Prompt:
${negativePrompt}

quality_tier:
${qualityTier}`,
    temperature: 0.1,
  });

  return parsePromptOutput(raw);
}

async function translatePromptText({ text, endpointId, apiKey, targetLanguage = "zh" }) {
  const languageLabel = targetLanguage === "en" ? "英文" : "中文";

  const raw = await callArkChat({
    endpointId,
    apiKey,
    system: `你是翻译助手。请把用户提供的图像生成prompt翻译为${languageLabel}，保持语义、风格和细节，不要解释，不要加引号。`,
    user: text,
    temperature: 0.1,
  });

  return raw.replace(/^```[\s\S]*?\n/, "").replace(/```$/, "").trim();
}

async function callGeminiImage({ prompt, model, apiKey, aspectRatio, imageSize }) {
  const key = apiKey || process.env.GEMINI_API_KEY;
  const imageModel = model || process.env.GEMINI_IMAGE_MODEL || "gemini-3.1-flash-image-preview";

  if (!key) throw new Error("缺少 GEMINI_API_KEY");

  const resp = await fetch("https://generativelanguage.googleapis.com/v1beta/interactions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-goog-api-key": key,
    },
    body: JSON.stringify({
      model: imageModel,
      input: prompt,
      response_modalities: ["IMAGE"],
      generation_config: {
        image_config: {
          aspect_ratio: aspectRatio || "1:1",
          image_size: imageSize || "1k",
        },
      },
    }),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Gemini Image HTTP ${resp.status}: ${body}`);
  }

  const data = await resp.json();
  const images = (data?.outputs || [])
    .filter((item) => item?.type === "image" && item?.data)
    .map((item) => ({
      mimeType: item?.mime_type || "image/png",
      data: item?.data,
    }));

  if (!images.length) {
    throw new Error("Gemini 未返回可用图片数据");
  }

  return images;
}

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, service: "prompt-engine-proxy" });
});

app.post("/api/generate-prompt", async (req, res) => {
  try {
    const { description, qualityTier = "high", endpointId, apiKey, outputLanguage = "en" } = req.body || {};

    if (!description || typeof description !== "string") {
      return res.status(400).json({ error: "description 不能为空" });
    }

    const output = await callArkPrompt({
      description,
      qualityTier,
      endpointId,
      apiKey,
      outputLanguage,
    });

    return res.json({ success: true, data: output });
  } catch (error) {
    return res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "服务器异常",
    });
  }
});

app.post("/api/translate-prompt", async (req, res) => {
  try {
    const { text, endpointId, apiKey, targetLanguage = "zh" } = req.body || {};

    if (!text || typeof text !== "string") {
      return res.status(400).json({ error: "text 不能为空" });
    }

    const translated = await translatePromptText({
      text,
      endpointId,
      apiKey,
      targetLanguage,
    });

    return res.json({ success: true, data: { translated } });
  } catch (error) {
    return res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "服务器异常",
    });
  }
});

app.post("/api/review-prompt", async (req, res) => {
  try {
    const { description, prompt, negativePrompt = "", qualityTier = "high", endpointId, apiKey } = req.body || {};

    if (!description || typeof description !== "string") {
      return res.status(400).json({ error: "description 不能为空" });
    }
    if (!prompt || typeof prompt !== "string") {
      return res.status(400).json({ error: "prompt 不能为空" });
    }

    const review = await callArkReview({
      description,
      prompt,
      negativePrompt,
      qualityTier,
      endpointId,
      apiKey,
    });

    return res.json({ success: true, data: review });
  } catch (error) {
    return res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "服务器异常",
    });
  }
});

app.post("/api/generate-image", async (req, res) => {
  try {
    const { prompt, model, apiKey, aspectRatio, imageSize } = req.body || {};

    if (!prompt || typeof prompt !== "string") {
      return res.status(400).json({ error: "prompt 不能为空" });
    }

    const images = await callGeminiImage({
      prompt,
      model,
      apiKey,
      aspectRatio,
      imageSize,
    });

    return res.json({ success: true, data: { images } });
  } catch (error) {
    return res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "服务器异常",
    });
  }
});

app.listen(port, () => {
  console.log(`[prompt-engine-proxy] running at http://localhost:${port}`);
});
