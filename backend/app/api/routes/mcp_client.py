import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings

from app.mcp.client import (
    MCPClientConfigurationError,
    MCPClientError,
    MCPClientService,
    MCPRemoteServerNotFoundError,
    MCPToolNotAllowedError,
)
from app.mcp.client_auth import require_mcp_client_token
from app.schemas.mcp_client import MCPToolCallRequest

router = APIRouter(
    prefix="/mcp-client",
    tags=["mcp-client"],
    dependencies=[Depends(require_mcp_client_token)],
)


def get_mcp_client_service(
    db: Session = Depends(get_db),
    tenant_id: Annotated[str | None, Header(alias="X-CodeMate-Tenant-ID")] = None,
    tenant_token: Annotated[str | None, Header(alias="X-CodeMate-Tenant-Token")] = None,
    repo_id: Annotated[str | None, Header(alias="X-CodeMate-Repo-ID")] = None,
) -> MCPClientService:
    try:
        quota_context = None
        config_filter = None
        if settings.mcp_tenant_authorization_enabled or settings.mcp_quota_enabled:
            from app.models.mcp_tenant import MCPTenant
            from app.models.repository import Repository

            tenant = db.get(MCPTenant, tenant_id) if tenant_id else None
            if tenant is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="A valid X-CodeMate-Tenant-ID header is required",
                )
            from app.services.mcp_tenancy_service import sha256

            if (
                not tenant.client_token_hash
                or not tenant_token
                or not secrets.compare_digest(tenant.client_token_hash, sha256(tenant_token))
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="A valid X-CodeMate-Tenant-Token header is required",
                )
            if repo_id:
                repository = db.get(Repository, repo_id)
                if repository is None or repository.tenant_id != tenant_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Repository does not belong to tenant",
                    )
            from app.services.mcp_quota_service import MCPQuotaContext

            quota_context = MCPQuotaContext(
                tenant_id=tenant_id,
                repo_id=repo_id,
                run_id=None,
                principal_type="service",
                principal_id="mcp-client",
            )
            if settings.mcp_tenant_authorization_enabled:
                from app.services.mcp_tenancy_service import (
                    MCPAuthorizationContext,
                    MCPTenancyService,
                )

                authorization_context = MCPAuthorizationContext(
                    tenant_id=tenant_id,
                    repo_id=repo_id,
                    principal_type="service",
                    principal_id="mcp-client",
                )
                tenancy = MCPTenancyService(db)

                def config_filter(configs):
                    return tenancy.filter_configs(configs, authorization_context)

        if settings.mcp_registry_enabled:
            from app.services.mcp_registry_service import MCPRegistryService

            configs = MCPRegistryService(db).effective_configs(
                config_filter=config_filter
            )
        else:
            configs = MCPClientService().servers
            if config_filter:
                configs = config_filter(configs)
        quota_hooks = {}
        if settings.mcp_quota_enabled and quota_context is not None:
            from app.services.mcp_quota_service import MCPQuotaService

            reserve, release = MCPQuotaService(db).client_hooks(quota_context)
            quota_hooks = {"quota_reserve": reserve, "quota_release": release}
        return MCPClientService(servers=configs, **quota_hooks)
    except MCPClientConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


MCPService = Annotated[MCPClientService, Depends(get_mcp_client_service)]


@router.get("/servers")
async def list_mcp_servers(service: MCPService):
    return {"servers": service.configured_servers()}


@router.get("/servers/{server_name}")
async def probe_mcp_server(server_name: str, service: MCPService):
    try:
        return await service.probe(server_name)
    except Exception as exc:  # converted to a stable HTTP contract below.
        raise_mcp_http_error(exc)


@router.get("/servers/{server_name}/tools")
async def list_mcp_tools(server_name: str, service: MCPService):
    try:
        return {"server": server_name, "tools": await service.list_tools(server_name)}
    except Exception as exc:  # converted to a stable HTTP contract below.
        raise_mcp_http_error(exc)


@router.post("/servers/{server_name}/call")
async def call_mcp_tool(
    server_name: str,
    payload: MCPToolCallRequest,
    service: MCPService,
    idempotency_key: Annotated[
        str | None, Header(alias="X-CodeMate-Idempotency-Key", max_length=255)
    ] = None,
):
    try:
        kwargs = {"idempotency_key": idempotency_key} if idempotency_key else {}
        result = await service.call_tool(
            server_name, payload.tool_name, payload.arguments, **kwargs
        )
        return {"server": server_name, "tool": payload.tool_name, "result": result}
    except Exception as exc:  # converted to a stable HTTP contract below.
        raise_mcp_http_error(exc)


def raise_mcp_http_error(exc: Exception) -> None:
    from app.services.mcp_quota_service import (
        MCPQuotaConflictError,
        MCPQuotaExceededError,
        MCPQuotaUnavailableError,
    )

    if isinstance(exc, MCPQuotaExceededError):
        headers = (
            {"Retry-After": str(exc.retry_after_seconds)}
            if exc.retry_after_seconds
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "mcp_quota_exceeded",
                "reason": exc.reason,
                "policy_id": exc.policy_id,
                "message": str(exc),
            },
            headers=headers,
        ) from exc
    if isinstance(exc, MCPQuotaUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mcp_quota_unavailable", "message": str(exc)},
        ) from exc
    if isinstance(exc, MCPQuotaConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "mcp_quota_conflict", "message": str(exc)},
        ) from exc
    if isinstance(exc, MCPRemoteServerNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, MCPToolNotAllowedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, MCPClientConfigurationError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if isinstance(exc, MCPClientError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise exc
