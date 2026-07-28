from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.mcp.server import create_mcp_server
from app.services.retrieval_service import RetrievalService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp_server(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "example.py").write_text(
        "def greet(name):\n    return f'Hello {name}'\n\nprint(greet('CodeMate'))\n",
        encoding="utf-8",
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'mcp.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        visible = Repository(
            id="visible-repo",
            name="visible",
            repo_url="https://example.com/visible.git",
            local_path=str(workspace),
            status="indexed",
            language_summary={"python": 1},
            file_count=1,
            chunk_count=1,
        )
        hidden = Repository(
            id="hidden-repo",
            name="hidden",
            repo_url="https://example.com/hidden.git",
            status="indexed",
        )
        code_file = CodeFile(
            id="file-1",
            repo_id=visible.id,
            file_path="example.py",
            language="python",
            content_hash="hash",
            line_count=4,
            size_bytes=72,
        )
        chunk = CodeChunk(
            id="chunk-1",
            repo_id=visible.id,
            file_id=code_file.id,
            file_path=code_file.file_path,
            language="python",
            symbol_name="greet",
            symbol_type="function",
            start_line=1,
            end_line=2,
            content="def greet(name):\n    return f'Hello {name}'",
        )
        db.add_all([visible, hidden, code_file, chunk])
        db.commit()

    monkeypatch.setattr(RetrievalService, "_vector_search", lambda *args, **kwargs: [])
    return create_mcp_server(
        session_factory=session_factory,
        allowed_repo_ids={"visible-repo"},
        max_file_lines=2,
    )


@pytest.mark.anyio
async def test_mcp_lists_only_read_only_scoped_tools(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        tools = (await session.list_tools()).tools
        tool_names = {tool.name for tool in tools}
        repositories = await session.call_tool("list_repositories", {})

    assert tool_names == {
        "get_repo_memory",
        "get_run_status",
        "inspect_ci",
        "list_files",
        "list_repositories",
        "read_file",
        "search_code",
    }
    assert all(tool.annotations and tool.annotations.readOnlyHint is True for tool in tools)
    visible_repositories = repositories.structuredContent["result"]
    assert [repository["id"] for repository in visible_repositories] == ["visible-repo"]
    assert visible_repositories[0]["language_summary"] == {"python": 1}


@pytest.mark.anyio
async def test_mcp_reads_bounded_files_and_searches_code(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        read_result = await session.call_tool(
            "read_file",
            {"repo_id": "visible-repo", "path": "example.py"},
        )
        oversized_result = await session.call_tool(
            "read_file",
            {
                "repo_id": "visible-repo",
                "path": "example.py",
                "start_line": 1,
                "end_line": 3,
            },
        )
        search_result = await session.call_tool(
            "search_code",
            {"repo_id": "visible-repo", "query": "greet", "top_k": 3},
        )

    assert read_result.isError is not True, read_result
    assert read_result.structuredContent["content"] == (
        "def greet(name):\n    return f'Hello {name}'"
    )
    assert read_result.structuredContent["truncated"] is True
    assert oversized_result.isError is True
    assert "limited to 2 lines" in oversized_result.content[0].text
    assert search_result.structuredContent["result"][0]["symbol_name"] == "greet"


@pytest.mark.anyio
async def test_mcp_repository_scope_hides_unapproved_repositories(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool("list_files", {"repo_id": "hidden-repo"})

    assert result.isError is True
    assert "Repository not available" in result.content[0].text
