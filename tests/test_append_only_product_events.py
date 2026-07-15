import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError


class _MigrationOp:
    def __init__(self, connection) -> None:
        self.connection = connection

    def get_bind(self):
        return self.connection

    def execute(self, statement: str) -> None:
        self.connection.exec_driver_sql(statement)


def _migration():
    path = Path("migrations/versions/20260715_0033_append_only_product_events.py")
    spec = importlib.util.spec_from_file_location("append_only_product_events", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_application_and_recommendation_histories_reject_updates() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE product_job_application_events ("
            "id TEXT PRIMARY KEY, application_id TEXT, sequence INTEGER, from_status TEXT, "
            "to_status TEXT, actor_type TEXT, actor_user_id TEXT, reason_code TEXT, "
            "metadata_json TEXT, created_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE product_recommendation_feedback ("
            "id TEXT PRIMARY KEY, event_type TEXT, training_eligible INTEGER)"
        )
        migration = _migration()
        migration.op = _MigrationOp(connection)
        migration.upgrade()
        connection.exec_driver_sql(
            "INSERT INTO product_job_application_events VALUES "
            "('event-1', 'application-1', 1, NULL, 'planned', 'user', 'user-1', NULL, '{}', '2026-07-15')"
        )
        connection.exec_driver_sql(
            "INSERT INTO product_recommendation_feedback VALUES ('feedback-1', 'dismissed', 0)"
        )

        with pytest.raises(DatabaseError, match="domain history is immutable"):
            connection.exec_driver_sql(
                "UPDATE product_job_application_events SET to_status = 'accepted' WHERE id = 'event-1'"
            )
        with pytest.raises(DatabaseError, match="domain history is immutable"):
            connection.exec_driver_sql(
                "UPDATE product_recommendation_feedback SET training_eligible = 1 WHERE id = 'feedback-1'"
            )

        connection.exec_driver_sql(
            "UPDATE product_job_application_events SET actor_user_id = NULL WHERE id = 'event-1'"
        )
        connection.exec_driver_sql("DELETE FROM product_job_application_events WHERE id = 'event-1'")
        connection.exec_driver_sql("DELETE FROM product_recommendation_feedback WHERE id = 'feedback-1'")
