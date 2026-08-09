from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentRunStatus = Literal[
    "pending",
    "running",
    "waiting_approval",
    "waiting_reconciliation",
    "verified_success",
    "unverified_patch",
    "not_reproduced",
    "failed",
    "infra_error",
]
FeedbackStatus = Literal["accepted", "rejected", "modified"]


class FixRequest(BaseModel):
    issue: str = Field(..., min_length=1, max_length=20000)
    test_command: str | None = Field(default=None, max_length=255)
    delegated_identity_id: str | None = Field(default=None, max_length=36)
    delegation_token: str | None = Field(default=None, max_length=512)


class FixResponse(BaseModel):
    run_id: str
    status: AgentRunStatus


class RunFeedbackRequest(BaseModel):
    status: FeedbackStatus
    note: str | None = Field(default=None, max_length=2000)


class RunFeedbackResponse(BaseModel):
    run_id: str
    feedback_status: FeedbackStatus
    feedback_note: str | None


class AgentStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    step_type: str
    tool_name: str | None
    input_json: Any
    output_json: Any
    input_classification: str | None = None
    output_classification: str | None = None
    duration_ms: int | None
    created_at: datetime


class AgentStepRestrictedRead(BaseModel):
    id: str
    run_id: str
    step_type: str
    tool_name: str | None
    input_json: Any
    output_json: Any
    input_classification: str
    output_classification: str
    payload_expires_at: datetime | None
    created_at: datetime


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_id: str
    task_type: str
    tenant_id: str | None
    principal_type: str
    principal_id: str
    delegated_identity_id: str | None
    user_input: str
    test_command: str | None
    status: AgentRunStatus
    final_diff: str | None
    final_summary: str | None
    failure_reason: str | None
    test_result: dict | None
    iterations: int
    feedback_status: str | None
    feedback_note: str | None
    feedback_at: datetime | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    steps: list[AgentStepRead] = []
