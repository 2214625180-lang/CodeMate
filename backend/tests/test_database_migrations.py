from alembic import command
import pytest
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401
from app.core import database, migrations
from app.core.config import settings
from app.core.database import Base


def configure_database(tmp_path, monkeypatch, name):
    url = f"sqlite:///{tmp_path / name}"
    engine = create_engine(url)
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(migrations, "engine", engine)
    return engine


def test_fresh_database_upgrade_check_and_downgrade(tmp_path, monkeypatch):
    engine = configure_database(tmp_path, monkeypatch, "fresh.db")

    migrations.upgrade_database()
    current, head = migrations.current_and_head()
    tables = set(inspect(engine).get_table_names())
    assert current == head
    assert {
        "repositories",
        "mcp_tool_executions",
        "mcp_quota_policies",
        "agent_checkpoints",
        "agent_checkpoint_blobs",
        "agent_checkpoint_writes",
    } <= tables

    command.downgrade(migrations.alembic_config(), "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    migrations.upgrade_database()
    assert migrations.require_database_at_head() == head


def test_unversioned_database_requires_explicit_legacy_adoption(tmp_path, monkeypatch):
    engine = configure_database(tmp_path, monkeypatch, "legacy.db")
    Base.metadata.create_all(engine)
    with pytest.raises(migrations.UnversionedDatabaseError, match="adopt-legacy"):
        migrations.upgrade_database()
    with pytest.raises(migrations.UnversionedDatabaseError, match="requires --yes"):
        migrations.adopt_legacy_database(confirmed=False)

    revision = migrations.adopt_legacy_database(confirmed=True)
    assert revision == migrations.current_and_head()[1]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1
