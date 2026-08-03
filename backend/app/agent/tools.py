import posixpath
from pathlib import Path, PurePosixPath
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.sandbox import SandboxService
from app.services.agent_step_service import AgentStepService
from app.services.retrieval_service import RetrievalService


class AgentTools:
    GRAPH_MAX_NODES = 80
    GRAPH_MAX_EDGES = 120
    CALL_RE = re.compile(
        r"(?<![\w$])([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?)\s*\("
    )
    CALL_KEYWORDS = {"catch", "class", "def", "for", "function", "if", "switch", "while"}

    def __init__(
        self,
        *,
        db: Session,
        run_id: str,
        repo_id: str,
        workspace: Path,
        sandbox: SandboxService,
    ):
        self.db = db
        self.run_id = run_id
        self.repo_id = repo_id
        self.workspace = workspace
        self.sandbox = sandbox
        self.steps = AgentStepService(db)

    def search_code(self, query: str, top_k: int = 6) -> list[dict]:
        def _call():
            results = RetrievalService(self.db).retrieve(
                repo_id=self.repo_id,
                query=query,
                top_k=top_k,
            )
            return [
                {
                    "chunk_id": result.chunk.id,
                    "file_path": result.chunk.file_path,
                    "symbol_name": result.chunk.symbol_name,
                    "symbol_type": result.chunk.symbol_type,
                    "start_line": result.chunk.start_line,
                    "end_line": result.chunk.end_line,
                    "score": result.score,
                    "source": result.source,
                    "content": (result.chunk.content or "")[:4000],
                }
                for result in results
            ]

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="search_code",
            input_json={"query": query, "repo_id": self.repo_id, "top_k": top_k},
            fn=_call,
        )

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="read_file",
            input_json={"path": path, "start_line": start_line, "end_line": end_line},
            fn=lambda: self.sandbox.read_file(
                workspace=self.workspace,
                file_path=path,
                start_line=start_line,
                end_line=end_line,
            ),
        )

    def list_files(self, pattern: str | None = None) -> list[str]:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="list_files",
            input_json={"pattern": pattern},
            fn=lambda: self.sandbox.list_files(workspace=self.workspace, pattern=pattern),
        )

    def find_symbol(self, symbol: str, limit: int = 12) -> list[dict]:
        def _call() -> list[dict]:
            chunks = (
                self.db.execute(
                    select(CodeChunk)
                    .where(
                        CodeChunk.repo_id == self.repo_id,
                        CodeChunk.symbol_name == symbol,
                    )
                    .order_by(CodeChunk.file_path, CodeChunk.start_line)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._chunk_result(chunk, symbol) for chunk in chunks]

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="find_symbol",
            input_json={"symbol": symbol, "repo_id": self.repo_id, "limit": limit},
            fn=_call,
        )

    def find_references(self, symbol: str, limit: int = 20) -> list[dict]:
        def _call() -> list[dict]:
            candidates = (
                self.db.execute(
                    select(CodeChunk)
                    .where(
                        CodeChunk.repo_id == self.repo_id,
                        CodeChunk.content.ilike(f"%{self._escape_like(symbol)}%", escape="\\"),
                    )
                    .order_by(CodeChunk.file_path, CodeChunk.start_line)
                    .limit(limit * 4)
                )
                .scalars()
                .all()
            )
            boundary = re.compile(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])")
            references = [
                self._chunk_result(chunk, symbol)
                for chunk in candidates
                if boundary.search(chunk.content or "")
            ]
            return references[:limit]

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="find_references",
            input_json={"symbol": symbol, "repo_id": self.repo_id, "limit": limit},
            fn=_call,
        )

    def get_import_graph(
        self,
        path: str,
        *,
        direction: str = "both",
        depth: int = 1,
    ) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="get_import_graph",
            input_json={
                "path": path,
                "repo_id": self.repo_id,
                "direction": direction,
                "depth": depth,
            },
            fn=lambda: self._build_import_graph(path, direction=direction, depth=depth),
        )

    def get_call_graph(
        self,
        symbol: str,
        *,
        direction: str = "both",
        depth: int = 1,
    ) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="get_call_graph",
            input_json={
                "symbol": symbol,
                "repo_id": self.repo_id,
                "direction": direction,
                "depth": depth,
            },
            fn=lambda: self._build_call_graph(symbol, direction=direction, depth=depth),
        )

    def apply_patch(self, diff: str) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="apply_patch",
            input_json={"diff_preview": diff[:1000], "length": len(diff)},
            fn=lambda: self.sandbox.apply_patch(workspace=self.workspace, diff=diff),
        )

    def inspect_repository(self, requested_test_command: str | None) -> dict:
        def _call() -> dict:
            files = self.sandbox.list_files(workspace=self.workspace)
            detected_test_command = self.sandbox.detect_test_command(
                workspace=self.workspace,
                requested_command=None,
            )
            resolved_test_command = self.sandbox.detect_test_command(
                workspace=self.workspace,
                requested_command=requested_test_command,
            )
            return {
                "file_count": len(files),
                "requested_test_command": requested_test_command,
                "detected_test_command": detected_test_command,
                "resolved_test_command": resolved_test_command,
                "regression_test_command": detected_test_command or resolved_test_command,
            }

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="inspect_repository",
            input_json={"requested_test_command": requested_test_command},
            fn=_call,
        )

    def run_tests(self, command: str | None = None, *, phase: str) -> dict:
        detected = self.sandbox.detect_test_command(
            workspace=self.workspace,
            requested_command=command,
        )
        result = self.steps.record_tool(
            run_id=self.run_id,
            tool_name="run_tests",
            input_json={"command": detected, "phase": phase},
            fn=lambda: self.sandbox.run_tests(workspace=self.workspace, command=detected).to_dict(),
        )
        result["phase"] = phase
        return result

    def git_diff(self) -> str:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="git_diff",
            input_json={},
            fn=lambda: self.sandbox.git_diff(workspace=self.workspace),
        )

    def reset_workspace(self) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="reset_workspace",
            input_json={},
            fn=lambda: self.sandbox.reset_workspace(workspace=self.workspace),
        )

    def _build_import_graph(self, path: str, *, direction: str, depth: int) -> dict:
        files = self._indexed_files()
        by_path = {code_file.file_path: code_file for code_file in files}
        normalized_path = path.strip()
        if normalized_path not in by_path:
            return {
                "kind": "import",
                "path": normalized_path,
                "direction": direction,
                "depth": depth,
                "nodes": [],
                "edges": [],
                "error": "indexed_file_not_found",
                "truncated": False,
            }

        nodes: dict[str, dict] = {}
        edges: dict[tuple[str, str, str], dict] = {}
        frontier = [(normalized_path, 0)]
        visited = {normalized_path}
        truncated = False

        def add_node(node: dict) -> bool:
            nonlocal truncated
            node_id = str(node["id"])
            if node_id in nodes:
                return True
            if len(nodes) >= self.GRAPH_MAX_NODES:
                truncated = True
                return False
            nodes[node_id] = node
            return True

        def add_edge(edge: dict) -> bool:
            nonlocal truncated
            key = (str(edge["from"]), str(edge["to"]), str(edge["kind"]))
            if key in edges:
                return True
            if len(edges) >= self.GRAPH_MAX_EDGES:
                truncated = True
                return False
            edges[key] = edge
            return True

        add_node(self._file_node(by_path[normalized_path]))
        while frontier and not truncated:
            current_path, current_depth = frontier.pop(0)
            current_file = by_path[current_path]
            if direction in {"imports", "both"}:
                for imported in sorted(current_file.imports or []):
                    target_path = self._resolve_import_path(current_path, imported, by_path)
                    target_id = target_path or f"module:{imported}"
                    target_node = (
                        self._file_node(by_path[target_path])
                        if target_path is not None
                        else {"id": target_id, "kind": "external_module", "name": imported}
                    )
                    if not add_node(target_node) or not add_edge(
                        {"from": current_path, "to": target_id, "kind": "imports", "module": imported}
                    ):
                        break
                    if target_path and current_depth + 1 < depth and target_path not in visited:
                        visited.add(target_path)
                        frontier.append((target_path, current_depth + 1))
            if direction in {"importers", "both"} and not truncated:
                for candidate in files:
                    for imported in sorted(candidate.imports or []):
                        if self._resolve_import_path(candidate.file_path, imported, by_path) != current_path:
                            continue
                        if not add_node(self._file_node(candidate)) or not add_edge(
                            {
                                "from": candidate.file_path,
                                "to": current_path,
                                "kind": "imports",
                                "module": imported,
                            }
                        ):
                            break
                        if current_depth + 1 < depth and candidate.file_path not in visited:
                            visited.add(candidate.file_path)
                            frontier.append((candidate.file_path, current_depth + 1))
                    if truncated:
                        break

        return {
            "kind": "import",
            "path": normalized_path,
            "direction": direction,
            "depth": depth,
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": [edges[key] for key in sorted(edges)],
            "truncated": truncated,
        }

    def _build_call_graph(self, symbol: str, *, direction: str, depth: int) -> dict:
        chunks = self._indexed_chunks()
        nodes: dict[str, dict] = {}
        edges: dict[tuple[str, str], dict] = {}
        frontier = [symbol]
        visited: set[str] = set()
        truncated = False

        def add_node(node: dict) -> bool:
            nonlocal truncated
            node_id = str(node["id"])
            if node_id in nodes:
                return True
            if len(nodes) >= self.GRAPH_MAX_NODES:
                truncated = True
                return False
            nodes[node_id] = node
            return True

        def add_edge(source: str, target: str) -> bool:
            nonlocal truncated
            key = (source, target)
            if key in edges:
                return True
            if len(edges) >= self.GRAPH_MAX_EDGES:
                truncated = True
                return False
            edges[key] = {"from": source, "to": target, "kind": "calls"}
            return True

        for current_depth in range(depth):
            next_frontier: list[str] = []
            for current_symbol in frontier:
                normalized_symbol = current_symbol.lower()
                if normalized_symbol in visited or truncated:
                    continue
                visited.add(normalized_symbol)
                definitions = [
                    chunk
                    for chunk in chunks
                    if chunk.symbol_name and self._symbol_matches(chunk.symbol_name, current_symbol)
                ]
                target_nodes = [self._symbol_node(chunk) for chunk in definitions]
                if not target_nodes:
                    target_nodes = [
                        {
                            "id": f"external_symbol:{current_symbol}",
                            "kind": "external_symbol",
                            "name": current_symbol,
                        }
                    ]
                for node in target_nodes:
                    add_node(node)

                if direction in {"callers", "both"}:
                    for candidate in chunks:
                        if not self._calls_symbol(candidate.content or "", current_symbol):
                            continue
                        source_node = self._symbol_node(candidate)
                        if not add_node(source_node):
                            break
                        for target_node in target_nodes:
                            if not add_edge(source_node["id"], target_node["id"]):
                                break
                        if candidate.symbol_name and current_depth + 1 < depth:
                            next_frontier.append(candidate.symbol_name)

                if direction in {"callees", "both"} and not truncated:
                    for definition in definitions:
                        source_node = self._symbol_node(definition)
                        if not add_node(source_node):
                            break
                        for callee in self._called_symbols(definition.content or ""):
                            targets = [
                                self._symbol_node(chunk)
                                for chunk in chunks
                                if chunk.symbol_name and self._symbol_matches(chunk.symbol_name, callee)
                            ]
                            if not targets:
                                targets = [
                                    {
                                        "id": f"external_symbol:{callee}",
                                        "kind": "external_symbol",
                                        "name": callee,
                                    }
                                ]
                            for target in targets:
                                if not add_node(target) or not add_edge(source_node["id"], target["id"]):
                                    break
                            if current_depth + 1 < depth:
                                next_frontier.append(callee)
            frontier = sorted(set(next_frontier))
            if not frontier or truncated:
                break

        return {
            "kind": "call",
            "symbol": symbol,
            "direction": direction,
            "depth": depth,
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": [edges[key] for key in sorted(edges)],
            "truncated": truncated,
        }

    def _indexed_files(self) -> list[CodeFile]:
        return list(
            self.db.execute(
                select(CodeFile)
                .where(CodeFile.repo_id == self.repo_id)
                .order_by(CodeFile.file_path)
            )
            .scalars()
            .all()
        )

    def _indexed_chunks(self) -> list[CodeChunk]:
        return list(
            self.db.execute(
                select(CodeChunk)
                .where(CodeChunk.repo_id == self.repo_id)
                .where(CodeChunk.symbol_name.is_not(None))
                .where(CodeChunk.content.is_not(None))
                .order_by(CodeChunk.file_path, CodeChunk.start_line, CodeChunk.id)
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _file_node(code_file: CodeFile) -> dict:
        return {
            "id": code_file.file_path,
            "kind": "file",
            "path": code_file.file_path,
            "language": code_file.language,
        }

    @staticmethod
    def _symbol_node(chunk: CodeChunk) -> dict:
        return {
            "id": f"symbol:{chunk.file_path}:{chunk.start_line}:{chunk.symbol_name}",
            "kind": "symbol",
            "name": chunk.symbol_name,
            "path": chunk.file_path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
        }

    @staticmethod
    def _resolve_import_path(
        source_path: str,
        imported: str,
        files_by_path: dict[str, CodeFile],
    ) -> str | None:
        normalized_import = imported.strip().replace("\\", "/")
        module_candidates: list[str] = []
        if normalized_import.startswith("."):
            source_dir = str(PurePosixPath(source_path).parent)
            module_candidates.append(posixpath.normpath(posixpath.join(source_dir, normalized_import)))
        else:
            parts = normalized_import.replace("/", ".").split(".")
            for end in range(len(parts), 0, -1):
                module_candidates.append("/".join(parts[:end]))

        for candidate in module_candidates:
            for file_path in files_by_path:
                stem = str(PurePosixPath(file_path).with_suffix(""))
                stems = {stem}
                if stem.endswith("/index"):
                    stems.add(stem.removesuffix("/index"))
                if stem.endswith("/__init__"):
                    stems.add(stem.removesuffix("/__init__"))
                if candidate in stems or any(stem.endswith(f"/{candidate}") for stem in stems):
                    return file_path
        return None

    @classmethod
    def _calls_symbol(cls, content: str, symbol: str) -> bool:
        target = symbol.rsplit(".", maxsplit=1)[-1]
        return any(
            call == symbol or call.rsplit(".", maxsplit=1)[-1] == target
            for call in cls._called_symbols(content)
        )

    @classmethod
    def _called_symbols(cls, content: str) -> list[str]:
        calls: list[str] = []
        for match in cls.CALL_RE.finditer(content):
            call = match.group(1)
            prefix = content[max(0, match.start() - 12) : match.start()].strip()
            if call in cls.CALL_KEYWORDS or prefix.endswith(("def", "function", "class")):
                continue
            if call not in calls:
                calls.append(call)
        return calls

    @staticmethod
    def _symbol_matches(candidate: str, symbol: str) -> bool:
        return candidate == symbol or candidate.rsplit(".", maxsplit=1)[-1] == symbol.rsplit(
            ".", maxsplit=1
        )[-1]

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _chunk_result(chunk: CodeChunk, symbol: str) -> dict:
        content = chunk.content or ""
        match = re.search(re.escape(symbol), content)
        if match:
            start = max(0, match.start() - 600)
            end = min(len(content), match.end() + 1_400)
            preview = content[start:end]
        else:
            preview = content[:2_000]
        return {
            "chunk_id": chunk.id,
            "file_path": chunk.file_path,
            "symbol_name": chunk.symbol_name,
            "symbol_type": chunk.symbol_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content": preview,
        }
