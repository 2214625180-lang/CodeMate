from types import SimpleNamespace

import pytest

from app.services.capability_benchmark_service import (
    CapabilityBenchmarkEvidenceError,
    CapabilityBenchmarkService,
)


def test_capability_admission_requires_a_passing_matching_benchmark() -> None:
    service = CapabilityBenchmarkService.__new__(CapabilityBenchmarkService)
    service.evaluations = SimpleNamespace(
        evaluate_gate=lambda _dataset_id, _candidate_run_id: {
            "dataset": SimpleNamespace(id="dataset-retrieval", version=4, task_type="retrieval"),
            "baseline_run": SimpleNamespace(id="baseline"),
            "candidate_run": SimpleNamespace(
                id="candidate",
                config_snapshot={"code_commit_sha": "abc123"},
            ),
            "status": "passed",
            "checks": [{"name": "primary_metric", "passed": True}],
            "comparison": {
                "verdict": "pass",
                "primary_metric": "recall_at_k",
                "metric_deltas": [{"name": "recall_at_k", "delta": 0.1}],
            },
        }
    )

    evidence = service.require_benefit_evidence(
        capability="learned_reranker",
        dataset_id="dataset-retrieval",
        candidate_run_id="candidate",
    )

    assert evidence["status"] == "admitted"
    assert evidence["candidate_config_snapshot"] == {"code_commit_sha": "abc123"}
    assert evidence["primary_metric_delta"] == 0.1


def test_capability_admission_rejects_unproven_or_wrong_benchmarks() -> None:
    service = CapabilityBenchmarkService.__new__(CapabilityBenchmarkService)
    service.evaluations = SimpleNamespace(
        evaluate_gate=lambda _dataset_id, _candidate_run_id: {
            "dataset": SimpleNamespace(id="dataset-fix", version=1, task_type="fix"),
            "baseline_run": SimpleNamespace(id="baseline"),
            "candidate_run": SimpleNamespace(id="candidate", config_snapshot={}),
            "status": "failed",
            "checks": [],
            "comparison": {"primary_metric": "verified_fix_rate", "metric_deltas": []},
        }
    )

    with pytest.raises(CapabilityBenchmarkEvidenceError, match="requires a retrieval"):
        service.require_benefit_evidence(
            capability="go_java_parser",
            dataset_id="dataset-fix",
            candidate_run_id="candidate",
        )


def test_capability_admission_rejects_a_non_regressing_but_non_improving_run() -> None:
    service = CapabilityBenchmarkService.__new__(CapabilityBenchmarkService)
    service.evaluations = SimpleNamespace(
        evaluate_gate=lambda _dataset_id, _candidate_run_id: {
            "dataset": SimpleNamespace(id="dataset-retrieval", version=1, task_type="retrieval"),
            "baseline_run": SimpleNamespace(id="baseline"),
            "candidate_run": SimpleNamespace(id="candidate", config_snapshot={}),
            "status": "passed",
            "checks": [],
            "comparison": {
                "primary_metric": "recall_at_k",
                "metric_deltas": [{"name": "recall_at_k", "delta": 0.0}],
            },
        }
    )

    with pytest.raises(CapabilityBenchmarkEvidenceError, match="positive primary-metric gain"):
        service.require_benefit_evidence(
            capability="learned_reranker",
            dataset_id="dataset-retrieval",
            candidate_run_id="candidate",
        )
