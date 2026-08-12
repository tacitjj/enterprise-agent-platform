from __future__ import annotations

import pytest

from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.migrations import load_migrations, main


def test_context_migrations_are_explicit_and_ordered() -> None:
    migrations = load_migrations()

    assert [migration.version for migration in migrations] == ["000", "001", "002"]
    assert "CREATE SCHEMA IF NOT EXISTS dianlian_context" in migrations[0].sql
    assert "CREATE TABLE dianlian_context.projection_fence" in migrations[1].sql
    assert "UNIQUE NULLS NOT DISTINCT" in migrations[1].sql
    assert "normalization_profile_version" in migrations[1].sql
    expansion = migrations[2].sql
    statements = (
        "DROP INDEX dianlian_context.idx_context_lexical_chunk_search",
        "DROP COLUMN search_document",
        "ALTER COLUMN title TYPE VARCHAR(500)",
        "ADD COLUMN search_document TSVECTOR GENERATED ALWAYS AS",
        "CREATE INDEX idx_context_lexical_chunk_search",
    )
    assert all(statement in expansion for statement in statements)
    assert [expansion.index(statement) for statement in statements] == sorted(
        expansion.index(statement) for statement in statements
    )
    assert "TO_TSVECTOR('simple', COALESCE(title, '') || ' ' || COALESCE(content, ''))" in expansion


def test_migration_cli_requires_environment_dsn(monkeypatch) -> None:
    monkeypatch.delenv("DIANLIAN_CONTEXT_DATABASE_DSN", raising=False)

    with pytest.raises(SystemExit, match="DIANLIAN_CONTEXT_DATABASE_DSN is required"):
        main([])


def test_runtime_settings_repr_does_not_expose_database_dsn() -> None:
    settings = RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=True,
        agent_enabled=False,
        supervisor_enabled=False,
        context_database_dsn="postgresql://example.invalid/not-a-secret",
    )

    assert "postgresql://" not in repr(settings)
