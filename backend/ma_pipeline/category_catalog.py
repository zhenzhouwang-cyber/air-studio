from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .clients import ArkClient
from .config import CATEGORY_LIBRARY_FILE, DEFAULT_CATEGORY_LIBRARY, ensure_dirs


class CategoryCatalog:
    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path or CATEGORY_LIBRARY_FILE
        self._lock = threading.Lock()
        self._library: dict[str, dict[str, list[str]]] = {}
        self._load_or_init()

    def list_categories(self) -> list[str]:
        with self._lock:
            return list(self._library.keys())

    def keywords_map(self) -> dict[str, list[str]]:
        with self._lock:
            return {k: list(v.get("keywords", [])) for k, v in self._library.items()}

    def negative_patch_map(self) -> dict[str, list[str]]:
        with self._lock:
            return {k: list(v.get("negative_patch", [])) for k, v in self._library.items()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {k: {"keywords": list(v.get("keywords", [])), "negative_patch": list(v.get("negative_patch", []))} for k, v in self._library.items()}

    async def refresh_with_ai(self, ark_client: ArkClient) -> dict[str, Any]:
        current = self.snapshot()
        system_prompt = """
You are an image prompt taxonomy expert.
Expand and refine category library for text-to-image prompt engineering.
Return JSON only with shape:
{
  "categories": [
    {
      "name": "category name in Chinese",
      "keywords": ["keyword1", "keyword2"],
      "negative_patch": ["english negative token 1", "english negative token 2"]
    }
  ]
}
Rules:
- Keep original categories and enrich them.
- You may add useful new categories.
- keywords should be Chinese terms for intent classification.
- negative_patch should be English prompt negatives, category-specific, concise.
- each list length: 6~20.
""".strip()

        user_instruction = json.dumps(
            {
                "current_categories": current,
                "goal": "expand with practical categories and stronger keyword/negative coverage",
            },
            ensure_ascii=False,
        )
        data = await ark_client.optimize_prompt(user_instruction=user_instruction, system_prompt=system_prompt)
        rows = data.get("categories", []) if isinstance(data, dict) else []
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Category refresh returned empty categories")

        new_count = 0
        updated_count = 0
        with self._lock:
            for row in rows:
                name = str((row or {}).get("name", "")).strip()
                if not name:
                    continue
                keywords = _uniq_str_list((row or {}).get("keywords", []))
                negatives = _uniq_str_list((row or {}).get("negative_patch", []))
                if not keywords:
                    continue

                if name not in self._library:
                    self._library[name] = {"keywords": keywords, "negative_patch": negatives}
                    new_count += 1
                    continue

                old = self._library[name]
                merged_keywords = _merge_list(old.get("keywords", []), keywords)
                merged_negatives = _merge_list(old.get("negative_patch", []), negatives)
                if merged_keywords != old.get("keywords", []) or merged_negatives != old.get("negative_patch", []):
                    updated_count += 1
                self._library[name] = {"keywords": merged_keywords, "negative_patch": merged_negatives}

            self._save_locked()

        return {
            "categories_total": len(self._library),
            "updated_categories": updated_count,
            "new_categories": new_count,
            "file_path": str(self.file_path),
        }

    def _load_or_init(self) -> None:
        ensure_dirs()
        if not self.file_path.exists():
            with self._lock:
                self._library = {
                    k: {
                        "keywords": list(v.get("keywords", [])),
                        "negative_patch": list(v.get("negative_patch", [])),
                    }
                    for k, v in DEFAULT_CATEGORY_LIBRARY.items()
                }
                self._save_locked()
            return

        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            categories = raw.get("categories", {}) if isinstance(raw, dict) else {}
            parsed: dict[str, dict[str, list[str]]] = {}
            for name, node in categories.items():
                n = str(name).strip()
                if not n:
                    continue
                parsed[n] = {
                    "keywords": _uniq_str_list((node or {}).get("keywords", [])),
                    "negative_patch": _uniq_str_list((node or {}).get("negative_patch", [])),
                }
            with self._lock:
                self._library = parsed or {
                    k: {
                        "keywords": list(v.get("keywords", [])),
                        "negative_patch": list(v.get("negative_patch", [])),
                    }
                    for k, v in DEFAULT_CATEGORY_LIBRARY.items()
                }
                self._save_locked()
        except Exception:
            with self._lock:
                self._library = {
                    k: {
                        "keywords": list(v.get("keywords", [])),
                        "negative_patch": list(v.get("negative_patch", [])),
                    }
                    for k, v in DEFAULT_CATEGORY_LIBRARY.items()
                }
                self._save_locked()

    def _save_locked(self) -> None:
        payload = {
            "categories": self._library,
        }
        self.file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _uniq_str_list(items: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(items, list):
        return out
    for x in items:
        val = str(x).strip()
        if not val:
            continue
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(val)
    return out


def _merge_list(a: list[str], b: list[str]) -> list[str]:
    merged = list(a)
    seen = {x.lower() for x in merged}
    for x in b:
        if x.lower() not in seen:
            seen.add(x.lower())
            merged.append(x)
    return merged
