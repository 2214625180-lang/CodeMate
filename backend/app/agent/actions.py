import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class AgentAction(BaseModel):
    """Shared, strictly validated fields emitted by the local action planner.

    The model proposes intent; it never receives an untyped escape hatch for a
    shell command or filesystem operation. ``extra='forbid'`` makes prompt or
    provider drift fail closed before any tool is dispatched.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    hypothesis: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    
class SearchCode(AgentAction):
    action: Literal["SearchCode"]
    query: str = Field(min_length=2, max_length=2_000)
    top_k: int = Field(default=6, ge=1, le=12)


class ReadFile(AgentAction):
    action: Literal["ReadFile"]
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ReadFile":
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class ListFiles(AgentAction):
    action: Literal["ListFiles"]
    pattern: str | None = Field(default=None, max_length=500)


class FindSymbol(AgentAction):
    action: Literal["FindSymbol"]
    symbol: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z_$][\w$.:/-]*$")


class FindReferences(AgentAction):
    action: Literal["FindReferences"]
    symbol: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z_$][\w$.:/-]*$")


class GetImportGraph(AgentAction):
    """Navigate imports inferred from indexed source metadata."""

    action: Literal["GetImportGraph"] = Field(
        description="Inspect static import-navigation candidates from the repository index."
    )
    path: str = Field(min_length=1, max_length=500)
    direction: Literal["imports", "importers", "both"] = "both"
    depth: int = Field(default=1, ge=1, le=3)


class GetCallGraph(AgentAction):
    """Navigate heuristic call candidates, not resolved compiler call edges."""

    action: Literal["GetCallGraph"] = Field(
        description=(
            "Inspect heuristic static-navigation candidates. It does not resolve aliases, "
            "dynamic dispatch, overloads, re-exports, or cross-language calls."
        )
    )
    symbol: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z_$][\w$.:/-]*$")
    direction: Literal["callers", "callees", "both"] = "both"
    depth: int = Field(default=1, ge=1, le=3)


class RunTests(AgentAction):
    action: Literal["RunTests"]
    command: str = Field(min_length=1, max_length=500)


class GeneratePatch(AgentAction):
    action: Literal["GeneratePatch"]


class Finish(AgentAction):
    action: Literal["Finish"]
    reason: str = Field(min_length=1, max_length=2_000)


# The discriminator turns model output into one of a finite set of capabilities.
# Adding a tool therefore requires an explicit schema, executor branch and test;
# merely mentioning a new action name in a prompt cannot grant permission.
PlanNextAction = Annotated[
    SearchCode
    | ReadFile
    | ListFiles
    | FindSymbol
    | FindReferences
    | GetImportGraph
    | GetCallGraph
    | RunTests
    | GeneratePatch
    | Finish,
    Field(discriminator="action"),
]
PLAN_NEXT_ACTION_ADAPTER = TypeAdapter(PlanNextAction)

LOCAL_TOOL_ACTIONS = (
    SearchCode,
    ReadFile,
    ListFiles,
    FindSymbol,
    FindReferences,
    GetImportGraph,
    GetCallGraph,
    RunTests,
)


def action_fingerprint(action: PlanNextAction) -> str:
    """Fingerprint execution arguments while excluding mutable reasoning text.

    A model can rephrase its hypothesis or rationale without turning the same
    search/read/test request into a new action and bypassing loop detection.
    """

    payload = action.model_dump(exclude={"hypothesis", "rationale"}, mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def plan_next_action_json_schema() -> dict:
    return PLAN_NEXT_ACTION_ADAPTER.json_schema()
