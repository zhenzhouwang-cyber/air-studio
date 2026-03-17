from __future__ import annotations

from typing import Any

from .agents import (
    CategoryPolicyAgent,
    ConstraintAgent,
    FinalizerAgent,
    InputAgent,
    IntentAgent,
    PromptDraftAgent,
    QAAgent,
    ReferenceAlignAgent,
)
from .category_catalog import CategoryCatalog
from .clients import ArkClient
from .config import LOG_FILE
from .logger import PipelineLogger, StepTimer
from .schemas import PipelineInput, PipelineOutput


class MultiAgentPromptPipeline:
    def __init__(self, catalog: CategoryCatalog | None = None) -> None:
        self.logger = PipelineLogger()
        self.catalog = catalog or CategoryCatalog()
        self.input_agent = InputAgent()
        self.intent_agent = IntentAgent(self.catalog)
        self.constraint_agent = ConstraintAgent()
        self.prompt_draft_agent = PromptDraftAgent(ArkClient())
        self.policy_agent = CategoryPolicyAgent(self.catalog)
        self.ref_align_agent = ReferenceAlignAgent()
        self.qa_agent = QAAgent(self.catalog)
        self.finalizer = FinalizerAgent()

    async def run(self, task_id: str, payload: PipelineInput) -> PipelineOutput:
        normalized = self._run_step(task_id, "InputAgent", payload.model_dump(), self.input_agent.run, payload.model_dump())
        intent = self._run_step(task_id, "IntentAgent", {"description": normalized["description"]}, self.intent_agent.run, normalized)
        constraints = self._run_step(task_id, "ConstraintAgent", {"category": intent["category"]}, self.constraint_agent.run, normalized)

        with StepTimer() as t:
            draft = await self.prompt_draft_agent.run(normalized, intent, constraints)
        self.logger.log_step(
            task_id=task_id,
            step="PromptDraftAgent",
            input_summary={"category": intent["category"], "description": normalized["description"][:120]},
            output_summary={"final_prompt": draft.get("final_prompt", "")[:220]},
            duration_ms=t.duration_ms,
        )

        refined = self._run_step(task_id, "CategoryPolicyAgent", {"category": intent["category"]}, self.policy_agent.run, draft, intent)
        aligned = self._run_step(
            task_id,
            "ReferenceAlignAgent",
            {"has_reference": bool(normalized.get("reference_image_url") or normalized.get("reference_image_data_url"))},
            self.ref_align_agent.run,
            refined,
            normalized,
        )

        qa = self._run_step(task_id, "QAAgent", {"category": intent["category"]}, self.qa_agent.run, aligned, intent["category"])
        final = self._run_step(
            task_id,
            "FinalizerAgent",
            {"category": intent["category"]},
            self.finalizer.run,
            aligned,
            intent["category"],
            qa,
            str(LOG_FILE),
        )
        return PipelineOutput(**final)

    def _run_step(
        self,
        task_id: str,
        step_name: str,
        input_summary: dict[str, Any],
        fn: Any,
        *args: Any,
    ) -> Any:
        try:
            with StepTimer() as t:
                out = fn(*args)
            self.logger.log_step(
                task_id=task_id,
                step=step_name,
                input_summary=input_summary,
                output_summary=out,
                duration_ms=t.duration_ms,
            )
            return out
        except Exception as exc:
            self.logger.log_step(
                task_id=task_id,
                step=step_name,
                input_summary=input_summary,
                output_summary={},
                duration_ms=0,
                error=str(exc),
            )
            raise
