import asyncio
import base64
import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from pydantic import SecretStr

from app.core.config import settings
from app.core.kms import (
    ENVELOPE_PREFIX,
    KMSConfigurationError,
    KMSDecryptionError,
    decrypt_envelope,
    encrypt_envelope,
    envelope_metadata,
)
from app.mcp.client import MCPClientService, MCPRemoteServerConfig, parse_server_configs
from app.mcp.egress import egress_httpx_proxy, validate_egress_url
from app.models.mcp_credential import MCPCredential
from app.models.mcp_server_health import MCPServerHealth
from app.models.mcp_server_registration import MCPServerRegistration
from app.models.mcp_server_revision import MCPServerRevision
from app.services.mcp_approval_service import jsonable


class MCPRegistryError(RuntimeError):
    pass


class MCPRegistryNotFoundError(MCPRegistryError):
    pass


class MCPRegistryConflictError(MCPRegistryError):
    pass


class MCPCredentialError(MCPRegistryError):
    pass


class MCPCredentialBroker:
    def __init__(self, db: Session):
        self.db = db

    def set_credential(
        self,
        server: MCPServerRegistration,
        *,
        auth_type: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> MCPCredential:
        if auth_type not in {"bearer", "oauth2_client_credentials"}:
            raise MCPCredentialError("Unsupported MCP credential type")
        normalized = self._validate_payload(auth_type, payload)
        credential = server.credential
        if credential is None:
            credential = MCPCredential(server_id=server.id, auth_type=auth_type)
            server.credential = credential
        elif expected_version is None or credential.version != expected_version:
            raise MCPRegistryConflictError(
                "Current expected_version is required to rotate an MCP credential"
            )
        credential.auth_type = auth_type
        credential.encrypted_payload = encrypt_payload(normalized, binding=server.id)
        credential.key_version = settings.mcp_registry_key_version
        credential.expires_at = None
        credential.last_error = None
        credential.version = (credential.version or 0) + 1 if credential.id else 1
        credential.updated_at = datetime.utcnow()
        self.db.add(credential)
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def delete_credential(self, server: MCPServerRegistration) -> None:
        if server.credential is not None:
            self.db.delete(server.credential)
            self.db.commit()

    def rewrap_all(self) -> int:
        credentials = list(self.db.execute(select(MCPCredential)).scalars().all())
        for credential in credentials:
            payload = decrypt_payload(credential.encrypted_payload, binding=credential.server_id)
            credential.encrypted_payload = encrypt_payload(payload, binding=credential.server_id)
            credential.key_version = settings.mcp_registry_key_version
            credential.version += 1
            credential.updated_at = datetime.utcnow()
            self.db.add(credential)
        self.db.commit()
        return len(credentials)

    def resolve_bearer_token(self, server: MCPServerRegistration) -> str | None:
        credential = server.credential
        if credential is None:
            return None
        payload = decrypt_payload(credential.encrypted_payload, binding=server.id)
        if credential.auth_type == "bearer":
            return str(payload["token"])
        return self._oauth_access_token(credential, payload)

    @staticmethod
    def public_dict(credential: MCPCredential | None) -> dict[str, Any] | None:
        if credential is None:
            return None
        encryption = envelope_metadata(credential.encrypted_payload)
        return {
            "id": credential.id,
            "auth_type": credential.auth_type,
            "key_version": credential.key_version,
            "encryption_provider": encryption["provider"],
            "kms_key_id": encryption["key_id"],
            "expires_at": iso(credential.expires_at),
            "last_refreshed_at": iso(credential.last_refreshed_at),
            "last_error": credential.last_error,
            "version": credential.version,
            "created_at": iso(credential.created_at),
            "updated_at": iso(credential.updated_at),
        }

    def _oauth_access_token(self, credential: MCPCredential, payload: dict[str, Any]) -> str:
        now = datetime.utcnow()
        cached = str(payload.get("access_token") or "")
        expires_at = parse_iso(payload.get("access_token_expires_at"))
        skew = timedelta(seconds=max(0, settings.mcp_oauth_token_expiry_skew_seconds))
        if cached and expires_at and now + skew < expires_at:
            return cached

        token_url = str(payload["token_url"])
        validate_registry_url(token_url, resolve_dns=True)
        if settings.mcp_sandbox_enabled:
            validate_egress_url(token_url)
        data = {
            "grant_type": "client_credentials",
            "client_id": str(payload["client_id"]),
            "client_secret": str(payload["client_secret"]),
        }
        scopes = payload.get("scopes") or []
        if scopes:
            data["scope"] = " ".join(str(item) for item in scopes)
        try:
            response = httpx.post(
                token_url,
                data=data,
                timeout=max(1.0, settings.mcp_client_timeout_seconds),
                follow_redirects=False,
                proxy=egress_httpx_proxy(),
                trust_env=False,
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = str(token_data.get("access_token") or "")
            if not access_token:
                raise MCPCredentialError("OAuth token response did not contain access_token")
            expires_in = max(1, int(token_data.get("expires_in") or 3600))
            payload["access_token"] = access_token
            payload["access_token_expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
            credential.encrypted_payload = encrypt_payload(payload, binding=credential.server_id)
            credential.expires_at = now + timedelta(seconds=expires_in)
            credential.last_refreshed_at = now
            credential.last_error = None
            credential.version += 1
            credential.updated_at = now
            self.db.add(credential)
            self.db.commit()
            return access_token
        except Exception as exc:
            credential.last_error = str(exc)[:4000]
            credential.updated_at = now
            self.db.add(credential)
            self.db.commit()
            if isinstance(exc, MCPCredentialError):
                raise
            raise MCPCredentialError(f"OAuth client credentials exchange failed: {exc}") from exc

    @staticmethod
    def _validate_payload(auth_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if auth_type == "bearer":
            token = str(payload.get("token") or "").strip()
            if len(token) < 8:
                raise MCPCredentialError("Bearer token must contain at least 8 characters")
            return {"token": token}
        token_url = str(payload.get("token_url") or "").strip()
        client_id = str(payload.get("client_id") or "").strip()
        client_secret = str(payload.get("client_secret") or "").strip()
        if not token_url or not client_id or len(client_secret) < 8:
            raise MCPCredentialError(
                "OAuth token_url, client_id, and a client_secret of at least 8 characters are required"
            )
        validate_registry_url(token_url)
        return {
            "token_url": token_url,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": [str(item) for item in (payload.get("scopes") or []) if str(item)],
        }


class MCPRegistryService:
    def __init__(self, db: Session):
        self.db = db
        self.credentials = MCPCredentialBroker(db)

    def list_servers(self) -> list[MCPServerRegistration]:
        return list(
            self.db.execute(
                select(MCPServerRegistration).order_by(MCPServerRegistration.name.asc())
            )
            .scalars()
            .all()
        )

    def get(self, server_id: str) -> MCPServerRegistration:
        server = self.db.get(MCPServerRegistration, server_id)
        if server is None:
            raise MCPRegistryNotFoundError("Dynamic MCP server not found")
        return server

    def create(self, payload: dict[str, Any], *, actor: str) -> MCPServerRegistration:
        if not settings.mcp_registry_enabled:
            raise MCPRegistryConflictError("Dynamic MCP registry is disabled")
        count = self.db.scalar(select(func.count()).select_from(MCPServerRegistration)) or 0
        if count >= max(1, settings.mcp_registry_max_servers):
            raise MCPRegistryConflictError("Dynamic MCP server limit reached")
        config = validate_config_payload(payload)
        static_names = {item.name for item in parse_server_configs(settings.mcp_client_servers_json)}
        if config.name in static_names:
            raise MCPRegistryConflictError("Server name conflicts with static MCP configuration")
        if self.db.scalar(
            select(MCPServerRegistration.id).where(MCPServerRegistration.name == config.name)
        ):
            raise MCPRegistryConflictError("Dynamic MCP server name already exists")
        server = MCPServerRegistration(
            name=config.name,
            url=str(config.url),
            enabled=config.enabled,
            allowed_tools_json=config.allowed_tools,
            tool_policies_json=config.tool_policies,
            agent_context_tools_json=[item.model_dump(mode="json") for item in config.agent_context_tools],
            idempotency_mode=config.idempotency_mode,
            created_by=actor,
            updated_by=actor,
        )
        self.db.add(server)
        self.db.flush()
        self._revision(server, "create", actor)
        self.db.commit()
        self.db.refresh(server)
        return server

    def update(
        self,
        server_id: str,
        payload: dict[str, Any],
        *,
        expected_version: int,
        actor: str,
        action: str = "update",
    ) -> MCPServerRegistration:
        server = self._locked(server_id)
        old_name = server.name
        if server.version != expected_version:
            raise MCPRegistryConflictError("Dynamic MCP server version conflict")
        merged = {**server_config_snapshot(server), **payload}
        config = validate_config_payload(merged)
        conflict = self.db.scalar(
            select(MCPServerRegistration.id)
            .where(MCPServerRegistration.name == config.name)
            .where(MCPServerRegistration.id != server.id)
        )
        if conflict:
            raise MCPRegistryConflictError("Dynamic MCP server name already exists")
        static_names = {item.name for item in parse_server_configs(settings.mcp_client_servers_json)}
        if config.name in static_names:
            raise MCPRegistryConflictError("Server name conflicts with static MCP configuration")
        server.name = config.name
        server.url = str(config.url)
        server.enabled = config.enabled
        server.allowed_tools_json = config.allowed_tools
        server.tool_policies_json = config.tool_policies
        server.agent_context_tools_json = [
            item.model_dump(mode="json") for item in config.agent_context_tools
        ]
        server.idempotency_mode = config.idempotency_mode
        server.validation_status = "unvalidated"
        server.validation_error = None
        server.version += 1
        server.updated_by = actor
        server.updated_at = datetime.utcnow()
        if old_name != server.name:
            old_health = self.db.get(MCPServerHealth, old_name)
            if old_health is not None:
                self.db.delete(old_health)
        self._revision(server, action, actor)
        self.db.add(server)
        self.db.commit()
        self.db.refresh(server)
        return server

    def delete(self, server_id: str, *, expected_version: int) -> None:
        server = self._locked(server_id)
        if server.version != expected_version:
            raise MCPRegistryConflictError("Dynamic MCP server version conflict")
        health = self.db.get(MCPServerHealth, server.name)
        if health is not None:
            self.db.delete(health)
        self.db.delete(server)
        self.db.commit()

    def revisions(self, server_id: str) -> list[MCPServerRevision]:
        self.get(server_id)
        return list(
            self.db.execute(
                select(MCPServerRevision)
                .where(MCPServerRevision.server_id == server_id)
                .order_by(MCPServerRevision.created_at.desc())
            )
            .scalars()
            .all()
        )

    def restore(
        self,
        server_id: str,
        revision_id: str,
        *,
        expected_version: int,
        actor: str,
    ) -> MCPServerRegistration:
        revision = self.db.get(MCPServerRevision, revision_id)
        if revision is None or revision.server_id != server_id:
            raise MCPRegistryNotFoundError("MCP server revision not found")
        return self.update(
            server_id,
            revision.snapshot_json,
            expected_version=expected_version,
            actor=actor,
            action="restore",
        )

    def effective_configs(
        self,
        *,
        config_filter: Callable[
            [list[MCPRemoteServerConfig]], list[MCPRemoteServerConfig]
        ]
        | None = None,
    ) -> list[MCPRemoteServerConfig]:
        static = parse_server_configs(settings.mcp_client_servers_json)
        if not settings.mcp_registry_enabled:
            return config_filter(static) if config_filter else static
        servers = [item for item in self.list_servers() if item.enabled]
        dynamic = [self._config_without_credential(item) for item in servers]
        names = [item.name for item in [*static, *dynamic]]
        if len(names) != len(set(names)):
            raise MCPRegistryConflictError("Static and dynamic MCP server names conflict")
        configs = [*static, *dynamic]
        if config_filter:
            configs = config_filter(configs)
        servers_by_name = {item.name: item for item in servers}
        hydrated: list[MCPRemoteServerConfig] = []
        for config in configs:
            if not config.registry_managed:
                hydrated.append(config)
                continue
            server = servers_by_name.get(config.name)
            if server is None:
                continue
            try:
                hydrated.append(self._runtime_config(server, base=config))
            except MCPCredentialError:
                continue
        return hydrated

    def client(self) -> MCPClientService:
        return MCPClientService(servers=self.effective_configs())

    def validate(self, server_id: str, *, actor: str) -> MCPServerRegistration:
        server = self.get(server_id)
        try:
            client = MCPClientService(servers=[self._runtime_config(server)])
            probe = asyncio.run(client.probe(server.name))
            tools = asyncio.run(client.list_tools(server.name))
            server.validation_status = "valid"
            server.validation_error = None
            server.protocol_version = str(probe.get("protocol_version") or "") or None
            server.server_info_json = jsonable(probe.get("server_info") or {})
            server.capabilities_json = jsonable(probe.get("capabilities") or {})
            server.tools_snapshot_json = jsonable(tools)
        except Exception as exc:
            server.validation_status = "invalid"
            server.validation_error = str(exc)[:4000]
        server.validated_at = datetime.utcnow()
        server.version += 1
        server.updated_by = actor
        server.updated_at = datetime.utcnow()
        self._revision(server, "validate", actor)
        self.db.add(server)
        self.db.commit()
        self.db.refresh(server)
        return server

    def public_dict(self, server: MCPServerRegistration) -> dict[str, Any]:
        return {
            "id": server.id,
            **server_config_snapshot(server),
            "validation_status": server.validation_status,
            "validation_error": server.validation_error,
            "protocol_version": server.protocol_version,
            "server_info": server.server_info_json,
            "capabilities": server.capabilities_json,
            "tools_snapshot": server.tools_snapshot_json,
            "validated_at": iso(server.validated_at),
            "credential": self.credentials.public_dict(server.credential),
            "version": server.version,
            "created_by": server.created_by,
            "updated_by": server.updated_by,
            "created_at": iso(server.created_at),
            "updated_at": iso(server.updated_at),
        }

    def _config_without_credential(
        self, server: MCPServerRegistration
    ) -> MCPRemoteServerConfig:
        return MCPRemoteServerConfig.model_validate(
            {**server_config_snapshot(server), "registry_managed": True}
        )

    def _runtime_config(
        self,
        server: MCPServerRegistration,
        *,
        base: MCPRemoteServerConfig | None = None,
    ) -> MCPRemoteServerConfig:
        config = base or self._config_without_credential(server)
        token = self.credentials.resolve_bearer_token(server)
        return config.model_copy(
            update={"bearer_token": SecretStr(token) if token else None}
        )

    def _revision(self, server: MCPServerRegistration, action: str, actor: str) -> None:
        self.db.add(
            MCPServerRevision(
                server_id=server.id,
                version=server.version,
                action=action,
                snapshot_json=server_config_snapshot(server),
                actor=actor,
            )
        )

    def _locked(self, server_id: str) -> MCPServerRegistration:
        server = self.db.execute(
            select(MCPServerRegistration)
            .where(MCPServerRegistration.id == server_id)
            .with_for_update()
        ).scalar_one_or_none()
        if server is None:
            raise MCPRegistryNotFoundError("Dynamic MCP server not found")
        return server


def validate_config_payload(payload: dict[str, Any]) -> MCPRemoteServerConfig:
    data = {
        "name": payload.get("name"),
        "url": payload.get("url"),
        "allowed_tools": payload.get("allowed_tools") or [],
        "tool_policies": payload.get("tool_policies") or {},
        "agent_context_tools": payload.get("agent_context_tools") or [],
        "idempotency_mode": payload.get("idempotency_mode") or "none",
        "enabled": payload.get("enabled", True),
        "registry_managed": True,
    }
    validate_registry_url(str(data["url"] or ""))
    return MCPRemoteServerConfig.model_validate(data)


def validate_registry_url(url: str, *, resolve_dns: bool = False) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise MCPRegistryConflictError("MCP registry URL must be HTTP(S)")
    if parts.username or parts.password or parts.fragment:
        raise MCPRegistryConflictError("MCP registry URL must not contain credentials or fragments")
    if settings.mcp_registry_require_https and parts.scheme != "https":
        raise MCPRegistryConflictError("Dynamic MCP server URLs must use HTTPS")
    host = parts.hostname.lower()
    allowlist = settings.mcp_registry_host_allowlist
    if allowlist and host not in allowlist:
        raise MCPRegistryConflictError("MCP server host is not in MCP_REGISTRY_ALLOWED_HOSTS")
    if settings.mcp_registry_allow_private_networks:
        return
    if host == "localhost" or host.endswith(".local"):
        raise MCPRegistryConflictError("Private MCP server hosts are not allowed")
    addresses: list[str] = []
    try:
        addresses.append(str(ipaddress.ip_address(host)))
    except ValueError:
        if resolve_dns:
            try:
                addresses.extend(item[4][0] for item in socket.getaddrinfo(host, None))
            except OSError as exc:
                raise MCPRegistryConflictError(f"MCP server DNS resolution failed: {exc}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise MCPRegistryConflictError("Private or non-global MCP server addresses are not allowed")


def encrypt_payload(payload: dict[str, Any], *, binding: str | None = None) -> str:
    try:
        return encrypt_envelope(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            binding=binding,
        )
    except (KMSConfigurationError, KMSDecryptionError) as exc:
        raise MCPCredentialError(str(exc)) from exc


def decrypt_payload(value: str, *, binding: str | None = None) -> dict[str, Any]:
    if value.startswith(ENVELOPE_PREFIX):
        try:
            payload = json.loads(decrypt_envelope(value, binding=binding))
            if not isinstance(payload, dict):
                raise ValueError("credential payload is not an object")
            return payload
        except (KMSConfigurationError, KMSDecryptionError, ValueError, json.JSONDecodeError) as exc:
            raise MCPCredentialError("MCP KMS credential could not be decrypted") from exc
    last_error: Exception | None = None
    for secret in (
        settings.mcp_registry_master_key,
        settings.mcp_registry_previous_master_key,
    ):
        if not (secret or "").strip():
            continue
        try:
            raw = base64.urlsafe_b64decode(value.encode())
            plaintext = AESGCM(registry_key(secret)).decrypt(
                raw[:12], raw[12:], b"codemate-mcp-credential-v1"
            )
            payload = json.loads(plaintext)
            if not isinstance(payload, dict):
                raise ValueError("credential payload is not an object")
            return payload
        except Exception as exc:  # noqa: BLE001 - try previous rotation key.
            last_error = exc
    try:
        registry_key()
    except MCPCredentialError as exc:
        raise exc from last_error
    raise MCPCredentialError("MCP credential could not be decrypted") from last_error


def registry_key(secret: str | None = None) -> bytes:
    value = (secret if secret is not None else settings.mcp_registry_master_key or "").strip()
    if len(value) < 16:
        raise MCPCredentialError("MCP_REGISTRY_MASTER_KEY is not configured")
    return hashlib.sha256(value.encode()).digest()


def server_config_snapshot(server: MCPServerRegistration) -> dict[str, Any]:
    return {
        "name": server.name,
        "url": server.url,
        "enabled": server.enabled,
        "allowed_tools": list(server.allowed_tools_json or []),
        "tool_policies": dict(server.tool_policies_json or {}),
        "agent_context_tools": list(server.agent_context_tools_json or []),
        "idempotency_mode": server.idempotency_mode,
    }


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
