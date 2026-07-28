import ast
from pathlib import Path

from app.indexing.chunkers.base import ChunkData, ParsedFile, line_slice, make_content_hash


class PythonAstChunker:
    def parse(self, path: Path, content: str) -> ParsedFile:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return ParsedFile(imports=[], exports=[], chunks=[])

        lines = content.splitlines()
        imports = self._extract_imports(tree)
        exports = self._extract_exports(tree)
        chunks: list[ChunkData] = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                chunks.append(self._chunk_from_node(node, lines, "class", imports, exports))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        chunks.append(
                            self._chunk_from_node(
                                child,
                                lines,
                                "method",
                                imports,
                                exports,
                                symbol_prefix=node.name,
                            )
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol_type = "decorated_function" if node.decorator_list else "function"
                chunks.append(self._chunk_from_node(node, lines, symbol_type, imports, exports))

        return ParsedFile(imports=imports, exports=exports, chunks=chunks)

    def _chunk_from_node(
        self,
        node: ast.AST,
        lines: list[str],
        symbol_type: str,
        imports: list[str],
        exports: list[str],
        symbol_prefix: str | None = None,
    ) -> ChunkData:
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        name = getattr(node, "name", "anonymous")
        symbol_name = f"{symbol_prefix}.{name}" if symbol_prefix else name
        content = line_slice(lines, start_line, end_line)

        # TODO: If a function is too long, split inside the function body while preserving
        # the signature chunk. Phase 2 keeps the full semantic unit intact.
        return ChunkData(
            symbol_name=symbol_name,
            symbol_type=symbol_type,
            start_line=start_line,
            end_line=end_line,
            content=content,
            content_hash=make_content_hash(content),
            imports=imports,
            exports=exports,
        )

    def _extract_imports(self, tree: ast.Module) -> list[str]:
        imports: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.extend(f"{module}.{alias.name}".strip(".") for alias in node.names)
        return sorted(set(imports))

    def _extract_exports(self, tree: ast.Module) -> list[str]:
        exports: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    exports.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        exports.extend(self._literal_string_list(node.value))
        return sorted(set(exports))

    def _literal_string_list(self, node: ast.AST) -> list[str]:
        if not isinstance(node, (ast.List, ast.Tuple)):
            return []
        values: list[str] = []
        for item in node.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
        return values
