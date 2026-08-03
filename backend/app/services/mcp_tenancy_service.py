import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.kms import envelope_is_unbound
from app.mcp.client import MCPRemoteServerConfig
from app.mcp.egress import egress_httpx_proxy, validate_egress_url
from app.models.agent_run import AgentRun
from app.models.mcp_access_grant import MCPAccessGrant
from app.models.mcp_delegated_identity import (
    MCPDelegatedIdentity,
    MCPDelegatedOAuthProvider,
    MCPDelegatedOAuthState,
)
from app.models.mcp_tenant import MCPTenant
from app.models.mcp_tenant_membership import MCPTenantMembership
from app.models.mcp_tenant_server_binding import MCPTenantServerBinding
from app.services.mcp_registry_service import (
    decrypt_payload,
    encrypt_payload,
    validate_registry_url,
)


class MCPTenancyError(RuntimeError):
    pass


class MCPAuthorizationDenied(MCPTenancyError):
    pass


class MCPDelegatedIdentityError(MCPTenancyError):
    pass


@dataclass(frozen=True)
class MCPAuthorizationContext:
    tenant_id: str
    repo_id: str | None
    principal_type: str
    principal_id: str
    principal_provider: str | None = None
    delegated_identity_id: str | None = None


class MCPTenancyService:
    def __init__(self, db: Session):
        self.db = db

    def default_tenant(self) -> MCPTenant:
        tenant = self.db.scalar(
            select(MCPTenant).where(MCPTenant.slug == settings.mcp_default_tenant_slug)
        )
        if tenant is None:
            tenant = MCPTenant(slug=settings.mcp_default_tenant_slug, name="Default")
            self.db.add(tenant)
            self.db.commit()
            self.db.refresh(tenant)
        return tenant

    def context_for_run(self, run: AgentRun) -> MCPAuthorizationContext:
        tenant_id = run.tenant_id or self.default_tenant().id
        principal_provider = None
        if run.delegated_identity_id:
            identity = self.db.get(MCPDelegatedIdentity, run.delegated_identity_id)
            principal_provider = identity.subject_provider if identity else None
        return MCPAuthorizationContext(
            tenant_id=tenant_id,
            repo_id=run.repo_id,
            principal_type=run.principal_type,
            principal_id=run.principal_id,
            principal_provider=principal_provider,
            delegated_identity_id=run.delegated_identity_id,
        )

    def is_allowed(
        self,
        context: MCPAuthorizationContext,
        *,
        server_name: str,
        tool_name: str,
        permission: str,
    ) -> bool:
        if not settings.mcp_tenant_authorization_enabled:
            return True
        binding = self.db.scalar(
            select(MCPTenantServerBinding).where(
                MCPTenantServerBinding.tenant_id == context.tenant_id,
                MCPTenantServerBinding.server_name == server_name,
                MCPTenantServerBinding.enabled.is_(True),
            )
        )
        if binding is None:
            return False
        now = datetime.now(timezone.utc)
        grants = list(
            self.db.execute(
                select(MCPAccessGrant).where(
                    MCPAccessGrant.tenant_id == context.tenant_id,
                    or_(MCPAccessGrant.repo_id.is_(None), MCPAccessGrant.repo_id == context.repo_id),
                    MCPAccessGrant.server_name.in_([server_name, "*"]),
                    MCPAccessGrant.tool_name.in_([tool_name, "*"]),
                    or_(MCPAccessGrant.expires_at.is_(None), MCPAccessGrant.expires_at > now),
                )
            )
            .scalars()
            .all()
        )
        principals = {(context.principal_type, context.principal_id), ("*", "*")}
        if context.principal_type == "user":
            membership = self.db.scalar(
                select(MCPTenantMembership).where(
                    MCPTenantMembership.tenant_id == context.tenant_id,
                    MCPTenantMembership.subject == context.principal_id,
                    or_(
                        context.principal_provider is None,
                        MCPTenantMembership.provider == context.principal_provider,
                    ),
                )
            )
            if membership:
                principals.add(("role", membership.role))
        matching = [
            grant
            for grant in grants
            if (grant.principal_type, grant.principal_id) in principals
            and permission in (grant.permissions_json or [])
        ]
        if any(grant.effect == "deny" for grant in matching):
            return False
        return any(grant.effect == "allow" for grant in matching)

    def require(
        self,
        context: MCPAuthorizationContext,
        *,
        server_name: str,
        tool_name: str,
        permission: str,
    ) -> None:
        if not self.is_allowed(
            context,
            server_name=server_name,
            tool_name=tool_name,
            permission=permission,
        ):
            raise MCPAuthorizationDenied(
                f"Tenant policy denied {permission} for {server_name}.{tool_name}"
            )

    def filter_configs(
        self,
        configs: list[MCPRemoteServerConfig],
        context: MCPAuthorizationContext,
    ) -> list[MCPRemoteServerConfig]:
        if not settings.mcp_tenant_authorization_enabled:
            return configs
        filtered = []
        for config in configs:
            allowed = [
                tool
                for tool in config.allowed_tools
                if self.is_allowed(
                    context,
                    server_name=config.name,
                    tool_name=tool,
                    permission="discover",
                )
                and self.is_allowed(
                    context,
                    server_name=config.name,
                    tool_name=tool,
                    permission="execute",
                )
            ]
            if not allowed:
                continue
            filtered.append(
                config.model_copy(
                    update={
                        "allowed_tools": allowed,
                        "tool_policies": {
                            tool: policy
                            for tool, policy in config.tool_policies.items()
                            if tool in allowed
                        },
                        "agent_context_tools": [
                            item for item in config.agent_context_tools if item.tool in allowed
                        ],
                    }
                )
            )
        return filtered


class MCPDelegatedIdentityService:
    def __init__(self, db: Session):
        self.db = db

    def configure_provider(
        self,
        *,
        tenant_id: str,
        server_name: str,
        authorization_url: str,
        token_url: str,
        client_id: str,
        client_secret: str | None,
        scopes: list[str],
        redirect_uri: str,
    ) -> MCPDelegatedOAuthProvider:
        for url in (authorization_url, token_url, redirect_uri):
            validate_registry_url(url)
        provider = self.db.scalar(
            select(MCPDelegatedOAuthProvider).where(
                MCPDelegatedOAuthProvider.tenant_id == tenant_id,
                MCPDelegatedOAuthProvider.server_name == server_name,
            )
        )
        if provider is None:
            provider = MCPDelegatedOAuthProvider(tenant_id=tenant_id, server_name=server_name)
        provider.authorization_url = authorization_url
        provider.token_url = token_url
        provider.client_id = client_id
        if client_secret:
            provider.encrypted_client_secret = encrypt_payload(
                {"client_secret": client_secret},
                binding=provider_secret_binding(tenant_id, server_name),
            )
        provider.scopes_json = scopes
        provider.redirect_uri = redirect_uri
        provider.version = (provider.version or 0) + 1 if provider.id else 1
        self.db.add(provider)
        self.db.commit()
        self.db.refresh(provider)
        return provider

    def start_authorization(
        self,
        provider_id: str,
        *,
        subject_provider: str,
        subject: str,
    ) -> dict[str, str]:
        provider = self.db.get(MCPDelegatedOAuthProvider, provider_id)
        if provider is None:
            raise MCPDelegatedIdentityError("Delegated OAuth provider not found")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.db.add(
            MCPDelegatedOAuthState(
                state_hash=sha256(state),
                provider_id=provider.id,
                subject_provider=subject_provider,
                subject=subject,
                encrypted_verifier=encrypt_payload(
                    {"verifier": verifier}, binding=oauth_state_binding(sha256(state))
                ),
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=max(60, settings.mcp_delegated_oauth_state_ttl_seconds)),
            )
        )
        self.db.commit()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": provider.client_id,
                "redirect_uri": provider.redirect_uri,
                "scope": " ".join(provider.scopes_json or []),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if urlsplit(provider.authorization_url).query else "?"
        return {"authorization_url": f"{provider.authorization_url}{separator}{query}"}

    def complete_authorization(self, *, code: str, state: str) -> dict[str, Any]:
        oauth_state = self.db.execute(
            select(MCPDelegatedOAuthState)
            .where(MCPDelegatedOAuthState.state_hash == sha256(state))
            .with_for_update()
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if (
            oauth_state is None
            or oauth_state.consumed_at is not None
            or oauth_state.expires_at <= now
        ):
            raise MCPDelegatedIdentityError("Delegated OAuth state is invalid or expired")
        oauth_state.consumed_at = now
        self.db.add(oauth_state)
        provider = self.db.get(MCPDelegatedOAuthProvider, oauth_state.provider_id)
        if provider is None:
            raise MCPDelegatedIdentityError("Delegated OAuth provider not found")
        verifier_payload, migrated = decrypt_sensitive_payload(
            oauth_state.encrypted_verifier,
            binding=oauth_state_binding(oauth_state.state_hash),
        )
        verifier = verifier_payload["verifier"]
        if migrated:
            oauth_state.encrypted_verifier = encrypt_payload(
                verifier_payload,
                binding=oauth_state_binding(oauth_state.state_hash),
            )
            self.db.add(oauth_state)
        try:
            token_data = self._exchange(
                provider,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": provider.redirect_uri,
                    "code_verifier": verifier,
                },
            )
        except Exception:
            # Keep the one-time state retryable after a transient token endpoint
            # failure. The row lock prevents two successful consumers.
            self.db.rollback()
            raise
        delegation_token = secrets.token_urlsafe(32)
        expires_in = max(1, int(token_data.get("expires_in") or 3600))
        identity_id = str(uuid.uuid4())
        identity = MCPDelegatedIdentity(
            id=identity_id,
            tenant_id=provider.tenant_id,
            provider_id=provider.id,
            server_name=provider.server_name,
            subject_provider=oauth_state.subject_provider,
            subject=oauth_state.subject,
            encrypted_token_payload=encrypt_payload(
                token_data, binding=delegated_identity_binding(identity_id)
            ),
            delegation_token_hash=sha256(delegation_token),
            scopes_json=str(token_data.get("scope") or "").split()
            or list(provider.scopes_json or []),
            expires_at=now + timedelta(seconds=expires_in),
        )
        self.db.add(identity)
        self.db.commit()
        self.db.refresh(identity)
        return {
            "identity": self.public_dict(identity),
            "delegation_token": delegation_token,
        }

    def verify_for_run(
        self,
        identity_id: str,
        delegation_token: str,
        *,
        tenant_id: str,
    ) -> MCPDelegatedIdentity:
        identity = self.db.get(MCPDelegatedIdentity, identity_id)
        if (
            identity is None
            or identity.tenant_id != tenant_id
            or identity.revoked
            or not secrets.compare_digest(identity.delegation_token_hash, sha256(delegation_token))
        ):
            raise MCPDelegatedIdentityError("Delegated identity proof is invalid")
        return identity

    def access_token(self, identity_id: str) -> str:
        identity = self.db.get(MCPDelegatedIdentity, identity_id)
        if identity is None or identity.revoked:
            raise MCPDelegatedIdentityError("Delegated identity is unavailable")
        payload, migrated = decrypt_sensitive_payload(
            identity.encrypted_token_payload,
            binding=delegated_identity_binding(identity.id),
        )
        if migrated:
            identity.encrypted_token_payload = encrypt_payload(
                payload, binding=delegated_identity_binding(identity.id)
            )
            self.db.add(identity)
        now = datetime.now(timezone.utc)
        skew = timedelta(seconds=max(0, settings.mcp_oauth_token_expiry_skew_seconds))
        if identity.expires_at and now + skew < identity.expires_at:
            if migrated:
                self.db.commit()
            return str(payload["access_token"])
        refresh_token = str(payload.get("refresh_token") or "")
        if not refresh_token:
            raise MCPDelegatedIdentityError("Delegated identity has expired without refresh token")
        provider = self.db.get(MCPDelegatedOAuthProvider, identity.provider_id)
        if provider is None:
            raise MCPDelegatedIdentityError("Delegated OAuth provider not found")
        refreshed = self._exchange(
            provider,
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = refresh_token
        expires_in = max(1, int(refreshed.get("expires_in") or 3600))
        identity.encrypted_token_payload = encrypt_payload(
            refreshed, binding=delegated_identity_binding(identity.id)
        )
        identity.expires_at = now + timedelta(seconds=expires_in)
        identity.version += 1
        identity.updated_at = now
        self.db.add(identity)
        self.db.commit()
        return str(refreshed["access_token"])

    def revoke(self, identity_id: str) -> MCPDelegatedIdentity:
        identity = self.db.get(MCPDelegatedIdentity, identity_id)
        if identity is None:
            raise MCPDelegatedIdentityError("Delegated identity not found")
        identity.revoked = True
        identity.version += 1
        identity.updated_at = datetime.now(timezone.utc)
        self.db.add(identity)
        self.db.commit()
        return identity

    @staticmethod
    def public_dict(identity: MCPDelegatedIdentity) -> dict[str, Any]:
        return {
            "id": identity.id,
            "tenant_id": identity.tenant_id,
            "server_name": identity.server_name,
            "subject_provider": identity.subject_provider,
            "subject": identity.subject,
            "scopes": identity.scopes_json,
            "expires_at": identity.expires_at.isoformat() if identity.expires_at else None,
            "revoked": identity.revoked,
            "version": identity.version,
            "created_at": identity.created_at.isoformat(),
            "updated_at": identity.updated_at.isoformat(),
        }

    @staticmethod
    def provider_public(provider: MCPDelegatedOAuthProvider) -> dict[str, Any]:
        return {
            "id": provider.id,
            "tenant_id": provider.tenant_id,
            "server_name": provider.server_name,
            "authorization_url": provider.authorization_url,
            "token_url": provider.token_url,
            "client_id": provider.client_id,
            "has_client_secret": bool(provider.encrypted_client_secret),
            "scopes": provider.scopes_json,
            "redirect_uri": provider.redirect_uri,
            "version": provider.version,
        }

    @staticmethod
    def _exchange(provider: MCPDelegatedOAuthProvider, data: dict[str, Any]) -> dict[str, Any]:
        validate_registry_url(provider.token_url, resolve_dns=True)
        if settings.mcp_sandbox_enabled:
            validate_egress_url(provider.token_url)
        payload = {**data, "client_id": provider.client_id}
        if provider.encrypted_client_secret:
            secret_payload, migrated = decrypt_sensitive_payload(
                provider.encrypted_client_secret,
                binding=provider_secret_binding(provider.tenant_id, provider.server_name),
            )
            payload["client_secret"] = secret_payload["client_secret"]
            if migrated:
                provider.encrypted_client_secret = encrypt_payload(
                    secret_payload,
                    binding=provider_secret_binding(provider.tenant_id, provider.server_name),
                )
        try:
            response = httpx.post(
                provider.token_url,
                data=payload,
                timeout=max(1.0, settings.mcp_client_timeout_seconds),
                follow_redirects=False,
                proxy=egress_httpx_proxy(),
                trust_env=False,
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("access_token"):
                raise MCPDelegatedIdentityError("OAuth response did not include access_token")
            return dict(result)
        except MCPDelegatedIdentityError:
            raise
        except Exception as exc:
            raise MCPDelegatedIdentityError(f"Delegated OAuth token exchange failed: {exc}") from exc


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def provider_secret_binding(tenant_id: str, server_name: str) -> str:
    return f"mcp-oauth-provider:{tenant_id}:{server_name}"


def oauth_state_binding(state_hash: str) -> str:
    return f"mcp-oauth-state:{state_hash}"


def delegated_identity_binding(identity_id: str) -> str:
    return f"mcp-delegated-identity:{identity_id}"


def decrypt_sensitive_payload(
    value: str,
    *,
    binding: str,
) -> tuple[dict[str, Any], bool]:
    needs_migration = envelope_is_unbound(value)
    payload = decrypt_payload(value, binding=None if needs_migration else binding)
    return payload, needs_migration
