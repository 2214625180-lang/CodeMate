from collections import Counter
from datetime import datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.evaluation import Evaluation
from app.models.evaluation_dataset import EvaluationDataset
from app.models.evaluation_dataset_snapshot import EvaluationDatasetSnapshot
from app.models.evaluation_run import EvaluationRun
from app.models.repository import Repository
from app.schemas.evaluations import (
    EvaluationGatePolicy,
    FixEvaluationRunRequest,
    RetrievalEvaluationRunRequest,
)
from app.services.agent_service import AgentService
from app.services.retrieval_service import RetrievalResult, RetrievalService


class EvaluationService:
    def __init__(self, db: Session):
        self.db = db

    def list_runs(self, *, limit: int = 20) -> list[EvaluationRun]:
        statement = (
            select(EvaluationRun)
            .options(selectinload(EvaluationRun.results))
            .order_by(EvaluationRun.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def get_run(self, evaluation_run_id: str) -> EvaluationRun:
        run = self.db.get(
            EvaluationRun,
            evaluation_run_id,
            options=[selectinload(EvaluationRun.results)],
        )
        if run is None:
            raise FileNotFoundError("Evaluation run not found")
        return run

    def compare_runs(self, baseline_run_id: str, candidate_run_id: str) -> dict:
        baseline_run = self.get_run(baseline_run_id)
        candidate_run = self.get_run(candidate_run_id)
        if baseline_run.task_type != candidate_run.task_type:
            raise ValueError("Evaluation runs must have the same task type")

        compatibility_warnings = self._comparison_warnings(baseline_run, candidate_run)
        primary_metric = (
            "fix_success_rate" if baseline_run.task_type == "fix" else "recall_at_5"
        )
        metric_deltas = self._comparison_metric_deltas(
            baseline_run,
            candidate_run,
            primary_metric=primary_metric,
        )
        case_comparisons = self._comparison_cases(baseline_run, candidate_run)
        failure_distribution_delta = self._failure_distribution_delta(
            baseline_run.metrics_json,
            candidate_run.metrics_json,
        )
        summary = self._comparison_summary(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            case_comparisons=case_comparisons,
            metric_deltas=metric_deltas,
            primary_metric=primary_metric,
        )

        return {
            "baseline_run": baseline_run,
            "candidate_run": candidate_run,
            "compatible": not compatibility_warnings,
            "compatibility_warnings": compatibility_warnings,
            "verdict": self._comparison_verdict(
                baseline_run=baseline_run,
                candidate_run=candidate_run,
                summary=summary,
                metric_deltas=metric_deltas,
                primary_metric=primary_metric,
            ),
            "primary_metric": primary_metric,
            "metric_deltas": metric_deltas,
            "summary": summary,
            "failure_distribution_delta": failure_distribution_delta,
            "case_comparisons": case_comparisons,
        }

    def evaluate_gate(self, dataset_id: str, candidate_run_id: str) -> dict:
        dataset = self.db.get(EvaluationDataset, dataset_id)
        if dataset is None:
            raise FileNotFoundError("Evaluation dataset not found")
        if not dataset.baseline_run_id:
            raise ValueError("Benchmark dataset has no baseline evaluation run")

        candidate_run = self.get_run(candidate_run_id)
        if candidate_run.task_type != dataset.task_type:
            raise ValueError("Candidate evaluation run task type must match dataset task type")
        if candidate_run.dataset_id != dataset.id:
            raise ValueError("Candidate evaluation run must belong to this benchmark dataset")

        policy = self._gate_policy(dataset.gate_policy_json)
        comparison = self.compare_runs(dataset.baseline_run_id, candidate_run_id)
        checks = self._gate_checks(comparison, policy)
        status = self._gate_status(checks)
        return {
            "dataset": dataset,
            "baseline_run": comparison["baseline_run"],
            "candidate_run": comparison["candidate_run"],
            "status": status,
            "policy": policy,
            "checks": checks,
            "comparison": comparison,
        }

    def dataset_history(
        self,
        dataset_id: str,
        *,
        limit: int = 30,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        status_filter: str | None = None,
        gate_status_filter: str | None = None,
        provider_filter: str | None = None,
        model_filter: str | None = None,
    ) -> dict:
        dataset = self.db.get(EvaluationDataset, dataset_id)
        if dataset is None:
            raise FileNotFoundError("Evaluation dataset not found")

        statement = (
            select(EvaluationRun)
            .options(selectinload(EvaluationRun.results))
            .where(EvaluationRun.dataset_id == dataset.id)
            .order_by(EvaluationRun.created_at.desc())
        )
        if created_after is not None:
            statement = statement.where(EvaluationRun.created_at >= created_after)
        if created_before is not None:
            statement = statement.where(EvaluationRun.created_at <= created_before)
        if status_filter is not None:
            statement = statement.where(EvaluationRun.status == status_filter)

        runs = list(self.db.execute(statement).scalars().all())
        primary_metric = self._primary_metric_for_task(dataset.task_type)
        history_runs = [
            self._history_run(
                run,
                dataset=dataset,
                primary_metric=primary_metric,
            )
            for run in runs
        ]
        history_runs = [
            run
            for run in history_runs
            if self._history_run_matches(
                run,
                gate_status_filter=gate_status_filter,
                provider_filter=provider_filter,
                model_filter=model_filter,
            )
        ][:limit]
        return {
            "dataset": dataset,
            "baseline_run_id": dataset.baseline_run_id,
            "primary_metric_name": primary_metric,
            "filters": {
                "limit": limit,
                "created_after": created_after.isoformat() if created_after else None,
                "created_before": created_before.isoformat() if created_before else None,
                "status": status_filter,
                "gate_status": gate_status_filter,
                "provider": provider_filter,
                "model": model_filter,
            },
            "summary": self._history_summary(history_runs, primary_metric=primary_metric),
            "gate_status_counts": dict(Counter(item["gate_status"] for item in history_runs)),
            "runs": history_runs,
        }

    def create_retrieval_run(self, request: RetrievalEvaluationRunRequest) -> EvaluationRun:
        request_json = request.model_dump()
        cases = [case.model_dump() for case in request.cases]
        dataset_snapshot = self._resolve_dataset_snapshot(
            snapshot_id=request.dataset_snapshot_id,
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            task_type="retrieval",
            cases=cases,
        )
        dataset_snapshot_id = dataset_snapshot.id if dataset_snapshot is not None else None
        dataset_version = request.dataset_version
        if dataset_snapshot is not None and dataset_version is None:
            dataset_version = dataset_snapshot.version
        if dataset_snapshot_id:
            request_json["dataset_snapshot_id"] = dataset_snapshot_id
            request_json["dataset_version"] = dataset_version
        run = EvaluationRun(
            name=request.name,
            task_type="retrieval",
            status="running",
            dataset_id=request.dataset_id,
            dataset_version=dataset_version,
            dataset_snapshot_id=dataset_snapshot_id,
            case_count=len(request.cases),
            config_snapshot=self._config_snapshot(),
            request_json=request_json,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def create_fix_run(self, request: FixEvaluationRunRequest) -> EvaluationRun:
        request_json = request.model_dump()
        cases = [case.model_dump() for case in request.cases]
        dataset_snapshot = self._resolve_dataset_snapshot(
            snapshot_id=request.dataset_snapshot_id,
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            task_type="fix",
            cases=cases,
        )
        dataset_snapshot_id = dataset_snapshot.id if dataset_snapshot is not None else None
        dataset_version = request.dataset_version
        if dataset_snapshot is not None and dataset_version is None:
            dataset_version = dataset_snapshot.version
        if dataset_snapshot_id:
            request_json["dataset_snapshot_id"] = dataset_snapshot_id
            request_json["dataset_version"] = dataset_version
        run = EvaluationRun(
            name=request.name,
            task_type="fix",
            status="running",
            dataset_id=request.dataset_id,
            dataset_version=dataset_version,
            dataset_snapshot_id=dataset_snapshot_id,
            case_count=len(request.cases),
            config_snapshot=self._config_snapshot(),
            request_json=request_json,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def execute_run(self, evaluation_run_id: str) -> EvaluationRun:
        run = self.get_run(evaluation_run_id)
        if run.task_type == "retrieval":
            request = RetrievalEvaluationRunRequest(**run.request_json)
            return self._execute_retrieval_run(run, request)
        if run.task_type == "fix":
            request = FixEvaluationRunRequest(**run.request_json)
            return self._execute_fix_run(run, request)
        raise ValueError(f"Unsupported evaluation task type: {run.task_type}")

    def fail_run(self, evaluation_run_id: str, reason: str) -> None:
        run = self.db.get(EvaluationRun, evaluation_run_id)
        if run is None:
            return
        run.status = "failed"
        run.metrics_json = {"error": reason}
        run.finished_at = datetime.utcnow()
        self.db.add(run)
        self.db.commit()

    def _execute_retrieval_run(
        self,
        run: EvaluationRun,
        request: RetrievalEvaluationRunRequest,
    ) -> EvaluationRun:
        self._clear_existing_results(run.id)
        results: list[Evaluation] = []
        for index, case in enumerate(request.cases, start=1):
            results.append(
                self._run_retrieval_case(
                    evaluation_run_id=run.id,
                    case_id=case.case_id or f"retrieval-{index}",
                    repo_id=case.repo_id,
                    question=case.question,
                    expected_file=case.expected_file,
                    expected_lines=case.expected_lines,
                    top_k=request.top_k,
                )
            )

        passed_count = sum(1 for result in results if result.passed)
        failed_count = len(results) - passed_count
        run.status = "completed"
        run.passed_count = passed_count
        run.failed_count = failed_count
        run.metrics_json = self._retrieval_metrics(results, top_k=request.top_k)
        run.finished_at = datetime.utcnow()
        self.db.add(run)
        self.db.commit()
        return self.get_run(run.id)

    def _execute_fix_run(
        self,
        run: EvaluationRun,
        request: FixEvaluationRunRequest,
    ) -> EvaluationRun:
        self._clear_existing_results(run.id)
        results: list[Evaluation] = []
        for index, case in enumerate(request.cases, start=1):
            results.append(
                self._run_fix_case(
                    evaluation_run_id=run.id,
                    case_id=case.case_id or f"fix-{index}",
                    repo_id=case.repo_id,
                    issue=case.issue,
                    test_command=case.test_command,
                    expected_status=case.expected_status,
                    expected_diff_contains=case.expected_diff_contains,
                    require_tests_ran=request.require_tests_ran,
                )
            )

        passed_count = sum(1 for result in results if result.passed)
        failed_count = len(results) - passed_count
        run.status = "completed"
        run.passed_count = passed_count
        run.failed_count = failed_count
        run.metrics_json = self._fix_metrics(results)
        run.finished_at = datetime.utcnow()
        self.db.add(run)
        self.db.commit()
        return self.get_run(run.id)

    def _clear_existing_results(self, evaluation_run_id: str) -> None:
        existing = self.db.execute(
            select(Evaluation).where(Evaluation.evaluation_run_id == evaluation_run_id)
        ).scalars()
        for result in existing:
            self.db.delete(result)
        self.db.commit()

    def _run_retrieval_case(
        self,
        *,
        evaluation_run_id: str,
        case_id: str,
        repo_id: str,
        question: str,
        expected_file: str,
        expected_lines: dict | list | None,
        top_k: int,
    ) -> Evaluation:
        started = perf_counter()
        try:
            retrieved = RetrievalService(self.db).retrieve(
                repo_id=repo_id,
                query=question,
                top_k=top_k,
            )
            latency_ms = int((perf_counter() - started) * 1000)
            citations = [self._citation(result) for result in retrieved[:top_k]]
            passed = any(citation["file_path"] == expected_file for citation in citations[:5])
            failure_category = None if passed else self._retrieval_failure(citations)
            result = Evaluation(
                evaluation_run_id=evaluation_run_id,
                case_id=case_id,
                repo_id=self._safe_repo_id(repo_id),
                task_type="retrieval",
                status="passed" if passed else "failed",
                question=question,
                expected_file=expected_file,
                expected_lines=expected_lines,
                result_json={
                    "citations": citations,
                    "top_k": top_k,
                    "expected_file": expected_file,
                },
                passed=passed,
                latency_ms=latency_ms,
                score=1.0 if passed else 0.0,
                failure_category=failure_category,
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                metadata_json={"metric": "recall_at_5"},
            )
        except Exception as exc:  # noqa: BLE001 - keep eval batches inspectable.
            self.db.rollback()
            latency_ms = int((perf_counter() - started) * 1000)
            result = Evaluation(
                evaluation_run_id=evaluation_run_id,
                case_id=case_id,
                repo_id=self._safe_repo_id(repo_id),
                task_type="retrieval",
                status="error",
                question=question,
                expected_file=expected_file,
                expected_lines=expected_lines,
                result_json={"error": str(exc)},
                passed=False,
                latency_ms=latency_ms,
                score=0.0,
                failure_category="runner_error",
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                metadata_json={"metric": "recall_at_5"},
            )

        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def _retrieval_metrics(self, results: list[Evaluation], *, top_k: int) -> dict:
        case_count = len(results)
        passed_count = sum(1 for result in results if result.passed)
        latencies = [result.latency_ms for result in results if result.latency_ms is not None]
        failures = Counter(
            result.failure_category or "unknown"
            for result in results
            if not result.passed
        )
        return {
            "cases": case_count,
            "passed": passed_count,
            "failed": case_count - passed_count,
            "recall_at_5": passed_count / case_count if case_count else 0.0,
            "avg_latency_sec": (sum(latencies) / len(latencies) / 1000) if latencies else 0.0,
            "failure_distribution": dict(failures),
            "top_k": top_k,
        }

    def _run_fix_case(
        self,
        *,
        evaluation_run_id: str,
        case_id: str,
        repo_id: str,
        issue: str,
        test_command: str | None,
        expected_status: str,
        expected_diff_contains: list[str],
        require_tests_ran: bool,
    ) -> Evaluation:
        started = perf_counter()
        agent_run_id: str | None = None
        try:
            agent_service = AgentService(self.db)
            agent_run = agent_service.create_fix_run(
                repo_id=repo_id,
                issue=issue,
                test_command=test_command,
            )
            agent_run_id = agent_run.id
            agent_service.run_fix(agent_run.id)
            completed_run = self._get_agent_run(agent_run.id)
            latency_ms = int((perf_counter() - started) * 1000)
            passed = self._fix_case_passed(
                run=completed_run,
                expected_status=expected_status,
                expected_diff_contains=expected_diff_contains,
                require_tests_ran=require_tests_ran,
            )
            result = Evaluation(
                evaluation_run_id=evaluation_run_id,
                case_id=case_id,
                repo_id=repo_id,
                task_type="fix",
                status="passed" if passed else "failed",
                question=issue,
                result_json=self._agent_result_json(completed_run),
                passed=passed,
                latency_ms=latency_ms,
                score=1.0 if passed else 0.0,
                failure_category=None
                if passed
                else self._fix_failure(
                    run=completed_run,
                    expected_status=expected_status,
                    expected_diff_contains=expected_diff_contains,
                    require_tests_ran=require_tests_ran,
                ),
                agent_run_id=agent_run_id,
                provider=settings.llm_provider,
                model=settings.llm_model,
                metadata_json={
                    "metric": "fix_success_rate",
                    "expected_status": expected_status,
                    "expected_diff_contains": expected_diff_contains,
                    "require_tests_ran": require_tests_ran,
                    "test_command": test_command,
                },
            )
        except Exception as exc:  # noqa: BLE001 - keep eval batches inspectable.
            self.db.rollback()
            latency_ms = int((perf_counter() - started) * 1000)
            result = Evaluation(
                evaluation_run_id=evaluation_run_id,
                case_id=case_id,
                repo_id=self._safe_repo_id(repo_id),
                task_type="fix",
                status="error",
                question=issue,
                result_json={"error": str(exc)},
                passed=False,
                latency_ms=latency_ms,
                score=0.0,
                failure_category="runner_error",
                agent_run_id=agent_run_id,
                provider=settings.llm_provider,
                model=settings.llm_model,
                metadata_json={
                    "metric": "fix_success_rate",
                    "expected_status": expected_status,
                    "expected_diff_contains": expected_diff_contains,
                    "require_tests_ran": require_tests_ran,
                    "test_command": test_command,
                },
            )

        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def _fix_metrics(self, results: list[Evaluation]) -> dict:
        case_count = len(results)
        passed_count = sum(1 for result in results if result.passed)
        latencies = [result.latency_ms for result in results if result.latency_ms is not None]
        tool_calls = [
            int(result.result_json.get("tool_calls", 0))
            for result in results
            if isinstance(result.result_json, dict)
        ]
        failures = Counter(
            result.failure_category or "unknown"
            for result in results
            if not result.passed
        )
        return {
            "cases": case_count,
            "passed": passed_count,
            "failed": case_count - passed_count,
            "fix_success_rate": passed_count / case_count if case_count else 0.0,
            "avg_tool_calls": sum(tool_calls) / len(tool_calls) if tool_calls else 0.0,
            "avg_latency_sec": (sum(latencies) / len(latencies) / 1000) if latencies else 0.0,
            "failure_distribution": dict(failures),
        }

    def _comparison_warnings(
        self,
        baseline_run: EvaluationRun,
        candidate_run: EvaluationRun,
    ) -> list[str]:
        warnings: list[str] = []
        if baseline_run.status != "completed":
            warnings.append("Baseline run is not completed")
        if candidate_run.status != "completed":
            warnings.append("Candidate run is not completed")
        if baseline_run.dataset_id != candidate_run.dataset_id:
            warnings.append("Runs use different benchmark datasets")
        if baseline_run.dataset_version != candidate_run.dataset_version:
            warnings.append("Runs use different benchmark dataset versions")
        if (
            baseline_run.dataset_snapshot_id
            and candidate_run.dataset_snapshot_id
            and baseline_run.dataset_snapshot_id != candidate_run.dataset_snapshot_id
        ):
            warnings.append("Runs use different benchmark dataset snapshots")
        if baseline_run.case_count != candidate_run.case_count:
            warnings.append("Runs have different case counts")

        baseline_cases = {self._comparison_case_key(result) for result in baseline_run.results}
        candidate_cases = {self._comparison_case_key(result) for result in candidate_run.results}
        if not baseline_cases.intersection(candidate_cases):
            warnings.append("Runs have no common case ids")

        baseline_top_k = baseline_run.metrics_json.get("top_k")
        candidate_top_k = candidate_run.metrics_json.get("top_k")
        if baseline_top_k and candidate_top_k and baseline_top_k != candidate_top_k:
            warnings.append("Runs use different retrieval top_k values")
        return warnings

    def _gate_policy(self, raw_policy: dict | None) -> EvaluationGatePolicy:
        return EvaluationGatePolicy(**(raw_policy or {}))

    def _gate_checks(self, comparison: dict, policy: EvaluationGatePolicy) -> list[dict]:
        summary = comparison["summary"]
        metric_deltas = comparison["metric_deltas"]
        primary_delta = summary.get("primary_metric_delta") or {}
        primary_metric_delta = self._optional_number(primary_delta.get("delta"))
        regressed_cases = int(summary.get("regressions", 0))
        compatibility_warnings = comparison["compatibility_warnings"]
        generic_compatibility_warnings = self._gate_compatibility_warnings(
            compatibility_warnings
        )
        generic_compatible = not generic_compatibility_warnings
        latency_delta = self._metric_delta(metric_deltas, "avg_latency_sec")
        tool_call_delta = self._metric_delta(metric_deltas, "avg_tool_calls")
        baseline_context = summary.get("baseline_context") or {}
        candidate_context = summary.get("candidate_context") or {}
        baseline_snapshot_id = baseline_context.get("dataset_snapshot_id")
        candidate_snapshot_id = candidate_context.get("dataset_snapshot_id")

        checks = [
            {
                "name": "matching_dataset_snapshot",
                "passed": self._dataset_snapshot_check_passed(
                    baseline_snapshot_id=baseline_snapshot_id,
                    candidate_snapshot_id=candidate_snapshot_id,
                    required=policy.require_matching_dataset_snapshot,
                ),
                "observed": self._dataset_snapshot_observed(
                    baseline_snapshot_id=baseline_snapshot_id,
                    candidate_snapshot_id=candidate_snapshot_id,
                ),
                "threshold": "matching dataset_snapshot_id"
                if policy.require_matching_dataset_snapshot
                else "ignored",
                "message": (
                    "Baseline and candidate must use the same dataset snapshot "
                    "unless require_matching_dataset_snapshot is disabled."
                ),
            },
            {
                "name": "compatible_runs",
                "passed": True if policy.allow_incompatible else generic_compatible,
                "observed": "compatible"
                if generic_compatible
                else "; ".join(generic_compatibility_warnings),
                "threshold": "compatible" if not policy.allow_incompatible else "ignored",
                "message": "Runs must be comparable unless allow_incompatible is enabled.",
            },
            {
                "name": "primary_metric_drop",
                "passed": None
                if primary_metric_delta is None
                else primary_metric_delta >= -policy.max_primary_metric_drop,
                "observed": primary_metric_delta,
                "threshold": -policy.max_primary_metric_drop,
                "message": "Primary metric may not drop beyond the configured allowance.",
            },
            {
                "name": "case_regressions",
                "passed": regressed_cases <= policy.max_regressed_cases,
                "observed": regressed_cases,
                "threshold": policy.max_regressed_cases,
                "message": "Regressed benchmark cases must stay within policy.",
            },
        ]

        if policy.max_avg_latency_increase_sec is not None:
            checks.append(
                {
                    "name": "avg_latency_increase",
                    "passed": None
                    if latency_delta is None
                    else latency_delta <= policy.max_avg_latency_increase_sec,
                    "observed": latency_delta,
                    "threshold": policy.max_avg_latency_increase_sec,
                    "message": "Average latency increase must stay within policy.",
                }
            )

        if policy.max_avg_tool_call_increase is not None:
            checks.append(
                {
                    "name": "avg_tool_call_increase",
                    "passed": None
                    if tool_call_delta is None
                    else tool_call_delta <= policy.max_avg_tool_call_increase,
                    "observed": tool_call_delta,
                    "threshold": policy.max_avg_tool_call_increase,
                    "message": "Average tool call increase must stay within policy.",
                }
            )

        return checks

    def _gate_compatibility_warnings(self, warnings: list[str]) -> list[str]:
        return [
            warning
            for warning in warnings
            if warning != "Runs use different benchmark dataset snapshots"
        ]

    def _dataset_snapshot_check_passed(
        self,
        *,
        baseline_snapshot_id: object,
        candidate_snapshot_id: object,
        required: bool,
    ) -> bool | None:
        if not required:
            return True
        if not baseline_snapshot_id or not candidate_snapshot_id:
            return None
        return baseline_snapshot_id == candidate_snapshot_id

    def _dataset_snapshot_observed(
        self,
        *,
        baseline_snapshot_id: object,
        candidate_snapshot_id: object,
    ) -> str:
        return (
            f"baseline={baseline_snapshot_id or 'missing'}, "
            f"candidate={candidate_snapshot_id or 'missing'}"
        )

    def _gate_status(self, checks: list[dict]) -> str:
        if any(check["passed"] is False for check in checks):
            return "failed"
        if any(check["passed"] is None for check in checks):
            return "inconclusive"
        return "passed"

    def _comparison_metric_deltas(
        self,
        baseline_run: EvaluationRun,
        candidate_run: EvaluationRun,
        *,
        primary_metric: str,
    ) -> list[dict]:
        metric_specs: list[tuple[str, str]] = [
            (primary_metric, "higher_is_better"),
            ("passed", "higher_is_better"),
            ("failed", "lower_is_better"),
            ("avg_latency_sec", "lower_is_better"),
        ]
        if baseline_run.task_type == "fix":
            metric_specs.append(("avg_tool_calls", "lower_is_better"))

        deltas: list[dict] = []
        for name, direction in metric_specs:
            baseline = self._numeric_metric(baseline_run.metrics_json, name)
            candidate = self._numeric_metric(candidate_run.metrics_json, name)
            delta = None if baseline is None or candidate is None else candidate - baseline
            percent_delta = (
                None
                if baseline in (None, 0) or delta is None
                else delta / baseline
            )
            deltas.append(
                {
                    "name": name,
                    "baseline": baseline,
                    "candidate": candidate,
                    "delta": delta,
                    "percent_delta": percent_delta,
                    "direction": direction,
                }
            )
        return deltas

    def _comparison_cases(
        self,
        baseline_run: EvaluationRun,
        candidate_run: EvaluationRun,
    ) -> list[dict]:
        baseline_results = {
            self._comparison_case_key(result): result for result in baseline_run.results
        }
        candidate_results = {
            self._comparison_case_key(result): result for result in candidate_run.results
        }
        case_ids = sorted(set(baseline_results) | set(candidate_results))
        comparisons = []
        for case_id in case_ids:
            baseline = baseline_results.get(case_id)
            candidate = candidate_results.get(case_id)
            status = self._comparison_case_status(baseline, candidate)
            baseline_latency = baseline.latency_ms if baseline is not None else None
            candidate_latency = candidate.latency_ms if candidate is not None else None
            comparisons.append(
                {
                    "case_id": case_id,
                    "status": status,
                    "question": self._first_value(baseline, candidate, "question"),
                    "expected_file": self._first_value(baseline, candidate, "expected_file"),
                    "baseline_passed": baseline.passed if baseline is not None else None,
                    "candidate_passed": candidate.passed if candidate is not None else None,
                    "baseline_status": baseline.status if baseline is not None else None,
                    "candidate_status": candidate.status if candidate is not None else None,
                    "baseline_failure_category": (
                        baseline.failure_category if baseline is not None else None
                    ),
                    "candidate_failure_category": (
                        candidate.failure_category if candidate is not None else None
                    ),
                    "baseline_latency_ms": baseline_latency,
                    "candidate_latency_ms": candidate_latency,
                    "latency_delta_ms": (
                        None
                        if baseline_latency is None or candidate_latency is None
                        else candidate_latency - baseline_latency
                    ),
                    "baseline_result": self._comparison_result_summary(baseline),
                    "candidate_result": self._comparison_result_summary(candidate),
                }
            )

        order = {
            "regressed": 0,
            "improved": 1,
            "baseline_only": 2,
            "candidate_only": 3,
            "unchanged_fail": 4,
            "unchanged_pass": 5,
        }
        return sorted(comparisons, key=lambda item: (order[item["status"]], item["case_id"]))

    def _history_run(
        self,
        run: EvaluationRun,
        *,
        dataset: EvaluationDataset,
        primary_metric: str,
    ) -> dict:
        metrics = run.metrics_json or {}
        comparison: dict | None = None
        gate_status = "not_evaluated"
        primary_metric_delta = None
        regressions = None
        improvements = None

        if (
            dataset.baseline_run_id
            and run.id != dataset.baseline_run_id
            and run.status == "completed"
        ):
            try:
                comparison = self.compare_runs(dataset.baseline_run_id, run.id)
                checks = self._gate_checks(comparison, self._gate_policy(dataset.gate_policy_json))
                gate_status = self._gate_status(checks)
                summary = comparison["summary"]
                primary_delta = summary.get("primary_metric_delta") or {}
                primary_metric_delta = primary_delta.get("delta")
                regressions = summary.get("regressions")
                improvements = summary.get("improvements")
            except (FileNotFoundError, ValueError):
                gate_status = "inconclusive"
        elif dataset.baseline_run_id and run.id != dataset.baseline_run_id:
            gate_status = "inconclusive"
        elif dataset.baseline_run_id and run.id == dataset.baseline_run_id:
            gate_status = "not_evaluated"

        return {
            "id": run.id,
            "name": run.name,
            "task_type": run.task_type,
            "status": run.status,
            "dataset_version": run.dataset_version,
            "dataset_snapshot_id": run.dataset_snapshot_id,
            "gate_status": gate_status,
            "primary_metric_name": primary_metric,
            "primary_metric_value": self._optional_number(metrics.get(primary_metric)),
            "primary_metric_delta": self._optional_number(primary_metric_delta),
            "pass_rate": self._history_pass_rate(run, metrics, primary_metric=primary_metric),
            "case_count": run.case_count,
            "passed_count": run.passed_count,
            "failed_count": run.failed_count,
            "avg_latency_sec": self._optional_number(metrics.get("avg_latency_sec")),
            "avg_tool_calls": self._optional_number(metrics.get("avg_tool_calls")),
            "failure_distribution": self._int_dict(metrics.get("failure_distribution")),
            "regressions": regressions if isinstance(regressions, int) else None,
            "improvements": improvements if isinstance(improvements, int) else None,
            "provider": self._history_provider(run),
            "model": self._history_model(run),
            "created_at": run.created_at,
            "finished_at": run.finished_at,
        }

    def _history_summary(self, history_runs: list[dict], *, primary_metric: str) -> dict:
        completed_runs = [item for item in history_runs if item["status"] == "completed"]
        latest = history_runs[0] if history_runs else None
        latest_completed = completed_runs[0] if completed_runs else None
        previous_completed = completed_runs[1] if len(completed_runs) > 1 else None
        latest_value = latest_completed.get("primary_metric_value") if latest_completed else None
        previous_value = (
            previous_completed.get("primary_metric_value") if previous_completed else None
        )
        latest_delta = (
            None
            if latest_value is None or previous_value is None
            else latest_value - previous_value
        )
        return {
            "run_count": len(history_runs),
            "completed_count": len(completed_runs),
            "failed_run_count": sum(1 for item in history_runs if item["status"] == "failed"),
            "running_count": sum(1 for item in history_runs if item["status"] == "running"),
            "latest_run_id": latest.get("id") if latest else None,
            "latest_completed_run_id": latest_completed.get("id") if latest_completed else None,
            "latest_primary_metric": latest_value,
            "previous_primary_metric": previous_value,
            "latest_primary_metric_delta": latest_delta,
            "primary_metric_name": primary_metric,
            "avg_primary_metric": self._average(
                item.get("primary_metric_value") for item in completed_runs
            ),
            "avg_latency_sec": self._average(
                item.get("avg_latency_sec") for item in completed_runs
            ),
            "avg_tool_calls": self._average(
                item.get("avg_tool_calls") for item in completed_runs
            ),
        }

    def _history_run_matches(
        self,
        run: dict,
        *,
        gate_status_filter: str | None,
        provider_filter: str | None,
        model_filter: str | None,
    ) -> bool:
        if gate_status_filter and run["gate_status"] != gate_status_filter:
            return False
        if provider_filter and not self._contains_filter(run.get("provider"), provider_filter):
            return False
        if model_filter and not self._contains_filter(run.get("model"), model_filter):
            return False
        return True

    def _contains_filter(self, value: str | None, filter_text: str) -> bool:
        return filter_text.strip().lower() in str(value or "").lower()

    def _comparison_summary(
        self,
        *,
        baseline_run: EvaluationRun,
        candidate_run: EvaluationRun,
        case_comparisons: list[dict],
        metric_deltas: list[dict],
        primary_metric: str,
    ) -> dict:
        status_counts = Counter(item["status"] for item in case_comparisons)
        primary_delta = next(
            (item for item in metric_deltas if item["name"] == primary_metric),
            None,
        )
        return {
            "case_status_counts": dict(status_counts),
            "common_cases": sum(
                1
                for item in case_comparisons
                if item["status"] not in {"baseline_only", "candidate_only"}
            ),
            "regressions": status_counts.get("regressed", 0),
            "improvements": status_counts.get("improved", 0),
            "baseline_only_cases": status_counts.get("baseline_only", 0),
            "candidate_only_cases": status_counts.get("candidate_only", 0),
            "primary_metric_delta": primary_delta,
            "baseline_context": self._run_context(baseline_run),
            "candidate_context": self._run_context(candidate_run),
        }

    def _comparison_verdict(
        self,
        *,
        baseline_run: EvaluationRun,
        candidate_run: EvaluationRun,
        summary: dict,
        metric_deltas: list[dict],
        primary_metric: str,
    ) -> str:
        if baseline_run.status != "completed" or candidate_run.status != "completed":
            return "inconclusive"
        if summary.get("common_cases", 0) == 0:
            return "inconclusive"

        primary_delta = next(
            (item for item in metric_deltas if item["name"] == primary_metric),
            None,
        )
        if primary_delta is None or primary_delta["delta"] is None:
            return "inconclusive"
        if primary_delta["delta"] < 0 or summary.get("regressions", 0) > 0:
            return "regression"
        return "pass"

    def _comparison_case_status(
        self,
        baseline: Evaluation | None,
        candidate: Evaluation | None,
    ) -> str:
        if baseline is None:
            return "candidate_only"
        if candidate is None:
            return "baseline_only"
        baseline_passed = baseline.passed is True
        candidate_passed = candidate.passed is True
        if baseline_passed and not candidate_passed:
            return "regressed"
        if not baseline_passed and candidate_passed:
            return "improved"
        if baseline_passed and candidate_passed:
            return "unchanged_pass"
        return "unchanged_fail"

    def _comparison_result_summary(self, result: Evaluation | None) -> dict | list | None:
        if result is None:
            return None
        if not isinstance(result.result_json, dict):
            return result.result_json

        if result.task_type == "fix":
            return {
                "agent_status": result.result_json.get("agent_status"),
                "tool_calls": result.result_json.get("tool_calls"),
                "iterations": result.result_json.get("iterations"),
                "final_diff_length": result.result_json.get("final_diff_length"),
                "error": result.result_json.get("error"),
            }

        citations = result.result_json.get("citations")
        if isinstance(citations, list):
            top_citation = citations[0] if citations else None
            return {
                "citation_count": len(citations),
                "top_citation": top_citation,
                "error": result.result_json.get("error"),
            }
        return result.result_json

    def _failure_distribution_delta(
        self,
        baseline_metrics: dict,
        candidate_metrics: dict,
    ) -> dict[str, int]:
        baseline_failures = self._dict_metric(baseline_metrics, "failure_distribution")
        candidate_failures = self._dict_metric(candidate_metrics, "failure_distribution")
        categories = sorted(set(baseline_failures) | set(candidate_failures))
        return {
            category: int(candidate_failures.get(category, 0))
            - int(baseline_failures.get(category, 0))
            for category in categories
        }

    def _run_context(self, run: EvaluationRun) -> dict:
        config = run.config_snapshot or {}
        return {
            "id": run.id,
            "name": run.name,
            "task_type": run.task_type,
            "status": run.status,
            "dataset_id": run.dataset_id,
            "dataset_version": run.dataset_version,
            "dataset_snapshot_id": run.dataset_snapshot_id,
            "created_at": run.created_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "llm_provider": config.get("llm_provider"),
            "llm_model": config.get("llm_model"),
            "embedding_provider": config.get("embedding_provider"),
            "embedding_model": config.get("embedding_model"),
        }

    def _comparison_case_key(self, result: Evaluation) -> str:
        return result.case_id or result.id

    def _numeric_metric(self, metrics: dict, name: str) -> float | int | None:
        value = metrics.get(name)
        return value if isinstance(value, int | float) else None

    def _optional_number(self, value: object) -> float | int | None:
        return value if isinstance(value, int | float) else None

    def _metric_delta(self, metric_deltas: list[dict], name: str) -> float | int | None:
        metric = next((item for item in metric_deltas if item["name"] == name), None)
        if metric is None:
            return None
        return self._optional_number(metric.get("delta"))

    def _dict_metric(self, metrics: dict, name: str) -> dict:
        value = metrics.get(name)
        return value if isinstance(value, dict) else {}

    def _int_dict(self, value: object) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): int(count)
            for key, count in value.items()
            if isinstance(count, int | float)
        }

    def _primary_metric_for_task(self, task_type: str) -> str:
        return "fix_success_rate" if task_type == "fix" else "recall_at_5"

    def _history_pass_rate(
        self,
        run: EvaluationRun,
        metrics: dict,
        *,
        primary_metric: str,
    ) -> float | int | None:
        primary = self._optional_number(metrics.get(primary_metric))
        if primary is not None:
            return primary
        if run.case_count <= 0:
            return None
        return run.passed_count / run.case_count

    def _history_provider(self, run: EvaluationRun) -> str | None:
        config = run.config_snapshot or {}
        if run.task_type == "fix":
            return config.get("llm_provider")
        return config.get("embedding_provider")

    def _history_model(self, run: EvaluationRun) -> str | None:
        config = run.config_snapshot or {}
        if run.task_type == "fix":
            return config.get("llm_model")
        return config.get("embedding_model")

    def _resolve_dataset_snapshot(
        self,
        *,
        snapshot_id: str | None,
        dataset_id: str | None,
        dataset_version: int | None,
        task_type: str,
        cases: list[dict],
    ) -> EvaluationDatasetSnapshot | None:
        if snapshot_id is None:
            return self._matching_dataset_snapshot(
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                task_type=task_type,
                cases=cases,
            )

        if dataset_id is None:
            raise ValueError("Dataset id is required when dataset snapshot is provided")
        snapshot = self.db.get(EvaluationDatasetSnapshot, snapshot_id)
        if snapshot is None:
            raise ValueError("Evaluation dataset snapshot not found")
        if snapshot.dataset_id != dataset_id:
            raise ValueError("Evaluation dataset snapshot does not match dataset")
        if dataset_version is not None and snapshot.version != dataset_version:
            raise ValueError("Evaluation dataset snapshot does not match dataset version")
        if snapshot.task_type != task_type:
            raise ValueError("Evaluation dataset snapshot task type does not match run task type")
        if snapshot.cases_json != cases:
            raise ValueError("Evaluation cases do not match dataset snapshot")
        return snapshot

    def _matching_dataset_snapshot(
        self,
        *,
        dataset_id: str | None,
        dataset_version: int | None,
        task_type: str,
        cases: list[dict],
    ) -> EvaluationDatasetSnapshot | None:
        if not dataset_id:
            return None

        dataset = self.db.get(EvaluationDataset, dataset_id)
        if dataset is None or dataset.task_type != task_type:
            return None

        version = dataset_version or dataset.version
        statement = select(EvaluationDatasetSnapshot).where(
            EvaluationDatasetSnapshot.dataset_id == dataset_id,
            EvaluationDatasetSnapshot.version == version,
        )
        snapshot = self.db.execute(statement).scalars().first()
        if snapshot is None:
            if version != dataset.version or dataset.cases_json != cases:
                return None
            snapshot = EvaluationDatasetSnapshot(
                dataset_id=dataset.id,
                name=dataset.name,
                task_type=dataset.task_type,
                description=dataset.description,
                version=dataset.version,
                baseline_run_id=dataset.baseline_run_id,
                gate_policy_json=dataset.gate_policy_json,
                cases_json=dataset.cases_json,
                metadata_json=dataset.metadata_json,
            )
            self.db.add(snapshot)
            self.db.flush()

        if snapshot.task_type != task_type or snapshot.cases_json != cases:
            return None
        return snapshot

    def _average(self, values: object) -> float | None:
        numbers = [value for value in values if isinstance(value, int | float)]
        if not numbers:
            return None
        return sum(numbers) / len(numbers)

    def _first_value(
        self,
        baseline: Evaluation | None,
        candidate: Evaluation | None,
        attr_name: str,
    ) -> str | None:
        for result in (candidate, baseline):
            if result is None:
                continue
            value = getattr(result, attr_name)
            if value:
                return value
        return None

    def _config_snapshot(self) -> dict:
        return {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "retrieval": {
                "top_k": settings.retrieval_top_k,
                "min_vector_score": settings.retrieval_min_vector_score,
                "candidate_multiplier": settings.retrieval_candidate_multiplier,
                "rerank_enabled": settings.retrieval_rerank_enabled,
                "context_expansion_enabled": settings.retrieval_context_expansion_enabled,
            },
        }

    def _citation(self, result: RetrievalResult) -> dict:
        chunk = result.chunk
        return {
            "chunk_id": chunk.id,
            "repo_id": chunk.repo_id,
            "file_path": chunk.file_path,
            "symbol_name": chunk.symbol_name,
            "symbol_type": chunk.symbol_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "score": result.score,
            "source": result.source,
        }

    def _retrieval_failure(self, citations: list[dict]) -> str:
        if not citations:
            return "no_retrieval_results"
        return "expected_file_not_retrieved"

    def _get_agent_run(self, run_id: str) -> AgentRun:
        statement = (
            select(AgentRun)
            .options(selectinload(AgentRun.steps))
            .where(AgentRun.id == run_id)
        )
        run = self.db.execute(statement).scalars().first()
        if run is None:
            raise FileNotFoundError("Agent run not found")
        return run

    def _safe_repo_id(self, repo_id: str) -> str | None:
        return repo_id if self.db.get(Repository, repo_id) is not None else None

    def _fix_case_passed(
        self,
        *,
        run: AgentRun,
        expected_status: str,
        expected_diff_contains: list[str],
        require_tests_ran: bool,
    ) -> bool:
        if run.status != expected_status:
            return False
        final_diff = run.final_diff or ""
        if any(fragment not in final_diff for fragment in expected_diff_contains):
            return False
        if expected_status == "success" and require_tests_ran:
            test_result = run.test_result or {}
            if not test_result.get("tests_ran"):
                return False
        return True

    def _fix_failure(
        self,
        *,
        run: AgentRun,
        expected_status: str,
        expected_diff_contains: list[str],
        require_tests_ran: bool,
    ) -> str:
        final_diff = run.final_diff or ""
        missing_diff_fragments = [
            fragment
            for fragment in expected_diff_contains
            if fragment not in final_diff
        ]
        if missing_diff_fragments:
            return "expected_diff_not_found"

        test_result = run.test_result or {}
        if expected_status == "success" and require_tests_ran and not test_result.get("tests_ran"):
            if test_result.get("skipped_reason"):
                return "tests_skipped_dependency_install"
            return "tests_not_run"

        if run.status != expected_status:
            if run.status == "failed":
                if test_result.get("tests_ran"):
                    return "tests_failed"
                if "patch" in str(test_result.get("stderr", "")).lower():
                    return "patch_apply_failed"
                if not final_diff:
                    return "no_patch_generated"
                return "agent_failed"
            return "unexpected_status"

        return "unknown"

    def _agent_result_json(self, run: AgentRun) -> dict:
        final_diff = run.final_diff or ""
        return {
            "agent_run_id": run.id,
            "agent_status": run.status,
            "summary": run.final_summary,
            "iterations": run.iterations,
            "tool_calls": sum(1 for step in run.steps if step.step_type == "tool_call"),
            "steps_by_type": dict(Counter(step.step_type for step in run.steps)),
            "test_result": run.test_result,
            "final_diff_length": len(final_diff),
            "final_diff_preview": final_diff[:12000],
        }
