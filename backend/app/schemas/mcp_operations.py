from typing import Literal

from pydantic import BaseModel, Field


class MCPCircuitControlRequest(BaseModel):
    action: Literal["open", "close", "reset"]
    expected_version: int = Field(ge=1)


class MCPProbeResponse(BaseModel):
    server_name: str | None
    job_id: str
