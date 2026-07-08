from pathlib import Path

from app.indexing.chunkers.base import Chunker
from app.indexing.chunkers.javascript_chunker import JavaScriptTreeSitterChunker
from app.indexing.chunkers.python_chunker import PythonAstChunker
from app.indexing.chunkers.vue_chunker import VueSFCChunker


def get_chunker(language: str, path: Path) -> Chunker:
    if language == "python":
        return PythonAstChunker()
    if language in {"typescript", "javascript"}:
        return JavaScriptTreeSitterChunker(path)
    if language == "vue":
        return VueSFCChunker(path)
    raise ValueError(f"Unsupported language for chunking: {language}")
