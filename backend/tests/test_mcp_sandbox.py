from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

import app.mcp.client as client_module
from app.core.config import settings
from app.mcp.client import MCPClientService
from app.mcp.sandbox_broker import app as sandbox_app


SERVER_CONFIG = """
[{"name":"docs","url":"https://mcp.example.com/mcp","allowed_tools":["search"]}]
"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_client_delegates_tool_call_to_authenticated_sandbox(monkeypatch):
    requests = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "result": {
                    "content": [{"type": "text", "text": "sandboxed"}],
                    "isError": False,
                    "truncated": False,
                }
            }

    class FakeHTTPClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return Response()

    monkeypatch.setattr(settings, "mcp_sandbox_broker_url", "http://mcp-sandbox:8090")
    monkeypatch.setattr(settings, "mcp_sandbox_broker_token", "b" * 32)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeHTTPClient)
    service = MCPClientService(servers_json=SERVER_CONFIG, sandbox_enabled=True)

    result = await service.call_tool("docs", "search", {"query": "MCP"})

    assert result["content"][0]["text"] == "sandboxed"
    assert requests[0][0] == "http://mcp-sandbox:8090/v1/execute"
    assert requests[0][1]["headers"]["Authorization"] == f"Bearer {'b' * 32}"
    assert requests[0][1]["json"]["operation"] == "call_tool"


@pytest.mark.anyio
async def test_sandbox_path_never_opens_direct_mcp_session(monkeypatch):
    service = MCPClientService(servers_json=SERVER_CONFIG, sandbox_enabled=True)

    @asynccontextmanager
    async def forbidden_session(_server):
        raise AssertionError("direct MCP session must not be used")
        yield  # pragma: no cover

    async def broker(_operation, _server, _payload=None):
        return {"tools": []}

    service._session = forbidden_session
    service._sandbox_request = broker

    assert await service.list_tools("docs") == []


def test_sandbox_broker_authenticates_and_rechecks_tool_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "mcp_sandbox_enabled", True)
    monkeypatch.setattr(settings, "mcp_sandbox_broker_mode", True)
    monkeypatch.setattr(settings, "mcp_sandbox_broker_token", "b" * 32)
    monkeypatch.setattr(settings, "mcp_egress_proxy_url", "http://mcp-egress:8080")
    monkeypatch.setattr(settings, "mcp_egress_proxy_token", "e" * 32)
    monkeypatch.setattr(settings, "mcp_registry_allowed_hosts", "mcp.example.com")
    monkeypatch.setattr("app.mcp.sandbox_broker.validate_egress_url", lambda _url: None)
    payload = {
        "operation": "call_tool",
        "server": {
            "name": "docs",
            "url": "https://mcp.example.com/mcp",
            "allowed_tools": ["search"],
        },
        "payload": {"tool_name": "delete", "arguments": {}},
    }
    with TestClient(sandbox_app) as client:
        unauthorized = client.post("/v1/execute", json=payload)
        denied = client.post(
            "/v1/execute",
            json=payload,
            headers={"Authorization": f"Bearer {'b' * 32}"},
        )

    assert unauthorized.status_code == 401
    assert denied.status_code == 403
