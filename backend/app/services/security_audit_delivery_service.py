import argparse
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.kms import verify_kms
from app.models.security_audit_delivery import SecurityAuditDelivery


class SecurityAuditDeliveryError(RuntimeError):
    pass


class SecurityAuditDeliveryService:
    def __init__(self, db: Session):
        self.db = db

    def enqueue(self, record: dict[str, Any]) -> int:
        sinks = sorted(settings.security_audit_sink_set)
        unsupported = set(sinks) - {"http", "s3"}
        if unsupported:
            raise SecurityAuditDeliveryError(
                f"Unsupported security audit sinks: {', '.join(sorted(unsupported))}"
            )
        if not sinks:
            return 0
        event_id = str(record.get("id") or "").strip()
        if not event_id:
            raise SecurityAuditDeliveryError("Security audit event requires an id")
        serialized = canonical_payload(record)
        digest = hashlib.sha256(serialized).hexdigest()
        for sink in sinks:
            self.db.add(
                SecurityAuditDelivery(
                    event_id=event_id,
                    sink=sink,
                    payload_json=record,
                    payload_sha256=digest,
                    status="pending",
                )
            )
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(func.count())
                .select_from(SecurityAuditDelivery)
                .where(SecurityAuditDelivery.event_id == event_id)
            )
            if existing != len(sinks):
                raise
        return len(sinks)

    def deliver_batch(self, limit: int | None = None) -> dict[str, int]:
        claimed = self._claim_batch(limit or settings.security_audit_delivery_batch_size)
        counts = {"claimed": len(claimed), "delivered": 0, "retry": 0, "dead_letter": 0}
        for delivery_id, lease_token in claimed:
            delivery = self.db.get(SecurityAuditDelivery, delivery_id)
            if delivery is None or delivery.lease_token != lease_token:
                continue
            try:
                receipt = self._deliver(delivery)
                delivery.status = "delivered"
                delivery.delivered_at = datetime.utcnow()
                delivery.remote_receipt_json = receipt
                delivery.last_error = None
                counts["delivered"] += 1
            except Exception as exc:  # noqa: BLE001 - durable retry captures provider errors.
                delivery.last_error = f"{type(exc).__name__}: {exc}"[:4000]
                if delivery.attempt_count >= max(1, settings.security_audit_delivery_max_attempts):
                    delivery.status = "dead_letter"
                    counts["dead_letter"] += 1
                else:
                    delivery.status = "retry"
                    delay = min(3600, 2 ** min(10, delivery.attempt_count))
                    delivery.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
                    counts["retry"] += 1
            delivery.lease_token = None
            delivery.lease_expires_at = None
            delivery.updated_at = datetime.utcnow()
            self.db.add(delivery)
            self.db.commit()
        return counts

    def status(self, *, event_id: str | None = None) -> dict[str, Any]:
        if event_id:
            rows = list(
                self.db.scalars(
                    select(SecurityAuditDelivery).where(
                        SecurityAuditDelivery.event_id == event_id
                    )
                )
            )
            counts: dict[str, int] = {}
            for row in rows:
                counts[row.status] = counts.get(row.status, 0) + 1
            oldest_pending = min(
                (row.created_at for row in rows if row.status != "delivered"),
                default=None,
            )
        else:
            rows = []
            counts = {
                status: count
                for status, count in self.db.execute(
                    select(SecurityAuditDelivery.status, func.count())
                    .group_by(SecurityAuditDelivery.status)
                )
            }
            oldest_pending = self.db.scalar(
                select(func.min(SecurityAuditDelivery.created_at)).where(
                    SecurityAuditDelivery.status != "delivered"
                )
            )
        oldest_age = 0.0
        if oldest_pending:
            oldest_age = max(0.0, (datetime.utcnow() - oldest_pending).total_seconds())
        return {
            "event_id": event_id,
            "configured_sinks": sorted(settings.security_audit_sink_set),
            "counts": counts,
            "oldest_undelivered_seconds": round(oldest_age, 3),
            "deliveries": [self.public_dict(row) for row in rows] if event_id else [],
        }

    def purge_delivered(self) -> int:
        cutoff = datetime.utcnow() - timedelta(
            days=max(30, settings.security_audit_outbox_retention_days)
        )
        result = self.db.execute(
            delete(SecurityAuditDelivery).where(
                SecurityAuditDelivery.status == "delivered",
                SecurityAuditDelivery.delivered_at < cutoff,
            )
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def requeue_dead_letters(self, limit: int = 100) -> int:
        rows = list(
            self.db.scalars(
                select(SecurityAuditDelivery)
                .where(SecurityAuditDelivery.status == "dead_letter")
                .order_by(SecurityAuditDelivery.created_at.asc())
                .limit(max(1, min(limit, 1000)))
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            row.status = "pending"
            row.attempt_count = 0
            row.next_attempt_at = None
            row.lease_token = None
            row.lease_expires_at = None
            row.last_error = None
            row.updated_at = datetime.utcnow()
            self.db.add(row)
        self.db.commit()
        return len(rows)

    @staticmethod
    def public_dict(row: SecurityAuditDelivery) -> dict[str, Any]:
        return {
            "id": row.id,
            "event_id": row.event_id,
            "sink": row.sink,
            "payload_sha256": row.payload_sha256,
            "status": row.status,
            "attempt_count": row.attempt_count,
            "delivered_at": iso(row.delivered_at),
            "remote_receipt": row.remote_receipt_json,
            "last_error": row.last_error,
            "created_at": iso(row.created_at),
        }

    def _claim_batch(self, limit: int) -> list[tuple[str, str]]:
        now = datetime.utcnow()
        rows = list(
            self.db.scalars(
                select(SecurityAuditDelivery)
                .where(
                    or_(
                        SecurityAuditDelivery.status == "pending",
                        (
                            (SecurityAuditDelivery.status == "retry")
                            & or_(
                                SecurityAuditDelivery.next_attempt_at.is_(None),
                                SecurityAuditDelivery.next_attempt_at <= now,
                            )
                        ),
                        (
                            (SecurityAuditDelivery.status == "delivering")
                            & (SecurityAuditDelivery.lease_expires_at < now)
                        ),
                    )
                )
                .order_by(SecurityAuditDelivery.created_at.asc())
                .limit(max(1, limit))
                .with_for_update(skip_locked=True)
            )
        )
        claimed: list[tuple[str, str]] = []
        for row in rows:
            token = uuid.uuid4().hex
            row.status = "delivering"
            row.attempt_count += 1
            row.lease_token = token
            row.lease_expires_at = now + timedelta(
                seconds=max(10, settings.security_audit_delivery_lease_seconds)
            )
            row.updated_at = now
            self.db.add(row)
            claimed.append((row.id, token))
        self.db.commit()
        return claimed

    def _deliver(self, delivery: SecurityAuditDelivery) -> dict[str, Any]:
        payload = canonical_payload(delivery.payload_json)
        actual = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(actual, delivery.payload_sha256):
            raise SecurityAuditDeliveryError("Audit payload integrity check failed")
        if delivery.sink == "http":
            return self._deliver_http(delivery, payload)
        if delivery.sink == "s3":
            return self._deliver_s3(delivery, payload)
        raise SecurityAuditDeliveryError(f"Unsupported sink: {delivery.sink}")

    @staticmethod
    def _deliver_http(delivery: SecurityAuditDelivery, payload: bytes) -> dict[str, Any]:
        url = (settings.security_audit_siem_url or "").strip()
        secret = (settings.security_audit_siem_hmac_secret or "").strip()
        if not url or not secret:
            raise SecurityAuditDeliveryError("SIEM URL and HMAC secret are required")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signed = f"{timestamp}.{delivery.payload_sha256}".encode()
        signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        response = httpx.post(
            url,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": delivery.event_id,
                "X-CodeMate-Event-SHA256": delivery.payload_sha256,
                "X-CodeMate-Timestamp": timestamp,
                "X-CodeMate-Signature": f"sha256={signature}",
            },
            timeout=10,
            follow_redirects=False,
        )
        response.raise_for_status()
        return {
            "status_code": response.status_code,
            "request_id": response.headers.get("x-request-id"),
        }

    @staticmethod
    def _deliver_s3(delivery: SecurityAuditDelivery, payload: bytes) -> dict[str, Any]:
        bucket = (settings.security_audit_s3_bucket or "").strip()
        if not bucket:
            raise SecurityAuditDeliveryError("Security audit S3 bucket is required")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise SecurityAuditDeliveryError("boto3 is required for the S3 audit sink") from exc
        client = boto3.client(
            "s3",
            region_name=settings.aws_region or None,
            endpoint_url=settings.aws_endpoint_url or None,
        )
        created = delivery.created_at.strftime("%Y/%m/%d")
        prefix = settings.security_audit_s3_prefix.strip("/")
        key = f"{prefix}/{created}/{delivery.event_id}.json"
        checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode()
        retain_until = datetime.now(timezone.utc) + timedelta(
            days=max(30, settings.security_audit_s3_retention_days)
        )
        response = client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            ChecksumSHA256=checksum,
            Metadata={"event-sha256": delivery.payload_sha256},
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
        )
        return {
            "bucket": bucket,
            "key": key,
            "version_id": response.get("VersionId"),
            "etag": response.get("ETag"),
            "retention_mode": "COMPLIANCE",
            "retain_until": retain_until.isoformat(),
        }


def canonical_payload(record: dict[str, Any]) -> bytes:
    return json.dumps(record, separators=(",", ":"), sort_keys=True).encode()


def enqueue_security_audit_record(record: dict[str, Any]) -> int:
    db = SessionLocal()
    try:
        return SecurityAuditDeliveryService(db).enqueue(record)
    finally:
        db.close()


def deliver_security_audit_batch() -> dict[str, int]:
    db = SessionLocal()
    try:
        service = SecurityAuditDeliveryService(db)
        result = service.deliver_batch()
        result["purged"] = service.purge_delivered()
        return result
    finally:
        db.close()


def verify_security_integrations() -> dict[str, Any]:
    settings.validate_security_config()
    kms = verify_kms()
    event_id = str(uuid.uuid4())
    record = {
        "id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eventType": "staging_security_integration_probe",
        "outcome": "success",
        "actor": {"provider": "system", "login": "staging-qualification", "role": "admin"},
        "method": "INTERNAL",
        "path": "/staging/qualification",
        "status": 200,
        "reason": None,
        "ip": None,
        "userAgent": "codemate-staging-qualification",
        "metadata": {"kmsProvider": kms["provider"], "kmsKeyId": kms["key_id"]},
    }
    db = SessionLocal()
    try:
        service = SecurityAuditDeliveryService(db)
        service.enqueue(record)
        for _ in range(max(1, len(settings.security_audit_sink_set))):
            result = service.deliver_batch()
            if result["claimed"] == 0:
                break
        status = service.status(event_id=event_id)
    finally:
        db.close()
    if not status["deliveries"] or any(
        item["status"] != "delivered" for item in status["deliveries"]
    ):
        raise SecurityAuditDeliveryError("KMS/SIEM/S3 integration verification did not complete")
    return {"status": "verified", "kms": kms, "audit": status}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the durable security audit delivery outbox")
    parser.add_argument("action", choices=["deliver", "status", "requeue", "verify"])
    args = parser.parse_args()
    if args.action == "deliver":
        result: dict[str, Any] = deliver_security_audit_batch()
    elif args.action == "status":
        db = SessionLocal()
        try:
            result = SecurityAuditDeliveryService(db).status()
        finally:
            db.close()
    elif args.action == "requeue":
        db = SessionLocal()
        try:
            result = {"requeued": SecurityAuditDeliveryService(db).requeue_dead_letters()}
        finally:
            db.close()
    else:
        result = verify_security_integrations()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
