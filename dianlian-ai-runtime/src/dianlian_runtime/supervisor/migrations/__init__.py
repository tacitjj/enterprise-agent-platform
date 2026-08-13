from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import os

import psycopg


MIGRATION_LOCK_ID = 7_619_104_232


@dataclass(frozen=True, slots=True)
class SqlMigration:
    version: str
    name: str
    sql: str
    checksum: str


def load_migrations() -> list[SqlMigration]:
    sql_root = files(__package__).joinpath("sql")
    migrations = []
    for resource in sorted(sql_root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".sql"):
            continue
        version, separator, _ = resource.name.partition("__")
        if not separator or not version.isdigit():
            raise RuntimeError(f"Invalid migration name: {resource.name}")
        sql = resource.read_text(encoding="utf-8")
        migrations.append(
            SqlMigration(
                version=version,
                name=resource.name,
                sql=sql,
                checksum=sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    if not migrations or migrations[0].version != "000":
        raise RuntimeError("The first supervisor migration must be version 000")
    if len({migration.version for migration in migrations}) != len(migrations):
        raise RuntimeError("Supervisor migration versions must be unique")
    return migrations


def apply_migrations(dsn: str) -> list[str]:
    migrations = load_migrations()
    applied_now: list[str] = []
    with psycopg.connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
            ledger_exists = connection.execute(
                "SELECT to_regclass('deer_runtime.schema_migration') IS NOT NULL"
            ).fetchone()[0]
            if not ledger_exists:
                connection.execute(migrations[0].sql)
            applied_rows = connection.execute(
                "SELECT version, checksum FROM deer_runtime.schema_migration"
            ).fetchall()
            applied = {row[0]: row[1] for row in applied_rows}
            for migration in migrations:
                previous_checksum = applied.get(migration.version)
                if previous_checksum is not None:
                    if previous_checksum != migration.checksum:
                        raise RuntimeError(
                            f"Migration {migration.version} checksum does not match"
                        )
                    continue
                if migration.version != "000":
                    connection.execute(migration.sql)
                connection.execute(
                    """
                    INSERT INTO deer_runtime.schema_migration (version, name, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
                applied_now.append(migration.version)
    return applied_now


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Apply explicit deer_runtime PostgreSQL migrations",
    )
    parser.parse_args(argv)
    dsn = os.getenv("DIANLIAN_SUPERVISOR_MIGRATION_DATABASE_DSN")
    if dsn is None or not dsn.strip():
        raise SystemExit("DIANLIAN_SUPERVISOR_MIGRATION_DATABASE_DSN is required")
    applied = apply_migrations(dsn.strip())
    if applied:
        print("Applied supervisor migrations: " + ", ".join(applied))
    else:
        print("Supervisor migrations are already current")
