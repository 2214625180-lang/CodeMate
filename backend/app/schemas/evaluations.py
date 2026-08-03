from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EvaluationTaskType = Literal["retrieval", "fix"]
EvaluationRunStatus = Literal["running", "completed", "failed"]
BenchmarkGatedCapability = Literal[
    "reviewer_critic_agent",
    "swe_bench_subset",
    "go_java_parser",
    "learned_reranker",
]


class RetrievalEvaluationCase(BaseModel):
    case_id: str | None = Field(default=None, max_length=128)
    repo_id: str = Field(..., min_length=1, max_length=36)
    question: str = Field(..., min_length=1, max_length=8000)
    expected_file: str = Field(..., min_length=1, max_length=2048)
    expected_lines: dict | list | None = None
    category: str = Field(default="unspecified", min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=20)


class RetrievalEvaluationRunRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    dataset_id: str | None = Field(default=None, max_length=36)
    dataset_version: int | None = Field(default=None, ge=1)
    dataset_snapshot_id: str | None = Field(default=None, max_length=36)
    top_k: int = Field(default=5, ge=1, le=20)
    cases: list[RetrievalEvaluationCase] = Field(..., min_length=1, max_length=200)


class FixEvaluationCase(BaseModel):
    case_id: str | None = Field(default=None, max_length=128)
    repo_id: str = Field(..., min_length=1, max_length=36)
    issue: str = Field(..., min_length=1, max_length=20000)
    test_command: str | None = Field(default=None, max_length=255)
    expected_status: Literal[
        "verified_success",
        "unverified_patch",
        "not_reproduced",
        "failed",
        "infra_error",
    ] = "verified_success"
    expected_diff_contains: list[str] = Field(default_factory=list, max_length=20)
    allowed_changed_files: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default="unspecified", min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("expected_status", mode="before")
    @classmethod
    def normalize_legacy_success(cls, value: object) -> object:
        # Historical datasets used `success` before baseline reproduction became mandatory.
        return "verified_success" if value == "success" else value


class FixEvaluationRunRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    dataset_id: str | None = Field(default=None, max_length=36)
    dataset_version: int | None = Field(default=None, ge=1)
    dataset_snapshot_id: str | None = Field(default=None, max_length=36)
    require_tests_ran: bool = True
    cases: list[FixEvaluationCase] = Field(..., min_length=1, max_length=50)


class EvaluationDatasetRunRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    top_k: int = Field(default=5, ge=1, le=20)
    require_tests_ran: bool = True


class EvaluationSnapshotBackfillRequest(BaseModel):
    run_id: str | None = Field(default=None, max_length=36)
    task_type: EvaluationTaskType | None = None
    limit: int | None = Field(default=None, ge=1, le=1000)
    dry_run: bool = True
    create_missing_snapshots: bool = True
    include_details: bool = True


class EvaluationSnapshotBackfillResultRead(BaseModel):
    dry_run: bool
    scanned: int
    backfilled: int
    skipped: int
    created_snapshots: int
    status_counts: dict[str, int]
    details: list[dict] = []


class EvaluationGatePolicy(BaseModel):
    max_primary_metric_drop: float = Field(default=0.0, ge=0.0, le=1.0)
    max_regressed_cases: int = Field(default=0, ge=0)
    allow_incompatible: bool = False
    require_matching_dataset_snapshot: bool = True
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


class EvaluationDatasetSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    name: str
    task_type: EvaluationTaskType
    description: str | None
    version: int
    baseline_run_id: str | None
    gate_policy_json: EvaluationGatePolicy
    cases_json: list[dict]
    metadata_json: dict
    created_at: datetime


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
    dataset_snapshot_id: str | None
    case_count: int
    passed_count: int
    failed_count: int
    metrics_json: dict
    config_snapshot: dict
    request_json: dict
    created_at: datetime
    finished_at: datetime | None
    results: list[EvaluationResultRead] = []


class EvaluationRunArtifactMetadata(BaseModel):
    id: str
    name: str | None
    task_type: EvaluationTaskType
    status: EvaluationRunStatus
    dataset_id: str | None
    dataset_version: int | None
    dataset_snapshot_id: str | None
    case_count: int
    passed_count: int
    failed_count: int
    metrics_json: dict
    config_snapshot: dict
    request_json: dict
    created_at: datetime
    finished_at: datetime | None


class EvaluationArtifactStepRead(BaseModel):
    id: str
    step_type: str
    tool_name: str | None
    input_json: dict | list | None
    output_json: dict | list | None
    duration_ms: int | None
    created_at: datetime


class EvaluationArtifactAgentTraceRead(BaseModel):
    run_id: str
    status: str
    user_input: str
    test_command: str | None
    iterations: int
    final_summary: str | None
    failure_reason: str | None
    test_result: dict | None
    steps_by_type: dict[str, int]
    steps: list[EvaluationArtifactStepRead]


class EvaluationArtifactCaseRead(BaseModel):
    evaluation_id: str
    case_id: str | None
    repo_id: str | None
    task_type: EvaluationTaskType
    prompt: str | None
    expected_file: str | None
    expected_lines: dict | list | None
    status: str | None
    passed: bool | None
    score: float | None
    latency_ms: int | None
    failure_category: str | None
    provider: str | None
    model: str | None
    metadata_json: dict
    result_json: dict | list | None
    agent_trace: EvaluationArtifactAgentTraceRead | None


class EvaluationRunArtifactRead(BaseModel):
    artifact_version: str
    generated_at: datetime
    run: EvaluationRunArtifactMetadata
    summary: dict
    cases: list[EvaluationArtifactCaseRead]


class EvaluationHistoryRunRead(BaseModel):
    id: str
    name: str | None
    task_type: EvaluationTaskType
    status: EvaluationRunStatus
    dataset_version: int | None
    dataset_snapshot_id: str | None
    gate_status: Literal["passed", "failed", "inconclusive", "not_evaluated"]
    primary_metric_name: str
    primary_metric_value: float | int | None
    primary_metric_delta: float | int | None
    pass_rate: float | None
    case_count: int
    passed_count: int
    failed_count: int
    avg_latency_sec: float | int | None
    avg_tool_calls: float | int | None
    failure_distribution: dict[str, int]
    regressions: int | None
    improvements: int | None
    provider: str | None
    model: str | None
    created_at: datetime
    finished_at: datetime | None


class EvaluationHistoryRead(BaseModel):
    dataset: EvaluationDatasetRead
    baseline_run_id: str | None
    primary_metric_name: str
    filters: dict
    summary: dict
    gate_status_counts: dict[str, int]
    runs: list[EvaluationHistoryRunRead]


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


class CapabilityBenchmarkEvidenceRead(BaseModel):
    capability: BenchmarkGatedCapability
    status: Literal["admitted"]
    dataset_id: str
    dataset_version: int
    baseline_run_id: str
    candidate_run_id: str
    candidate_config_snapshot: dict
    primary_metric: str
    primary_metric_delta: float
    checks: list[EvaluationGateCheckRead]
    comparison: EvaluationRunCompareRead
