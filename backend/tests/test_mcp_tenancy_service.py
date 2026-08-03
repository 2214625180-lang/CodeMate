from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.api.routes.mcp_client import get_mcp_client_service
from fastapi import HTTPException
from app.mcp.client import MCPRemoteServerConfig
from app.models.mcp_access_grant import MCPAccessGrant
from app.models.mcp_tenant import MCPTenant
from app.models.mcp_tenant_membership import MCPTenantMembership
from app.models.mcp_tenant_server_binding import MCPTenantServerBinding
from app.services.mcp_tenancy_service import (
    MCPAuthorizationContext,
    MCPDelegatedIdentityError,
    MCPDelegatedIdentityService,
    MCPTenancyService,
    delegated_identity_binding,
    sha256,
)
from app.services.mcp_registry_service import MCPCredentialError, decrypt_payload


@pytest.fixture
def tenancy_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tenancy.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(settings, "mcp_tenant_authorization_enabled", True)
    monkeypatch.setattr(settings, "mcp_registry_master_key", "tenancy-master-key-32-characters-long")
    monkeypatch.setattr(settings, "mcp_registry_require_https", True)
    monkeypatch.setattr(settings, "mcp_registry_allow_private_networks", False)
    monkeypatch.setattr(settings, "mcp_registry_allowed_hosts", "")
    tenant = MCPTenant(slug="acme", name="Acme")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    yield db, tenant
    db.close()


def add_policy(db, tenant, *, principal_type="agent", principal_id="codemate-agent", effect="allow"):
    db.add(MCPTenantServerBinding(tenant_id=tenant.id, server_name="docs", enabled=True))
    db.add(
        MCPAccessGrant(
            tenant_id=tenant.id,
            principal_type=principal_type,
            principal_id=principal_id,
            server_name="docs",
            tool_name="search",
            permissions_json=["discover", "execute", "approve"],
            effect=effect,
            created_by="test",
        )
    )
    db.commit()


def test_tenant_policy_is_default_deny_filters_tools_and_honors_explicit_deny(tenancy_db):
    db, tenant = tenancy_db
    service = MCPTenancyService(db)
    context = MCPAuthorizationContext(tenant.id, None, "agent", "codemate-agent")
    config = MCPRemoteServerConfig(
        name="docs",
        url="https://docs.example.com/mcp",
        allowed_tools=["search", "write"],
        tool_policies={"search": "auto", "write": "auto"},
    )

    assert service.filter_configs([config], context) == []
    add_policy(db, tenant)
    filtered = service.filter_configs([config], context)
    assert filtered[0].allowed_tools == ["search"]

    db.add(
        MCPAccessGrant(
            tenant_id=tenant.id,
            principal_type="agent",
            principal_id="codemate-agent",
            server_name="docs",
            tool_name="search",
            permissions_json=["execute"],
            effect="deny",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            created_by="test",
        )
    )
    db.commit()
    assert service.is_allowed(
        context, server_name="docs", tool_name="search", permission="execute"
    ) is False


def test_user_role_grant_is_scoped_by_identity_provider(tenancy_db):
    db, tenant = tenancy_db
    db.add(MCPTenantMembership(tenant_id=tenant.id, provider="github", subject="alice", role="approver"))
    add_policy(db, tenant, principal_type="role", principal_id="approver")
    service = MCPTenancyService(db)

    assert service.is_allowed(
        MCPAuthorizationContext(tenant.id, None, "user", "alice", "github"),
        server_name="docs",
        tool_name="search",
        permission="approve",
    )
    assert not service.is_allowed(
        MCPAuthorizationContext(tenant.id, None, "user", "alice", "gitlab"),
        server_name="docs",
        tool_name="search",
        permission="approve",
    )


def test_delegated_oauth_pkce_one_time_proof_refresh_and_revoke(tenancy_db, monkeypatch):
    db, tenant = tenancy_db
    service = MCPDelegatedIdentityService(db)
    provider = service.configure_provider(
        tenant_id=tenant.id,
        server_name="docs",
        authorization_url="https://oauth.example.com/authorize?audience=mcp",
        token_url="https://oauth.example.com/token",
        client_id="codemate",
        client_secret="secret",
        scopes=["mcp.read"],
        redirect_uri="https://codemate.example.com/mcp-tenancy/oauth/callback",
    )
    authorization = service.start_authorization(
        provider.id, subject_provider="github", subject="alice"
    )["authorization_url"]
    query = parse_qs(urlsplit(authorization).query)
    assert query["audience"] == ["mcp"]
    assert query["code_challenge_method"] == ["S256"]

    responses = [
        {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1},
        {"access_token": "access-2", "expires_in": 3600},
    ]

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return responses.pop(0)

    monkeypatch.setattr(
        "app.services.mcp_tenancy_service.validate_registry_url",
        lambda *_args, **_kwargs: None,
    )
    fail_once = [True]

    def exchange(*_args, **_kwargs):
        if fail_once[0]:
            fail_once[0] = False
            raise RuntimeError("temporary OAuth outage")
        return Response()

    monkeypatch.setattr("app.services.mcp_tenancy_service.httpx.post", exchange)
    with pytest.raises(MCPDelegatedIdentityError, match="token exchange failed"):
        service.complete_authorization(code="code", state=query["state"][0])
    completed = service.complete_authorization(code="code", state=query["state"][0])
    identity_id = completed["identity"]["id"]
    proof = completed["delegation_token"]
    identity = service.verify_for_run(identity_id, proof, tenant_id=tenant.id)
    token_payload = decrypt_payload(
        identity.encrypted_token_payload,
        binding=delegated_identity_binding(identity.id),
    )
    assert token_payload["access_token"] == "access-1"
    with pytest.raises(MCPCredentialError):
        decrypt_payload(
            identity.encrypted_token_payload,
            binding=delegated_identity_binding("different-identity"),
        )
    identity.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    assert service.access_token(identity_id) == "access-2"
    service.revoke(identity_id)
    with pytest.raises(MCPDelegatedIdentityError):
        service.verify_for_run(identity_id, proof, tenant_id=tenant.id)


def test_direct_mcp_client_requires_tenant_bound_token_and_service_grant(
    tenancy_db, monkeypatch
):
    db, tenant = tenancy_db
    tenant.client_token_hash = sha256("tenant-secret")
    db.add(tenant)
    add_policy(db, tenant, principal_type="service", principal_id="mcp-client")
    monkeypatch.setattr(settings, "mcp_registry_enabled", False)
    monkeypatch.setattr(
        settings,
        "mcp_client_servers_json",
        '[{"name":"docs","url":"https://docs.example.com/mcp",'
        '"allowed_tools":["search","write"]}]',
    )

    client = get_mcp_client_service(db, tenant.id, "tenant-secret", None)
    assert client.servers[0].allowed_tools == ["search"]
    with pytest.raises(HTTPException) as denied:
        get_mcp_client_service(db, tenant.id, "wrong", None)
    assert denied.value.status_code == 403
