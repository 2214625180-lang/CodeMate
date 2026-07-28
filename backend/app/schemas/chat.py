from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8000)


class MultiRepoChatRequest(ChatRequest):
    repo_ids: list[str] | None = Field(default=None, max_length=16)


class CodeCitation(BaseModel):
    chunk_id: str
    repo_id: str | None = None
    repo_name: str | None = None
    file_path: str
    start_line: int | None
    end_line: int | None
    symbol_name: str | None
    symbol_type: str | None
