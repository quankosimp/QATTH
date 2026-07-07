from sqlalchemy.orm import Session

from app.models.db import AuditLog


class AuditService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        actor_user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=metadata,
            )
        )
