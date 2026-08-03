from typing import Literal

from sqlalchemy.orm import Session

from app.services.evaluation_service import EvaluationService


BenchmarkGatedCapability = Literal[
    "reviewer_critic_agent",
    "swe_bench_subset",
    "go_java_parser",
    "learned_reranker",
]


class CapabilityBenchmarkEvidenceError(ValueError):
    pass


class CapabilityBenchmarkService:
    """Admit planned capabilities only after an existing benchmark gate passes."""

    REQUIRED_TASK_TYPES: dict[str, str] = {
        "reviewer_critic_agent": "fix",
        "swe_bench_subset": "fix",
        "go_java_parser": "retrieval",
        "learned_reranker": "retrieval",
    }

    def __init__(self, db: Session):
        self.db = db
        self.evaluations = EvaluationService(db)

    def require_benefit_evidence(
        self,
        *,
        capability: BenchmarkGatedCapability,
        dataset_id: str,
        candidate_run_id: str,
    ) -> dict:
        expected_task_type = self.REQUIRED_TASK_TYPES.get(capability)
        if expected_task_type is None:
            raise CapabilityBenchmarkEvidenceError("Capability is not benchmark-gated")
        gate = self.evaluations.evaluate_gate(dataset_id, candidate_run_id)
        dataset = gate["dataset"]
        if dataset.task_type != expected_task_type:
            raise CapabilityBenchmarkEvidenceError(
                f"{capability} requires a {expected_task_type} benchmark dataset"
            )
        if gate["status"] != "passed":
            raise CapabilityBenchmarkEvidenceError(
                f"Benchmark gate did not prove a benefit for {capability}"
            )
        comparison = gate["comparison"]
        primary_metric = comparison.get("primary_metric")
        primary_delta = next(
            (
                item.get("delta")
                for item in comparison.get("metric_deltas") or []
                if isinstance(item, dict) and item.get("name") == primary_metric
            ),
            None,
        )
        if not isinstance(primary_delta, int | float) or primary_delta <= 0:
            raise CapabilityBenchmarkEvidenceError(
                f"Benchmark gate did not show a positive primary-metric gain for {capability}"
            )
        baseline = gate["baseline_run"]
        candidate = gate["candidate_run"]
        return {
            "capability": capability,
            "status": "admitted",
            "dataset_id": dataset.id,
            "dataset_version": dataset.version,
            "baseline_run_id": baseline.id,
            "candidate_run_id": candidate.id,
            "candidate_config_snapshot": candidate.config_snapshot,
            "primary_metric": primary_metric,
            "primary_metric_delta": primary_delta,
            "checks": gate["checks"],
            "comparison": comparison,
        }
