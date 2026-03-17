from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from .config import LOG_FILE, ensure_dirs


class PipelineLogger:
    def __init__(self) -> None:
        ensure_dirs()

    def log_step(
        self,
        *,
        task_id: str,
        step: str,
        input_summary: Any,
        output_summary: Any,
        duration_ms: int,
        error: str = "",
    ) -> None:
        ensure_dirs()
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "step": step,
            "input": input_summary,
            "output": output_summary,
            "duration_ms": duration_ms,
            "error": error,
        }
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


class StepTimer:
    def __enter__(self) -> "StepTimer":
        self.start = time.perf_counter()
        self.duration_ms = 0
        return self

    def __exit__(self, *_: object) -> None:
        self.duration_ms = int((time.perf_counter() - self.start) * 1000)
