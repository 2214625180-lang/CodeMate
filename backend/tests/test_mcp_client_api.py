from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.mcp_client import get_mcp_client_service, router
from app.core.config import settings
from app.mcp.client import MCPToolNotAllowedError
from app.services.mcp_quota_service import MCPQuotaExceededError


class FakeMCPClientService:
    def configured_servers(self):
        return [{"name": "docs", "url": "https://mcp.example/mcp", "enabled": True}]

    async def probe(self, server_name):
        return {"name": server_name, "connected": True}

    async def list_tools(self, _server_name):
        return [{"name": "search_docs", "allowed": True}]

    async def call_tool(self, server_name, tool_name, arguments):
        if tool_name == "blocked":
            raise MCPToolNotAllowedError("blocked")
        if tool_name == "quota-blocked":
            raise MCPQuotaExceededError(
                "daily_call_limit",
                policy_id="policy-1",
                retry_after_seconds=30,
                detail="daily quota exceeded",
            )
        return {"server": server_name, "arguments": arguments, "isError": False}


def create_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "mcp_client_enabled", True)
    monkeypatch.setattr(settings, "mcp_client_api_token", "client-api-token")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_mcp_client_service] = FakeMCPClientService
    return TestClient(app)


def test_mcp_client_api_requires_bearer_authentication(monkeypatch):
    response = create_client(monkeypatch).get("/mcp-client/servers")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer realm="codemate-mcp-client"'


def test_mcp_client_api_lists_and_calls_configured_servers(monkeypatch):
    client = create_client(monkeypatch)
    headers = {"Authorization": "Bearer client-api-token"}

    servers = client.get("/mcp-client/servers", headers=headers)
    tools = client.get("/mcp-client/servers/docs/tools", headers=headers)
    called = client.post(
        "/mcp-client/servers/docs/call",
        headers=headers,
        json={"tool_name": "search_docs", "arguments": {"query": "MCP"}},
    )

    assert servers.status_code == 200
    assert servers.json()["servers"][0]["name"] == "docs"
    assert tools.json()["tools"] == [{"name": "search_docs", "allowed": True}]
    assert called.json()["result"]["arguments"] == {"query": "MCP"}


def test_mcp_client_api_maps_allowlist_failure_to_forbidden(monkeypatch):
    response = create_client(monkeypatch).post(
        "/mcp-client/servers/docs/call",
        headers={"Authorization": "Bearer client-api-token"},
        json={"tool_name": "blocked", "arguments": {}},
    )

    assert response.status_code == 403


def test_mcp_client_api_maps_quota_failure_to_429_with_retry_after(monkeypatch):
    response = create_client(monkeypatch).post(
        "/mcp-client/servers/docs/call",
        headers={"Authorization": "Bearer client-api-token"},
        json={"tool_name": "quota-blocked", "arguments": {}},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.json()["detail"]["reason"] == "daily_call_limit"
