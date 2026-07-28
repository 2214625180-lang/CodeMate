import hashlib
import json
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.mcp_quota import (
    MCPQuotaCharge,
    MCPQuotaEvent,
    MCPQuotaPolicy,
    MCPQuotaRejection,
    MCPQuotaReconciliation,
)
from app.models.mcp_delegated_identity import MCPDelegatedIdentity
from app.models.mcp_tenant_membership import MCPTenantMembership


class MCPQuotaError(RuntimeError):
    pass


class MCPQuotaConflictError(MCPQuotaError):
    pass


class MCPQuotaNotFoundError(MCPQuotaError):
    pass


class MCPQuotaUnavailableError(MCPQuotaError):
    pass


class MCPQuotaExceededError(MCPQuotaError):
    def __init__(
        self,
        reason: str,
        *,
        policy_id: str | None,
        retry_after_seconds: int | None,
        detail: str,
    ):
        super().__init__(detail)
        self.reason = reason
        self.policy_id = policy_id
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class MCPQuotaContext:
    tenant_id: str
    repo_id: str | None
    run_id: str | None
    principal_type: str
    principal_id: str
    principal_provider: str | None = None
    delegated_identity_id: str | None = None
    run_created_at: datetime | None = None


@dataclass(frozen=True)
class MCPQuotaReservation:
    event_id: str | None
    lease_token: str | None
    policy_ids: tuple[str, ...]
    enabled: bool = True


REDIS_RESERVE_SCRIPT = """
local count = tonumber(ARGV[1])
local now_ms = tonumber(ARGV[2])
local lease_expiry = tonumber(ARGV[3])
local member = ARGV[4]
local cost = tonumber(ARGV[5])
local already_counted = ARGV[6] == '1'
if redis.call('EXISTS', KEYS[1]) == 1 then return {0, 0, 'quota_reconciling', 1} end
for i = 1, count do
  local key_offset = 1 + (i - 1) * 5
  local arg_offset = 6 + (i - 1) * 5
  local rate_limit = tonumber(ARGV[arg_offset + 1])
  local daily_calls_limit = tonumber(ARGV[arg_offset + 2])
  local daily_cost_limit = tonumber(ARGV[arg_offset + 3])
  local run_limit = tonumber(ARGV[arg_offset + 4])
  local concurrent_limit = tonumber(ARGV[arg_offset + 5])
  redis.call('ZREMRANGEBYSCORE', KEYS[key_offset + 4], '-inf', now_ms)
  local counted = already_counted or redis.call('EXISTS', KEYS[key_offset + 5]) == 1
  if not counted then
    if rate_limit >= 0 and tonumber(redis.call('GET', KEYS[key_offset + 1]) or '0') + 1 > rate_limit then
      return {0, i, 'rate_limit_per_minute', math.max(1, redis.call('TTL', KEYS[key_offset + 1]))}
    end
    if daily_calls_limit >= 0 and tonumber(redis.call('HGET', KEYS[key_offset + 2], 'calls') or '0') + 1 > daily_calls_limit then
      return {0, i, 'daily_call_limit', math.max(1, redis.call('TTL', KEYS[key_offset + 2]))}
    end
    if daily_cost_limit >= 0 and tonumber(redis.call('HGET', KEYS[key_offset + 2], 'cost') or '0') + cost > daily_cost_limit then
      return {0, i, 'daily_cost_limit', math.max(1, redis.call('TTL', KEYS[key_offset + 2]))}
    end
    if run_limit >= 0 and tonumber(redis.call('GET', KEYS[key_offset + 3]) or '0') + 1 > run_limit then
      return {0, i, 'run_call_limit', 0}
    end
  end
  local existing_member = redis.call('ZSCORE', KEYS[key_offset + 4], member)
  if not existing_member and concurrent_limit >= 0 and redis.call('ZCARD', KEYS[key_offset + 4]) + 1 > concurrent_limit then
    local first = redis.call('ZRANGE', KEYS[key_offset + 4], 0, 0, 'WITHSCORES')
    local retry_after = 1
    if first[2] then retry_after = math.max(1, math.ceil((tonumber(first[2]) - now_ms) / 1000)) end
    return {0, i, 'concurrent_limit', retry_after}
  end
end
for i = 1, count do
  local key_offset = 1 + (i - 1) * 5
  local counted = already_counted or redis.call('EXISTS', KEYS[key_offset + 5]) == 1
  if not counted then
    redis.call('INCR', KEYS[key_offset + 1]); redis.call('EXPIRE', KEYS[key_offset + 1], 120)
    redis.call('HINCRBY', KEYS[key_offset + 2], 'calls', 1)
    redis.call('HINCRBYFLOAT', KEYS[key_offset + 2], 'cost', cost)
    redis.call('EXPIRE', KEYS[key_offset + 2], 172800)
    redis.call('INCR', KEYS[key_offset + 3]); redis.call('EXPIRE', KEYS[key_offset + 3], 691200)
    redis.call('SET', KEYS[key_offset + 5], '1', 'EX', 691200)
  end
  redis.call('ZADD', KEYS[key_offset + 4], lease_expiry, member)
  redis.call('EXPIRE', KEYS[key_offset + 4], 691200)
end
return {1}
"""


class MCPQuotaService:
    def __init__(self, db: Session, redis_client: Redis | None = None):
        self.db = db
        self._redis = redis_client

    def context_for_run(self, run: AgentRun) -> MCPQuotaContext:
        identity = (
            self.db.get(MCPDelegatedIdentity, run.delegated_identity_id)
            if run.delegated_identity_id
            else None
        )
        return MCPQuotaContext(
            tenant_id=str(run.tenant_id or ""),
            repo_id=run.repo_id,
            run_id=run.id,
            principal_type=run.principal_type,
            principal_id=run.principal_id,
            principal_provider=identity.subject_provider if identity else None,
            delegated_identity_id=run.delegated_identity_id,
            run_created_at=run.created_at,
        )

    def client_hooks(self, context: MCPQuotaContext):
        def reserve_hook(
            server_name: str,
            tool_name: str,
            arguments: dict[str, Any],
            idempotency_key: str | None,
            execution_id: str | None,
        ) -> MCPQuotaReservation:
            key = (
                quota_idempotency_key("provided", context.tenant_id, idempotency_key)
                if idempotency_key
                else quota_idempotency_key(
                    "client",
                    context.tenant_id,
                    context.run_id or secrets.token_hex(16),
                    server_name,
                    tool_name,
                    arguments,
                )
            )
            return self.reserve(
                context,
                server_name=server_name,
                tool_name=tool_name,
                idempotency_key=key,
                execution_id=execution_id,
            )

        def release_hook(reservation: MCPQuotaReservation, outcome: str) -> None:
            self.release(reservation, outcome=outcome)

        return reserve_hook, release_hook

    def create_policy(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> MCPQuotaPolicy:
        if self.policy_count(tenant_id) >= max(1, settings.mcp_quota_max_policies_per_tenant):
            raise MCPQuotaConflictError("Tenant quota policy limit reached")
        normalized = normalize_policy_payload(tenant_id, payload)
        policy = MCPQuotaPolicy(
            **normalized,
            scope_key=policy_scope_key(normalized),
            created_by=actor,
            updated_by=actor,
        )
        self.db.add(policy)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise MCPQuotaConflictError("A quota policy already exists for this scope") from exc
        self.db.refresh(policy)
        return policy

    def update_policy(
        self,
        policy_id: str,
        payload: dict[str, Any],
        *,
        expected_version: int,
        actor: str,
    ) -> MCPQuotaPolicy:
        policy = self._locked_policy(policy_id)
        if policy.version != expected_version:
            raise MCPQuotaConflictError("Quota policy version conflict")
        current = policy_payload(policy)
        for field in (
            "repo_id",
            "principal_type",
            "principal_id",
            "server_name",
            "tool_name",
        ):
            if field in payload and payload[field] != current[field]:
                raise MCPQuotaConflictError(
                    "Quota policy scope is immutable; create a new policy instead"
                )
        current.update(payload)
        normalized = normalize_policy_payload(policy.tenant_id, current)
        for key, value in normalized.items():
            setattr(policy, key, value)
        policy.scope_key = policy_scope_key(normalized)
        policy.updated_by = actor
        policy.version += 1
        policy.updated_at = datetime.utcnow()
        self.db.add(policy)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise MCPQuotaConflictError("A quota policy already exists for this scope") from exc
        self.db.refresh(policy)
        return policy

    def disable_policy(self, policy_id: str, *, actor: str) -> MCPQuotaPolicy:
        policy = self._locked_policy(policy_id)
        policy.enabled = False
        policy.updated_by = actor
        policy.version += 1
        policy.updated_at = datetime.utcnow()
        self.db.add(policy)
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def reset_policy(
        self,
        policy_id: str,
        *,
        expected_version: int,
        actor: str,
    ) -> MCPQuotaPolicy:
        policy = self._locked_policy(policy_id)
        if policy.version != expected_version:
            raise MCPQuotaConflictError("Quota policy version conflict")
        policy.reset_at = datetime.utcnow()
        policy.updated_by = actor
        policy.version += 1
        policy.updated_at = policy.reset_at
        self.db.add(policy)
        self._clear_redis_policy(policy.id)
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def temporarily_adjust_policy(
        self,
        policy_id: str,
        *,
        overrides: dict[str, Any],
        duration_seconds: int,
        expected_version: int,
        actor: str,
    ) -> MCPQuotaPolicy:
        allowed = {
            "rate_limit_per_minute",
            "daily_call_limit",
            "daily_cost_limit",
            "concurrent_limit",
            "run_call_limit",
            "max_run_duration_seconds",
        }
        if not overrides or set(overrides) - allowed:
            raise MCPQuotaConflictError("Unsupported temporary quota override")
        policy = self._locked_policy(policy_id)
        if policy.version != expected_version:
            raise MCPQuotaConflictError("Quota policy version conflict")
        policy.temporary_override_json = overrides
        policy.temporary_override_expires_at = datetime.utcnow() + timedelta(
            seconds=max(60, min(duration_seconds, 7 * 24 * 60 * 60))
        )
        policy.updated_by = actor
        policy.version += 1
        policy.updated_at = datetime.utcnow()
        self.db.add(policy)
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def list_policies(self, tenant_id: str) -> list[MCPQuotaPolicy]:
        return list(
            self.db.scalars(
                select(MCPQuotaPolicy)
                .where(MCPQuotaPolicy.tenant_id == tenant_id)
                .order_by(MCPQuotaPolicy.created_at.asc())
            )
        )

    def policy_count(self, tenant_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(MCPQuotaPolicy).where(
                    MCPQuotaPolicy.tenant_id == tenant_id,
                    MCPQuotaPolicy.enabled.is_(True),
                )
            )
            or 0
        )

    def reserve(
        self,
        context: MCPQuotaContext,
        *,
        server_name: str,
        tool_name: str,
        idempotency_key: str,
        execution_id: str | None = None,
    ) -> MCPQuotaReservation:
        if not settings.mcp_quota_enabled:
            return MCPQuotaReservation(None, None, (), enabled=False)
        if not context.tenant_id:
            raise MCPQuotaUnavailableError("MCP quota context has no tenant")
        now = datetime.utcnow()
        policies = self._matching_policies(context, server_name, tool_name, lock=True)
        if not policies:
            return MCPQuotaReservation(None, None, (), enabled=False)
        existing = self.db.scalar(
            select(MCPQuotaEvent).where(MCPQuotaEvent.idempotency_key == idempotency_key)
        )
        if existing and (
            existing.tenant_id != context.tenant_id
            or existing.server_name != server_name
            or existing.tool_name != tool_name
        ):
            raise MCPQuotaConflictError("Quota idempotency key was reused for another request")
        if existing and existing.lease_expires_at and existing.lease_expires_at > now:
            self._reject(
                policies[0],
                context,
                server_name,
                tool_name,
                "idempotency_in_progress",
                max(1, math.ceil((existing.lease_expires_at - now).total_seconds())),
            )
        cost_units = max(
            [effective_policy_values(policy, now)["call_cost_units"] for policy in policies]
            or [settings.mcp_quota_default_call_cost_units]
        )
        for policy in policies:
            self._check_policy(
                policy,
                context,
                now=now,
                cost_units=cost_units,
                existing_event=existing,
                server_name=server_name,
                tool_name=tool_name,
            )
        lease_token = secrets.token_hex(24)
        lease_seconds = max(1, settings.mcp_quota_concurrency_lease_seconds)
        event = existing or MCPQuotaEvent(
            idempotency_key=idempotency_key,
            execution_id=execution_id,
            tenant_id=context.tenant_id,
            repo_id=context.repo_id,
            run_id=context.run_id,
            delegated_identity_id=context.delegated_identity_id,
            principal_type=context.principal_type,
            principal_id=context.principal_id,
            server_name=server_name,
            tool_name=tool_name,
            cost_units=cost_units,
        )
        event.status = "reserved"
        event.lease_token = lease_token
        event.lease_expires_at = now + timedelta(seconds=lease_seconds)
        event.released_at = None
        event.updated_at = now
        self.db.add(event)
        if existing is None:
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                return self.reserve(
                    context,
                    server_name=server_name,
                    tool_name=tool_name,
                    idempotency_key=idempotency_key,
                    execution_id=execution_id,
                )
            for policy in policies:
                self.db.add(
                    MCPQuotaCharge(
                        event_id=event.id,
                        policy_id=policy.id,
                        cost_units=cost_units,
                    )
                )
        try:
            self._redis_reserve(
                policies,
                event_id=event.id,
                idempotency_key=idempotency_key,
                cost_units=cost_units,
                already_counted=existing is not None,
                now=now,
                lease_seconds=lease_seconds,
                run_id=context.run_id,
            )
            self.db.commit()
        except MCPQuotaExceededError as exc:
            self.db.rollback()
            self.db.add(
                MCPQuotaRejection(
                    policy_id=exc.policy_id,
                    tenant_id=context.tenant_id,
                    repo_id=context.repo_id,
                    run_id=context.run_id,
                    principal_type=context.principal_type,
                    principal_id=context.principal_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    reason=exc.reason,
                    retry_after_seconds=exc.retry_after_seconds,
                    detail=str(exc),
                    metadata_json={"source": "redis"},
                )
            )
            self.db.commit()
            raise
        except Exception:
            self.db.rollback()
            self._redis_release(tuple(policy.id for policy in policies), event.id)
            raise
        self.db.refresh(event)
        return MCPQuotaReservation(
            event.id,
            lease_token,
            tuple(policy.id for policy in policies),
        )

    def release(self, reservation: MCPQuotaReservation, *, outcome: str) -> None:
        if not reservation.enabled or not reservation.event_id:
            return
        event = self.db.get(MCPQuotaEvent, reservation.event_id)
        if event is not None and event.lease_token == reservation.lease_token:
            event.status = outcome[:32]
            event.lease_token = None
            event.lease_expires_at = None
            event.released_at = datetime.utcnow()
            event.updated_at = event.released_at
            self.db.add(event)
            self.db.commit()
        self._redis_release(reservation.policy_ids, reservation.event_id)

    def overview(self, tenant_id: str, *, window_days: int = 1) -> dict[str, Any]:
        now = datetime.utcnow()
        cutoff = now - timedelta(days=max(1, min(window_days, 90)))
        events = list(
            self.db.scalars(
                select(MCPQuotaEvent)
                .where(MCPQuotaEvent.tenant_id == tenant_id, MCPQuotaEvent.created_at >= cutoff)
                .order_by(MCPQuotaEvent.created_at.desc())
            )
        )
        rejections = list(
            self.db.scalars(
                select(MCPQuotaRejection)
                .where(
                    MCPQuotaRejection.tenant_id == tenant_id,
                    MCPQuotaRejection.created_at >= cutoff,
                )
                .order_by(MCPQuotaRejection.created_at.desc())
            )
        )
        policies = self.list_policies(tenant_id)
        policy_usage = [self._policy_public_usage(item, now) for item in policies]
        server_calls: dict[str, int] = {}
        tool_calls: dict[str, int] = {}
        principal_calls: dict[str, int] = {}
        for event in events:
            server_calls[event.server_name] = server_calls.get(event.server_name, 0) + 1
            qualified = f"{event.server_name}.{event.tool_name}"
            tool_calls[qualified] = tool_calls.get(qualified, 0) + 1
            principal = f"{event.principal_type}:{event.principal_id}"
            principal_calls[principal] = principal_calls.get(principal, 0) + 1
        alerts = []
        for item in policy_usage:
            if item["enabled"] and item["frozen"]:
                alerts.append(
                    {
                        "severity": "critical",
                        "type": "quota_policy_frozen",
                        "policy_id": item["id"],
                        "message": "MCP quota policy is frozen",
                    }
                )
            if item["enabled"] and item["utilization"] >= item["warning_threshold"]:
                alerts.append(
                    {
                        "severity": "critical" if item["utilization"] >= 1 else "warning",
                        "type": "quota_utilization",
                        "policy_id": item["id"],
                        "message": f'Quota utilization is {item["utilization"]:.0%}',
                    }
                )
        if len(rejections) >= max(1, settings.mcp_quota_rejection_alert_threshold):
            alerts.append(
                {
                    "severity": "warning",
                    "type": "quota_rejections",
                    "message": f"{len(rejections)} quota requests were rejected",
                }
            )
        return {
            "generated_at": now.isoformat(),
            "window_days": window_days,
            "summary": {
                "calls": len(events),
                "cost_units": round(sum(item.cost_units for item in events), 4),
                "rejections": len(rejections),
                "active_concurrency": sum(
                    bool(item.lease_expires_at and item.lease_expires_at > now) for item in events
                ),
                "delegated_user_calls": sum(bool(item.delegated_identity_id) for item in events),
            },
            "policies": policy_usage,
            "per_server": sorted(server_calls.items(), key=lambda item: (-item[1], item[0])),
            "per_tool": sorted(tool_calls.items(), key=lambda item: (-item[1], item[0])),
            "per_principal": sorted(
                principal_calls.items(), key=lambda item: (-item[1], item[0])
            ),
            "alerts": alerts,
            "recent_rejections": [rejection_public(item) for item in rejections[:50]],
            "recent_events": [event_public(item) for item in events[:50]],
        }

    def prometheus(self, tenant_id: str, *, window_days: int = 1) -> str:
        overview = self.overview(tenant_id, window_days=window_days)
        tenant = prometheus_label(tenant_id)
        summary = overview["summary"]
        lines = [
            "# HELP codemate_mcp_quota_calls Tenant MCP calls in the selected window.",
            "# TYPE codemate_mcp_quota_calls gauge",
            f'codemate_mcp_quota_calls{{tenant="{tenant}"}} {summary["calls"]}',
            "# HELP codemate_mcp_quota_cost_units Tenant MCP budget units used.",
            "# TYPE codemate_mcp_quota_cost_units gauge",
            f'codemate_mcp_quota_cost_units{{tenant="{tenant}"}} {summary["cost_units"]}',
            "# HELP codemate_mcp_quota_rejections Tenant MCP quota rejections.",
            "# TYPE codemate_mcp_quota_rejections gauge",
            f'codemate_mcp_quota_rejections{{tenant="{tenant}"}} {summary["rejections"]}',
            "# HELP codemate_mcp_quota_active_concurrency Active Tenant MCP quota leases.",
            "# TYPE codemate_mcp_quota_active_concurrency gauge",
            f'codemate_mcp_quota_active_concurrency{{tenant="{tenant}"}} '
            f'{summary["active_concurrency"]}',
            "# HELP codemate_mcp_quota_utilization MCP quota policy utilization ratio.",
            "# TYPE codemate_mcp_quota_utilization gauge",
        ]
        for policy in overview["policies"]:
            lines.append(
                f'codemate_mcp_quota_utilization{{tenant="{tenant}",policy="{policy["id"]}"}} '
                f'{policy["utilization"]}'
            )
        lines.append("")
        return "\n".join(lines)

    def reconcile_redis(self, tenant_id: str, *, repair: bool = False) -> dict[str, Any]:
        if settings.mcp_quota_backend.strip().lower() != "redis":
            report = {"status": "skipped", "reason": "quota_backend_is_not_redis"}
            self._record_reconciliation(tenant_id, report, repaired=False)
            return report
        prefix = settings.mcp_quota_redis_prefix.rstrip(":")
        lock_key = f"{prefix}:reconcile:{tenant_id}"
        lock_token = secrets.token_hex(24)
        try:
            if not self.redis.set(lock_key, lock_token, nx=True, ex=60):
                raise MCPQuotaConflictError("Quota reconciliation is already running")
            time.sleep(0.1)
            now = datetime.utcnow()
            policies = self.list_policies(tenant_id)
            drift: dict[str, Any] = {}
            rebuilt = 0
            for policy in policies:
                expected = self._reconciliation_snapshot(policy, now)
                actual = self._redis_policy_snapshot(policy, now)
                differences = {
                    key: {"database": expected[key], "redis": actual[key]}
                    for key in expected
                    if key in actual and expected[key] != actual[key]
                }
                if differences:
                    drift[policy.id] = differences
                if repair and differences:
                    self._rebuild_redis_policy(policy, now)
                    rebuilt += 1
            status = "repaired" if repair and drift else ("drift_detected" if drift else "clean")
            report = {
                "status": status,
                "tenant_id": tenant_id,
                "policy_count": len(policies),
                "drifted_policy_count": len(drift),
                "rebuilt_policy_count": rebuilt,
                "drift": drift,
                "generated_at": now.isoformat(),
            }
            self._record_reconciliation(tenant_id, report, repaired=bool(repair and drift))
            return report
        except RedisError as exc:
            report = {"status": "failed", "error": str(exc)}
            self._record_reconciliation(tenant_id, report, repaired=False, error=str(exc))
            raise MCPQuotaUnavailableError("MCP quota Redis reconciliation failed") from exc
        finally:
            try:
                self.redis.eval(
                    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                    "return redis.call('DEL', KEYS[1]) else return 0 end",
                    1,
                    lock_key,
                    lock_token,
                )
            except RedisError:
                pass

    def purge_usage(
        self,
        tenant_id: str,
        *,
        retention_days: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        days = max(30, retention_days or settings.mcp_quota_retention_days)
        cutoff = datetime.utcnow() - timedelta(days=days)
        event_ids = select(MCPQuotaEvent.id).where(
            MCPQuotaEvent.tenant_id == tenant_id,
            MCPQuotaEvent.created_at < cutoff,
            or_(
                MCPQuotaEvent.lease_expires_at.is_(None),
                MCPQuotaEvent.lease_expires_at < datetime.utcnow(),
            ),
        )
        event_count = int(
            self.db.scalar(select(func.count()).select_from(event_ids.subquery())) or 0
        )
        rejection_count = int(
            self.db.scalar(
                select(func.count()).select_from(MCPQuotaRejection).where(
                    MCPQuotaRejection.tenant_id == tenant_id,
                    MCPQuotaRejection.created_at < cutoff,
                )
            )
            or 0
        )
        if not dry_run:
            self.db.execute(
                delete(MCPQuotaCharge).where(MCPQuotaCharge.event_id.in_(event_ids))
            )
            self.db.execute(delete(MCPQuotaEvent).where(MCPQuotaEvent.id.in_(event_ids)))
            self.db.execute(
                delete(MCPQuotaRejection).where(
                    MCPQuotaRejection.tenant_id == tenant_id,
                    MCPQuotaRejection.created_at < cutoff,
                )
            )
            self.db.commit()
        return {
            "tenant_id": tenant_id,
            "dry_run": dry_run,
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "events": event_count,
            "rejections": rejection_count,
        }

    def recent_reconciliations(self, tenant_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        items = self.db.scalars(
            select(MCPQuotaReconciliation)
            .where(MCPQuotaReconciliation.tenant_id == tenant_id)
            .order_by(MCPQuotaReconciliation.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return [
            {
                "id": item.id,
                "status": item.status,
                "repaired": item.repaired,
                "drift": item.drift_json,
                "error_message": item.error_message,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]

    def _reconciliation_snapshot(
        self, policy: MCPQuotaPolicy, now: datetime
    ) -> dict[str, Any]:
        usage = self._policy_usage(policy, now, None)
        return {
            "minute_calls": usage["minute_calls"],
            "daily_calls": usage["daily_calls"],
            "daily_cost": round(usage["daily_cost"], 6),
            "active_concurrency": usage["active_concurrency"],
        }

    def _redis_policy_snapshot(
        self, policy: MCPQuotaPolicy, now: datetime
    ) -> dict[str, Any]:
        root = f"{settings.mcp_quota_redis_prefix.rstrip(':')}:{policy.id}"
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        pipeline = self.redis.pipeline(transaction=False)
        pipeline.get(f"{root}:minute:{minute}")
        pipeline.hget(f"{root}:day:{day}", "calls")
        pipeline.hget(f"{root}:day:{day}", "cost")
        pipeline.zremrangebyscore(f"{root}:concurrency", "-inf", int(now.timestamp() * 1000))
        pipeline.zcard(f"{root}:concurrency")
        minute_calls, daily_calls, daily_cost, _removed, concurrency = pipeline.execute()
        return {
            "minute_calls": int(minute_calls or 0),
            "daily_calls": int(daily_calls or 0),
            "daily_cost": round(float(daily_cost or 0), 6),
            "active_concurrency": int(concurrency or 0),
        }

    def _rebuild_redis_policy(self, policy: MCPQuotaPolicy, now: datetime) -> None:
        prefix = settings.mcp_quota_redis_prefix.rstrip(":")
        root = f"{prefix}:{policy.id}"
        keys = list(self.redis.scan_iter(match=f"{root}:*", count=500))
        pipeline = self.redis.pipeline(transaction=True)
        if keys:
            pipeline.delete(*keys)
        usage = self._policy_usage(policy, now, None)
        minute_key = f"{root}:minute:{now.strftime('%Y%m%d%H%M')}"
        day_key = f"{root}:day:{now.strftime('%Y%m%d')}"
        if usage["minute_calls"]:
            pipeline.set(minute_key, usage["minute_calls"], ex=120)
        if usage["daily_calls"] or usage["daily_cost"]:
            pipeline.hset(
                day_key,
                mapping={"calls": usage["daily_calls"], "cost": usage["daily_cost"]},
            )
            pipeline.expire(day_key, 172800)
        cutoff = now - timedelta(days=8)
        statement = (
            select(MCPQuotaEvent)
            .join(MCPQuotaCharge, MCPQuotaCharge.event_id == MCPQuotaEvent.id)
            .where(
                MCPQuotaCharge.policy_id == policy.id,
                MCPQuotaEvent.created_at >= cutoff,
            )
        )
        if policy.reset_at:
            statement = statement.where(MCPQuotaCharge.created_at >= policy.reset_at)
        events = list(self.db.scalars(statement))
        run_counts: dict[str, int] = {}
        active: dict[str, float] = {}
        for event in events:
            if event.run_id:
                run_counts[event.run_id] = run_counts.get(event.run_id, 0) + 1
            idem_hash = hashlib.sha256(event.idempotency_key.encode()).hexdigest()
            pipeline.set(f"{root}:idem:{idem_hash}", "1", ex=691200)
            if event.lease_expires_at and event.lease_expires_at > now:
                active[event.id] = event.lease_expires_at.timestamp() * 1000
        for run_id, calls in run_counts.items():
            pipeline.set(f"{root}:run:{run_id}", calls, ex=691200)
        if active:
            pipeline.zadd(f"{root}:concurrency", active)
            pipeline.expire(f"{root}:concurrency", 691200)
        pipeline.execute()

    def _record_reconciliation(
        self,
        tenant_id: str,
        report: dict[str, Any],
        *,
        repaired: bool,
        error: str | None = None,
    ) -> None:
        self.db.add(
            MCPQuotaReconciliation(
                tenant_id=tenant_id,
                status=str(report.get("status") or "unknown"),
                repaired=repaired,
                drift_json=report.get("drift") or report,
                error_message=error,
            )
        )
        self.db.commit()

    def _matching_policies(
        self,
        context: MCPQuotaContext,
        server_name: str,
        tool_name: str,
        *,
        lock: bool,
    ) -> list[MCPQuotaPolicy]:
        statement = select(MCPQuotaPolicy).where(
            MCPQuotaPolicy.tenant_id == context.tenant_id,
            MCPQuotaPolicy.enabled.is_(True),
            or_(MCPQuotaPolicy.repo_id.is_(None), MCPQuotaPolicy.repo_id == context.repo_id),
            MCPQuotaPolicy.server_name.in_([server_name, "*"]),
            MCPQuotaPolicy.tool_name.in_([tool_name, "*"]),
        ).order_by(MCPQuotaPolicy.id.asc())
        if lock:
            statement = statement.with_for_update()
        policies = list(self.db.scalars(statement))
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
        return [
            item
            for item in policies
            if (item.principal_type, item.principal_id) in principals
        ]

    def _check_policy(
        self,
        policy: MCPQuotaPolicy,
        context: MCPQuotaContext,
        *,
        now: datetime,
        cost_units: float,
        existing_event: MCPQuotaEvent | None,
        server_name: str,
        tool_name: str,
    ) -> None:
        if policy.frozen:
            self._reject(policy, context, server_name, tool_name, "tenant_frozen", None)
        limits = effective_policy_values(policy, now)
        if (
            limits["max_run_duration_seconds"] is not None
            and context.run_created_at is not None
            and now - context.run_created_at
            >= timedelta(seconds=limits["max_run_duration_seconds"])
        ):
            self._reject(policy, context, server_name, tool_name, "run_duration_limit", None)
        usage = self._policy_usage(policy, now, context.run_id, exclude_event_id=existing_event.id if existing_event else None)
        if existing_event is None:
            checks = (
                (limits["rate_limit_per_minute"], usage["minute_calls"] + 1, "rate_limit_per_minute", 60),
                (limits["daily_call_limit"], usage["daily_calls"] + 1, "daily_call_limit", seconds_until_tomorrow(now)),
                (limits["daily_cost_limit"], usage["daily_cost"] + cost_units, "daily_cost_limit", seconds_until_tomorrow(now)),
                (limits["run_call_limit"], usage["run_calls"] + 1, "run_call_limit", None),
            )
            for limit, proposed, reason, retry_after in checks:
                if limit is not None and proposed > limit:
                    self._reject(policy, context, server_name, tool_name, reason, retry_after)
        if limits["concurrent_limit"] is not None and usage["active_concurrency"] + 1 > limits["concurrent_limit"]:
            self._reject(
                policy,
                context,
                server_name,
                tool_name,
                "concurrent_limit",
                usage["concurrency_retry_after"],
            )

    def _policy_usage(
        self,
        policy: MCPQuotaPolicy,
        now: datetime,
        run_id: str | None,
        *,
        exclude_event_id: str | None = None,
    ) -> dict[str, Any]:
        base = select(MCPQuotaCharge).join(MCPQuotaEvent, MCPQuotaEvent.id == MCPQuotaCharge.event_id).where(
            MCPQuotaCharge.policy_id == policy.id
        )
        if policy.reset_at:
            base = base.where(MCPQuotaCharge.created_at >= policy.reset_at)
        minute_cutoff = max_datetime(now - timedelta(minutes=1), policy.reset_at)
        day_cutoff = max_datetime(now.replace(hour=0, minute=0, second=0, microsecond=0), policy.reset_at)
        minute_calls = self._sum_calls(base.where(MCPQuotaCharge.created_at >= minute_cutoff))
        daily_statement = base.where(MCPQuotaCharge.created_at >= day_cutoff)
        daily_calls = self._sum_calls(daily_statement)
        daily_cost = self._sum_cost(daily_statement)
        run_calls = 0
        if run_id:
            run_calls = self._sum_calls(base.where(MCPQuotaEvent.run_id == run_id))
        active = base.where(MCPQuotaEvent.lease_expires_at > now)
        if exclude_event_id:
            active = active.where(MCPQuotaEvent.id != exclude_event_id)
        active_events = list(self.db.scalars(active.with_only_columns(MCPQuotaEvent)))
        retry_after = None
        expiries = [item.lease_expires_at for item in active_events if item.lease_expires_at]
        if expiries:
            retry_after = max(1, math.ceil((min(expiries) - now).total_seconds()))
        return {
            "minute_calls": minute_calls,
            "daily_calls": daily_calls,
            "daily_cost": daily_cost,
            "run_calls": run_calls,
            "active_concurrency": len({item.id for item in active_events}),
            "concurrency_retry_after": retry_after,
        }

    def _policy_public_usage(self, policy: MCPQuotaPolicy, now: datetime) -> dict[str, Any]:
        usage = self._policy_usage(policy, now, None)
        limits = effective_policy_values(policy, now)
        ratios = []
        for used, limit in (
            (usage["minute_calls"], limits["rate_limit_per_minute"]),
            (usage["daily_calls"], limits["daily_call_limit"]),
            (usage["daily_cost"], limits["daily_cost_limit"]),
            (usage["active_concurrency"], limits["concurrent_limit"]),
        ):
            if limit is not None and limit > 0:
                ratios.append(float(used) / float(limit))
        return {
            **policy_public(policy),
            "usage": usage,
            "effective_limits": limits,
            "utilization": round(max(ratios or [0.0]), 4),
        }

    def _sum_calls(self, statement: Any) -> int:
        return int(self.db.scalar(statement.with_only_columns(func.coalesce(func.sum(MCPQuotaCharge.calls), 0))) or 0)

    def _sum_cost(self, statement: Any) -> float:
        return float(self.db.scalar(statement.with_only_columns(func.coalesce(func.sum(MCPQuotaCharge.cost_units), 0.0))) or 0.0)

    def _reject(
        self,
        policy: MCPQuotaPolicy | None,
        context: MCPQuotaContext,
        server_name: str,
        tool_name: str,
        reason: str,
        retry_after: int | None,
    ) -> None:
        detail = f"MCP quota denied {server_name}.{tool_name}: {reason}"
        self.db.add(
            MCPQuotaRejection(
                policy_id=policy.id if policy else None,
                tenant_id=context.tenant_id,
                repo_id=context.repo_id,
                run_id=context.run_id,
                principal_type=context.principal_type,
                principal_id=context.principal_id,
                server_name=server_name,
                tool_name=tool_name,
                reason=reason,
                retry_after_seconds=retry_after,
                detail=detail,
            )
        )
        self.db.commit()
        raise MCPQuotaExceededError(
            reason,
            policy_id=policy.id if policy else None,
            retry_after_seconds=retry_after,
            detail=detail,
        )

    def _redis_reserve(
        self,
        policies: list[MCPQuotaPolicy],
        *,
        event_id: str,
        idempotency_key: str,
        cost_units: float,
        already_counted: bool,
        now: datetime,
        lease_seconds: int,
        run_id: str | None,
    ) -> None:
        if settings.mcp_quota_backend.strip().lower() != "redis":
            return
        prefix = settings.mcp_quota_redis_prefix.rstrip(":")
        keys = [f"{prefix}:reconcile:{policies[0].tenant_id}"]
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        arguments: list[Any] = [
            len(policies),
            int(now.timestamp() * 1000),
            int((now + timedelta(seconds=lease_seconds)).timestamp() * 1000),
            event_id,
            cost_units,
            "1" if already_counted else "0",
        ]
        idem_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        for policy in policies:
            limits = effective_policy_values(policy, now)
            root = f"{prefix}:{policy.id}"
            keys.extend(
                [
                    f"{root}:minute:{minute}",
                    f"{root}:day:{day}",
                    f"{root}:run:{run_id or event_id}",
                    f"{root}:concurrency",
                    f"{root}:idem:{idem_hash}",
                ]
            )
            arguments.extend(
                [
                    redis_limit(limits["rate_limit_per_minute"]),
                    redis_limit(limits["daily_call_limit"]),
                    redis_limit(limits["daily_cost_limit"]),
                    redis_limit(limits["run_call_limit"]),
                    redis_limit(limits["concurrent_limit"]),
                ]
            )
        try:
            result = self.redis.eval(REDIS_RESERVE_SCRIPT, len(keys), *keys, *arguments)
        except RedisError as exc:
            if settings.mcp_quota_fail_closed:
                raise MCPQuotaUnavailableError("MCP quota Redis backend is unavailable") from exc
            return
        if not result or int(result[0]) != 1:
            raw_index = int(result[1])
            index = max(1, raw_index) - 1
            reason = decode_redis(result[2])
            retry_after = int(result[3]) if len(result) > 3 and int(result[3]) > 0 else None
            raise MCPQuotaExceededError(
                reason,
                policy_id=policies[index].id if raw_index > 0 else None,
                retry_after_seconds=retry_after,
                detail=f"MCP quota denied by distributed limiter: {reason}",
            )

    def _redis_release(self, policy_ids: tuple[str, ...], event_id: str) -> None:
        if settings.mcp_quota_backend.strip().lower() != "redis" or not policy_ids:
            return
        prefix = settings.mcp_quota_redis_prefix.rstrip(":")
        try:
            pipeline = self.redis.pipeline(transaction=False)
            for policy_id in policy_ids:
                pipeline.zrem(f"{prefix}:{policy_id}:concurrency", event_id)
            pipeline.execute()
        except Exception:  # noqa: BLE001 - lease expiry is the final recovery path.
            return

    def _clear_redis_policy(self, policy_id: str) -> None:
        if settings.mcp_quota_backend.strip().lower() != "redis":
            return
        prefix = f"{settings.mcp_quota_redis_prefix.rstrip(':')}:{policy_id}:*"
        try:
            keys = list(self.redis.scan_iter(match=prefix, count=100))
            if keys:
                self.redis.delete(*keys)
        except RedisError:
            if settings.mcp_quota_fail_closed:
                raise MCPQuotaUnavailableError("MCP quota Redis backend is unavailable")

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def _locked_policy(self, policy_id: str) -> MCPQuotaPolicy:
        policy = self.db.scalar(
            select(MCPQuotaPolicy)
            .where(MCPQuotaPolicy.id == policy_id)
            .with_for_update()
        )
        if policy is None:
            raise MCPQuotaNotFoundError("MCP quota policy not found")
        return policy


def normalize_policy_payload(tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "tenant_id": tenant_id,
        "repo_id": payload.get("repo_id") or None,
        "principal_type": str(payload.get("principal_type") or "*"),
        "principal_id": str(payload.get("principal_id") or "*"),
        "server_name": str(payload.get("server_name") or "*"),
        "tool_name": str(payload.get("tool_name") or "*"),
        "rate_limit_per_minute": positive_or_none(payload.get("rate_limit_per_minute")),
        "daily_call_limit": positive_or_none(payload.get("daily_call_limit")),
        "daily_cost_limit": positive_float_or_none(payload.get("daily_cost_limit")),
        "concurrent_limit": positive_or_none(payload.get("concurrent_limit")),
        "run_call_limit": positive_or_none(payload.get("run_call_limit")),
        "max_run_duration_seconds": positive_or_none(payload.get("max_run_duration_seconds")),
        "call_cost_units": float(
            payload.get("call_cost_units") or settings.mcp_quota_default_call_cost_units
        ),
        "warning_threshold": float(payload.get("warning_threshold") or 0.8),
        "enabled": bool(payload.get("enabled", True)),
        "frozen": bool(payload.get("frozen", False)),
    }
    if not 0 < result["warning_threshold"] <= 1:
        raise MCPQuotaConflictError("warning_threshold must be greater than 0 and at most 1")
    if result["call_cost_units"] <= 0:
        raise MCPQuotaConflictError("call_cost_units must be greater than 0")
    return result


def policy_scope_key(payload: dict[str, Any]) -> str:
    fields = [
        payload.get("tenant_id"),
        payload.get("repo_id"),
        payload.get("principal_type"),
        payload.get("principal_id"),
        payload.get("server_name"),
        payload.get("tool_name"),
    ]
    return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


def policy_payload(policy: MCPQuotaPolicy) -> dict[str, Any]:
    return {
        key: getattr(policy, key)
        for key in (
            "repo_id",
            "principal_type",
            "principal_id",
            "server_name",
            "tool_name",
            "rate_limit_per_minute",
            "daily_call_limit",
            "daily_cost_limit",
            "concurrent_limit",
            "run_call_limit",
            "max_run_duration_seconds",
            "call_cost_units",
            "warning_threshold",
            "enabled",
            "frozen",
        )
    }


def policy_public(policy: MCPQuotaPolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "tenant_id": policy.tenant_id,
        **policy_payload(policy),
        "reset_at": policy.reset_at.isoformat() if policy.reset_at else None,
        "temporary_override": policy.temporary_override_json,
        "temporary_override_expires_at": (
            policy.temporary_override_expires_at.isoformat()
            if policy.temporary_override_expires_at
            else None
        ),
        "version": policy.version,
        "created_by": policy.created_by,
        "updated_by": policy.updated_by,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


def event_public(event: MCPQuotaEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "principal": f"{event.principal_type}:{event.principal_id}",
        "server_name": event.server_name,
        "tool_name": event.tool_name,
        "cost_units": event.cost_units,
        "status": event.status,
        "delegated": bool(event.delegated_identity_id),
        "created_at": event.created_at.isoformat(),
        "released_at": event.released_at.isoformat() if event.released_at else None,
    }


def rejection_public(item: MCPQuotaRejection) -> dict[str, Any]:
    return {
        "id": item.id,
        "policy_id": item.policy_id,
        "run_id": item.run_id,
        "principal": f"{item.principal_type}:{item.principal_id}",
        "server_name": item.server_name,
        "tool_name": item.tool_name,
        "reason": item.reason,
        "retry_after_seconds": item.retry_after_seconds,
        "created_at": item.created_at.isoformat(),
    }


def positive_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    normalized = int(value)
    if normalized <= 0:
        raise MCPQuotaConflictError("Quota limits must be greater than 0")
    return normalized


def positive_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    normalized = float(value)
    if normalized <= 0:
        raise MCPQuotaConflictError("Quota limits must be greater than 0")
    return normalized


def max_datetime(first: datetime, second: datetime | None) -> datetime:
    return max(first, second) if second else first


def seconds_until_tomorrow(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((tomorrow - now).total_seconds()))


def redis_limit(value: Any) -> float:
    return float(value) if value is not None else -1


def decode_redis(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def effective_policy_values(policy: MCPQuotaPolicy, now: datetime) -> dict[str, Any]:
    values = {
        key: getattr(policy, key)
        for key in (
            "rate_limit_per_minute",
            "daily_call_limit",
            "daily_cost_limit",
            "concurrent_limit",
            "run_call_limit",
            "max_run_duration_seconds",
            "call_cost_units",
        )
    }
    if (
        policy.temporary_override_expires_at
        and policy.temporary_override_expires_at > now
        and policy.temporary_override_json
    ):
        values.update(policy.temporary_override_json)
    return values


def quota_idempotency_key(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
