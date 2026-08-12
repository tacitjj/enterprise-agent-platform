-- Purpose: align the lexical projection title with the 500-character authority contract.
-- Scope: derived data only; existing title values remain unchanged.
-- Rollback: a later reviewed migration may shrink the column only after proving no title exceeds 300.

DROP INDEX dianlian_context.idx_context_lexical_chunk_search;

ALTER TABLE dianlian_context.lexical_chunk
    DROP COLUMN search_document;

ALTER TABLE dianlian_context.lexical_chunk
    ALTER COLUMN title TYPE VARCHAR(500);

ALTER TABLE dianlian_context.lexical_chunk
    ADD COLUMN search_document TSVECTOR GENERATED ALWAYS AS (
        TO_TSVECTOR('simple', COALESCE(title, '') || ' ' || COALESCE(content, ''))
    ) STORED;

CREATE INDEX idx_context_lexical_chunk_search
    ON dianlian_context.lexical_chunk USING GIN (search_document);
