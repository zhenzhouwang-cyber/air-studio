import base64
import json
import os
import time
import uuid
from typing import Any

import boto3
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google import genai
from pydantic import BaseModel, Field

load_dotenv(override=True)

SYSTEM_PROMPT = """你是资深图像生成Prompt架构师。目标：把用户描述转成可执行、细节充分、稳定出图的专业Prompt。

你必须执行完整工作流程（不能跳步）：
1) 意图识别：判断品类（食品/科技产品/中国风/品牌logo/室内等）。
2) 主体拆解：主体形态、材质、颜色、状态。
3) 风格匹配：仅从对应品类风格库选择，不得跨品类乱用。
4) 构图镜头：镜头距离、机位角度、主体位置、景深。
5) 光影氛围：光源方向、光质、氛围词。
6) 画质参数：细节等级、清晰度、商业可用性。
7) 负向约束：按品类给出差异化负向词，不可仅给通用词。

品类风格库锚点（示例）：
- 中国风: ink wash, xuan paper texture, seal red accents, shanshui composition, guochao, calligraphic rhythm, elegant negative space
- 食品: appetizing food photography, steam rising, warm tones, glossy highlights control, texture-rich close-up
- 科技产品: futuristic industrial design, hard-surface details, neon rim light, dark clean background, precision product shot
- 品牌logo: minimal vector branding, geometric balance, clean negative space, flat graphic identity

强制规则：
1) 构图信息必须明确（镜头/角度/景深）。
2) 光影信息必须明确（打光方式与氛围）。
3) 食品类必须考虑“食欲感”（steam, warm tones, texture appeal）。
4) 负向词必须品类定制，不得只写 blurry/low resolution 这类泛词。
5) aspect_ratio 需按场景判断：手机壁纸/竖版海报->9:16；横幅/横版海报->16:9；logo/头像->1:1；多数产品主图可1:1或4:3。

输出语言：根据用户要求输出为中文或英文。

仅输出JSON，不要输出额外说明：
{
  "prompt": "...",
  "negative_prompt": "...",
  "style_tags": ["..."],
  "aspect_ratio": "1:1|16:9|9:16|4:3",
  "quality_tier": "standard|high|ultra",
  "reasoning": "中文一句话",
  "category": "inferred category",
  "structure_report": {
    "has_composition_terms": true,
    "has_lighting_terms": true,
    "style_matches_category": true,
    "negative_prompt_specific": true
  }
}
"""

COMPOSITION_TERMS_EN = [
    "close-up",
    "macro",
    "wide shot",
    "three-quarter view",
    "45-degree angle",
    "top-down",
    "bird's-eye view",
    "shallow depth of field",
    "deep depth of field",
]
LIGHTING_TERMS_EN = [
    "soft diffused light",
    "studio lighting",
    "three-point lighting",
    "rim light",
    "backlight",
    "key light",
    "fill light",
    "dramatic lighting",
    "natural window light",
]

COMPOSITION_TERMS_ZH = ["特写", "微距", "广角", "45度", "俯视", "鸟瞰", "浅景深", "深景深", "三分构图"]
LIGHTING_TERMS_ZH = ["柔光", "硬光", "棚拍", "三点布光", "轮廓光", "逆光", "主光", "补光", "自然窗光"]

CATEGORY_PROFILES = {
    "food": {
        "keywords": ["食品", "美食", "饮料", "餐", "咖啡", "蛋糕", "甜点", "food", "drink", "beverage"],
        "preferred_styles": ["food photography", "commercial food styling", "appetizing texture"],
        "forbidden_styles": ["editorial fashion", "streetwear fashion", "runway"],
        "negative_focus": [
            "plastic look",
            "artificial color",
            "burnt edges",
            "greasy glare",
            "unappetizing color cast",
            "flat lifeless texture",
        ],
    },
    "logo_branding": {
        "keywords": ["logo", "标志", "品牌", "vi", "字体设计", "平面设计"],
        "preferred_styles": ["minimal vector design", "flat graphic", "clean geometric branding"],
        "forbidden_styles": ["photorealistic scene", "cinematic lighting", "fashion editorial"],
        "negative_focus": ["complex texture", "photographic background", "3d render artifacts", "illegible shape"],
    },
    "product": {
        "keywords": ["产品", "耳机", "手机", "电商", "包装", "product", "ecommerce"],
        "preferred_styles": ["studio product photography", "commercial catalog style", "clean background"],
        "forbidden_styles": ["fashion runway", "busy street scene"],
        "negative_focus": ["warped product geometry", "logo distortion", "dirty background", "random props"],
    },
    "tech": {
        "keywords": ["科技", "未来感", "芯片", "机器人", "赛博", "cyber", "tech", "futuristic"],
        "preferred_styles": ["futuristic product render", "high-tech industrial aesthetic", "precision hard-surface detailing"],
        "forbidden_styles": ["organic rustic style", "natural botanical scene", "food editorial"],
        "negative_focus": ["organic texture", "natural elements", "wood grain look", "soft handmade texture", "low-tech appearance"],
    },
    "chinese_style": {
        "keywords": ["中国风", "国风", "水墨", "山水", "中式", "古风", "guochao", "ink wash", "shanshui"],
        "preferred_styles": ["ink wash aesthetics", "xuan paper texture", "traditional chinese composition", "seal red accents"],
        "forbidden_styles": ["editorial fashion", "cyberpunk neon tech", "western streetwear style"],
        "negative_focus": ["western architectural motifs", "latin typography", "modern corporate stock look", "plastic 3d effect"],
    },
    "interior": {
        "keywords": ["客厅", "室内", "家居", "interior", "living room", "bedroom"],
        "preferred_styles": ["interior photography", "architectural composition", "natural materials"],
        "forbidden_styles": ["editorial fashion", "macro product shot"],
        "negative_focus": ["distorted perspective", "tilted walls", "overexposure", "cluttered composition"],
    },
}


class PipelineRequest(BaseModel):
    description: str = Field(min_length=3)
    quality_tier: str = "high"
    output_language: str = "en"
    aspect_ratio: str = "1:1"


class PipelineResponse(BaseModel):
    optimized_prompt: str
    negative_prompt: str
    style_tags: list[str]
    aspect_ratio: str
    quality_tier: str
    reasoning: str
    r2_key: str
    image_url: str


class OptimizeResponse(BaseModel):
    optimized_prompt: str
    negative_prompt: str
    style_tags: list[str]
    aspect_ratio: str
    quality_tier: str
    reasoning: str
    category: str = "generic"
    structure_report: dict[str, Any] = Field(default_factory=dict)


class TextToImageRequest(BaseModel):
    prompt: str = Field(min_length=3)
    negative_prompt: str = ""
    aspect_ratio: str = "1:1"


class TextToImageResponse(BaseModel):
    r2_key: str
    image_url: str
    aspect_ratio: str


app = FastAPI(title="Prompt2Image Pipeline")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": f"Unhandled server error: {exc}"},
    )


def _must_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.replace("```json", "").replace("```", "").strip()
    return t


def _parse_prompt_json(raw_text: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _contains_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _infer_category(description: str) -> str:
    desc = description.lower()
    best_category = "generic"
    best_score = 0
    for category, profile in CATEGORY_PROFILES.items():
        score = sum(1 for k in profile["keywords"] if k.lower() in desc)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


def _infer_aspect_ratio(description: str, current_ratio: str) -> str:
    desc = description.lower()
    if any(k in desc for k in ["手机壁纸", "壁纸", "竖版", "竖屏", "story", "mobile wallpaper", "vertical poster", "9:16"]):
        return "9:16"
    if any(k in desc for k in ["横幅", "横版", "banner", "landscape", "16:9"]):
        return "16:9"
    if any(k in desc for k in ["logo", "头像", "icon", "app icon", "方图", "1:1"]):
        return "1:1"
    if current_ratio in {"1:1", "16:9", "9:16", "4:3"}:
        return current_ratio
    return "1:1"


def _category_instruction(category: str, output_language: str) -> str:
    profile = CATEGORY_PROFILES.get(category)
    if not profile:
        return ""

    if output_language == "zh":
        return (
            f"推断品类: {category}\n"
            f"建议风格: {', '.join(profile['preferred_styles'])}\n"
            f"禁用风格: {', '.join(profile['forbidden_styles'])}\n"
            f"负向词重点: {', '.join(profile['negative_focus'])}"
        )

    return (
        f"Inferred category: {category}\n"
        f"Preferred styles: {', '.join(profile['preferred_styles'])}\n"
        f"Forbidden styles: {', '.join(profile['forbidden_styles'])}\n"
        f"Negative focus: {', '.join(profile['negative_focus'])}"
    )


def _quality_terms(quality_tier: str) -> str:
    if quality_tier == "ultra":
        return "masterpiece, ultra-detailed, photorealistic, 8k uhd, perfect composition"
    if quality_tier == "high":
        return "highly detailed, professional quality, sharp focus, clean rendering"
    return "high quality, detailed, sharp"


def _must_include_clause(description: str, output_language: str) -> str:
    parts = [x.strip() for x in description.replace("、", "，").replace(",", "，").split("，") if x.strip()]
    picks = [p for p in parts if 1 < len(p) <= 24][:6]
    if not picks:
        return ""
    if output_language == "zh":
        return f"必须包含要点：{'; '.join(picks)}"
    return f"must include key requirements: {'; '.join(picks)}"


def _postprocess_prompt(
    result: dict[str, Any], description: str, quality_tier: str, output_language: str
) -> dict[str, Any]:
    category = _infer_category(description)
    prompt = str(result.get("prompt", "")).strip()
    negative = str(result.get("negative_prompt", "")).strip()
    style_tags = list(result.get("style_tags", []))
    must_include = _must_include_clause(description, output_language)
    if must_include and must_include.lower() not in prompt.lower():
        prompt = f"{must_include}，{prompt}" if output_language == "zh" else f"{must_include}, {prompt}"

    composition_terms = COMPOSITION_TERMS_ZH if output_language == "zh" else COMPOSITION_TERMS_EN
    lighting_terms = LIGHTING_TERMS_ZH if output_language == "zh" else LIGHTING_TERMS_EN

    has_comp = _contains_any(prompt, composition_terms)
    has_light = _contains_any(prompt, lighting_terms)

    if not has_comp:
        prompt += "，三分构图，45度视角，浅景深" if output_language == "zh" else ", rule-of-thirds composition, 45-degree view, shallow depth of field"
        has_comp = True

    if not has_light:
        prompt += "，主光+补光，柔和棚拍光" if output_language == "zh" else ", soft studio key light with gentle fill light"
        has_light = True

    if _quality_terms(quality_tier).lower() not in prompt.lower():
        prompt += f"，{_quality_terms(quality_tier)}" if output_language == "zh" else f", {_quality_terms(quality_tier)}"

    # Food scenes must include appetite cues
    if category == "food":
        lower_prompt = prompt.lower()
        if output_language == "zh":
            if "蒸汽" not in prompt and "热气" not in prompt:
                prompt += "，可见蒸汽热气"
            if "暖色调" not in prompt and "食欲" not in prompt:
                prompt += "，暖色调食欲氛围"
        else:
            if "steam" not in lower_prompt:
                prompt += ", visible steam rising"
            if "warm tones" not in lower_prompt and "appetizing" not in lower_prompt:
                prompt += ", warm tones with appetizing texture appeal"

    profile = CATEGORY_PROFILES.get(category)
    style_match = True
    if profile:
        lower_prompt = prompt.lower()
        if any(bad.lower() in lower_prompt for bad in profile["forbidden_styles"]):
            style_match = False
        if not any(tag in style_tags for tag in profile["preferred_styles"][:2]):
            style_tags.extend(profile["preferred_styles"][:2])

    negative_specific = len(negative.split()) >= 8 or len(negative) >= 24
    if profile and not _contains_any(negative, profile["negative_focus"]):
        joiner = "，" if output_language == "zh" else ", "
        addition = joiner.join(profile["negative_focus"])
        negative = f"{negative}{joiner}{addition}" if negative else addition
        negative_specific = True

    result["prompt"] = prompt.strip()
    result["negative_prompt"] = negative.strip()
    result["style_tags"] = style_tags[:10]
    result["category"] = category
    result["aspect_ratio"] = _infer_aspect_ratio(description, str(result.get("aspect_ratio", "1:1")))
    result["structure_report"] = {
        "has_composition_terms": has_comp,
        "has_lighting_terms": has_light,
        "style_matches_category": style_match,
        "negative_prompt_specific": negative_specific,
    }
    return result


async def optimize_prompt_with_ark(description: str, quality_tier: str, output_language: str) -> dict[str, Any]:
    ark_api_key = _must_env("ARK_API_KEY")
    ark_endpoint_id = _must_env("ARK_ENDPOINT_ID")
    ark_base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")

    language_req = "中文" if output_language == "zh" else "英文"
    category = _infer_category(description)
    category_guide = _category_instruction(category, output_language)
    user_text = (
        f"{description}\n\n"
        f"[quality_tier: {quality_tier}]\n"
        f"[output_language: {language_req}]\n"
        f"[category_guidance]\n{category_guide}"
    )

    payload = {
        "model": ark_endpoint_id,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"{SYSTEM_PROMPT}\n\n{user_text}"},
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{ark_base_url}/responses",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ark_api_key}",
            },
            json=payload,
        )

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ARK error: {resp.text}")

    data = resp.json()

    raw = str(data.get("output_text", "")).strip()
    if not raw:
        # Fallback for non-standard serialized content blocks
        output_blocks = data.get("output", [])
        for block in output_blocks:
            contents = block.get("content", [])
            for part in contents:
                if part.get("type") == "output_text" and part.get("text"):
                    raw = str(part.get("text")).strip()
                    break
            if raw:
                break

    if not raw:
        preview = json.dumps(
            {
                "id": data.get("id"),
                "status": data.get("status"),
                "has_output": bool(data.get("output")),
            },
            ensure_ascii=False,
        )
        raise HTTPException(status_code=502, detail=f"ARK returned empty content. preview={preview}")

    try:
        parsed = _parse_prompt_json(raw)
        return _postprocess_prompt(parsed, description, quality_tier, output_language)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse ARK output JSON: {exc}") from exc


def _size_by_aspect_ratio(aspect_ratio: str) -> str:
    mapping = {
        "1:1": "1920x1920",
        "16:9": "2560x1440",
        "9:16": "1440x2560",
        "4:3": "2304x1728",
        "3:4": "1728x2304",
    }
    return mapping.get(aspect_ratio, "1920x1920")


async def generate_image_with_ark(prompt: str, negative_prompt: str = "", aspect_ratio: str = "1:1") -> tuple[str, str]:
    ark_api_key = _must_env("ARK_API_KEY")
    image_model = os.getenv("ARK_IMAGE_ENDPOINT_ID", "ep-20260316182601-pprlj")
    ark_base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")

    merged_prompt = prompt.strip()
    if negative_prompt.strip():
        merged_prompt += f"\n\nAvoid: {negative_prompt.strip()}"

    payload = {
        "model": image_model,
        "prompt": merged_prompt,
        "size": _size_by_aspect_ratio(aspect_ratio),
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{ark_base_url}/images/generations",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ark_api_key}",
            },
            json=payload,
        )

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ARK image error: {resp.text}")

    data = resp.json()
    image_url = str((data.get("data") or [{}])[0].get("url", "")).strip()
    if not image_url:
        raise HTTPException(status_code=502, detail="ARK image returned empty url")

    return image_url, payload["size"]


def upload_image_to_r2(image_bytes: bytes, mime_type: str) -> tuple[str, str]:
    account_id = _must_env("R2_ACCOUNT_ID")
    access_key = _must_env("R2_ACCESS_KEY_ID")
    secret_key = _must_env("R2_SECRET_ACCESS_KEY")
    bucket = _must_env("R2_BUCKET")
    public_base_url = os.getenv("R2_PUBLIC_BASE_URL", "").strip()

    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    key = f"generated/{time.strftime('%Y%m%d')}/{uuid.uuid4().hex}.png"

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=image_bytes,
        ContentType=mime_type,
    )

    if public_base_url:
        return key, f"{public_base_url.rstrip('/')}/{key}"

    signed = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=3600,
    )
    return key, signed


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/pipeline", response_model=PipelineResponse)
async def pipeline(req: PipelineRequest) -> PipelineResponse:
    optimized = await optimize_prompt_with_ark(
        description=req.description,
        quality_tier=req.quality_tier,
        output_language=req.output_language,
    )

    prompt = str(optimized.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=502, detail="Optimized prompt is empty")

    image_url, _size = await generate_image_with_ark(prompt, "", req.aspect_ratio)
    r2_key = "ark-direct"

    return PipelineResponse(
        optimized_prompt=prompt,
        negative_prompt=str(optimized.get("negative_prompt", "")),
        style_tags=list(optimized.get("style_tags", [])),
        aspect_ratio=str(optimized.get("aspect_ratio", req.aspect_ratio)),
        quality_tier=str(optimized.get("quality_tier", req.quality_tier)),
        reasoning=str(optimized.get("reasoning", "")),
        r2_key=r2_key,
        image_url=image_url,
    )


@app.post("/api/optimize", response_model=OptimizeResponse)
async def optimize_only(req: PipelineRequest) -> OptimizeResponse:
    optimized = await optimize_prompt_with_ark(
        description=req.description,
        quality_tier=req.quality_tier,
        output_language=req.output_language,
    )

    prompt = str(optimized.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=502, detail="Optimized prompt is empty")

    return OptimizeResponse(
        optimized_prompt=prompt,
        negative_prompt=str(optimized.get("negative_prompt", "")),
        style_tags=list(optimized.get("style_tags", [])),
        aspect_ratio=str(optimized.get("aspect_ratio", req.aspect_ratio)),
        quality_tier=str(optimized.get("quality_tier", req.quality_tier)),
        reasoning=str(optimized.get("reasoning", "")),
        category=str(optimized.get("category", "generic")),
        structure_report=dict(optimized.get("structure_report", {})),
    )


@app.post("/api/text-to-image", response_model=TextToImageResponse)
async def text_to_image(req: TextToImageRequest) -> TextToImageResponse:
    image_url, _size = await generate_image_with_ark(
        req.prompt.strip(),
        req.negative_prompt.strip(),
        req.aspect_ratio,
    )
    # Temporary mode: use Ark direct URL. R2 can be re-enabled later.
    return TextToImageResponse(r2_key="ark-direct", image_url=image_url, aspect_ratio=req.aspect_ratio)
