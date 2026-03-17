from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, ensure_dirs
from .schemas import TaskRecord


class TaskStore:
    def __init__(self) -> None:
        ensure_dirs()
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}

    def _task_path(self, task_id: str) -> Path:
        return DATA_DIR / f"{task_id}.json"

    def create(self, payload: dict[str, Any]) -> TaskRecord:
        with self._lock:
            now = datetime.now(timezone.utc)
            task = TaskRecord(
                task_id=uuid.uuid4().hex,
                status="queued",
                created_at=now,
                updated_at=now,
                input=payload,
            )
            self._tasks[task.task_id] = task
            self._save(task)
            return task

    def update(self, task_id: str, **changes: Any) -> TaskRecord:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                task = self._load_from_file(task_id)
            if task is None:
                raise KeyError(f"Task not found: {task_id}")
            current = task.model_dump()
            current.update(changes)
            current["updated_at"] = datetime.now(timezone.utc)
            new_task = TaskRecord(**current)
            self._tasks[task_id] = new_task
            self._save(new_task)
            return new_task

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id]
            task = self._load_from_file(task_id)
            if task is not None:
                self._tasks[task_id] = task
            return task

    def _save(self, task: TaskRecord) -> None:
        ensure_dirs()
        self._task_path(task.task_id).write_text(
            json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_from_file(self, task_id: str) -> TaskRecord | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return TaskRecord(**raw)
        except Exception:
            return None
