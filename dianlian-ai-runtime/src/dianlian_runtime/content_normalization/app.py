from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Security, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dianlian_runtime.auth import (
    InternalServiceAuthenticationRequired,
    InternalServiceAuthenticator,
    InternalServiceAuthUnavailable,
    InternalServicePrincipal,
    InternalServiceScope,
    InternalServiceScopeDenied,
    create_internal_service_authenticator,
)
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.content_normalization.contracts import (
    ContentNormalizationProblem,
    ContentNormalizationRequest,
    ContentNormalizationResponse,
)
from dianlian_runtime.content_normalization.service import (
    ContentNormalizationContractRejected,
    ContentNormalizationDisabled,
    ContentNormalizationService,
    ContentNormalizationSourceConflict,
    ContentNormalizationUnavailable,
    DisabledContentNormalizationService,
    IsolatedContentNormalizationService,
    create_parser,
)
from dianlian_runtime.content_normalization.settings import ContentNormalizationSettings


CONTENT_NORMALIZATION_ROUTE = "/internal/v1/content/normalize"
_BODY_LIMIT_BYTES = 32 * 1024
_BEARER = HTTPBearer(
    scheme_name="ContentNormalizationServiceBearer",
    bearerFormat="JWT",
    description="Dedicated RS256 Service JWT; user access tokens are not accepted.",
    auto_error=False,
)


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey("duplicate JSON key")
        result[key] = value
    return result


class _NormalizationJsonBodyGuard:
    """限制并严格解码唯一规范化命令，避免重复键绕过。"""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != CONTENT_NORMALIZATION_ROUTE
        ):
            await self._app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > _BODY_LIMIT_BYTES:
                await _send_problem(
                    scope,
                    receive,
                    send,
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "CONTENT_NORMALIZATION_REQUEST_TOO_LARGE",
                    "The content normalization request is too large",
                )
                return
            if not message.get("more_body", False):
                break
        try:
            parsed = json.loads(
                bytes(body).decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            if not isinstance(parsed, dict):
                raise _DuplicateJsonKey("top-level JSON must be an object")
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateJsonKey,
            RecursionError,
        ):
            await _send_problem(
                scope,
                receive,
                send,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "CONTENT_NORMALIZATION_REQUEST_INVALID",
                "The content normalization request is invalid",
            )
            return
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self._app(scope, replay_receive, send)


async def _send_problem(
    scope: Scope,
    receive: Receive,
    send: Send,
    status_code: int,
    code: str,
    message: str,
) -> None:
    response = JSONResponse(status_code=status_code, content={"code": code, "message": message})
    await response(scope, receive, send)


def _require_exact_content_normalize_scope(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_BEARER),
    ],
) -> InternalServicePrincipal:
    token = "" if credentials is None else credentials.credentials
    principal = request.app.state.internal_service_authenticator.authorize(
        token,
        InternalServiceScope.CONTENT_NORMALIZE,
    )
    if principal.scopes != frozenset({InternalServiceScope.CONTENT_NORMALIZE}):
        raise InternalServiceScopeDenied(
            "content normalization token must have one exact scope"
        )
    return principal


def create_content_normalization_app(
    settings: ContentNormalizationSettings | None = None,
    service: ContentNormalizationService | None = None,
    authenticator: InternalServiceAuthenticator | None = None,
) -> FastAPI:
    """创建独立、默认关闭的 Docling/Tika 规范化服务。"""

    active_settings = settings or ContentNormalizationSettings.from_environment()
    active_service: ContentNormalizationService
    if service is not None:
        active_service = service
    elif active_settings.enabled:
        active_service = IsolatedContentNormalizationService(
            active_settings,
            create_parser(active_settings),
        )
    else:
        active_service = DisabledContentNormalizationService()
    active_authenticator = authenticator or create_internal_service_authenticator(
        _auth_runtime_settings_from_environment()
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        del application
        try:
            yield
        finally:
            close = getattr(active_service, "close", None)
            if close is not None:
                close()

    app = FastAPI(
        title="Dianlian Isolated Content Normalization API",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/internal/v1/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(_NormalizationJsonBodyGuard)
    app.state.internal_service_authenticator = active_authenticator
    app.state.content_normalization_service = active_service

    @app.exception_handler(InternalServiceAuthUnavailable)
    async def auth_unavailable(request: Request, exception: InternalServiceAuthUnavailable):
        del request, exception
        return _problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "INTERNAL_SERVICE_AUTH_UNAVAILABLE",
            "Internal service authentication is unavailable",
        )

    @app.exception_handler(InternalServiceAuthenticationRequired)
    async def authentication_required(
        request: Request,
        exception: InternalServiceAuthenticationRequired,
    ):
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
    async def scope_denied(request: Request, exception: InternalServiceScopeDenied):
        del request, exception
        return _problem(
            status.HTTP_403_FORBIDDEN,
            "INTERNAL_SERVICE_SCOPE_DENIED",
            "The internal service token does not grant this operation",
        )

    @app.exception_handler(ContentNormalizationDisabled)
    async def normalization_disabled(
        request: Request,
        exception: ContentNormalizationDisabled,
    ):
        del request, exception
        return _problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CONTENT_NORMALIZATION_DISABLED",
            "Content normalization is disabled",
        )

    @app.exception_handler(ContentNormalizationSourceConflict)
    async def source_conflict(
        request: Request,
        exception: ContentNormalizationSourceConflict,
    ):
        del request, exception
        return _problem(
            status.HTTP_409_CONFLICT,
            "CONTENT_NORMALIZATION_SOURCE_CONFLICT",
            "The source read capability conflicts with the normalization request",
        )

    @app.exception_handler(ContentNormalizationContractRejected)
    async def contract_rejected(
        request: Request,
        exception: ContentNormalizationContractRejected,
    ):
        del request, exception
        return _problem(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "CONTENT_NORMALIZATION_CONTRACT_REJECTED",
            "The parser rejected the source or returned an invalid document",
        )

    @app.exception_handler(ContentNormalizationUnavailable)
    async def normalization_unavailable(
        request: Request,
        exception: ContentNormalizationUnavailable,
    ):
        del request, exception
        return _problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CONTENT_NORMALIZATION_UNAVAILABLE",
            "Content normalization is unavailable",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        exception: RequestValidationError,
    ):
        if request.url.path == CONTENT_NORMALIZATION_ROUTE:
            return _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "CONTENT_NORMALIZATION_REQUEST_INVALID",
                "The content normalization request is invalid",
            )
        return await request_validation_exception_handler(request, exception)

    @app.get("/internal/v1/health/liveness")
    def liveness() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/internal/v1/health/readiness")
    def readiness() -> JSONResponse:
        ready = active_authenticator.ready and active_service.ready
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "UP" if ready else "NOT_READY"},
        )

    @app.post(
        CONTENT_NORMALIZATION_ROUTE,
        response_model=ContentNormalizationResponse,
        response_model_by_alias=True,
        dependencies=[Depends(_require_exact_content_normalize_scope)],
        openapi_extra={"x-required-scopes": ["content.normalize"]},
        responses={
            status.HTTP_401_UNAUTHORIZED: {"model": ContentNormalizationProblem},
            status.HTTP_403_FORBIDDEN: {"model": ContentNormalizationProblem},
            status.HTTP_409_CONFLICT: {"model": ContentNormalizationProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {"model": ContentNormalizationProblem},
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ContentNormalizationProblem},
            status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ContentNormalizationProblem},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ContentNormalizationProblem},
        },
    )
    def normalize_content(
        request: ContentNormalizationRequest,
    ) -> ContentNormalizationResponse:
        return active_service.normalize(request)

    return app


def _auth_runtime_settings_from_environment() -> RuntimeSettings:
    raw_skew = os.getenv("DIANLIAN_SERVICE_JWT_CLOCK_SKEW_SECONDS", "5")
    try:
        skew = int(raw_skew)
    except ValueError as exception:
        raise ValueError("DIANLIAN_SERVICE_JWT_CLOCK_SKEW_SECONDS must be an integer") from exception
    return RuntimeSettings(
        service_name="dianlian-content-normalization",
        service_version="1.0",
        role="runtime-api",
        agent_enabled=False,
        supervisor_enabled=False,
        service_jwt_public_key_ring_json=os.getenv(
            "DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON"
        ),
        service_jwt_clock_skew_seconds=skew,
    )


def _problem(status_code: int, code: str, message: str) -> JSONResponse:
    body = ContentNormalizationProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )
