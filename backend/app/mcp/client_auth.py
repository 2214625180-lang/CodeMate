import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_mcp_client_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.mcp_client_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP client is disabled",
        )

    expected_token = (settings.mcp_client_api_token or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP client API authentication is not configured",
        )

    provided_token = bearer_token(authorization)
    if provided_token is None or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid MCP client API Bearer token required",
            headers={"WWW-Authenticate": 'Bearer realm="codemate-mcp-client"'},
        )


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer":
        token = value.strip()
        return token or None
    return None

