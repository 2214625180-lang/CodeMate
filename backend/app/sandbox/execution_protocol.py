import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=36, max_length=36)
    archive_base64: str = Field(min_length=1)
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    command: str = Field(min_length=1, max_length=255)
    shell_command: str = Field(min_length=1, max_length=4096)
    image: str = Field(min_length=1, max_length=255)
    requested_runtime: Literal["docker", "gvisor", "firecracker"]
    timeout_seconds: int = Field(ge=1, le=3600)

    def binding_hash(self) -> str:
        bound = self.model_dump(exclude={"archive_base64"})
        return hashlib.sha256(
            json.dumps(bound, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str
    backend: Literal["firecracker", "kubernetes"]
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    archive_sha256: str
    workload_subject: str
    attestation: dict[str, str] = Field(default_factory=dict)
