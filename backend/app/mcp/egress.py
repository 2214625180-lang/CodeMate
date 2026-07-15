import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.config import settings


class MCPEgressDeniedError(RuntimeError):
    pass


@dataclass(frozen=True)
class EgressTarget:
    host: str
    port: int
    addresses: tuple[str, ...]


def resolve_egress_target(host: str, port: int) -> EgressTarget:
    normalized_host = host.strip().rstrip(".").lower()
    if not normalized_host:
        raise MCPEgressDeniedError("MCP egress host is required")
    if port not in settings.mcp_egress_port_allowlist:
        raise MCPEgressDeniedError(f"MCP egress port {port} is not allowed")
    allowlist = settings.mcp_registry_host_allowlist
    if not allowlist or normalized_host not in allowlist:
        raise MCPEgressDeniedError("MCP egress host is not explicitly allowlisted")
    try:
        candidates = [str(ipaddress.ip_address(normalized_host))]
    except ValueError:
        try:
            candidates = [
                item[4][0]
                for item in socket.getaddrinfo(
                    normalized_host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            ]
        except OSError as exc:
            raise MCPEgressDeniedError(f"MCP egress DNS resolution failed: {exc}") from exc
    addresses = tuple(dict.fromkeys(candidates))
    if not addresses:
        raise MCPEgressDeniedError("MCP egress DNS resolution returned no addresses")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise MCPEgressDeniedError("MCP egress resolved an invalid address") from exc
        if not ip.is_global:
            raise MCPEgressDeniedError(
                f"MCP egress resolved a non-global address for {normalized_host}"
            )
    return EgressTarget(normalized_host, port, addresses)


def validate_egress_url(url: str) -> EgressTarget:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise MCPEgressDeniedError("MCP egress requires an HTTPS URL")
    if parts.username or parts.password or parts.fragment:
        raise MCPEgressDeniedError("MCP egress URL contains forbidden components")
    return resolve_egress_target(parts.hostname, parts.port or 443)


def egress_httpx_proxy() -> httpx.Proxy | None:
    if not settings.mcp_sandbox_enabled:
        return None
    proxy_url = (settings.mcp_egress_proxy_url or "").strip()
    proxy_token = (settings.mcp_egress_proxy_token or "").strip()
    if not proxy_url or not proxy_token:
        raise MCPEgressDeniedError("MCP egress proxy authentication is not configured")
    return httpx.Proxy(proxy_url, auth=("codemate", proxy_token))
