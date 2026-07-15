from alembic.config import Config
from alembic.script import ScriptDirectory

from app.api.v1.health import REQUIRED_DATABASE_REVISION


def test_runtime_schema_gate_matches_single_alembic_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == [REQUIRED_DATABASE_REVISION]
