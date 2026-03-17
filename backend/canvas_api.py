from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .ma_pipeline.orchestrator import MultiAgentPromptPipeline
from .ma_pipeline.schemas import PipelineInput

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_DATA_FILE = PROJECT_ROOT / "data" / "canvas_boards.json"

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


class CanvasElement(BaseModel):
    id: str
    type: Literal["note", "image", "shape"] = "note"
    x: float = 0
    y: float = 0
    w: float = 260
    h: float = 160
    content: str = ""
    image_url: str = ""


class CanvasViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1.0


class CanvasBoard(BaseModel):
    id: str
    title: str = "Untitled"
    created_at: datetime
    updated_at: datetime
    viewport: CanvasViewport = Field(default_factory=CanvasViewport)
    elements: list[CanvasElement] = Field(default_factory=list)
    command_history: list[dict[str, Any]] = Field(default_factory=list)


class CreateBoardRequest(BaseModel):
    title: str = "Untitled"


class SaveBoardRequest(BaseModel):
    viewport: CanvasViewport
    elements: list[CanvasElement]


class RunCommandRequest(BaseModel):
    instruction: str = Field(min_length=1)
    reference_image_data_url: str = ""
    reference_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    image_size: str = "1K"
    style_strength: str = "medium"


class RunCommandResponse(BaseModel):
    board_id: str
    command_id: str
    optimized_prompt: str
    negative_prompt: str
    category: str
    score: int
    suggested_element: CanvasElement


class CanvasStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._boards: dict[str, CanvasBoard] = {}
        self._load()

    def create_board(self, title: str) -> CanvasBoard:
        with self._lock:
            now = datetime.now(timezone.utc)
            board = CanvasBoard(id=uuid.uuid4().hex, title=title.strip() or "Untitled", created_at=now, updated_at=now)
            self._boards[board.id] = board
            self._save_locked()
            return board

    def list_boards(self) -> list[CanvasBoard]:
        with self._lock:
            return sorted(self._boards.values(), key=lambda b: b.updated_at, reverse=True)

    def get_board(self, board_id: str) -> CanvasBoard | None:
        with self._lock:
            return self._boards.get(board_id)

    def save_board(self, board_id: str, viewport: CanvasViewport, elements: list[CanvasElement]) -> CanvasBoard:
        with self._lock:
            board = self._boards.get(board_id)
            if board is None:
                raise KeyError(board_id)
            board.viewport = viewport
            board.elements = elements
            board.updated_at = datetime.now(timezone.utc)
            self._save_locked()
            return board

    def append_command(self, board_id: str, record: dict[str, Any], suggested: CanvasElement) -> CanvasBoard:
        with self._lock:
            board = self._boards.get(board_id)
            if board is None:
                raise KeyError(board_id)
            board.command_history.append(record)
            board.elements.append(suggested)
            board.updated_at = datetime.now(timezone.utc)
            self._save_locked()
            return board

    def _load(self) -> None:
        CANVAS_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not CANVAS_DATA_FILE.exists():
            self._save_locked()
            return
        try:
            raw = json.loads(CANVAS_DATA_FILE.read_text(encoding="utf-8"))
            boards = raw.get("boards", {}) if isinstance(raw, dict) else {}
            parsed: dict[str, CanvasBoard] = {}
            for bid, node in boards.items():
                parsed[bid] = CanvasBoard(**node)
            self._boards = parsed
        except Exception:
            self._boards = {}

    def _save_locked(self) -> None:
        payload = {"boards": {bid: board.model_dump(mode="json") for bid, board in self._boards.items()}}
        CANVAS_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        CANVAS_DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


store = CanvasStore()
pipeline = MultiAgentPromptPipeline()


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/boards")
def list_boards() -> list[CanvasBoard]:
    return store.list_boards()


@router.post("/boards")
def create_board(req: CreateBoardRequest) -> CanvasBoard:
    return store.create_board(req.title)


@router.get("/boards/{board_id}")
def get_board(board_id: str) -> CanvasBoard:
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@router.put("/boards/{board_id}")
def save_board(board_id: str, req: SaveBoardRequest) -> CanvasBoard:
    try:
        return store.save_board(board_id, req.viewport, req.elements)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Board not found") from exc


@router.post("/boards/{board_id}/commands", response_model=RunCommandResponse)
async def run_command(board_id: str, req: RunCommandRequest) -> RunCommandResponse:
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    task_input = PipelineInput(
        description=req.instruction,
        reference_image_data_url=req.reference_image_data_url,
        reference_weight=req.reference_weight,
        image_size=req.image_size,
        style_strength=req.style_strength,
    )
    result = await pipeline.run(task_id=f"canvas-{uuid.uuid4().hex}", payload=task_input)

    command_id = uuid.uuid4().hex
    suggested = CanvasElement(
        id=uuid.uuid4().hex,
        type="note",
        x=120,
        y=120,
        w=420,
        h=220,
        content=f"Prompt:\n{result.final_prompt}\n\nNegative:\n{result.negative_prompt}",
    )
    record = {
        "id": command_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instruction": req.instruction,
        "optimized_prompt": result.final_prompt,
        "negative_prompt": result.negative_prompt,
        "category": result.category,
        "score": result.qa_report.score,
    }
    store.append_command(board_id, record, suggested)

    return RunCommandResponse(
        board_id=board_id,
        command_id=command_id,
        optimized_prompt=result.final_prompt,
        negative_prompt=result.negative_prompt,
        category=result.category,
        score=result.qa_report.score,
        suggested_element=suggested,
    )
