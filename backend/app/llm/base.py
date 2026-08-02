from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Any

from app.agent.actions import Finish, PlanNextAction


@dataclass(slots=True)
class LLMContext:
    chunk_id: str
    file_path: str
    symbol_name: str | None
    symbol_type: str | None
    start_line: int | None
    end_line: int | None
    content: str
    repo_id: str | None = None
    repo_name: str | None = None


class BaseLLMProvider(ABC):
    @abstractmethod
    def stream_answer(self, *, question: str, contexts: list[LLMContext]) -> Iterator[str]:
        raise NotImplementedError

    def generate_patch(
        self,
        *,
        issue: str,
        diagnosis: str,
        files: dict[str, str],
        previous_failure: str | None = None,
    ) -> str:
        raise NotImplementedError("Patch generation is not implemented for this provider.")

    def plan_next_action(
        self,
        *,
        issue: str,
        context: dict[str, Any],
    ) -> tuple[PlanNextAction, int]:
        return (
            Finish(
                action="Finish",
                hypothesis="The configured model does not support local action planning.",
                rationale="Stopping is safer than inventing an unvalidated action.",
                reason="local_action_planner_not_implemented",
            ),
            0,
        )

    def record_llm_usage(
        self,
        *,
        total_tokens: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated: bool = False,
    ) -> None:
        """Expose per-call usage to the deterministic trace without provider coupling."""

        self._last_llm_usage = {
            "total_tokens": max(0, int(total_tokens)),
            "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
            "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
            "estimated": estimated,
        }

    def consume_llm_usage(self) -> dict[str, int | bool | None] | None:
        usage = getattr(self, "_last_llm_usage", None)
        self._last_llm_usage = None
        return usage if isinstance(usage, dict) else None

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
        return []

    def reflect(
        self,
        *,
        issue: str,
        patch: str,
        test_result: dict,
        iteration: int,
    ) -> dict:
        return {
            "summary": "测试未通过，需要重新生成 patch 或读取更多上下文。",
            "next_action": "regenerate_patch",
        }

    def review_pull_request(
        self,
        *,
        diff: str,
        contexts: list[LLMContext],
        question: str | None = None,
    ) -> dict:
        return {
            "summary": "当前 provider 未实现真实 PR Review。",
            "findings": [],
        }
