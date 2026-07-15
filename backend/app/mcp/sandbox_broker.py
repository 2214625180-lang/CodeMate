import secrets
import json
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.core.config import settings
from app.mcp.client import MCPClientService, MCPRemoteServerConfig
from app.mcp.egress import validate_egress_url


class SandboxServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    bearer_token: SecretStr | None = None
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    tool_policies: dict[str, str] = Field(default_factory=dict)
    idempotency_mode: Literal["none", "metadata"] = "none"
    registry_managed: bool = True


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["probe", "list_tools", "call_tool"]
    server: SandboxServer
    payload: dict[str, Any] = Field(default_factory=dict)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.mcp_sandbox_enabled or not settings.mcp_sandbox_broker_mode:
        raise RuntimeError("MCP sandbox broker mode is not enabled")
    settings.validate_security_config()
    yield


app = FastAPI(
    title="CodeMate MCP Sandbox Broker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def bound_request_body(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > settings.mcp_execution_max_checkpoint_chars
        except ValueError:
            too_large = True
        if too_large:
            return JSONResponse(
                {"detail": "MCP sandbox request body is too large"},
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "isolation": "sandbox-broker", "egress": "proxy-enforced"}


@app.post("/v1/execute")
async def execute(
    request: SandboxRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_broker_token(authorization)
    validate_egress_url(request.server.url)
    config = MCPRemoteServerConfig.model_validate(
        {
            **request.server.model_dump(exclude={"bearer_token"}),
            "bearer_token": request.server.bearer_token,
            "enabled": True,
        }
    )
    client = MCPClientService(
        servers=[config],
        sandbox_enabled=True,
        sandbox_broker_mode=True,
    )
    if request.operation == "probe":
        return bounded_response(await client.probe(config.name))
    if request.operation == "list_tools":
        return bounded_response({"tools": await client.list_tools(config.name)})
    tool_name = str(request.payload.get("tool_name") or "")
    if tool_name not in config.allowed_tools:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MCP sandbox tool is not allowlisted",
        )
    result = await client.call_tool(
        config.name,
        tool_name,
        request.payload.get("arguments") or {},
        idempotency_key=request.payload.get("idempotency_key"),
        execution_id=request.payload.get("execution_id"),
    )
    return {"result": result}


def bounded_response(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False, default=str)) > settings.mcp_client_max_result_chars:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="MCP sandbox response exceeded the configured size limit",
        )
    return value


def require_broker_token(authorization: str | None) -> None:
    scheme, separator, provided = (authorization or "").partition(" ")
    expected = (settings.mcp_sandbox_broker_token or "").strip()
    if (
        not expected
        or not separator
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(provided.strip(), expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid MCP sandbox broker token required",
            headers={"WWW-Authenticate": 'Bearer realm="codemate-mcp-sandbox"'},
        )
