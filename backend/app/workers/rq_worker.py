import time

from redis import Redis
from rq import Connection, Queue, Worker

from app.core.config import settings


class ObservableWorker(Worker):
    def __init__(self, *args, heartbeat_prefix: str, heartbeat_ttl: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.liveness_key = f"{heartbeat_prefix}:{self.name}"
        self.liveness_ttl = heartbeat_ttl

    def heartbeat(self, timeout=None, pipeline=None):
        result = super().heartbeat(timeout=timeout, pipeline=pipeline)
        self.connection.set(self.liveness_key, str(time.time()), ex=self.liveness_ttl)
        return result

    def register_death(self):
        self.connection.delete(self.liveness_key)
        return super().register_death()


def main() -> None:
    settings.validate_security_config()
    redis_connection = Redis.from_url(settings.redis_url)
    with Connection(redis_connection):
        interval = settings.rq_worker_heartbeat_interval_seconds
        worker = ObservableWorker(
            [Queue(settings.rq_queue_name)],
            heartbeat_prefix=settings.rq_worker_heartbeat_prefix,
            heartbeat_ttl=settings.rq_worker_heartbeat_ttl_seconds,
            default_worker_ttl=interval + 15,
            job_monitoring_interval=interval,
        )
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
