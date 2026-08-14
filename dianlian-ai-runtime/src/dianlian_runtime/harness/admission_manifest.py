from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID

import httpx
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.h1_contracts import (
    BoundedKey,
    LowerSha256,
)
from dianlian_runtime.harness.h12_gateway import (
    ADMISSION_RESOLVE_SCOPE,
    ScopedRuntimeServiceJwtIssuer,
)
from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalPermitStatus,
    RuntimeExternalPermitFact,
)
from dianlian_runtime.supervisor.driver import (
    DriverExecutionRequest,
    DriverFenceGate,
)


_ADMISSION_MANIFEST_PATH = (
    "/internal/v1/agent-runtime/runs/{runtime_run_id}/admission-manifest"
)
_MAX_ADMISSION_MANIFEST_RESPONSE_BYTES = 256 * 1024
_ADMISSION_MANIFEST_RESPONSE_CHUNK_BYTES = 64 * 1024
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,128}$")
_FORBIDDEN_MANIFEST_KEYS = frozenset(
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


def _require_non_nil_uuid(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must not be the nil UUID")
    return value


NonNilUuid = Annotated[UUID, AfterValidator(_require_non_nil_uuid)]


class _AdmissionManifestWireContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class JavaAdmissionManifestResolveRequest(_AdmissionManifestWireContract):
    tenant_id: NonNilUuid
    task_step_id: NonNilUuid
    execution_generation: int = Field(ge=1)
    admission_contract_version: Literal["2.2"] = "2.2"
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    runtime_external_permit_id: NonNilUuid
    permit_intent_id: NonNilUuid
    permit_request_hash: LowerSha256
    lease_owner: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=160),
    ]
    lease_epoch: int = Field(ge=1)

    @model_validator(mode="after")
    def reject_padded_owner(self) -> "JavaAdmissionManifestResolveRequest":
        if self.lease_owner != self.lease_owner.strip():
            raise ValueError("leaseOwner must not contain surrounding whitespace")
        return self


class JavaAdmissionPromptReceipt(_AdmissionManifestWireContract):
    prompt_snapshot_id: NonNilUuid
    hash: LowerSha256


class JavaAdmissionContextReceipt(_AdmissionManifestWireContract):
    context_snapshot_id: NonNilUuid
    hash: LowerSha256


class JavaAdmissionToolPolicyReceipt(_AdmissionManifestWireContract):
    tool_policy_snapshot_id: NonNilUuid
    hash: LowerSha256


class JavaAdmissionOrchestrationReceipt(_AdmissionManifestWireContract):
    orchestration_policy_snapshot_id: NonNilUuid
    max_model_calls: Literal[2]
    max_tool_calls: Literal[1]
    model_call_reservation_ceiling: int = Field(ge=1)
    total_model_reservation_ceiling: int = Field(ge=2)
    hash: LowerSha256

    @model_validator(mode="after")
    def validate_receipt(self) -> "JavaAdmissionOrchestrationReceipt":
        if self.total_model_reservation_ceiling != (
            self.model_call_reservation_ceiling * self.max_model_calls
        ):
            raise ValueError(
                "total model reservation ceiling must equal both model call ceilings"
            )
        if self.hash != _orchestration_receipt_hash(self):
            raise ValueError("orchestration policy hash does not match the receipt")
        return self


class JavaAdmissionModelRouteReceipt(_AdmissionManifestWireContract):
    route_binding_id: NonNilUuid
    route_state_version: int = Field(ge=1)
    model_definition_id: NonNilUuid
    model_configuration_version: int = Field(ge=1)
    reservation_ceiling_micro_credit: int = Field(ge=1)


class JavaAdmissionManifest(_AdmissionManifestWireContract):
    runtime_run_id: NonNilUuid
    tenant_id: NonNilUuid
    task_id: NonNilUuid
    task_step_id: NonNilUuid
    execution_generation: int = Field(ge=1)
    admission_contract_version: Literal["2.2"]
    runtime_profile: Literal["DEERFLOW_H1_TEXT"]
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    request_hash: LowerSha256
    idempotency_key: BoundedKey
    actor_user_id: NonNilUuid
    input_snapshot_id: NonNilUuid
    enterprise_agent_id: NonNilUuid
    agent_version_id: NonNilUuid
    configuration_version_id: NonNilUuid
    point_reservation_id: NonNilUuid
    model_route: JavaAdmissionModelRouteReceipt
    prompt: JavaAdmissionPromptReceipt
    context: JavaAdmissionContextReceipt
    tool_policy: JavaAdmissionToolPolicyReceipt
    orchestration_policy: JavaAdmissionOrchestrationReceipt

    @model_validator(mode="after")
    def validate_h12_policy_binding(self) -> "JavaAdmissionManifest":
        if (
            self.model_route.reservation_ceiling_micro_credit
            != self.orchestration_policy.model_call_reservation_ceiling
        ):
            raise ValueError(
                "model route ceiling does not match the orchestration policy"
            )
        return self


def _orchestration_receipt_hash(
    receipt: JavaAdmissionOrchestrationReceipt,
) -> str:
    canonical = (
        '{"schemaVersion":"runtime-orchestration-policy-v1",'
        '"maxModelCalls":2,'
        '"maxToolCalls":1,'
        f'"modelCallReservationCeiling":{receipt.model_call_reservation_ceiling},'
        f'"totalModelReservationCeiling":{receipt.total_model_reservation_ceiling}}}'
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AdmissionManifestFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Java admission manifest resolution failed")
        self.code = (
            code
            if _FAILURE_CODE_PATTERN.fullmatch(code)
            else "ADMISSION_MANIFEST_FAILED"
        )


class AdmissionManifestFailedSafe(AdmissionManifestFailure):
    pass


class AdmissionManifestOutcomeUnknown(AdmissionManifestFailure):
    pass


class JavaAdmissionManifestClient:
    """Dormant, non-caching reader; production composition is intentionally absent."""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_issuer: ScopedRuntimeServiceJwtIssuer,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("admission manifest client configuration is invalid")
        self._base_url = base_url.rstrip("/")
        self._jwt_issuer = jwt_issuer
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.AsyncHTTPTransport(retries=0),
        )

    async def resolve(
        self,
        execution: DriverExecutionRequest,
        permit: RuntimeExternalPermitFact,
        *,
        gate: DriverFenceGate,
    ) -> JavaAdmissionManifest:
        wire_request = _bind_request(execution, permit)
        payload = wire_request.model_dump(mode="json", by_alias=True)
        _assert_no_forbidden_manifest_keys(payload)
        content = wire_request.model_dump_json(by_alias=True).encode("utf-8")
        path = _ADMISSION_MANIFEST_PATH.format(
            runtime_run_id=execution.authority.runtime_run_id
        )

        response_status: int | None = None
        response_content_type: str | None = None
        response_content = b""
        response_too_large = False
        for attempt in range(2):
            response_status = None
            response_content_type = None
            response_content = b""
            response_too_large = False
            token = self._issue_token()
            await gate.authorize_execution()
            try:
                async with self._client.stream(
                    "POST",
                    self._base_url + path,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    content=content,
                    follow_redirects=False,
                ) as response:
                    response_status = response.status_code
                    response_content_type = response.headers.get("content-type")
                    response_content, response_too_large = (
                        await _read_bounded_response(response)
                    )
            except httpx.RequestError as exception:
                raise AdmissionManifestOutcomeUnknown(
                    "ADMISSION_MANIFEST_OUTCOME_UNKNOWN"
                ) from exception
            if response_status != 401 or attempt == 1:
                break

        if response_status is None:
            raise AdmissionManifestOutcomeUnknown(
                "ADMISSION_MANIFEST_OUTCOME_UNKNOWN"
            )
        if response_status != 200:
            if (
                response_status >= 500
                or response_status in {408, 429}
                or response_status < 400
            ):
                raise AdmissionManifestOutcomeUnknown(
                    "ADMISSION_MANIFEST_OUTCOME_UNKNOWN"
                )
            if response_too_large:
                raise AdmissionManifestFailedSafe(
                    "ADMISSION_MANIFEST_REJECTED"
                )
            raise AdmissionManifestFailedSafe(_problem_code(response_content))

        if response_too_large:
            raise AdmissionManifestOutcomeUnknown(
                "ADMISSION_MANIFEST_RESPONSE_TOO_LARGE"
            )
        if not _is_json_content_type(response_content_type):
            raise AdmissionManifestOutcomeUnknown(
                "ADMISSION_MANIFEST_RESPONSE_INVALID"
            )

        try:
            raw_response = json.loads(
                response_content,
                object_pairs_hook=_reject_duplicate_keys,
            )
            _assert_no_forbidden_manifest_keys(raw_response)
            manifest = JavaAdmissionManifest.model_validate_json(
                response_content,
                strict=True,
            )
        except (TypeError, ValueError) as exception:
            raise AdmissionManifestOutcomeUnknown(
                "ADMISSION_MANIFEST_RESPONSE_INVALID"
            ) from exception
        _require_exact_manifest_binding(execution, manifest)
        # The permit protects the Java read; this second live gate prevents a
        # manifest fetched across takeover from becoming executable authority.
        await gate.authorize_execution()
        return manifest

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _issue_token(self) -> str:
        try:
            issued = self._jwt_issuer.issue(scope=ADMISSION_RESOLVE_SCOPE)
            value = issued.value
        except Exception as exception:
            raise AdmissionManifestFailedSafe(
                "ADMISSION_MANIFEST_SERVICE_TOKEN_UNAVAILABLE"
            ) from exception
        if not isinstance(value, str) or not value:
            raise AdmissionManifestFailedSafe(
                "ADMISSION_MANIFEST_SERVICE_TOKEN_UNAVAILABLE"
            )
        return value


def _bind_request(
    execution: DriverExecutionRequest,
    permit: RuntimeExternalPermitFact,
) -> JavaAdmissionManifestResolveRequest:
    if not isinstance(execution, DriverExecutionRequest):
        raise TypeError("execution must be a DriverExecutionRequest")
    if not isinstance(permit, RuntimeExternalPermitFact):
        raise TypeError("permit must be a RuntimeExternalPermitFact")
    authority = execution.authority
    fence = execution.fence
    shared_binding_matches = (
        permit.tenant_id == authority.tenant_id == fence.tenant_id
        and permit.runtime_run_id
        == authority.runtime_run_id
        == fence.runtime_run_id
        and permit.task_step_id == authority.task_step_id
        and permit.task_execution_generation
        == authority.task_execution_generation
        == fence.task_execution_generation
        and permit.admission_contract_version
        == authority.admission_contract_version
        == fence.admission_contract_version
        == "2.2"
        and permit.admission_snapshot_id
        == authority.admission_snapshot_id
        == fence.admission_snapshot_id
        and permit.admission_snapshot_hash
        == authority.admission_snapshot_hash
        == fence.admission_snapshot_hash
        and permit.operation_kind == ExternalOperation.ADMISSION_RESOLVE
    )
    if not shared_binding_matches:
        raise AdmissionManifestFailedSafe("ADMISSION_MANIFEST_BINDING_INVALID")

    if permit.status not in {
        ExternalPermitStatus.ISSUED,
        ExternalPermitStatus.CONSUMED,
    }:
        raise AdmissionManifestFailedSafe("ADMISSION_MANIFEST_BINDING_INVALID")
    if (
        permit.lease_owner != authority.lease_owner
        or permit.lease_owner != fence.lease_owner
        or permit.lease_epoch != authority.lease_epoch
        or permit.lease_epoch != fence.lease_epoch
    ):
        raise AdmissionManifestFailedSafe("ADMISSION_MANIFEST_BINDING_INVALID")

    try:
        return JavaAdmissionManifestResolveRequest(
            tenant_id=authority.tenant_id,
            task_step_id=authority.task_step_id,
            execution_generation=authority.task_execution_generation,
            admission_snapshot_id=authority.admission_snapshot_id,
            admission_snapshot_hash=authority.admission_snapshot_hash,
            runtime_external_permit_id=permit.runtime_external_permit_id,
            permit_intent_id=permit.intent_id,
            permit_request_hash=permit.request_hash,
            lease_owner=permit.lease_owner,
            lease_epoch=permit.lease_epoch,
        )
    except (TypeError, ValueError) as exception:
        raise AdmissionManifestFailedSafe(
            "ADMISSION_MANIFEST_BINDING_INVALID"
        ) from exception


def _require_exact_manifest_binding(
    execution: DriverExecutionRequest,
    manifest: JavaAdmissionManifest,
) -> None:
    authority = execution.authority
    if (
        manifest.runtime_run_id != authority.runtime_run_id
        or manifest.tenant_id != authority.tenant_id
        or manifest.task_id != authority.task_run_id
        or manifest.task_step_id != authority.task_step_id
        or manifest.execution_generation != authority.task_execution_generation
        or manifest.admission_contract_version
        != authority.admission_contract_version
        or manifest.admission_snapshot_id != authority.admission_snapshot_id
        or manifest.admission_snapshot_hash != authority.admission_snapshot_hash
        or manifest.request_hash != authority.request_hash
        or manifest.idempotency_key != authority.idempotency_key
        or manifest.actor_user_id != authority.user_id
        or manifest.enterprise_agent_id != authority.agent_instance_id
        or manifest.point_reservation_id != authority.budget_reservation_id
    ):
        raise AdmissionManifestOutcomeUnknown("ADMISSION_MANIFEST_BINDING_INVALID")


def _assert_no_forbidden_manifest_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if normalized in _FORBIDDEN_MANIFEST_KEYS:
                raise ValueError("admission manifest contains a forbidden key")
            _assert_no_forbidden_manifest_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_forbidden_manifest_keys(nested)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("admission manifest contains a duplicate key")
        result[key] = value
    return result


async def _read_bounded_response(response: httpx.Response) -> tuple[bytes, bool]:
    content = bytearray()
    async for chunk in response.aiter_bytes(
        chunk_size=_ADMISSION_MANIFEST_RESPONSE_CHUNK_BYTES
    ):
        if len(content) + len(chunk) > _MAX_ADMISSION_MANIFEST_RESPONSE_BYTES:
            return b"", True
        content.extend(chunk)
    return bytes(content), False


def _is_json_content_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type, _, _ = value.partition(";")
    return media_type.strip().lower() == "application/json"


def _problem_code(content: bytes) -> str:
    try:
        body = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
        value = body.get("code") if isinstance(body, dict) else None
    except (TypeError, ValueError):
        value = None
    if isinstance(value, str) and _FAILURE_CODE_PATTERN.fullmatch(value):
        return value
    return "ADMISSION_MANIFEST_REJECTED"
