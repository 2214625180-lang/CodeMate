from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    evaluations,
    github_app,
    health,
    mcp_approvals,
    mcp_client,
    mcp_executions,
    mcp_operations,
    mcp_quotas,
    mcp_registry,
    mcp_tenancy,
    repos,
    runs,
    security_audit,
)
from app.core.audit import evaluation_audit_middleware
from app.core.config import settings
from app.core.database import init_db
from app.core.telemetry import configure_telemetry
from app.mcp.auth import MCPBearerAuthMiddleware
from app.mcp.client import MCPClientService
from app.mcp.server import create_mcp_server

codemate_mcp = create_mcp_server()
codemate_mcp_http_app = MCPBearerAuthMiddleware(
    codemate_mcp.streamable_http_app(),
    token_provider=lambda: settings.mcp_auth_token,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_security_config()
    if settings.mcp_client_enabled:
        MCPClientService()
    init_db()
    configure_telemetry()
    if settings.mcp_client_enabled and settings.mcp_health_monitor_enabled:
        try:
            from app.core.queue import enqueue_mcp_health_probe

            enqueue_mcp_health_probe(delay_seconds=1, recurring=True)
        except Exception:  # noqa: BLE001 - dashboard can still trigger probes manually.
            pass
    if settings.mcp_quota_enabled:
        try:
            from app.core.queue import enqueue_mcp_quota_reconciliation

            enqueue_mcp_quota_reconciliation(delay_seconds=5, recurring=True)
        except Exception:  # noqa: BLE001 - API reconciliation remains available.
            pass
    if settings.security_audit_sink_set:
        try:
            from app.core.queue import enqueue_security_audit_delivery

            enqueue_security_audit_delivery(delay_seconds=2, recurring=True)
        except Exception:  # noqa: BLE001 - durable outbox can be drained manually.
            pass
    if settings.mcp_compliance_enabled:
        try:
            from app.core.queue import enqueue_mcp_compliance_scan

            enqueue_mcp_compliance_scan(delay_seconds=1, recurring=True)
        except Exception:  # noqa: BLE001 - readiness stays failed until scheduling recovers.
            pass
    if settings.mcp_enabled:
        async with codemate_mcp.session_manager.run():
            yield
        return
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="CodeMate API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    app.middleware("http")(evaluation_audit_middleware)

    app.include_router(health.router)
    app.include_router(repos.router)
    app.include_router(runs.router)
    app.include_router(evaluations.router)
    app.include_router(github_app.router)
    app.include_router(mcp_client.router)
    app.include_router(mcp_approvals.router)
    app.include_router(mcp_executions.router)
    app.include_router(mcp_operations.router)
    app.include_router(mcp_quotas.router)
    app.include_router(mcp_registry.router)
    app.include_router(mcp_tenancy.router)
    app.include_router(security_audit.router)

    if settings.mcp_enabled:
        app.mount("/mcp", codemate_mcp_http_app, name="mcp")

    return app


app = create_app()
