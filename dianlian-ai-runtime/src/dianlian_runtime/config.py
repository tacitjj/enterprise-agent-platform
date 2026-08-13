from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_ALLOWED_ROLES = frozenset({"runtime-api", "context-worker", "agent-worker"})


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
    permit_authorizer_enabled: bool = False
    permit_authorizer_database_dsn: str | None = field(default=None, repr=False)
    permit_authorizer_database_connect_timeout_seconds: int = 5
    permit_authorizer_database_statement_timeout_seconds: int = 5
    permit_authorizer_database_lock_timeout_seconds: int = 5
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
) -> None:
    if value is None:
        raise ValueError(
            "DeerFlow H1 requires DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL"
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
