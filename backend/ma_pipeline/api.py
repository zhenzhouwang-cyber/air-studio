from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from .category_catalog import CategoryCatalog
from .orchestrator import MultiAgentPromptPipeline
from .clients import ArkClient
from .schemas import (
    AsyncRunResponse,
    CategoryListResponse,
    CategoryRefreshResponse,
    PipelineInput,
    SyncRunResponse,
    TaskResultResponse,
)
from .store import TaskStore

router = APIRouter(prefix="/api/ma-pipeline", tags=["ma-pipeline"])
store = TaskStore()
catalog = CategoryCatalog()
pipeline = MultiAgentPromptPipeline(catalog)


@router.post("/run-sync", response_model=SyncRunResponse)
async def run_sync(req: PipelineInput) -> SyncRunResponse:
    task = store.create(req.model_dump())
    store.update(task.task_id, status="running")
    try:
        result = await pipeline.run(task.task_id, req)
    except Exception as exc:
        store.update(task.task_id, status="failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    store.update(task.task_id, status="completed", result=result.model_dump())
    return SyncRunResponse(task_id=task.task_id, status="completed", result=result)


@router.post("/run-async", response_model=AsyncRunResponse)
async def run_async(req: PipelineInput) -> AsyncRunResponse:
    task = store.create(req.model_dump())

    async def worker() -> None:
        store.update(task.task_id, status="running")
        try:
            result = await pipeline.run(task.task_id, req)
            store.update(task.task_id, status="completed", result=result.model_dump())
        except Exception as exc:
            store.update(task.task_id, status="failed", error=str(exc))

    asyncio.create_task(worker())
    return AsyncRunResponse(task_id=task.task_id, status="queued")


@router.get("/result/{task_id}", response_model=TaskResultResponse)
def get_result(task_id: str) -> TaskResultResponse:
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResultResponse(**task.model_dump())


@router.post("/categories/refresh", response_model=CategoryRefreshResponse)
async def refresh_categories() -> CategoryRefreshResponse:
    try:
        result = await catalog.refresh_with_ai(ArkClient())
        return CategoryRefreshResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/categories", response_model=CategoryListResponse)
def list_categories() -> CategoryListResponse:
    return CategoryListResponse(categories=catalog.list_categories())
