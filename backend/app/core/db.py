from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    settings = get_settings()
    connect_args: dict[str, object] = {}
    engine_options: dict[str, object] = {
        "pool_pre_ping": True,
    }

    if settings.database_url.startswith("sqlite"):
        Path("data").mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    else:
        engine_options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_pool_overflow,
        )

    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        **engine_options,
    )


engine = _build_engine()
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)


def init_db() -> None:
    settings = get_settings()
    if not settings.auto_create_tables:
        return
    if settings.app_env not in {"local", "test"}:
        raise RuntimeError("Automatic table creation is restricted to local/test environments.")

    import app.models.db  # noqa: F401
    import app.models.foundation  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
