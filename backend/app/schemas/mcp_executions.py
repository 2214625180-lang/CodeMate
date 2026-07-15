from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MCPExecutionRead(BaseModel):
    id: str
    run_id: str
    approval_id: str | None
    qualified_name: str
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    arguments_hash: str
    idempotency_key: str
    idempotency_mode: str
    status: str
    attempt_count: int
    recovery_count: int
    retry_safe: bool
    lease_owner: str | None
    lease_expires_at: datetime | None
    result: dict[str, Any] | None
    error_message: str | None
    reconciliation_note: str | None
    reconciled_by: str | None
    reconciled_provider: str | None
    version: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    reconciled_at: datetime | None
    updated_at: datetime


class MCPExecutionReconcileRequest(BaseModel):
    action: Literal["confirm_succeeded", "confirm_failed", "retry"]
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)
    result: dict[str, Any] | None = None


class MCPExecutionReconcileResponse(BaseModel):
    execution: MCPExecutionRead
    job_id: str | None


class MCPExecutionResumeResponse(BaseModel):
    execution_id: str
    status: str
    job_id: str | None
