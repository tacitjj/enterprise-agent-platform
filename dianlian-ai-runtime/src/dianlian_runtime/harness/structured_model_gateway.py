from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.h12_gateway import (
    STRUCTURED_MODEL_INVOKE_SCOPE,
    ScopedRuntimeServiceJwtIssuer,
)
from dianlian_runtime.harness.structured_admission_manifest import (
    JAVA_LONG_MAX,
    NonNilUuid,
)
from dianlian_runtime.harness.structured_model_receipt import (
    StructuredModelRequestReceipt,
    reject_duplicate_json_keys,
)


_STRUCTURED_MODEL_PATH = (
    "/internal/v1/agent-runtime/executions/"
    "{execution_id}/structured-model-calls/capability"
)
_MAX_RESPONSE_BYTES = 128 * 1024

LowerSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StableCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
]
LeaseOwner = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=160),
]


class _StructuredResponseContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class StructuredDispatchIdentity(_StructuredResponseContract):
    runtime_external_permit_id: NonNilUuid
    lease_owner: LeaseOwner
    lease_epoch: int = Field(ge=1, le=JAVA_LONG_MAX)
    arm_event_id: NonNilUuid

    @model_validator(mode="after")
    def reject_padded_owner(self) -> "StructuredDispatchIdentity":
        if self.lease_owner != self.lease_owner.strip():
            raise ValueError("leaseOwner must not contain surrounding whitespace")
        return self


class StructuredCanonicalFact(_StructuredResponseContract):
    outcome_event_id: NonNilUuid
    outcome_status: Literal[
        "NOT_DISPATCHED",
        "SUCCEEDED",
        "FAILED_CONFIRMED",
        "OUTCOME_UNKNOWN",
    ]
    source_fact_id: NonNilUuid
    source_fact_version: int = Field(ge=1, le=JAVA_LONG_MAX)
    source_fact_hash: LowerSha256
    outcome_code: StableCode
    result_hash: LowerSha256 | None

    @model_validator(mode="after")
    def validate_result_hash(self) -> "StructuredCanonicalFact":
        has_result = self.outcome_status in {"SUCCEEDED", "FAILED_CONFIRMED"}
        if has_result != (self.result_hash is not None):
            raise ValueError("canonical outcome status and resultHash differ")
        return self


class StructuredCandidateReceipt(_StructuredResponseContract):
    document_id: NonNilUuid
    document_kind: Literal["EXTRACTION_CANDIDATE_BATCH"]
    document_version: int = Field(ge=1, le=JAVA_LONG_MAX)
    document_hash: LowerSha256


class StructuredModelCallResponse(_StructuredResponseContract):
    """结构化 Java 命令的公开收敛结果；永不携带候选正文。"""

    contract_version: Literal["1.0"]
    model_call_id: NonNilUuid
    model_request_hash: LowerSha256
    disposition: Literal[
        "PROVIDER_IN_FLIGHT",
        "RECONCILIATION_REQUIRED",
        "CANONICAL_OUTCOME_PENDING",
        "CANONICAL_OUTCOME_APPLIED",
        "CANDIDATE_PROJECTION_PENDING",
        "CANDIDATE_PROJECTED",
    ]
    model_call_status: Literal[
        "PREPARED",
        "PROVIDER_IN_FLIGHT",
        "RESPONSE_RECEIVED",
        "RESPONSE_REJECTED",
        "USAGE_PENDING",
        "FAILED_SAFE",
        "OUTCOME_UNKNOWN",
    ]
    action: Literal[
        "NONE",
        "QUERY_EXACT_JAVA",
        "QUERY_EXACT_ARM_AND_JAVA",
        "REDELIVER_SAME_CANONICAL_FACT",
        "MANUAL_RECONCILIATION_REQUIRED",
        "REPLAY_CANDIDATE_PROJECTION",
    ]
    provider_retry_allowed: Literal[False]
    persisted_dispatch: StructuredDispatchIdentity
    attempted_dispatch: StructuredDispatchIdentity
    canonical_fact: StructuredCanonicalFact | None
    candidate_receipt: StructuredCandidateReceipt | None

    @model_validator(mode="after")
    def validate_public_state(self) -> "StructuredModelCallResponse":
        canonical_required = self.disposition in {
            "CANONICAL_OUTCOME_PENDING",
            "CANONICAL_OUTCOME_APPLIED",
            "CANDIDATE_PROJECTION_PENDING",
            "CANDIDATE_PROJECTED",
        }
        if canonical_required != (self.canonical_fact is not None):
            raise ValueError("structured canonical fact state is inconsistent")
        candidate_required = self.disposition == "CANDIDATE_PROJECTED"
        if candidate_required != (self.candidate_receipt is not None):
            raise ValueError("structured candidate receipt state is inconsistent")
        if self.disposition in {
            "CANDIDATE_PROJECTION_PENDING",
            "CANDIDATE_PROJECTED",
        } and (
            self.canonical_fact is None
            or self.canonical_fact.outcome_status != "SUCCEEDED"
        ):
            raise ValueError("candidate projection requires a succeeded canonical fact")
        if (
            self.disposition == "CANONICAL_OUTCOME_APPLIED"
            and self.canonical_fact is not None
            and self.canonical_fact.outcome_status == "SUCCEEDED"
        ):
            raise ValueError("succeeded outcome must enter candidate projection")
        return self


class StructuredModelGatewayFailure(RuntimeError):
    def __init__(self, code: str, action: str) -> None:
        super().__init__("structured Java model gateway call failed")
        self.code = code
        self.action = action


class StructuredModelGatewayRejected(StructuredModelGatewayFailure):
    pass


class StructuredModelGatewayOutcomeUnknown(StructuredModelGatewayFailure):
    pass


class StructuredModelGatewayClient:
    """默认休眠的 exact receipt 客户端；单次发送且从不授权 Provider 重试。"""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_issuer: ScopedRuntimeServiceJwtIssuer,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("structured model gateway configuration is invalid")
        self._base_url = base_url.rstrip("/")
        self._jwt_issuer = jwt_issuer
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False,
        )

    async def invoke(
        self,
        receipt: StructuredModelRequestReceipt,
    ) -> StructuredModelCallResponse:
        if not isinstance(receipt, StructuredModelRequestReceipt):
            raise TypeError("receipt must be a StructuredModelRequestReceipt")
        try:
            issued = self._jwt_issuer.issue(scope=STRUCTURED_MODEL_INVOKE_SCOPE)
            token = issued.value
        except Exception as exception:
            raise StructuredModelGatewayRejected(
                "STRUCTURED_MODEL_SERVICE_TOKEN_UNAVAILABLE",
                "NONE",
            ) from exception
        if not isinstance(token, str) or not token:
            raise StructuredModelGatewayRejected(
                "STRUCTURED_MODEL_SERVICE_TOKEN_UNAVAILABLE",
                "NONE",
            )

        try:
            response = await self._client.post(
                self._base_url
                + _STRUCTURED_MODEL_PATH.format(execution_id=receipt.execution_id),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                content=receipt.exact_body,
            )
        except httpx.RequestError as exception:
            raise StructuredModelGatewayOutcomeUnknown(
                "STRUCTURED_MODEL_GATEWAY_OUTCOME_UNKNOWN",
                "QUERY_EXACT_ARM_AND_JAVA",
            ) from exception

        if response.status_code not in {200, 202}:
            code, action = _problem(response)
            if 400 <= response.status_code < 500:
                raise StructuredModelGatewayRejected(code, action)
            raise StructuredModelGatewayOutcomeUnknown(code, action)
        if (
            not _single_json_content_type(response)
            or len(response.content) > _MAX_RESPONSE_BYTES
        ):
            raise StructuredModelGatewayOutcomeUnknown(
                "STRUCTURED_MODEL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            )
        try:
            reject_duplicate_json_keys(response.content)
            result = StructuredModelCallResponse.model_validate_json(
                response.content,
                strict=True,
            )
            self._validate_response(receipt, response.status_code, result)
        except (TypeError, ValueError) as exception:
            raise StructuredModelGatewayOutcomeUnknown(
                "STRUCTURED_MODEL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            ) from exception
        return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _validate_response(
        receipt: StructuredModelRequestReceipt,
        status_code: int,
        result: StructuredModelCallResponse,
    ) -> None:
        request = receipt.request
        attempted = result.attempted_dispatch
        expected = request.dispatch_arm
        if (
            result.model_call_id != request.model_call_id
            or result.model_request_hash != request.model_request_hash
            or attempted.runtime_external_permit_id
            != expected.runtime_external_permit_id
            or attempted.lease_owner != expected.lease_owner
            or attempted.lease_epoch != expected.lease_epoch
            or attempted.arm_event_id != expected.arm_event_id
        ):
            raise ValueError("structured response does not match the exact request")

        expected_state = {
            "PROVIDER_IN_FLIGHT": (202, "QUERY_EXACT_JAVA"),
            "RECONCILIATION_REQUIRED": (202, "QUERY_EXACT_ARM_AND_JAVA"),
            "CANONICAL_OUTCOME_PENDING": (
                202,
                "REDELIVER_SAME_CANONICAL_FACT",
            ),
            "CANDIDATE_PROJECTION_PENDING": (
                202,
                "REPLAY_CANDIDATE_PROJECTION",
            ),
            "CANDIDATE_PROJECTED": (200, "NONE"),
        }
        if result.disposition == "CANONICAL_OUTCOME_APPLIED":
            assert result.canonical_fact is not None
            expected = (
                (202, "MANUAL_RECONCILIATION_REQUIRED")
                if result.canonical_fact.outcome_status == "OUTCOME_UNKNOWN"
                else (200, "NONE")
            )
        else:
            expected = expected_state[result.disposition]
        if (status_code, result.action) != expected:
            raise ValueError("structured response status and action differ")


def _single_json_content_type(response: httpx.Response) -> bool:
    values = response.headers.get_list("content-type")
    if len(values) != 1:
        return False
    return values[0].split(";", 1)[0].strip().lower() == "application/json"


def _problem(response: httpx.Response) -> tuple[str, str]:
    if len(response.content) > _MAX_RESPONSE_BYTES:
        return "STRUCTURED_MODEL_GATEWAY_REJECTED", "QUERY_EXACT_JAVA"
    try:
        reject_duplicate_json_keys(response.content)
        body = json.loads(response.content)
    except (TypeError, ValueError):
        body = None
    code = body.get("code") if isinstance(body, dict) else None
    action = body.get("action") if isinstance(body, dict) else None
    if not isinstance(code, str) or not code:
        code = "STRUCTURED_MODEL_GATEWAY_REJECTED"
    if not isinstance(action, str) or not action:
        action = "QUERY_EXACT_JAVA"
    return code, action
