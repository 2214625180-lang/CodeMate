import base64

import pytest

from app.core.config import settings
from app.mcp.egress import MCPEgressDeniedError, resolve_egress_target, validate_egress_url
from app.mcp.egress_gateway import parse_authority, valid_proxy_token


def configure_policy(monkeypatch):
    monkeypatch.setattr(settings, "mcp_registry_allowed_hosts", "mcp.example.com")
    monkeypatch.setattr(settings, "mcp_egress_allowed_ports", "443")


def test_egress_policy_allows_only_allowlisted_global_tls_targets(monkeypatch):
    configure_policy(monkeypatch)
    monkeypatch.setattr(
        "app.mcp.egress.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )

    target = validate_egress_url("https://mcp.example.com/tools")

    assert target.host == "mcp.example.com"
    assert target.port == 443
    assert target.addresses == ("93.184.216.34",)
    with pytest.raises(MCPEgressDeniedError, match="allowlisted"):
        validate_egress_url("https://evil.example.com/mcp")
    with pytest.raises(MCPEgressDeniedError, match="HTTPS"):
        validate_egress_url("http://mcp.example.com/mcp")


def test_egress_policy_rejects_dns_rebinding_to_private_address(monkeypatch):
    configure_policy(monkeypatch)
    monkeypatch.setattr(
        "app.mcp.egress.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )

    with pytest.raises(MCPEgressDeniedError, match="non-global"):
        resolve_egress_target("mcp.example.com", 443)


def test_gateway_requires_scoped_basic_proxy_auth(monkeypatch):
    monkeypatch.setattr(settings, "mcp_egress_proxy_token", "e" * 32)
    encoded = base64.b64encode(f"codemate:{'e' * 32}".encode()).decode()

    assert valid_proxy_token(f"Basic {encoded}") is True
    assert valid_proxy_token("Basic invalid") is False
    assert parse_authority("mcp.example.com:443") == ("mcp.example.com", 443)
    assert parse_authority("[2001:4860:4860::8888]:443") == (
        "2001:4860:4860::8888",
        443,
    )
