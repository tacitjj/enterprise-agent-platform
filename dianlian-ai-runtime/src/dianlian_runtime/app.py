from __future__ import annotations

from contextlib import asynccontextmanager
import json
from typing import Annotated, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response, Security, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dianlian_runtime.auth import (
    InternalServiceAuthenticator,
    InternalServiceAuthenticationRequired,
    InternalServiceAuthUnavailable,
    InternalServicePrincipal,
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
from dianlian_runtime.harness import DeerFlowH0Runtime, StartExecutionRequest
from dianlian_runtime.harness.api_contracts import (
    CancelExecutionRequest,
    CreateExecutionRequest,
    ExecutionEventPageResponse,
    ExecutionEventResponse,
    ExecutionSnapshotResponse,
    GuideExecutionRequest,
    RuntimeApiProblem,
)
from dianlian_runtime.harness.h0_runtime import (
    GuidanceOutcomeUnknown,
    GuidancePreconditionRejected,
)
from dianlian_runtime.harness.h1_contracts import (
    CreateH1ExecutionRequest,
    H1ExecutionEventPageResponse,
    H1ExecutionEventResponse,
    H1ExecutionSnapshotResponse,
)
from dianlian_runtime.harness.h1_runtime import (
    DeerFlowH1Runtime,
    H1IdempotencyConflict,
)
from dianlian_runtime.harness.h12_contracts import CreateH12ExecutionRequest
from dianlian_runtime.harness.h12_gateway import (
    H12RuntimeServiceJwtIssuer,
    JavaH12GatewayClient,
)
from dianlian_runtime.harness.model_gateway import (
    JavaModelGatewayChatModel,
)
from dianlian_runtime.supervisor import RunSupervisor
from dianlian_runtime.supervisor.authorizer import (
    PermitAuthorizationConflict,
    PermitAuthorizationInvalidCommand,
    PermitAuthorizationService,
    PermitAuthorizationUnavailable,
    UnavailablePermitAuthorizationService,
    create_postgres_permit_authorization_service,
)
from dianlian_runtime.supervisor.authorizer_contracts import (
    ExternalDispatchArmProblem,
    ExternalDispatchArmRequest,
    ExternalDispatchArmResponse,
    ExternalOperationOutcomeProblem,
    ExternalOperationOutcomeRecordRequest,
    ExternalOperationOutcomeReconcileRequest,
    ExternalOperationOutcomeResponse,
    PermitAuthorizationProblem,
    PermitAuthorizationRequest,
    PermitAuthorizationResponse,
    RuntimeRunAdmissionProblem,
    RuntimeRunAdmissionRequest,
    RuntimeRunAdmissionResponse,
    RuntimeRunCancelProblem,
    RuntimeRunCancelRequest,
    RuntimeRunCancelResponse,
)
from dianlian_runtime.supervisor.control import (
    RuntimeRunCancelConflict,
    RuntimeRunCancelInvalidCommand,
    RuntimeRunCancelService,
    RuntimeRunCancelUnavailable,
    UnavailableRuntimeRunCancelService,
    create_postgres_runtime_run_cancel_service,
)
from dianlian_runtime.supervisor.dispatch_authorizer import (
    ExternalDispatchArmConflict,
    ExternalDispatchArmInvalidCommand,
    ExternalDispatchArmService,
    ExternalDispatchArmUnavailable,
    UnavailableExternalDispatchArmService,
    create_postgres_external_dispatch_arm_service,
)
from dianlian_runtime.supervisor.outcome_reconciler import (
    ExternalOperationOutcomeConflict,
    ExternalOperationOutcomeInvalidCommand,
    ExternalOperationOutcomeService,
    ExternalOperationOutcomeUnavailable,
    UnavailableExternalOperationOutcomeService,
    create_postgres_external_operation_outcome_service,
)
from dianlian_runtime.supervisor.run_admitter import (
    RuntimeRunAdmissionConflict,
    RuntimeRunAdmissionInvalidCommand,
    RuntimeRunAdmissionService,
    RuntimeRunAdmissionUnavailable,
    UnavailableRuntimeRunAdmissionService,
    create_postgres_runtime_run_admission_service,
)
from dianlian_runtime.supervisor.run_projection import (
    RuntimeRunProjectionInvalidQuery,
    RuntimeRunProjectionNotFound,
    RuntimeRunProjectionProblem,
    RuntimeRunProjectionRequest,
    RuntimeRunProjectionResponse,
    RuntimeRunProjectionService,
    RuntimeRunProjectionUnavailable,
    UnavailableRuntimeRunProjectionService,
    create_postgres_runtime_run_projection_service,
)


_INTERNAL_SERVICE_BEARER = HTTPBearer(
    scheme_name="InternalServiceBearer",
    bearerFormat="JWT",
    description="Dedicated RS256 Service JWT; user access tokens are not accepted.",
    auto_error=False,
)
_PERMIT_AUTHORIZATION_ROUTE = (
    "/internal/v1/runtime-supervisor/external-permits/consume-and-authorize"
)
_EXTERNAL_DISPATCH_ARM_ROUTE = (
    "/internal/v1/runtime-supervisor/external-dispatches/consume-and-arm"
)
_EXTERNAL_OUTCOME_RECORD_ROUTE = (
    "/internal/v1/runtime-supervisor/external-operation-outcomes/record"
)
_EXTERNAL_OUTCOME_RECONCILE_ROUTE = (
    "/internal/v1/runtime-supervisor/external-operation-outcomes/reconcile"
)
_RUNTIME_RUN_ADMISSION_ROUTE = (
    "/internal/v1/runtime-supervisor/run-admissions/admit"
)
_RUNTIME_RUN_PROJECTION_ROUTE = (
    "/internal/v1/runtime-supervisor/run-projections/read"
)
_RUNTIME_RUN_CANCEL_ROUTE = (
    "/internal/v1/runtime-supervisor/run-cancellations/request"
)
_HIGH_AUTHORITY_JSON_BODY_LIMIT_BYTES = 8 * 1024
_RUNTIME_RUN_ADMISSION_BODY_LIMIT_BYTES = 32 * 1024
_HIGH_AUTHORITY_JSON_PROBLEMS = {
    _PERMIT_AUTHORIZATION_ROUTE: (
        "PERMIT_AUTHORIZATION_REQUEST_INVALID",
        "The permit authorization request is invalid",
        "PERMIT_AUTHORIZATION_REQUEST_TOO_LARGE",
        "The permit authorization request is too large",
    ),
    _EXTERNAL_DISPATCH_ARM_ROUTE: (
        "EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",
        "The external dispatch arm request is invalid",
        "EXTERNAL_DISPATCH_ARM_REQUEST_TOO_LARGE",
        "The external dispatch arm request is too large",
    ),
    _EXTERNAL_OUTCOME_RECORD_ROUTE: (
        "EXTERNAL_OUTCOME_RECORD_REQUEST_INVALID",
        "The external operation outcome record request is invalid",
        "EXTERNAL_OUTCOME_RECORD_REQUEST_TOO_LARGE",
        "The external operation outcome record request is too large",
    ),
    _EXTERNAL_OUTCOME_RECONCILE_ROUTE: (
        "EXTERNAL_OUTCOME_RECONCILE_REQUEST_INVALID",
        "The external operation outcome reconciliation request is invalid",
        "EXTERNAL_OUTCOME_RECONCILE_REQUEST_TOO_LARGE",
        "The external operation outcome reconciliation request is too large",
    ),
    _RUNTIME_RUN_CANCEL_ROUTE: (
        "RUNTIME_RUN_CANCEL_REQUEST_INVALID",
        "The runtime Run cancel request is invalid",
        "RUNTIME_RUN_CANCEL_REQUEST_TOO_LARGE",
        "The runtime Run cancel request is too large",
    ),
    _RUNTIME_RUN_ADMISSION_ROUTE: (
        "RUNTIME_RUN_ADMISSION_REQUEST_INVALID",
        "The runtime Run admission request is invalid",
        "RUNTIME_RUN_ADMISSION_REQUEST_TOO_LARGE",
        "The runtime Run admission request is too large",
    ),
    _RUNTIME_RUN_PROJECTION_ROUTE: (
        "RUNTIME_RUN_PROJECTION_REQUEST_INVALID",
        "The runtime Run projection request is invalid",
        "RUNTIME_RUN_PROJECTION_REQUEST_TOO_LARGE",
        "The runtime Run projection request is too large",
    ),
}


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey("duplicate JSON key")
        value[key] = item
    return value


class _HighAuthorityJsonBodyGuard:
    """Bound and strictly decode only the two high-authority JSON commands."""

    def __init__(self, app: ASGIApp, active_paths: frozenset[str]) -> None:
        self._app = app
        self._active_paths = active_paths

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        path = scope.get("path")
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or path not in self._active_paths
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
            body_limit = (
                _RUNTIME_RUN_ADMISSION_BODY_LIMIT_BYTES
                if path == _RUNTIME_RUN_ADMISSION_ROUTE
                else _HIGH_AUTHORITY_JSON_BODY_LIMIT_BYTES
            )
            if len(body) > body_limit:
                assert isinstance(path, str)
                await _send_high_authority_guard_problem(
                    scope,
                    receive,
                    send,
                    path=path,
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    too_large=True,
                )
                return
            if not message.get("more_body", False):
                break

        try:
            parsed_body = json.loads(
                bytes(body).decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            if not isinstance(parsed_body, dict):
                raise _DuplicateJsonKey("top-level JSON value must be an object")
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateJsonKey,
            RecursionError,
        ):
            assert isinstance(path, str)
            await _send_high_authority_guard_problem(
                scope,
                receive,
                send,
                path=path,
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                too_large=False,
            )
            return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self._app(scope, replay_receive, send)


async def _send_high_authority_guard_problem(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    path: str,
    status_code: int,
    too_large: bool,
) -> None:
    invalid_code, invalid_message, too_large_code, too_large_message = (
        _HIGH_AUTHORITY_JSON_PROBLEMS[path]
    )
    response = JSONResponse(
        status_code=status_code,
        content={
            "code": too_large_code if too_large else invalid_code,
            "message": too_large_message if too_large else invalid_message,
        },
    )
    await response(scope, receive, send)


def _require_internal_service_scope(
    required_scope: InternalServiceScope,
) -> Callable[..., InternalServicePrincipal]:
    def authorize(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_INTERNAL_SERVICE_BEARER),
        ],
    ) -> InternalServicePrincipal:
        token = "" if credentials is None else credentials.credentials
        return request.app.state.internal_service_authenticator.authorize(
            token,
            required_scope,
        )

    return authorize


def _require_exact_internal_service_scope(
    required_scope: InternalServiceScope,
) -> Callable[..., InternalServicePrincipal]:
    def authorize(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_INTERNAL_SERVICE_BEARER),
        ],
    ) -> InternalServicePrincipal:
        token = "" if credentials is None else credentials.credentials
        principal = request.app.state.internal_service_authenticator.authorize(
            token,
            required_scope,
        )
        if principal.scopes != frozenset({required_scope}):
            raise InternalServiceScopeDenied(
                "high-authority internal service token must have one exact scope"
            )
        return principal

    return authorize


_REQUIRE_CONTEXT_RETRIEVE = _require_internal_service_scope(
    InternalServiceScope.CONTEXT_RETRIEVE
)
_REQUIRE_CONTEXT_INDEX_WRITE = _require_internal_service_scope(
    InternalServiceScope.CONTEXT_INDEX_WRITE
)
_REQUIRE_AGENT_RUNTIME_EXECUTE = _require_internal_service_scope(
    InternalServiceScope.AGENT_RUNTIME_EXECUTE
)
_REQUIRE_RUNTIME_EXTERNAL_PERMIT_AUTHORIZE = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_EXTERNAL_PERMIT_AUTHORIZE
)
_REQUIRE_RUNTIME_EXTERNAL_DISPATCH_ARM = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_EXTERNAL_DISPATCH_ARM
)
_REQUIRE_RUNTIME_EXTERNAL_OUTCOME_RECORD = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_EXTERNAL_OUTCOME_RECORD
)
_REQUIRE_RUNTIME_EXTERNAL_OUTCOME_RECONCILE = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_EXTERNAL_OUTCOME_RECONCILE
)
_REQUIRE_RUNTIME_RUN_ADMIT = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_RUN_ADMIT
)
_REQUIRE_RUNTIME_RUN_OBSERVE = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_RUN_OBSERVE
)
_REQUIRE_RUNTIME_RUN_CANCEL = _require_exact_internal_service_scope(
    InternalServiceScope.RUNTIME_RUN_CANCEL
)


def create_app(
    settings: RuntimeSettings | None = None,
    context_retrieval_service: ContextRetrievalService | None = None,
    context_indexing_service: ContextIndexingService | None = None,
    internal_service_authenticator: InternalServiceAuthenticator | None = None,
    agent_harness_runtime: DeerFlowH0Runtime | None = None,
    agent_h1_runtime: DeerFlowH1Runtime | None = None,
    run_supervisor: RunSupervisor | None = None,
    permit_authorization_service: PermitAuthorizationService | None = None,
    external_dispatch_arm_service: ExternalDispatchArmService | None = None,
    external_operation_outcome_service: ExternalOperationOutcomeService | None = None,
    runtime_run_admission_service: RuntimeRunAdmissionService | None = None,
    runtime_run_projection_service: RuntimeRunProjectionService | None = None,
    runtime_run_cancel_service: RuntimeRunCancelService | None = None,
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

    active_agent_harness = agent_harness_runtime
    if runtime_settings.deerflow_h0_enabled and active_agent_harness is None:
        active_agent_harness = DeerFlowH0Runtime(
            data_dir=runtime_settings.deerflow_data_dir,
            upstream_root=runtime_settings.deerflow_source_root,
        )

    active_agent_h1 = agent_h1_runtime
    if runtime_settings.deerflow_h1_enabled and active_agent_h1 is None:
        if (
            runtime_settings.deerflow_h1_data_dir is None
            or runtime_settings.deerflow_source_root is None
            or runtime_settings.runtime_model_service_base_url is None
            or runtime_settings.runtime_model_service_jwt_key_id is None
            or runtime_settings.runtime_model_service_jwt_private_key_path is None
        ):
            raise RuntimeError("DeerFlow H1 runtime configuration is incomplete")
        model_jwt_issuer = H12RuntimeServiceJwtIssuer(
            key_id=runtime_settings.runtime_model_service_jwt_key_id,
            private_key_path=(
                runtime_settings.runtime_model_service_jwt_private_key_path
            ),
            ttl_seconds=runtime_settings.runtime_model_service_jwt_ttl_seconds,
        )
        active_agent_h1 = DeerFlowH1Runtime(
            data_dir=runtime_settings.deerflow_h1_data_dir,
            upstream_root=runtime_settings.deerflow_source_root,
            model=JavaModelGatewayChatModel(
                base_url=runtime_settings.runtime_model_service_base_url,
                jwt_issuer=model_jwt_issuer,
                timeout_seconds=runtime_settings.runtime_model_service_timeout_seconds,
            ),
            h12_gateway=JavaH12GatewayClient(
                base_url=runtime_settings.runtime_model_service_base_url,
                jwt_issuer=model_jwt_issuer,
                timeout_seconds=runtime_settings.runtime_model_service_timeout_seconds,
            ),
        )

    active_run_supervisor = run_supervisor
    if (
        runtime_settings.governed_h12_driver_enabled
        and active_run_supervisor is None
    ):
        from dianlian_runtime.supervisor.composition import (
            create_governed_h12_run_supervisor,
        )

        active_run_supervisor = create_governed_h12_run_supervisor(runtime_settings)
    elif (
        runtime_settings.structured_driver_enabled
        and active_run_supervisor is None
    ):
        from dianlian_runtime.supervisor.composition import (
            create_structured_run_supervisor,
        )

        active_run_supervisor = create_structured_run_supervisor(runtime_settings)

    if not runtime_settings.permit_authorizer_enabled:
        active_permit_authorization_service: PermitAuthorizationService = (
            UnavailablePermitAuthorizationService()
        )
    elif permit_authorization_service is not None:
        active_permit_authorization_service = permit_authorization_service
    elif runtime_settings.permit_authorizer_database_dsn is None:
        active_permit_authorization_service = UnavailablePermitAuthorizationService()
    else:
        active_permit_authorization_service = (
            create_postgres_permit_authorization_service(
                runtime_settings.permit_authorizer_database_dsn,
                connect_timeout_seconds=(
                    runtime_settings.permit_authorizer_database_connect_timeout_seconds
                ),
                statement_timeout_seconds=(
                    runtime_settings.permit_authorizer_database_statement_timeout_seconds
                ),
                lock_timeout_seconds=(
                    runtime_settings.permit_authorizer_database_lock_timeout_seconds
                ),
            )
        )

    if not runtime_settings.dispatch_authorizer_enabled:
        active_external_dispatch_arm_service: ExternalDispatchArmService = (
            UnavailableExternalDispatchArmService()
        )
    elif external_dispatch_arm_service is not None:
        active_external_dispatch_arm_service = external_dispatch_arm_service
    elif runtime_settings.dispatch_authorizer_database_dsn is None:
        active_external_dispatch_arm_service = UnavailableExternalDispatchArmService()
    else:
        active_external_dispatch_arm_service = (
            create_postgres_external_dispatch_arm_service(
                runtime_settings.dispatch_authorizer_database_dsn,
                connect_timeout_seconds=(
                    runtime_settings.dispatch_authorizer_database_connect_timeout_seconds
                ),
                statement_timeout_seconds=(
                    runtime_settings.dispatch_authorizer_database_statement_timeout_seconds
                ),
                lock_timeout_seconds=(
                    runtime_settings.dispatch_authorizer_database_lock_timeout_seconds
                ),
            )
        )

    if not runtime_settings.outcome_reconciler_enabled:
        active_external_operation_outcome_service: ExternalOperationOutcomeService = (
            UnavailableExternalOperationOutcomeService()
        )
    elif external_operation_outcome_service is not None:
        active_external_operation_outcome_service = external_operation_outcome_service
    elif runtime_settings.outcome_reconciler_database_dsn is None:
        active_external_operation_outcome_service = (
            UnavailableExternalOperationOutcomeService()
        )
    else:
        active_external_operation_outcome_service = (
            create_postgres_external_operation_outcome_service(
                runtime_settings.outcome_reconciler_database_dsn,
                connect_timeout_seconds=(
                    runtime_settings.outcome_reconciler_database_connect_timeout_seconds
                ),
                statement_timeout_seconds=(
                    runtime_settings.outcome_reconciler_database_statement_timeout_seconds
                ),
                lock_timeout_seconds=(
                    runtime_settings.outcome_reconciler_database_lock_timeout_seconds
                ),
            )
        )

    if not runtime_settings.run_admitter_enabled:
        active_runtime_run_admission_service: RuntimeRunAdmissionService = (
            UnavailableRuntimeRunAdmissionService()
        )
    elif runtime_run_admission_service is not None:
        active_runtime_run_admission_service = runtime_run_admission_service
    elif runtime_settings.run_admitter_database_dsn is None:
        active_runtime_run_admission_service = UnavailableRuntimeRunAdmissionService()
    else:
        active_runtime_run_admission_service = create_postgres_runtime_run_admission_service(
            runtime_settings.run_admitter_database_dsn,
            connect_timeout_seconds=(
                runtime_settings.run_admitter_database_connect_timeout_seconds
            ),
            statement_timeout_seconds=(
                runtime_settings.run_admitter_database_statement_timeout_seconds
            ),
            lock_timeout_seconds=(
                runtime_settings.run_admitter_database_lock_timeout_seconds
            ),
        )

    if not runtime_settings.run_observer_enabled:
        active_runtime_run_projection_service: RuntimeRunProjectionService = (
            UnavailableRuntimeRunProjectionService()
        )
    elif runtime_run_projection_service is not None:
        active_runtime_run_projection_service = runtime_run_projection_service
    elif runtime_settings.run_observer_database_dsn is None:
        active_runtime_run_projection_service = UnavailableRuntimeRunProjectionService()
    else:
        active_runtime_run_projection_service = create_postgres_runtime_run_projection_service(
            runtime_settings.run_observer_database_dsn,
            connect_timeout_seconds=(
                runtime_settings.run_observer_database_connect_timeout_seconds
            ),
            statement_timeout_seconds=(
                runtime_settings.run_observer_database_statement_timeout_seconds
            ),
            lock_timeout_seconds=(
                runtime_settings.run_observer_database_lock_timeout_seconds
            ),
        )

    if not runtime_settings.run_controller_enabled:
        active_runtime_run_cancel_service: RuntimeRunCancelService = (
            UnavailableRuntimeRunCancelService()
        )
    elif runtime_run_cancel_service is not None:
        active_runtime_run_cancel_service = runtime_run_cancel_service
    elif runtime_settings.run_controller_database_dsn is None:
        active_runtime_run_cancel_service = UnavailableRuntimeRunCancelService()
    else:
        active_runtime_run_cancel_service = create_postgres_runtime_run_cancel_service(
            runtime_settings.run_controller_database_dsn,
            connect_timeout_seconds=(
                runtime_settings.run_controller_database_connect_timeout_seconds
            ),
            statement_timeout_seconds=(
                runtime_settings.run_controller_database_statement_timeout_seconds
            ),
            lock_timeout_seconds=(
                runtime_settings.run_controller_database_lock_timeout_seconds
            ),
        )

    lifecycle_services = list(
        {
            id(service): service
            for service in (
                active_context_service,
                active_indexing_service,
                active_permit_authorization_service,
                active_external_dispatch_arm_service,
                active_external_operation_outcome_service,
                active_runtime_run_admission_service,
                active_runtime_run_projection_service,
                active_runtime_run_cancel_service,
            )
            if hasattr(service, "start") or hasattr(service, "close")
        }.values()
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        del application
        started_services: list[object] = []
        harness_started = False
        h1_started = False
        supervisor_start_attempted = False
        try:
            for service in lifecycle_services:
                start = getattr(service, "start", None)
                if start is not None:
                    start()
                    started_services.append(service)
            if active_agent_harness is not None:
                await active_agent_harness.__aenter__()
                harness_started = True
            if active_agent_h1 is not None:
                await active_agent_h1.__aenter__()
                h1_started = True
            if runtime_settings.supervisor_enabled and active_run_supervisor is not None:
                supervisor_start_attempted = True
                await active_run_supervisor.start()
            yield
        finally:
            if supervisor_start_attempted and active_run_supervisor is not None:
                await active_run_supervisor.close()
            if h1_started and active_agent_h1 is not None:
                await active_agent_h1.__aexit__(None, None, None)
            if harness_started and active_agent_harness is not None:
                await active_agent_harness.__aexit__(None, None, None)
            for service in reversed(started_services):
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
    guarded_high_authority_paths = frozenset(
        path
        for enabled, path in (
            (runtime_settings.permit_authorizer_enabled, _PERMIT_AUTHORIZATION_ROUTE),
            (runtime_settings.dispatch_authorizer_enabled, _EXTERNAL_DISPATCH_ARM_ROUTE),
            (runtime_settings.outcome_reconciler_enabled, _EXTERNAL_OUTCOME_RECORD_ROUTE),
            (runtime_settings.outcome_reconciler_enabled, _EXTERNAL_OUTCOME_RECONCILE_ROUTE),
            (runtime_settings.run_admitter_enabled, _RUNTIME_RUN_ADMISSION_ROUTE),
            (runtime_settings.run_observer_enabled, _RUNTIME_RUN_PROJECTION_ROUTE),
            (runtime_settings.run_controller_enabled, _RUNTIME_RUN_CANCEL_ROUTE),
        )
        if enabled
    )
    app.add_middleware(
        _HighAuthorityJsonBodyGuard,
        active_paths=guarded_high_authority_paths,
    )
    app.state.settings = runtime_settings
    app.state.context_retrieval_service = active_context_service
    app.state.context_indexing_service = active_indexing_service
    app.state.internal_service_authenticator = active_internal_service_authenticator
    app.state.agent_harness_runtime = active_agent_harness
    app.state.agent_h1_runtime = active_agent_h1
    app.state.run_supervisor = active_run_supervisor
    app.state.permit_authorization_service = active_permit_authorization_service
    app.state.external_dispatch_arm_service = active_external_dispatch_arm_service
    app.state.external_operation_outcome_service = active_external_operation_outcome_service
    app.state.runtime_run_admission_service = active_runtime_run_admission_service
    app.state.runtime_run_projection_service = active_runtime_run_projection_service
    app.state.runtime_run_cancel_service = active_runtime_run_cancel_service

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

    @app.exception_handler(PermitAuthorizationInvalidCommand)
    async def permit_authorization_invalid_command(
        request: Request,
        exception: PermitAuthorizationInvalidCommand,
    ) -> JSONResponse:
        del request, exception
        return _permit_authorization_problem(
            status.HTTP_400_BAD_REQUEST,
            "PERMIT_AUTHORIZATION_REQUEST_INVALID",
            "The permit authorization request is invalid",
        )

    @app.exception_handler(PermitAuthorizationConflict)
    async def permit_authorization_conflict(
        request: Request,
        exception: PermitAuthorizationConflict,
    ) -> JSONResponse:
        del request, exception
        return _permit_authorization_problem(
            status.HTTP_409_CONFLICT,
            "PERMIT_AUTHORIZATION_CONFLICT",
            "The permit authorization request conflicts with durable state",
        )

    @app.exception_handler(PermitAuthorizationUnavailable)
    async def permit_authorization_unavailable(
        request: Request,
        exception: PermitAuthorizationUnavailable,
    ) -> JSONResponse:
        del request, exception
        return _permit_authorization_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PERMIT_AUTHORIZATION_UNAVAILABLE",
            "Permit authorization is unavailable",
        )

    @app.exception_handler(ExternalDispatchArmInvalidCommand)
    async def external_dispatch_arm_invalid_command(
        request: Request,
        exception: ExternalDispatchArmInvalidCommand,
    ) -> JSONResponse:
        del request, exception
        return _external_dispatch_arm_problem(
            status.HTTP_400_BAD_REQUEST,
            "EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",
            "The external dispatch arm request is invalid",
        )

    @app.exception_handler(ExternalDispatchArmConflict)
    async def external_dispatch_arm_conflict(
        request: Request,
        exception: ExternalDispatchArmConflict,
    ) -> JSONResponse:
        del request, exception
        return _external_dispatch_arm_problem(
            status.HTTP_409_CONFLICT,
            "EXTERNAL_DISPATCH_ARM_CONFLICT",
            "The external dispatch arm request conflicts with durable state",
        )

    @app.exception_handler(ExternalDispatchArmUnavailable)
    async def external_dispatch_arm_unavailable(
        request: Request,
        exception: ExternalDispatchArmUnavailable,
    ) -> JSONResponse:
        del request, exception
        return _external_dispatch_arm_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "EXTERNAL_DISPATCH_ARM_UNAVAILABLE",
            "External dispatch arm is unavailable",
        )

    @app.exception_handler(ExternalOperationOutcomeInvalidCommand)
    async def external_operation_outcome_invalid_command(
        request: Request,
        exception: ExternalOperationOutcomeInvalidCommand,
    ) -> JSONResponse:
        del request, exception
        return _external_operation_outcome_problem(
            status.HTTP_400_BAD_REQUEST,
            "EXTERNAL_OPERATION_OUTCOME_REQUEST_INVALID",
            "The external operation outcome request is invalid",
        )

    @app.exception_handler(ExternalOperationOutcomeConflict)
    async def external_operation_outcome_conflict(
        request: Request,
        exception: ExternalOperationOutcomeConflict,
    ) -> JSONResponse:
        del request, exception
        return _external_operation_outcome_problem(
            status.HTTP_409_CONFLICT,
            "EXTERNAL_OPERATION_OUTCOME_CONFLICT",
            "The external operation outcome request conflicts with durable state",
        )

    @app.exception_handler(ExternalOperationOutcomeUnavailable)
    async def external_operation_outcome_unavailable(
        request: Request,
        exception: ExternalOperationOutcomeUnavailable,
    ) -> JSONResponse:
        del request, exception
        return _external_operation_outcome_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "EXTERNAL_OPERATION_OUTCOME_UNAVAILABLE",
            "External operation outcome reconciliation is unavailable",
        )

    @app.exception_handler(RuntimeRunAdmissionInvalidCommand)
    async def runtime_run_admission_invalid_command(
        request: Request,
        exception: RuntimeRunAdmissionInvalidCommand,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_admission_problem(
            status.HTTP_400_BAD_REQUEST,
            "RUNTIME_RUN_ADMISSION_REQUEST_INVALID",
            "The runtime Run admission request is invalid",
        )

    @app.exception_handler(RuntimeRunAdmissionConflict)
    async def runtime_run_admission_conflict(
        request: Request,
        exception: RuntimeRunAdmissionConflict,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_admission_problem(
            status.HTTP_409_CONFLICT,
            "RUNTIME_RUN_ADMISSION_CONFLICT",
            "The runtime Run admission request conflicts with durable state",
        )

    @app.exception_handler(RuntimeRunAdmissionUnavailable)
    async def runtime_run_admission_unavailable(
        request: Request,
        exception: RuntimeRunAdmissionUnavailable,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_admission_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "RUNTIME_RUN_ADMISSION_UNAVAILABLE",
            "Runtime Run admission is unavailable",
        )

    @app.exception_handler(RuntimeRunProjectionInvalidQuery)
    async def runtime_run_projection_invalid_query(
        request: Request,
        exception: RuntimeRunProjectionInvalidQuery,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_projection_problem(
            status.HTTP_400_BAD_REQUEST,
            "RUNTIME_RUN_PROJECTION_REQUEST_INVALID",
            "The runtime Run projection request is invalid",
        )

    @app.exception_handler(RuntimeRunProjectionNotFound)
    async def runtime_run_projection_not_found(
        request: Request,
        exception: RuntimeRunProjectionNotFound,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_projection_problem(
            status.HTTP_404_NOT_FOUND,
            "RUNTIME_RUN_PROJECTION_NOT_FOUND",
            "The runtime Run projection was not found",
        )

    @app.exception_handler(RuntimeRunProjectionUnavailable)
    async def runtime_run_projection_unavailable(
        request: Request,
        exception: RuntimeRunProjectionUnavailable,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_projection_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "RUNTIME_RUN_PROJECTION_UNAVAILABLE",
            "Runtime Run projection is unavailable",
        )

    @app.exception_handler(RuntimeRunCancelInvalidCommand)
    async def runtime_run_cancel_invalid_command(
        request: Request,
        exception: RuntimeRunCancelInvalidCommand,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_cancel_problem(
            status.HTTP_400_BAD_REQUEST,
            "RUNTIME_RUN_CANCEL_REQUEST_INVALID",
            "The runtime Run cancel request is invalid",
        )

    @app.exception_handler(RuntimeRunCancelConflict)
    async def runtime_run_cancel_conflict(
        request: Request,
        exception: RuntimeRunCancelConflict,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_cancel_problem(
            status.HTTP_409_CONFLICT,
            "RUNTIME_RUN_CANCEL_CONFLICT",
            "The runtime Run cancel request conflicts with durable state",
        )

    @app.exception_handler(RuntimeRunCancelUnavailable)
    async def runtime_run_cancel_unavailable(
        request: Request,
        exception: RuntimeRunCancelUnavailable,
    ) -> JSONResponse:
        del request, exception
        return _runtime_run_cancel_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "RUNTIME_RUN_CANCEL_UNAVAILABLE",
            "Runtime Run cancellation is unavailable",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        exception: RequestValidationError,
    ) -> JSONResponse:
        if request.url.path == (
            _PERMIT_AUTHORIZATION_ROUTE
        ):
            return _permit_authorization_problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "PERMIT_AUTHORIZATION_REQUEST_INVALID",
                "The permit authorization request is invalid",
            )
        if request.url.path == (
            _EXTERNAL_DISPATCH_ARM_ROUTE
        ):
            return _external_dispatch_arm_problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",
                "The external dispatch arm request is invalid",
            )
        if request.url.path == _EXTERNAL_OUTCOME_RECORD_ROUTE:
            return _external_operation_outcome_problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "EXTERNAL_OUTCOME_RECORD_REQUEST_INVALID",
                "The external operation outcome record request is invalid",
            )
        if request.url.path == _EXTERNAL_OUTCOME_RECONCILE_ROUTE:
            return _external_operation_outcome_problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "EXTERNAL_OUTCOME_RECONCILE_REQUEST_INVALID",
                "The external operation outcome reconciliation request is invalid",
            )
        if request.url.path == _RUNTIME_RUN_CANCEL_ROUTE:
            return _runtime_run_cancel_problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "RUNTIME_RUN_CANCEL_REQUEST_INVALID",
                "The runtime Run cancel request is invalid",
            )
        if request.url.path == _RUNTIME_RUN_ADMISSION_ROUTE:
            return _runtime_run_admission_problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "RUNTIME_RUN_ADMISSION_REQUEST_INVALID",
                "The runtime Run admission request is invalid",
            )
        return await request_validation_exception_handler(request, exception)

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
            supervisor_ready = (
                runtime_settings.supervisor_enabled
                and active_run_supervisor is not None
                and active_run_supervisor.ready
            )
            ready = (
                runtime_settings.agent_enabled
                and supervisor_ready
            )
        else:
            ready = active_internal_service_authenticator.ready and (
                not runtime_settings.deerflow_h0_enabled
                or (
                    active_agent_harness is not None
                    and active_agent_harness.ready
                )
            ) and (
                not runtime_settings.deerflow_h1_enabled
                or active_agent_h1 is not None
                and active_agent_h1.ready
            ) and (
                not runtime_settings.permit_authorizer_enabled
                or active_permit_authorization_service.ready
            ) and (
                not runtime_settings.dispatch_authorizer_enabled
                or active_external_dispatch_arm_service.ready
            ) and (
                not runtime_settings.outcome_reconciler_enabled
                or active_external_operation_outcome_service.ready
            ) and (
                not runtime_settings.run_admitter_enabled
                or active_runtime_run_admission_service.ready
            ) and (
                not runtime_settings.run_observer_enabled
                or active_runtime_run_projection_service.ready
            ) and (
                not runtime_settings.run_controller_enabled
                or active_runtime_run_cancel_service.ready
            )
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
        supervisor_ready = (
            runtime_settings.supervisor_enabled
            and active_run_supervisor is not None
            and active_run_supervisor.ready
        )
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
                enabled=(
                    runtime_settings.agent_enabled
                    or runtime_settings.deerflow_h0_enabled
                    or runtime_settings.deerflow_h1_enabled
                ),
                ready=(
                    runtime_settings.agent_enabled and supervisor_ready
                    or runtime_settings.deerflow_h0_enabled
                    and active_agent_harness is not None
                    and active_agent_harness.ready
                    or runtime_settings.deerflow_h1_enabled
                    and active_agent_h1 is not None
                    and active_agent_h1.ready
                ),
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

    if runtime_settings.permit_authorizer_enabled:
        permit_authorization_responses = {
            status.HTTP_400_BAD_REQUEST: {"model": PermitAuthorizationProblem},
            status.HTTP_401_UNAUTHORIZED: {"model": PermitAuthorizationProblem},
            status.HTTP_403_FORBIDDEN: {"model": PermitAuthorizationProblem},
            status.HTTP_409_CONFLICT: {"model": PermitAuthorizationProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {
                "model": PermitAuthorizationProblem
            },
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": PermitAuthorizationProblem
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": PermitAuthorizationProblem
            },
        }

        @app.post(
            _PERMIT_AUTHORIZATION_ROUTE,
            response_model=PermitAuthorizationResponse,
            response_model_by_alias=True,
            openapi_extra={
                "x-required-scopes": ["runtime.external-permit.authorize"]
            },
            responses=permit_authorization_responses,
        )
        def consume_and_authorize_external_permit(
            request: PermitAuthorizationRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_EXTERNAL_PERMIT_AUTHORIZE),
            ],
        ) -> PermitAuthorizationResponse:
            outcome = active_permit_authorization_service.authorize(
                request,
                consumed_by=principal.subject,
            )
            return PermitAuthorizationResponse(outcome=outcome)

    if runtime_settings.dispatch_authorizer_enabled:
        external_dispatch_arm_responses = {
            status.HTTP_400_BAD_REQUEST: {"model": ExternalDispatchArmProblem},
            status.HTTP_401_UNAUTHORIZED: {"model": ExternalDispatchArmProblem},
            status.HTTP_403_FORBIDDEN: {"model": ExternalDispatchArmProblem},
            status.HTTP_409_CONFLICT: {"model": ExternalDispatchArmProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {
                "model": ExternalDispatchArmProblem
            },
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": ExternalDispatchArmProblem
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ExternalDispatchArmProblem
            },
        }

        @app.post(
            _EXTERNAL_DISPATCH_ARM_ROUTE,
            response_model=ExternalDispatchArmResponse,
            response_model_by_alias=True,
            openapi_extra={"x-required-scopes": ["runtime.external-dispatch.arm"]},
            responses=external_dispatch_arm_responses,
        )
        def consume_and_arm_external_dispatch(
            request: ExternalDispatchArmRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_EXTERNAL_DISPATCH_ARM),
            ],
        ) -> ExternalDispatchArmResponse:
            arm_result = active_external_dispatch_arm_service.arm(
                request,
                armed_by=principal.subject,
            )
            return ExternalDispatchArmResponse.from_result(arm_result)

    if runtime_settings.outcome_reconciler_enabled:
        external_operation_outcome_responses = {
            status.HTTP_400_BAD_REQUEST: {"model": ExternalOperationOutcomeProblem},
            status.HTTP_401_UNAUTHORIZED: {"model": ExternalOperationOutcomeProblem},
            status.HTTP_403_FORBIDDEN: {"model": ExternalOperationOutcomeProblem},
            status.HTTP_409_CONFLICT: {"model": ExternalOperationOutcomeProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {
                "model": ExternalOperationOutcomeProblem
            },
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": ExternalOperationOutcomeProblem
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ExternalOperationOutcomeProblem
            },
        }

        @app.post(
            _EXTERNAL_OUTCOME_RECORD_ROUTE,
            response_model=ExternalOperationOutcomeResponse,
            response_model_by_alias=True,
            openapi_extra={"x-required-scopes": ["runtime.external-outcome.record"]},
            responses=external_operation_outcome_responses,
        )
        def record_external_operation_outcome(
            request: ExternalOperationOutcomeRecordRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_EXTERNAL_OUTCOME_RECORD),
            ],
        ) -> ExternalOperationOutcomeResponse:
            outcome = active_external_operation_outcome_service.record(
                request,
                recorded_by=principal.subject,
            )
            return ExternalOperationOutcomeResponse(outcome=outcome)

        @app.post(
            _EXTERNAL_OUTCOME_RECONCILE_ROUTE,
            response_model=ExternalOperationOutcomeResponse,
            response_model_by_alias=True,
            openapi_extra={
                "x-required-scopes": ["runtime.external-outcome.reconcile"]
            },
            responses=external_operation_outcome_responses,
        )
        def reconcile_external_operation_outcome(
            request: ExternalOperationOutcomeReconcileRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_EXTERNAL_OUTCOME_RECONCILE),
            ],
        ) -> ExternalOperationOutcomeResponse:
            outcome = active_external_operation_outcome_service.reconcile(
                request,
                recorded_by=principal.subject,
            )
            return ExternalOperationOutcomeResponse(outcome=outcome)

    if runtime_settings.run_admitter_enabled:
        runtime_run_admission_responses = {
            status.HTTP_400_BAD_REQUEST: {"model": RuntimeRunAdmissionProblem},
            status.HTTP_401_UNAUTHORIZED: {"model": RuntimeRunAdmissionProblem},
            status.HTTP_403_FORBIDDEN: {"model": RuntimeRunAdmissionProblem},
            status.HTTP_409_CONFLICT: {"model": RuntimeRunAdmissionProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {
                "model": RuntimeRunAdmissionProblem
            },
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": RuntimeRunAdmissionProblem
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": RuntimeRunAdmissionProblem
            },
        }

        @app.post(
            _RUNTIME_RUN_ADMISSION_ROUTE,
            response_model=RuntimeRunAdmissionResponse,
            response_model_by_alias=True,
            openapi_extra={"x-required-scopes": ["runtime.run.admit"]},
            responses=runtime_run_admission_responses,
        )
        def admit_runtime_run(
            request: RuntimeRunAdmissionRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_RUN_ADMIT),
            ],
        ) -> RuntimeRunAdmissionResponse:
            del principal
            outcome = active_runtime_run_admission_service.admit(request)
            return RuntimeRunAdmissionResponse(outcome=outcome)

    if runtime_settings.run_observer_enabled:
        runtime_run_projection_responses = {
            status.HTTP_400_BAD_REQUEST: {"model": RuntimeRunProjectionProblem},
            status.HTTP_401_UNAUTHORIZED: {"model": RuntimeRunProjectionProblem},
            status.HTTP_403_FORBIDDEN: {"model": RuntimeRunProjectionProblem},
            status.HTTP_404_NOT_FOUND: {"model": RuntimeRunProjectionProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {
                "model": RuntimeRunProjectionProblem
            },
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": RuntimeRunProjectionProblem
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": RuntimeRunProjectionProblem
            },
        }

        @app.post(
            _RUNTIME_RUN_PROJECTION_ROUTE,
            response_model=RuntimeRunProjectionResponse,
            response_model_by_alias=True,
            openapi_extra={"x-required-scopes": ["runtime.run.observe"]},
            responses=runtime_run_projection_responses,
        )
        def read_runtime_run_projection(
            request: RuntimeRunProjectionRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_RUN_OBSERVE),
            ],
        ) -> RuntimeRunProjectionResponse:
            del principal
            return active_runtime_run_projection_service.read(request)

    if runtime_settings.run_controller_enabled:
        runtime_run_cancel_responses = {
            status.HTTP_400_BAD_REQUEST: {"model": RuntimeRunCancelProblem},
            status.HTTP_401_UNAUTHORIZED: {"model": RuntimeRunCancelProblem},
            status.HTTP_403_FORBIDDEN: {"model": RuntimeRunCancelProblem},
            status.HTTP_409_CONFLICT: {"model": RuntimeRunCancelProblem},
            status.HTTP_413_CONTENT_TOO_LARGE: {"model": RuntimeRunCancelProblem},
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": RuntimeRunCancelProblem
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": RuntimeRunCancelProblem
            },
        }

        @app.post(
            _RUNTIME_RUN_CANCEL_ROUTE,
            response_model=RuntimeRunCancelResponse,
            response_model_by_alias=True,
            openapi_extra={"x-required-scopes": ["runtime.run.cancel"]},
            responses=runtime_run_cancel_responses,
        )
        def request_runtime_run_cancel(
            request: RuntimeRunCancelRequest,
            principal: Annotated[
                InternalServicePrincipal,
                Depends(_REQUIRE_RUNTIME_RUN_CANCEL),
            ],
        ) -> RuntimeRunCancelResponse:
            outcome = active_runtime_run_cancel_service.request_cancel(
                request,
                requested_by=principal.subject,
            )
            return RuntimeRunCancelResponse(outcome=outcome)

    if runtime_settings.deerflow_h0_enabled:
        if active_agent_harness is None:
            raise RuntimeError("DeerFlow H0 runtime is enabled but unavailable")

        runtime_responses = {
            status.HTTP_401_UNAUTHORIZED: {"model": RuntimeApiProblem},
            status.HTTP_403_FORBIDDEN: {"model": RuntimeApiProblem},
            status.HTTP_404_NOT_FOUND: {"model": RuntimeApiProblem},
            status.HTTP_409_CONFLICT: {"model": RuntimeApiProblem},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": RuntimeApiProblem},
        }

        @app.post(
            "/internal/v1/agent-runtime/executions",
            response_model=ExecutionSnapshotResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=runtime_responses,
        )
        async def create_runtime_execution(
            request: CreateExecutionRequest,
        ) -> ExecutionSnapshotResponse | JSONResponse:
            try:
                snapshot = await active_agent_harness.start_execution(
                    StartExecutionRequest(
                        execution_id=request.execution_id,
                        idempotency_key=request.idempotency_key,
                        thread_id=request.thread_id,
                        request_hash=request.request_hash,
                        prompt=f"H0 execution {request.execution_id}",
                    )
                )
            except ValueError as exception:
                return _runtime_problem(422, "RUNTIME_REQUEST_INVALID", str(exception))
            except RuntimeError as exception:
                return _runtime_problem(409, "RUNTIME_IDEMPOTENCY_CONFLICT", str(exception))
            return ExecutionSnapshotResponse.from_snapshot(snapshot)

        @app.get(
            "/internal/v1/agent-runtime/executions/{execution_id}",
            response_model=ExecutionSnapshotResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=runtime_responses,
        )
        async def get_runtime_execution(
            execution_id: str,
        ) -> ExecutionSnapshotResponse | JSONResponse:
            try:
                snapshot = await active_agent_harness.get_execution(execution_id)
            except KeyError:
                return _runtime_problem(404, "RUNTIME_EXECUTION_NOT_FOUND", "Runtime execution was not found")
            except RuntimeError:
                return _runtime_problem(503, "RUNTIME_EXECUTION_UNAVAILABLE", "Runtime execution is unavailable")
            return ExecutionSnapshotResponse.from_snapshot(snapshot)

        @app.post(
            "/internal/v1/agent-runtime/executions/{execution_id}/guidance",
            response_model=ExecutionSnapshotResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=runtime_responses,
        )
        async def guide_runtime_execution(
            execution_id: str,
            request: GuideExecutionRequest,
        ) -> ExecutionSnapshotResponse | JSONResponse:
            try:
                snapshot = await active_agent_harness.guide(
                    execution_id,
                    expected_checkpoint_id=request.expected_checkpoint_id,
                    guidance=request.guidance,
                )
            except KeyError:
                return _runtime_problem(404, "RUNTIME_EXECUTION_NOT_FOUND", "Runtime execution was not found")
            except GuidancePreconditionRejected as exception:
                return _runtime_problem(409, exception.code, str(exception))
            except GuidanceOutcomeUnknown:
                return _runtime_problem(
                    503,
                    "RUNTIME_GUIDANCE_OUTCOME_UNKNOWN",
                    "Guidance may have been applied; automatic retry is forbidden",
                )
            except ValueError as exception:
                return _runtime_problem(422, "RUNTIME_REQUEST_INVALID", str(exception))
            except RuntimeError:
                return _runtime_problem(
                    503,
                    "RUNTIME_GUIDANCE_UNAVAILABLE",
                    "Runtime guidance is unavailable",
                )
            return ExecutionSnapshotResponse.from_snapshot(snapshot)

        @app.post(
            "/internal/v1/agent-runtime/executions/{execution_id}/cancel",
            response_model=ExecutionSnapshotResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=runtime_responses,
        )
        async def cancel_runtime_execution(
            execution_id: str,
            request: CancelExecutionRequest,
        ) -> ExecutionSnapshotResponse | JSONResponse:
            try:
                snapshot = await active_agent_harness.cancel(
                    execution_id,
                    action=request.action.value,
                )
            except KeyError:
                return _runtime_problem(404, "RUNTIME_EXECUTION_NOT_FOUND", "Runtime execution was not found")
            except (ValueError, RuntimeError) as exception:
                return _runtime_problem(409, "RUNTIME_CANCEL_CONFLICT", str(exception))
            return ExecutionSnapshotResponse.from_snapshot(snapshot)

        @app.get(
            "/internal/v1/agent-runtime/executions/{execution_id}/events",
            response_model=ExecutionEventPageResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=runtime_responses,
        )
        async def get_runtime_events(
            execution_id: str,
            after_sequence: Annotated[int, Query(alias="afterSequence", ge=0)] = 0,
        ) -> ExecutionEventPageResponse | JSONResponse:
            try:
                events = await active_agent_harness.stream_events(
                    execution_id,
                    after_sequence=after_sequence,
                )
            except KeyError:
                return _runtime_problem(404, "RUNTIME_EXECUTION_NOT_FOUND", "Runtime execution was not found")
            except RuntimeError:
                return _runtime_problem(503, "RUNTIME_EVENTS_UNAVAILABLE", "Runtime events are unavailable")
            items = [ExecutionEventResponse.from_event(event) for event in events]
            next_sequence = items[-1].sequence if items else after_sequence
            return ExecutionEventPageResponse(
                execution_id=execution_id,
                after_sequence=after_sequence,
                next_sequence=next_sequence,
                events=items,
            )

    if runtime_settings.deerflow_h1_enabled:
        if active_agent_h1 is None:
            raise RuntimeError("DeerFlow H1 runtime is enabled but unavailable")

        h1_runtime_responses = {
            status.HTTP_401_UNAUTHORIZED: {"model": RuntimeApiProblem},
            status.HTTP_403_FORBIDDEN: {"model": RuntimeApiProblem},
            status.HTTP_404_NOT_FOUND: {"model": RuntimeApiProblem},
            status.HTTP_409_CONFLICT: {"model": RuntimeApiProblem},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": RuntimeApiProblem},
        }

        @app.post(
            "/internal/v2/agent-runtime/executions",
            response_model=H1ExecutionSnapshotResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=h1_runtime_responses,
        )
        async def create_h1_runtime_execution(
            request: CreateH1ExecutionRequest | CreateH12ExecutionRequest,
        ) -> H1ExecutionSnapshotResponse | JSONResponse:
            try:
                snapshot = await active_agent_h1.start_execution(request)
            except H1IdempotencyConflict:
                return _runtime_problem(
                    409,
                    "RUNTIME_IDEMPOTENCY_CONFLICT",
                    "The H1 idempotency identity is bound to another request",
                )
            except ValueError:
                return _runtime_problem(
                    422,
                    "RUNTIME_REQUEST_INVALID",
                    "The H1 runtime request is invalid",
                )
            except RuntimeError:
                return _runtime_problem(
                    503,
                    "RUNTIME_EXECUTION_UNAVAILABLE",
                    "The H1 runtime execution is unavailable",
                )
            return H1ExecutionSnapshotResponse.from_snapshot(snapshot)

        @app.get(
            "/internal/v2/agent-runtime/executions/{execution_id}",
            response_model=H1ExecutionSnapshotResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=h1_runtime_responses,
        )
        async def get_h1_runtime_execution(
            execution_id: UUID,
        ) -> H1ExecutionSnapshotResponse | JSONResponse:
            try:
                snapshot = await active_agent_h1.get_execution(execution_id)
            except KeyError:
                return _runtime_problem(
                    404,
                    "RUNTIME_EXECUTION_NOT_FOUND",
                    "Runtime execution was not found",
                )
            except RuntimeError:
                return _runtime_problem(
                    503,
                    "RUNTIME_EXECUTION_UNAVAILABLE",
                    "Runtime execution is unavailable",
                )
            return H1ExecutionSnapshotResponse.from_snapshot(snapshot)

        @app.get(
            "/internal/v2/agent-runtime/executions/{execution_id}/events",
            response_model=H1ExecutionEventPageResponse,
            response_model_by_alias=True,
            dependencies=[Depends(_REQUIRE_AGENT_RUNTIME_EXECUTE)],
            openapi_extra={"x-required-scopes": ["agent.runtime.execute"]},
            responses=h1_runtime_responses,
        )
        async def get_h1_runtime_events(
            execution_id: UUID,
            after_sequence: Annotated[int, Query(alias="afterSequence", ge=0)] = 0,
        ) -> H1ExecutionEventPageResponse | JSONResponse:
            try:
                events = await active_agent_h1.stream_events(
                    execution_id,
                    after_sequence=after_sequence,
                )
                snapshot = await active_agent_h1.get_execution(execution_id)
            except KeyError:
                return _runtime_problem(
                    404,
                    "RUNTIME_EXECUTION_NOT_FOUND",
                    "Runtime execution was not found",
                )
            except RuntimeError:
                return _runtime_problem(
                    503,
                    "RUNTIME_EVENTS_UNAVAILABLE",
                    "Runtime events are unavailable",
                )
            items = [H1ExecutionEventResponse.from_event(event) for event in events]
            next_sequence = items[-1].sequence if items else after_sequence
            return H1ExecutionEventPageResponse(
                contract_version=snapshot.contract_version,
                execution_id=execution_id,
                after_sequence=after_sequence,
                next_sequence=next_sequence,
                events=items,
            )

    return app


def _runtime_problem(status_code: int, code: str, message: str) -> JSONResponse:
    body = RuntimeApiProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )


def _permit_authorization_problem(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = PermitAuthorizationProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )


def _external_dispatch_arm_problem(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = ExternalDispatchArmProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )


def _external_operation_outcome_problem(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = ExternalOperationOutcomeProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )


def _runtime_run_cancel_problem(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = RuntimeRunCancelProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )


def _runtime_run_admission_problem(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = RuntimeRunAdmissionProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )


def _runtime_run_projection_problem(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = RuntimeRunProjectionProblem(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
    )
