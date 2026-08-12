package com.dianlian.platform.knowledge.api;

/**
 * REGISTERED only proves that the immutable source reference was accepted.
 * PUBLISHED proves that trusted normalization completed and projection jobs were recorded.
 * Neither state by itself means that the retrieval projection is READY.
 */
public enum KnowledgeDocumentVersionState {
    REGISTERED,
    PUBLISHED,
    SUPERSEDED
}
