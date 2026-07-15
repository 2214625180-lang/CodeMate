import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.core.config import settings
from app.core.database import Base, engine, ensure_phase2_columns


class UnversionedDatabaseError(RuntimeError):
    pass


class DatabaseRevisionError(RuntimeError):
    pass


def alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return config


def upgrade_database(revision: str = "head") -> None:
    assert_versioned_or_empty()
    command.upgrade(alembic_config(), revision)


def current_and_head() -> tuple[str | None, str]:
    config = alembic_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise DatabaseRevisionError("Alembic migration head is missing")
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current, head


def require_database_at_head() -> str:
    current, head = current_and_head()
    if current != head:
        raise DatabaseRevisionError(
            f"Database revision is {current or 'unversioned'}, expected {head}"
        )
    return head


def assert_versioned_or_empty() -> None:
    tables = set(inspect(engine).get_table_names())
    application_tables = tables - {"alembic_version"}
    if application_tables and "alembic_version" not in tables:
        raise UnversionedDatabaseError(
            "Existing database has no Alembic revision. Back it up, then run "
            "`python -m app.core.migrations adopt-legacy --yes` once."
        )


def adopt_legacy_database(*, confirmed: bool) -> str:
    if not confirmed:
        raise UnversionedDatabaseError("Legacy adoption requires --yes after a database backup")
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" in tables:
        return require_database_at_head()
    if not tables:
        upgrade_database()
        return require_database_at_head()

    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_phase2_columns()
    validate_metadata_columns()
    command.stamp(alembic_config(), "head")
    return require_database_at_head()


def validate_metadata_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(Base.metadata.tables) - existing_tables)
    missing_columns: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing = {item["name"] for item in inspector.get_columns(table_name)}
        missing_columns.extend(
            f"{table_name}.{column.name}" for column in table.columns if column.name not in existing
        )
    if missing_tables or missing_columns:
        details = ", ".join([*missing_tables, *missing_columns])
        raise DatabaseRevisionError(f"Legacy schema adoption is incomplete: {details}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeMate database migration operations")
    parser.add_argument(
        "action",
        choices=["upgrade", "check", "adopt-legacy", "downgrade-base"],
    )
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.action == "upgrade":
        upgrade_database()
        print(require_database_at_head())
    elif args.action == "check":
        print(require_database_at_head())
    elif args.action == "adopt-legacy":
        print(adopt_legacy_database(confirmed=args.yes))
    else:
        if not args.yes:
            raise SystemExit("downgrade-base requires --yes and destroys application tables")
        command.downgrade(alembic_config(), "base")


if __name__ == "__main__":
    main()
