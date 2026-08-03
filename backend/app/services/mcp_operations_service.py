import asyncio
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.telemetry import mark_span_error, mcp_span
from app.models.mcp_server_health import MCPServerHealth
from app.models.mcp_tool_approval import MCPToolApproval
from app.models.mcp_tool_execution import MCPToolExecution
from app.services.mcp_approval_service import redact_sensitive


class MCPOperationsError(RuntimeError):
    pass


class MCPServerNotFoundError(MCPOperationsError):
    pass


class MCPCircuitConflictError(MCPOperationsError):
    pass


class MCPCircuitOpenError(MCPOperationsError):
    def __init__(self, health: MCPServerHealth):
        retry_after = None
        if health.cooldown_until:
            retry_after = max(
                0,
                math.ceil((health.cooldown_until - datetime.now(timezone.utc)).total_seconds()),
            )
        super().__init__(f"MCP circuit is open for server '{health.server_name}'")
        self.server_name = health.server_name
        self.retry_after_seconds = retry_after


class MCPOperationsService:
    def __init__(self, db: Session):
        self.db = db

    def register_servers(self, servers: list[dict[str, Any]]) -> list[MCPServerHealth]:
        registered: list[MCPServerHealth] = []
        for server in servers:
            name = str(server["name"])
            health = self._locked_or_create(name)
            health.public_url = str(server.get("url") or "") or None
            health.updated_at = datetime.now(timezone.utc)
            self.db.add(health)
            self.db.commit()
            self.db.refresh(health)
            registered.append(health)
        return registered

    def list_servers(self) -> list[MCPServerHealth]:
        return list(
            self.db.execute(
                select(MCPServerHealth).order_by(MCPServerHealth.server_name.asc())
            )
            .scalars()
            .all()
        )

    def get_server(self, server_name: str) -> MCPServerHealth:
        health = self.db.get(MCPServerHealth, server_name)
        if health is None:
            raise MCPServerNotFoundError("MCP server health record not found")
        return health

    def before_execution(self, server_name: str, execution_id: str) -> MCPServerHealth:
        health = self._locked_or_create(server_name)
        now = datetime.now(timezone.utc)
        if settings.mcp_circuit_breaker_enabled:
            if health.circuit_state == "open":
                if health.manual_open or not health.cooldown_until or now < health.cooldown_until:
                    health.circuit_rejections += 1
                    health.version += 1
                    health.updated_at = now
                    self.db.add(health)
                    self.db.commit()
                    self.db.refresh(health)
                    raise MCPCircuitOpenError(health)
                health.circuit_state = "half_open"
                health.half_open_trial_id = execution_id
                health.half_open_lease_expires_at = now + timedelta(
                    seconds=max(1, settings.mcp_circuit_half_open_lease_seconds)
                )
            elif health.circuit_state == "half_open":
                active_trial = (
                    health.half_open_trial_id
                    and health.half_open_trial_id != execution_id
                    and health.half_open_lease_expires_at
                    and now < health.half_open_lease_expires_at
                )
                if active_trial:
                    health.circuit_rejections += 1
                    health.version += 1
                    health.updated_at = now
                    self.db.add(health)
                    self.db.commit()
                    self.db.refresh(health)
                    raise MCPCircuitOpenError(health)
                health.half_open_trial_id = execution_id
                health.half_open_lease_expires_at = now + timedelta(
                    seconds=max(1, settings.mcp_circuit_half_open_lease_seconds)
                )
        health.total_requests += 1
        health.version += 1
        health.updated_at = now
        self.db.add(health)
        self.db.commit()
        self.db.refresh(health)
        return health

    def record_transport_success(self, server_name: str, latency_ms: float) -> MCPServerHealth:
        health = self._locked_or_create(server_name)
        now = datetime.now(timezone.utc)
        health.total_transport_successes += 1
        health.consecutive_failures = 0
        health.last_success_at = now
        health.last_latency_ms = round(latency_ms, 2)
        health.last_error = None
        if not health.manual_open:
            self._close_circuit(health)
        health.version += 1
        health.updated_at = now
        self.db.add(health)
        self.db.commit()
        self.db.refresh(health)
        return health

    def record_transport_failure(
        self,
        server_name: str,
        error: Exception | str,
        latency_ms: float,
    ) -> MCPServerHealth:
        health = self._locked_or_create(server_name)
        now = datetime.now(timezone.utc)
        health.total_transport_failures += 1
        self._record_failure(health, error, latency_ms, now)
        health.version += 1
        health.updated_at = now
        self.db.add(health)
        self.db.commit()
        self.db.refresh(health)
        return health

    def record_probe(
        self,
        server_name: str,
        *,
        ok: bool,
        latency_ms: float,
        result: dict[str, Any] | None = None,
        error: Exception | str | None = None,
    ) -> MCPServerHealth:
        health = self._locked_or_create(server_name)
        now = datetime.now(timezone.utc)
        health.total_probes += 1
        health.last_probe_at = now
        health.last_latency_ms = round(latency_ms, 2)
        if ok:
            health.last_probe_status = "healthy"
            health.last_success_at = now
            health.consecutive_failures = 0
            health.last_error = None
            health.protocol_version = str((result or {}).get("protocol_version") or "") or None
            server_info = (result or {}).get("server_info")
            health.server_info_json = server_info if isinstance(server_info, dict) else None
            if not health.manual_open:
                self._close_circuit(health)
        else:
            health.failed_probes += 1
            health.last_probe_status = "unhealthy"
            self._record_failure(health, error or "Health probe failed", latency_ms, now)
        health.version += 1
        health.updated_at = now
        self.db.add(health)
        self.db.commit()
        self.db.refresh(health)
        return health

    def control_circuit(
        self,
        server_name: str,
        *,
        action: str,
        expected_version: int,
    ) -> MCPServerHealth:
        if action not in {"open", "close", "reset"}:
            raise MCPCircuitConflictError("Unsupported circuit action")
        health = self._locked_existing(server_name)
        if health.version != expected_version:
            raise MCPCircuitConflictError("MCP server health version conflict")
        now = datetime.now(timezone.utc)
        if action == "open":
            self._open_circuit(health, now, manual=True)
        else:
            health.manual_open = False
            self._close_circuit(health)
            if action == "reset":
                health.total_requests = 0
                health.total_transport_successes = 0
                health.total_transport_failures = 0
                health.circuit_rejections = 0
                health.circuit_open_count = 0
                health.total_probes = 0
                health.failed_probes = 0
        health.version += 1
        health.updated_at = now
        self.db.add(health)
        self.db.commit()
        self.db.refresh(health)
        return health

    def probe_servers(self, client: Any, server_name: str | None = None) -> list[MCPServerHealth]:
        configured = client.configured_servers()
        self.register_servers(configured)
        names = [str(item["name"]) for item in configured]
        if server_name is not None:
            if server_name not in names:
                raise MCPServerNotFoundError("Configured MCP server not found")
            names = [server_name]
        probed: list[MCPServerHealth] = []
        for name in names:
            started = perf_counter()
            with mcp_span("mcp.health_probe", {"mcp.server": name}) as span:
                try:
                    result = asyncio.run(client.probe(name))
                    health = self.record_probe(
                        name,
                        ok=True,
                        latency_ms=(perf_counter() - started) * 1000,
                        result=result,
                    )
                except Exception as exc:  # noqa: BLE001 - persist probe failure.
                    mark_span_error(span, exc)
                    health = self.record_probe(
                        name,
                        ok=False,
                        latency_ms=(perf_counter() - started) * 1000,
                        error=exc,
                    )
            probed.append(health)
        return probed

    def snapshot(self, *, window_minutes: int | None = None) -> dict[str, Any]:
        window = max(1, window_minutes or settings.mcp_observability_window_minutes)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=window)
        executions = list(
            self.db.execute(
                select(MCPToolExecution)
                .where(MCPToolExecution.created_at >= cutoff)
                .order_by(MCPToolExecution.created_at.desc())
            )
            .scalars()
            .all()
        )
        approvals = list(
            self.db.execute(
                select(MCPToolApproval).where(MCPToolApproval.requested_at >= cutoff)
            )
            .scalars()
            .all()
        )
        servers = self.list_servers()
        status_counts: dict[str, int] = defaultdict(int)
        server_groups: dict[str, list[MCPToolExecution]] = defaultdict(list)
        tool_groups: dict[str, list[MCPToolExecution]] = defaultdict(list)
        latencies: list[float] = []
        for execution in executions:
            status_counts[execution.status] += 1
            server_groups[execution.server_name].append(execution)
            tool_groups[execution.qualified_name].append(execution)
            latency = execution_latency_ms(execution)
            if latency is not None:
                latencies.append(latency)

        per_server = []
        for server_name, items in sorted(server_groups.items()):
            item_latencies = [
                latency
                for item in items
                if (latency := execution_latency_ms(item)) is not None
            ]
            failed = sum(item.status in {"failed", "unknown"} for item in items)
            per_server.append(
                {
                    "server_name": server_name,
                    "calls": len(items),
                    "succeeded": sum(item.status == "succeeded" for item in items),
                    "failed": sum(item.status == "failed" for item in items),
                    "unknown": sum(item.status == "unknown" for item in items),
                    "error_rate": round(failed / len(items), 4) if items else 0.0,
                    "latency_ms": latency_summary(item_latencies),
                }
            )

        alerts = self._alerts(now, executions, servers, per_server)
        per_tool = []
        for qualified_name, items in sorted(tool_groups.items()):
            item_latencies = [
                latency
                for item in items
                if (latency := execution_latency_ms(item)) is not None
            ]
            per_tool.append(
                {
                    "qualified_name": qualified_name,
                    "calls": len(items),
                    "succeeded": sum(item.status == "succeeded" for item in items),
                    "failed": sum(item.status == "failed" for item in items),
                    "unknown": sum(item.status == "unknown" for item in items),
                    "latency_ms": latency_summary(item_latencies),
                }
            )
        return {
            "generated_at": now.isoformat(),
            "window_minutes": window,
            "summary": {
                "executions": len(executions),
                "succeeded": status_counts["succeeded"],
                "failed": status_counts["failed"],
                "unknown": status_counts["unknown"],
                "executing": status_counts["executing"],
                "deduplication_hits": sum(item.deduplication_hits for item in executions),
                "recovery_count": sum(item.recovery_count for item in executions),
                "pending_approvals": sum(item.status == "pending" for item in approvals),
                "open_circuits": sum(item.circuit_state == "open" for item in servers),
                "unhealthy_servers": sum(
                    server_operational_status(item, now) == "unhealthy" for item in servers
                ),
                "requests_per_minute": round(len(executions) / window, 4),
            },
            "latency_ms": latency_summary(latencies),
            "servers": [self.public_server(item, now=now) for item in servers],
            "per_server": per_server,
            "per_tool": per_tool,
            "alerts": alerts,
            "recent_executions": [execution_public(item) for item in executions[:50]],
        }

    def prometheus(self, *, window_minutes: int | None = None) -> str:
        snapshot = self.snapshot(window_minutes=window_minutes)
        summary = snapshot["summary"]
        lines = [
            "# HELP codemate_mcp_executions MCP executions in the selected window.",
            "# TYPE codemate_mcp_executions gauge",
        ]
        for status in ("succeeded", "failed", "unknown", "executing"):
            lines.append(
                f'codemate_mcp_executions{{status="{status}"}} {summary[status]}'
            )
        lines.extend(
            [
                "# HELP codemate_mcp_execution_latency_ms MCP execution latency percentiles.",
                "# TYPE codemate_mcp_execution_latency_ms gauge",
                f'codemate_mcp_execution_latency_ms{{quantile="0.50"}} '
                f'{snapshot["latency_ms"]["p50"]}',
                f'codemate_mcp_execution_latency_ms{{quantile="0.95"}} '
                f'{snapshot["latency_ms"]["p95"]}',
                f'codemate_mcp_execution_latency_ms{{quantile="0.99"}} '
                f'{snapshot["latency_ms"]["p99"]}',
                "# HELP codemate_mcp_circuit_state Circuit state (1 for current state).",
                "# TYPE codemate_mcp_circuit_state gauge",
                "# HELP codemate_mcp_requests_per_minute MCP execution request rate.",
                "# TYPE codemate_mcp_requests_per_minute gauge",
                f'codemate_mcp_requests_per_minute {summary["requests_per_minute"]}',
            ]
        )
        for server in snapshot["servers"]:
            name = prometheus_label(server["server_name"])
            for state in ("closed", "open", "half_open"):
                value = 1 if server["circuit_state"] == state else 0
                lines.append(
                    f'codemate_mcp_circuit_state{{server="{name}",state="{state}"}} {value}'
                )
            lines.append(
                f'codemate_mcp_circuit_rejections_total{{server="{name}"}} '
                f'{server["circuit_rejections"]}'
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def public_server(
        health: MCPServerHealth,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        reference = now or datetime.now(timezone.utc)
        return {
            "server_name": health.server_name,
            "public_url": health.public_url,
            "operational_status": server_operational_status(health, reference),
            "circuit_state": health.circuit_state,
            "manual_open": health.manual_open,
            "consecutive_failures": health.consecutive_failures,
            "total_requests": health.total_requests,
            "total_transport_successes": health.total_transport_successes,
            "total_transport_failures": health.total_transport_failures,
            "circuit_rejections": health.circuit_rejections,
            "circuit_open_count": health.circuit_open_count,
            "total_probes": health.total_probes,
            "failed_probes": health.failed_probes,
            "last_probe_status": health.last_probe_status,
            "last_probe_at": iso(health.last_probe_at),
            "last_success_at": iso(health.last_success_at),
            "last_failure_at": iso(health.last_failure_at),
            "last_latency_ms": health.last_latency_ms,
            "last_error": health.last_error,
            "protocol_version": health.protocol_version,
            "server_info": health.server_info_json,
            "opened_at": iso(health.opened_at),
            "cooldown_until": iso(health.cooldown_until),
            "version": health.version,
            "updated_at": iso(health.updated_at),
        }

    def _alerts(
        self,
        now: datetime,
        executions: list[MCPToolExecution],
        servers: list[MCPServerHealth],
        per_server: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        unknown_cutoff = now - timedelta(seconds=max(1, settings.mcp_alert_unknown_age_seconds))
        for execution in executions:
            if execution.status == "unknown" and execution.updated_at <= unknown_cutoff:
                alerts.append(
                    {
                        "severity": "critical",
                        "type": "unknown_execution_stale",
                        "server_name": execution.server_name,
                        "execution_id": execution.id,
                        "message": "MCP execution requires reconciliation",
                    }
                )
        for health in servers:
            if health.circuit_state == "open":
                alerts.append(
                    {
                        "severity": "critical" if health.manual_open else "warning",
                        "type": "circuit_open",
                        "server_name": health.server_name,
                        "message": "MCP server circuit is open",
                    }
                )
            if server_operational_status(health, now) == "unhealthy":
                alerts.append(
                    {
                        "severity": "warning",
                        "type": "server_unhealthy",
                        "server_name": health.server_name,
                        "message": health.last_error or "MCP server health probe is stale",
                    }
                )
        for item in per_server:
            if (
                item["calls"] >= max(1, settings.mcp_alert_minimum_calls)
                and item["error_rate"] >= settings.mcp_alert_error_rate_threshold
            ):
                alerts.append(
                    {
                        "severity": "warning",
                        "type": "high_error_rate",
                        "server_name": item["server_name"],
                        "message": f'MCP error rate is {item["error_rate"]:.0%}',
                    }
                )
        return alerts

    def _locked_or_create(self, server_name: str) -> MCPServerHealth:
        health = self.db.execute(
            select(MCPServerHealth)
            .where(MCPServerHealth.server_name == server_name)
            .with_for_update()
        ).scalar_one_or_none()
        if health is None:
            health = MCPServerHealth(server_name=server_name)
            self.db.add(health)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                health = self.db.execute(
                    select(MCPServerHealth)
                    .where(MCPServerHealth.server_name == server_name)
                    .with_for_update()
                ).scalar_one()
        return health

    def _locked_existing(self, server_name: str) -> MCPServerHealth:
        health = self.db.execute(
            select(MCPServerHealth)
            .where(MCPServerHealth.server_name == server_name)
            .with_for_update()
        ).scalar_one_or_none()
        if health is None:
            raise MCPServerNotFoundError("MCP server health record not found")
        return health

    @staticmethod
    def _close_circuit(health: MCPServerHealth) -> None:
        health.circuit_state = "closed"
        health.consecutive_failures = 0
        health.opened_at = None
        health.cooldown_until = None
        health.half_open_trial_id = None
        health.half_open_lease_expires_at = None

    @staticmethod
    def _open_circuit(
        health: MCPServerHealth,
        now: datetime,
        *,
        manual: bool = False,
    ) -> None:
        if health.circuit_state != "open":
            health.circuit_open_count += 1
        health.circuit_state = "open"
        health.manual_open = manual
        health.opened_at = now
        health.cooldown_until = (
            None
            if manual
            else now + timedelta(seconds=max(1, settings.mcp_circuit_cooldown_seconds))
        )
        health.half_open_trial_id = None
        health.half_open_lease_expires_at = None

    def _record_failure(
        self,
        health: MCPServerHealth,
        error: Exception | str,
        latency_ms: float,
        now: datetime,
    ) -> None:
        health.consecutive_failures += 1
        health.last_failure_at = now
        health.last_latency_ms = round(latency_ms, 2)
        health.last_error = str(error)[:4000]
        should_open = (
            health.circuit_state == "half_open"
            or health.consecutive_failures >= max(1, settings.mcp_circuit_failure_threshold)
        )
        if settings.mcp_circuit_breaker_enabled and should_open and not health.manual_open:
            self._open_circuit(health, now)


def server_operational_status(health: MCPServerHealth, now: datetime) -> str:
    if health.circuit_state == "open":
        return "unhealthy"
    if health.last_probe_status == "unhealthy":
        return "unhealthy"
    if health.last_probe_at is None:
        return "unknown"
    stale_after = timedelta(seconds=max(1, settings.mcp_health_stale_seconds))
    if now - health.last_probe_at > stale_after:
        return "unhealthy"
    return "healthy"


def execution_latency_ms(execution: MCPToolExecution) -> float | None:
    if not execution.started_at or not execution.finished_at:
        return None
    return max(0.0, (execution.finished_at - execution.started_at).total_seconds() * 1000)


def latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 2)


def execution_public(execution: MCPToolExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "run_id": execution.run_id,
        "approval_id": execution.approval_id,
        "qualified_name": execution.qualified_name,
        "server_name": execution.server_name,
        "tool_name": execution.tool_name,
        "arguments": redact_sensitive(execution.arguments_json),
        "status": execution.status,
        "attempt_count": execution.attempt_count,
        "recovery_count": execution.recovery_count,
        "deduplication_hits": execution.deduplication_hits,
        "retry_safe": execution.retry_safe,
        "error_message": execution.error_message,
        "created_at": iso(execution.created_at),
        "started_at": iso(execution.started_at),
        "finished_at": iso(execution.finished_at),
        "updated_at": iso(execution.updated_at),
        "latency_ms": execution_latency_ms(execution),
    }


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
