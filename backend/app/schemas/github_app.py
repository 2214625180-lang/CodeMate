from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GitHubAppFailedCIRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=36)
    installation_id: str = Field(min_length=1, max_length=36)
    workflow_run_id: str = Field(min_length=1, max_length=36)


class GitHubAppRepairDecisionRequest(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=2_000)


class GitHubAppRepairRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_id: str
    run_id: str
    repository_full_name: str
    workflow_run_id: str
    workflow_url: str | None
    head_sha: str
    base_branch: str
    failure_summary: dict
    status: Literal[
        "fixing",
        "waiting_approval",
        "rejected",
        "creating_draft",
        "draft_pr_created",
        "fix_failed",
        "failed",
    ]
    approval_note: str | None
    approved_by: str | None
    approved_at: datetime | None
    branch_name: str | None
    pull_request_number: int | None
    pull_request_url: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
