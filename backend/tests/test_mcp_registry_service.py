import base64
import hashlib
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.services.mcp_registry_service import (
    MCPCredentialError,
    MCPRegistryConflictError,
    MCPRegistryService,
    decrypt_payload,
    validate_registry_url,
)
from app.core.kms import ENVELOPE_PREFIX


@pytest.fixture
def registry_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'registry.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(settings, "mcp_registry_enabled", True)
    monkeypatch.setattr(settings, "mcp_registry_master_key", "registry-master-key-32-characters-long")
    monkeypatch.setattr(settings, "mcp_registry_require_https", True)
    monkeypatch.setattr(settings, "mcp_registry_allow_private_networks", False)
    monkeypatch.setattr(settings, "mcp_registry_allowed_hosts", "")
    monkeypatch.setattr(settings, "mcp_client_servers_json", "[]")
    yield db
    db.close()


def server_payload(name="docs"):
    return {
        "name": name,
        "url": f"https://{name}.example.com/mcp",
        "enabled": True,
        "allowed_tools": ["search"],
        "tool_policies": {"search": "auto"},
        "agent_context_tools": [],
        "idempotency_mode": "none",
    }


def test_registry_crud_hot_load_revision_and_restore(registry_db):
    service = MCPRegistryService(registry_db)
    created = service.create(server_payload(), actor="alice")
    updated = service.update(
        created.id,
        {"allowed_tools": ["search", "write"], "tool_policies": {"search": "auto", "write": "approval_required"}},
        expected_version=created.version,
        actor="bob",
    )
    updated_version = updated.version
    revisions = service.revisions(created.id)
    create_revision = next(item for item in revisions if item.action == "create")
    restored = service.restore(
        created.id,
        create_revision.id,
        expected_version=updated.version,
        actor="alice",
    )
    configs = service.effective_configs()

    assert updated_version == 2
    assert len(revisions) == 2
    assert restored.allowed_tools_json == ["search"]
    assert configs[0].name == "docs"
    assert configs[0].registry_managed is True


def test_credential_broker_encrypts_bearer_and_never_exposes_secret(registry_db):
    service = MCPRegistryService(registry_db)
    server = service.create(server_payload(), actor="alice")
    credential = service.credentials.set_credential(
        server,
        auth_type="bearer",
        payload={"token": "super-secret-bearer-token"},
    )
    registry_db.refresh(server)
    public = service.public_dict(server)

    assert "super-secret" not in credential.encrypted_payload
    assert decrypt_payload(credential.encrypted_payload)["token"] == "super-secret-bearer-token"
    assert public["credential"]["auth_type"] == "bearer"
    assert "token" not in public["credential"]
    assert service.effective_configs()[0].bearer_token.get_secret_value() == "super-secret-bearer-token"


def test_registry_filters_before_resolving_credentials(registry_db, monkeypatch):
    service = MCPRegistryService(registry_db)
    allowed = service.create(server_payload("allowed"), actor="alice")
    denied = service.create(server_payload("denied"), actor="alice")
    service.credentials.set_credential(
        allowed,
        auth_type="bearer",
        payload={"token": "allowed-secret-token"},
    )
    service.credentials.set_credential(
        denied,
        auth_type="bearer",
        payload={"token": "denied-secret-token"},
    )
    resolved = []
    original = service.credentials.resolve_bearer_token

    def resolve(server):
        resolved.append(server.name)
        return original(server)

    monkeypatch.setattr(service.credentials, "resolve_bearer_token", resolve)
    configs = service.effective_configs(
        config_filter=lambda values: [item for item in values if item.name == "allowed"]
    )

    assert [item.name for item in configs] == ["allowed"]
    assert resolved == ["allowed"]


def test_oauth_client_credentials_are_cached_and_refreshed(registry_db, monkeypatch):
    service = MCPRegistryService(registry_db)
    server = service.create(server_payload(), actor="alice")
    monkeypatch.setattr(settings, "mcp_registry_allow_private_networks", True)
    credential = service.credentials.set_credential(
        server,
        auth_type="oauth2_client_credentials",
        payload={
            "token_url": "https://127.0.0.1/oauth/token",
            "client_id": "codemate",
            "client_secret": "oauth-secret-value",
            "scopes": ["mcp.call"],
        },
    )
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "access-token", "expires_in": 3600}

    monkeypatch.setattr(
        "app.services.mcp_registry_service.httpx.post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
    )

    first = service.credentials.resolve_bearer_token(server)
    second = service.credentials.resolve_bearer_token(server)

    assert first == second == "access-token"
    assert len(calls) == 1
    assert credential.last_refreshed_at is not None


def test_registry_blocks_private_urls_and_static_name_conflicts(registry_db, monkeypatch):
    with pytest.raises(MCPRegistryConflictError, match="Private"):
        validate_registry_url("https://127.0.0.1/mcp")
    with pytest.raises(MCPRegistryConflictError, match="Private"):
        validate_registry_url("https://localhost/mcp")

    monkeypatch.setattr(
        settings,
        "mcp_client_servers_json",
        '[{"name":"docs","url":"https://static.example.com/mcp"}]',
    )
    with pytest.raises(MCPRegistryConflictError, match="static"):
        MCPRegistryService(registry_db).create(server_payload(), actor="alice")


def test_wrong_master_key_cannot_decrypt_credentials(registry_db, monkeypatch):
    service = MCPRegistryService(registry_db)
    server = service.create(server_payload(), actor="alice")
    credential = service.credentials.set_credential(
        server,
        auth_type="bearer",
        payload={"token": "super-secret-bearer-token"},
    )
    monkeypatch.setattr(settings, "mcp_registry_master_key", "a-different-master-key-that-is-long")

    with pytest.raises(MCPCredentialError, match="decrypted"):
        decrypt_payload(credential.encrypted_payload)


def test_previous_master_key_supports_online_rewrap(registry_db, monkeypatch):
    service = MCPRegistryService(registry_db)
    server = service.create(server_payload(), actor="alice")
    service.credentials.set_credential(
        server,
        auth_type="bearer",
        payload={"token": "super-secret-bearer-token"},
    )
    old_key = settings.mcp_registry_master_key
    monkeypatch.setattr(settings, "mcp_registry_previous_master_key", old_key)
    monkeypatch.setattr(settings, "mcp_registry_master_key", "new-registry-master-key-32-characters")
    monkeypatch.setattr(settings, "mcp_registry_key_version", 2)

    assert service.credentials.rewrap_all() == 1
    monkeypatch.setattr(settings, "mcp_registry_previous_master_key", None)
    registry_db.refresh(server.credential)
    assert service.credentials.resolve_bearer_token(server) == "super-secret-bearer-token"
    assert server.credential.key_version == 2


def test_legacy_ciphertext_is_migrated_to_versioned_envelope(registry_db):
    service = MCPRegistryService(registry_db)
    server = service.create(server_payload(), actor="alice")
    credential = service.credentials.set_credential(
        server,
        auth_type="bearer",
        payload={"token": "legacy-secret-token"},
    )
    nonce = os.urandom(12)
    legacy_key = hashlib.sha256(settings.mcp_registry_master_key.encode()).digest()
    ciphertext = AESGCM(legacy_key).encrypt(
        nonce,
        json.dumps({"token": "legacy-secret-token"}).encode(),
        b"codemate-mcp-credential-v1",
    )
    credential.encrypted_payload = base64.urlsafe_b64encode(nonce + ciphertext).decode()
    registry_db.add(credential)
    registry_db.commit()

    assert service.credentials.rewrap_all() == 1
    registry_db.refresh(credential)
    assert credential.encrypted_payload.startswith(ENVELOPE_PREFIX)
    assert decrypt_payload(credential.encrypted_payload) == {"token": "legacy-secret-token"}


def test_credential_envelope_is_bound_to_server(registry_db):
    service = MCPRegistryService(registry_db)
    first = service.create(server_payload("first"), actor="alice")
    second = service.create(server_payload("second"), actor="alice")
    first_credential = service.credentials.set_credential(
        first, auth_type="bearer", payload={"token": "first-secret-token"}
    )
    second_credential = service.credentials.set_credential(
        second, auth_type="bearer", payload={"token": "second-secret-token"}
    )
    second_credential.encrypted_payload = first_credential.encrypted_payload
    registry_db.add(second_credential)
    registry_db.commit()

    with pytest.raises(MCPCredentialError, match="decrypted"):
        service.credentials.resolve_bearer_token(second)


def test_validation_persists_capability_and_tool_snapshots(registry_db, monkeypatch):
    service = MCPRegistryService(registry_db)
    server = service.create(server_payload(), actor="alice")

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def probe(self, _name):
            return {
                "protocol_version": "2025-11-25",
                "server_info": {"name": "docs"},
                "capabilities": {"tools": {}},
            }

        async def list_tools(self, _name):
            return [{"name": "search", "input_schema": {"type": "object"}}]

    monkeypatch.setattr("app.services.mcp_registry_service.MCPClientService", FakeClient)
    validated = service.validate(server.id, actor="alice")

    assert validated.validation_status == "valid"
    assert validated.protocol_version == "2025-11-25"
    assert validated.tools_snapshot_json[0]["name"] == "search"
