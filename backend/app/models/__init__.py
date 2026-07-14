"""SQLAlchemy model registry.

Import domain model modules from Alembic or application startup so every table is
registered on the shared metadata without coupling domain services together.
"""

from app.models.foundation import IdempotencyRecord, OutboxEvent

__all__ = ["IdempotencyRecord", "OutboxEvent"]
