from redis import Redis
from rq import Connection, Queue, Worker

from app.core.config import settings


def main() -> None:
    redis_connection = Redis.from_url(settings.redis_url)
    with Connection(redis_connection):
        worker = Worker([Queue(settings.rq_queue_name)])
        worker.work()


if __name__ == "__main__":
    main()
