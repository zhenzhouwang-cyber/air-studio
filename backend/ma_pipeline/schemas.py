from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PipelineInput(BaseModel):
    description: str = Field(min_length=1)
    reference_image_url: str = ""
    reference_image_data_url: str = ""
    reference_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    aspect_ratio_hint: str = ""
    image_size: str = "1K"
    style_strength: str = "medium"
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QAReport(BaseModel):
    has_composition_terms: bool
    has_lighting_terms: bool
    style_matches_category: bool
    negative_prompt_specific: bool
    score: int
    notes: list[str] = Field(default_factory=list)


class PipelineOutput(BaseModel):
    final_prompt: str
    negative_prompt: str
    aspect_ratio: str
    image_size: str
    style_strength: str
    camera: str
    lighting: str
    composition: str
    seed: int | None = None
    category: str
    qa_report: QAReport
    debug_trace_path: str


class SyncRunResponse(BaseModel):
    task_id: str
    status: Literal["completed"]
    result: PipelineOutput


class AsyncRunResponse(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]


class CategoryRefreshResponse(BaseModel):
    categories_total: int
    updated_categories: int
    new_categories: int
    file_path: str


class CategoryListResponse(BaseModel):
    categories: list[str]


class TaskRecord(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: datetime
    updated_at: datetime
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str = ""


class TaskResultResponse(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None
    error: str = ""
