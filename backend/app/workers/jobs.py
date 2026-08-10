import logging

from app.core.database import SessionLocal
from app.services.agent_service import AgentService
from app.services.evaluation_service import EvaluationService
from app.services.index_service import IndexService
from app.services.agent_step_service import AgentStepService
from app.services.mcp_approval_service import MCPApprovalService
from app.services.mcp_execution_service import MCPExecutionService
from app.services.mcp_operations_service import MCPOperationsService
from app.services.mcp_quota_service import MCPQuotaService
from app.services.security_audit_delivery_service import deliver_security_audit_batch
from app.models.mcp_tenant import MCPTenant
from sqlalchemy import select
from app.mcp.client import MCPClientService
from app.core.config import settings


logger = logging.getLogger(__name__)


def index_repository_job(repo_id: str, full: bool = False) -> None:
    db = SessionLocal()
    try:
        IndexService(db).index_repository(repo_id, full=full)
    finally:
        db.close()


def run_agent_job(run_id: str) -> None:
    """Provide one per-job, session-scoped adapter from RQ into AgentService.

    Retry and resume semantics belong to the durable run/checkpoint layer, so an
    RQ retry creates a fresh SQLAlchemy session instead of reusing failed process
    state from the previous attempt. The lower layers commit multiple lifecycle
    transitions; one Agent run is intentionally not a single database transaction.
    """
    db = SessionLocal()
    try:
        AgentService(db).run_fix(run_id)
        from app.services.github_app_repair_service import GitHubAppRepairService

        GitHubAppRepairService(db).sync_agent_result(run_id)
    finally:
        db.close()


def resume_agent_approval_job(approval_id: str) -> None:
    db = SessionLocal()
    try:
        AgentService(db).resume_from_approval(approval_id)
    finally:
        db.close()


def resume_agent_execution_job(execution_id: str) -> None:
    db = SessionLocal()
    try:
        AgentService(db).resume_from_execution(execution_id)
    finally:
        db.close()


def recover_mcp_execution_job(execution_id: str) -> None:
    db = SessionLocal()
    try:
        service = MCPExecutionService(db)
        execution = service.recover_stale(execution_id)
        if execution is None:
            return
        AgentStepService(db).record(
            run_id=execution.run_id,
            step_type="mcp_execution",
            tool_name=execution.qualified_name,
            input_json={"event": "lease_expired", "execution_id": execution.id},
            output_json={"execution": service.public_dict(execution)},
        )
        if execution.status == "prepared":
            approval = service.prepare_resume_target(execution)
            if approval is not None:
                AgentService(db).resume_from_approval(approval.id)
            else:
                AgentService(db).resume_from_execution(execution.id)
    finally:
        db.close()


def probe_mcp_servers_job(
    server_name: str | None = None,
    recurring: bool = False,
) -> None:
    db = SessionLocal()
    try:
        if settings.mcp_registry_enabled:
            from app.services.mcp_registry_service import MCPRegistryService

            client = MCPRegistryService(db).client()
        else:
            client = MCPClientService()
        MCPOperationsService(db).probe_servers(client, server_name)
    finally:
        db.close()
        if recurring and settings.mcp_health_monitor_enabled:
            try:
                from app.core.queue import enqueue_mcp_health_probe

                enqueue_mcp_health_probe(
                    delay_seconds=max(5, settings.mcp_health_probe_interval_seconds),
                    recurring=True,
                )
            except Exception:  # noqa: BLE001 - next API startup can restore scheduling.
                pass


def expire_mcp_approval_job(approval_id: str) -> None:
    db = SessionLocal()
    try:
        approval = MCPApprovalService(db).expire(approval_id)
        if approval is not None:
            AgentStepService(db).record(
                run_id=approval.run_id,
                step_type="approval_decision",
                tool_name=approval.qualified_name,
                input_json={
                    "approval_id": approval.id,
                    "decision": approval.decision,
                    "version": approval.version,
                },
                output_json={
                    "approval": MCPApprovalService.public_dict(approval),
                },
            )
            AgentService(db).resume_from_approval(approval.id)
    finally:
        db.close()


def reconcile_mcp_quotas_job(recurring: bool = False) -> None:
    db = SessionLocal()
    try:
        service = MCPQuotaService(db)
        tenant_ids = list(db.scalars(select(MCPTenant.id)))
        for tenant_id in tenant_ids:
            try:
                service.reconcile_redis(tenant_id, repair=True)
                service.purge_usage(
                    tenant_id,
                    retention_days=settings.mcp_quota_retention_days,
                    dry_run=False,
                )
            except Exception:  # noqa: BLE001 - isolate tenant maintenance failures.
                db.rollback()
                logger.exception("MCP quota maintenance failed for tenant %s", tenant_id)
    finally:
        db.close()
        if recurring and settings.mcp_quota_enabled:
            try:
                from app.core.queue import enqueue_mcp_quota_reconciliation

                enqueue_mcp_quota_reconciliation(
                    delay_seconds=max(
                        30, settings.mcp_quota_reconciliation_interval_seconds
                    ),
                    recurring=True,
                )
            except Exception:  # noqa: BLE001 - startup can restore the schedule.
                pass


def deliver_security_audit_job(recurring: bool = False) -> None:
    try:
        deliver_security_audit_batch()
    except Exception:  # noqa: BLE001 - outbox leases make the next run safe.
        logger.exception("Security audit delivery batch failed")
    finally:
        if recurring and settings.security_audit_sink_set:
            try:
                from app.core.queue import enqueue_security_audit_delivery

                enqueue_security_audit_delivery(
                    delay_seconds=max(5, settings.security_audit_delivery_interval_seconds),
                    recurring=True,
                )
            except Exception:  # noqa: BLE001 - startup can restore the schedule.
                logger.exception("Failed to reschedule security audit delivery")


def purge_agent_timeline_payloads_job(recurring: bool = False) -> None:
    db = SessionLocal()
    try:
        AgentStepService(db).purge_expired_payloads()
    finally:
        db.close()
        if recurring:
            try:
                from app.core.queue import enqueue_agent_timeline_payload_cleanup

                enqueue_agent_timeline_payload_cleanup(
                    delay_seconds=max(300, settings.agent_timeline_cleanup_interval_seconds),
                    recurring=True,
                )
            except Exception:  # noqa: BLE001 - startup can restore the schedule.
                logger.exception("Failed to reschedule agent Timeline payload cleanup")


def scan_mcp_compliance_job(recurring: bool = False) -> None:
    try:
        from app.services.mcp_compliance_service import scan_and_persist

        report = scan_and_persist(include_runtime=True)
        if report["status"] != "compliant":
            logger.error("MCP continuous compliance scan failed: %s", report["report_sha256"])
    finally:
        if recurring and settings.mcp_compliance_enabled:
            try:
                from app.core.queue import enqueue_mcp_compliance_scan

                enqueue_mcp_compliance_scan(
                    delay_seconds=max(60, settings.mcp_compliance_interval_seconds),
                    recurring=True,
                )
            except Exception:  # noqa: BLE001 - startup can restore the schedule.
                logger.exception("Failed to reschedule MCP compliance scan")


def evaluation_run_job(evaluation_run_id: str) -> None:
    db = SessionLocal()
    try:
        service = EvaluationService(db)
        try:
            service.execute_run(evaluation_run_id)
        except Exception as exc:  # noqa: BLE001 - keep failed eval visible in UI.
            service.fail_run(evaluation_run_id, str(exc))
            raise
    finally:
        db.close()
