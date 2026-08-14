-- Purpose: bootstrap the Python-owned deer_runtime migration ledger.
-- Scope: PostgreSQL 15+; safe to execute repeatedly through dianlian-supervisor-migrate.
-- Rollback: retain the ledger; destructive schema removal is intentionally not automated.

CREATE SCHEMA IF NOT EXISTS deer_runtime;

CREATE TABLE IF NOT EXISTS deer_runtime.schema_migration
(
    version    VARCHAR(32)  PRIMARY KEY,
    name       VARCHAR(255) NOT NULL,
    checksum   CHAR(64)     NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);
