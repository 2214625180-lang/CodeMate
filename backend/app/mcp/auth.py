import json
import secrets
from collections.abc import Callable

from starlette.types import ASGIApp, Receive, Scope, Send


class MCPBearerAuthMiddleware:
    """Fail-closed Bearer authentication for the mounted MCP ASGI app."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token_provider: Callable[[], str | None],
    ) -> None:
        self.app = app
        self.token_provider = token_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        expected_token = (self.token_provider() or "").strip()
        if not expected_token:
            await self._json_response(
                send,
                status_code=503,
                detail="MCP authentication is not configured",
            )
            return

        provided_token = self._bearer_token(scope)
        if provided_token is None or not secrets.compare_digest(provided_token, expected_token):
            await self._json_response(
                send,
                status_code=401,
                detail="Valid MCP Bearer token required",
                authenticate=True,
            )
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _bearer_token(scope: Scope) -> str | None:
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() != b"authorization":
                continue
            authorization = raw_value.decode("latin-1")
            scheme, separator, value = authorization.partition(" ")
            if separator and scheme.lower() == "bearer":
                token = value.strip()
                return token or None
        return None

    @staticmethod
    async def _json_response(
        send: Send,
        *,
        status_code: int,
        detail: str,
        authenticate: bool = False,
    ) -> None:
        payload = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ]
        if authenticate:
            headers.append((b"www-authenticate", b'Bearer realm="codemate-mcp"'))
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": payload})
