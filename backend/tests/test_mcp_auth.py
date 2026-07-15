from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from app.mcp.auth import MCPBearerAuthMiddleware


async def ok(_request):
    return JSONResponse({"ok": True})


def create_client(token: str | None = "test-mcp-token") -> TestClient:
    protected_app = MCPBearerAuthMiddleware(
        Starlette(routes=[Route("/", ok)]),
        token_provider=lambda: token,
    )
    app = Starlette(routes=[Mount("/mcp", protected_app)])
    return TestClient(app)


def test_mcp_auth_rejects_missing_token():
    response = create_client().get("/mcp/")

    assert response.status_code == 401
    assert response.json() == {"detail": "Valid MCP Bearer token required"}
    assert response.headers["www-authenticate"] == 'Bearer realm="codemate-mcp"'


def test_mcp_auth_rejects_wrong_scheme_and_wrong_token():
    client = create_client()

    assert client.get("/mcp/", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/mcp/", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_mcp_auth_accepts_valid_bearer_token():
    response = create_client().get(
        "/mcp/",
        headers={"Authorization": "Bearer test-mcp-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_mcp_auth_fails_closed_when_token_is_not_configured():
    response = create_client(token=None).get("/mcp/")

    assert response.status_code == 503
    assert response.json() == {"detail": "MCP authentication is not configured"}

