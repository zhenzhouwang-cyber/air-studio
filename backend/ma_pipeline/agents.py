from __future__ import annotations

from typing import Any

from .clients import ArkClient
from .category_catalog import CategoryCatalog
from .config import (
    COMPOSITION_TERMS,
    LIGHTING_TERMS,
    VALID_ASPECT_RATIOS,
    VALID_IMAGE_SIZES,
    VALID_STYLE_STRENGTH,
)


class InputAgent:
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        description = str(payload.get("description", "")).strip()
        if not description:
            raise ValueError("description is required")

        style_strength = str(payload.get("style_strength", "medium")).lower().strip() or "medium"
        if style_strength not in VALID_STYLE_STRENGTH:
            style_strength = "medium"

        image_size = str(payload.get("image_size", "1K")).upper().strip() or "1K"
        if image_size not in VALID_IMAGE_SIZES:
            image_size = "1K"

        reference_weight = float(payload.get("reference_weight", 0.7))
        reference_weight = min(1.0, max(0.0, reference_weight))

        return {
            "description": description,
            "reference_image_url": str(payload.get("reference_image_url", "")).strip(),
            "reference_image_data_url": str(payload.get("reference_image_data_url", "")).strip(),
            "reference_weight": reference_weight,
            "aspect_ratio_hint": str(payload.get("aspect_ratio_hint", "")).strip(),
            "image_size": image_size,
            "style_strength": style_strength,
            "seed": payload.get("seed"),
            "metadata": payload.get("metadata") or {},
        }


class IntentAgent:
    def __init__(self, catalog: CategoryCatalog) -> None:
        self.catalog = catalog

    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        text = ctx["description"]
        lower_text = text.lower()
        matched = "海报KV"
        hit_count = 0
        for category, keywords in self.catalog.keywords_map().items():
            hits = sum(1 for kw in keywords if kw.lower() in lower_text)
            if hits > hit_count:
                matched = category
                hit_count = hits
        if hit_count == 0:
            matched = "海报KV"
        return {"category": matched, "subject_focus": text[:80], "risk_flags": []}


class ConstraintAgent:
    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        constraints = [
            "Strictly preserve all user-requested core elements.",
            "Do not change subject category or scene semantics.",
            "Keep full subject in frame with safe margins and no edge cut-off.",
            "Use explicit camera/composition/lighting language.",
            "Output in English only.",
        ]
        return {"hard_constraints": constraints}


class PromptDraftAgent:
    def __init__(self, ark_client: ArkClient) -> None:
        self.ark_client = ark_client

    async def run(self, ctx: dict[str, Any], intent: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        system_prompt = """
You are a senior image prompt engineer for Nano Banana 2.
Return strict JSON only with fields:
final_prompt, negative_prompt, aspect_ratio, image_size, style_strength, camera, lighting, composition, seed.
Rules:
- English output only.
- Prioritize strict requirement fidelity over creativity.
- Include camera, composition, lighting terms explicitly.
- Keep subject fully in frame and mention safe margins.
- aspect_ratio must be one of: 1:1,16:9,9:16,4:3,3:4.
- image_size must be one of: 1K,2K,4K.
- style_strength must be one of: low,medium,high.
""".strip()

        user_instruction = {
            "description_zh": ctx["description"],
            "category": intent["category"],
            "constraints": constraints["hard_constraints"],
            "aspect_ratio_hint": ctx.get("aspect_ratio_hint", ""),
            "image_size": ctx.get("image_size", "1K"),
            "style_strength": ctx.get("style_strength", "medium"),
            "seed": ctx.get("seed"),
        }
        draft = await self.ark_client.optimize_prompt(str(user_instruction), system_prompt)

        aspect_ratio = str(draft.get("aspect_ratio", "1:1"))
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            aspect_ratio = "1:1"
        image_size = str(draft.get("image_size", ctx.get("image_size", "1K"))).upper()
        if image_size not in VALID_IMAGE_SIZES:
            image_size = "1K"
        style_strength = str(draft.get("style_strength", ctx.get("style_strength", "medium"))).lower()
        if style_strength not in VALID_STYLE_STRENGTH:
            style_strength = "medium"

        return {
            "final_prompt": str(draft.get("final_prompt", "")).strip(),
            "negative_prompt": str(draft.get("negative_prompt", "")).strip(),
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "style_strength": style_strength,
            "camera": str(draft.get("camera", "")).strip() or "medium shot",
            "lighting": str(draft.get("lighting", "")).strip() or "studio key light + gentle fill",
            "composition": str(draft.get("composition", "")).strip() or "rule of thirds, safe margins",
            "seed": draft.get("seed", ctx.get("seed")),
        }


class CategoryPolicyAgent:
    def __init__(self, catalog: CategoryCatalog) -> None:
        self.catalog = catalog

    def run(self, draft: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        category = intent["category"]
        patch = self.catalog.negative_patch_map().get(category, [])
        negative = draft.get("negative_prompt", "")
        items = [x.strip() for x in negative.split(",") if x.strip()]
        for p in patch:
            if p not in items:
                items.append(p)
        draft["negative_prompt"] = ", ".join(items)
        return draft


class ReferenceAlignAgent:
    def run(self, draft: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        has_ref = bool(ctx.get("reference_image_url") or ctx.get("reference_image_data_url"))
        if not has_ref:
            return draft
        weight = ctx.get("reference_weight", 0.7)
        addition = (
            f" Maintain structural and stylistic alignment with reference image at weight {weight:.2f}, "
            "while preserving all requested content."
        )
        draft["final_prompt"] = (draft.get("final_prompt", "") + addition).strip()
        return draft


class QAAgent:
    def __init__(self, catalog: CategoryCatalog) -> None:
        self.catalog = catalog

    def run(self, result: dict[str, Any], category: str) -> dict[str, Any]:
        prompt = (result.get("final_prompt", "") + " " + result.get("composition", "") + " " + result.get("camera", "") + " " + result.get("lighting", "")).lower()
        negative = str(result.get("negative_prompt", "")).lower()

        has_composition = any(t.lower() in prompt for t in COMPOSITION_TERMS)
        has_lighting = any(t.lower() in prompt for t in LIGHTING_TERMS)

        style_ok = True
        if category == "食品" and "editorial fashion" in prompt:
            style_ok = False
        if category == "科技产品" and "rustic" in prompt:
            style_ok = False

        category_patch = self.catalog.negative_patch_map().get(category, [])
        negative_specific = any(p.lower() in negative for p in category_patch) if category_patch else len(negative) > 15

        score = 100
        notes: list[str] = []
        if not has_composition:
            score -= 20
            notes.append("Missing composition tokens")
        if not has_lighting:
            score -= 20
            notes.append("Missing lighting tokens")
        if not style_ok:
            score -= 30
            notes.append("Style and category mismatch")
        if not negative_specific:
            score -= 20
            notes.append("Negative prompt lacks category specificity")

        return {
            "has_composition_terms": has_composition,
            "has_lighting_terms": has_lighting,
            "style_matches_category": style_ok,
            "negative_prompt_specific": negative_specific,
            "score": max(0, score),
            "notes": notes,
        }


class FinalizerAgent:
    def run(self, result: dict[str, Any], category: str, qa: dict[str, Any], trace_path: str) -> dict[str, Any]:
        return {
            "final_prompt": result["final_prompt"],
            "negative_prompt": result["negative_prompt"],
            "aspect_ratio": result["aspect_ratio"],
            "image_size": result["image_size"],
            "style_strength": result["style_strength"],
            "camera": result["camera"],
            "lighting": result["lighting"],
            "composition": result["composition"],
            "seed": result.get("seed"),
            "category": category,
            "qa_report": qa,
            "debug_trace_path": trace_path,
        }
