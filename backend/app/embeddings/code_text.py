from typing import Any


def build_chunk_embedding_text(chunk: Any) -> str:
    return build_code_embedding_text(
        file_path=chunk.file_path,
        language=chunk.language,
        symbol_name=chunk.symbol_name,
        symbol_type=chunk.symbol_type,
        imports=chunk.imports,
        exports=chunk.exports,
        content=chunk.content or "",
    )


def build_code_embedding_text(
    *,
    file_path: str,
    language: str,
    symbol_name: str | None,
    symbol_type: str | None,
    imports: list | None,
    exports: list | None,
    content: str,
) -> str:
    parts = [
        f"path: {file_path}",
        f"language: {language}",
    ]
    if symbol_name:
        parts.append(f"symbol: {symbol_name}")
    if symbol_type:
        parts.append(f"symbol_type: {symbol_type}")
    imports_text = _join_metadata(imports)
    if imports_text:
        parts.append(f"imports: {imports_text}")
    exports_text = _join_metadata(exports)
    if exports_text:
        parts.append(f"exports: {exports_text}")
    parts.append(f"code:\n{content}")
    return "\n".join(parts)


def build_query_embedding_text(
    *,
    query: str,
    keywords: list[str],
    file_paths: list[str],
    symbols: list[str],
    error_terms: list[str],
) -> str:
    parts = [f"query: {query}"]
    if keywords:
        parts.append(f"keywords: {', '.join(keywords[:24])}")
    if file_paths:
        parts.append(f"file_paths: {', '.join(file_paths[:8])}")
    if symbols:
        parts.append(f"symbols: {', '.join(symbols[:16])}")
    if error_terms:
        parts.append(f"errors: {', '.join(error_terms[:8])}")
    return "\n".join(parts)


def _join_metadata(values: list | None) -> str:
    if not values:
        return ""
    return ", ".join(str(value) for value in values[:32] if value)
