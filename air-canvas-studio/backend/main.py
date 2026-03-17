from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

DATA_FILE = ROOT / "data" / "boards.json"
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AIR Canvas Studio API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ElementNode(BaseModel):
    id: str
    type: Literal["note", "text", "rect", "image", "line"] = "note"
    x: float
    y: float
    w: float = 320
    h: float = 220
    text: str = ""
    image_url: str = ""


class BoardViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1.0


class Board(BaseModel):
    id: str
    title: str = "Untitled"
    viewport: BoardViewport = Field(default_factory=BoardViewport)
    elements: list[ElementNode] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CreateBoardRequest(BaseModel):
    title: str = "Untitled"


class SaveBoardRequest(BaseModel):
    viewport: BoardViewport
    elements: list[ElementNode]


class CommandRequest(BaseModel):
    instruction: str = Field(min_length=1)
    reference_image_data_url: str = ""
    aspect_ratio: str = "1:1"
    image_size: str = "2K"
    image_model: str = ""


class CommandResponse(BaseModel):
    board_id: str
    optimized_prompt: str
    negative_prompt: str
    image_url: str
    added_element: ElementNode


class BoardStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._boards: dict[str, Board] = {}
        self._load()

    def create(self, title: str) -> Board:
        with self._lock:
            now = datetime.now(timezone.utc)
            b = Board(id=uuid.uuid4().hex, title=title.strip() or "Untitled", created_at=now, updated_at=now)
            self._boards[b.id] = b
            self._save_locked()
            return b

    def get(self, board_id: str) -> Board | None:
        with self._lock:
            return self._boards.get(board_id)

    def list(self) -> list[Board]:
        with self._lock:
            return sorted(self._boards.values(), key=lambda b: b.updated_at, reverse=True)

    def delete(self, board_id: str) -> None:
        with self._lock:
            if board_id not in self._boards:
                raise KeyError(board_id)
            del self._boards[board_id]
            self._save_locked()

    def save(self, board_id: str, viewport: BoardViewport, elements: list[ElementNode]) -> Board:
        with self._lock:
            b = self._boards.get(board_id)
            if not b:
                raise KeyError(board_id)
            b.viewport = viewport
            b.elements = elements
            b.updated_at = datetime.now(timezone.utc)
            self._save_locked()
            return b

    def append_element(self, board_id: str, element: ElementNode) -> Board:
        with self._lock:
            b = self._boards.get(board_id)
            if not b:
                raise KeyError(board_id)
            b.elements.append(element)
            b.updated_at = datetime.now(timezone.utc)
            self._save_locked()
            return b

    def _load(self) -> None:
        if not DATA_FILE.exists():
            self._save_locked()
            return
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            parsed: dict[str, Board] = {}
            for bid, node in raw.get("boards", {}).items():
                parsed[bid] = Board(**node)
            self._boards = parsed
        except Exception:
            self._boards = {}

    def _save_locked(self) -> None:
        payload = {"boards": {bid: b.model_dump(mode="json") for bid, b in self._boards.items()}}
        DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


store = BoardStore()


def _must(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise HTTPException(status_code=500, detail=f"Missing env: {name}")
    return val


def _ark_base() -> str:
    return os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")


def _ark_optimize_model() -> str:
    return os.getenv("ARK_ENDPOINT_ID", "").strip() or "ep-20260316165656-t858c"


def _ark_image_model() -> str:
    return os.getenv("ARK_SEEDREAM_MODEL", "").strip() or "doubao-seedream-4-0-250828"


def _size_for_ratio(aspect_ratio: str, image_size: str) -> str:
    tier = image_size.upper().strip() if image_size.upper().strip() in {"1K", "2K", "4K"} else "2K"
    ratio = aspect_ratio if aspect_ratio in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "1:1"
    table = {
        "1K": {"1:1": "1024x1024", "16:9": "1344x768", "9:16": "768x1344", "4:3": "1152x864", "3:4": "864x1152"},
        "2K": {"1:1": "1536x1536", "16:9": "1792x1024", "9:16": "1024x1792", "4:3": "1792x1344", "3:4": "1344x1792"},
        "4K": {"1:1": "2048x2048", "16:9": "2560x1440", "9:16": "1440x2560", "4:3": "2560x1920", "3:4": "1920x2560"},
    }
    return table[tier][ratio]


async def optimize_prompt(description: str) -> tuple[str, str]:
    api_key = _must("ARK_API_KEY")
    sys_prompt = (
        "You are a prompt optimizer for image generation. "
        "Return JSON only: {\"optimized_prompt\":\"...\",\"negative_prompt\":\"...\"}. "
        "Use English output. Keep strict requirement fidelity, include composition and lighting details."
    )
    payload = {
        "model": _ark_optimize_model(),
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": sys_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": description}]},
        ],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{_ark_base()}/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ARK optimize error: {r.text}")

    data = r.json()
    raw = ""
    for item in data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text" and part.get("text"):
                raw = str(part.get("text")).strip()
                break
        if raw:
            break
    if not raw:
        raise HTTPException(status_code=502, detail="ARK optimize empty response")

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]

    try:
        obj = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Optimize JSON parse failed: {exc}") from exc

    prompt = str(obj.get("optimized_prompt", "")).strip() or description.strip()
    negative = str(obj.get("negative_prompt", "")).strip()
    return prompt, negative


async def generate_image(
    prompt: str,
    negative_prompt: str,
    aspect_ratio: str,
    image_size: str,
    image_model: str = "",
) -> str:
    api_key = _must("ARK_API_KEY")
    merged = f"{prompt}\n\nMANDATORY OUTPUT RATIO: {aspect_ratio}. Keep full subject in frame with safe margins."
    if negative_prompt:
        merged += f"\n\nAvoid: {negative_prompt}"
    payload = {
        "model": image_model.strip() or _ark_image_model(),
        "prompt": merged,
        "sequential_image_generation": "disabled",
        "response_format": "url",
        "size": _size_for_ratio(aspect_ratio, image_size),
        "stream": False,
        "watermark": False,
    }
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{_ark_base()}/images/generations", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ARK image error: {r.text}")

    data = r.json()
    url = str((data.get("data") or [{}])[0].get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=502, detail="ARK image empty url")
    return url


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/canvas/boards")
def create_board(req: CreateBoardRequest) -> Board:
    return store.create(req.title)


@app.get("/api/canvas/boards")
def list_boards() -> list[Board]:
    return store.list()


@app.get("/api/canvas/boards/{board_id}")
def get_board(board_id: str) -> Board:
    b = store.get(board_id)
    if not b:
        raise HTTPException(status_code=404, detail="Board not found")
    return b


@app.delete("/api/canvas/boards/{board_id}")
def delete_board(board_id: str) -> dict[str, bool]:
    try:
        store.delete(board_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Board not found") from exc


@app.put("/api/canvas/boards/{board_id}")
def save_board(board_id: str, req: SaveBoardRequest) -> Board:
    try:
        return store.save(board_id, req.viewport, req.elements)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Board not found") from exc


@app.post("/api/canvas/boards/{board_id}/command", response_model=CommandResponse)
async def run_command(board_id: str, req: CommandRequest) -> CommandResponse:
    if not store.get(board_id):
        raise HTTPException(status_code=404, detail="Board not found")

    optimized_prompt, negative_prompt = await optimize_prompt(req.instruction)
    image_url = await generate_image(
        optimized_prompt,
        negative_prompt,
        req.aspect_ratio,
        req.image_size,
        req.image_model,
    )

    element = ElementNode(
        id=uuid.uuid4().hex,
        type="image",
        x=180,
        y=140,
        w=520 if req.aspect_ratio == "16:9" else 420,
        h=292 if req.aspect_ratio == "16:9" else 420,
        text="",
        image_url=image_url,
    )
    store.append_element(board_id, element)

    return CommandResponse(
        board_id=board_id,
        optimized_prompt=optimized_prompt,
        negative_prompt=negative_prompt,
        image_url=image_url,
        added_element=element,
    )
