from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer


RepositoryStatus = Literal["pending", "cloning", "parsing", "embedding", "indexed", "failed"]


class RepositoryCreate(BaseModel):
    repo_url: str = Field(..., min_length=5, max_length=2048)


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    repo_url: str
    status: RepositoryStatus
    error_message: str | None
    language_summary: dict
    last_commit_hash: str | None
    file_count: int
    chunk_count: int
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("repo_url")
    def redact_legacy_repository_userinfo(self, value: str) -> str:
        """Avoid reflecting credentials from repository rows created before validation."""
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return value
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        try:
            port = parsed.port
        except ValueError:
            return value
        netloc = f"{host}:{port}" if port is not None else host
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


class RepositoryStatusRead(BaseModel):
    id: str
    status: RepositoryStatus
    error_message: str | None = None
    file_count: int = 0
    chunk_count: int = 0
