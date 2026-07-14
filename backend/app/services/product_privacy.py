from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import redis
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register all product tables for export/deletion traversal
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser
from app.models.db import AuthToken, Base, User
from app.models.identity import AccountStatusEvent, AuthIdentity, UserConsent, UserProductProfile, UserSession
from app.models.product_cv import ProductFileAsset
from app.models.product_privacy import DeletionTombstone, PrivacyArtifact, PrivacyDispatch, PrivacyEvent, PrivacyRequest
from app.schemas.product_privacy import CreateDeletionRequest, PrivacyRequestView, PrivacySignedUrl
from app.services.object_storage import ObjectStorage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductPrivacyService:
    retention_exceptions = [
        "billing_ledger: retained for financial reconciliation and statutory obligations",
        "payment_events: retained until payment dispute and accounting retention expires",
        "security_audit: retained in pseudonymous form for fraud and access investigations",
        "backups: removed through the documented backup lifecycle rather than historical backup mutation",
    ]
    secret_fields = {"password_hash", "token_hash", "token_fingerprint", "download_token_hash", "raw_payload", "claims_snapshot"}

    def __init__(self, db: Session) -> None:
        self.db = db
        self.storage = ObjectStorage()

    def create_export(self, current: ProductCurrentUser, idempotency_key: str) -> PrivacyRequest:
        return self._create_request(current, "export", idempotency_key, {"type": "export"})

    def create_deletion(self, current: ProductCurrentUser, payload: CreateDeletionRequest, idempotency_key: str) -> PrivacyRequest:
        active = self.db.scalar(select(PrivacyRequest).where(PrivacyRequest.user_id == current.id, PrivacyRequest.request_type == "deletion", PrivacyRequest.status.in_(["queued", "processing", "awaiting_retention"])))
        if active is not None:
            if active.idempotency_key == idempotency_key:
                return active
            raise AppError(409, "DELETION_ALREADY_REQUESTED", "An account deletion request is already active")
        request = self._create_request(current, "deletion", idempotency_key, payload.model_dump(mode="json"), reason=payload.reason, publish=False)
        profile = self.db.scalar(select(UserProductProfile).where(UserProductProfile.user_id == current.id).with_for_update())
        if profile is None:
            profile = UserProductProfile(user_id=current.id)
            self.db.add(profile)
            self.db.flush()
        previous_status = profile.account_status
        profile.account_status = "pending_deletion"
        self.db.add(AccountStatusEvent(user_id=current.id, previous_status=previous_status, new_status="pending_deletion", reason=payload.reason or "user_requested_deletion", actor_id=current.id))
        self.db.commit()
        self.publish_dispatch(request.id)
        return request

    def _create_request(self, current: ProductCurrentUser, request_type: str, idempotency_key: str, payload: dict[str, Any], reason: str | None = None, publish: bool = True) -> PrivacyRequest:
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        existing = self.db.scalar(select(PrivacyRequest).where(PrivacyRequest.user_id == current.id, PrivacyRequest.request_type == request_type, PrivacyRequest.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
            return existing
        request = PrivacyRequest(user_id=current.id, request_type=request_type, idempotency_key=idempotency_key, request_hash=request_hash, reason=reason, retention_exceptions=self.retention_exceptions if request_type == "deletion" else [], checkpoints={})
        self.db.add(request)
        self.db.flush()
        self.db.add(PrivacyDispatch(request_id=request.id, payload={"request_id": request.id}))
        self._append_event(request.id, "request.queued", {"type": request_type})
        self.db.commit()
        self.db.refresh(request)
        if publish:
            self.publish_dispatch(request.id)
        return request

    def get(self, current: ProductCurrentUser, request_id: str) -> PrivacyRequest:
        request = self.db.get(PrivacyRequest, request_id)
        if request is None or (current.role != "admin" and request.user_id != current.id):
            raise AppError(404, "PRIVACY_REQUEST_NOT_FOUND", "Privacy request was not found")
        return request

    def view(self, request: PrivacyRequest) -> PrivacyRequestView:
        download = None
        if request.request_type == "export" and request.status == "completed":
            artifact = self.db.scalar(select(PrivacyArtifact).where(PrivacyArtifact.request_id == request.id))
            if artifact is not None and artifact.deleted_at is None and artifact.expires_at > _utcnow():
                raw_token = secrets.token_urlsafe(32)
                ttl = min(int(get_settings().signed_url_ttl_seconds), int((artifact.expires_at - _utcnow()).total_seconds()))
                expires_at = _utcnow() + timedelta(seconds=max(ttl, 1))
                artifact.download_token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                artifact.download_token_expires_at = expires_at
                self.db.commit()
                origin = str(get_settings().public_api_origin).rstrip("/")
                prefix = str(get_settings().api_v1_prefix).rstrip("/")
                download = PrivacySignedUrl(url=origin + prefix + "/privacy/requests/" + request.id + "/download?token=" + quote(raw_token), expires_at=expires_at)
        return PrivacyRequestView(id=request.id, type=request.request_type, status=request.status, download=download, retention_exceptions=request.retention_exceptions or [], requested_at=request.requested_at, completed_at=request.completed_at)

    def download(self, request_id: str, raw_token: str) -> bytes:
        artifact = self.db.scalar(select(PrivacyArtifact).where(PrivacyArtifact.request_id == request_id))
        now = _utcnow()
        if artifact is None or artifact.deleted_at is not None or artifact.expires_at <= now or artifact.download_token_expires_at is None or artifact.download_token_expires_at <= now:
            raise AppError(404, "PRIVACY_EXPORT_NOT_FOUND", "Privacy export is not available")
        if not secrets.compare_digest(artifact.download_token_hash or "", hashlib.sha256(raw_token.encode()).hexdigest()):
            raise AppError(401, "PRIVACY_DOWNLOAD_TOKEN_INVALID", "Privacy export download token is invalid")
        encrypted = self.storage.read(artifact.object_key, int(get_settings().privacy_export_max_bytes))
        if hashlib.sha256(encrypted).hexdigest() != artifact.sha256 or not encrypted.startswith(b"QATTH-EXPORT-V1\0"):
            raise AppError(409, "PRIVACY_EXPORT_CORRUPT", "Privacy export integrity check failed")
        nonce = encrypted[16:28]
        ciphertext = encrypted[28:]
        try:
            return AESGCM(self._encryption_key()).decrypt(nonce, ciphertext, request_id.encode())
        except Exception as exc:
            raise AppError(409, "PRIVACY_EXPORT_DECRYPTION_FAILED", "Privacy export could not be decrypted") from exc

    def publish_dispatch(self, request_id: str) -> bool:
        dispatch = self.db.scalar(select(PrivacyDispatch).where(PrivacyDispatch.request_id == request_id).with_for_update())
        if dispatch is None or dispatch.status == "published":
            return True
        dispatch.attempts += 1
        try:
            from app.workers.tasks import execute_product_privacy_request_task

            execute_product_privacy_request_task.delay(request_id)
        except Exception as exc:
            dispatch.last_error = str(exc)[:1000]
            dispatch.available_at = _utcnow() + timedelta(seconds=min(300, 2 ** min(dispatch.attempts, 8)))
            self.db.commit()
            return False
        dispatch.status = "published"
        dispatch.published_at = _utcnow()
        dispatch.last_error = None
        self.db.commit()
        return True

    def publish_pending_dispatches(self, limit: int = 100) -> int:
        dispatches = list(self.db.scalars(select(PrivacyDispatch).where(PrivacyDispatch.status == "pending", PrivacyDispatch.available_at <= _utcnow()).order_by(PrivacyDispatch.created_at).limit(limit)))
        return sum(1 for item in dispatches if self.publish_dispatch(item.request_id))

    def execute(self, request_id: str) -> None:
        request = self.db.scalar(select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update())
        if request is None or request.status == "completed":
            return
        now = _utcnow()
        if request.status in {"processing", "awaiting_retention"} and request.lease_expires_at is not None and request.lease_expires_at > now:
            return
        request.status = "processing"
        request.started_at = request.started_at or now
        request.attempts += 1
        request.lease_expires_at = now + timedelta(minutes=30)
        request.error = None
        self._checkpoint(request, "started")
        self.db.commit()
        if request.request_type == "export":
            self._execute_export(request)
        else:
            self._execute_deletion(request)

    def _execute_export(self, request: PrivacyRequest) -> None:
        archive = self._export_archive(request.user_id)
        if len(archive) > int(get_settings().privacy_export_max_bytes):
            raise AppError(413, "PRIVACY_EXPORT_TOO_LARGE", "Privacy export exceeds the configured maximum size")
        nonce = os.urandom(12)
        encrypted = b"QATTH-EXPORT-V1\0" + nonce + AESGCM(self._encryption_key()).encrypt(nonce, archive, request.id.encode())
        object_key = "privacy-exports/" + request.user_id + "/" + request.id + ".zip.enc"
        self.storage.put_system(object_key, encrypted, "application/octet-stream")
        expires_at = _utcnow() + timedelta(hours=int(get_settings().privacy_export_ttl_hours))
        artifact = self.db.scalar(select(PrivacyArtifact).where(PrivacyArtifact.request_id == request.id))
        if artifact is None:
            artifact = PrivacyArtifact(request_id=request.id, user_id=request.user_id, object_key=object_key, content_type="application/zip", size_bytes=len(encrypted), sha256=hashlib.sha256(encrypted).hexdigest(), encryption_version="aes-256-gcm-v1", expires_at=expires_at)
            self.db.add(artifact)
        self._checkpoint(request, "artifact_written")
        request.status = "completed"
        request.completed_at = _utcnow()
        request.lease_expires_at = None
        self._append_event(request.id, "request.completed", {"artifact_expires_at": expires_at.isoformat()})
        self.db.commit()

    def _execute_deletion(self, request: PrivacyRequest) -> None:
        user = self.db.scalar(select(User).where(User.id == request.user_id).with_for_update())
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User was not found")
        now = _utcnow()
        self.db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).update({UserSession.revoked_at: now}, synchronize_session=False)
        self.db.query(AuthToken).filter(AuthToken.user_id == user.id, AuthToken.revoked_at.is_(None)).update({AuthToken.revoked_at: now}, synchronize_session=False)
        self._checkpoint(request, "access_revoked")
        self.db.commit()

        object_keys = list(self.db.scalars(select(ProductFileAsset.object_key).where(ProductFileAsset.user_id == user.id, ProductFileAsset.deleted_at.is_(None))))
        object_keys.extend(self.db.scalars(select(PrivacyArtifact.object_key).where(PrivacyArtifact.user_id == user.id, PrivacyArtifact.deleted_at.is_(None))))
        for object_key in sorted(set(object_keys)):
            self.storage.delete(object_key)
        self.db.query(ProductFileAsset).filter(ProductFileAsset.user_id == user.id).update({ProductFileAsset.deleted_at: now}, synchronize_session=False)
        self.db.query(PrivacyArtifact).filter(PrivacyArtifact.user_id == user.id).update({PrivacyArtifact.deleted_at: now}, synchronize_session=False)
        self._checkpoint(request, "objects_deleted")
        self.db.commit()

        manifest = self._purge_domain_rows(user.id)
        self._checkpoint(request, "domain_data_purged")
        self.db.commit()

        self._purge_cache(user.id)
        self._checkpoint(request, "cache_purged")
        self.db.commit()

        subject = hashlib.sha256(("deleted-user:" + user.id).encode()).hexdigest()
        self.db.query(AuthIdentity).filter(AuthIdentity.user_id == user.id).delete(synchronize_session=False)
        profile = self.db.scalar(select(UserProductProfile).where(UserProductProfile.user_id == user.id).with_for_update())
        if profile is not None:
            profile.account_status = "deleted"
            profile.display_name = None
            profile.headline = None
            profile.summary = None
            profile.location = None
            profile.skills = []
            profile.profile_links = []
            profile.job_preferences = {}
        for consent in self.db.scalars(select(UserConsent).where(UserConsent.user_id == user.id)):
            consent.evidence = {"retained_for": "consent_audit", "redacted_at": now.isoformat()}
        legacy_consent = Base.metadata.tables.get("consent_records")
        if legacy_consent is not None and "user_id" in legacy_consent.c:
            redacted_values = {}
            for field in ("evidence", "evidence_json", "metadata_json"):
                if field in legacy_consent.c:
                    redacted_values[field] = {"retained_for": "consent_audit", "redacted_at": now.isoformat()}
            if redacted_values:
                self.db.execute(update(legacy_consent).where(legacy_consent.c.user_id == user.id).values(**redacted_values))
        user.email = "deleted+" + subject[:24] + "@privacy.invalid"
        user.full_name = None
        user.password_hash = ""
        user.is_active = False
        tombstone = self.db.scalar(select(DeletionTombstone).where(DeletionTombstone.request_id == request.id))
        if tombstone is None:
            self.db.add(DeletionTombstone(request_id=request.id, user_id=user.id, pseudonymous_subject=subject, retention_exceptions=self.retention_exceptions, deletion_manifest=manifest, completed_at=now))
        request.status = "awaiting_retention"
        request.retention_exceptions = self.retention_exceptions
        self._checkpoint(request, "retention_recorded")
        self.db.commit()

        request.status = "completed"
        request.completed_at = _utcnow()
        self._checkpoint(request, "completed")
        request.lease_expires_at = None
        self._append_event(request.id, "request.completed", {"retention_exceptions": self.retention_exceptions})
        self.db.commit()

    def _export_archive(self, user_id: str) -> bytes:
        snapshot: dict[str, Any] = {"exported_at": _utcnow().isoformat(), "schema_version": "privacy-export-v1", "tables": {}}
        metadata = Base.metadata
        for table in sorted(metadata.tables.values(), key=lambda item: item.name):
            predicates = []
            for field in ("user_id", "actor_user_id", "reporter_user_id"):
                if field in table.c:
                    predicates.append(table.c[field] == user_id)
            if not predicates:
                continue
            predicate = predicates[0]
            for item in predicates[1:]:
                predicate = predicate | item
            rows = [self._safe_row(dict(row)) for row in self.db.execute(select(table).where(predicate)).mappings()]
            if rows:
                snapshot["tables"][table.name] = rows
        self._add_linked_export(snapshot, "product_cv_drafts", "scan_id", "product_cv_scans")
        self._add_linked_export(snapshot, "product_interview_events", "interview_id", "product_interviews")
        self._add_linked_export(snapshot, "product_job_search_events", "run_id", "product_job_search_runs")
        self._add_linked_export(snapshot, "product_job_search_results", "run_id", "product_job_search_runs")
        self._add_linked_export(snapshot, "product_job_application_events", "application_id", "product_job_applications")
        self._add_linked_export(snapshot, "product_recommendation_matches", "run_id", "product_recommendation_runs")
        self._add_linked_export(snapshot, "product_credit_buckets", "account_id", "product_credit_accounts")
        self._add_linked_export(snapshot, "product_credit_ledger_entries", "account_id", "product_credit_accounts")
        self._add_linked_export(snapshot, "product_credit_reservation_allocations", "reservation_id", "product_credit_reservations")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("profile.json", json.dumps(snapshot, ensure_ascii=False, indent=2, default=self._json_default))
            assets = list(self.db.scalars(select(ProductFileAsset).where(ProductFileAsset.user_id == user_id, ProductFileAsset.upload_status == "uploaded", ProductFileAsset.deleted_at.is_(None))))
            for asset in assets:
                filename = re.sub(r"[^A-Za-z0-9._-]", "_", asset.original_filename) or "document.pdf"
                content = self.storage.read(asset.object_key, asset.declared_size_bytes)
                archive.writestr("files/" + asset.id + "/" + filename, content)
        return output.getvalue()

    def _add_linked_export(self, snapshot: dict[str, Any], child_name: str, foreign_key: str, parent_name: str) -> None:
        tables = snapshot["tables"]
        parent_ids = [row.get("id") for row in tables.get(parent_name, []) if row.get("id")]
        child = Base.metadata.tables.get(child_name)
        if child is None or foreign_key not in child.c or not parent_ids:
            return
        rows = [self._safe_row(dict(row)) for row in self.db.execute(select(child).where(child.c[foreign_key].in_(parent_ids))).mappings()]
        if rows:
            tables[child_name] = rows

    def _purge_domain_rows(self, user_id: str) -> dict[str, int]:
        retained = {
            "users", "audit_logs", "account_status_events", "user_consents", "consent_records",
            "product_credit_accounts", "product_credit_buckets", "product_credit_ledger_entries",
            "product_credit_reservations", "product_credit_reservation_allocations", "product_signup_trial_grants",
            "product_billing_subscriptions", "product_billing_checkout_sessions", "product_billing_commands",
            "product_payment_event_inbox", "product_privacy_requests", "product_privacy_artifacts",
            "product_privacy_dispatches", "product_privacy_events", "product_deletion_tombstones",
            "product_model_configurations", "product_operational_jobs", "product_privileged_commands",
            "product_privileged_audit_events", "product_audit_chain_heads",
        }
        metadata = Base.metadata
        manifest: dict[str, int] = {}
        roots: list[tuple[Any, list[str]]] = []
        for table in metadata.tables.values():
            if table.name in retained or "id" not in table.c:
                continue
            user_columns = [fk.parent for fk in table.foreign_keys if fk.column.table.name == "users" and fk.parent.name in {"user_id", "actor_user_id", "reporter_user_id"}]
            if not user_columns:
                continue
            predicate = user_columns[0] == user_id
            for column in user_columns[1:]:
                predicate = predicate | (column == user_id)
            ids = list(self.db.scalars(select(table.c.id).where(predicate)))
            if ids:
                roots.append((table, ids))
        visited: set[tuple[str, str]] = set()
        for table, ids in roots:
            self._delete_graph(table, ids, retained, manifest, visited)
        for checkout in self.db.execute(select(Base.metadata.tables["product_billing_checkout_sessions"]).where(Base.metadata.tables["product_billing_checkout_sessions"].c.user_id == user_id)).mappings():
            self.db.execute(Base.metadata.tables["product_billing_checkout_sessions"].update().where(Base.metadata.tables["product_billing_checkout_sessions"].c.id == checkout["id"]).values(success_url="about:blank", cancel_url="about:blank", redirect_url=None))
        return manifest

    def _delete_graph(self, table: Any, ids: list[str], retained: set[str], manifest: dict[str, int], visited: set[tuple[str, str]]) -> None:
        pending = [item for item in ids if (table.name, item) not in visited]
        if not pending or table.name in retained:
            return
        for item in pending:
            visited.add((table.name, item))
        for child in Base.metadata.tables.values():
            if child.name in retained or "id" not in child.c:
                continue
            for foreign_key in child.foreign_keys:
                if foreign_key.column.table.name == table.name and foreign_key.column.name == "id":
                    child_ids = list(self.db.scalars(select(child.c.id).where(foreign_key.parent.in_(pending))))
                    if child_ids:
                        self._delete_graph(child, child_ids, retained, manifest, visited)
        result = self.db.execute(delete(table).where(table.c.id.in_(pending)))
        manifest[table.name] = manifest.get(table.name, 0) + int(result.rowcount or 0)

    def _purge_cache(self, user_id: str) -> None:
        settings = get_settings()
        client = redis.Redis.from_url(settings.redis_url, decode_responses=False, socket_connect_timeout=2, socket_timeout=2)
        try:
            keys = list(client.scan_iter(match=settings.redis_key_prefix + ":*" + user_id + "*", count=200))
            if keys:
                client.delete(*keys)
        except redis.RedisError as exc:
            if str(settings.app_env).lower() in {"staging", "production"}:
                raise AppError(503, "PRIVACY_CACHE_PURGE_FAILED", "Privacy cache purge did not complete", retryable=True) from exc

    def cleanup_expired_artifacts(self, limit: int = 100) -> int:
        artifacts = list(self.db.scalars(select(PrivacyArtifact).where(PrivacyArtifact.deleted_at.is_(None), PrivacyArtifact.expires_at <= _utcnow()).order_by(PrivacyArtifact.expires_at).limit(limit)))
        for artifact in artifacts:
            self.storage.delete(artifact.object_key)
            artifact.deleted_at = _utcnow()
            artifact.download_token_hash = None
            artifact.download_token_expires_at = None
        self.db.commit()
        return len(artifacts)

    def _checkpoint(self, request: PrivacyRequest, name: str) -> None:
        checkpoints = dict(request.checkpoints or {})
        checkpoints[name] = _utcnow().isoformat()
        request.checkpoints = checkpoints
        request.lease_expires_at = _utcnow() + timedelta(minutes=30)
        self._append_event(request.id, "checkpoint.completed", {"checkpoint": name})

    def _append_event(self, request_id: str, event_type: str, payload: dict[str, Any]) -> None:
        sequence = self.db.scalar(select(func.max(PrivacyEvent.sequence)).where(PrivacyEvent.request_id == request_id)) or 0
        self.db.add(PrivacyEvent(request_id=request_id, sequence=sequence + 1, event_type=event_type, payload=payload))

    def _encryption_key(self) -> bytes:
        configured = str(get_settings().privacy_export_encryption_key or "")
        if configured:
            try:
                key = base64.urlsafe_b64decode(configured + "=" * (-len(configured) % 4))
            except ValueError as exc:
                raise AppError(500, "PRIVACY_ENCRYPTION_KEY_INVALID", "Privacy export encryption key is invalid") from exc
            if len(key) != 32:
                raise AppError(500, "PRIVACY_ENCRYPTION_KEY_INVALID", "Privacy export encryption key must contain 32 bytes")
            return key
        if str(get_settings().app_env).lower() in {"local", "development", "test"}:
            return hashlib.sha256(b"qatth-local-privacy-export-key").digest()
        raise AppError(500, "PRIVACY_ENCRYPTION_KEY_MISSING", "Privacy export encryption key is required")

    def _safe_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: self._json_value(value) for key, value in row.items() if key not in self.secret_fields}

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bytes):
            return "<binary omitted>"
        return value

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)
