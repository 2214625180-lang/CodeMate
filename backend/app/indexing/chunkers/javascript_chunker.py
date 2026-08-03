import re
from pathlib import Path
from typing import Any

from app.indexing.chunkers.base import ChunkData, ParsedFile, line_slice, make_content_hash


class JavaScriptTreeSitterChunker:
    def __init__(self, path: Path):
        self.path = path

    def parse(self, path: Path, content: str) -> ParsedFile:
        imports = self._extract_imports(content)
        exports = self._extract_exports(content)

        try:
            from tree_sitter_languages import get_parser

            parser_name = self._parser_name(path)
            parser = get_parser(parser_name)
            tree = parser.parse(content.encode("utf-8"))
            chunks = self._chunks_from_tree(tree.root_node, content, imports, exports)
            return ParsedFile(imports=imports, exports=exports, chunks=chunks)
        except Exception:  # noqa: BLE001 - fallback keeps indexing usable if parser packages fail.
            return ParsedFile(
                imports=imports,
                exports=exports,
                chunks=SimpleJavaScriptChunker().parse(path, content, imports, exports),
            )

    def _parser_name(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".tsx":
            return "tsx"
        if suffix == ".ts":
            return "typescript"
        return "javascript"

    def _chunks_from_tree(
        self,
        root: Any,
        content: str,
        imports: list[str],
        exports: list[str],
    ) -> list[ChunkData]:
        lines = content.splitlines()
        chunks: list[ChunkData] = []
        seen_ranges: set[tuple[int, int, str]] = set()

        def visit(node: Any, class_name: str | None = None, inside_function: bool = False) -> None:
            node_type = node.type
            next_class_name = class_name
            next_inside_function = inside_function or node_type in {
                "function_declaration",
                "arrow_function",
                "function",
                "method_definition",
            }

            if node_type == "class_declaration":
                name = self._node_name(node) or "AnonymousClass"
                next_class_name = name
                self._append_node_chunk(
                    chunks,
                    seen_ranges,
                    node,
                    lines,
                    name,
                    self._class_symbol_type(node, content),
                    imports,
                    exports,
                )
            elif node_type == "function_declaration":
                name = self._node_name(node) or "anonymous"
                self._append_node_chunk(
                    chunks,
                    seen_ranges,
                    node,
                    lines,
                    name,
                    self._function_symbol_type(name, node, content),
                    imports,
                    exports,
                )
            elif node_type == "method_definition":
                name = self._node_name(node) or "anonymous"
                symbol_name = f"{class_name}.{name}" if class_name else name
                self._append_node_chunk(
                    chunks,
                    seen_ranges,
                    node,
                    lines,
                    symbol_name,
                    "method",
                    imports,
                    exports,
                )
            elif node_type == "variable_declarator" and not inside_function:
                value = node.child_by_field_name("value")
                name = self._node_name(node)
                if name and value is not None and value.type == "arrow_function":
                    self._append_node_chunk(
                        chunks,
                        seen_ranges,
                        node,
                        lines,
                        name,
                        self._function_symbol_type(name, node, content),
                        imports,
                        exports,
                    )

            for child in node.children:
                visit(child, next_class_name, next_inside_function)

        visit(root)
        return chunks

    def _append_node_chunk(
        self,
        chunks: list[ChunkData],
        seen_ranges: set[tuple[int, int, str]],
        node: Any,
        lines: list[str],
        symbol_name: str,
        symbol_type: str,
        imports: list[str],
        exports: list[str],
    ) -> None:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        key = (start_line, end_line, symbol_name)
        if key in seen_ranges:
            return
        seen_ranges.add(key)

        content = line_slice(lines, start_line, end_line)
        # TODO: If a function is too long, split inside the function body while preserving
        # the signature chunk. Phase 2 keeps the full semantic unit intact.
        chunks.append(
            ChunkData(
                symbol_name=symbol_name,
                symbol_type=symbol_type,
                start_line=start_line,
                end_line=end_line,
                content=content,
                content_hash=make_content_hash(content),
                imports=imports,
                exports=exports,
            )
        )

    def _node_name(self, node: Any) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            name_node = node.child_by_field_name("property")
        if name_node is None:
            return None
        return name_node.text.decode("utf-8", errors="ignore")

    def _class_symbol_type(self, node: Any, full_content: str) -> str:
        text = node.text.decode("utf-8", errors="ignore")
        if "React.Component" in text or "React.PureComponent" in text or "Component<" in text:
            return "component"
        return "class"

    def _function_symbol_type(self, name: str, node: Any, full_content: str) -> str:
        text = node.text.decode("utf-8", errors="ignore")
        if name[:1].isupper() and self._looks_like_react_component(text):
            return "component"
        return "function"

    def _looks_like_react_component(self, text: str) -> bool:
        return bool(
            re.search(r"(?:return|=>)\s*\(?\s*<", text)
            or "React.createElement" in text
        )

    def _extract_imports(self, content: str) -> list[str]:
        imports: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            from_match = re.match(r"import\s+.+?\s+from\s+['\"]([^'\"]+)['\"]", stripped)
            side_effect_match = re.match(r"import\s+['\"]([^'\"]+)['\"]", stripped)
            require_match = re.match(
                r"(?:const|let|var)\s+.+?\s*=\s*require\(['\"]([^'\"]+)['\"]\)",
                stripped,
            )
            for match in (from_match, side_effect_match, require_match):
                if match:
                    imports.append(match.group(1))
        return sorted(set(imports))

    def _extract_exports(self, content: str) -> list[str]:
        exports: list[str] = []
        patterns = [
            r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
            r"export\s+class\s+([A-Za-z_$][\w$]*)",
            r"export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)",
            r"export\s+default\s+(?:function\s+)?([A-Za-z_$][\w$]*)?",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                name = match.group(1)
                exports.append(name or "default")
        return sorted(set(exports))


class SimpleJavaScriptChunker:
    DECLARATION_PATTERNS = [
        (re.compile(r"^\s*export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
        (re.compile(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
        (re.compile(r"^\s*export\s+class\s+([A-Za-z_$][\w$]*)"), "class"),
        (re.compile(r"^\s*class\s+([A-Za-z_$][\w$]*)"), "class"),
        (
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^=]*\)\s*=>"
            ),
            "function",
        ),
        (
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>"
            ),
            "function",
        ),
    ]

    def parse(
        self,
        path: Path,
        content: str,
        imports: list[str],
        exports: list[str],
    ) -> list[ChunkData]:
        lines = content.splitlines()
        chunks: list[ChunkData] = []
        line_index = 0

        while line_index < len(lines):
            line = lines[line_index]
            match_result = self._match_declaration(line)
            if match_result is None:
                line_index += 1
                continue

            symbol_name, symbol_type = match_result
            start_line = line_index + 1
            end_line = self._find_block_end(lines, line_index)
            chunk_content = line_slice(lines, start_line, end_line)
            if symbol_name[:1].isupper() and re.search(r"return\s*\(?\s*<", chunk_content):
                symbol_type = "component"
            chunks.append(
                ChunkData(
                    symbol_name=symbol_name,
                    symbol_type=symbol_type,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_content,
                    content_hash=make_content_hash(chunk_content),
                    imports=imports,
                    exports=exports,
                )
            )
            line_index = end_line

        return chunks

    def _match_declaration(self, line: str) -> tuple[str, str] | None:
        for pattern, symbol_type in self.DECLARATION_PATTERNS:
            match = pattern.match(line)
            if match:
                return match.group(1), symbol_type
        return None

    def _find_block_end(self, lines: list[str], start_index: int) -> int:
        brace_depth = 0
        started = False
        for index in range(start_index, len(lines)):
            line = lines[index]
            brace_depth += line.count("{")
            if "{" in line:
                started = True
            brace_depth -= line.count("}")
            if started and brace_depth <= 0:
                return index + 1
        return start_index + 1
