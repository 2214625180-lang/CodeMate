from datetime import datetime
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import (
    EvaluationPrincipal,
    require_evaluation_admin,
    require_evaluation_viewer,
)
from app.core.database import get_db
from app.models.mcp_access_grant import MCPAccessGrant
from app.models.mcp_delegated_identity import MCPDelegatedIdentity, MCPDelegatedOAuthProvider
from app.models.mcp_tenant import MCPTenant
from app.models.mcp_tenant_membership import MCPTenantMembership
from app.models.mcp_tenant_server_binding import MCPTenantServerBinding
from app.models.repository import Repository
from app.schemas.mcp_tenancy import (
    MCPAccessGrantCreate,
    MCPDelegatedProviderWrite,
    MCPMembershipCreate,
    MCPServerBindingCreate,
    MCPTenantCreate,
)
from app.services.mcp_tenancy_service import (
    MCPDelegatedIdentityError,
    MCPDelegatedIdentityService,
)
from app.services.mcp_registry_service import MCPRegistryConflictError

router = APIRouter(prefix="/mcp-tenancy", tags=["mcp-tenancy"])
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]
ViewerPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_viewer)]


@router.get("/tenants")
def list_tenants(_principal: AdminPrincipal, db: Session = Depends(get_db)):
    return [tenant_dict(item) for item in db.scalars(select(MCPTenant).order_by(MCPTenant.slug))]


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: MCPTenantCreate,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    tenant = MCPTenant(slug=payload.slug, name=payload.name)
    db.add(tenant)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tenant slug exists") from exc
    db.refresh(tenant)
    return tenant_dict(tenant)


@router.post("/tenants/{tenant_id}/client-token")
def rotate_tenant_client_token(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    tenant = require_tenant(db, tenant_id)
    token = secrets.token_urlsafe(32)
    from app.services.mcp_tenancy_service import sha256

    tenant.client_token_hash = sha256(token)
    db.add(tenant)
    db.commit()
    return {"tenant_id": tenant.id, "client_token": token}


@router.post("/tenants/{tenant_id}/memberships", status_code=status.HTTP_201_CREATED)
def create_membership(
    tenant_id: str,
    payload: MCPMembershipCreate,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    item = MCPTenantMembership(tenant_id=tenant_id, **payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tenant membership exists") from exc
    db.refresh(item)
    return membership_dict(item)


@router.get("/tenants/{tenant_id}/memberships")
def list_memberships(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return [
        membership_dict(item)
        for item in db.scalars(
            select(MCPTenantMembership).where(MCPTenantMembership.tenant_id == tenant_id)
        )
    ]


@router.post("/tenants/{tenant_id}/bindings", status_code=status.HTTP_201_CREATED)
def bind_server(
    tenant_id: str,
    payload: MCPServerBindingCreate,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    item = db.scalar(
        select(MCPTenantServerBinding).where(
            MCPTenantServerBinding.tenant_id == tenant_id,
            MCPTenantServerBinding.server_name == payload.server_name,
        )
    ) or MCPTenantServerBinding(tenant_id=tenant_id, server_name=payload.server_name)
    item.enabled = payload.enabled
    db.add(item)
    db.commit()
    db.refresh(item)
    return binding_dict(item)


@router.get("/tenants/{tenant_id}/bindings")
def list_bindings(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return [
        binding_dict(item)
        for item in db.scalars(
            select(MCPTenantServerBinding).where(MCPTenantServerBinding.tenant_id == tenant_id)
        )
    ]


@router.post("/tenants/{tenant_id}/grants", status_code=status.HTTP_201_CREATED)
def create_grant(
    tenant_id: str,
    payload: MCPAccessGrantCreate,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    try:
        expires_at = datetime.fromisoformat(payload.expires_at) if payload.expires_at else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="expires_at must be ISO-8601") from exc
    if payload.repo_id:
        repository = db.get(Repository, payload.repo_id)
        if repository is None or repository.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="Repository does not belong to tenant")
    item = MCPAccessGrant(
        tenant_id=tenant_id,
        repo_id=payload.repo_id,
        principal_type=payload.principal_type,
        principal_id=payload.principal_id,
        server_name=payload.server_name,
        tool_name=payload.tool_name,
        permissions_json=payload.permissions,
        effect=payload.effect,
        expires_at=expires_at,
        created_by=principal.login,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return grant_dict(item)


@router.put("/tenants/{tenant_id}/repositories/{repo_id}")
def assign_repository(
    tenant_id: str,
    repo_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    repository = db.get(Repository, repo_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    repository.tenant_id = tenant_id
    db.add(repository)
    db.commit()
    return {"repo_id": repository.id, "tenant_id": tenant_id}


@router.get("/tenants/{tenant_id}/grants")
def list_grants(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return [
        grant_dict(item)
        for item in db.scalars(
            select(MCPAccessGrant).where(MCPAccessGrant.tenant_id == tenant_id)
        )
    ]


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grant(grant_id: str, _principal: AdminPrincipal, db: Session = Depends(get_db)):
    item = db.get(MCPAccessGrant, grant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    db.delete(item)
    db.commit()


@router.post("/tenants/{tenant_id}/oauth/providers")
def configure_delegated_provider(
    tenant_id: str,
    payload: MCPDelegatedProviderWrite,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    try:
        provider = MCPDelegatedIdentityService(db).configure_provider(
            tenant_id=tenant_id,
            **payload.model_dump(),
        )
        return MCPDelegatedIdentityService.provider_public(provider)
    except (MCPDelegatedIdentityError, MCPRegistryConflictError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tenants/{tenant_id}/oauth/providers")
def list_delegated_providers(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return [
        MCPDelegatedIdentityService.provider_public(item)
        for item in db.scalars(
            select(MCPDelegatedOAuthProvider).where(
                MCPDelegatedOAuthProvider.tenant_id == tenant_id
            )
        )
    ]


@router.post("/oauth/providers/{provider_id}/authorize")
def start_delegated_authorization(
    provider_id: str,
    principal: ViewerPrincipal,
    db: Session = Depends(get_db),
):
    try:
        provider = db.get(MCPDelegatedOAuthProvider, provider_id)
        if provider is None:
            raise MCPDelegatedIdentityError("Delegated OAuth provider not found")
        membership = db.scalar(
            select(MCPTenantMembership).where(
                MCPTenantMembership.tenant_id == provider.tenant_id,
                MCPTenantMembership.provider == principal.provider,
                MCPTenantMembership.subject == principal.login,
            )
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Tenant membership is required")
        return MCPDelegatedIdentityService(db).start_authorization(
            provider_id,
            subject_provider=principal.provider,
            subject=principal.login,
        )
    except MCPDelegatedIdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/oauth/callback")
def delegated_oauth_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    db: Session = Depends(get_db),
):
    try:
        return MCPDelegatedIdentityService(db).complete_authorization(code=code, state=state)
    except MCPDelegatedIdentityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tenants/{tenant_id}/identities")
def list_delegated_identities(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return [
        MCPDelegatedIdentityService.public_dict(item)
        for item in db.scalars(
            select(MCPDelegatedIdentity).where(MCPDelegatedIdentity.tenant_id == tenant_id)
        )
    ]


@router.post("/identities/{identity_id}/revoke")
def revoke_delegated_identity(
    identity_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    try:
        return MCPDelegatedIdentityService.public_dict(
            MCPDelegatedIdentityService(db).revoke(identity_id)
        )
    except MCPDelegatedIdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def require_tenant(db: Session, tenant_id: str) -> MCPTenant:
    tenant = db.get(MCPTenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def tenant_dict(item: MCPTenant):
    return {
        "id": item.id,
        "slug": item.slug,
        "name": item.name,
        "has_client_token": bool(item.client_token_hash),
    }


def membership_dict(item: MCPTenantMembership):
    return {"id": item.id, "provider": item.provider, "subject": item.subject, "role": item.role}


def binding_dict(item: MCPTenantServerBinding):
    return {"id": item.id, "server_name": item.server_name, "enabled": item.enabled}


def grant_dict(item: MCPAccessGrant):
    return {
        "id": item.id,
        "repo_id": item.repo_id,
        "principal_type": item.principal_type,
        "principal_id": item.principal_id,
        "server_name": item.server_name,
        "tool_name": item.tool_name,
        "permissions": item.permissions_json,
        "effect": item.effect,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
    }
