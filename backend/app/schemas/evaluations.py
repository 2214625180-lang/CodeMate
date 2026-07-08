from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EvaluationTaskType = Literal["retrieval", "fix"]
EvaluationRunStatus = Literal["running", "completed", "failed"]


class RetrievalEvaluationCase(BaseModel):
    case_id: str | None = Field(default=None, max_length=128)
    repo_id: str = Field(..., min_length=1, max_length=36)
    question: str = Field(..., min_length=1, max_length=8000)
    expected_file: str = Field(..., min_length=1, max_length=2048)
    expected_lines: dict | list | None = None


class RetrievalEvaluationRunRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    dataset_id: str | None = Field(default=None, max_length=36)
    dataset_version: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=20)
    cases: list[RetrievalEvaluationCase] = Field(..., min_length=1, max_length=200)


class FixEvaluationCase(BaseModel):
    case_id: str | None = Field(default=None, max_length=128)
    repo_id: str = Field(..., min_length=1, max_length=36)
    issue: str = Field(..., min_length=1, max_length=20000)
    test_command: str | None = Field(default=None, max_length=255)
    expected_status: Literal["success", "failed"] = "success"
    expected_diff_contains: list[str] = Field(default_factory=list, max_length=20)


class FixEvaluationRunRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    dataset_id: str | None = Field(default=None, max_length=36)
    dataset_version: int | None = Field(default=None, ge=1)
    require_tests_ran: bool = True
    cases: list[FixEvaluationCase] = Field(..., min_length=1, max_length=50)


class EvaluationGatePolicy(BaseModel):
    max_primary_metric_drop: float = Field(default=0.0, ge=0.0, le=1.0)
    max_regressed_cases: int = Field(default=0, ge=0)
    allow_incompatible: bool = False
    max_avg_latency_increase_sec: float | None = Field(default=None, ge=0.0)
    max_avg_tool_call_increase: float | None = Field(default=None, ge=0.0)


class EvaluationDatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    task_type: EvaluationTaskType
    description: str | None = None
    version: int = Field(default=1, ge=1)
    baseline_run_id: str | None = Field(default=None, max_length=36)
    gate_policy_json: EvaluationGatePolicy = Field(default_factory=EvaluationGatePolicy)
    cases_json: list[dict] = Field(..., min_length=1)
    metadata_json: dict = Field(default_factory=dict)


class EvaluationDatasetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    task_type: EvaluationTaskType | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    baseline_run_id: str | None = Field(default=None, max_length=36)
    gate_policy_json: EvaluationGatePolicy | None = None
    cases_json: list[dict] | None = None
    metadata_json: dict | None = None


class EvaluationDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    task_type: EvaluationTaskType
    description: str | None
    version: int
    baseline_run_id: str | None
    gate_policy_json: EvaluationGatePolicy
    cases_json: list[dict]
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class EvaluationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_run_id: str | None
    case_id: str | None
    repo_id: str | None
    task_type: str
    status: str | None
    question: str | None
    expected_file: str | None
    expected_lines: dict | list | None
    result_json: dict | list | None
    passed: bool | None
    latency_ms: int | None
    score: float | None
    failure_category: str | None
    agent_run_id: str | None
    provider: str | None
    model: str | None
    metadata_json: dict
    created_at: datetime


class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None
    task_type: EvaluationTaskType
    status: EvaluationRunStatus
    dataset_id: str | None
    dataset_version: int | None
    case_count: int
    passed_count: int
    failed_count: int
    metrics_json: dict
    config_snapshot: dict
    request_json: dict
    created_at: datetime
    finished_at: datetime | None
    results: list[EvaluationResultRead] = []


class EvaluationMetricDelta(BaseModel):
    name: str
    baseline: float | int | None
    candidate: float | int | None
    delta: float | int | None
    percent_delta: float | None
    direction: Literal["higher_is_better", "lower_is_better", "neutral"]


class EvaluationCaseComparison(BaseModel):
    case_id: str
    status: Literal[
        "regressed",
        "improved",
        "unchanged_pass",
        "unchanged_fail",
        "baseline_only",
        "candidate_only",
    ]
    question: str | None
    expected_file: str | None
    baseline_passed: bool | None
    candidate_passed: bool | None
    baseline_status: str | None
    candidate_status: str | None
    baseline_failure_category: str | None
    candidate_failure_category: str | None
    baseline_latency_ms: int | None
    candidate_latency_ms: int | None
    latency_delta_ms: int | None
    baseline_result: dict | list | None
    candidate_result: dict | list | None


class EvaluationRunCompareRead(BaseModel):
    baseline_run: EvaluationRunRead
    candidate_run: EvaluationRunRead
    compatible: bool
    compatibility_warnings: list[str]
    verdict: Literal["pass", "regression", "inconclusive"]
    primary_metric: str
    metric_deltas: list[EvaluationMetricDelta]
    summary: dict
    failure_distribution_delta: dict[str, int]
    case_comparisons: list[EvaluationCaseComparison]


class EvaluationGateCheckRead(BaseModel):
    name: str
    passed: bool | None
    observed: float | int | str | bool | None
    threshold: float | int | str | bool | None
    message: str


class EvaluationGateResultRead(BaseModel):
    dataset: EvaluationDatasetRead
    baseline_run: EvaluationRunRead
    candidate_run: EvaluationRunRead
    status: Literal["passed", "failed", "inconclusive"]
    policy: EvaluationGatePolicy
    checks: list[EvaluationGateCheckRead]
    comparison: EvaluationRunCompareRead
