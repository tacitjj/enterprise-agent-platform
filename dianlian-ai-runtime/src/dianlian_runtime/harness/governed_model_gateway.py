from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.governed_model_receipt import (
    GovernedAfterToolModelRequestReceipt,
    GovernedInitialModelRequestReceipt,
)
from dianlian_runtime.harness.h12_gateway import (
    GOVERNED_MODEL_INVOKE_SCOPE,
    ScopedRuntimeServiceJwtIssuer,
)


_INITIAL_PATH = (
    "/internal/v1/agent-runtime/executions/"
    "{execution_id}/governed-model-calls/initial"
)
_AFTER_TOOL_PATH = (
    "/internal/v1/agent-runtime/executions/"
    "{execution_id}/governed-model-calls/after-tool"
)
_MAX_RESPONSE_BYTES = 128 * 1024

LowerSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StableCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]
LeaseOwner = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=160),
]


class _WireContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class GovernedDispatchIdentity(_WireContract):
    runtime_external_permit_id: UUID
    lease_owner: LeaseOwner
    lease_epoch: int = Field(ge=1)
    arm_event_id: UUID

    @model_validator(mode="after")
    def validate_identity(self) -> "GovernedDispatchIdentity":
        _require_non_nil_uuid(
            "runtimeExternalPermitId",
            self.runtime_external_permit_id,
        )
        _require_non_nil_uuid("armEventId", self.arm_event_id)
        if self.lease_owner != self.lease_owner.strip():
            raise ValueError("leaseOwner must not contain surrounding whitespace")
        return self


class GovernedCanonicalFact(_WireContract):
    outcome_event_id: UUID
    outcome_status: Literal[
        "NOT_DISPATCHED",
        "SUCCEEDED",
        "FAILED_CONFIRMED",
        "OUTCOME_UNKNOWN",
    ]
    source_fact_id: UUID
    source_fact_version: int = Field(ge=1)
    source_fact_hash: LowerSha256
    outcome_code: StableCode
    result_hash: LowerSha256 | None

    @model_validator(mode="after")
    def validate_fact(self) -> "GovernedCanonicalFact":
        _require_non_nil_uuid("outcomeEventId", self.outcome_event_id)
        _require_non_nil_uuid("sourceFactId", self.source_fact_id)
        has_result = self.outcome_status in {"SUCCEEDED", "FAILED_CONFIRMED"}
        if has_result != (self.result_hash is not None):
            raise ValueError("canonical outcome status and resultHash differ")
        return self


class GovernedTerminalResult(_WireContract):
    status: Literal[
        "RESPONSE_RECEIVED",
        "RESPONSE_REJECTED",
        "USAGE_PENDING",
        "FAILED_SAFE",
        "OUTCOME_UNKNOWN",
    ]
    response_kind: Literal["FINAL_TEXT", "RESPONSE_REJECTED"]
    assistant_text: str | None
    provider_request_id: str | None
    provider_model_name: str | None
    finish_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    usage_confirmed: bool
    captured_amount: int = Field(ge=0)
    failure_code: StableCode | None

    @model_validator(mode="after")
    def validate_terminal_result(self) -> "GovernedTerminalResult":
        if self.response_kind == "FINAL_TEXT":
            if (
                self.status != "RESPONSE_RECEIVED"
                or self.assistant_text is None
                or not self.assistant_text.strip()
                or self.failure_code is not None
                or not self.usage_confirmed
            ):
                raise ValueError("final governed result evidence is inconsistent")
        elif (
            self.status != "RESPONSE_REJECTED"
            or self.assistant_text is not None
            or self.failure_code is None
            or not self.usage_confirmed
        ):
            raise ValueError("rejected governed result evidence is inconsistent")
        return self


class GovernedInitialModelCallResponse(_WireContract):
    contract_version: Literal["1.2"]
    model_call_id: UUID
    request_hash: LowerSha256
    disposition: Literal[
        "FAILED_SAFE_BEFORE_ARM",
        "MANUAL_RECONCILIATION_REQUIRED",
        "PROVIDER_IN_FLIGHT",
        "ARM_RECONCILIATION_REQUIRED",
        "CANONICAL_OUTCOME_PENDING",
        "SETTLEMENT_PENDING",
        "CANONICAL_OUTCOME_APPLIED",
        "GOVERNED_TOOL_REQUIRED",
    ]
    model_call_status: str
    failure_code: StableCode | None
    action: Literal[
        "NONE",
        "MANUAL_RECONCILIATION_REQUIRED",
        "QUERY_EXACT_JAVA",
        "QUERY_EXACT_ARM_AND_JAVA",
        "REDELIVER_SAME_CANONICAL_FACT",
        "WAIT_FOR_GOVERNED_TOOL_CHAIN",
    ]
    provider_retry_allowed: Literal[False]
    persisted_dispatch: GovernedDispatchIdentity
    attempted_dispatch: GovernedDispatchIdentity
    canonical_fact: GovernedCanonicalFact | None
    terminal_result: GovernedTerminalResult | None

    @model_validator(mode="after")
    def validate_public_state(self) -> "GovernedInitialModelCallResponse":
        canonical = self.disposition in {
            "CANONICAL_OUTCOME_PENDING",
            "SETTLEMENT_PENDING",
            "CANONICAL_OUTCOME_APPLIED",
            "GOVERNED_TOOL_REQUIRED",
        }
        if canonical != (self.canonical_fact is not None):
            raise ValueError("governed response canonical fact is inconsistent")
        if self.disposition in {
            "CANONICAL_OUTCOME_PENDING",
            "SETTLEMENT_PENDING",
            "GOVERNED_TOOL_REQUIRED",
            "MANUAL_RECONCILIATION_REQUIRED",
            "PROVIDER_IN_FLIGHT",
            "ARM_RECONCILIATION_REQUIRED",
            "FAILED_SAFE_BEFORE_ARM",
        } and self.terminal_result is not None:
            raise ValueError("non-releasable governed state contains a terminal result")
        if self.terminal_result is not None:
            if self.disposition != "CANONICAL_OUTCOME_APPLIED":
                raise ValueError("terminal result requires an applied canonical outcome")
            if self.canonical_fact is None or self.canonical_fact.outcome_status not in {
                "SUCCEEDED",
                "FAILED_CONFIRMED",
            }:
                raise ValueError("terminal result lacks a determinate canonical outcome")
        return self


class GovernedModelGatewayFailure(RuntimeError):
    def __init__(self, code: str, action: str) -> None:
        super().__init__("governed Java model gateway call failed")
        self.code = code
        self.action = action


class GovernedModelGatewayRejected(GovernedModelGatewayFailure):
    pass


class GovernedModelGatewayOutcomeUnknown(GovernedModelGatewayFailure):
    pass


class GovernedInitialModelGatewayClient:
    """Dormant model receipt client; it never retries or authorizes Provider work."""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_issuer: ScopedRuntimeServiceJwtIssuer,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("governed model gateway configuration is invalid")
        self._base_url = base_url.rstrip("/")
        self._jwt_issuer = jwt_issuer
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False,
        )

    async def invoke_initial(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> GovernedInitialModelCallResponse:
        if not isinstance(receipt, GovernedInitialModelRequestReceipt):
            raise TypeError("receipt must be a GovernedInitialModelRequestReceipt")
        return await self._invoke(receipt, _INITIAL_PATH)

    async def invoke_after_tool(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> GovernedInitialModelCallResponse:
        if not isinstance(receipt, GovernedAfterToolModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedAfterToolModelRequestReceipt"
            )
        return await self._invoke(receipt, _AFTER_TOOL_PATH)

    async def _invoke(
        self,
        receipt: (
            GovernedInitialModelRequestReceipt
            | GovernedAfterToolModelRequestReceipt
        ),
        path: str,
    ) -> GovernedInitialModelCallResponse:
        try:
            issued = self._jwt_issuer.issue(scope=GOVERNED_MODEL_INVOKE_SCOPE)
            token = issued.value
        except Exception as exception:
            raise GovernedModelGatewayRejected(
                "GOVERNED_MODEL_SERVICE_TOKEN_UNAVAILABLE",
                "NONE",
            ) from exception
        if not isinstance(token, str) or not token:
            raise GovernedModelGatewayRejected(
                "GOVERNED_MODEL_SERVICE_TOKEN_UNAVAILABLE",
                "NONE",
            )

        try:
            response = await self._client.post(
                self._base_url
                + path.format(execution_id=receipt.execution_id),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                content=receipt.exact_body,
            )
        except httpx.RequestError as exception:
            raise GovernedModelGatewayOutcomeUnknown(
                "GOVERNED_MODEL_GATEWAY_OUTCOME_UNKNOWN",
                "QUERY_EXACT_ARM_AND_JAVA",
            ) from exception

        if response.status_code not in {200, 202}:
            code, action = _problem(response)
            if 400 <= response.status_code < 500:
                raise GovernedModelGatewayRejected(code, action)
            raise GovernedModelGatewayOutcomeUnknown(code, action)
        if not _single_json_content_type(response):
            raise GovernedModelGatewayOutcomeUnknown(
                "GOVERNED_MODEL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            )
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise GovernedModelGatewayOutcomeUnknown(
                "GOVERNED_MODEL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            )
        try:
            result = GovernedInitialModelCallResponse.model_validate_json(
                response.content,
                strict=True,
            )
            self._validate_response(receipt, response.status_code, result)
        except (TypeError, ValueError) as exception:
            raise GovernedModelGatewayOutcomeUnknown(
                "GOVERNED_MODEL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            ) from exception
        return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _validate_response(
        receipt: (
            GovernedInitialModelRequestReceipt
            | GovernedAfterToolModelRequestReceipt
        ),
        status_code: int,
        result: GovernedInitialModelCallResponse,
    ) -> None:
        request = receipt.request
        attempted = result.attempted_dispatch
        expected = request.dispatch_arm
        if (
            result.model_call_id != request.model_call_id
            or result.request_hash != request.request_hash
            or attempted.runtime_external_permit_id
            != expected.runtime_external_permit_id
            or attempted.lease_owner != expected.lease_owner
            or attempted.lease_epoch != expected.lease_epoch
            or attempted.arm_event_id != expected.arm_event_id
        ):
            raise ValueError("governed response does not match the exact request receipt")
        accepted = result.disposition in {
            "PROVIDER_IN_FLIGHT",
            "ARM_RECONCILIATION_REQUIRED",
            "CANONICAL_OUTCOME_PENDING",
            "SETTLEMENT_PENDING",
            "GOVERNED_TOOL_REQUIRED",
            "MANUAL_RECONCILIATION_REQUIRED",
        }
        if (status_code == 202) != accepted:
            raise ValueError("governed response status and disposition differ")


def _single_json_content_type(response: httpx.Response) -> bool:
    values = response.headers.get_list("content-type")
    if len(values) != 1:
        return False
    return values[0].split(";", 1)[0].strip().lower() == "application/json"


def _problem(response: httpx.Response) -> tuple[str, str]:
    try:
        body = response.json()
    except ValueError:
        body = None
    code = body.get("code") if isinstance(body, dict) else None
    action = body.get("action") if isinstance(body, dict) else None
    if not isinstance(code, str) or not code:
        code = "GOVERNED_MODEL_GATEWAY_REJECTED"
    if not isinstance(action, str) or not action:
        action = "QUERY_EXACT_JAVA"
    return code, action


def _require_non_nil_uuid(name: str, value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{name} must be a non-nil UUID")
