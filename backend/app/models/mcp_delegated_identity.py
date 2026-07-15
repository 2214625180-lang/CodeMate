import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MCPDelegatedOAuthProvider(Base):
    __tablename__ = "mcp_delegated_oauth_providers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "server_name", name="uq_mcp_delegated_provider_server"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authorization_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    token_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    client_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    encrypted_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MCPDelegatedIdentity(Base):
    __tablename__ = "mcp_delegated_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_delegated_oauth_providers.id", ondelete="CASCADE"), nullable=False
    )
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    encrypted_token_payload: Mapped[str] = mapped_column(Text, nullable=False)
    delegation_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MCPDelegatedOAuthState(Base):
    __tablename__ = "mcp_delegated_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_delegated_oauth_providers.id", ondelete="CASCADE"), nullable=False
    )
    subject_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
