from collections.abc import Iterator
import difflib
import re

from app.llm.base import BaseLLMProvider, LLMContext


class MockLLMProvider(BaseLLMProvider):
    def stream_answer(self, *, question: str, contexts: list[LLMContext]) -> Iterator[str]:
        if not contexts:
            yield "未在当前索引中找到相关代码。"
            return

        top = contexts[0]
        lines = self._line_range(top)
        references = "\n".join(
            f"- {self._context_path(context)}:{self._line_range(context)}"
            + (f" `{context.symbol_name}`" if context.symbol_name else "")
            for context in contexts[:5]
        )

        answer = (
            f"根据当前索引，最相关的代码位于 {self._context_path(top)}:{lines}"
            f"{f'，符号 `{top.symbol_name}`' if top.symbol_name else ''}。\n\n"
            "相关代码：\n"
            f"{references}\n\n"
            "这是基于检索到的 chunk 生成的本地 Mock 回答；后续接入真实 LLM 后会补充更细的逻辑解释。"
        )

        for token in self._chunk_text(answer):
            yield token

    def _line_range(self, context: LLMContext) -> str:
        if context.start_line is None or context.end_line is None:
            return "unknown"
        return f"{context.start_line}-{context.end_line}"

    def _context_path(self, context: LLMContext) -> str:
        if context.repo_name:
            return f"{context.repo_name}/{context.file_path}"
        return context.file_path

    def _chunk_text(self, text: str, size: int = 24) -> Iterator[str]:
        for start in range(0, len(text), size):
            yield text[start : start + size]

    def generate_patch(
        self,
        *,
        issue: str,
        diagnosis: str,
        files: dict[str, str],
        previous_failure: str | None = None,
    ) -> str:
        embedded = self._extract_embedded_diff(issue)
        if embedded:
            return embedded

        lowered_issue = issue.lower()
        for file_path, content in files.items():
            updated = self._fix_addition_bug(content, lowered_issue)
            if updated != content:
                return self._unified_diff(file_path, content, updated)

            updated = self._fix_expected_true_bug(content, lowered_issue)
            if updated != content:
                return self._unified_diff(file_path, content, updated)

        return ""

    def plan_mcp_tools(
        self,
        *,
        issue: str,
        repo_id: str,
        diagnosis: str,
        tools: list[dict],
        observations: list[dict],
        max_calls: int,
    ) -> list[dict]:
        if max_calls <= 0:
            return []
        observed_tools = {
            observation.get("qualified_name")
            for observation in observations
            if isinstance(observation, dict)
        }
        for tool in tools:
            qualified_name = tool.get("qualified_name")
            if tool.get("policy") != "auto" or qualified_name in observed_tools:
                continue
            name = str(tool.get("name") or "").lower()
            if not any(hint in name for hint in ("search", "find", "lookup", "query", "get")):
                continue
            arguments = self._mock_mcp_arguments(
                schema=tool.get("input_schema") or {},
                issue=issue,
                repo_id=repo_id,
            )
            if arguments is not None:
                return [{"tool": qualified_name, "arguments": arguments}]
        return []

    def _mock_mcp_arguments(
        self,
        *,
        schema: dict,
        issue: str,
        repo_id: str,
    ) -> dict | None:
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required")
        if not isinstance(required, list):
            required = []
        arguments: dict = {}
        for name in properties:
            lowered = name.lower()
            if lowered in {"query", "question", "issue", "text", "message"}:
                arguments[name] = issue
            elif lowered in {"repo_id", "repository_id"}:
                arguments[name] = repo_id
        if any(name not in arguments for name in required):
            return None
        return arguments

    def reflect(
        self,
        *,
        issue: str,
        patch: str,
        test_result: dict,
        iteration: int,
    ) -> dict:
        if not patch:
            return {
                "summary": "Mock provider 没有找到可套用的确定性修复规则。",
                "next_action": "read_more_context",
            }
        if not test_result.get("tests_ran"):
            return {
                "summary": "未运行测试，无法根据测试输出反思。",
                "next_action": "stop",
            }
        return {
            "summary": f"第 {iteration} 轮测试失败，下一轮重新生成 patch。",
            "next_action": "regenerate_patch",
        }

    def review_pull_request(
        self,
        *,
        diff: str,
        contexts: list[LLMContext],
        question: str | None = None,
    ) -> dict:
        changed_files = self._extract_changed_files(diff)
        context_files = sorted({context.file_path for context in contexts})
        return {
            "summary": (
                f"Mock PR Review 检测到 {len(changed_files)} 个变更文件。"
                "已返回检索上下文，真实 LLM provider 会生成具体风险和建议。"
            ),
            "findings": [],
            "changed_files": changed_files,
            "context_files": context_files,
        }

    def _extract_embedded_diff(self, issue: str) -> str:
        fence_match = re.search(r"```(?:diff|patch)?\n(.*?)```", issue, re.DOTALL)
        if fence_match and ("--- " in fence_match.group(1) or "diff --git" in fence_match.group(1)):
            return fence_match.group(1).strip() + "\n"
        if "--- a/" in issue and "+++ b/" in issue:
            return issue[issue.index("--- a/") :].strip() + "\n"
        return ""

    def _extract_changed_files(self, diff: str) -> list[str]:
        files: list[str] = []
        for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", diff, re.MULTILINE):
            path = match.group(2)
            if path != "/dev/null" and path not in files:
                files.append(path)
        return files

    def _fix_addition_bug(self, content: str, lowered_issue: str) -> str:
        addition_hints = ("add", "sum", "plus", "addition", "expected", "加法", "求和")
        if not any(hint in lowered_issue for hint in addition_hints):
            return content

        patterns = [
            (
                r"return\s+([A-Za-z_$][\w$]*)\s*-\s*([A-Za-z_$][\w$]*)(\s*;?)",
                r"return \1 + \2\3",
            ),
            (
                r"return\s+([A-Za-z_$][\w$]*)\s*\*\s*([A-Za-z_$][\w$]*)(\s*;?)",
                r"return \1 + \2\3",
            ),
        ]
        for pattern, replacement in patterns:
            updated, count = re.subn(pattern, replacement, content, count=1)
            if count:
                return updated
        return content

    def _fix_expected_true_bug(self, content: str, lowered_issue: str) -> str:
        if "expected true" not in lowered_issue and "to be true" not in lowered_issue:
            return content
        return content.replace("return false;", "return true;", 1).replace(
            "return False",
            "return True",
            1,
        )

    def _unified_diff(self, file_path: str, original: str, updated: str) -> str:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )
        )
