from app.core.worker_health import active_worker_count, worker_heartbeat_pattern
from app.workers.rq_worker import ObservableWorker
from rq import Worker


class FakeRedis:
    def __init__(self, keys):
        self.keys = keys
        self.scan = None

    def scan_iter(self, **kwargs):
        self.scan = kwargs
        yield from self.keys


def test_active_worker_count_uses_scoped_heartbeat_keys():
    redis = FakeRedis([b"worker-1", b"worker-2"])

    assert active_worker_count(redis, "codemate:workers") == 2
    assert redis.scan == {"match": "codemate:workers:*", "count": 100}
    assert worker_heartbeat_pattern("codemate:workers") == "codemate:workers:*"


def test_observable_worker_publishes_expiring_heartbeat(monkeypatch):
    writes = []

    class Connection:
        def set(self, *args, **kwargs):
            writes.append((args, kwargs))

    worker = object.__new__(ObservableWorker)
    worker.connection = Connection()
    worker.liveness_key = "codemate:workers:test"
    worker.liveness_ttl = 20
    monkeypatch.setattr(Worker, "heartbeat", lambda *_args, **_kwargs: "sent")

    assert worker.heartbeat() == "sent"
    assert writes[0][0][0] == "codemate:workers:test"
    assert writes[0][1] == {"ex": 20}
