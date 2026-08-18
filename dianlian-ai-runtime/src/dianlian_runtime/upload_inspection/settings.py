from __future__ import annotations

from dataclasses import dataclass
import os
import re


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


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
class UploadInspectionSettings:
    """独立上传检查进程配置；默认关闭且无隐式来源 Host。"""

    enabled: bool = False
    allowed_source_hosts: tuple[str, ...] = ()
    clamd_host: str | None = None
    clamd_port: int = 3310
    source_fetch_timeout_seconds: int = 30
    clamd_connect_timeout_seconds: int = 3
    clamd_scan_timeout_seconds: int = 50

    def __post_init__(self) -> None:
        normalized_hosts = tuple(host.lower() for host in self.allowed_source_hosts)
        if len(set(normalized_hosts)) != len(normalized_hosts):
            raise ValueError("allowed source hosts must be unique")
        if any(
            not host
            or host != host.strip()
            or not _HOST.fullmatch(host)
            for host in normalized_hosts
        ):
            raise ValueError("allowed source host is invalid")
        object.__setattr__(self, "allowed_source_hosts", normalized_hosts)
        if not 1 <= self.clamd_port <= 65535:
            raise ValueError("clamd port is invalid")
        if not 1 <= self.source_fetch_timeout_seconds <= 30:
            raise ValueError("source fetch timeout must be between 1 and 30 seconds")
        if not 1 <= self.clamd_connect_timeout_seconds <= 30:
            raise ValueError("clamd connect timeout must be between 1 and 30 seconds")
        if not 1 <= self.clamd_scan_timeout_seconds <= 50:
            raise ValueError("clamd scan timeout must be between 1 and 50 seconds")
        if self.enabled:
            if not normalized_hosts:
                raise ValueError("enabled upload inspection requires allowed source hosts")
            if (
                self.clamd_host is None
                or not self.clamd_host
                or self.clamd_host != self.clamd_host.strip()
                or not _HOST.fullmatch(self.clamd_host)
            ):
                raise ValueError("enabled upload inspection requires a valid clamd host")

    @classmethod
    def from_environment(cls) -> "UploadInspectionSettings":
        raw_hosts = os.getenv("DIANLIAN_UPLOAD_INSPECTION_ALLOWED_SOURCE_HOSTS", "")
        hosts = tuple(item.strip() for item in raw_hosts.split(",") if item.strip())
        raw_clamd_host = os.getenv("DIANLIAN_UPLOAD_INSPECTION_CLAMD_HOST")
        clamd_host = raw_clamd_host.strip() if raw_clamd_host else None
        return cls(
            enabled=_read_bool("DIANLIAN_UPLOAD_INSPECTION_SERVICE_ENABLED"),
            allowed_source_hosts=hosts,
            clamd_host=clamd_host,
            clamd_port=_read_int(
                "DIANLIAN_UPLOAD_INSPECTION_CLAMD_PORT", 3310, 1, 65535
            ),
            source_fetch_timeout_seconds=_read_int(
                "DIANLIAN_UPLOAD_INSPECTION_SOURCE_FETCH_TIMEOUT_SECONDS",
                30,
                1,
                30,
            ),
            clamd_connect_timeout_seconds=_read_int(
                "DIANLIAN_UPLOAD_INSPECTION_CLAMD_CONNECT_TIMEOUT_SECONDS",
                3,
                1,
                30,
            ),
            clamd_scan_timeout_seconds=_read_int(
                "DIANLIAN_UPLOAD_INSPECTION_CLAMD_SCAN_TIMEOUT_SECONDS",
                50,
                1,
                50,
            ),
        )
