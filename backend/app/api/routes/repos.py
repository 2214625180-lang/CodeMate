from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.queue import enqueue_agent_run, enqueue_repository_index
from app.schemas.ci import CIConfigRead
from app.schemas.chat import ChatRequest, MultiRepoChatRequest
from app.schemas.files import CodeFileRead, FileContentRead
from app.schemas.memory import RepoMemoryRead
from app.schemas.repos import RepositoryCreate, RepositoryRead, RepositoryStatusRead
from app.schemas.reviews import ReviewRequest, ReviewResponse
from app.schemas.runs import FixRequest, FixResponse
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService
from app.services.ci_service import CIService
from app.services.file_service import FileService
from app.services.repo_memory_service import RepoMemoryService
from app.services.repo_service import RepoService
from app.services.review_service import ReviewService

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
def create_repo(payload: RepositoryCreate, db: Session = Depends(get_db)):
    service = RepoService(db)
    try:
        repository = service.create(payload.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        enqueue_repository_index(repository.id, full=True)
    except RedisError as exc:
        repository.status = "failed"
        repository.error_message = f"Failed to enqueue index job: {exc}"
        db.add(repository)
        db.commit()
        db.refresh(repository)

    return repository


@router.get("", response_model=list[RepositoryRead])
def list_repos(db: Session = Depends(get_db)):
    return RepoService(db).list()


@router.post("/chat")
def chat_across_repos(payload: MultiRepoChatRequest, db: Session = Depends(get_db)):
    service = RepoService(db)
    if payload.repo_ids:
        if len(payload.repo_ids) > settings.multi_repo_max_repos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"At most {settings.multi_repo_max_repos} repositories can be queried.",
            )
        repositories = [service.get(repo_id) for repo_id in payload.repo_ids]
        missing = [
            repo_id
            for repo_id, repository in zip(payload.repo_ids, repositories)
            if repository is None
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository not found: {', '.join(missing)}",
            )
        indexed_repositories = [repository for repository in repositories if repository is not None]
    else:
        indexed_repositories = [
            repository
            for repository in service.list()
            if repository.status == "indexed"
        ][: settings.multi_repo_max_repos]

    not_indexed = [
        repository.name
        for repository in indexed_repositories
        if repository.status != "indexed"
    ]
    if not_indexed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repositories must be indexed first: {', '.join(not_indexed)}",
        )
    if not indexed_repositories:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No indexed repositories are available for multi-repo chat.",
        )

    repo_ids = [repository.id for repository in indexed_repositories]
    return StreamingResponse(
        ChatService(db).stream_multi_repo_chat(repo_ids=repo_ids, question=payload.question),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{repo_id}", response_model=RepositoryRead)
def get_repo(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return repository


@router.get("/{repo_id}/files", response_model=list[CodeFileRead])
def list_repo_files(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return FileService(db).list_files(repo_id)


@router.get("/{repo_id}/files/content", response_model=FileContentRead)
def get_repo_file_content(
    repo_id: str,
    path: str = Query(..., min_length=1),
    start_line: int | None = Query(default=None, ge=1),
    end_line: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        code_file, safe_start, safe_end, content = FileService(db).read_content(
            repo_id=repo_id,
            file_path=path,
            start_line=start_line,
            end_line=end_line,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return FileContentRead(
        file_path=path,
        language=code_file.language if code_file else None,
        start_line=safe_start,
        end_line=safe_end,
        content=content,
    )


@router.get("/{repo_id}/memory", response_model=RepoMemoryRead)
def get_repo_memory(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return RepoMemoryService(db).read(repo_id)


@router.post("/{repo_id}/memory/refresh", response_model=RepoMemoryRead)
def refresh_repo_memory(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    try:
        return RepoMemoryService(db).refresh(repo_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{repo_id}/ci", response_model=CIConfigRead)
def inspect_repo_ci(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    try:
        return CIService(db).inspect(repo_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{repo_id}/ci/workflow", response_model=CIConfigRead)
def write_repo_ci_workflow(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    try:
        return CIService(db).write_workflow(repo_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{repo_id}/chat")
def chat_with_repo(repo_id: str, payload: ChatRequest, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    return StreamingResponse(
        ChatService(db).stream_chat(repo_id=repo_id, question=payload.question),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{repo_id}/review", response_model=ReviewResponse)
def review_repo_changes(repo_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    try:
        return ReviewService(db).review(repo_id=repo_id, request=payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{repo_id}/fix", response_model=FixResponse, status_code=status.HTTP_202_ACCEPTED)
def create_fix_run(repo_id: str, payload: FixRequest, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    if repository.status != "indexed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be indexed before running the fix agent",
        )

    try:
        run = AgentService(db).create_fix_run(
            repo_id=repo_id,
            issue=payload.issue,
            test_command=payload.test_command,
            delegated_identity_id=payload.delegated_identity_id,
            delegation_token=payload.delegation_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        enqueue_agent_run(run.id)
    except RedisError as exc:
        run.status = "failed"
        run.failure_reason = f"Failed to enqueue agent run: {exc}"
        db.add(run)
        db.commit()
        db.refresh(run)

    return FixResponse(run_id=run.id, status=run.status)


@router.post("/{repo_id}/reindex", response_model=RepositoryRead)
def reindex_repo(
    repo_id: str,
    full: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    repository.status = "pending"
    repository.error_message = None
    db.add(repository)
    db.commit()
    db.refresh(repository)

    try:
        enqueue_repository_index(repository.id, full=full)
    except RedisError as exc:
        repository.status = "failed"
        repository.error_message = f"Failed to enqueue reindex job: {exc}"
        db.add(repository)
        db.commit()
        db.refresh(repository)

    return repository


@router.get("/{repo_id}/status", response_model=RepositoryStatusRead)
def get_repo_status(repo_id: str, db: Session = Depends(get_db)):
    repository = RepoService(db).get(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return RepositoryStatusRead(
        id=repository.id,
        status=repository.status,
        error_message=repository.error_message,
        file_count=repository.file_count,
        chunk_count=repository.chunk_count,
    )
