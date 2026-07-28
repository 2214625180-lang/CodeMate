from pydantic import BaseModel, ConfigDict


class CodeFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_path: str
    language: str
    content_hash: str
    line_count: int
    size_bytes: int
    imports: list
    exports: list


class FileContentRead(BaseModel):
    file_path: str
    language: str | None = None
    start_line: int
    end_line: int
    content: str
