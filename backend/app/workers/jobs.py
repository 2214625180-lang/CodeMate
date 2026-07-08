from app.core.database import SessionLocal
from app.services.agent_service import AgentService
from app.services.evaluation_service import EvaluationService
from app.services.index_service import IndexService


def index_repository_job(repo_id: str, full: bool = False) -> None:
    db = SessionLocal()
    try:
        IndexService(db).index_repository(repo_id, full=full)
    finally:
        db.close()


def run_agent_job(run_id: str) -> None:
    db = SessionLocal()
    try:
        AgentService(db).run_fix(run_id)
    finally:
        db.close()


def evaluation_run_job(evaluation_run_id: str) -> None:
    db = SessionLocal()
    try:
        service = EvaluationService(db)
        try:
            service.execute_run(evaluation_run_id)
        except Exception as exc:  # noqa: BLE001 - keep failed eval visible in UI.
            service.fail_run(evaluation_run_id, str(exc))
            raise
    finally:
        db.close()
