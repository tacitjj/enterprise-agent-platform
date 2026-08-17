from __future__ import annotations

from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.governed_model_gateway import (
    GovernedCanonicalFact,
    GovernedDispatchIdentity,
    LowerSha256,
)
from dianlian_runtime.harness.governed_tool_receipt import (
    GovernedToolRequestReceipt,
)
from dianlian_runtime.harness.h12_gateway import (
    GOVERNED_TOOL_INVOKE_SCOPE,
    ScopedRuntimeServiceJwtIssuer,
)


_PATH = (
    "/internal/v1/agent-runtime/executions/"
    "{execution_id}/governed-tool-calls/model-selected"
)
_MAX_RESPONSE_BYTES = 128 * 1024


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


class GovernedToolCallResponse(_WireContract):
    contract_version: Literal["1.2"]
    tool_invocation_id: UUID
    request_hash: LowerSha256
    disposition: Literal[
        "IN_FLIGHT",
        "ARM_RECONCILIATION_REQUIRED",
        "CANONICAL_OUTCOME_PENDING",
        "CANONICAL_OUTCOME_APPLIED",
    ]
    action: Literal[
        "NONE",
        "MANUAL_RECONCILIATION_REQUIRED",
        "QUERY_EXACT_JAVA",
        "QUERY_EXACT_ARM_AND_JAVA",
        "REDELIVER_SAME_CANONICAL_FACT",
    ]
    provider_retry_allowed: Literal[False]
    persisted_dispatch: GovernedDispatchIdentity
    attempted_dispatch: GovernedDispatchIdentity
    canonical_fact: GovernedCanonicalFact | None

    @model_validator(mode="after")
    def validate_public_state(self) -> "GovernedToolCallResponse":
        has_fact = self.disposition in {
            "CANONICAL_OUTCOME_PENDING",
            "CANONICAL_OUTCOME_APPLIED",
        }
        if has_fact != (self.canonical_fact is not None):
            raise ValueError("governed Tool canonical fact is inconsistent")
        return self


class GovernedToolGatewayFailure(RuntimeError):
    def __init__(self, code: str, action: str) -> None:
        super().__init__("governed Java Tool gateway call failed")
        self.code = code
        self.action = action


class GovernedToolGatewayRejected(GovernedToolGatewayFailure):
    pass


class GovernedToolGatewayOutcomeUnknown(GovernedToolGatewayFailure):
    pass


class GovernedToolGatewayClient:
    """Dormant exact-receipt client; it never retries or releases Tool output."""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_issuer: ScopedRuntimeServiceJwtIssuer,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("governed Tool gateway configuration is invalid")
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
        receipt: GovernedToolRequestReceipt,
    ) -> GovernedToolCallResponse:
        if not isinstance(receipt, GovernedToolRequestReceipt):
            raise TypeError("receipt must be a GovernedToolRequestReceipt")
        try:
            issued = self._jwt_issuer.issue(scope=GOVERNED_TOOL_INVOKE_SCOPE)
            token = issued.value
        except Exception as exception:
            raise GovernedToolGatewayRejected(
                "GOVERNED_TOOL_SERVICE_TOKEN_UNAVAILABLE",
                "NONE",
            ) from exception
        if not isinstance(token, str) or not token:
            raise GovernedToolGatewayRejected(
                "GOVERNED_TOOL_SERVICE_TOKEN_UNAVAILABLE",
                "NONE",
            )

        try:
            response = await self._client.post(
                self._base_url + _PATH.format(execution_id=receipt.execution_id),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                content=receipt.exact_body,
            )
        except httpx.RequestError as exception:
            raise GovernedToolGatewayOutcomeUnknown(
                "GOVERNED_TOOL_GATEWAY_OUTCOME_UNKNOWN",
                "QUERY_EXACT_ARM_AND_JAVA",
            ) from exception

        if response.status_code not in {200, 202}:
            code, action = _problem(response)
            if 400 <= response.status_code < 500:
                raise GovernedToolGatewayRejected(code, action)
            raise GovernedToolGatewayOutcomeUnknown(code, action)
        if not _single_json_content_type(response):
            raise GovernedToolGatewayOutcomeUnknown(
                "GOVERNED_TOOL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            )
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise GovernedToolGatewayOutcomeUnknown(
                "GOVERNED_TOOL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            )
        try:
            result = GovernedToolCallResponse.model_validate_json(
                response.content,
                strict=True,
            )
            self._validate_response(receipt, response.status_code, result)
        except (TypeError, ValueError) as exception:
            raise GovernedToolGatewayOutcomeUnknown(
                "GOVERNED_TOOL_GATEWAY_RESPONSE_INVALID",
                "QUERY_EXACT_JAVA",
            ) from exception
        return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _validate_response(
        receipt: GovernedToolRequestReceipt,
        status_code: int,
        result: GovernedToolCallResponse,
    ) -> None:
        request = receipt.request
        expected = request.dispatch_arm
        attempted = result.attempted_dispatch
        if (
            result.tool_invocation_id != request.tool_invocation_id
            or result.request_hash != request.request_hash
            or attempted.runtime_external_permit_id
            != expected.runtime_external_permit_id
            or attempted.lease_owner != expected.lease_owner
            or attempted.lease_epoch != expected.lease_epoch
            or attempted.arm_event_id != expected.arm_event_id
        ):
            raise ValueError("governed Tool response differs from the exact receipt")
        accepted = result.disposition != "CANONICAL_OUTCOME_APPLIED"
        if (status_code == 202) != accepted:
            raise ValueError("governed Tool response status and disposition differ")


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
        code = "GOVERNED_TOOL_GATEWAY_REJECTED"
    if not isinstance(action, str) or not action:
        action = "QUERY_EXACT_JAVA"
    return code, action
