from typing import Literal

from pydantic import BaseModel, Field


class MCPTenantCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=255)


class MCPMembershipCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=255)
    role: Literal["admin", "approver", "member"] = "member"


class MCPServerBindingCreate(BaseModel):
    server_name: str = Field(min_length=1, max_length=64)
    enabled: bool = True


class MCPAccessGrantCreate(BaseModel):
    repo_id: str | None = Field(default=None, max_length=36)
    principal_type: Literal["user", "role", "service", "agent", "*"]
    principal_id: str = Field(min_length=1, max_length=255)
    server_name: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(default="*", min_length=1, max_length=128)
    permissions: list[Literal["discover", "execute", "approve"]] = Field(min_length=1)
    effect: Literal["allow", "deny"] = "allow"
    expires_at: str | None = None


class MCPDelegatedProviderWrite(BaseModel):
    server_name: str = Field(min_length=1, max_length=64)
    authorization_url: str = Field(max_length=2048)
    token_url: str = Field(max_length=2048)
    client_id: str = Field(max_length=1024)
    client_secret: str | None = Field(default=None, max_length=10000)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    redirect_uri: str = Field(max_length=2048)
