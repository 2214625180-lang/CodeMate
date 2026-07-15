import asyncio
import hashlib
import json
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.core.config import settings
from app.llm.base import BaseLLMProvider
from app.mcp.client import MCPClientService, MCPRemoteServerConfig


class MCPToolRouter:
    """Plan and execute MCP calls while keeping authorization outside the model."""

    def __init__(
        self,
        *,
        client: MCPClientService,
        llm: BaseLLMProvider,
        max_catalog_tools: int | None = None,
        authorize: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.client = client
        self.llm = llm
        self.max_catalog_tools = max(
            1,
            max_catalog_tools or settings.mcp_tool_router_max_catalog_tools,
        )
        self.authorize = authorize

    def discover_catalog(self) -> dict[str, Any]:
        return asyncio.run(self._discover_catalog())

    def idempotency_mode(self, server_name: str) -> str:
        resolver = getattr(self.client, "idempotency_mode", None)
        return str(resolver(server_name)) if callable(resolver) else "none"

    async def _discover_catalog(self) -> dict[str, Any]:
        servers = [
            server
            for server in self.client.servers
            if server.enabled and server.allowed_tools
        ]
        if not servers:
            return {"tools": [], "errors": []}

        results = await asyncio.gather(
            *(self.client.list_tools(server.name) for server in servers),
            return_exceptions=True,
        )
        catalog: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for server, result in zip(servers, results):
            if isinstance(result, BaseException):
                errors.append({"server": server.name, "error": str(result)})
                continue
            for tool in result:
                if tool["name"] not in server.allowed_tools:
                    continue
                input_schema = tool.get("input_schema") or {"type": "object"}
                if len(json.dumps(input_schema, ensure_ascii=False, default=str)) > 20_000:
                    errors.append(
                        {
                            "server": server.name,
                            "error": f"Tool schema too large: {tool['name']}",
                        }
                    )
                    continue
                catalog.append(self._catalog_entry(server, tool, input_schema))
                if len(catalog) >= self.max_catalog_tools:
                    return {"tools": catalog, "errors": errors, "truncated": True}
        return {"tools": catalog, "errors": errors, "truncated": False}

    def plan(
        self,
        *,
        issue: str,
        repo_id: str,
        diagnosis: str,
        catalog: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        remaining_calls: int,
    ) -> dict[str, Any]:
        if remaining_calls <= 0 or not any(
            tool["policy"] in {"auto", "approval_required"} for tool in catalog
        ):
            return {
                "calls": [],
                "approval_requests": [],
                "rejected": [],
                "planner_calls": [],
            }

        proposed_calls = self.llm.plan_mcp_tools(
            issue=issue,
            repo_id=repo_id,
            diagnosis=diagnosis,
            tools=catalog,
            observations=observations,
            max_calls=remaining_calls,
        )
        return self.validate_plan(
            proposed_calls=proposed_calls,
            catalog=catalog,
            remaining_calls=remaining_calls,
            prior_observations=observations,
        )

    def validate_plan(
        self,
        *,
        proposed_calls: list[dict[str, Any]],
        catalog: list[dict[str, Any]],
        remaining_calls: int,
        prior_observations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        by_name = {tool["qualified_name"]: tool for tool in catalog}
        accepted: list[dict[str, Any]] = []
        approval_requests: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen: set[str] = {
            call_fingerprint(
                str(observation.get("qualified_name") or ""),
                observation.get("arguments") or {},
            )
            for observation in (prior_observations or [])
            if isinstance(observation, dict) and observation.get("qualified_name")
        }

        for proposed in proposed_calls[:20]:
            qualified_name = proposed.get("tool")
            arguments = proposed.get("arguments")
            if not isinstance(qualified_name, str) or not isinstance(arguments, dict):
                rejected.append(
                    {"tool": str(qualified_name or "unknown"), "reason": "invalid_plan_shape"}
                )
                continue
            catalog_tool = by_name.get(qualified_name)
            if catalog_tool is None:
                rejected.append({"tool": qualified_name, "reason": "tool_not_in_catalog"})
                continue
            policy = catalog_tool["policy"]
            if policy == "deny":
                rejected.append({"tool": qualified_name, "reason": policy})
                continue
            fingerprint = call_fingerprint(qualified_name, arguments)
            if fingerprint in seen:
                rejected.append({"tool": qualified_name, "reason": "duplicate_call"})
                continue
            schema_error = validate_tool_arguments(catalog_tool["input_schema"], arguments)
            if schema_error:
                rejected.append(
                    {
                        "tool": qualified_name,
                        "reason": "schema_validation_failed",
                        "detail": schema_error,
                    }
                )
                continue
            if len(accepted) + len(approval_requests) >= remaining_calls:
                rejected.append({"tool": qualified_name, "reason": "call_budget_exhausted"})
                continue
            seen.add(fingerprint)
            normalized_call = {
                "qualified_name": qualified_name,
                "server": catalog_tool["server"],
                "tool": catalog_tool["name"],
                "arguments": arguments,
            }
            if policy == "approval_required":
                approval_requests.append(normalized_call)
            elif policy == "auto":
                accepted.append(normalized_call)
            else:
                rejected.append({"tool": qualified_name, "reason": "invalid_policy"})

        return {
            "calls": accepted,
            "approval_requests": approval_requests,
            "rejected": rejected,
            "planner_calls": proposed_calls[:20],
        }

    def execute(
        self,
        *,
        call: dict[str, Any],
        catalog: list[dict[str, Any]],
        idempotency_key: str | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        validation = self.validate_plan(
            proposed_calls=[
                {
                    "tool": call.get("qualified_name"),
                    "arguments": call.get("arguments"),
                }
            ],
            catalog=catalog,
            remaining_calls=1,
        )
        if not validation["calls"]:
            if validation["approval_requests"]:
                rejection = {
                    "tool": call.get("qualified_name"),
                    "reason": "approval_required",
                }
            else:
                rejection = validation["rejected"][0]
            return {
                "ok": False,
                "qualified_name": call.get("qualified_name"),
                "policy_rejection": rejection,
            }
        validated = validation["calls"][0]
        if self.authorize:
            self.authorize(validated["server"], validated["tool"], "execute")
        execution_kwargs = {}
        if idempotency_key or execution_id:
            execution_kwargs = {
                "idempotency_key": idempotency_key,
                "execution_id": execution_id,
            }
        result = asyncio.run(
            self.client.call_tool(
                validated["server"],
                validated["tool"],
                validated["arguments"],
                **execution_kwargs,
            )
        )
        return {
            "ok": not bool(result.get("isError")),
            "qualified_name": validated["qualified_name"],
            "arguments": validated["arguments"],
            "result": result,
        }

    def execute_approved(
        self,
        *,
        qualified_name: str,
        arguments: dict[str, Any],
        expected_arguments_hash: str,
        catalog: list[dict[str, Any]],
        idempotency_key: str | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        catalog_tool = next(
            (tool for tool in catalog if tool.get("qualified_name") == qualified_name),
            None,
        )
        if catalog_tool is None:
            return {
                "ok": False,
                "qualified_name": qualified_name,
                "error": "approved_tool_not_in_current_catalog",
            }
        if catalog_tool.get("policy") != "approval_required":
            return {
                "ok": False,
                "qualified_name": qualified_name,
                "error": "approval_policy_changed",
            }
        if sha256_arguments(arguments) != expected_arguments_hash:
            return {
                "ok": False,
                "qualified_name": qualified_name,
                "error": "approved_arguments_hash_mismatch",
            }
        schema_error = validate_tool_arguments(catalog_tool["input_schema"], arguments)
        if schema_error:
            return {
                "ok": False,
                "qualified_name": qualified_name,
                "error": "approved_arguments_no_longer_valid",
                "detail": schema_error,
            }
        if self.authorize:
            self.authorize(
                str(catalog_tool["server"]),
                str(catalog_tool["name"]),
                "execute",
            )
        execution_kwargs = {}
        if idempotency_key or execution_id:
            execution_kwargs = {
                "idempotency_key": idempotency_key,
                "execution_id": execution_id,
            }
        result = asyncio.run(
            self.client.call_tool(
                str(catalog_tool["server"]),
                str(catalog_tool["name"]),
                arguments,
                **execution_kwargs,
            )
        )
        return {
            "ok": not bool(result.get("isError")),
            "qualified_name": qualified_name,
            "arguments": arguments,
            "result": result,
            "approved": True,
        }

    @staticmethod
    def _catalog_entry(
        server: MCPRemoteServerConfig,
        tool: dict[str, Any],
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = str(tool["name"])
        return {
            "qualified_name": f"{server.name}.{tool_name}",
            "server": server.name,
            "name": tool_name,
            "description": tool.get("description") or "",
            "input_schema": input_schema,
            "annotations": tool.get("annotations"),
            "policy": server.tool_policies.get(tool_name, "deny"),
        }


def validate_tool_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    external_ref = find_external_ref(schema)
    if external_ref:
        return f"external schema references are not allowed: {external_ref}"
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except SchemaError as exc:
        return f"invalid tool schema: {exc.message}"
    errors = sorted(validator.iter_errors(arguments), key=lambda error: list(error.path))
    if not errors:
        return None
    first = errors[0]
    location = ".".join(str(part) for part in first.path)
    return f"{location + ': ' if location else ''}{first.message}"[:1000]


def find_external_ref(value: Any) -> str | None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            return ref
        for item in value.values():
            found = find_external_ref(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_external_ref(item)
            if found:
                return found
    return None


def call_fingerprint(qualified_name: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        [qualified_name, arguments],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def sha256_arguments(arguments: dict[str, Any]) -> str:
    serialized = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
