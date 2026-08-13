from datetime import timedelta
import time

from redis import Redis
from rq import Queue, Retry

from app.core.config import settings
from app.workers.jobs import (
    evaluation_run_job,
    deliver_security_audit_job,
    expire_mcp_approval_job,
    recover_mcp_execution_job,
    index_repository_job,
    purge_agent_timeline_payloads_job,
    probe_mcp_servers_job,
    scan_mcp_compliance_job,
    reconcile_mcp_quotas_job,
    resume_agent_approval_job,
    resume_agent_execution_job,
    run_agent_job,
)


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.redis_url)


def get_index_queue() -> Queue:
    return Queue(settings.rq_queue_name, connection=get_redis_connection())


def enqueue_repository_index(repo_id: str, *, full: bool = False) -> str:
    job = get_index_queue().enqueue(index_repository_job, repo_id, full, job_timeout=600)
    return job.id


def enqueue_agent_run(run_id: str) -> str:
    job = get_index_queue().enqueue(
        run_agent_job,
        run_id,
        job_timeout=900,
        retry=Retry(max=3, interval=[5, 30, 120]),
    )
    return job.id


def enqueue_agent_approval_resume(approval_id: str, *, version: int) -> str:
    job = get_index_queue().enqueue(
        resume_agent_approval_job,
        approval_id,
        job_timeout=900,
        job_id=f"mcp-approval-resume-{approval_id}-v{version}",
    )
    return job.id


def enqueue_approval_expiration(approval_id: str, *, delay_seconds: int) -> str:
    job = get_index_queue().enqueue_in(
        timedelta(seconds=max(1, delay_seconds)),
        expire_mcp_approval_job,
        approval_id,
        job_timeout=900,
        job_id=f"mcp-approval-expire-{approval_id}",
    )
    return job.id


def enqueue_agent_execution_resume(execution_id: str, *, version: int) -> str:
    job = get_index_queue().enqueue(
        resume_agent_execution_job,
        execution_id,
        job_timeout=900,
        job_id=f"mcp-execution-resume-{execution_id}-v{version}",
    )
    return job.id


def enqueue_mcp_execution_watchdog(
    execution_id: str,
    *,
    version: int,
    delay_seconds: int,
) -> str:
    job = get_index_queue().enqueue_in(
        timedelta(seconds=max(1, delay_seconds)),
        recover_mcp_execution_job,
        execution_id,
        job_timeout=900,
        job_id=f"mcp-execution-watchdog-{execution_id}-v{version}",
    )
    return job.id


def enqueue_mcp_health_probe(
    *,
    server_name: str | None = None,
    delay_seconds: int = 0,
    recurring: bool = False,
) -> str:
    queue = get_index_queue()
    job_kwargs = {"job_timeout": 300}
    if recurring:
        interval = max(5, settings.mcp_health_probe_interval_seconds)
        target_time = time.time() + max(0, delay_seconds)
        job_kwargs["job_id"] = f"mcp-health-monitor-{int(target_time // interval)}"
    if delay_seconds > 0:
        job = queue.enqueue_in(
            timedelta(seconds=delay_seconds),
            probe_mcp_servers_job,
            server_name,
            recurring,
            **job_kwargs,
        )
    else:
        job = queue.enqueue(
            probe_mcp_servers_job,
            server_name,
            recurring,
            **job_kwargs,
        )
    return job.id


def enqueue_mcp_quota_reconciliation(
    *,
    delay_seconds: int = 0,
    recurring: bool = False,
) -> str:
    queue = get_index_queue()
    job_kwargs = {"job_timeout": 600}
    if recurring:
        interval = max(30, settings.mcp_quota_reconciliation_interval_seconds)
        target_time = time.time() + max(0, delay_seconds)
        job_kwargs["job_id"] = f"mcp-quota-reconcile-{int(target_time // interval)}"
    if delay_seconds > 0:
        job = queue.enqueue_in(
            timedelta(seconds=delay_seconds),
            reconcile_mcp_quotas_job,
            recurring,
            **job_kwargs,
        )
    else:
        job = queue.enqueue(reconcile_mcp_quotas_job, recurring, **job_kwargs)
    return job.id


def enqueue_security_audit_delivery(
    *,
    delay_seconds: int = 0,
    recurring: bool = False,
) -> str:
    queue = get_index_queue()
    job_kwargs = {"job_timeout": 300}
    if recurring:
        interval = max(5, settings.security_audit_delivery_interval_seconds)
        target_time = time.time() + max(0, delay_seconds)
        job_kwargs["job_id"] = f"security-audit-delivery-{int(target_time // interval)}"
    if delay_seconds > 0:
        job = queue.enqueue_in(
            timedelta(seconds=delay_seconds),
            deliver_security_audit_job,
            recurring,
            **job_kwargs,
        )
    else:
        job = queue.enqueue(
            deliver_security_audit_job,
            recurring,
            **job_kwargs,
        )
    return job.id


def enqueue_agent_timeline_payload_cleanup(
    *,
    delay_seconds: int = 0,
    recurring: bool = False,
) -> str:
    queue = get_index_queue()
    job_kwargs = {"job_timeout": 300}
    if recurring:
        interval = max(300, settings.agent_timeline_cleanup_interval_seconds)
        target_time = time.time() + max(0, delay_seconds)
        job_kwargs["job_id"] = f"agent-timeline-purge-{int(target_time // interval)}"
    if delay_seconds > 0:
        job = queue.enqueue_in(
            timedelta(seconds=delay_seconds),
            purge_agent_timeline_payloads_job,
            recurring,
            **job_kwargs,
        )
    else:
        job = queue.enqueue(purge_agent_timeline_payloads_job, recurring, **job_kwargs)
    return job.id


def enqueue_mcp_compliance_scan(
    *,
    delay_seconds: int = 0,
    recurring: bool = False,
) -> str:
    queue = get_index_queue()
    job_kwargs = {"job_timeout": 120}
    if recurring:
        interval = max(60, settings.mcp_compliance_interval_seconds)
        target_time = time.time() + max(0, delay_seconds)
        job_kwargs["job_id"] = f"mcp-compliance-{int(target_time // interval)}"
    if delay_seconds > 0:
        job = queue.enqueue_in(
            timedelta(seconds=delay_seconds),
            scan_mcp_compliance_job,
            recurring,
            **job_kwargs,
        )
    else:
        job = queue.enqueue(scan_mcp_compliance_job, recurring, **job_kwargs)
    return job.id


def enqueue_evaluation_run(evaluation_run_id: str) -> str:
    job = get_index_queue().enqueue(evaluation_run_job, evaluation_run_id, job_timeout=3600)
    return job.id
