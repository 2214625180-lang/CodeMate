import json
from typing import Any

from pydantic import BaseModel, Field, model_validator


class MCPToolCallRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_arguments(self):
        if len(json.dumps(self.arguments, ensure_ascii=False, default=str)) > 100_000:
            raise ValueError("MCP tool arguments must not exceed 100000 characters")
        return self

