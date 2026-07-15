from typing import Any, Literal

from pydantic import BaseModel, Field


class MCPRegistryServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    tool_policies: dict[str, Literal["auto", "approval_required", "deny"]] = Field(
        default_factory=dict
    )
    agent_context_tools: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    idempotency_mode: Literal["none", "metadata"] = "none"


class MCPRegistryServerUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool | None = None
    allowed_tools: list[str] | None = Field(default=None, max_length=100)
    tool_policies: dict[str, Literal["auto", "approval_required", "deny"]] | None = None
    agent_context_tools: list[dict[str, Any]] | None = Field(default=None, max_length=10)
    idempotency_mode: Literal["none", "metadata"] | None = None


class MCPRegistryDeleteRequest(BaseModel):
    expected_version: int = Field(ge=1)


class MCPCredentialWriteRequest(BaseModel):
    auth_type: Literal["bearer", "oauth2_client_credentials"]
    token: str | None = Field(default=None, max_length=10000)
    token_url: str | None = Field(default=None, max_length=2048)
    client_id: str | None = Field(default=None, max_length=1024)
    client_secret: str | None = Field(default=None, max_length=10000)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    expected_version: int | None = Field(default=None, ge=1)


class MCPRevisionRestoreRequest(BaseModel):
    expected_version: int = Field(ge=1)
