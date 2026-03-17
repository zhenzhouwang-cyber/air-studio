from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .config import ark_base_url, ark_model


class ArkClient:
    async def optimize_prompt(self, user_instruction: str, system_prompt: str) -> dict[str, Any]:
        api_key = os.getenv("ARK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Missing ARK_API_KEY")

        payload = {
            "model": ark_model(),
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_instruction}],
                },
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{ark_base_url()}/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )

        if resp.status_code >= 400:
            raise RuntimeError(f"ARK responses error: {resp.text}")

        data = resp.json()
        text = _extract_output_text(data)
        try:
            return _extract_json(text)
        except Exception as exc:
            raise RuntimeError(f"Failed to parse LLM JSON: {exc}; raw={text[:500]}") from exc


def _extract_output_text(data: dict[str, Any]) -> str:
    out = data.get("output", [])
    for item in out:
        for c in item.get("content", []):
            if c.get("type") == "output_text" and c.get("text"):
                return str(c.get("text")).strip()
    return ""


def _extract_json(raw: str) -> dict[str, Any]:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt.replace("json", "", 1).strip()

    start = txt.find("{")
    end = txt.rfind("}")
    if start >= 0 and end > start:
        txt = txt[start : end + 1]
    return json.loads(txt)
