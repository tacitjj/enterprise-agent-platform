from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_ALLOWED_ROLES = frozenset({"runtime-api", "context-worker", "agent-worker"})
_ALLOWED_RUNTIME_ENVIRONMENTS = frozenset({"local", "staging", "production"})
_ALLOWED_GOVERNED_H12_STORE_BACKENDS = frozenset({"local", "postgres"})


def _read_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of true/false, 1/0, yes/no, or on/off")


def _read_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exception:
        raise ValueError(f"{name} must be an integer") from exception
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    service_name: str
    service_version: str
    role: str
    context_enabled: bool
    agent_enabled: bool
    supervisor_enabled: bool
    governed_h12_driver_enabled: bool = False
    # 结构化 3.0 Driver 使用独立开关，不能与 H12 在同一 worker 中同时领取 Run。
    structured_driver_enabled: bool = False
    runtime_environment: str = "production"
    governed_h12_store_backend: str = "postgres"
    run_supervisor_database_dsn: str | None = field(default=None, repr=False)
    run_supervisor_database_connect_timeout_seconds: int = 5
    run_supervisor_database_statement_timeout_seconds: int = 5
    run_supervisor_database_lock_timeout_seconds: int = 5
    run_supervisor_agent_name: str | None = None
    run_supervisor_lease_seconds: int = 30
    governed_h12_data_dir: Path | None = field(default=None, repr=False)
    governed_h12_permit_ttl_seconds: int = 10
    structured_driver_permit_ttl_seconds: int = 10
    permit_authorizer_enabled: bool = False
    permit_authorizer_database_dsn: str | None = field(default=None, repr=False)
    permit_authorizer_database_connect_timeout_seconds: int = 5
    permit_authorizer_database_statement_timeout_seconds: int = 5
    permit_authorizer_database_lock_timeout_seconds: int = 5
    dispatch_authorizer_enabled: bool = False
    dispatch_authorizer_database_dsn: str | None = field(default=None, repr=False)
    dispatch_authorizer_database_connect_timeout_seconds: int = 5
    dispatch_authorizer_database_statement_timeout_seconds: int = 5
    dispatch_authorizer_database_lock_timeout_seconds: int = 5
    outcome_reconciler_enabled: bool = False
    outcome_reconciler_database_dsn: str | None = field(default=None, repr=False)
    outcome_reconciler_database_connect_timeout_seconds: int = 5
    outcome_reconciler_database_statement_timeout_seconds: int = 5
    outcome_reconciler_database_lock_timeout_seconds: int = 5
    run_admitter_enabled: bool = False
    run_admitter_database_dsn: str | None = field(default=None, repr=False)
    run_admitter_database_connect_timeout_seconds: int = 5
    run_admitter_database_statement_timeout_seconds: int = 5
    run_admitter_database_lock_timeout_seconds: int = 5
    run_observer_enabled: bool = False
    run_observer_database_dsn: str | None = field(default=None, repr=False)
    run_observer_database_connect_timeout_seconds: int = 5
    run_observer_database_statement_timeout_seconds: int = 5
    run_observer_database_lock_timeout_seconds: int = 5
    run_controller_enabled: bool = False
    run_controller_database_dsn: str | None = field(default=None, repr=False)
    run_controller_database_connect_timeout_seconds: int = 5
    run_controller_database_statement_timeout_seconds: int = 5
    run_controller_database_lock_timeout_seconds: int = 5
    context_database_dsn: str | None = field(default=None, repr=False)
    context_database_pool_min_size: int = 1
    context_database_pool_max_size: int = 8
    context_database_connect_timeout_seconds: int = 5
    context_index_profile: str = "context-default-v1"
    service_jwt_public_key_ring_json: str | None = field(default=None, repr=False)
    service_jwt_clock_skew_seconds: int = 5
    deerflow_h0_enabled: bool = False
    deerflow_source_root: Path | None = field(default=None, repr=False)
    deerflow_data_dir: Path | None = field(default=None, repr=False)
    deerflow_h1_enabled: bool = False
    deerflow_h1_data_dir: Path | None = field(default=None, repr=False)
    runtime_model_service_base_url: str | None = field(default=None, repr=False)
    runtime_model_service_jwt_key_id: str | None = field(default=None, repr=False)
    runtime_model_service_jwt_private_key_path: Path | None = field(
        default=None,
        repr=False,
    )
    runtime_model_service_jwt_ttl_seconds: int = 30
    runtime_model_service_timeout_seconds: int = 60
    runtime_model_service_allow_insecure_loopback: bool = False

    def __post_init__(self) -> None:
        if self.runtime_environment not in _ALLOWED_RUNTIME_ENVIRONMENTS:
            allowed = ", ".join(sorted(_ALLOWED_RUNTIME_ENVIRONMENTS))
            raise ValueError(f"runtime environment must be one of: {allowed}")
        if self.governed_h12_store_backend not in _ALLOWED_GOVERNED_H12_STORE_BACKENDS:
            allowed = ", ".join(sorted(_ALLOWED_GOVERNED_H12_STORE_BACKENDS))
            raise ValueError(f"governed H12 store backend must be one of: {allowed}")
        if not 1 <= self.run_supervisor_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "run supervisor database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.run_supervisor_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "run supervisor database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.run_supervisor_database_lock_timeout_seconds
            <= self.run_supervisor_database_statement_timeout_seconds
        ):
            raise ValueError(
                "run supervisor database lock timeout must be positive and not exceed statement timeout"
            )
        if self.run_supervisor_agent_name is not None and not (
            1 <= len(self.run_supervisor_agent_name) <= 128
        ):
            raise ValueError("run supervisor agent name is outside its allowed range")
        if not 5 <= self.run_supervisor_lease_seconds <= 3600:
            raise ValueError("run supervisor lease must be between 5 and 3600 seconds")
        if not 1 <= self.governed_h12_permit_ttl_seconds <= 60:
            raise ValueError("governed H12 permit TTL must be between 1 and 60 seconds")
        if self.governed_h12_permit_ttl_seconds >= self.run_supervisor_lease_seconds:
            raise ValueError("governed H12 permit TTL must be shorter than the Run lease")
        if not 1 <= self.structured_driver_permit_ttl_seconds <= 60:
            raise ValueError("structured Driver permit TTL must be between 1 and 60 seconds")
        if self.structured_driver_permit_ttl_seconds >= self.run_supervisor_lease_seconds:
            raise ValueError("structured Driver permit TTL must be shorter than the Run lease")
        if self.governed_h12_driver_enabled and self.structured_driver_enabled:
            raise ValueError("governed H12 and structured Drivers are mutually exclusive")
        if self.governed_h12_driver_enabled:
            if (
                self.governed_h12_store_backend == "local"
                and self.runtime_environment != "local"
            ):
                raise ValueError(
                    "governed H12 SQLite storage can only be enabled in the local runtime environment"
                )
            if self.role != "agent-worker":
                raise ValueError(
                    "governed H12 Driver can only be enabled for the agent-worker role"
                )
            if not self.agent_enabled or not self.supervisor_enabled:
                raise ValueError(
                    "governed H12 Driver requires agent and Run Supervisor capabilities"
                )
            if self.run_supervisor_database_dsn is None:
                raise ValueError(
                    "governed H12 Driver requires DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN"
                )
            if self.run_supervisor_agent_name is None:
                raise ValueError(
                    "governed H12 Driver requires DIANLIAN_RUN_SUPERVISOR_AGENT_NAME"
                )
            if (
                self.governed_h12_store_backend == "local"
                and self.governed_h12_data_dir is None
            ):
                raise ValueError(
                    "governed H12 Driver requires DIANLIAN_GOVERNED_H12_DATA_DIR"
                )
            if (
                self.governed_h12_store_backend == "postgres"
                and self.governed_h12_data_dir is not None
            ):
                raise ValueError(
                    "PostgreSQL governed H12 storage does not accept a local data directory"
                )
            _validate_internal_base_url(
                self.runtime_model_service_base_url,
                allow_insecure_loopback=(
                    self.runtime_model_service_allow_insecure_loopback
                ),
            )
            if not self.runtime_model_service_jwt_key_id:
                raise ValueError(
                    "governed H12 Driver requires DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID"
                )
            if self.runtime_model_service_jwt_private_key_path is None:
                raise ValueError(
                    "governed H12 Driver requires DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH"
                )
        if self.structured_driver_enabled:
            if self.role != "agent-worker":
                raise ValueError(
                    "structured Driver can only be enabled for the agent-worker role"
                )
            if not self.agent_enabled or not self.supervisor_enabled:
                raise ValueError(
                    "structured Driver requires agent and Run Supervisor capabilities"
                )
            if self.run_supervisor_database_dsn is None:
                raise ValueError(
                    "structured Driver requires DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN"
                )
            if self.run_supervisor_agent_name is None:
                raise ValueError(
                    "structured Driver requires DIANLIAN_RUN_SUPERVISOR_AGENT_NAME"
                )
            _validate_internal_base_url(
                self.runtime_model_service_base_url,
                allow_insecure_loopback=(
                    self.runtime_model_service_allow_insecure_loopback
                ),
                feature="structured Driver",
            )
            if not self.runtime_model_service_jwt_key_id:
                raise ValueError(
                    "structured Driver requires DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID"
                )
            if self.runtime_model_service_jwt_private_key_path is None:
                raise ValueError(
                    "structured Driver requires DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH"
                )
        if self.permit_authorizer_enabled and self.role != "runtime-api":
            raise ValueError("permit authorizer API can only be enabled for runtime-api")
        if not 1 <= self.permit_authorizer_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "permit authorizer database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.permit_authorizer_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "permit authorizer database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.permit_authorizer_database_lock_timeout_seconds
            <= self.permit_authorizer_database_statement_timeout_seconds
        ):
            raise ValueError(
                "permit authorizer database lock timeout must be positive and not exceed statement timeout"
            )
        if self.dispatch_authorizer_enabled and self.role != "runtime-api":
            raise ValueError("dispatch authorizer API can only be enabled for runtime-api")
        if not 1 <= self.dispatch_authorizer_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "dispatch authorizer database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.dispatch_authorizer_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "dispatch authorizer database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.dispatch_authorizer_database_lock_timeout_seconds
            <= self.dispatch_authorizer_database_statement_timeout_seconds
        ):
            raise ValueError(
                "dispatch authorizer database lock timeout must be positive and not exceed statement timeout"
            )
        if self.outcome_reconciler_enabled and self.role != "runtime-api":
            raise ValueError("outcome reconciler API can only be enabled for runtime-api")
        if not 1 <= self.outcome_reconciler_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "outcome reconciler database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.outcome_reconciler_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "outcome reconciler database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.outcome_reconciler_database_lock_timeout_seconds
            <= self.outcome_reconciler_database_statement_timeout_seconds
        ):
            raise ValueError(
                "outcome reconciler database lock timeout must be positive and not exceed statement timeout"
            )
        if self.run_admitter_enabled and self.role != "runtime-api":
            raise ValueError("Run admitter API can only be enabled for runtime-api")
        if not 1 <= self.run_admitter_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "Run admitter database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.run_admitter_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "Run admitter database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.run_admitter_database_lock_timeout_seconds
            <= self.run_admitter_database_statement_timeout_seconds
        ):
            raise ValueError(
                "Run admitter database lock timeout must be positive and not exceed statement timeout"
            )
        if self.run_observer_enabled and self.role != "runtime-api":
            raise ValueError("Run observer API can only be enabled for runtime-api")
        if not 1 <= self.run_observer_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "Run observer database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.run_observer_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "Run observer database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.run_observer_database_lock_timeout_seconds
            <= self.run_observer_database_statement_timeout_seconds
        ):
            raise ValueError(
                "Run observer database lock timeout must be positive and not exceed statement timeout"
            )
        if self.run_controller_enabled and self.role != "runtime-api":
            raise ValueError("Run controller API can only be enabled for runtime-api")
        if not 1 <= self.run_controller_database_connect_timeout_seconds <= 60:
            raise ValueError(
                "Run controller database connect timeout must be between 1 and 60 seconds"
            )
        if not 1 <= self.run_controller_database_statement_timeout_seconds <= 30:
            raise ValueError(
                "Run controller database statement timeout must be between 1 and 30 seconds"
            )
        if not (
            1
            <= self.run_controller_database_lock_timeout_seconds
            <= self.run_controller_database_statement_timeout_seconds
        ):
            raise ValueError(
                "Run controller database lock timeout must be positive and not exceed statement timeout"
            )
        if self.context_database_pool_min_size > self.context_database_pool_max_size:
            raise ValueError("context database pool minimum cannot exceed maximum")
        if not self.context_index_profile:
            raise ValueError("context index profile must not be blank")
        if not 0 <= self.service_jwt_clock_skew_seconds <= 10:
            raise ValueError("service JWT clock skew must be between 0 and 10 seconds")
        if self.deerflow_h0_enabled:
            if self.role != "runtime-api":
                raise ValueError("DeerFlow H0 API can only be enabled for the runtime-api role")
            if self.deerflow_source_root is None:
                raise ValueError("DeerFlow H0 requires DIANLIAN_DEERFLOW_SOURCE_ROOT")
            if self.deerflow_data_dir is None:
                raise ValueError("DeerFlow H0 requires DIANLIAN_DEERFLOW_DATA_DIR")
        if self.deerflow_h1_enabled:
            if self.role != "runtime-api":
                raise ValueError("DeerFlow H1 API can only be enabled for the runtime-api role")
            if self.deerflow_h1_data_dir is None:
                raise ValueError("DeerFlow H1 requires DIANLIAN_DEERFLOW_H1_DATA_DIR")
            _validate_internal_base_url(
                self.runtime_model_service_base_url,
                allow_insecure_loopback=(
                    self.runtime_model_service_allow_insecure_loopback
                ),
            )
            if self.deerflow_source_root is None:
                raise ValueError("DeerFlow H1 requires DIANLIAN_DEERFLOW_SOURCE_ROOT")
            if not self.runtime_model_service_jwt_key_id:
                raise ValueError(
                    "DeerFlow H1 requires DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID"
                )
            if self.runtime_model_service_jwt_private_key_path is None:
                raise ValueError(
                    "DeerFlow H1 requires DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH"
                )
        if not 1 <= self.runtime_model_service_jwt_ttl_seconds <= 60:
            raise ValueError("runtime model service JWT TTL must be between 1 and 60 seconds")
        if not 1 <= self.runtime_model_service_timeout_seconds <= 300:
            raise ValueError("runtime model service timeout must be between 1 and 300 seconds")

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        role = os.getenv("DIANLIAN_RUNTIME_ROLE", "runtime-api").strip()
        if role not in _ALLOWED_ROLES:
            allowed = ", ".join(sorted(_ALLOWED_ROLES))
            raise ValueError(f"DIANLIAN_RUNTIME_ROLE must be one of: {allowed}")

        context_database_dsn = os.getenv("DIANLIAN_CONTEXT_DATABASE_DSN")
        if context_database_dsn is not None:
            context_database_dsn = context_database_dsn.strip() or None
        permit_authorizer_database_dsn = os.getenv(
            "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_DSN"
        )
        if permit_authorizer_database_dsn is not None:
            permit_authorizer_database_dsn = (
                permit_authorizer_database_dsn.strip() or None
            )
        dispatch_authorizer_database_dsn = os.getenv(
            "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_DSN"
        )
        if dispatch_authorizer_database_dsn is not None:
            dispatch_authorizer_database_dsn = (
                dispatch_authorizer_database_dsn.strip() or None
            )
        outcome_reconciler_database_dsn = os.getenv(
            "DIANLIAN_OUTCOME_RECONCILER_DATABASE_DSN"
        )
        if outcome_reconciler_database_dsn is not None:
            outcome_reconciler_database_dsn = (
                outcome_reconciler_database_dsn.strip() or None
            )
        run_admitter_database_dsn = os.getenv(
            "DIANLIAN_RUN_ADMITTER_DATABASE_DSN"
        )
        if run_admitter_database_dsn is not None:
            run_admitter_database_dsn = run_admitter_database_dsn.strip() or None
        run_observer_database_dsn = os.getenv(
            "DIANLIAN_RUN_OBSERVER_DATABASE_DSN"
        )
        if run_observer_database_dsn is not None:
            run_observer_database_dsn = run_observer_database_dsn.strip() or None
        run_controller_database_dsn = os.getenv(
            "DIANLIAN_RUN_CONTROLLER_DATABASE_DSN"
        )
        if run_controller_database_dsn is not None:
            run_controller_database_dsn = run_controller_database_dsn.strip() or None
        run_supervisor_database_dsn = os.getenv(
            "DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN"
        )
        if run_supervisor_database_dsn is not None:
            run_supervisor_database_dsn = run_supervisor_database_dsn.strip() or None
        service_jwt_public_key_ring_json = os.getenv(
            "DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON"
        )
        if service_jwt_public_key_ring_json is not None:
            service_jwt_public_key_ring_json = (
                service_jwt_public_key_ring_json.strip() or None
            )

        return cls(
            service_name="dianlian-ai-runtime",
            service_version=os.getenv("DIANLIAN_RUNTIME_VERSION", "0.1.0").strip(),
            role=role,
            context_enabled=_read_bool("DIANLIAN_CONTEXT_ENABLED"),
            agent_enabled=_read_bool("DIANLIAN_AGENT_ENABLED"),
            supervisor_enabled=_read_bool("DIANLIAN_RUN_SUPERVISOR_ENABLED"),
            governed_h12_driver_enabled=_read_bool(
                "DIANLIAN_GOVERNED_H12_DRIVER_ENABLED"
            ),
            structured_driver_enabled=_read_bool(
                "DIANLIAN_STRUCTURED_DRIVER_ENABLED"
            ),
            runtime_environment=os.getenv(
                "DIANLIAN_RUNTIME_ENVIRONMENT",
                "production",
            )
            .strip()
            .lower(),
            governed_h12_store_backend=os.getenv(
                "DIANLIAN_GOVERNED_H12_STORE_BACKEND",
                "postgres",
            )
            .strip()
            .lower(),
            run_supervisor_database_dsn=run_supervisor_database_dsn,
            run_supervisor_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_RUN_SUPERVISOR_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            run_supervisor_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_RUN_SUPERVISOR_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_supervisor_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_RUN_SUPERVISOR_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_supervisor_agent_name=_read_optional_text(
                "DIANLIAN_RUN_SUPERVISOR_AGENT_NAME"
            ),
            run_supervisor_lease_seconds=_read_int(
                "DIANLIAN_RUN_SUPERVISOR_LEASE_SECONDS",
                30,
                minimum=5,
                maximum=3600,
            ),
            governed_h12_data_dir=_read_path("DIANLIAN_GOVERNED_H12_DATA_DIR"),
            governed_h12_permit_ttl_seconds=_read_int(
                "DIANLIAN_GOVERNED_H12_PERMIT_TTL_SECONDS",
                10,
                minimum=1,
                maximum=60,
            ),
            structured_driver_permit_ttl_seconds=_read_int(
                "DIANLIAN_STRUCTURED_DRIVER_PERMIT_TTL_SECONDS",
                10,
                minimum=1,
                maximum=60,
            ),
            permit_authorizer_enabled=_read_bool(
                "DIANLIAN_PERMIT_AUTHORIZER_ENABLED"
            ),
            permit_authorizer_database_dsn=permit_authorizer_database_dsn,
            permit_authorizer_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            permit_authorizer_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            permit_authorizer_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            dispatch_authorizer_enabled=_read_bool(
                "DIANLIAN_DISPATCH_AUTHORIZER_ENABLED"
            ),
            dispatch_authorizer_database_dsn=dispatch_authorizer_database_dsn,
            dispatch_authorizer_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            dispatch_authorizer_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            dispatch_authorizer_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            outcome_reconciler_enabled=_read_bool(
                "DIANLIAN_OUTCOME_RECONCILER_ENABLED"
            ),
            outcome_reconciler_database_dsn=outcome_reconciler_database_dsn,
            outcome_reconciler_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_OUTCOME_RECONCILER_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            outcome_reconciler_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_OUTCOME_RECONCILER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            outcome_reconciler_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_OUTCOME_RECONCILER_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_admitter_enabled=_read_bool(
                "DIANLIAN_RUN_ADMITTER_ENABLED"
            ),
            run_admitter_database_dsn=run_admitter_database_dsn,
            run_admitter_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_RUN_ADMITTER_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            run_admitter_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_RUN_ADMITTER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_admitter_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_RUN_ADMITTER_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_observer_enabled=_read_bool(
                "DIANLIAN_RUN_OBSERVER_ENABLED"
            ),
            run_observer_database_dsn=run_observer_database_dsn,
            run_observer_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_RUN_OBSERVER_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            run_observer_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_RUN_OBSERVER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_observer_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_RUN_OBSERVER_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_controller_enabled=_read_bool(
                "DIANLIAN_RUN_CONTROLLER_ENABLED"
            ),
            run_controller_database_dsn=run_controller_database_dsn,
            run_controller_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_RUN_CONTROLLER_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            run_controller_database_statement_timeout_seconds=_read_int(
                "DIANLIAN_RUN_CONTROLLER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            run_controller_database_lock_timeout_seconds=_read_int(
                "DIANLIAN_RUN_CONTROLLER_DATABASE_LOCK_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
            context_database_dsn=context_database_dsn,
            context_database_pool_min_size=_read_int(
                "DIANLIAN_CONTEXT_DATABASE_POOL_MIN_SIZE",
                1,
                minimum=0,
                maximum=32,
            ),
            context_database_pool_max_size=_read_int(
                "DIANLIAN_CONTEXT_DATABASE_POOL_MAX_SIZE",
                8,
                minimum=1,
                maximum=128,
            ),
            context_database_connect_timeout_seconds=_read_int(
                "DIANLIAN_CONTEXT_DATABASE_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=60,
            ),
            context_index_profile=os.getenv(
                "DIANLIAN_CONTEXT_INDEX_PROFILE",
                "context-default-v1",
            ).strip(),
            service_jwt_public_key_ring_json=service_jwt_public_key_ring_json,
            service_jwt_clock_skew_seconds=_read_int(
                "DIANLIAN_SERVICE_JWT_CLOCK_SKEW_SECONDS",
                5,
                minimum=0,
                maximum=10,
            ),
            deerflow_h0_enabled=_read_bool("DIANLIAN_DEERFLOW_H0_ENABLED"),
            deerflow_source_root=_read_path("DIANLIAN_DEERFLOW_SOURCE_ROOT"),
            deerflow_data_dir=_read_path("DIANLIAN_DEERFLOW_DATA_DIR"),
            deerflow_h1_enabled=_read_bool("DIANLIAN_DEERFLOW_H1_ENABLED"),
            deerflow_h1_data_dir=_read_path("DIANLIAN_DEERFLOW_H1_DATA_DIR"),
            runtime_model_service_base_url=_read_optional_text(
                "DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL"
            ),
            runtime_model_service_jwt_key_id=_read_optional_text(
                "DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID"
            ),
            runtime_model_service_jwt_private_key_path=_read_path(
                "DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH"
            ),
            runtime_model_service_jwt_ttl_seconds=_read_int(
                "DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_TTL_SECONDS",
                30,
                minimum=1,
                maximum=60,
            ),
            runtime_model_service_timeout_seconds=_read_int(
                "DIANLIAN_RUNTIME_MODEL_SERVICE_TIMEOUT_SECONDS",
                60,
                minimum=1,
                maximum=300,
            ),
            runtime_model_service_allow_insecure_loopback=_read_bool(
                "DIANLIAN_RUNTIME_MODEL_SERVICE_ALLOW_INSECURE_LOOPBACK"
            ),
        )

    @property
    def ready(self) -> bool:
        if self.role == "context-worker":
            return self.context_enabled
        if self.role == "agent-worker":
            return self.agent_enabled and self.supervisor_enabled
        return True


def _read_path(name: str) -> Path | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    return Path(raw_value.strip())


def _read_optional_text(name: str) -> str | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    return raw_value.strip()


def _validate_internal_base_url(
    value: str | None,
    *,
    allow_insecure_loopback: bool,
    feature: str = "DeerFlow H1",
) -> None:
    if value is None:
        raise ValueError(
            f"{feature} requires DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL"
        )
    parsed = urlsplit(value)
    loopback_http = (
        allow_insecure_loopback
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    )
    if (
        parsed.scheme != "https"
        and not loopback_http
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("runtime model service base URL is invalid")
