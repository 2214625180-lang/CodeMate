from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.repository import Repository


def create_repository(db: Session, *, name: str, repo_url: str, owner_id: str) -> Repository:
    repository = Repository(name=name, repo_url=repo_url, owner_id=owner_id, status="pending")
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def list_repositories(db: Session) -> list[Repository]:
    result = db.execute(select(Repository).order_by(Repository.created_at.desc()))
    return list(result.scalars().all())


def list_repositories_for_owner(db: Session, owner_id: str) -> list[Repository]:
    result = db.execute(
        select(Repository)
        .where(Repository.owner_id == owner_id)
        .order_by(Repository.created_at.desc())
    )
    return list(result.scalars().all())


def get_repository(db: Session, repo_id: str) -> Repository | None:
    return db.get(Repository, repo_id)


def get_repository_for_owner(db: Session, repo_id: str, owner_id: str) -> Repository | None:
    return db.execute(
        select(Repository)
        .where(Repository.id == repo_id)
        .where(Repository.owner_id == owner_id)
    ).scalar_one_or_none()
