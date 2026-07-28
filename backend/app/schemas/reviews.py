from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReviewRequest(BaseModel):
    diff: str | None = Field(default=None, max_length=200_000)
    base_ref: str | None = Field(default=None, max_length=255)
    head_ref: str | None = Field(default=None, max_length=255)
    question: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_diff_or_refs(self):
        if self.diff and self.diff.strip():
            return self
        if self.base_ref and self.head_ref:
            return self
        raise ValueError("Provide either a diff or both base_ref and head_ref.")


class ReviewFinding(BaseModel):
    severity: Literal["info", "low", "medium", "high"] = "info"
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    title: str
    body: str
    suggestion: str | None = None


class ReviewCitation(BaseModel):
    chunk_id: str
    repo_id: str | None = None
    repo_name: str | None = None
    file_path: str
    start_line: int | None
    end_line: int | None
    symbol_name: str | None
    symbol_type: str | None


class ReviewResponse(BaseModel):
    summary: str
    changed_files: list[str]
    findings: list[ReviewFinding]
    citations: list[ReviewCitation]
