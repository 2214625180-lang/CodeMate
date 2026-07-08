from typing import Any, TypedDict


class FixAgentState(TypedDict, total=False):
    run_id: str
    repo_id: str
    user_input: str
    test_command: str | None
    parsed_issue: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    files: dict[str, str]
    diagnosis: str
    patch: str
    apply_result: dict[str, Any]
    test_result: dict[str, Any]
    reflection: dict[str, Any]
    iterations: int
    max_iterations: int
    final_diff: str
    final_summary: str
    status: str
