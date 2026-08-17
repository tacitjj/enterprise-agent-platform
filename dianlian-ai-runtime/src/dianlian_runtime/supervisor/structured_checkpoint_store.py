from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid5

from dianlian_runtime.harness.structured_admission_manifest import (
    JavaCapabilityStructuredAdmissionManifest,
)
from dianlian_runtime.harness.structured_model_receipt import (
    StructuredModelCallRequest,
    StructuredModelRequestReceipt,
)
from dianlian_runtime.supervisor.contracts import (
    FrozenJsonObject,
    LoadRuntimeStructuredCheckpointRequest,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeStructuredCheckpointFact,
    SaveRuntimeStructuredCheckpointRequest,
)
from dianlian_runtime.supervisor.driver import DriverFence


_CHECKPOINT_NAMESPACE = UUID("ec02e4ad-e9d0-5ac9-9255-8cd0b6988606")
_STATE_SCHEMA_VERSION = "structured-model-driver-state-v1"


class RuntimeStructuredCheckpointRejected(RuntimeError):
    """当前 Run fence 或预期 checkpoint CAS 未生效。"""


class RuntimeStructuredCheckpointContractViolation(RuntimeError):
    """受限仓储返回了冻结契约之外的证据。"""


class RuntimeStructuredCheckpointRepository(Protocol):
    def check_structured_checkpoint_capability(self) -> PrimitiveResult[bool]: ...

    def load_structured_checkpoint(
        self,
        request: LoadRuntimeStructuredCheckpointRequest,
    ) -> PrimitiveResult[RuntimeStructuredCheckpointFact]: ...

    def save_structured_checkpoint(
        self,
        request: SaveRuntimeStructuredCheckpointRequest,
    ) -> PrimitiveResult[RuntimeStructuredCheckpointFact]: ...


@dataclass(frozen=True, slots=True)
class StructuredReceiptRecord:
    """持久化的 exact Java 请求索引；不携带密钥、Provider 配置或模型结果。"""

    runtime_external_permit_id: UUID
    arm_event_id: UUID
    lease_owner: str
    lease_epoch: int
    model_call_id: UUID
    model_request_hash: str
    body_sha256: str

    @classmethod
    def from_receipt(
        cls,
        receipt: StructuredModelRequestReceipt,
    ) -> "StructuredReceiptRecord":
        request = receipt.request
        dispatch = request.dispatch_arm
        return cls(
            dispatch.runtime_external_permit_id,
            dispatch.arm_event_id,
            dispatch.lease_owner,
            dispatch.lease_epoch,
            request.model_call_id,
            request.model_request_hash,
            receipt.body_sha256,
        )

    @classmethod
    def from_document(cls, value: object) -> "StructuredReceiptRecord":
        if not isinstance(value, dict) or set(value) != {
            "runtimeExternalPermitId",
            "armEventId",
            "leaseOwner",
            "leaseEpoch",
            "modelCallId",
            "modelRequestHash",
            "bodySha256",
        }:
            raise RuntimeStructuredCheckpointContractViolation(
                "structured receipt record shape is invalid"
            )
        try:
            record = cls(
                UUID(str(value["runtimeExternalPermitId"])),
                UUID(str(value["armEventId"])),
                str(value["leaseOwner"]),
                _strict_positive_integer(value["leaseEpoch"]),
                UUID(str(value["modelCallId"])),
                str(value["modelRequestHash"]),
                str(value["bodySha256"]),
            )
            record._validate()
            return record
        except (TypeError, ValueError) as exception:
            raise RuntimeStructuredCheckpointContractViolation(
                "structured receipt record is invalid"
            ) from exception

    def to_document(self) -> dict[str, object]:
        self._validate()
        return {
            "runtimeExternalPermitId": str(self.runtime_external_permit_id),
            "armEventId": str(self.arm_event_id),
            "leaseOwner": self.lease_owner,
            "leaseEpoch": self.lease_epoch,
            "modelCallId": str(self.model_call_id),
            "modelRequestHash": self.model_request_hash,
            "bodySha256": self.body_sha256,
        }

    def restore_receipt(
        self,
        manifest: JavaCapabilityStructuredAdmissionManifest,
    ) -> StructuredModelRequestReceipt:
        body_request = StructuredModelCallRequest.model_validate(
            {
                "contractVersion": "1.0",
                "modelCallId": self.model_call_id,
                "idempotencyKey": f"structured-model-call:{self.model_call_id}",
                "modelRequestHash": self.model_request_hash,
                "admission": manifest.model_dump(mode="python", by_alias=True),
                "dispatchArm": {
                    "runtimeExternalPermitId": self.runtime_external_permit_id,
                    "leaseOwner": self.lease_owner,
                    "leaseEpoch": self.lease_epoch,
                    "armEventId": self.arm_event_id,
                },
            },
            strict=True,
        )
        exact_body = body_request.exact_body()
        return StructuredModelRequestReceipt(
            manifest.runtime_run_id,
            body_request,
            exact_body,
            self.body_sha256,
        )

    def _validate(self) -> None:
        for value in (
            self.runtime_external_permit_id,
            self.arm_event_id,
            self.model_call_id,
        ):
            if not isinstance(value, UUID) or value.int == 0:
                raise ValueError("structured receipt UUID must be non-nil")
        if (
            not isinstance(self.lease_owner, str)
            or not self.lease_owner
            or self.lease_owner != self.lease_owner.strip()
            or len(self.lease_owner) > 160
        ):
            raise ValueError("structured receipt leaseOwner is invalid")
        _strict_positive_integer(self.lease_epoch)
        for value in (self.model_request_hash, self.body_sha256):
            if not _is_hash(value):
                raise ValueError("structured receipt hash is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeStructuredState:
    """3.0 Driver 的最小持久状态：权威 Admission 与 exact receipt 历史。"""

    admission_manifest: JavaCapabilityStructuredAdmissionManifest
    receipts: tuple[StructuredReceiptRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.admission_manifest,
            JavaCapabilityStructuredAdmissionManifest,
        ):
            raise TypeError("admission_manifest must be a structured Admission")
        if not isinstance(self.receipts, tuple):
            raise TypeError("receipts must be a tuple")
        permit_ids: set[UUID] = set()
        arm_event_ids: set[UUID] = set()
        previous_epoch = 0
        for receipt in self.receipts:
            if not isinstance(receipt, StructuredReceiptRecord):
                raise TypeError("receipts must contain StructuredReceiptRecord")
            receipt._validate()
            if (
                receipt.runtime_external_permit_id in permit_ids
                or receipt.arm_event_id in arm_event_ids
                or receipt.lease_epoch <= previous_epoch
            ):
                raise ValueError("structured receipt history is not append-only")
            permit_ids.add(receipt.runtime_external_permit_id)
            arm_event_ids.add(receipt.arm_event_id)
            previous_epoch = receipt.lease_epoch

    def append_receipt(
        self,
        receipt: StructuredModelRequestReceipt,
    ) -> "RuntimeStructuredState":
        record = StructuredReceiptRecord.from_receipt(receipt)
        if record in self.receipts:
            return self
        if any(
            existing.runtime_external_permit_id == record.runtime_external_permit_id
            or existing.arm_event_id == record.arm_event_id
            or existing.lease_epoch >= record.lease_epoch
            for existing in self.receipts
        ):
            raise RuntimeStructuredCheckpointContractViolation(
                "structured receipt cannot replace persisted history"
            )
        return RuntimeStructuredState(
            self.admission_manifest,
            (*self.receipts, record),
        )

    def find_receipt(self, permit_id: UUID) -> StructuredModelRequestReceipt | None:
        for record in self.receipts:
            if record.runtime_external_permit_id == permit_id:
                return record.restore_receipt(self.admission_manifest)
        return None

    def find_current_receipt(
        self,
        fence: DriverFence,
        *,
        model_call_id: UUID,
        model_request_hash: str,
    ) -> StructuredModelRequestReceipt | None:
        """按当前 fence 和稳定模型意图精确恢复 receipt，不选择 latest/history。"""

        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if fence.admission_contract_version != "3.0":
            raise ValueError("structured receipt requires Admission 3.0")
        if (
            self.admission_manifest.tenant_id != fence.tenant_id
            or self.admission_manifest.runtime_run_id != fence.runtime_run_id
            or self.admission_manifest.execution_generation
            != fence.task_execution_generation
            or self.admission_manifest.admission_snapshot_id
            != fence.admission_snapshot_id
            or self.admission_manifest.admission_snapshot_hash
            != fence.admission_snapshot_hash
        ):
            raise RuntimeStructuredCheckpointContractViolation(
                "structured receipt history does not match the current fence"
            )
        matches = [
            record
            for record in self.receipts
            if record.lease_owner == fence.lease_owner
            and record.lease_epoch == fence.lease_epoch
            and record.model_call_id == model_call_id
            and record.model_request_hash == model_request_hash
        ]
        if len(matches) > 1:
            raise RuntimeStructuredCheckpointContractViolation(
                "structured current receipt is ambiguous"
            )
        return (
            matches[0].restore_receipt(self.admission_manifest)
            if matches
            else None
        )

    def to_document(self, fence: DriverFence, state_version: int) -> FrozenJsonObject:
        if fence.admission_contract_version != "3.0":
            raise ValueError("structured checkpoint requires Admission 3.0")
        manifest = self.admission_manifest
        if (
            manifest.tenant_id != fence.tenant_id
            or manifest.runtime_run_id != fence.runtime_run_id
            or manifest.execution_generation != fence.task_execution_generation
            or manifest.admission_snapshot_id != fence.admission_snapshot_id
            or manifest.admission_snapshot_hash != fence.admission_snapshot_hash
        ):
            raise ValueError("structured state does not match the Run fence")
        return FrozenJsonObject(
            {
                "schemaVersion": _STATE_SCHEMA_VERSION,
                "stateVersion": state_version,
                "tenantId": str(fence.tenant_id),
                "runtimeRunId": str(fence.runtime_run_id),
                "taskExecutionGeneration": fence.task_execution_generation,
                "admissionManifest": manifest.model_dump(mode="json", by_alias=True),
                "receipts": [receipt.to_document() for receipt in self.receipts],
            }
        )

    @classmethod
    def from_fact(
        cls,
        fact: RuntimeStructuredCheckpointFact,
    ) -> "RuntimeStructuredState":
        if not isinstance(fact, RuntimeStructuredCheckpointFact):
            raise TypeError("fact must be a RuntimeStructuredCheckpointFact")
        document = fact.state.to_builtin()
        try:
            manifest = JavaCapabilityStructuredAdmissionManifest.model_validate_json(
                json.dumps(
                    document["admissionManifest"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                strict=True,
            )
            receipts = tuple(
                StructuredReceiptRecord.from_document(value)
                for value in document["receipts"]
            )
            state = cls(manifest, receipts)
        except (TypeError, ValueError, KeyError) as exception:
            if isinstance(exception, RuntimeStructuredCheckpointContractViolation):
                raise
            raise RuntimeStructuredCheckpointContractViolation(
                "structured checkpoint document is invalid"
            ) from exception
        if (
            manifest.tenant_id != fact.tenant_id
            or manifest.runtime_run_id != fact.runtime_run_id
            or manifest.execution_generation != fact.task_execution_generation
        ):
            raise RuntimeStructuredCheckpointContractViolation(
                "structured checkpoint Admission identity drifted"
            )
        return state


class PostgresStructuredCheckpointStore:
    """共享 PostgreSQL 账本上的 3.0 专用异步 CAS facade。"""

    def __init__(self, repository: RuntimeStructuredCheckpointRepository) -> None:
        for method in (
            "check_structured_checkpoint_capability",
            "load_structured_checkpoint",
            "save_structured_checkpoint",
        ):
            if not callable(getattr(repository, method, None)):
                raise TypeError("repository lacks structured checkpoint primitives")
        self._repository = repository

    async def verify_capability(self) -> None:
        result = await asyncio.to_thread(
            self._repository.check_structured_checkpoint_capability
        )
        if (
            not isinstance(result, PrimitiveResult)
            or result.outcome != PrimitiveOutcome.FACT_RETURNED
            or result.fact is not True
        ):
            raise RuntimeStructuredCheckpointContractViolation(
                "structured checkpoint database capability is not ready"
            )

    async def load(
        self,
        fence: DriverFence,
    ) -> RuntimeStructuredCheckpointFact | None:
        request = LoadRuntimeStructuredCheckpointRequest(
            fence.tenant_id,
            fence.runtime_run_id,
            fence.task_execution_generation,
            fence.lease_owner,
            fence.lease_epoch,
        )
        result = await asyncio.to_thread(
            self._repository.load_structured_checkpoint,
            request,
        )
        if not isinstance(result, PrimitiveResult):
            raise RuntimeStructuredCheckpointContractViolation(
                "structured checkpoint load returned an invalid result"
            )
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return None
        fact = _require_fact(result)
        _verify_loaded_fact(fact, fence)
        RuntimeStructuredState.from_fact(fact)
        return fact

    async def save(
        self,
        fence: DriverFence,
        *,
        expected: RuntimeStructuredCheckpointFact | None,
        transition_code: str,
        state: RuntimeStructuredState,
    ) -> RuntimeStructuredCheckpointFact:
        if expected is not None:
            _verify_loaded_fact(expected, fence)
            previous = RuntimeStructuredState.from_fact(expected)
            _validate_transition(previous, state, transition_code)
        elif transition_code != "MANIFEST_RESOLVED" or state.receipts:
            raise RuntimeStructuredCheckpointContractViolation(
                "initial structured checkpoint must freeze only the Manifest"
            )
        expected_version = expected.state_version if expected is not None else 0
        document = state.to_document(fence, expected_version + 1)
        event_id = _stable_event_id(fence, transition_code, document)
        request = SaveRuntimeStructuredCheckpointRequest(
            fence.tenant_id,
            fence.runtime_run_id,
            fence.task_execution_generation,
            fence.lease_owner,
            fence.lease_epoch,
            expected.checkpoint_id if expected is not None else None,
            expected_version,
            event_id,
            f"structured-{expected_version + 1}-{event_id}",
            transition_code,
            document,
        )
        result = await asyncio.to_thread(
            self._repository.save_structured_checkpoint,
            request,
        )
        if not isinstance(result, PrimitiveResult):
            raise RuntimeStructuredCheckpointContractViolation(
                "structured checkpoint save returned an invalid result"
            )
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            raise RuntimeStructuredCheckpointRejected(
                "current Run fence or expected structured checkpoint was not applied"
            )
        fact = _require_fact(result)
        _verify_saved_fact(fact, request)
        RuntimeStructuredState.from_fact(fact)
        return fact


def _validate_transition(
    previous: RuntimeStructuredState,
    current: RuntimeStructuredState,
    transition_code: str,
) -> None:
    if previous.admission_manifest != current.admission_manifest:
        raise RuntimeStructuredCheckpointContractViolation(
            "structured Admission is immutable"
        )
    if (
        transition_code != "MODEL_RECEIPT_APPENDED"
        or len(current.receipts) != len(previous.receipts) + 1
        or current.receipts[:-1] != previous.receipts
    ):
        raise RuntimeStructuredCheckpointContractViolation(
            "structured checkpoint transition is invalid"
        )


def _stable_event_id(
    fence: DriverFence,
    transition_code: str,
    document: FrozenJsonObject,
) -> UUID:
    digest = hashlib.sha256(document.canonical.encode("utf-8")).hexdigest()
    name = json.dumps(
        [
            "structured-model-checkpoint-v1",
            str(fence.tenant_id),
            str(fence.runtime_run_id),
            fence.task_execution_generation,
            fence.lease_owner,
            fence.lease_epoch,
            transition_code,
            digest,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(_CHECKPOINT_NAMESPACE, name)


def _require_fact(
    result: PrimitiveResult[RuntimeStructuredCheckpointFact],
) -> RuntimeStructuredCheckpointFact:
    if not isinstance(result.fact, RuntimeStructuredCheckpointFact):
        raise RuntimeStructuredCheckpointContractViolation(
            "structured checkpoint primitive returned an invalid fact"
        )
    return result.fact


def _verify_loaded_fact(
    fact: RuntimeStructuredCheckpointFact,
    fence: DriverFence,
) -> None:
    if (
        fact.tenant_id != fence.tenant_id
        or fact.runtime_run_id != fence.runtime_run_id
        or fact.task_execution_generation != fence.task_execution_generation
    ):
        raise RuntimeStructuredCheckpointContractViolation(
            "structured checkpoint fact does not match the Run identity"
        )


def _verify_saved_fact(
    fact: RuntimeStructuredCheckpointFact,
    request: SaveRuntimeStructuredCheckpointRequest,
) -> None:
    if (
        fact.tenant_id != request.tenant_id
        or fact.runtime_run_id != request.runtime_run_id
        or fact.task_execution_generation != request.task_execution_generation
        or fact.checkpoint_id != request.checkpoint_id
        or fact.previous_checkpoint_id != request.expected_checkpoint_id
        or fact.state_version != request.expected_state_version + 1
        or fact.state != request.state
        or fact.transition_code != request.transition_code
        or fact.event_id != request.event_id
        or fact.created_by != request.lease_owner
        or fact.lease_epoch != request.lease_epoch
    ):
        raise RuntimeStructuredCheckpointContractViolation(
            "structured checkpoint evidence does not match the exact command"
        )


def _strict_positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("value must be a positive integer")
    return value


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
