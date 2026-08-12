from __future__ import annotations

from dataclasses import dataclass, field
import os


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
    context_database_dsn: str | None = field(default=None, repr=False)
    context_database_pool_min_size: int = 1
    context_database_pool_max_size: int = 8
    context_database_connect_timeout_seconds: int = 5
    context_index_profile: str = "context-default-v1"
    service_jwt_public_key_ring_json: str | None = field(default=None, repr=False)
    service_jwt_clock_skew_seconds: int = 5

    def __post_init__(self) -> None:
        if self.context_database_pool_min_size > self.context_database_pool_max_size:
            raise ValueError("context database pool minimum cannot exceed maximum")
        if not self.context_index_profile:
            raise ValueError("context index profile must not be blank")
        if not 0 <= self.service_jwt_clock_skew_seconds <= 10:
            raise ValueError("service JWT clock skew must be between 0 and 10 seconds")

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        role = os.getenv("DIANLIAN_RUNTIME_ROLE", "runtime-api").strip()
        if role not in _ALLOWED_ROLES:
            allowed = ", ".join(sorted(_ALLOWED_ROLES))
            raise ValueError(f"DIANLIAN_RUNTIME_ROLE must be one of: {allowed}")

        context_database_dsn = os.getenv("DIANLIAN_CONTEXT_DATABASE_DSN")
        if context_database_dsn is not None:
            context_database_dsn = context_database_dsn.strip() or None
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
        )

    @property
    def ready(self) -> bool:
        if self.role == "context-worker":
            return self.context_enabled
        if self.role == "agent-worker":
            return self.agent_enabled and self.supervisor_enabled
        return True
