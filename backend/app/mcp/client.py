import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Callable, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator, model_validator

from app.core.config import settings

SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MCPToolPolicyMode = Literal["auto", "approval_required", "deny"]
MCPIdempotencyMode = Literal["none", "metadata"]


class MCPClientError(RuntimeError):
    pass


class MCPClientConfigurationError(MCPClientError):
    pass


class MCPRemoteServerNotFoundError(MCPClientError):
    pass


class MCPToolNotAllowedError(MCPClientError):
    pass


class MCPAgentContextTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPRemoteServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: HttpUrl
    bearer_token_env: str | None = None
    bearer_token: SecretStr | None = Field(default=None, exclude=True)
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    tool_policies: dict[str, MCPToolPolicyMode] = Field(default_factory=dict)
    agent_context_tools: list[MCPAgentContextTool] = Field(default_factory=list, max_length=10)
    idempotency_mode: MCPIdempotencyMode = "none"
    registry_managed: bool = False
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not SERVER_NAME_PATTERN.fullmatch(value):
            raise ValueError("name must contain only letters, digits, underscores, and hyphens")
        return value

    @field_validator("bearer_token_env")
    @classmethod
    def valid_token_env(cls, value: str | None) -> str | None:
        if value is not None and not ENV_NAME_PATTERN.fullmatch(value):
            raise ValueError("bearer_token_env must be a valid environment variable name")
        return value

    @field_validator("allowed_tools")
    @classmethod
    def unique_allowed_tools(cls, value: list[str]) -> list[str]:
        normalized = [tool.strip() for tool in value if tool.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_tools must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def agent_tools_are_allowed(self):
        if self.url.username or self.url.password:
            raise ValueError("MCP server URL must not contain credentials")
        allowed = set(self.allowed_tools)
        unknown_policy_tools = sorted(set(self.tool_policies) - allowed)
        if unknown_policy_tools:
            raise ValueError(
                "tool_policies keys must also appear in allowed_tools: "
                + ", ".join(unknown_policy_tools)
            )
        invalid = sorted({item.tool for item in self.agent_context_tools} - allowed)
        if invalid:
            raise ValueError(
                "agent_context_tools must also appear in allowed_tools: " + ", ".join(invalid)
            )
        unsafe_context_tools = sorted(
            item.tool
            for item in self.agent_context_tools
            if self.tool_policies.get(item.tool) != "auto"
        )
        if unsafe_context_tools:
            raise ValueError(
                "agent_context_tools require an explicit auto policy: "
                + ", ".join(unsafe_context_tools)
            )
        if self.bearer_token and self.bearer_token_env:
            raise ValueError("bearer_token and bearer_token_env are mutually exclusive")
        return self


class MCPClientService:
    def __init__(
        self,
        *,
        servers_json: str | None = None,
        servers: list[MCPRemoteServerConfig] | None = None,
        timeout_seconds: float | None = None,
        max_result_chars: int | None = None,
        quota_reserve: Callable[[str, str, dict[str, Any], str | None, str | None], Any]
        | None = None,
        quota_release: Callable[[Any, str], None] | None = None,
        sandbox_enabled: bool | None = None,
        sandbox_broker_mode: bool | None = None,
    ) -> None:
        self.servers = (
            list(servers)
            if servers is not None
            else parse_server_configs(
                settings.mcp_client_servers_json if servers_json is None else servers_json
            )
        )
        self.timeout_seconds = max(1.0, timeout_seconds or settings.mcp_client_timeout_seconds)
        self.max_result_chars = max(
            1000,
            max_result_chars or settings.mcp_client_max_result_chars,
        )
        self.quota_reserve = quota_reserve
        self.quota_release = quota_release
        self.sandbox_enabled = (
            settings.mcp_sandbox_enabled if sandbox_enabled is None else sandbox_enabled
        )
        self.sandbox_broker_mode = (
            settings.mcp_sandbox_broker_mode
            if sandbox_broker_mode is None
            else sandbox_broker_mode
        )

    def configured_servers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": server.name,
                "url": public_server_url(server.url),
                "enabled": server.enabled,
                "authentication": (
                    "credential_broker"
                    if server.bearer_token
                    else ("bearer_env" if server.bearer_token_env else "none")
                ),
                "allowed_tools": server.allowed_tools,
                "tool_policies": server.tool_policies,
                "agent_context_tools": [item.tool for item in server.agent_context_tools],
                "idempotency_mode": server.idempotency_mode,
                "source": "registry" if server.registry_managed else "static",
            }
            for server in self.servers
        ]

    async def probe(self, server_name: str) -> dict[str, Any]:
        server = self._server(server_name)
        if self._use_sandbox_broker:
            return await self._sandbox_request("probe", server)
        async with self._session(server) as (session, initialize_result):
            return {
                "name": server.name,
                "url": public_server_url(server.url),
                "connected": True,
                "protocol_version": initialize_result.protocolVersion,
                "server_info": initialize_result.serverInfo.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                "capabilities": initialize_result.capabilities.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            }

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        server = self._server(server_name)
        if self._use_sandbox_broker:
            result = await self._sandbox_request("list_tools", server)
            return list(result.get("tools") or [])
        tools: list[dict[str, Any]] = []
        async with self._session(server) as (session, _initialize_result):
            cursor: str | None = None
            for _page in range(10):
                result = await session.list_tools(cursor=cursor)
                tools.extend(
                    {
                        "name": tool.name,
                        "title": tool.title,
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                        "output_schema": tool.outputSchema,
                        "annotations": (
                            tool.annotations.model_dump(
                                mode="json", by_alias=True, exclude_none=True
                            )
                            if tool.annotations
                            else None
                        ),
                        "allowed": tool.name in server.allowed_tools,
                    }
                    for tool in result.tools
                )
                cursor = result.nextCursor
                if not cursor:
                    break
        return tools

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        server = self._server(server_name)
        if tool_name not in server.allowed_tools:
            raise MCPToolNotAllowedError(
                f"Tool '{tool_name}' is not allowed for MCP server '{server_name}'"
            )
        normalized_arguments = arguments or {}
        reservation = (
            self.quota_reserve(
                server_name,
                tool_name,
                normalized_arguments,
                idempotency_key,
                execution_id,
            )
            if self.quota_reserve
            else None
        )
        try:
            if self._use_sandbox_broker:
                payload = await self._sandbox_request(
                    "call_tool",
                    server,
                    {
                        "tool_name": tool_name,
                        "arguments": normalized_arguments,
                        "idempotency_key": idempotency_key,
                        "execution_id": execution_id,
                    },
                )
                payload = dict(payload.get("result") or {})
            else:
                async with self._session(server) as (session, _initialize_result):
                    result = await session.call_tool(
                        tool_name,
                        normalized_arguments,
                        read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                        meta=execution_meta(idempotency_key, execution_id),
                    )
                payload = self._bounded_tool_result(
                    result.model_dump(mode="json", by_alias=True)
                )
        except Exception:
            self._release_quota(reservation, "transport_unknown")
            raise
        self._release_quota(reservation, "failed" if payload.get("isError") else "succeeded")
        return payload

    def idempotency_mode(self, server_name: str) -> MCPIdempotencyMode:
        return self._server(server_name).idempotency_mode

    def collect_agent_context(self, *, issue: str, repo_id: str) -> list[dict[str, Any]]:
        configured = [server for server in self.servers if server.agent_context_tools]
        if not configured:
            return []
        return asyncio.run(self._collect_agent_context(issue=issue, repo_id=repo_id))

    async def _collect_agent_context(self, *, issue: str, repo_id: str) -> list[dict[str, Any]]:
        context: list[dict[str, Any]] = []
        variables = {"issue": issue, "repo_id": repo_id}
        for server in self.servers:
            if not server.enabled:
                continue
            for item in server.agent_context_tools:
                arguments = render_arguments(item.arguments, variables)
                try:
                    result = await self.call_tool(server.name, item.tool, arguments)
                    context.append(
                        {
                            "server": server.name,
                            "tool": item.tool,
                            "arguments": arguments,
                            "result": result,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - optional context must fail soft.
                    context.append(
                        {
                            "server": server.name,
                            "tool": item.tool,
                            "arguments": arguments,
                            "error": str(exc),
                        }
                    )
        return context

    def _server(self, server_name: str) -> MCPRemoteServerConfig:
        for server in self.servers:
            if server.enabled and server.name == server_name:
                return server
        raise MCPRemoteServerNotFoundError(f"MCP server '{server_name}' is not configured")

    @property
    def _use_sandbox_broker(self) -> bool:
        return self.sandbox_enabled and not self.sandbox_broker_mode

    async def _sandbox_request(
        self,
        operation: str,
        server: MCPRemoteServerConfig,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        broker_url = (settings.mcp_sandbox_broker_url or "").rstrip("/")
        token = (settings.mcp_sandbox_broker_token or "").strip()
        if not broker_url or not token:
            raise MCPClientConfigurationError("MCP sandbox broker is not configured")
        request_payload = {
            "operation": operation,
            "server": {
                "name": server.name,
                "url": str(server.url),
                "allowed_tools": server.allowed_tools,
                "tool_policies": server.tool_policies,
                "idempotency_mode": server.idempotency_mode,
                "registry_managed": server.registry_managed,
                "bearer_token": (
                    server.bearer_token.get_secret_value()
                    if server.bearer_token
                    else self._environment_bearer_token(server)
                ),
            },
            "payload": payload or {},
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{broker_url}/v1/execute",
                    headers={"Authorization": f"Bearer {token}"},
                    json=request_payload,
                )
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise MCPClientError("MCP sandbox returned a non-object response")
                return result
        except MCPClientError:
            raise
        except Exception as exc:
            raise MCPClientError(f"MCP sandbox execution failed: {exc}") from exc

    @staticmethod
    def _environment_bearer_token(server: MCPRemoteServerConfig) -> str | None:
        if not server.bearer_token_env:
            return None
        token = (os.getenv(server.bearer_token_env) or "").strip()
        if not token:
            raise MCPClientConfigurationError(
                f"Environment variable '{server.bearer_token_env}' is not configured"
            )
        return token

    @asynccontextmanager
    async def _session(
        self,
        server: MCPRemoteServerConfig,
    ) -> AsyncIterator[tuple[ClientSession, Any]]:
        headers = {"Accept": "application/json, text/event-stream"}
        proxy = None
        if self.sandbox_broker_mode:
            from app.mcp.egress import validate_egress_url

            validate_egress_url(str(server.url))
            proxy_url = (settings.mcp_egress_proxy_url or "").strip()
            proxy_token = (settings.mcp_egress_proxy_token or "").strip()
            if not proxy_url or not proxy_token:
                raise MCPClientConfigurationError("MCP egress proxy is not configured")
            proxy = httpx.Proxy(proxy_url, auth=("codemate", proxy_token))
        if server.registry_managed:
            from app.services.mcp_registry_service import validate_registry_url

            validate_registry_url(str(server.url), resolve_dns=True)
        if server.bearer_token:
            headers["Authorization"] = f"Bearer {server.bearer_token.get_secret_value()}"
        elif server.bearer_token_env:
            token = (os.getenv(server.bearer_token_env) or "").strip()
            if not token:
                raise MCPClientConfigurationError(
                    f"Environment variable '{server.bearer_token_env}' is not configured"
                )
            headers["Authorization"] = f"Bearer {token}"

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            # Redirect targets have not passed registry DNS/SSRF validation. Keeping
            # redirects disabled also prevents bearer credentials from crossing an
            # MCP server trust boundary through a 30x response.
            follow_redirects=False,
            proxy=proxy,
            trust_env=False,
        ) as http_client:
            try:
                async with streamable_http_client(
                    str(server.url),
                    http_client=http_client,
                ) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                    ) as session:
                        initialize_result = await session.initialize()
                        yield session, initialize_result
            except MCPClientError:
                raise
            except Exception as exc:
                raise MCPClientError(
                    f"Failed to communicate with MCP server '{server.name}': {exc}"
                ) from exc

    def _bounded_tool_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if len(serialized) <= self.max_result_chars:
            payload["truncated"] = False
            return payload
        return {
            "isError": bool(payload.get("isError")),
            "content": [
                {
                    "type": "text",
                    "text": serialized[: self.max_result_chars],
                }
            ],
            "truncated": True,
        }

    def _release_quota(self, reservation: Any, outcome: str) -> None:
        if reservation is None or self.quota_release is None:
            return
        try:
            self.quota_release(reservation, outcome)
        except Exception:  # noqa: BLE001 - never obscure a remote MCP outcome.
            pass


def parse_server_configs(raw_json: str) -> list[MCPRemoteServerConfig]:
    try:
        data = json.loads(raw_json or "[]")
    except json.JSONDecodeError as exc:
        raise MCPClientConfigurationError(f"Invalid MCP_CLIENT_SERVERS_JSON: {exc}") from exc
    if not isinstance(data, list):
        raise MCPClientConfigurationError("MCP_CLIENT_SERVERS_JSON must be a JSON array")
    if len(data) > 16:
        raise MCPClientConfigurationError("At most 16 MCP servers can be configured")
    try:
        servers = [MCPRemoteServerConfig.model_validate(item) for item in data]
    except Exception as exc:
        raise MCPClientConfigurationError(f"Invalid MCP server configuration: {exc}") from exc
    names = [server.name for server in servers]
    if len(names) != len(set(names)):
        raise MCPClientConfigurationError("MCP server names must be unique")
    return servers


def render_arguments(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for name, replacement in variables.items():
            rendered = rendered.replace("{" + name + "}", replacement)
        return rendered
    if isinstance(value, dict):
        return {str(key): render_arguments(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render_arguments(item, variables) for item in value]
    return value


def public_server_url(url: HttpUrl) -> str:
    parts = urlsplit(str(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def execution_meta(
    idempotency_key: str | None,
    execution_id: str | None,
) -> dict[str, Any] | None:
    if not idempotency_key and not execution_id:
        return None
    return {
        "codemate.io/idempotency-key": idempotency_key,
        "codemate.io/execution-id": execution_id,
    }
