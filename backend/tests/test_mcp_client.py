from contextlib import asynccontextmanager

import pytest
from mcp.types import (
    CallToolResult,
    Implementation,
    InitializeResult,
    ListToolsResult,
    ServerCapabilities,
    TextContent,
    Tool,
    ToolAnnotations,
)

from app.mcp.client import (
    MCPClientConfigurationError,
    MCPClientService,
    MCPToolNotAllowedError,
    parse_server_configs,
    render_arguments,
)
import app.mcp.client as client_module

SERVER_CONFIG = """
[
  {
    "name": "docs",
    "url": "https://mcp.example.com/mcp",
    "allowed_tools": ["search_docs"],
    "tool_policies": {"search_docs": "auto"},
    "agent_context_tools": [
      {
        "tool": "search_docs",
        "arguments": {"query": "{issue}", "metadata": {"repo": "{repo_id}"}}
      }
    ]
  }
]
"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeSession:
    def __init__(self):
        self.calls = []

    async def list_tools(self, cursor=None):
        return ListToolsResult(
            tools=[
                Tool(
                    name="search_docs",
                    description="Search documentation",
                    inputSchema={"type": "object"},
                    annotations=ToolAnnotations(readOnlyHint=True),
                ),
                Tool(
                    name="delete_docs",
                    description="Delete documentation",
                    inputSchema={"type": "object"},
                ),
            ]
        )

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments, kwargs))
        return CallToolResult(
            content=[TextContent(type="text", text=f"result for {arguments['query']}")],
            structuredContent={"matches": 2},
        )


def initialized_server():
    return InitializeResult(
        protocolVersion="2025-11-25",
        capabilities=ServerCapabilities(),
        serverInfo=Implementation(name="fake-mcp", version="1.0.0"),
    )


def service_with_fake_session(session=None) -> MCPClientService:
    service = MCPClientService(servers_json=SERVER_CONFIG)
    fake_session_instance = session or FakeSession()

    @asynccontextmanager
    async def fake_session(_server):
        yield fake_session_instance, initialized_server()

    service._session = fake_session
    return service


def test_parse_server_configs_requires_unique_names_and_explicit_agent_allowlist():
    with pytest.raises(MCPClientConfigurationError, match="names must be unique"):
        parse_server_configs(
            '[{"name":"same","url":"https://one.example/mcp"},'
            '{"name":"same","url":"https://two.example/mcp"}]'
        )

    with pytest.raises(MCPClientConfigurationError, match="must also appear in allowed_tools"):
        parse_server_configs(
            '[{"name":"docs","url":"https://mcp.example/mcp",'
            '"agent_context_tools":[{"tool":"search","arguments":{}}]}]'
        )

    with pytest.raises(MCPClientConfigurationError, match="explicit auto policy"):
        parse_server_configs(
            '[{"name":"docs","url":"https://mcp.example/mcp",'
            '"allowed_tools":["search"],'
            '"agent_context_tools":[{"tool":"search","arguments":{}}]}]'
        )

    with pytest.raises(MCPClientConfigurationError, match="must not contain credentials"):
        parse_server_configs(
            '[{"name":"docs","url":"https://user:secret@mcp.example/mcp"}]'
        )


def test_render_arguments_replaces_only_known_agent_variables():
    rendered = render_arguments(
        {"query": "Fix {issue}", "nested": ["{repo_id}", "{unknown}"]},
        {"issue": "login", "repo_id": "repo-1"},
    )

    assert rendered == {
        "query": "Fix login",
        "nested": ["repo-1", "{unknown}"],
    }


@pytest.mark.anyio
async def test_client_discovers_tools_and_enforces_call_allowlist():
    service = service_with_fake_session()

    tools = await service.list_tools("docs")
    allowed_result = await service.call_tool("docs", "search_docs", {"query": "MCP"})

    assert [(tool["name"], tool["allowed"]) for tool in tools] == [
        ("search_docs", True),
        ("delete_docs", False),
    ]
    assert allowed_result["structuredContent"] == {"matches": 2}
    assert allowed_result["truncated"] is False
    with pytest.raises(MCPToolNotAllowedError):
        await service.call_tool("docs", "delete_docs", {})


@pytest.mark.anyio
async def test_client_probe_returns_negotiated_server_information():
    result = await service_with_fake_session().probe("docs")

    assert result["connected"] is True
    assert result["server_info"] == {"name": "fake-mcp", "version": "1.0.0"}
    assert result["protocol_version"] == "2025-11-25"


@pytest.mark.anyio
async def test_client_sends_stable_execution_metadata():
    session = FakeSession()
    service = service_with_fake_session(session)

    await service.call_tool(
        "docs",
        "search_docs",
        {"query": "MCP"},
        idempotency_key="stable-key",
        execution_id="execution-1",
    )

    assert session.calls[0][2]["meta"] == {
        "codemate.io/idempotency-key": "stable-key",
        "codemate.io/execution-id": "execution-1",
    }


@pytest.mark.anyio
async def test_client_reserves_and_releases_quota_around_remote_call():
    service = service_with_fake_session()
    lifecycle = []
    reservation = object()
    service.quota_reserve = lambda *args: lifecycle.append(("reserve", args)) or reservation
    service.quota_release = lambda value, outcome: lifecycle.append(
        ("release", value, outcome)
    )

    await service.call_tool(
        "docs",
        "search_docs",
        {"query": "quota"},
        idempotency_key="quota-key",
        execution_id="execution-1",
    )

    assert lifecycle[0][0] == "reserve"
    assert lifecycle[0][1][3:] == ("quota-key", "execution-1")
    assert lifecycle[1] == ("release", reservation, "succeeded")


@pytest.mark.anyio
async def test_client_never_follows_redirects_with_bearer_credentials(monkeypatch):
    captured = {}

    class FakeHTTPClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeClientSession:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def initialize(self):
            return initialized_server()

    @asynccontextmanager
    async def fake_transport(*_args, **_kwargs):
        yield object(), object(), lambda: None

    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(client_module, "streamable_http_client", fake_transport)
    monkeypatch.setattr(client_module, "ClientSession", FakeClientSession)
    server = client_module.MCPRemoteServerConfig(
        name="private",
        url="https://mcp.example.com/mcp",
        bearer_token="top-secret",
        allowed_tools=[],
    )
    service = MCPClientService(servers=[server])

    async with service._session(server):
        pass

    assert captured["follow_redirects"] is False
    assert captured["headers"]["Authorization"] == "Bearer top-secret"


def test_agent_context_uses_explicit_templates_and_allowed_tools():
    service = service_with_fake_session()

    context = service.collect_agent_context(issue="Login fails", repo_id="repo-42")

    assert context[0]["server"] == "docs"
    assert context[0]["tool"] == "search_docs"
    assert context[0]["arguments"] == {
        "query": "Login fails",
        "metadata": {"repo": "repo-42"},
    }
    assert context[0]["result"]["structuredContent"] == {"matches": 2}
