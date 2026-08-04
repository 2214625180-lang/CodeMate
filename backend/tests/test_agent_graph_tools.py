from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.tools import AgentTools
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository


def test_static_navigation_tools_use_existing_index_metadata(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'graphs.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-graphs",
        name="graphs",
        repo_url="https://example.com/graphs.git",
        status="indexed",
    )
    files = [
        CodeFile(
            id="file-main",
            repo_id=repository.id,
            file_path="src/main.py",
            language="python",
            content_hash="main",
            line_count=2,
            size_bytes=50,
            imports=["src.service"],
        ),
        CodeFile(
            id="file-service",
            repo_id=repository.id,
            file_path="src/service.py",
            language="python",
            content_hash="service",
            line_count=2,
            size_bytes=50,
            imports=["src.calculator"],
        ),
        CodeFile(
            id="file-calculator",
            repo_id=repository.id,
            file_path="src/calculator.py",
            language="python",
            content_hash="calculator",
            line_count=2,
            size_bytes=50,
        ),
        CodeFile(
            id="file-client",
            repo_id=repository.id,
            file_path="src/client.py",
            language="python",
            content_hash="client",
            line_count=2,
            size_bytes=50,
        ),
    ]
    chunks = [
        CodeChunk(
            id="chunk-main",
            repo_id=repository.id,
            file_id="file-main",
            file_path="src/main.py",
            language="python",
            symbol_name="run",
            symbol_type="function",
            start_line=1,
            end_line=2,
            content="def run():\n    return calculate_total()\n",
        ),
        CodeChunk(
            id="chunk-calculator",
            repo_id=repository.id,
            file_id="file-calculator",
            file_path="src/calculator.py",
            language="python",
            symbol_name="calculate_total",
            symbol_type="function",
            start_line=1,
            end_line=2,
            content="def calculate_total():\n    return 1\n",
        ),
        CodeChunk(
            id="chunk-client",
            repo_id=repository.id,
            file_id="file-client",
            file_path="src/client.py",
            language="python",
            symbol_name="render",
            symbol_type="function",
            start_line=1,
            end_line=2,
            content="def render():\n    return calculate_total()\n",
        ),
    ]
    run = AgentRun(
        id="run-graphs",
        repo_id=repository.id,
        user_input="Trace calculate_total",
        status="pending",
    )
    db.add_all([repository, *files, *chunks, run])
    db.commit()

    tools = AgentTools(
        db=db,
        run_id=run.id,
        repo_id=repository.id,
        workspace=tmp_path,
        sandbox=object(),  # type: ignore[arg-type]
    )
    import_graph = tools.get_import_graph("src/main.py", direction="imports", depth=2)
    call_graph = tools.get_call_graph("calculate_total", direction="callers", depth=1)

    assert import_graph["kind"] == "static_navigation"
    assert import_graph["relation"] == "imports"
    assert {(edge["from"], edge["to"]) for edge in import_graph["edges"]} == {
        ("src/main.py", "src/service.py"),
        ("src/service.py", "src/calculator.py"),
    }
    assert {
        edge["from"] for edge in call_graph["edges"]
    } == {
        "symbol:src/client.py:1:render",
        "symbol:src/main.py:1:run",
    }
    assert call_graph["kind"] == "static_navigation"
    assert call_graph["relation"] == "call_candidates"
    assert call_graph["supported_languages"] == ["python", "javascript", "typescript", "vue"]
    assert call_graph["limitations"] == [
        "Relations are candidates inferred from indexed chunks and identifier-pattern matching.",
        "Aliases, dynamic dispatch, overloads, re-exports, and cross-language calls are not resolved.",
        "Inspect the referenced source before treating a candidate relation as a dependency.",
    ]
    assert {edge["kind"] for edge in call_graph["edges"]} == {"possible_call"}
    assert {edge["resolution"] for edge in call_graph["edges"]} == {"unresolved"}
    assert {edge["match_method"] for edge in call_graph["edges"]} == {"identifier_pattern"}
    assert {step.tool_name for step in run.steps if step.step_type == "tool_call"} == {
        "get_import_graph",
        "get_call_graph",
    }


def test_static_call_navigation_marks_unresolved_symbols_as_candidates(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'unresolved-symbols.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-unresolved-symbols",
        name="unresolved-symbols",
        repo_url="https://example.com/unresolved-symbols.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-unresolved-symbols",
        repo_id=repository.id,
        user_input="Navigate missing_target",
        status="pending",
    )
    db.add_all([repository, run])
    db.commit()

    tools = AgentTools(
        db=db,
        run_id=run.id,
        repo_id=repository.id,
        workspace=tmp_path,
        sandbox=object(),  # type: ignore[arg-type]
    )

    navigation = tools.get_call_graph("missing_target", direction="callees", depth=1)

    assert navigation["nodes"] == [
        {
            "id": "unresolved_symbol:missing_target",
            "kind": "unresolved_symbol",
            "name": "missing_target",
        }
    ]
    assert navigation["edges"] == []
