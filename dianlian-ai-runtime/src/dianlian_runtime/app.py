from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, Request, Response, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from dianlian_runtime.auth import (
    InternalServiceAuthenticator,
    InternalServiceAuthenticationRequired,
    InternalServiceAuthUnavailable,
    InternalServiceScope,
    InternalServiceScopeDenied,
    create_internal_service_authenticator,
)
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.contracts import (
    HealthResponse,
    RuntimeFeatureStatus,
    RuntimeStatusResponse,
)
from dianlian_runtime.context.contracts import (
    ContextBundle,
    ContextRetrievalRequest,
    ServiceUnavailableResponse,
)
from dianlian_runtime.context.indexing import resolve_index_profile
from dianlian_runtime.context.indexing_contracts import (
    ContextIndexingReceipt,
    ContextIndexingRequest,
    IndexTarget,
)
from dianlian_runtime.context.postgres import (
    PostgresContextDatabase,
    PostgresContextService,
)
from dianlian_runtime.context.service import (
    ContextIndexingConflict,
    ContextIndexingService,
    ContextIndexingUnavailable,
    ContextOperationUnavailable,
    ContextRetrievalService,
    ContextRetrievalUnavailable,
    DisabledContextIndexingService,
    DisabledContextRetrievalService,
    UnavailableContextIndexingService,
    UnavailableContextRetrievalService,
)


_INTERNAL_SERVICE_BEARER = HTTPBearer(
    scheme_name="InternalServiceBearer",
    bearerFormat="JWT",
    description="Dedicated RS256 Service JWT; user access tokens are not accepted.",
    auto_error=False,
)


def _require_internal_service_scope(
    required_scope: InternalServiceScope,
) -> Callable[..., None]:
    def authorize(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_INTERNAL_SERVICE_BEARER),
        ],
    ) -> None:
        token = "" if credentials is None else credentials.credentials
        request.app.state.internal_service_authenticator.authorize(
            token,
            required_scope,
        )

    return authorize


_REQUIRE_CONTEXT_RETRIEVE = _require_internal_service_scope(
    InternalServiceScope.CONTEXT_RETRIEVE
)
_REQUIRE_CONTEXT_INDEX_WRITE = _require_internal_service_scope(
    InternalServiceScope.CONTEXT_INDEX_WRITE
)


def create_app(
    settings: RuntimeSettings | None = None,
    context_retrieval_service: ContextRetrievalService | None = None,
    context_indexing_service: ContextIndexingService | None = None,
    internal_service_authenticator: InternalServiceAuthenticator | None = None,
) -> FastAPI:
    runtime_settings = settings or RuntimeSettings.from_environment()
    active_internal_service_authenticator = (
        internal_service_authenticator
        or create_internal_service_authenticator(runtime_settings)
    )
    if not runtime_settings.context_enabled:
        active_context_service: ContextRetrievalService = DisabledContextRetrievalService()
        active_indexing_service: ContextIndexingService = DisabledContextIndexingService()
    elif context_retrieval_service is not None or context_indexing_service is not None:
        active_context_service = (
            context_retrieval_service or UnavailableContextRetrievalService()
        )
        active_indexing_service = (
            context_indexing_service or UnavailableContextIndexingService()
        )
    elif runtime_settings.context_database_dsn is None:
        active_context_service = UnavailableContextRetrievalService()
        active_indexing_service = UnavailableContextIndexingService()
    else:
        database = PostgresContextDatabase(
            runtime_settings.context_database_dsn,
            min_size=runtime_settings.context_database_pool_min_size,
            max_size=runtime_settings.context_database_pool_max_size,
            connect_timeout_seconds=runtime_settings.context_database_connect_timeout_seconds,
        )
        postgres_service = PostgresContextService(
            database,
            resolve_index_profile(runtime_settings.context_index_profile),
        )
        active_context_service = postgres_service
        active_indexing_service = postgres_service

    lifecycle_services = list(
        {
            id(service): service
            for service in (active_context_service, active_indexing_service)
            if hasattr(service, "start") or hasattr(service, "close")
        }.values()
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        del application
        for service in lifecycle_services:
            start = getattr(service, "start", None)
            if start is not None:
                start()
        try:
            yield
        finally:
            for service in reversed(lifecycle_services):
                close = getattr(service, "close", None)
                if close is not None:
                    close()

    app = FastAPI(
        title="Dianlian AI Runtime Internal API",
        version=runtime_settings.service_version,
        docs_url=None,
        redoc_url=None,
        openapi_url="/internal/v1/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.context_retrieval_service = active_context_service
    app.state.context_indexing_service = active_indexing_service
    app.state.internal_service_authenticator = active_internal_service_authenticator

    @app.exception_handler(InternalServiceAuthUnavailable)
    async def internal_service_auth_unavailable(
        request: Request,
        exception: InternalServiceAuthUnavailable,
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "INTERNAL_SERVICE_AUTH_UNAVAILABLE",
                "message": "Internal service authentication is unavailable",
            },
        )

    @app.exception_handler(InternalServiceAuthenticationRequired)
    async def internal_service_authentication_required(
        request: Request,
        exception: InternalServiceAuthenticationRequired,
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            content={
                "code": "INTERNAL_SERVICE_AUTHENTICATION_REQUIRED",
                "message": "A valid internal service token is required",
            },
        )

    @app.exception_handler(InternalServiceScopeDenied)
    async def internal_service_scope_denied(
        request: Request,
        exception: InternalServiceScopeDenied,
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "code": "INTERNAL_SERVICE_SCOPE_DENIED",
                "message": "The internal service token does not grant this operation",
            },
        )

    @app.exception_handler(ContextIndexingUnavailable)
    @app.exception_handler(ContextRetrievalUnavailable)
    async def context_operation_unavailable(
        request: Request,
        exception: ContextOperationUnavailable,
    ) -> JSONResponse:
        del request
        body = ServiceUnavailableResponse(
            code=exception.code,
            message=exception.message,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(mode="json", by_alias=True),
        )

    @app.exception_handler(ContextIndexingConflict)
    async def context_indexing_conflict(
        request: Request,
        exception: ContextIndexingConflict,
    ) -> JSONResponse:
        del request
        body = ServiceUnavailableResponse(
            code=exception.code,
            message=exception.message,
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=body.model_dump(mode="json", by_alias=True),
        )

    @app.get(
        "/internal/v1/health/liveness",
        response_model=HealthResponse,
        response_model_by_alias=True,
    )
    def liveness() -> HealthResponse:
        return HealthResponse.now(
            status="UP",
            service=runtime_settings.service_name,
            version=runtime_settings.service_version,
            role=runtime_settings.role,
        )

    @app.get(
        "/internal/v1/health/readiness",
        response_model=HealthResponse,
        response_model_by_alias=True,
    )
    def readiness(response: Response) -> HealthResponse:
        if runtime_settings.role == "context-worker":
            ready = (
                active_internal_service_authenticator.ready
                and active_context_service.ready
                and active_indexing_service.ready
            )
        elif runtime_settings.role == "agent-worker":
            ready = (
                runtime_settings.agent_enabled
                and runtime_settings.supervisor_enabled
            )
        else:
            ready = active_internal_service_authenticator.ready
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse.now(
            status="UP" if ready else "OUT_OF_SERVICE",
            service=runtime_settings.service_name,
            version=runtime_settings.service_version,
            role=runtime_settings.role,
        )

    @app.get(
        "/internal/v1/runtime/status",
        response_model=RuntimeStatusResponse,
    )
    def runtime_status() -> RuntimeStatusResponse:
        supervisor_ready = runtime_settings.supervisor_enabled
        context_ready = (
            active_internal_service_authenticator.ready
            and runtime_settings.context_enabled
            and active_context_service.ready
            and active_indexing_service.ready
        )
        return RuntimeStatusResponse(
            service=runtime_settings.service_name,
            version=runtime_settings.service_version,
            role=runtime_settings.role,
            context=RuntimeFeatureStatus(
                enabled=runtime_settings.context_enabled,
                ready=context_ready,
            ),
            agent=RuntimeFeatureStatus(
                enabled=runtime_settings.agent_enabled,
                ready=runtime_settings.agent_enabled and supervisor_ready,
            ),
            supervisor=RuntimeFeatureStatus(
                enabled=runtime_settings.supervisor_enabled,
                ready=supervisor_ready,
            ),
        )

    @app.post(
        "/internal/v1/retrieval/search",
        response_model=ContextBundle,
        response_model_by_alias=True,
        dependencies=[Depends(_REQUIRE_CONTEXT_RETRIEVE)],
        openapi_extra={"x-required-scopes": ["context.retrieve"]},
        responses={
            status.HTTP_401_UNAUTHORIZED: {
                "model": ServiceUnavailableResponse,
                "description": "The dedicated internal Service JWT is missing or invalid",
            },
            status.HTTP_403_FORBIDDEN: {
                "model": ServiceUnavailableResponse,
                "description": "The Service JWT does not grant context.retrieve",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ServiceUnavailableResponse,
                "description": "Authentication or context retrieval is unavailable",
            }
        },
    )
    def retrieve_context(request: ContextRetrievalRequest) -> ContextBundle:
        return active_context_service.retrieve(request)

    @app.post(
        "/internal/v1/indexing/apply",
        response_model=ContextIndexingReceipt,
        response_model_by_alias=True,
        dependencies=[Depends(_REQUIRE_CONTEXT_INDEX_WRITE)],
        openapi_extra={"x-required-scopes": ["context.index.write"]},
        responses={
            status.HTTP_401_UNAUTHORIZED: {
                "model": ServiceUnavailableResponse,
                "description": "The dedicated internal Service JWT is missing or invalid",
            },
            status.HTTP_403_FORBIDDEN: {
                "model": ServiceUnavailableResponse,
                "description": "The Service JWT does not grant context.index.write",
            },
            status.HTTP_409_CONFLICT: {
                "model": ServiceUnavailableResponse,
                "description": "The event conflicts with the current projection fence",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ServiceUnavailableResponse,
                "description": "Authentication, context storage, or the requested index provider is unavailable",
            },
        },
    )
    def apply_context_index(request: ContextIndexingRequest) -> ContextIndexingReceipt:
        if runtime_settings.context_enabled and request.target == IndexTarget.VECTOR:
            raise ContextIndexingUnavailable(
                "INDEX_PROVIDER_NOT_CONFIGURED",
                "No production embedding provider is configured",
            )
        return active_indexing_service.apply(request)

    return app
