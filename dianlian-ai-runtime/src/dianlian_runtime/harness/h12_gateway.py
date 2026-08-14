from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.model_gateway import (
    IssuedRuntimeModelJwt,
    RUNTIME_MODEL_JWT_AUDIENCE,
    RUNTIME_MODEL_JWT_ISSUER,
    RuntimeModelServiceJwtIssuer,
)


MODEL_INVOKE_SCOPE = "model.invoke"
TOOL_INVOKE_SCOPE = "tool.invoke"
ADMISSION_RESOLVE_SCOPE = "admission.resolve"
RuntimeServiceScope = Literal[
    "model.invoke",
    "tool.invoke",
    "admission.resolve",
]

_MODEL_CALL_PATH = "/internal/v1/agent-runtime/executions/{execution_id}/model-calls"
_TOOL_CALL_PATH = "/internal/v1/agent-runtime/executions/{execution_id}/tool-calls"
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,128}$")
_IN_FLIGHT_PROBLEM_CODES = frozenset(
    {"MODEL_CALL_IN_FLIGHT", "TOOL_INVOCATION_IN_FLIGHT"}
)
_FORBIDDEN_PERSISTED_KEYS = frozenset(
    {
        "authorization",
        "apikey",
        "baseurl",
        "credentialref",
        "key",
        "privatekey",
        "secret",
        "token",
    }
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
IdempotencyKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
FailureCode = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]{1,128}$")]


class _H12WireContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class JavaModelCall11Request(_H12WireContract):
    """Only durable identity is sent; Java reconstructs prompt, tools and continuation."""

    contract_version: Literal["1.1"] = "1.1"
    model_call_id: UUID
    call_index: Literal[1, 2]
    call_phase: Literal["INITIAL", "AFTER_TOOL"]
    execution_generation: int = Field(ge=1)
    idempotency_key: IdempotencyKey
    request_hash: Sha256
    admission_snapshot_id: UUID
    prompt_snapshot_id: UUID
    context_snapshot_id: UUID
    tool_policy_snapshot_id: UUID
    orchestration_policy_snapshot_id: UUID
    model_route_binding_id: UUID
    model_route_state_version: int = Field(ge=1)
    model_definition_id: UUID
    model_configuration_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_phase_slot(self) -> "JavaModelCall11Request":
        expected_phase = "INITIAL" if self.call_index == 1 else "AFTER_TOOL"
        if self.call_phase != expected_phase:
            raise ValueError("model call phase does not match its durable slot")
        return self


class JavaModelCall11Response(_H12WireContract):
    contract_version: Literal["1.1"]
    model_call_id: UUID
    status: Literal[
        "RESPONSE_RECEIVED",
        "RESPONSE_REJECTED",
        "USAGE_PENDING",
        "FAILED_SAFE",
        "OUTCOME_UNKNOWN",
    ]
    response_kind: Literal["FINAL_TEXT", "TOOL_SELECTION", "RESPONSE_REJECTED"] | None
    model_tool_selection_id: UUID | None
    assistant_text: str | None
    provider_request_id: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None
    provider_model_name: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None
    finish_reason: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    usage_confirmed: bool
    captured_amount: int = Field(ge=0)
    failure_code: FailureCode | None
    replayed: bool

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> "JavaModelCall11Response":
        if self.status == "RESPONSE_RECEIVED":
            if not self.usage_confirmed or self.failure_code is not None:
                raise ValueError("received model response requires confirmed non-failure usage")
            self._validate_classified_response()
        elif self.status == "RESPONSE_REJECTED":
            if (
                not self.usage_confirmed
                or self.response_kind != "RESPONSE_REJECTED"
                or self.failure_code is None
            ):
                raise ValueError("rejected model response evidence is inconsistent")
            self._require_no_content_or_selection()
        elif self.status == "USAGE_PENDING":
            if self.usage_confirmed or self.input_tokens != 0 or self.output_tokens != 0:
                raise ValueError("pending model usage cannot carry confirmed chargeable counts")
            if self.response_kind == "RESPONSE_REJECTED":
                if self.failure_code is None:
                    raise ValueError("pending rejection requires a failure code")
                self._require_no_content_or_selection()
            else:
                if self.failure_code is not None:
                    raise ValueError("pending successful response cannot carry a failure code")
                self._validate_classified_response()
        else:
            if (
                self.usage_confirmed
                or self.response_kind is not None
                or self.model_tool_selection_id is not None
                or self.assistant_text is not None
                or self.input_tokens != 0
                or self.output_tokens != 0
                or self.failure_code is None
            ):
                raise ValueError("failed model response evidence is inconsistent")
        return self

    def _validate_classified_response(self) -> None:
        if self.response_kind == "FINAL_TEXT":
            if (
                self.assistant_text is None
                or not self.assistant_text.strip()
                or self.model_tool_selection_id is not None
            ):
                raise ValueError("final model response requires text and no tool selection")
            return
        if self.response_kind == "TOOL_SELECTION":
            if self.assistant_text is not None or self.model_tool_selection_id is None:
                raise ValueError("tool response requires one durable model selection")
            return
        raise ValueError("model response requires an allowed classified response kind")

    def _require_no_content_or_selection(self) -> None:
        if self.assistant_text is not None or self.model_tool_selection_id is not None:
            raise ValueError("rejected model response cannot carry content or a selection")


class JavaToolCall11Request(_H12WireContract):
    """MODEL_SELECTED carries no caller-supplied tool reference or input payload."""

    contract_version: Literal["1.1"] = "1.1"
    selection_mode: Literal["MODEL_SELECTED"] = "MODEL_SELECTED"
    tool_invocation_id: UUID
    execution_generation: int = Field(ge=1)
    admission_snapshot_id: UUID
    tool_policy_snapshot_id: UUID
    model_tool_selection_id: UUID
    tool_call_slot: Literal[1] = 1
    idempotency_key: IdempotencyKey
    request_hash: Sha256


class JavaToolCall11Response(_H12WireContract):
    contract_version: Literal["1.1"]
    tool_invocation_id: UUID
    status: Literal["SUCCEEDED", "FAILED_SAFE", "OUTCOME_UNKNOWN"]
    output: dict[str, Any] | None
    failure_code: FailureCode | None
    replayed: bool

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> "JavaToolCall11Response":
        if self.status == "SUCCEEDED":
            if self.output is None or self.failure_code is not None:
                raise ValueError("successful tool response requires output and no failure code")
        elif self.output is not None or self.failure_code is None:
            raise ValueError("failed tool response requires only a failure code")
        return self


class ScopedRuntimeServiceJwtIssuer(Protocol):
    def issue(
        self,
        *,
        scope: RuntimeServiceScope = MODEL_INVOKE_SCOPE,
        now: datetime | None = None,
    ) -> IssuedRuntimeModelJwt: ...


class H12RuntimeServiceJwtIssuer(RuntimeModelServiceJwtIssuer):
    """Uses the established key validation while signing one exact endpoint scope."""

    def issue(
        self,
        *,
        scope: RuntimeServiceScope = MODEL_INVOKE_SCOPE,
        now: datetime | None = None,
    ) -> IssuedRuntimeModelJwt:
        if scope not in {
            MODEL_INVOKE_SCOPE,
            TOOL_INVOKE_SCOPE,
            ADMISSION_RESOLVE_SCOPE,
        }:
            raise ValueError("runtime service JWT scope is invalid")
        issued_at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)
        token = jwt.encode(
            {
                "iss": RUNTIME_MODEL_JWT_ISSUER,
                "sub": RUNTIME_MODEL_JWT_ISSUER,
                "aud": RUNTIME_MODEL_JWT_AUDIENCE,
                "iat": int(issued_at.timestamp()),
                "exp": int(expires_at.timestamp()),
                "jti": str(uuid4()),
                "token_use": "service",
                "scope": scope,
            },
            self._private_key,
            algorithm="RS256",
            headers={"alg": "RS256", "typ": "JWT", "kid": self._key_id},
        )
        return IssuedRuntimeModelJwt(token, issued_at, expires_at)


class H12GatewayFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Java H1 2.2 gateway call failed")
        self.code = code if _FAILURE_CODE_PATTERN.fullmatch(code) else "H12_GATEWAY_FAILED"


class H12GatewayFailedSafe(H12GatewayFailure):
    pass


class H12GatewayOutcomeUnknown(H12GatewayFailure):
    pass


class JavaH12GatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        jwt_issuer: ScopedRuntimeServiceJwtIssuer,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("H1 2.2 gateway configuration is invalid")
        self._base_url = base_url.rstrip("/")
        self._jwt_issuer = jwt_issuer
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.AsyncHTTPTransport(retries=0),
        )

    async def invoke_model(
        self,
        execution_id: UUID,
        request: JavaModelCall11Request,
    ) -> JavaModelCall11Response:
        result = await self._post_exact_intent(
            path=_MODEL_CALL_PATH.format(execution_id=execution_id),
            scope=MODEL_INVOKE_SCOPE,
            request=request,
            response_type=JavaModelCall11Response,
        )
        if result.model_call_id != request.model_call_id:
            raise H12GatewayOutcomeUnknown("H12_GATEWAY_RESPONSE_INVALID")
        if request.call_index == 2 and result.response_kind == "TOOL_SELECTION":
            raise H12GatewayOutcomeUnknown("H12_GATEWAY_RESPONSE_INVALID")
        return result

    async def invoke_tool(
        self,
        execution_id: UUID,
        request: JavaToolCall11Request,
    ) -> JavaToolCall11Response:
        result = await self._post_exact_intent(
            path=_TOOL_CALL_PATH.format(execution_id=execution_id),
            scope=TOOL_INVOKE_SCOPE,
            request=request,
            response_type=JavaToolCall11Response,
        )
        if result.tool_invocation_id != request.tool_invocation_id:
            raise H12GatewayOutcomeUnknown("H12_GATEWAY_RESPONSE_INVALID")
        return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post_exact_intent(
        self,
        *,
        path: str,
        scope: RuntimeServiceScope,
        request: _H12WireContract,
        response_type: type[JavaModelCall11Response] | type[JavaToolCall11Response],
    ) -> JavaModelCall11Response | JavaToolCall11Response:
        request_payload = request.model_dump(mode="json", by_alias=True)
        _assert_safe_persisted_payload(request_payload)
        content = request.model_dump_json(by_alias=True).encode("utf-8")

        response: httpx.Response | None = None
        for attempt in range(2):
            token = self._issue_token(scope)
            try:
                response = await self._client.post(
                    self._base_url + path,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    content=content,
                )
            except httpx.RequestError as exception:
                raise H12GatewayOutcomeUnknown("H12_GATEWAY_OUTCOME_UNKNOWN") from exception
            if response.status_code != 401 or attempt == 1:
                break

        if response is None:
            raise H12GatewayOutcomeUnknown("H12_GATEWAY_OUTCOME_UNKNOWN")
        if response.status_code != 200:
            if response.status_code >= 500 or response.status_code < 400:
                raise H12GatewayOutcomeUnknown("H12_GATEWAY_OUTCOME_UNKNOWN")
            problem_code = _problem_code(response)
            if response.status_code == 409 and problem_code in _IN_FLIGHT_PROBLEM_CODES:
                raise H12GatewayOutcomeUnknown(problem_code)
            raise H12GatewayFailedSafe(problem_code)
        try:
            result = response_type.model_validate_json(response.content)
            _assert_safe_persisted_payload(result.model_dump(mode="json", by_alias=True))
        except (TypeError, ValueError) as exception:
            raise H12GatewayOutcomeUnknown("H12_GATEWAY_RESPONSE_INVALID") from exception
        return result

    def _issue_token(self, scope: RuntimeServiceScope) -> str:
        try:
            issued = self._jwt_issuer.issue(scope=scope)
            value = issued.value
        except Exception as exception:
            raise H12GatewayFailedSafe("H12_SERVICE_TOKEN_UNAVAILABLE") from exception
        if not isinstance(value, str) or not value:
            raise H12GatewayFailedSafe("H12_SERVICE_TOKEN_UNAVAILABLE")
        return value


def _assert_safe_persisted_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if normalized in _FORBIDDEN_PERSISTED_KEYS:
                raise ValueError("H1 2.2 payload contains a forbidden configuration field")
            _assert_safe_persisted_payload(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_safe_persisted_payload(nested)


def _problem_code(response: httpx.Response) -> str:
    try:
        body = response.json()
        value = body.get("code") if isinstance(body, dict) else None
    except ValueError:
        value = None
    if isinstance(value, str) and _FAILURE_CODE_PATTERN.fullmatch(value):
        return value
    return "H12_GATEWAY_REJECTED"
