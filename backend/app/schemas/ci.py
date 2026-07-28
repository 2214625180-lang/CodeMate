from pydantic import BaseModel


class CIConfigRead(BaseModel):
    repo_id: str
    detected_configs: list[str]
    ecosystem: list[str]
    package_manager: str | None
    test_commands: list[str]
    workflow_path: str
    workflow_yaml: str
    applied_path: str | None = None
