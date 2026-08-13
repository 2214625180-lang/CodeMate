import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.agent.actions import (
    LOCAL_TOOL_ACTIONS,
    PLAN_NEXT_ACTION_ADAPTER,
    FindReferences,
    FindSymbol,
    Finish,
    GeneratePatch,
    GetCallGraph,
    GetImportGraph,
    ListFiles,
    PlanNextAction,
    ReadFile,
    RunTests,
    SearchCode,
    action_fingerprint,
)
from app.agent.state import FixAgentState
from app.agent.tools import AgentTools
from app.core.config import settings


class LocalAgentExecutor:
    """Deterministic policy boundary for model-selected repository actions."""

    def __init__(self, tools: AgentTools):
        self.tools = tools

    def planner_budget_violation(self, state: FixAgentState) -> str | None:
        if self._deadline_reached(state):
            return "agent_loop_time_budget_exhausted"
        if int(state.get("local_planner_call_count", 0)) >= settings.agent_max_planner_calls:
            return "agent_planner_call_budget_exhausted"
        if int(state.get("local_planner_token_count", 0)) >= settings.agent_max_planner_tokens:
            return "agent_planner_token_budget_exhausted"
        if int(state.get("no_progress_count", 0)) >= settings.agent_max_no_progress_steps:
            return "agent_no_progress_limit_reached"
        return None

    def execute(self, state: FixAgentState, raw_action: dict[str, Any]) -> FixAgentState:
        try:
            action = PLAN_NEXT_ACTION_ADAPTER.validate_python(raw_action)
        except ValidationError as exc:
            return self._guardrail_rejection(
                state,
                raw_action,
                reason=f"invalid_action_schema: {exc.errors(include_url=False)}",
            )

        hypotheses = self._append_bounded_unique(
            list(state.get("hypotheses") or []),
            action.hypothesis,
            limit=20,
        )
        if isinstance(action, Finish):
            history = self._append_history(state, action, status="finished", observation=action.reason)
            return {
                "current_action": action.model_dump(mode="json"),
                "action_outcome": {"route": "final", "ok": True, "reason": action.reason},
                "action_history": history,
                "hypotheses": hypotheses,
                "finish_reason": action.reason,
                "diagnosis": self._diagnosis(hypotheses, state.get("evidence") or []),
            }

        if isinstance(action, GeneratePatch):
            history = self._append_history(
                state,
                action,
                status="accepted",
                observation="Patch generation authorized by the planner.",
            )
            return {
                "current_action": action.model_dump(mode="json"),
                "action_outcome": {"route": "generate", "ok": True},
                "action_history": history,
                "hypotheses": hypotheses,
                "finish_reason": None,
                "diagnosis": self._diagnosis(hypotheses, state.get("evidence") or []),
            }

        if not isinstance(action, LOCAL_TOOL_ACTIONS):
            return self._guardrail_rejection(state, raw_action, reason="action_not_whitelisted")

        budget_reason = self._tool_budget_violation(state)
        if budget_reason:
            return self._forced_finish(state, action, budget_reason, hypotheses)

        fingerprint = action_fingerprint(action)
        prior_fingerprints = list(state.get("local_action_fingerprints") or [])
        if fingerprint in prior_fingerprints:
            return self._guardrail_rejection(
                state,
                action.model_dump(mode="json"),
                reason="duplicate_local_action",
                action=action,
                hypotheses=hypotheses,
            )

        if isinstance(action, ReadFile):
            end_line = action.end_line or (action.start_line + settings.agent_max_read_lines - 1)
            if end_line - action.start_line + 1 > settings.agent_max_read_lines:
                return self._guardrail_rejection(
                    state,
                    action.model_dump(mode="json"),
                    reason="read_line_budget_exceeded",
                    action=action,
                    hypotheses=hypotheses,
                )
        if isinstance(action, RunTests) and action.command not in settings.allowed_test_commands:
            return self._guardrail_rejection(
                state,
                action.model_dump(mode="json"),
                reason="test_command_not_allowlisted",
                action=action,
                hypotheses=hypotheses,
            )

        result = self._dispatch(action)
        evidence = list(state.get("evidence") or [])
        evidence_fingerprints = list(state.get("evidence_fingerprints") or [])
        evidence_item, evidence_fingerprint, made_progress = self._build_evidence(action, result)
        if evidence_fingerprint not in evidence_fingerprints:
            evidence.append(evidence_item)
            evidence = evidence[-settings.agent_max_evidence_items :]
            evidence_fingerprints.append(evidence_fingerprint)
            evidence_fingerprints = evidence_fingerprints[-settings.agent_max_evidence_items :]
        else:
            made_progress = False

        no_progress_count = 0 if made_progress else int(state.get("no_progress_count", 0)) + 1
        observation = evidence_item["summary"]
        history = self._append_history(state, action, status="completed", observation=observation)
        files = dict(state.get("files") or {})
        retrieved_chunks = list(state.get("retrieved_chunks") or [])
        code_graphs = list(state.get("code_graphs") or [])
        diagnostic_test_result = dict(state.get("diagnostic_test_result") or {})
        if isinstance(action, ReadFile):
            files[action.path] = str(result.get("content") or "")
        elif isinstance(action, (SearchCode, FindSymbol, FindReferences)):
            retrieved_chunks = result
        elif isinstance(action, (GetImportGraph, GetCallGraph)):
            code_graphs = [*code_graphs, result][-4:]
        elif isinstance(action, RunTests):
            diagnostic_test_result = result

        outcome_route = (
            "final" if no_progress_count >= settings.agent_max_no_progress_steps else "plan"
        )
        finish_reason = (
            "agent_no_progress_limit_reached" if outcome_route == "final" else None
        )
        return {
            "current_action": action.model_dump(mode="json"),
            "action_outcome": {
                "route": outcome_route,
                "ok": True,
                "observation": observation,
                "evidence_id": evidence_item["id"],
            },
            "action_history": history,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "evidence_fingerprints": evidence_fingerprints,
            "local_action_fingerprints": [*prior_fingerprints, fingerprint][
                -settings.agent_max_action_history :
            ],
            "local_tool_call_count": int(state.get("local_tool_call_count", 0)) + 1,
            "no_progress_count": no_progress_count,
            "finish_reason": finish_reason,
            "files": files,
            "retrieved_chunks": retrieved_chunks,
            "code_graphs": code_graphs,
            "diagnostic_test_result": diagnostic_test_result,
            "diagnosis": self._diagnosis(hypotheses, evidence),
        }

    def _dispatch(self, action: PlanNextAction) -> Any:
        if isinstance(action, SearchCode):
            return self.tools.search_code(action.query, top_k=action.top_k)
        if isinstance(action, ReadFile):
            end_line = action.end_line or (action.start_line + settings.agent_max_read_lines - 1)
            return self.tools.read_file(action.path, action.start_line, end_line)
        if isinstance(action, ListFiles):
            return self.tools.list_files(action.pattern)
        if isinstance(action, FindSymbol):
            return self.tools.find_symbol(action.symbol)
        if isinstance(action, FindReferences):
            return self.tools.find_references(action.symbol)
        if isinstance(action, GetImportGraph):
            return self.tools.get_import_graph(
                action.path,
                direction=action.direction,
                depth=action.depth,
            )
        if isinstance(action, GetCallGraph):
            return self.tools.get_call_graph(
                action.symbol,
                direction=action.direction,
                depth=action.depth,
            )
        if isinstance(action, RunTests):
            return self.tools.run_tests(action.command, phase="diagnostic")
        raise RuntimeError(f"Unsupported local action: {type(action).__name__}")

    def _tool_budget_violation(self, state: FixAgentState) -> str | None:
        if self._deadline_reached(state):
            return "agent_loop_time_budget_exhausted"
        if int(state.get("local_tool_call_count", 0)) >= settings.agent_max_local_tool_calls:
            return "agent_local_tool_call_budget_exhausted"
        return None

    @staticmethod
    def _deadline_reached(state: FixAgentState) -> bool:
        raw_deadline = state.get("agent_loop_deadline_at")
        if not raw_deadline:
            return False
        try:
            deadline = datetime.fromisoformat(raw_deadline)
        except ValueError:
            return True
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= deadline

    def _guardrail_rejection(
        self,
        state: FixAgentState,
        raw_action: dict[str, Any],
        *,
        reason: str,
        action: PlanNextAction | None = None,
        hypotheses: list[str] | None = None,
    ) -> FixAgentState:
        no_progress_count = int(state.get("no_progress_count", 0)) + 1
        route = "final" if no_progress_count >= settings.agent_max_no_progress_steps else "plan"
        history = list(state.get("action_history") or [])
        history.append(
            {
                "sequence": len(history) + 1,
                "action": raw_action.get("action", "InvalidAction"),
                "arguments": self._action_arguments(raw_action),
                "hypothesis": raw_action.get("hypothesis"),
                "rationale": raw_action.get("rationale"),
                "status": "rejected",
                "observation": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        final_hypotheses = hypotheses or list(state.get("hypotheses") or [])
        return {
            "current_action": raw_action,
            "action_outcome": {"route": route, "ok": False, "guardrail": reason},
            "action_history": history[-settings.agent_max_action_history :],
            "hypotheses": final_hypotheses,
            "no_progress_count": no_progress_count,
            "finish_reason": reason if route == "final" else None,
            "diagnosis": self._diagnosis(final_hypotheses, state.get("evidence") or []),
        }

    def _forced_finish(
        self,
        state: FixAgentState,
        action: PlanNextAction,
        reason: str,
        hypotheses: list[str],
    ) -> FixAgentState:
        history = self._append_history(state, action, status="rejected", observation=reason)
        return {
            "current_action": action.model_dump(mode="json"),
            "action_outcome": {"route": "final", "ok": False, "guardrail": reason},
            "action_history": history,
            "hypotheses": hypotheses,
            "finish_reason": reason,
            "diagnosis": self._diagnosis(hypotheses, state.get("evidence") or []),
        }

    def _append_history(
        self,
        state: FixAgentState,
        action: PlanNextAction,
        *,
        status: str,
        observation: str,
    ) -> list[dict[str, Any]]:
        history = list(state.get("action_history") or [])
        dumped = action.model_dump(mode="json")
        history.append(
            {
                "sequence": len(history) + 1,
                "action": action.action,
                "arguments": self._action_arguments(dumped),
                "hypothesis": action.hypothesis,
                "rationale": action.rationale,
                "fingerprint": action_fingerprint(action),
                "status": status,
                "observation": observation[:4_000],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return history[-settings.agent_max_action_history :]

    @staticmethod
    def _action_arguments(raw_action: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in raw_action.items()
            if key not in {"action", "hypothesis", "rationale"}
        }

    def _build_evidence(
        self,
        action: PlanNextAction,
        result: Any,
    ) -> tuple[dict[str, Any], str, bool]:
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        summary = self._observation_summary(action, result)
        item = {
            "id": fingerprint[:16],
            "action": action.action,
            "summary": summary,
            "result_fingerprint": fingerprint,
        }
        made_progress = bool(result)
        if isinstance(result, dict):
            made_progress = bool(
                result.get("content")
                or result.get("tests_ran")
                or result.get("nodes")
                or result.get("edges")
            )
        return item, fingerprint, made_progress

    @staticmethod
    def _observation_summary(action: PlanNextAction, result: Any) -> str:
        if isinstance(action, ReadFile) and isinstance(result, dict):
            content = str(result.get("content") or "")
            return (
                f"Read {action.path}:{action.start_line}-{action.end_line or 'bounded'} "
                f"({len(content)} chars, sha256={hashlib.sha256(content.encode()).hexdigest()[:12]})."
            )
        if isinstance(action, RunTests) and isinstance(result, dict):
            return (
                f"Diagnostic tests command={result.get('command')!r}, "
                f"tests_ran={bool(result.get('tests_ran'))}, "
                f"exit_code={result.get('exit_code')}, passed={bool(result.get('passed'))}."
            )
        if isinstance(action, (GetImportGraph, GetCallGraph)) and isinstance(result, dict):
            relation = result.get("relation", "relations")
            return (
                f"{action.action} returned {len(result.get('nodes') or [])} static-navigation "
                f"node(s) and {len(result.get('edges') or [])} {relation} candidate edge(s)."
            )
        if isinstance(result, list):
            paths: list[str] = []
            for item in result[:8]:
                path = item.get("file_path") if isinstance(item, dict) else item
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
            return f"{action.action} returned {len(result)} result(s): {', '.join(paths) or 'no paths'}."
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        return f"{action.action} returned: {serialized[:1_000]}"

    @staticmethod
    def _append_bounded_unique(items: list[str], value: str, *, limit: int) -> list[str]:
        if value not in items:
            items.append(value)
        return items[-limit:]

    @staticmethod
    def _diagnosis(hypotheses: list[str], evidence: list[dict[str, Any]]) -> str:
        hypothesis_text = "\n".join(f"- {item}" for item in hypotheses[-8:]) or "- None yet"
        evidence_text = "\n".join(
            f"- [{item.get('id')}] {item.get('summary')}" for item in evidence[-12:]
        ) or "- None yet"
        return f"Current hypotheses:\n{hypothesis_text}\n\nEvidence:\n{evidence_text}"
