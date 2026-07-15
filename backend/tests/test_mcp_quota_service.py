from datetime import datetime, timedelta

import pytest
from redis.exceptions import RedisError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.mcp_quota import MCPQuotaEvent, MCPQuotaRejection
from app.models.mcp_tenant import MCPTenant
from app.models.mcp_tenant_membership import MCPTenantMembership
from app.models.repository import Repository
from app.services.mcp_quota_service import (
    MCPQuotaContext,
    MCPQuotaExceededError,
    MCPQuotaService,
    MCPQuotaUnavailableError,
)


@pytest.fixture
def quota_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'quotas.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(settings, "mcp_quota_enabled", True)
    monkeypatch.setattr(settings, "mcp_quota_backend", "database")
    monkeypatch.setattr(settings, "mcp_quota_fail_closed", True)
    monkeypatch.setattr(settings, "mcp_quota_concurrency_lease_seconds", 60)
    tenant = MCPTenant(slug="acme-quota", name="Acme Quota")
    db.add(tenant)
    db.flush()
    repo = Repository(
        name="repo",
        tenant_id=tenant.id,
        repo_url="https://example.com/repo.git",
        status="indexed",
    )
    db.add(repo)
    db.flush()
    run = AgentRun(
        repo_id=repo.id,
        tenant_id=tenant.id,
        principal_type="agent",
        principal_id="codemate-agent",
        user_input="fix",
        status="running",
    )
    db.add(run)
    db.commit()
    yield db, tenant, repo, run
    db.close()


def policy_payload(**changes):
    return {
        "principal_type": "agent",
        "principal_id": "codemate-agent",
        "server_name": "docs",
        "tool_name": "search",
        "rate_limit_per_minute": 2,
        "daily_call_limit": 2,
        "daily_cost_limit": 2,
        "concurrent_limit": 1,
        "run_call_limit": 2,
        "call_cost_units": 1,
        **changes,
    }


def test_quota_enforces_concurrency_rate_budget_and_records_rejections(quota_db):
    db, tenant, _repo, run = quota_db
    service = MCPQuotaService(db)
    policy = service.create_policy(tenant.id, policy_payload(), actor="alice")
    context = service.context_for_run(run)
    first = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="a" * 64,
    )
    with pytest.raises(MCPQuotaExceededError) as concurrent:
        service.reserve(
            context,
            server_name="docs",
            tool_name="search",
            idempotency_key="b" * 64,
        )
    assert concurrent.value.reason == "concurrent_limit"

    service.release(first, outcome="succeeded")
    second = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="b" * 64,
    )
    service.release(second, outcome="failed")
    with pytest.raises(MCPQuotaExceededError) as rate:
        service.reserve(
            context,
            server_name="docs",
            tool_name="search",
            idempotency_key="c" * 64,
        )
    assert rate.value.reason == "rate_limit_per_minute"
    assert db.scalar(select(func.count()).select_from(MCPQuotaEvent)) == 2
    assert db.scalar(select(func.count()).select_from(MCPQuotaRejection)) == 2

    service.reset_policy(policy.id, expected_version=policy.version, actor="alice")
    third = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="c" * 64,
    )
    service.release(third, outcome="succeeded")


def test_quota_idempotency_does_not_charge_retry_twice(quota_db):
    db, tenant, _repo, run = quota_db
    service = MCPQuotaService(db)
    service.create_policy(
        tenant.id,
        policy_payload(rate_limit_per_minute=1, daily_call_limit=1, run_call_limit=1),
        actor="alice",
    )
    context = service.context_for_run(run)
    reservation = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="same".ljust(64, "x"),
    )
    with pytest.raises(MCPQuotaExceededError) as in_progress:
        service.reserve(
            context,
            server_name="docs",
            tool_name="search",
            idempotency_key="same".ljust(64, "x"),
        )
    assert in_progress.value.reason == "idempotency_in_progress"
    service.release(reservation, outcome="transport_unknown")
    retried = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="same".ljust(64, "x"),
    )
    service.release(retried, outcome="succeeded")

    overview = service.overview(tenant.id)
    assert overview["summary"]["calls"] == 1
    assert overview["summary"]["cost_units"] == 1
    assert overview["policies"][0]["usage"]["daily_calls"] == 1


def test_quota_freeze_run_duration_and_principal_scope(quota_db):
    _db, tenant, _repo, run = quota_db
    service = MCPQuotaService(_db)
    service.create_policy(
        tenant.id,
        policy_payload(frozen=True, max_run_duration_seconds=1),
        actor="alice",
    )
    context = MCPQuotaContext(
        tenant_id=tenant.id,
        repo_id=run.repo_id,
        run_id=run.id,
        principal_type="agent",
        principal_id="codemate-agent",
        run_created_at=datetime.utcnow() - timedelta(minutes=1),
    )
    with pytest.raises(MCPQuotaExceededError) as frozen:
        service.reserve(
            context,
            server_name="docs",
            tool_name="search",
            idempotency_key="f" * 64,
        )
    assert frozen.value.reason == "tenant_frozen"

    unrelated = MCPQuotaContext(tenant.id, run.repo_id, run.id, "agent", "other")
    assert service.reserve(
        unrelated,
        server_name="docs",
        tool_name="search",
        idempotency_key="u" * 64,
    ).enabled is False


def test_redis_failure_is_fail_closed(quota_db, monkeypatch):
    db, tenant, _repo, run = quota_db

    class BrokenRedis:
        def eval(self, *_args, **_kwargs):
            raise RedisError("down")

    monkeypatch.setattr(settings, "mcp_quota_backend", "redis")
    service = MCPQuotaService(db, redis_client=BrokenRedis())
    service.create_policy(tenant.id, policy_payload(), actor="alice")
    with pytest.raises(MCPQuotaUnavailableError):
        service.reserve(
            service.context_for_run(run),
            server_name="docs",
            tool_name="search",
            idempotency_key="r" * 64,
        )
    assert db.scalar(select(func.count()).select_from(MCPQuotaEvent)) == 0


def test_temporary_adjustment_raises_limit_without_losing_usage(quota_db):
    _db, tenant, _repo, run = quota_db
    service = MCPQuotaService(_db)
    policy = service.create_policy(
        tenant.id,
        policy_payload(
            rate_limit_per_minute=1,
            daily_call_limit=1,
            run_call_limit=1,
            concurrent_limit=2,
        ),
        actor="alice",
    )
    context = service.context_for_run(run)
    first = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="t1".ljust(64, "x"),
    )
    service.release(first, outcome="succeeded")
    service.temporarily_adjust_policy(
        policy.id,
        overrides={
            "rate_limit_per_minute": 2,
            "daily_call_limit": 2,
            "run_call_limit": 2,
        },
        duration_seconds=3600,
        expected_version=policy.version,
        actor="alice",
    )
    second = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="t2".ljust(64, "x"),
    )
    service.release(second, outcome="succeeded")
    assert service.overview(tenant.id)["summary"]["calls"] == 2


def test_delegated_user_matches_provider_scoped_role_quota(quota_db):
    db, tenant, repo, run = quota_db
    db.add(
        MCPTenantMembership(
            tenant_id=tenant.id,
            provider="github",
            subject="alice",
            role="member",
        )
    )
    db.commit()
    service = MCPQuotaService(db)
    service.create_policy(
        tenant.id,
        policy_payload(
            principal_type="role",
            principal_id="member",
            daily_call_limit=1,
        ),
        actor="admin",
    )
    context = MCPQuotaContext(
        tenant_id=tenant.id,
        repo_id=repo.id,
        run_id=run.id,
        principal_type="user",
        principal_id="alice",
        principal_provider="github",
        delegated_identity_id="identity-1",
    )
    reservation = service.reserve(
        context,
        server_name="docs",
        tool_name="search",
        idempotency_key="delegated".ljust(64, "x"),
    )
    service.release(reservation, outcome="succeeded")
    assert service.overview(tenant.id)["summary"]["delegated_user_calls"] == 1


def test_reconciliation_evidence_and_retention_cleanup(quota_db):
    db, tenant, _repo, run = quota_db
    service = MCPQuotaService(db)
    service.create_policy(tenant.id, policy_payload(), actor="admin")
    reservation = service.reserve(
        service.context_for_run(run),
        server_name="docs",
        tool_name="search",
        idempotency_key="old-event".ljust(64, "x"),
    )
    service.release(reservation, outcome="succeeded")
    event = db.get(MCPQuotaEvent, reservation.event_id)
    event.created_at = datetime.utcnow() - timedelta(days=120)
    event.updated_at = event.created_at
    db.add(event)
    db.commit()

    report = service.reconcile_redis(tenant.id)
    preview = service.purge_usage(tenant.id, retention_days=90, dry_run=True)
    deleted = service.purge_usage(tenant.id, retention_days=90, dry_run=False)

    assert report["status"] == "skipped"
    assert service.recent_reconciliations(tenant.id)[0]["status"] == "skipped"
    assert preview["events"] == deleted["events"] == 1
    assert db.get(MCPQuotaEvent, reservation.event_id) is None
