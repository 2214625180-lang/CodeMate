from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import EvaluationPrincipal, require_evaluation_admin
from app.core.database import get_db
from app.core.config import settings
from app.schemas.mcp_registry import (
    MCPCredentialWriteRequest,
    MCPRegistryDeleteRequest,
    MCPRegistryServerCreate,
    MCPRegistryServerUpdate,
    MCPRevisionRestoreRequest,
)
from app.services.mcp_registry_service import (
    MCPCredentialError,
    MCPRegistryConflictError,
    MCPRegistryNotFoundError,
    MCPRegistryService,
)

router = APIRouter(prefix="/mcp-registry", tags=["mcp-registry"])
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]


@router.get("/servers")
def list_registry_servers(
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    return [service.public_dict(item) for item in service.list_servers()]


@router.post("/servers", status_code=status.HTTP_201_CREATED)
def create_registry_server(
    payload: MCPRegistryServerCreate,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        server = service.create(payload.model_dump(mode="json"), actor=principal.login)
        return service.public_dict(server)
    except (MCPRegistryConflictError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/servers/{server_id}")
def get_registry_server(
    server_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        return service.public_dict(service.get(server_id))
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/servers/{server_id}")
def update_registry_server(
    server_id: str,
    payload: MCPRegistryServerUpdate,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    changes = payload.model_dump(exclude={"expected_version"}, exclude_none=True, mode="json")
    try:
        server = service.update(
            server_id,
            changes,
            expected_version=payload.expected_version,
            actor=principal.login,
        )
        return service.public_dict(server)
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (MCPRegistryConflictError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_registry_server(
    server_id: str,
    payload: MCPRegistryDeleteRequest,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    try:
        MCPRegistryService(db).delete(server_id, expected_version=payload.expected_version)
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPRegistryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/servers/{server_id}/validate")
def validate_registry_server(
    server_id: str,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        return service.public_dict(service.validate(server_id, actor=principal.login))
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/servers/{server_id}/credential")
def set_registry_credential(
    server_id: str,
    payload: MCPCredentialWriteRequest,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        server = service.get(server_id)
        credential = service.credentials.set_credential(
            server,
            auth_type=payload.auth_type,
            payload=payload.model_dump(exclude={"auth_type", "expected_version"}, mode="json"),
            expected_version=payload.expected_version,
        )
        return service.credentials.public_dict(credential)
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPRegistryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MCPCredentialError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/servers/{server_id}/credential", status_code=status.HTTP_204_NO_CONTENT)
def delete_registry_credential(
    server_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        service.credentials.delete_credential(service.get(server_id))
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/credentials/rewrap")
def rewrap_registry_credentials(
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    try:
        count = MCPRegistryService(db).credentials.rewrap_all()
        return {
            "rewrapped": count,
            "key_version": settings.mcp_registry_key_version,
            "kms_provider": settings.mcp_registry_kms_provider,
            "kms_key_id": settings.mcp_registry_kms_key_id,
        }
    except MCPCredentialError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/servers/{server_id}/revisions")
def list_registry_revisions(
    server_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        return [
            {
                "id": item.id,
                "version": item.version,
                "action": item.action,
                "snapshot": item.snapshot_json,
                "actor": item.actor,
                "created_at": item.created_at.isoformat(),
            }
            for item in service.revisions(server_id)
        ]
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/servers/{server_id}/revisions/{revision_id}/restore")
def restore_registry_revision(
    server_id: str,
    revision_id: str,
    payload: MCPRevisionRestoreRequest,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPRegistryService(db)
    try:
        server = service.restore(
            server_id,
            revision_id,
            expected_version=payload.expected_version,
            actor=principal.login,
        )
        return service.public_dict(server)
    except MCPRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPRegistryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
