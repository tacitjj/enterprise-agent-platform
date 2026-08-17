from __future__ import annotations

from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.harness.admission_manifest import JavaAdmissionManifestClient
from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelGatewayClient,
)
from dianlian_runtime.harness.governed_run_driver import (
    GovernedInitialRunExecutionDriver,
)
from dianlian_runtime.harness.postgres_governed_h12_slots import (
    PostgresGovernedH12SlotsFactory,
)
from dianlian_runtime.harness.governed_tool_gateway import GovernedToolGatewayClient
from dianlian_runtime.harness.h12_gateway import H12RuntimeServiceJwtIssuer
from dianlian_runtime.harness.structured_model_gateway import (
    StructuredModelGatewayClient,
)
from dianlian_runtime.harness.structured_run_driver import (
    StructuredRunExecutionDriver,
)
from dianlian_runtime.supervisor.admission_permit_issuer import (
    DormantAdmissionPermitIssuer,
)
from dianlian_runtime.supervisor.model_permit_issuer import DormantModelPermitIssuer
from dianlian_runtime.supervisor.h12_checkpoint_store import (
    PostgresH12CheckpointStore,
)
from dianlian_runtime.supervisor.postgres import PostgresRunSupervisorRepository
from dianlian_runtime.supervisor.service import DormantRunSupervisorWorker, RunSupervisor
from dianlian_runtime.supervisor.structured_checkpoint_store import (
    PostgresStructuredCheckpointStore,
)
from dianlian_runtime.supervisor.tool_permit_issuer import DormantToolPermitIssuer


def create_governed_h12_run_supervisor(settings: RuntimeSettings) -> RunSupervisor:
    """Compose the governed worker only after its explicit opt-in is validated."""
    if not settings.governed_h12_driver_enabled:
        raise ValueError("governed H12 Driver is not enabled")
    dsn = settings.run_supervisor_database_dsn
    agent_name = settings.run_supervisor_agent_name
    data_dir = settings.governed_h12_data_dir
    base_url = settings.runtime_model_service_base_url
    key_id = settings.runtime_model_service_jwt_key_id
    private_key_path = settings.runtime_model_service_jwt_private_key_path
    if (
        dsn is None
        or agent_name is None
        or base_url is None
        or key_id is None
        or private_key_path is None
    ):
        raise RuntimeError("governed H12 Driver configuration is incomplete")

    options = (
        "-c statement_timeout="
        f"{settings.run_supervisor_database_statement_timeout_seconds * 1000} "
        "-c lock_timeout="
        f"{settings.run_supervisor_database_lock_timeout_seconds * 1000}"
    )

    def connect() -> Connection[dict[str, Any]]:
        return psycopg.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=settings.run_supervisor_database_connect_timeout_seconds,
            options=options,
        )

    repository = PostgresRunSupervisorRepository(connect)
    jwt_issuer = H12RuntimeServiceJwtIssuer(
        key_id=key_id,
        private_key_path=private_key_path,
        ttl_seconds=settings.runtime_model_service_jwt_ttl_seconds,
    )
    slot_options: dict[str, object]
    if settings.governed_h12_store_backend == "local":
        if data_dir is None:
            raise RuntimeError("local governed H12 data directory is missing")
        slot_options = {"data_dir": data_dir}
    else:
        slot_options = {
            "slots_factory": PostgresGovernedH12SlotsFactory(
                PostgresH12CheckpointStore(repository)
            )
        }

    driver = GovernedInitialRunExecutionDriver(
        **slot_options,
        admission_permit_issuer=DormantAdmissionPermitIssuer(repository),
        admission_manifest_client=JavaAdmissionManifestClient(
            base_url=base_url,
            jwt_issuer=jwt_issuer,
            timeout_seconds=settings.runtime_model_service_timeout_seconds,
        ),
        model_permit_issuer=DormantModelPermitIssuer(repository),
        model_gateway=GovernedInitialModelGatewayClient(
            base_url=base_url,
            jwt_issuer=jwt_issuer,
            timeout_seconds=settings.runtime_model_service_timeout_seconds,
        ),
        tool_permit_issuer=DormantToolPermitIssuer(repository),
        tool_gateway=GovernedToolGatewayClient(
            base_url=base_url,
            jwt_issuer=jwt_issuer,
            timeout_seconds=settings.runtime_model_service_timeout_seconds,
        ),
        permit_ttl_seconds=settings.governed_h12_permit_ttl_seconds,
    )
    return DormantRunSupervisorWorker(
        repository,
        driver,
        runtime_version=settings.service_version,
        agent_name=agent_name,
        admission_contract_version="2.2",
        lease_seconds=settings.run_supervisor_lease_seconds,
    )


def create_structured_run_supervisor(settings: RuntimeSettings) -> RunSupervisor:
    """仅在显式选择 3.0 档位后装配结构化 OneCall worker。"""
    if not settings.structured_driver_enabled:
        raise ValueError("structured Driver is not enabled")
    dsn = settings.run_supervisor_database_dsn
    agent_name = settings.run_supervisor_agent_name
    base_url = settings.runtime_model_service_base_url
    key_id = settings.runtime_model_service_jwt_key_id
    private_key_path = settings.runtime_model_service_jwt_private_key_path
    if (
        dsn is None
        or agent_name is None
        or base_url is None
        or key_id is None
        or private_key_path is None
    ):
        raise RuntimeError("structured Driver configuration is incomplete")

    options = (
        "-c statement_timeout="
        f"{settings.run_supervisor_database_statement_timeout_seconds * 1000} "
        "-c lock_timeout="
        f"{settings.run_supervisor_database_lock_timeout_seconds * 1000}"
    )

    def connect() -> Connection[dict[str, Any]]:
        return psycopg.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=settings.run_supervisor_database_connect_timeout_seconds,
            options=options,
        )

    repository = PostgresRunSupervisorRepository(connect)
    jwt_issuer = H12RuntimeServiceJwtIssuer(
        key_id=key_id,
        private_key_path=private_key_path,
        ttl_seconds=settings.runtime_model_service_jwt_ttl_seconds,
    )
    driver = StructuredRunExecutionDriver(
        checkpoint_store=PostgresStructuredCheckpointStore(repository),
        admission_permit_issuer=DormantAdmissionPermitIssuer(repository),
        admission_manifest_client=JavaAdmissionManifestClient(
            base_url=base_url,
            jwt_issuer=jwt_issuer,
            timeout_seconds=settings.runtime_model_service_timeout_seconds,
        ),
        model_permit_issuer=DormantModelPermitIssuer(repository),
        model_gateway=StructuredModelGatewayClient(
            base_url=base_url,
            jwt_issuer=jwt_issuer,
            timeout_seconds=settings.runtime_model_service_timeout_seconds,
        ),
        permit_ttl_seconds=settings.structured_driver_permit_ttl_seconds,
    )
    return DormantRunSupervisorWorker(
        repository,
        driver,
        runtime_version=settings.service_version,
        agent_name=agent_name,
        admission_contract_version="3.0",
        lease_seconds=settings.run_supervisor_lease_seconds,
    )
