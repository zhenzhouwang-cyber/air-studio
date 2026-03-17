from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "tasks"
CATEGORY_LIBRARY_FILE = PROJECT_ROOT / "data" / "categories.json"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "pipeline.log"

DEFAULT_CATEGORIES = [
    "品牌设计",
    "食品",
    "科技产品",
    "中国风",
    "室内空间",
    "人像",
    "海报KV",
]

CATEGORY_KEYWORDS = {
    "品牌设计": ["品牌", "logo", "标志", "vi", "品牌设计", "品牌视觉"],
    "食品": ["食品", "美食", "饮料", "餐", "甜点", "咖啡", "蛋糕"],
    "科技产品": ["科技", "产品", "硬朗", "未来", "工业", "金属"],
    "中国风": ["中国风", "国潮", "水墨", "山水", "书法", "东方"],
    "室内空间": ["室内", "空间", "家居", "客厅", "卧室", "建筑内"],
    "人像": ["人像", "人物", "肖像", "模特", "面部"],
    "海报KV": ["海报", "kv", "主视觉", "广告图", "活动图"],
}

CATEGORY_NEGATIVE_PATCH = {
    "食品": ["plastic look", "artificial color cast", "unappetizing texture", "burnt edges"],
    "科技产品": ["organic texture", "natural wood grain", "rustic decor", "soft handmade look"],
    "品牌设计": ["photorealistic scene", "messy layout", "illegible typography", "overly decorative clutter"],
    "中国风": ["cyberpunk neon overload", "western streetwear tone", "random latin typography"],
    "室内空间": ["distorted perspective", "floating furniture", "broken architecture", "excessive fisheye"],
    "人像": ["deformed face", "extra fingers", "asymmetric eyes", "plastic skin"],
    "海报KV": ["text cutoff", "subject out of frame", "weak hierarchy", "visual clutter"],
}

DEFAULT_CATEGORY_LIBRARY = {
    category: {
        "keywords": CATEGORY_KEYWORDS.get(category, []),
        "negative_patch": CATEGORY_NEGATIVE_PATCH.get(category, []),
    }
    for category in DEFAULT_CATEGORIES
}

COMPOSITION_TERMS = [
    "close-up",
    "medium shot",
    "wide shot",
    "top-down",
    "45-degree",
    "rule of thirds",
    "safe margins",
    "full subject in frame",
    "depth of field",
]

LIGHTING_TERMS = [
    "key light",
    "fill light",
    "rim light",
    "backlight",
    "soft diffused",
    "studio lighting",
    "high contrast",
    "warm tones",
]

VALID_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4"}
VALID_IMAGE_SIZES = {"1K", "2K", "4K"}
VALID_STYLE_STRENGTH = {"low", "medium", "high"}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CATEGORY_LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def ark_base_url() -> str:
    return os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")


def ark_model() -> str:
    return (
        os.getenv("ARK_ENDPOINT_ID", "").strip()
        or os.getenv("ARK_PROMPT_MODEL", "").strip()
        or "ep-20260316165656-t858c"
    )
