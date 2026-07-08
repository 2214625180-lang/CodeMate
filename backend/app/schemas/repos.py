from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RepositoryStatus = Literal["pending", "cloning", "parsing", "embedding", "indexed", "failed"]


class RepositoryCreate(BaseModel):
    repo_url: str = Field(..., min_length=5, max_length=2048)


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    repo_url: str
    local_path: str | None
    status: RepositoryStatus
    error_message: str | None
    language_summary: dict
    last_commit_hash: str | None
    file_count: int
    chunk_count: int
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RepositoryStatusRead(BaseModel):
    id: str
    status: RepositoryStatus
    error_message: str | None = None
    file_count: int = 0
    chunk_count: int = 0
