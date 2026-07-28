import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class ChunkData:
    symbol_name: str
    symbol_type: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedFile:
    imports: list[str]
    exports: list[str]
    chunks: list[ChunkData]


class Chunker(Protocol):
    def parse(self, path: Path, content: str) -> ParsedFile:
        ...


def make_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def line_slice(lines: list[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1 : end_line])
