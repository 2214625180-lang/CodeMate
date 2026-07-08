import re
from pathlib import Path

from app.indexing.chunkers.base import ChunkData, ParsedFile, line_slice, make_content_hash
from app.indexing.chunkers.javascript_chunker import JavaScriptTreeSitterChunker


class VueSFCChunker:
    BLOCK_RE = re.compile(
        r"<(?P<tag>template|script)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, path: Path):
        self.path = path

    def parse(self, path: Path, content: str) -> ParsedFile:
        lines = content.splitlines()
        chunks: list[ChunkData] = []
        script_bodies: list[str] = []

        for match in self.BLOCK_RE.finditer(content):
            tag = match.group("tag").lower()
            attrs = match.group("attrs") or ""
            body = match.group("body")
            body_start_line = content.count("\n", 0, match.start("body")) + 1

            if tag == "template":
                template_chunk = self._template_chunk(path, lines, body, body_start_line)
                if template_chunk is not None:
                    chunks.append(template_chunk)
                continue

            script_bodies.append(body)
            chunks.extend(
                self._script_chunks(
                    path=path,
                    full_lines=lines,
                    body=body,
                    attrs=attrs,
                    body_start_line=body_start_line,
                )
            )

        imports = self._extract_imports(script_bodies)
        exports = self._extract_exports(script_bodies)
        chunks = [
            ChunkData(
                symbol_name=chunk.symbol_name,
                symbol_type=chunk.symbol_type,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                content_hash=chunk.content_hash,
                imports=imports,
                exports=exports,
            )
            for chunk in chunks
        ]
        return ParsedFile(imports=imports, exports=exports, chunks=chunks)

    def _template_chunk(
        self,
        path: Path,
        lines: list[str],
        body: str,
        body_start_line: int,
    ) -> ChunkData | None:
        if not body.strip():
            return None
        start_line, end_line = self._absolute_body_range(body, body_start_line)
        content = line_slice(lines, start_line, end_line)
        return ChunkData(
            symbol_name=f"{path.stem}.template",
            symbol_type="template",
            start_line=start_line,
            end_line=end_line,
            content=content,
            content_hash=make_content_hash(content),
        )

    def _script_chunks(
        self,
        *,
        path: Path,
        full_lines: list[str],
        body: str,
        attrs: str,
        body_start_line: int,
    ) -> list[ChunkData]:
        lang = self._script_language(attrs)
        synthetic_path = path.with_suffix(".ts" if lang == "typescript" else ".js")
        parsed = JavaScriptTreeSitterChunker(synthetic_path).parse(synthetic_path, body)
        chunks = [
            self._shift_chunk_lines(chunk, full_lines, body_start_line)
            for chunk in parsed.chunks
        ]
        if chunks:
            return chunks

        if not body.strip():
            return []
        start_line, end_line = self._absolute_body_range(body, body_start_line)
        content = line_slice(full_lines, start_line, end_line)
        script_kind = "script_setup" if "setup" in attrs else "script"
        return [
            ChunkData(
                symbol_name=f"{path.stem}.{script_kind}",
                symbol_type=script_kind,
                start_line=start_line,
                end_line=end_line,
                content=content,
                content_hash=make_content_hash(content),
                imports=parsed.imports,
                exports=parsed.exports,
            )
        ]

    def _shift_chunk_lines(
        self,
        chunk: ChunkData,
        full_lines: list[str],
        body_start_line: int,
    ) -> ChunkData:
        start_line = body_start_line + chunk.start_line - 1
        end_line = body_start_line + chunk.end_line - 1
        content = line_slice(full_lines, start_line, end_line)
        return ChunkData(
            symbol_name=chunk.symbol_name,
            symbol_type=chunk.symbol_type,
            start_line=start_line,
            end_line=end_line,
            content=content,
            content_hash=make_content_hash(content),
            imports=chunk.imports,
            exports=chunk.exports,
        )

    def _absolute_body_range(self, body: str, body_start_line: int) -> tuple[int, int]:
        leading_newlines = len(body) - len(body.lstrip("\n"))
        trailing_newlines = len(body) - len(body.rstrip("\n"))
        body_line_count = max(body.count("\n") + 1, 1)
        start_line = body_start_line + leading_newlines
        end_line = body_start_line + body_line_count - trailing_newlines - 1
        return start_line, max(start_line, end_line)

    def _script_language(self, attrs: str) -> str:
        lang_match = re.search(r"lang=[\"']?([^\"'\s>]+)", attrs, re.IGNORECASE)
        if lang_match and lang_match.group(1).lower() in {"ts", "tsx", "typescript"}:
            return "typescript"
        return "javascript"

    def _extract_imports(self, script_bodies: list[str]) -> list[str]:
        imports: set[str] = set()
        helper = JavaScriptTreeSitterChunker(self.path.with_suffix(".js"))
        for body in script_bodies:
            imports.update(helper._extract_imports(body))
        return sorted(imports)

    def _extract_exports(self, script_bodies: list[str]) -> list[str]:
        exports: set[str] = set()
        helper = JavaScriptTreeSitterChunker(self.path.with_suffix(".js"))
        for body in script_bodies:
            exports.update(helper._extract_exports(body))
        return sorted(exports)
