from datetime import datetime

from pydantic import BaseModel


class RepoMemoryRead(BaseModel):
    repo_id: str
    summary: str | None
    data: dict
    updated_at: datetime | None
