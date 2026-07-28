from typing import Literal

from pydantic import BaseModel, Field, model_validator


PrincipalType = Literal["user", "role", "service", "agent", "*"]


class MCPQuotaPolicyCreate(BaseModel):
    repo_id: str | None = Field(default=None, max_length=36)
    principal_type: PrincipalType = "*"
    principal_id: str = Field(default="*", min_length=1, max_length=255)
    server_name: str = Field(default="*", min_length=1, max_length=64)
    tool_name: str = Field(default="*", min_length=1, max_length=128)
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    daily_call_limit: int | None = Field(default=None, ge=1)
    daily_cost_limit: float | None = Field(default=None, gt=0)
    concurrent_limit: int | None = Field(default=None, ge=1)
    run_call_limit: int | None = Field(default=None, ge=1)
    max_run_duration_seconds: int | None = Field(default=None, ge=1)
    call_cost_units: float = Field(default=1.0, gt=0)
    warning_threshold: float = Field(default=0.8, gt=0, le=1)
    enabled: bool = True
    frozen: bool = False

    @model_validator(mode="after")
    def wildcard_principal_is_consistent(self):
        if self.principal_type == "*" and self.principal_id != "*":
            raise ValueError("Wildcard principal_type requires principal_id='*'")
        return self


class MCPQuotaPolicyUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    repo_id: str | None = Field(default=None, max_length=36)
    principal_type: PrincipalType | None = None
    principal_id: str | None = Field(default=None, min_length=1, max_length=255)
    server_name: str | None = Field(default=None, min_length=1, max_length=64)
    tool_name: str | None = Field(default=None, min_length=1, max_length=128)
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    daily_call_limit: int | None = Field(default=None, ge=1)
    daily_cost_limit: float | None = Field(default=None, gt=0)
    concurrent_limit: int | None = Field(default=None, ge=1)
    run_call_limit: int | None = Field(default=None, ge=1)
    max_run_duration_seconds: int | None = Field(default=None, ge=1)
    call_cost_units: float | None = Field(default=None, gt=0)
    warning_threshold: float | None = Field(default=None, gt=0, le=1)
    enabled: bool | None = None
    frozen: bool | None = None


class MCPQuotaResetRequest(BaseModel):
    expected_version: int = Field(ge=1)


class MCPQuotaTemporaryAdjustment(BaseModel):
    expected_version: int = Field(ge=1)
    duration_seconds: int = Field(ge=60, le=7 * 24 * 60 * 60)
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    daily_call_limit: int | None = Field(default=None, ge=1)
    daily_cost_limit: float | None = Field(default=None, gt=0)
    concurrent_limit: int | None = Field(default=None, ge=1)
    run_call_limit: int | None = Field(default=None, ge=1)
    max_run_duration_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def contains_an_override(self):
        values = self.model_dump(exclude={"expected_version", "duration_seconds"})
        if not any(value is not None for value in values.values()):
            raise ValueError("At least one temporary quota override is required")
        return self


class MCPQuotaReconcileRequest(BaseModel):
    repair: bool = False


class MCPQuotaRetentionRequest(BaseModel):
    retention_days: int = Field(default=90, ge=30, le=3650)
    dry_run: bool = True
