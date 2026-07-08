from redis import Redis
from rq import Queue

from app.core.config import settings
from app.workers.jobs import evaluation_run_job, index_repository_job, run_agent_job


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.redis_url)


def get_index_queue() -> Queue:
    return Queue(settings.rq_queue_name, connection=get_redis_connection())


def enqueue_repository_index(repo_id: str, *, full: bool = False) -> str:
    job = get_index_queue().enqueue(index_repository_job, repo_id, full, job_timeout=600)
    return job.id


def enqueue_agent_run(run_id: str) -> str:
    job = get_index_queue().enqueue(run_agent_job, run_id, job_timeout=900)
    return job.id


def enqueue_evaluation_run(evaluation_run_id: str) -> str:
    job = get_index_queue().enqueue(evaluation_run_job, evaluation_run_id, job_timeout=3600)
    return job.id
