import os
import time

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP(
    "CodeMate Production Evidence MCP",
    host="0.0.0.0",
    port=int(os.getenv("MOCK_MCP_PORT", "8765")),
    stateless_http=True,
    json_response=True,
)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def echo(value: str, delay_ms: int = 0, fail: bool = False) -> dict[str, object]:
    """Deterministic tool used by real-transport integration and load tests."""

    if delay_ms:
        time.sleep(min(delay_ms, 5000) / 1000)
    if fail:
        raise RuntimeError("injected MCP failure")
    return {"value": value, "served_at_ns": time.time_ns()}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
