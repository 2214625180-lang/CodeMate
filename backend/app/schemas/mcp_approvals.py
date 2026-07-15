from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MCPApprovalRead(BaseModel):
    id: str
    run_id: str
    qualified_name: str
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    arguments_hash: str
    policy_snapshot: str
    status: str
    decision: str | None
    decision_note: str | None
    decided_by: str | None
    decided_provider: str | None
    version: int
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    execution_started_at: datetime | None
    execution_finished_at: datetime | None
    result: dict[str, Any] | None
    error_message: str | None


class MCPApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class MCPApprovalResumeResponse(BaseModel):
    approval_id: str
    status: str
    job_id: str | None

