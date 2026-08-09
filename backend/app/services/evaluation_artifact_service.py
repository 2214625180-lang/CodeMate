import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.sensitive_data import redact_timeline_payload
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.evaluation import Evaluation
from app.models.evaluation_run import EvaluationRun


class EvaluationArtifactService:
    def __init__(self, db: Session):
        self.db = db

    def build_run_artifact(
        self,
        evaluation_run_id: str,
        *,
        include_agent_steps: bool = True,
        max_payload_chars: int = 12000,
    ) -> dict:
        run = self.db.get(
            EvaluationRun,
            evaluation_run_id,
            options=[selectinload(EvaluationRun.results)],
        )
        if run is None:
            raise FileNotFoundError("Evaluation run not found")

        agent_runs = self._agent_runs(run.results) if include_agent_steps else {}
        cases = [
            self._case_artifact(
                result,
                agent_run=agent_runs.get(result.agent_run_id or ""),
                include_agent_steps=include_agent_steps,
                max_payload_chars=max_payload_chars,
            )
            for result in run.results
        ]

        return {
            "artifact_version": "eval-run-artifact/v1",
            "generated_at": datetime.now(timezone.utc),
            "run": self._run_metadata(run),
            "summary": self._summary(run, cases),
            "cases": cases,
        }

    def _agent_runs(self, results: list[Evaluation]) -> dict[str, AgentRun]:
        agent_run_ids = sorted({result.agent_run_id for result in results if result.agent_run_id})
        if not agent_run_ids:
            return {}

        statement = (
            select(AgentRun)
            .options(selectinload(AgentRun.steps))
            .where(AgentRun.id.in_(agent_run_ids))
        )
        runs = self.db.execute(statement).scalars().all()
        return {run.id: run for run in runs}

    def _run_metadata(self, run: EvaluationRun) -> dict:
        return {
            "id": run.id,
            "name": run.name,
            "task_type": run.task_type,
            "status": run.status,
            "dataset_id": run.dataset_id,
            "dataset_version": run.dataset_version,
            "dataset_snapshot_id": run.dataset_snapshot_id,
            "case_count": run.case_count,
            "passed_count": run.passed_count,
            "failed_count": run.failed_count,
            "metrics_json": run.metrics_json,
            "config_snapshot": run.config_snapshot,
            "request_json": run.request_json,
            "created_at": run.created_at,
            "finished_at": run.finished_at,
        }

    def _case_artifact(
        self,
        result: Evaluation,
        *,
        agent_run: AgentRun | None,
        include_agent_steps: bool,
        max_payload_chars: int,
    ) -> dict:
        return {
            "evaluation_id": result.id,
            "case_id": result.case_id,
            "repo_id": result.repo_id,
            "task_type": result.task_type,
            "prompt": result.question,
            "expected_file": result.expected_file,
            "expected_lines": result.expected_lines,
            "status": result.status,
            "passed": result.passed,
            "score": result.score,
            "latency_ms": result.latency_ms,
            "failure_category": result.failure_category,
            "provider": result.provider,
            "model": result.model,
            "metadata_json": result.metadata_json or {},
            "result_json": self._bounded_payload(result.result_json, max_payload_chars),
            "agent_trace": self._agent_trace(
                agent_run,
                include_steps=include_agent_steps,
                max_payload_chars=max_payload_chars,
            ),
        }

    def _agent_trace(
        self,
        agent_run: AgentRun | None,
        *,
        include_steps: bool,
        max_payload_chars: int,
    ) -> dict | None:
        if agent_run is None:
            return None

        steps = agent_run.steps if include_steps else []
        return {
            "run_id": agent_run.id,
            "status": agent_run.status,
            "user_input": agent_run.user_input,
            "test_command": agent_run.test_command,
            "iterations": agent_run.iterations,
            "final_summary": agent_run.final_summary,
            "failure_reason": agent_run.failure_reason,
            "test_result": self._bounded_payload(agent_run.test_result, max_payload_chars),
            "steps_by_type": dict(Counter(step.step_type for step in agent_run.steps)),
            "steps": [
                self._step_artifact(step, max_payload_chars=max_payload_chars)
                for step in steps
            ],
        }

    def _step_artifact(self, step: AgentStep, *, max_payload_chars: int) -> dict:
        input_json, input_classification = redact_timeline_payload(step.input_json)
        output_json, output_classification = redact_timeline_payload(step.output_json)
        return {
            "id": step.id,
            "step_type": step.step_type,
            "tool_name": step.tool_name,
            "input_json": self._bounded_payload(input_json, max_payload_chars),
            "output_json": self._bounded_payload(output_json, max_payload_chars),
            "input_classification": step.input_classification or input_classification,
            "output_classification": step.output_classification or output_classification,
            "duration_ms": step.duration_ms,
            "created_at": step.created_at,
        }

    def _summary(self, run: EvaluationRun, cases: list[dict]) -> dict:
        failures = Counter(
            case["failure_category"] or "unknown"
            for case in cases
            if case["passed"] is not True
        )
        providers = sorted({case["provider"] for case in cases if case["provider"]})
        models = sorted({case["model"] for case in cases if case["model"]})
        return {
            "run_id": run.id,
            "task_type": run.task_type,
            "status": run.status,
            "cases": len(cases),
            "passed": sum(1 for case in cases if case["passed"] is True),
            "failed": sum(1 for case in cases if case["passed"] is not True),
            "failure_distribution": dict(failures),
            "providers": providers,
            "models": models,
            "metrics": run.metrics_json,
        }

    def _bounded_payload(self, value: Any, max_chars: int) -> dict | list | None:
        if value is None:
            return None
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= max_chars:
            return value
        return {
            "truncated": True,
            "original_type": type(value).__name__,
            "char_count": len(text),
            "preview": text[:max_chars],
        }
