from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.agent_step import AgentStep


class AgentStepService:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        *,
        run_id: str,
        step_type: str,
        tool_name: str | None = None,
        input_json: dict | list | None = None,
        output_json: dict | list | None = None,
        duration_ms: int | None = None,
    ) -> AgentStep:
        step = AgentStep(
            run_id=run_id,
            step_type=step_type,
            tool_name=tool_name,
            input_json=input_json,
            output_json=output_json,
            duration_ms=duration_ms,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)
        return step

    def record_tool(self, *, run_id: str, tool_name: str, input_json: dict, fn):
        start = perf_counter()
        self.record(
            run_id=run_id,
            step_type="tool_call",
            tool_name=tool_name,
            input_json=input_json,
        )
        try:
            output = fn()
        except Exception as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            self.record(
                run_id=run_id,
                step_type="tool_result",
                tool_name=tool_name,
                output_json={"ok": False, "error": str(exc)},
                duration_ms=duration_ms,
            )
            raise

        duration_ms = int((perf_counter() - start) * 1000)
        self.record(
            run_id=run_id,
            step_type="tool_result",
            tool_name=tool_name,
            output_json=_jsonable(output),
            duration_ms=duration_ms,
        )
        return output


def _jsonable(value: Any):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return str(value)
