from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from dianlian_runtime.context.contracts import ContextBundle, ContextRetrievalRequest
from dianlian_runtime.context.indexing_contracts import (
    ContextIndexingReceipt,
    ContextIndexingRequest,
)


class ContextOperationUnavailable(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ContextRetrievalUnavailable(ContextOperationUnavailable):
    pass


class ContextIndexingUnavailable(ContextOperationUnavailable):
    pass


class ContextIndexingConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ContextRetrievalService(Protocol):
    @property
    def ready(self) -> bool: ...

    def retrieve(self, request: ContextRetrievalRequest) -> ContextBundle: ...


class ContextIndexingService(Protocol):
    @property
    def ready(self) -> bool: ...

    def apply(self, request: ContextIndexingRequest) -> ContextIndexingReceipt: ...


@dataclass(frozen=True, slots=True)
class DisabledContextRetrievalService:
    @property
    def ready(self) -> bool:
        return False

    def retrieve(self, request: ContextRetrievalRequest) -> ContextBundle:
        raise ContextRetrievalUnavailable(
            "CONTEXT_FEATURE_DISABLED",
            "Context retrieval is disabled",
        )


@dataclass(frozen=True, slots=True)
class UnavailableContextRetrievalService:
    @property
    def ready(self) -> bool:
        return False

    def retrieve(self, request: ContextRetrievalRequest) -> ContextBundle:
        raise ContextRetrievalUnavailable(
            "CONTEXT_RETRIEVER_NOT_CONNECTED",
            "No production context retriever is configured",
        )


@dataclass(frozen=True, slots=True)
class DisabledContextIndexingService:
    @property
    def ready(self) -> bool:
        return False

    def apply(self, request: ContextIndexingRequest) -> ContextIndexingReceipt:
        raise ContextIndexingUnavailable(
            "CONTEXT_FEATURE_DISABLED",
            "Context indexing is disabled",
        )


@dataclass(frozen=True, slots=True)
class UnavailableContextIndexingService:
    @property
    def ready(self) -> bool:
        return False

    def apply(self, request: ContextIndexingRequest) -> ContextIndexingReceipt:
        raise ContextIndexingUnavailable(
            "CONTEXT_DATABASE_NOT_READY",
            "Context projection database is not ready",
        )
