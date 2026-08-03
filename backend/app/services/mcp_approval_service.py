import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.mcp_tool_approval import MCPToolApproval

ACTIVE_APPROVAL_STATUSES = {"pending", "queued", "resuming", "reconciliation_required"}
SENSITIVE_KEY_PARTS = {"authorization", "password", "secret", "token", "api_key", "apikey"}


class MCPApprovalError(RuntimeError):
    pass


class MCPApprovalNotFoundError(MCPApprovalError):
    pass


class MCPApprovalConflictError(MCPApprovalError):
    pass


class MCPApprovalService:
    def __init__(self, db: Session):
        self.db = db

    def create_pending(
        self,
        *,
        run: AgentRun,
        call: dict[str, Any],
        catalog_entry: dict[str, Any],
        checkpoint: dict[str, Any],
    ) -> MCPToolApproval:
        if not settings.mcp_approval_enabled:
            raise MCPApprovalConflictError("MCP approval workflow is disabled")
        existing = self.db.execute(
            select(MCPToolApproval)
            .where(MCPToolApproval.run_id == run.id)
            .where(MCPToolApproval.status.in_(ACTIVE_APPROVAL_STATUSES))
            .order_by(MCPToolApproval.requested_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        approval_id = str(uuid.uuid4())
        arguments = jsonable(call.get("arguments") or {})
        checkpoint_data = jsonable(
            {
                **checkpoint,
                "resume_from": "mcp_observe",
                "mcp_pending_approval_id": approval_id,
            }
        )
        checkpoint_serialized = canonical_json(checkpoint_data)
        if len(checkpoint_serialized) > settings.mcp_approval_max_checkpoint_chars:
            raise MCPApprovalConflictError("Agent checkpoint exceeds the configured size limit")

        now = datetime.now(timezone.utc)
        approval = MCPToolApproval(
            id=approval_id,
            run_id=run.id,
            qualified_name=str(call["qualified_name"]),
            server_name=str(call["server"]),
            tool_name=str(call["tool"]),
            arguments_json=arguments,
            arguments_hash=sha256_json(arguments),
            tool_schema_json=jsonable(catalog_entry.get("input_schema") or {}),
            catalog_entry_json=jsonable(catalog_entry),
            policy_snapshot=str(catalog_entry.get("policy") or "deny"),
            checkpoint_json=checkpoint_data,
            checkpoint_hash=hashlib.sha256(checkpoint_serialized.encode("utf-8")).hexdigest(),
            status="pending",
            version=1,
            requested_at=now,
            expires_at=now + timedelta(seconds=max(1, settings.mcp_approval_ttl_seconds)),
            updated_at=now,
        )
        run.status = "waiting_approval"
        run.final_summary = "Agent 正在等待 MCP 工具审批。"
        run.failure_reason = None
        run.updated_at = now
        self.db.add_all([approval, run])
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def list_for_run(self, run_id: str) -> list[MCPToolApproval]:
        return list(
            self.db.execute(
                select(MCPToolApproval)
                .where(MCPToolApproval.run_id == run_id)
                .order_by(MCPToolApproval.requested_at.asc())
            )
            .scalars()
            .all()
        )

    def get(self, approval_id: str) -> MCPToolApproval:
        approval = self.db.get(MCPToolApproval, approval_id)
        if approval is None:
            raise MCPApprovalNotFoundError("MCP approval not found")
        return approval

    def decide(
        self,
        *,
        approval_id: str,
        decision: str,
        note: str | None,
        actor: str,
        provider: str,
        expected_version: int,
    ) -> MCPToolApproval:
        approval = self.db.execute(
            select(MCPToolApproval)
            .where(MCPToolApproval.id == approval_id)
            .with_for_update()
        ).scalar_one_or_none()
        if approval is None:
            raise MCPApprovalNotFoundError("MCP approval not found")

        normalized_decision = "approved" if decision == "approve" else "rejected"
        if approval.version != expected_version:
            if approval.decision == normalized_decision:
                return approval
            raise MCPApprovalConflictError("MCP approval version conflict")
        if approval.status != "pending":
            if approval.decision == normalized_decision:
                return approval
            raise MCPApprovalConflictError("MCP approval has already been decided")

        now = datetime.now(timezone.utc)
        expired = now >= approval.expires_at
        approval.decision = "rejected" if expired else normalized_decision
        approval.decision_note = "Approval expired before decision" if expired else note
        approval.decided_by = actor
        approval.decided_provider = provider
        approval.decided_at = now
        approval.status = "queued"
        approval.version += 1
        approval.updated_at = now
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def expire(self, approval_id: str) -> MCPToolApproval | None:
        approval = self.db.execute(
            select(MCPToolApproval)
            .where(MCPToolApproval.id == approval_id)
            .with_for_update()
        ).scalar_one_or_none()
        if approval is None or approval.status != "pending":
            return None
        now = datetime.now(timezone.utc)
        if now < approval.expires_at:
            return None
        approval.decision = "rejected"
        approval.decision_note = "Approval expired"
        approval.decided_by = "system-expiry"
        approval.decided_provider = "system"
        approval.decided_at = now
        approval.status = "queued"
        approval.version += 1
        approval.updated_at = now
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def claim_for_resume(self, approval_id: str) -> MCPToolApproval | None:
        approval = self.db.execute(
            select(MCPToolApproval)
            .where(MCPToolApproval.id == approval_id)
            .with_for_update()
        ).scalar_one_or_none()
        if approval is None:
            raise MCPApprovalNotFoundError("MCP approval not found")
        now = datetime.now(timezone.utc)
        if approval.status == "resuming":
            stale_after = timedelta(seconds=max(1, settings.mcp_approval_resume_stale_seconds))
            if approval.execution_started_at and now - approval.execution_started_at < stale_after:
                return None
        elif approval.status != "queued":
            return None

        approval.status = "resuming"
        approval.execution_started_at = now
        approval.version += 1
        approval.updated_at = now
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def finish(
        self,
        approval: MCPToolApproval,
        *,
        result: dict[str, Any],
        failed: bool = False,
    ) -> MCPToolApproval:
        now = datetime.now(timezone.utc)
        approval.status = "failed" if failed else "completed"
        approval.result_json = jsonable(result)
        approval.error_message = str(result.get("error"))[:4000] if failed else None
        approval.execution_finished_at = now
        approval.version += 1
        approval.updated_at = now
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    @staticmethod
    def verify_checkpoint(approval: MCPToolApproval) -> bool:
        serialized = canonical_json(approval.checkpoint_json)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return digest == approval.checkpoint_hash

    @staticmethod
    def public_dict(approval: MCPToolApproval) -> dict[str, Any]:
        return {
            "id": approval.id,
            "run_id": approval.run_id,
            "qualified_name": approval.qualified_name,
            "server_name": approval.server_name,
            "tool_name": approval.tool_name,
            "arguments": redact_sensitive(approval.arguments_json),
            "arguments_hash": approval.arguments_hash,
            "policy_snapshot": approval.policy_snapshot,
            "status": approval.status,
            "decision": approval.decision,
            "decision_note": approval.decision_note,
            "decided_by": approval.decided_by,
            "decided_provider": approval.decided_provider,
            "version": approval.version,
            "requested_at": approval.requested_at.isoformat(),
            "expires_at": approval.expires_at.isoformat(),
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "execution_started_at": (
                approval.execution_started_at.isoformat()
                if approval.execution_started_at
                else None
            ),
            "execution_finished_at": (
                approval.execution_finished_at.isoformat()
                if approval.execution_finished_at
                else None
            ),
            "result": redact_sensitive(approval.result_json),
            "error_message": approval.error_message,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                redacted[str(key)] = "***redacted***"
            else:
                redacted[str(key)] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value
