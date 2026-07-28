from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.migrations import current_and_head
from app.core.queue import get_redis_connection
from app.core.worker_health import active_worker_count
from app.services.security_audit_delivery_service import SecurityAuditDeliveryService
from app.services.mcp_compliance_service import compliance_readiness

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/readiness")
def readiness_check():
    checks: dict[str, dict] = {}
    ready = True
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
        current, head = current_and_head()
        migration_ok = current == head
        checks["migration"] = {"status": "ok" if migration_ok else "failed", "current": current, "head": head}
        ready = ready and migration_ok
        if settings.security_audit_sink_set:
            audit = SecurityAuditDeliveryService(db).status()
            dead_letters = audit["counts"].get("dead_letter", 0)
            stale_threshold = max(60, settings.security_audit_delivery_interval_seconds * 10)
            audit_ok = dead_letters == 0 and audit["oldest_undelivered_seconds"] <= stale_threshold
            checks["security_audit"] = {
                "status": "ok" if audit_ok else "failed",
                **audit,
            }
            ready = ready and audit_ok
        else:
            checks["security_audit"] = {"status": "disabled"}
    except Exception as exc:  # noqa: BLE001 - readiness reports dependency failures.
        db.rollback()
        checks["database"] = {"status": "failed", "detail": str(exc)[:500]}
        ready = False
    finally:
        db.close()
    try:
        redis = get_redis_connection()
        checks["redis"] = {"status": "ok" if redis.ping() else "failed"}
        ready = ready and checks["redis"]["status"] == "ok"
        if settings.rq_worker_readiness_required:
            worker_count = active_worker_count(redis, settings.rq_worker_heartbeat_prefix)
            worker_ok = worker_count > 0
            checks["rq_workers"] = {
                "status": "ok" if worker_ok else "failed",
                "active": worker_count,
            }
            ready = ready and worker_ok
        else:
            checks["rq_workers"] = {"status": "disabled"}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"status": "failed", "detail": str(exc)[:500]}
        if settings.rq_worker_readiness_required:
            checks["rq_workers"] = {"status": "failed", "detail": "Redis unavailable"}
        ready = False
    checks["kms"] = {
        "status": "configured",
        "provider": settings.mcp_registry_kms_provider,
        "key_id_configured": bool(settings.mcp_registry_kms_key_id),
    }
    if settings.mcp_compliance_enabled:
        checks["mcp_compliance"] = compliance_readiness()
        ready = ready and checks["mcp_compliance"]["status"] == "ok"
    else:
        checks["mcp_compliance"] = {"status": "disabled"}
    payload = {"status": "ready" if ready else "not_ready", "checks": checks}
    return JSONResponse(payload, status_code=200 if ready else 503)
