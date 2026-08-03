import hashlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.security_audit_delivery import SecurityAuditDelivery
from app.services.security_audit_delivery_service import SecurityAuditDeliveryService


def audit_record(event_id="event-1"):
    return {
        "id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eventType": "test_event",
        "outcome": "success",
        "actor": {"provider": "test", "login": "alice", "role": "admin"},
        "metadata": {},
    }


def test_outbox_delivers_each_sink_idempotently(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(settings, "security_audit_sinks", "http,s3")
    service = SecurityAuditDeliveryService(db)
    assert service.enqueue(audit_record()) == 2
    assert service.enqueue(audit_record()) == 2
    monkeypatch.setattr(
        service,
        "_deliver",
        lambda row: {"sink": row.sink, "receipt": f"receipt-{row.sink}"},
    )

    result = service.deliver_batch()
    status = service.status(event_id="event-1")

    assert result == {"claimed": 2, "delivered": 2, "retry": 0, "dead_letter": 0}
    assert {item["sink"] for item in status["deliveries"]} == {"http", "s3"}
    assert all(item["status"] == "delivered" for item in status["deliveries"])
    for row in db.query(SecurityAuditDelivery).all():
        row.delivered_at = datetime.now(timezone.utc) - timedelta(days=120)
    db.commit()
    monkeypatch.setattr(settings, "security_audit_outbox_retention_days", 90)
    assert service.purge_delivered() == 2
    db.close()


def test_outbox_dead_letters_after_bounded_attempts(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit-dead.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(settings, "security_audit_sinks", "http")
    monkeypatch.setattr(settings, "security_audit_delivery_max_attempts", 1)
    service = SecurityAuditDeliveryService(db)
    service.enqueue(audit_record("event-dead"))

    def fail(_row):
        raise RuntimeError("SIEM unavailable")

    monkeypatch.setattr(service, "_deliver", fail)
    result = service.deliver_batch()
    delivery = service.status(event_id="event-dead")["deliveries"][0]

    assert result["dead_letter"] == 1
    assert delivery["status"] == "dead_letter"
    assert "SIEM unavailable" in delivery["last_error"]
    assert service.requeue_dead_letters() == 1
    requeued = service.status(event_id="event-dead")["deliveries"][0]
    assert requeued["status"] == "pending"
    assert requeued["attempt_count"] == 0
    db.close()


def test_http_signature_and_s3_object_lock_receipts(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit-sinks.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(settings, "security_audit_sinks", "http,s3")
    monkeypatch.setattr(settings, "security_audit_siem_url", "https://siem.example/events")
    monkeypatch.setattr(settings, "security_audit_siem_hmac_secret", "s" * 32)
    monkeypatch.setattr(settings, "security_audit_s3_bucket", "audit-bucket")
    monkeypatch.setattr(settings, "security_audit_s3_prefix", "events")
    monkeypatch.setattr(settings, "security_audit_s3_retention_days", 365)
    monkeypatch.setattr(settings, "aws_region", "ap-southeast-1")
    monkeypatch.setattr(settings, "aws_endpoint_url", None)
    captured_http = {}
    captured_s3 = {}

    class Response:
        status_code = 202
        headers = {"x-request-id": "siem-request"}

        def raise_for_status(self):
            return None

    def post(*args, **kwargs):
        captured_http.update({"args": args, **kwargs})
        return Response()

    class S3Client:
        def put_object(self, **kwargs):
            captured_s3.update(kwargs)
            return {"VersionId": "version-1", "ETag": "etag-1"}

    monkeypatch.setattr("app.services.security_audit_delivery_service.httpx.post", post)
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *a, **kw: S3Client()))
    service = SecurityAuditDeliveryService(db)
    service.enqueue(audit_record("event-sinks"))

    assert service.deliver_batch()["delivered"] == 2
    assert captured_http["headers"]["X-CodeMate-Signature"].startswith("sha256=")
    assert captured_http["headers"]["X-CodeMate-Event-SHA256"] == hashlib.sha256(
        captured_http["content"]
    ).hexdigest()
    assert captured_s3["ObjectLockMode"] == "COMPLIANCE"
    assert captured_s3["Bucket"] == "audit-bucket"
    assert captured_s3["Key"].endswith("event-sinks.json")
    db.close()
