from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
import httpx
import jwt
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.h1_contracts import CreateH1ExecutionRequest


RUNTIME_MODEL_JWT_ISSUER = "dianlian-ai-runtime"
RUNTIME_MODEL_JWT_AUDIENCE = "dianlian-platform"
RUNTIME_MODEL_JWT_SCOPE = "model.invoke"
_MODEL_CALL_PATH = "/internal/v1/agent-runtime/executions/{execution_id}/model-calls"
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,128}$")
_MAX_PRIVATE_KEY_FILE_SIZE = 65_536
_FORBIDDEN_PERSISTED_KEYS = frozenset({"key", "apikey", "baseurl", "credentialref"})
AnnotatedSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _GatewayContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class ModelCallMessage(_GatewayContract):
    role: Literal["HUMAN"]
    text: str


class JavaModelCallRequest(_GatewayContract):
    contract_version: Literal["1.0"] = "1.0"
    model_call_id: UUID
    call_index: Literal[1] = 1
    idempotency_key: str
    request_hash: AnnotatedSha256
    admission_snapshot_id: UUID
    prompt_snapshot_id: UUID
    context_snapshot_id: UUID
    tool_policy_snapshot_id: UUID
    model_route_binding_id: UUID
    model_route_state_version: int = Field(ge=1)
    model_definition_id: UUID
    model_configuration_version: int = Field(ge=1)
    system_instruction: str
    messages: list[ModelCallMessage]


class JavaModelCallResponse(_GatewayContract):
    contract_version: Literal["1.0"]
    model_call_id: UUID
    status: Literal[
        "RESPONSE_RECEIVED",
        "USAGE_PENDING",
        "FAILED_SAFE",
        "OUTCOME_UNKNOWN",
    ]
    assistant_text: str | None
    provider_request_id: str | None
    finish_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    usage_confirmed: bool
    captured_amount: int = Field(ge=0)
    failure_code: str | None
    replayed: bool

    @model_validator(mode="after")
    def validate_status_payload(self) -> "JavaModelCallResponse":
        if self.status in {"RESPONSE_RECEIVED", "USAGE_PENDING"}:
            if self.assistant_text is None or not self.assistant_text.strip():
                raise ValueError("successful model response requires assistantText")
            if self.failure_code is not None:
                raise ValueError("successful model response cannot contain failureCode")
        else:
            if self.assistant_text is not None:
                raise ValueError("failed model response cannot contain assistantText")
            if self.failure_code is None or not _FAILURE_CODE_PATTERN.fullmatch(
                self.failure_code
            ):
                raise ValueError("failed model response requires a stable failureCode")
        return self


@dataclass(frozen=True, slots=True)
class IssuedRuntimeModelJwt:
    value: str
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "IssuedRuntimeModelJwt(value=<redacted>, "
            f"issued_at={self.issued_at!r}, expires_at={self.expires_at!r})"
        )


class RuntimeModelServiceJwtIssuer:
    def __init__(
        self,
        *,
        key_id: str,
        private_key_path: Path,
        ttl_seconds: int,
    ) -> None:
        if not _KEY_ID_PATTERN.fullmatch(key_id):
            raise ValueError("runtime model service JWT key ID is invalid")
        if not 1 <= ttl_seconds <= 60:
            raise ValueError("runtime model service JWT TTL must be between 1 and 60 seconds")
        path = private_key_path
        if not path.is_absolute() or not path.is_file():
            raise ValueError("runtime model service JWT private key is unavailable")
        if path.stat().st_size > _MAX_PRIVATE_KEY_FILE_SIZE:
            raise ValueError("runtime model service JWT private key file is too large")
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError(
                "runtime model service JWT private key must be RSA with at least 2048 bits"
            )
        self._key_id = key_id
        self._private_key = key
        self._ttl_seconds = ttl_seconds

    def issue(self, *, now: datetime | None = None) -> IssuedRuntimeModelJwt:
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
                "scope": RUNTIME_MODEL_JWT_SCOPE,
            },
            self._private_key,
            algorithm="RS256",
            headers={"alg": "RS256", "typ": "JWT", "kid": self._key_id},
        )
        return IssuedRuntimeModelJwt(token, issued_at, expires_at)


class ModelGatewayFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Java model gateway call failed")
        self.code = code if _FAILURE_CODE_PATTERN.fullmatch(code) else "MODEL_GATEWAY_FAILED"


class ModelGatewayFailedSafe(ModelGatewayFailure):
    pass


class ModelGatewayOutcomeUnknown(ModelGatewayFailure):
    pass


class JavaModelGatewayChatModel(BaseChatModel):
    """One-shot text model node backed only by the authoritative Java gateway."""

    base_url: str
    jwt_issuer: Any
    timeout_seconds: int
    http_client: Any | None = None

    def __init__(
        self,
        *,
        base_url: str,
        jwt_issuer: RuntimeModelServiceJwtIssuer,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url.rstrip("/"),
            jwt_issuer=jwt_issuer,
            timeout_seconds=timeout_seconds,
            http_client=client,
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.AsyncHTTPTransport(retries=0),
        )

    @property
    def _llm_type(self) -> str:
        return "dianlian-java-model-gateway"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, kwargs
        raise RuntimeError("JavaModelGatewayChatModel supports async invocation only")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop
        execution_id = kwargs.get("execution_id")
        request = kwargs.get("model_call_request")
        if not isinstance(execution_id, UUID) or not isinstance(
            request,
            JavaModelCallRequest,
        ):
            raise ValueError("H1 graph must supply its persisted model call identity")
        _validate_chat_messages(messages, request)
        response = await self._call_gateway(execution_id, request)
        if response.status == "OUTCOME_UNKNOWN":
            raise ModelGatewayOutcomeUnknown(
                response.failure_code or "MODEL_GATEWAY_OUTCOME_UNKNOWN"
            )
        if response.status == "USAGE_PENDING":
            raise ModelGatewayFailedSafe("MODEL_USAGE_RECONCILIATION_REQUIRED")
        if response.status == "FAILED_SAFE":
            raise ModelGatewayFailedSafe(
                response.failure_code or "MODEL_GATEWAY_FAILED"
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=response.assistant_text or "",
                        response_metadata={
                            "modelCallId": str(response.model_call_id),
                            "status": response.status,
                            "usageConfirmed": response.usage_confirmed,
                            "capturedAmount": response.captured_amount,
                            "replayed": response.replayed,
                        },
                        usage_metadata={
                            "input_tokens": response.input_tokens,
                            "output_tokens": response.output_tokens,
                            "total_tokens": (
                                response.input_tokens + response.output_tokens
                            ),
                        },
                    )
                )
            ],
            llm_output={
                "modelCallResponse": response.model_dump(
                    mode="json",
                    by_alias=True,
                )
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call_gateway(
        self,
        execution_id: UUID,
        request: JavaModelCallRequest,
    ) -> JavaModelCallResponse:
        token = self.jwt_issuer.issue()
        try:
            response = await self._client.post(
                self.base_url
                + _MODEL_CALL_PATH.format(execution_id=execution_id),
                headers={
                    "Authorization": f"Bearer {token.value}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                content=request.model_dump_json(by_alias=True),
            )
        except httpx.RequestError as exception:
            raise ModelGatewayOutcomeUnknown("MODEL_GATEWAY_OUTCOME_UNKNOWN") from exception

        if not 200 <= response.status_code < 300:
            code = _problem_code(response)
            if response.status_code >= 500:
                raise ModelGatewayOutcomeUnknown("MODEL_GATEWAY_OUTCOME_UNKNOWN")
            raise ModelGatewayFailedSafe(code)
        try:
            result = JavaModelCallResponse.model_validate_json(response.content)
        except ValueError as exception:
            raise ModelGatewayOutcomeUnknown("MODEL_GATEWAY_RESPONSE_INVALID") from exception
        if result.model_call_id != request.model_call_id:
            raise ModelGatewayOutcomeUnknown("MODEL_GATEWAY_RESPONSE_INVALID")
        return result


def build_model_call_request(
    admission: CreateH1ExecutionRequest,
) -> JavaModelCallRequest:
    model_call_id = uuid5(
        NAMESPACE_URL,
        f"dianlian:h1:{admission.execution_id}:model-call:1",
    )
    payload: dict[str, Any] = {
        "contractVersion": "1.0",
        "modelCallId": str(model_call_id),
        "callIndex": 1,
        "idempotencyKey": f"h1-model-{model_call_id}",
        "admissionSnapshotId": str(admission.admission_snapshot_id),
        "promptSnapshotId": str(admission.prompt.prompt_snapshot_id),
        "contextSnapshotId": str(admission.context.context_snapshot_id),
        "toolPolicySnapshotId": str(admission.tool_policy.tool_policy_snapshot_id),
        "modelRouteBindingId": str(admission.model_route.route_binding_id),
        "modelRouteStateVersion": admission.model_route.route_state_version,
        "modelDefinitionId": str(admission.model_route.model_definition_id),
        "modelConfigurationVersion": admission.model_route.model_configuration_version,
        "systemInstruction": admission.prompt.system_instruction,
        "messages": [
            message.model_dump(mode="json", by_alias=True)
            for message in admission.prompt.messages
        ],
    }
    _assert_no_forbidden_persisted_keys(payload)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["requestHash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return JavaModelCallRequest.model_validate(payload)


def _assert_no_forbidden_persisted_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if normalized in _FORBIDDEN_PERSISTED_KEYS:
                raise ValueError("H1 runtime payload contains a forbidden configuration field")
            _assert_no_forbidden_persisted_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_forbidden_persisted_keys(nested)


def assert_safe_h1_payload(value: object) -> None:
    _assert_no_forbidden_persisted_keys(value)


def _validate_chat_messages(
    messages: list[BaseMessage],
    request: JavaModelCallRequest,
) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    if (
        len(messages) != 2
        or not isinstance(messages[0], SystemMessage)
        or not isinstance(messages[1], HumanMessage)
        or messages[0].content != request.system_instruction
        or messages[1].content != request.messages[0].text
    ):
        raise ValueError("H1 graph messages do not match the frozen admission")


def _problem_code(response: httpx.Response) -> str:
    try:
        value = response.json().get("code")
    except (ValueError, AttributeError):
        value = None
    if isinstance(value, str) and _FAILURE_CODE_PATTERN.fullmatch(value):
        return value
    return "MODEL_GATEWAY_REJECTED"
