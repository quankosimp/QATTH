import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError

from app.models.product_cv import ProductCvVersion
from app.services.product_cv import ProductCvService
from app.services.product_interview import ProductInterviewService


class _MigrationOp:
    def __init__(self, connection) -> None:
        self.connection = connection

    def get_bind(self):
        return self.connection

    def execute(self, statement: str) -> None:
        self.connection.exec_driver_sql(statement)


def _domain_history_migration():
    path = Path("migrations/versions/20260715_0032_immutable_domain_histories.py")
    spec = importlib.util.spec_from_file_location("immutable_domain_histories", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_domain_history_update_guards_allow_privacy_deletion() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE product_cv_versions ("
            "id TEXT PRIMARY KEY, cv_id TEXT, user_id TEXT, source_file_id TEXT, version INTEGER, "
            "schema_version TEXT, content TEXT, checksum TEXT, created_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE product_interview_events (id TEXT PRIMARY KEY, event_type TEXT, text TEXT)"
        )
        migration = _domain_history_migration()
        migration.op = _MigrationOp(connection)
        migration.upgrade()
        connection.exec_driver_sql(
            "INSERT INTO product_cv_versions VALUES "
            "('cvv-1', 'cv-1', 'user-1', 'file-1', 1, 'v1', '{}', 'abc', '2026-07-15')"
        )
        connection.exec_driver_sql(
            "INSERT INTO product_interview_events VALUES ('event-1', 'transcript', 'original')"
        )

        with pytest.raises(DatabaseError, match="domain history is immutable"):
            connection.exec_driver_sql("UPDATE product_cv_versions SET checksum = 'changed' WHERE id = 'cvv-1'")
        with pytest.raises(DatabaseError, match="domain history is immutable"):
            connection.exec_driver_sql("UPDATE product_interview_events SET text = 'changed' WHERE id = 'event-1'")

        connection.exec_driver_sql("DELETE FROM product_cv_versions WHERE id = 'cvv-1'")
        connection.exec_driver_sql("DELETE FROM product_interview_events WHERE id = 'event-1'")


def test_cv_confirm_serializes_scan_and_parent_cv() -> None:
    constraints = {constraint.name for constraint in ProductCvVersion.__table__.constraints}
    source = inspect.getsource(ProductCvService.confirm)

    assert "uq_product_cv_version_source_scan" in constraints
    assert ".with_for_update()" in source
    assert "_cv(current, scan.cv_id, lock=True)" in source


def test_interview_mutations_use_consistent_aggregate_locks() -> None:
    consume = inspect.getsource(ProductInterviewService.consume_realtime_token)
    record = inspect.getsource(ProductInterviewService.record_event)

    assert consume.index("select(ProductInterview)") < consume.index("select(InterviewRealtimeToken)")
    assert record.index("select(ProductInterview)") < record.index("if client_event_id:")
    for method in (
        ProductInterviewService.end,
        ProductInterviewService.cancel,
        ProductInterviewService.retry_evaluation,
    ):
        assert "_locked_interview" in inspect.getsource(method)
