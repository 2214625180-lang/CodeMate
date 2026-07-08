from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Iterator


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
