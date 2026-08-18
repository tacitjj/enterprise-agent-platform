from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit

from dianlian_runtime.content_normalization.contracts import ParserEngine


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _read_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean")


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exception:
        raise ValueError(f"{name} must be an integer") from exception
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class ContentNormalizationSettings:
    """独立解析进程配置；引擎、来源 Host 与上游地址都必须显式冻结。"""

    enabled: bool = False
    engine: ParserEngine | None = None
    allowed_source_hosts: tuple[str, ...] = ()
    parser_base_url: str | None = None
    parser_api_key: str | None = field(default=None, repr=False)
    source_fetch_timeout_seconds: int = 10
    parser_connect_timeout_seconds: int = 3
    parser_read_timeout_seconds: int = 45
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        normalized_hosts = tuple(host.lower() for host in self.allowed_source_hosts)
        if len(set(normalized_hosts)) != len(normalized_hosts) or any(
            not host or host != host.strip() or not _HOST.fullmatch(host)
            for host in normalized_hosts
        ):
            raise ValueError("allowed source hosts are invalid")
        object.__setattr__(self, "allowed_source_hosts", normalized_hosts)
        if not 1 <= self.source_fetch_timeout_seconds <= 30:
            raise ValueError("source fetch timeout must be between 1 and 30 seconds")
        if not 1 <= self.parser_connect_timeout_seconds <= 30:
            raise ValueError("parser connect timeout must be between 1 and 30 seconds")
        if not 1 <= self.parser_read_timeout_seconds <= 240:
            raise ValueError("parser read timeout must be between 1 and 240 seconds")
        if self.enabled:
            if self.engine is None or not normalized_hosts:
                raise ValueError("enabled normalization requires one engine and source host")
            _validate_parser_base_url(self.parser_base_url, self.allow_loopback_http)
        if self.parser_api_key is not None and (
            not self.parser_api_key
            or self.parser_api_key != self.parser_api_key.strip()
            or len(self.parser_api_key) > 4096
        ):
            raise ValueError("parser API key is invalid")

    @classmethod
    def from_environment(cls) -> "ContentNormalizationSettings":
        raw_engine = os.getenv("DIANLIAN_CONTENT_NORMALIZATION_SERVICE_ENGINE")
        engine = ParserEngine(raw_engine.strip().upper()) if raw_engine else None
        raw_hosts = os.getenv(
            "DIANLIAN_CONTENT_NORMALIZATION_ALLOWED_SOURCE_HOSTS", ""
        )
        return cls(
            enabled=_read_bool("DIANLIAN_CONTENT_NORMALIZATION_SERVICE_ENABLED"),
            engine=engine,
            allowed_source_hosts=tuple(
                item.strip() for item in raw_hosts.split(",") if item.strip()
            ),
            parser_base_url=os.getenv("DIANLIAN_CONTENT_NORMALIZATION_PARSER_BASE_URL"),
            parser_api_key=os.getenv("DIANLIAN_CONTENT_NORMALIZATION_PARSER_API_KEY"),
            source_fetch_timeout_seconds=_read_int(
                "DIANLIAN_CONTENT_NORMALIZATION_SOURCE_FETCH_TIMEOUT_SECONDS", 10, 1, 30
            ),
            parser_connect_timeout_seconds=_read_int(
                "DIANLIAN_CONTENT_NORMALIZATION_PARSER_CONNECT_TIMEOUT_SECONDS", 3, 1, 30
            ),
            parser_read_timeout_seconds=_read_int(
                "DIANLIAN_CONTENT_NORMALIZATION_PARSER_READ_TIMEOUT_SECONDS", 45, 1, 240
            ),
            allow_loopback_http=_read_bool(
                "DIANLIAN_CONTENT_NORMALIZATION_ALLOW_LOOPBACK_HTTP"
            ),
        )


def _validate_parser_base_url(value: str | None, allow_loopback_http: bool) -> None:
    if value is None or not value or value != value.strip():
        raise ValueError("enabled normalization requires parser base URL")
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("parser base URL must be a credential-free origin")
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return
    if (
        scheme != "http"
        or not allow_loopback_http
        or parsed.hostname.lower() not in _LOOPBACK_HOSTS
    ):
        raise ValueError("parser base URL requires HTTPS or explicit loopback HTTP")
