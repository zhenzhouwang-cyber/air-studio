import base64
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import boto3
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google import genai
from pydantic import BaseModel, Field
from backend.ma_pipeline.api import router as ma_pipeline_router
from backend.canvas_api import router as canvas_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)
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
- 品牌设计: brand identity strategy, brand personality alignment, logomark + logotype system, typography direction, color system with usage context

强制规则：
1) 构图信息必须明确（镜头/角度/景深）。
2) 光影信息必须明确（打光方式与氛围）。
3) 食品类必须考虑“食欲感”（steam, warm tones, texture appeal）。
4) 负向词必须品类定制，不得只写 blurry/low resolution 这类泛词。
5) aspect_ratio 需按场景判断：手机壁纸/竖版海报->9:16；横幅/横版海报->16:9；logo/头像->1:1；多数产品主图可1:1或4:3。
6) 主体与文字必须完整入画，不可裁切、越界或截断；需要明确安全边距（safe margins）。

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
    "full subject in frame",
    "safe margins",
    "no edge cropping",
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

COMPOSITION_TERMS_ZH = ["特写", "微距", "广角", "45度", "俯视", "鸟瞰", "浅景深", "深景深", "三分构图", "完整入画", "安全边距", "不裁切"]
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
            "cropped plate edge",
            "cut-off garnish",
        ],
    },
    "logo_branding": {
        "keywords": ["logo", "标志", "品牌", "vi", "字体设计", "平面设计"],
        "preferred_styles": [
            "brand identity strategy",
            "high-end brand visual language",
            "logomark and logotype system",
            "typographic hierarchy and brand tone",
        ],
        "forbidden_styles": ["random generic icon style", "off-topic illustration scene", "unrelated photography scene"],
        "negative_focus": [
            "generic stock icon look",
            "inconsistent brand tone",
            "illegible brand name",
            "arbitrary decorative clutter",
            "style-topic mismatch",
            "cropped logo",
            "cut-off logotype",
            "truncated text",
        ],
    },
    "product": {
        "keywords": ["产品", "耳机", "手机", "电商", "包装", "product", "ecommerce"],
        "preferred_styles": ["studio product photography", "commercial catalog style", "clean background"],
        "forbidden_styles": ["fashion runway", "busy street scene"],
        "negative_focus": [
            "warped product geometry",
            "logo distortion",
            "dirty background",
            "random props",
            "object cut off at frame edge",
            "cropped product corners",
        ],
    },
    "tech": {
        "keywords": ["科技", "未来感", "芯片", "机器人", "赛博", "cyber", "tech", "futuristic"],
        "preferred_styles": ["futuristic product render", "high-tech industrial aesthetic", "precision hard-surface detailing"],
        "forbidden_styles": ["organic rustic style", "natural botanical scene", "food editorial"],
        "negative_focus": [
            "organic texture",
            "natural elements",
            "wood grain look",
            "soft handmade texture",
            "low-tech appearance",
            "cropped device body",
            "cut-off product silhouette",
        ],
    },
    "chinese_style": {
        "keywords": ["中国风", "国风", "水墨", "山水", "中式", "古风", "guochao", "ink wash", "shanshui"],
        "preferred_styles": ["ink wash aesthetics", "xuan paper texture", "traditional chinese composition", "seal red accents"],
        "forbidden_styles": ["editorial fashion", "cyberpunk neon tech", "western streetwear style"],
        "negative_focus": [
            "western architectural motifs",
            "latin typography",
            "modern corporate stock look",
            "plastic 3d effect",
            "cut-off calligraphy strokes",
            "cropped seal mark",
        ],
    },
    "interior": {
        "keywords": ["客厅", "室内", "家居", "interior", "living room", "bedroom"],
        "preferred_styles": ["interior photography", "architectural composition", "natural materials"],
        "forbidden_styles": ["editorial fashion", "macro product shot"],
        "negative_focus": [
            "distorted perspective",
            "tilted walls",
            "overexposure",
            "cluttered composition",
            "cropped furniture edges",
            "cut-off room boundaries",
        ],
    },
}

BRAND_DIRECTIONS = {
    "luxury": {
        "keywords": ["高端", "奢华", "高级", "premium", "luxury"],
        "zh_terms": ["奢雅品牌调性", "精致留白", "高级字体气质", "克制金属或深色点缀"],
        "en_terms": ["luxury brand tone", "refined negative space", "elegant typographic voice", "restrained metallic or deep-tone accents"],
        "negative": ["cheap luxury imitation", "over-ornamented decorations", "low-end retail vibe"],
    },
    "tech": {
        "keywords": ["科技", "未来", "智能", "ai", "tech", "futuristic"],
        "zh_terms": ["科技品牌识别", "理性几何秩序", "数字感字体", "精密但克制的视觉语法"],
        "en_terms": ["technology brand identity", "rational geometric order", "digital-forward typography", "precise yet restrained visual grammar"],
        "negative": ["organic rustic style", "handmade craft look", "retro vintage ornament"],
    },
    "chinese": {
        "keywords": ["中国风", "国风", "中式", "东方", "guochao"],
        "zh_terms": ["东方品牌语义", "书法或印章灵感", "中式留白与章法", "现代化国风识别"],
        "en_terms": ["eastern brand semantics", "calligraphic or seal-inspired accents", "chinese composition rhythm with negative space", "modern guochao identity"],
        "negative": ["western stock corporate style", "random latin-heavy symbolism", "over-westernized fashion tone"],
    },
    "young_playful": {
        "keywords": ["年轻", "潮流", "活力", "趣味", "youth", "playful"],
        "zh_terms": ["年轻化品牌语气", "高识别图形节奏", "明快配色策略", "可延展社媒应用"],
        "en_terms": ["youthful brand voice", "high-recognition graphic rhythm", "vibrant but controlled color strategy", "social-media-ready extensibility"],
        "negative": ["childish random doodles", "over-saturated chaotic palette", "poor scalability in small sizes"],
    },
    "default": {
        "keywords": [],
        "zh_terms": ["品牌战略一致性", "标志与字标协同", "跨触点可用的视觉系统", "清晰层级与可读性"],
        "en_terms": ["brand-strategy consistency", "logomark-logotype synergy", "cross-touchpoint visual system", "clear hierarchy and readability"],
        "negative": ["style without strategy", "pretty-but-off-brand design", "inconsistent identity components"],
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
    image_model: str = ""
    image_size: str = "1K"
    reference_image_data_url: str = ""


class TextToImageResponse(BaseModel):
    r2_key: str
    image_url: str
    aspect_ratio: str


app = FastAPI(title="Prompt2Image Pipeline")
app.include_router(ma_pipeline_router)
app.include_router(canvas_router)
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


def _infer_brand_direction(description: str) -> str:
    desc = description.lower()
    for name, profile in BRAND_DIRECTIONS.items():
        if name == "default":
            continue
        if any(k.lower() in desc for k in profile["keywords"]):
            return name
    return "default"


def _apply_brand_design_enhancement(prompt: str, negative: str, description: str, output_language: str) -> tuple[str, str]:
    direction = _infer_brand_direction(description)
    profile = BRAND_DIRECTIONS[direction]
    terms = profile["zh_terms"] if output_language == "zh" else profile["en_terms"]
    separator = "，" if output_language == "zh" else ", "

    has_brand_core = (
        ("品牌" in prompt or "brand" in prompt.lower())
        and ("字体" in prompt or "typography" in prompt.lower() or "logotype" in prompt.lower())
    )

    if not has_brand_core:
        brand_core = terms + (
            ["标志图形+字标系统", "多场景可用（名片/官网/包装）"]
            if output_language == "zh"
            else ["logomark + logotype system", "multi-touchpoint usage (website/business card/packaging)"]
        )
        prompt = f"{prompt}{separator}{separator.join(brand_core)}"
    else:
        missing_terms = [t for t in terms if t.lower() not in prompt.lower()]
        if missing_terms:
            prompt = f"{prompt}{separator}{separator.join(missing_terms[:2])}"

    # Avoid over-collapsing branding requests into one fixed "minimal flat vector" formula.
    if not _contains_any(description, ["极简", "minimal", "扁平", "flat", "几何", "geometric"]):
        remove_patterns = [
            r"\b2D flat vector graphic\b",
            r"\bminimal(?:ist)? geometric composition\b",
            r"\bflat graphic identity\b",
            r"\bminimal vector branding\b",
        ]
        for pat in remove_patterns:
            prompt = re.sub(pat, "", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\s*,\s*,+", ", ", prompt).strip(" ,")

    direction_negative = profile["negative"]
    if not _contains_any(negative, direction_negative):
        addon = separator.join(direction_negative)
        negative = f"{negative}{separator}{addon}" if negative else addon

    return prompt.strip(), negative.strip()


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
    framing_terms = ["完整入画", "安全边距", "不裁切"] if output_language == "zh" else ["full subject in frame", "safe margins", "no edge cropping"]
    has_framing = _contains_any(prompt, framing_terms)

    if not has_comp:
        prompt += "，三分构图，45度视角，浅景深" if output_language == "zh" else ", rule-of-thirds composition, 45-degree view, shallow depth of field"
        has_comp = True

    if not has_light:
        prompt += "，主光+补光，柔和棚拍光" if output_language == "zh" else ", soft studio key light with gentle fill light"
        has_light = True

    if not has_framing:
        prompt += "，主体完整入画，保留安全边距，不要贴边裁切" if output_language == "zh" else ", full subject in frame, keep safe margins, no edge cropping or truncation"
        has_framing = True

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

    crop_guard = "裁切, 越界, 截断, 出框, 贴边构图" if output_language == "zh" else "cropped, cut off, truncated text, out of frame, edge-clipped composition"
    if not _contains_any(negative, ["裁切", "越界", "截断", "cropped", "cut off", "truncated"]):
        negative = f"{negative}，{crop_guard}" if output_language == "zh" and negative else f"{negative}, {crop_guard}" if negative else crop_guard

    if category == "logo_branding":
        prompt, negative = _apply_brand_design_enhancement(prompt, negative, description, output_language)
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


def _ark_image_size(requested_size: str = "") -> str:
    size = (requested_size or "").strip().upper() or os.getenv("ARK_IMAGE_SIZE", "2K").strip().upper()
    return size if size in {"1K", "2K", "4K"} else "2K"


def _ratio_hint(aspect_ratio: str) -> str:
    ratio = aspect_ratio if aspect_ratio in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "1:1"
    return (
        f"MANDATORY OUTPUT RATIO: {ratio}. "
        "Keep full subject inside frame with safe margins and no edge cut-off."
    )


def _ark_size_by_ratio(aspect_ratio: str, requested_size: str) -> str:
    tier = _ark_image_size(requested_size)
    ratio = aspect_ratio if aspect_ratio in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "1:1"
    mapping = {
        "1K": {
            "1:1": "1024x1024",
            "16:9": "1344x768",
            "9:16": "768x1344",
            "4:3": "1152x864",
            "3:4": "864x1152",
        },
        "2K": {
            "1:1": "1536x1536",
            "16:9": "1792x1024",
            "9:16": "1024x1792",
            "4:3": "1792x1344",
            "3:4": "1344x1792",
        },
        "4K": {
            "1:1": "2048x2048",
            "16:9": "2560x1440",
            "9:16": "1440x2560",
            "4:3": "2560x1920",
            "3:4": "1920x2560",
        },
    }
    return mapping[tier][ratio]


async def generate_image_with_ark(
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "1:1",
    image_model: str = "",
    image_size: str = "2K",
    reference_image_data_url: str = "",
) -> tuple[str, str]:
    ark_api_key = _must_env("ARK_API_KEY")
    model_key = image_model.strip().lower()
    if model_key in {"ark-seedream-4.0", "seedream-4.0", "seedream4.0", "seedream4"}:
        endpoint_model = (
            os.getenv("ARK_SEEDREAM_MODEL", "").strip()
            or os.getenv("ARK_IMAGE_ENDPOINT_ID", "").strip()
            or "doubao-seedream-4-0-250828"
        )
    else:
        endpoint_model = (
            image_model.strip()
            or os.getenv("ARK_IMAGE_ENDPOINT_ID", "").strip()
            or os.getenv("ARK_SEEDREAM_MODEL", "").strip()
            or "doubao-seedream-4-0-250828"
        )
    ark_base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")

    ratio = aspect_ratio if aspect_ratio in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "1:1"
    merged_prompt = prompt.strip()
    merged_prompt += f"\n\n{_ratio_hint(ratio)}"
    if negative_prompt.strip():
        merged_prompt += f"\n\nAvoid: {negative_prompt.strip()}"

    payload = {
        "model": endpoint_model,
        "prompt": merged_prompt,
        "sequential_image_generation": "disabled",
        "response_format": "url",
        "size": _ark_size_by_ratio(ratio, image_size),
        "stream": False,
        "watermark": False,
    }
    reference_url = _resolve_ark_reference_image_url(reference_image_data_url)
    if reference_url:
        payload["image"] = reference_url

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

    return image_url, f"{ratio}@{payload['size']}"


def _apiyi_image_size(requested_size: str = "") -> str:
    size = (requested_size or "").strip().upper() or os.getenv("APIYI_IMAGE_SIZE", "1K").strip().upper()
    return size if size in {"1K", "2K", "4K"} else "2K"


def _parse_data_url_image(data_url: str) -> tuple[str, str]:
    """
    Parse data URL like: data:image/png;base64,xxxx
    Returns: (mime_type, base64_data)
    """
    val = (data_url or "").strip()
    if not val.startswith("data:") or ";base64," not in val:
        return "", ""
    header, b64 = val.split(";base64,", 1)
    mime = header.replace("data:", "").strip()
    if not mime or not b64:
        return "", ""
    return mime, b64.strip()


def _resolve_ark_reference_image_url(reference_image_data_url: str) -> str:
    val = (reference_image_data_url or "").strip()
    if not val:
        return ""
    if val.startswith("http://") or val.startswith("https://"):
        return val

    mime, b64 = _parse_data_url_image(val)
    if not (mime and b64):
        raise HTTPException(
            status_code=400,
            detail="ARK 图生图的参考图仅支持 http(s) URL 或 data:image/...;base64 格式",
        )

    try:
        image_bytes = base64.b64decode(b64, validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"参考图 base64 解析失败: {exc}") from exc

    try:
        _, public_url = upload_image_to_r2(image_bytes, mime)
        return public_url
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"参考图已上传但无法生成可访问URL，请检查 R2 配置: {exc}",
        ) from exc


async def generate_image_with_apiyi(
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "1:1",
    image_model: str = "",
    image_size: str = "1K",
    reference_image_data_url: str = "",
) -> tuple[str, str]:
    apiyi_api_key = _must_env("APIYI_API_KEY")
    model = image_model.strip() or os.getenv("APIYI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
    default_url = f"https://api.apiyi.com/v1beta/models/{model}:generateContent"
    configured_url = os.getenv("APIYI_IMAGE_URL", "").strip()
    if "{model}" in configured_url:
        api_url = configured_url.format(model=model)
    elif image_model.strip():
        api_url = default_url
    else:
        api_url = configured_url or default_url

    merged_prompt = prompt.strip()
    merged_prompt += f"\n\n{_ratio_hint(aspect_ratio)}"
    if negative_prompt.strip():
        merged_prompt += f"\n\nAvoid: {negative_prompt.strip()}"

    ratio = aspect_ratio if aspect_ratio in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "1:1"
    parts: list[dict[str, Any]] = []
    mime, b64 = _parse_data_url_image(reference_image_data_url)
    if mime and b64:
        parts.append({"inlineData": {"mimeType": mime, "data": b64}})
    parts.append({"text": merged_prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": ratio,
                "imageSize": _apiyi_image_size(image_size),
            },
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            api_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {apiyi_api_key}",
            },
            json=payload,
        )

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"APIYI image error: {resp.text}")

    data = resp.json()

    # Gemini-style payload (inlineData)
    candidates = data.get("candidates", [])
    for cand in candidates:
        content = cand.get("content", {})
        for part in content.get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data") or {}
            b64 = str(inline.get("data", "")).strip()
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png").strip()
            if b64:
                return f"data:{mime};base64,{b64}", f"{ratio}@{_apiyi_image_size(image_size)}"

    # OpenAI-style fallback (if provider returns a compatible envelope)
    for item in data.get("data", []):
        url = str(item.get("url", "")).strip()
        if url:
            return url, f"{ratio}@{_apiyi_image_size(image_size)}"
        b64 = str(item.get("b64_json", "")).strip()
        if b64:
            return f"data:image/png;base64,{b64}", f"{ratio}@{_apiyi_image_size(image_size)}"

    raise HTTPException(status_code=502, detail="APIYI image returned empty image data")


async def generate_image(
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "1:1",
    image_model: str = "",
    image_size: str = "1K",
    reference_image_data_url: str = "",
) -> tuple[str, str]:
    model_key = image_model.strip().lower()
    if model_key in {"ark-seedream-4.0", "seedream-4.0", "seedream4.0", "seedream4"}:
        return await generate_image_with_ark(
            prompt,
            negative_prompt,
            aspect_ratio,
            "ark-seedream-4.0",
            image_size,
            reference_image_data_url,
        )

    provider = os.getenv("IMAGE_PROVIDER", "apiyi").strip().lower()
    if provider == "ark":
        return await generate_image_with_ark(
            prompt,
            negative_prompt,
            aspect_ratio,
            image_model,
            image_size,
            reference_image_data_url,
        )
    return await generate_image_with_apiyi(
        prompt,
        negative_prompt,
        aspect_ratio,
        image_model,
        image_size,
        reference_image_data_url,
    )


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

    negative_prompt = str(optimized.get("negative_prompt", ""))
    image_url, _size = await generate_image(prompt, negative_prompt, req.aspect_ratio)
    provider = os.getenv("IMAGE_PROVIDER", "apiyi").strip().lower()
    r2_key = f"{provider}-direct"

    return PipelineResponse(
        optimized_prompt=prompt,
        negative_prompt=negative_prompt,
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
    image_url, _size = await generate_image(
        req.prompt.strip(),
        req.negative_prompt.strip(),
        req.aspect_ratio,
        req.image_model.strip(),
        req.image_size.strip(),
        req.reference_image_data_url.strip(),
    )
    provider = os.getenv("IMAGE_PROVIDER", "apiyi").strip().lower()
    return TextToImageResponse(r2_key=f"{provider}-direct", image_url=image_url, aspect_ratio=req.aspect_ratio)
