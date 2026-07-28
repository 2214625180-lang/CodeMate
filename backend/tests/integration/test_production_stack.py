import os
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.core import database
from app.core.config import settings
from app.core.migrations import require_database_at_head
from app.mcp.client import MCPClientService, MCPRemoteServerConfig
from app.models.agent_run import AgentRun
from app.models.mcp_quota import MCPQuotaEvent
from app.models.mcp_tenant import MCPTenant
from app.models.repository import Repository
from app.services.mcp_quota_service import MCPQuotaExceededError, MCPQuotaService
from app.services.mcp_tenancy_service import MCPDelegatedIdentityService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MCP_E2E") != "1",
    reason="Set RUN_MCP_E2E=1 with real PostgreSQL, Redis, MCP and OAuth services",
)


@pytest.mark.anyio
async def test_real_postgres_redis_mcp_oauth_and_reconciliation(monkeypatch):
    assert require_database_at_head()
    monkeypatch.setattr(settings, "mcp_quota_enabled", True)
    monkeypatch.setattr(settings, "mcp_quota_backend", "redis")
    monkeypatch.setattr(settings, "mcp_quota_fail_closed", True)
    monkeypatch.setattr(settings, "mcp_quota_redis_prefix", "codemate:e2e:quota")
    monkeypatch.setattr(settings, "mcp_registry_master_key", "e2e-master-key-32-characters-long")
    monkeypatch.setattr(settings, "mcp_registry_require_https", False)
    monkeypatch.setattr(settings, "mcp_registry_allow_private_networks", True)

    with database.SessionLocal() as db:
        db.query(MCPQuotaEvent).delete()
        suffix = uuid.uuid4().hex[:8]
        tenant = MCPTenant(slug=f"e2e-tenant-{suffix}", name=f"E2E Tenant {suffix}")
        db.add(tenant)
        db.flush()
        repo = Repository(
            name=f"e2e-repo-{suffix}",
            tenant_id=tenant.id,
            repo_url="https://example.com/e2e.git",
            status="indexed",
        )
        db.add(repo)
        db.flush()
        run = AgentRun(
            repo_id=repo.id,
            tenant_id=tenant.id,
            principal_type="agent",
            principal_id="codemate-agent",
            user_input="production evidence",
            status="running",
        )
        db.add(run)
        db.commit()
        quota = MCPQuotaService(db)
        quota_keys = list(quota.redis.scan_iter(match="codemate:e2e:quota:*"))
        if quota_keys:
            quota.redis.delete(*quota_keys)
        quota.create_policy(
            tenant.id,
            {
                "principal_type": "agent",
                "principal_id": "codemate-agent",
                "server_name": "evidence",
                "tool_name": "echo",
                "daily_call_limit": 1,
                "rate_limit_per_minute": 10,
                "concurrent_limit": 2,
            },
            actor="e2e",
        )
        reserve, release = quota.client_hooks(quota.context_for_run(run))
        client = MCPClientService(
            servers=[
                MCPRemoteServerConfig(
                    name="evidence",
                    url="http://127.0.0.1:8765/mcp",
                    allowed_tools=["echo"],
                    tool_policies={"echo": "auto"},
                )
            ],
            quota_reserve=reserve,
            quota_release=release,
        )
        first = await client.call_tool(
            "evidence", "echo", {"value": "first"}, idempotency_key="logical-1"
        )
        duplicate = await client.call_tool(
            "evidence", "echo", {"value": "first"}, idempotency_key="logical-1"
        )
        with pytest.raises(MCPQuotaExceededError):
            await client.call_tool(
                "evidence", "echo", {"value": "second"}, idempotency_key="logical-2"
            )
        assert first["structuredContent"]["value"] == "first"
        assert duplicate["structuredContent"]["value"] == "first"
        assert db.scalar(select(func.count()).select_from(MCPQuotaEvent)) == 1

        policy = quota.list_policies(tenant.id)[0]
        day_key = (
            f"codemate:e2e:quota:{policy.id}:day:"
            f"{datetime.utcnow().strftime('%Y%m%d')}"
        )
        quota.redis.hset(day_key, mapping={"calls": 0, "cost": 0})
        report = quota.reconcile_redis(tenant.id, repair=True)
        assert report["status"] == "repaired"
        assert report["drifted_policy_count"] == 1

        delegated = MCPDelegatedIdentityService(db)
        provider = delegated.configure_provider(
            tenant_id=tenant.id,
            server_name="evidence",
            authorization_url="http://127.0.0.1:8766/authorize",
            token_url="http://127.0.0.1:8766/token",
            client_id="codemate-e2e",
            client_secret="e2e-secret",
            scopes=["mcp.read"],
            redirect_uri="http://127.0.0.1:8000/mcp-tenancy/oauth/callback",
        )
        authorization_url = delegated.start_authorization(
            provider.id, subject_provider="github", subject="alice"
        )["authorization_url"]
        state = parse_qs(urlsplit(authorization_url).query)["state"][0]
        identity = delegated.complete_authorization(code="e2e-code", state=state)
        assert identity["identity"]["subject"] == "alice"
        assert delegated.access_token(identity["identity"]["id"]) == "e2e-access"
