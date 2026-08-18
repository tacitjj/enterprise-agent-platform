from __future__ import annotations

import codecs
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
import socket
import struct
import tempfile
from typing import BinaryIO, Callable, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid5
import zipfile

import httpx

from dianlian_runtime.upload_inspection.contracts import (
    UploadInspectionOutcome,
    UploadInspectionRequest,
    UploadInspectionResponse,
)
from dianlian_runtime.upload_inspection.settings import UploadInspectionSettings


_SCANNER_FACT_NAMESPACE = UUID("5925ac0b-0d4e-5b8b-a220-bc96e83e5168")
_CLAMAV_VERSION = re.compile(
    r"^ClamAV ([0-9]+(?:\.[0-9]+){1,3})/([0-9]+)/"
)
_OOXML_MEDIA_BY_MARKER = {
    "word/document.xml": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "xl/workbook.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "ppt/presentation.xml": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
}


class UploadInspectionError(RuntimeError):
    pass


class UploadInspectionDisabled(UploadInspectionError):
    pass


class UploadInspectionSourceConflict(UploadInspectionError):
    pass


class UploadInspectionUnsupportedMedia(UploadInspectionError):
    pass


class UploadInspectionUnavailable(UploadInspectionError):
    pass


class UploadInspectionService(Protocol):
    @property
    def ready(self) -> bool: ...

    def inspect(self, request: UploadInspectionRequest) -> UploadInspectionResponse: ...


class DisabledUploadInspectionService:
    @property
    def ready(self) -> bool:
        return False

    def inspect(self, request: UploadInspectionRequest) -> UploadInspectionResponse:
        del request
        raise UploadInspectionDisabled("upload inspection is disabled")


@dataclass(frozen=True, slots=True)
class ClamdScanResult:
    infected: bool


class ClamdPort(Protocol):
    def profile_version(self) -> str: ...

    def scan(self, content: BinaryIO) -> ClamdScanResult: ...


class ClamdClient:
    """使用 clamd 原生 VERSION 与 INSTREAM 协议，不执行 shell 命令。"""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_timeout_seconds: int,
        scan_timeout_seconds: int,
        socket_factory: Callable[[tuple[str, int], float], socket.socket] | None = None,
    ) -> None:
        self._target = (host, port)
        self._connect_timeout_seconds = connect_timeout_seconds
        self._scan_timeout_seconds = scan_timeout_seconds
        self._socket_factory = socket_factory or (
            lambda target, timeout: socket.create_connection(target, timeout=timeout)
        )

    def profile_version(self) -> str:
        response = self._simple_command(b"zVERSION\0")
        matched = _CLAMAV_VERSION.match(response)
        if matched is None:
            raise UploadInspectionUnavailable("clamd returned an invalid VERSION response")
        return f"clamav-{matched.group(1)}-db-{matched.group(2)}"

    def scan(self, content: BinaryIO) -> ClamdScanResult:
        try:
            with self._socket_factory(
                self._target,
                float(self._connect_timeout_seconds),
            ) as connection:
                connection.settimeout(float(self._scan_timeout_seconds))
                connection.sendall(b"zINSTREAM\0")
                content.seek(0)
                while chunk := content.read(64 * 1024):
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = _receive_bounded(connection)
        except UploadInspectionUnavailable:
            raise
        except (OSError, TimeoutError) as exception:
            raise UploadInspectionUnavailable("clamd scan is unavailable") from exception
        if response == "stream: OK":
            return ClamdScanResult(infected=False)
        if response.startswith("stream: ") and response.endswith(" FOUND"):
            return ClamdScanResult(infected=True)
        raise UploadInspectionUnavailable("clamd returned an invalid INSTREAM response")

    def _simple_command(self, command: bytes) -> str:
        try:
            with self._socket_factory(
                self._target,
                float(self._connect_timeout_seconds),
            ) as connection:
                connection.settimeout(float(self._connect_timeout_seconds))
                connection.sendall(command)
                return _receive_bounded(connection)
        except UploadInspectionUnavailable:
            raise
        except (OSError, TimeoutError) as exception:
            raise UploadInspectionUnavailable("clamd is unavailable") from exception


class ClamAvUploadInspectionService:
    """下载精确短时对象、重算身份、识别允许媒体并通过 clamd INSTREAM 扫描。"""

    def __init__(
        self,
        settings: UploadInspectionSettings,
        *,
        http_client: httpx.Client | None = None,
        clamd_client: ClamdPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not settings.enabled or settings.clamd_host is None:
            raise ValueError("ClamAV upload inspection requires enabled settings")
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            timeout=httpx.Timeout(settings.source_fetch_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )
        self._clamd = clamd_client or ClamdClient(
            settings.clamd_host,
            settings.clamd_port,
            connect_timeout_seconds=settings.clamd_connect_timeout_seconds,
            scan_timeout_seconds=settings.clamd_scan_timeout_seconds,
        )

    @property
    def ready(self) -> bool:
        return True

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def inspect(self, request: UploadInspectionRequest) -> UploadInspectionResponse:
        self._require_safe_source(request)
        with tempfile.TemporaryFile(mode="w+b") as content:
            actual_length, actual_sha256 = self._download(request, content)
            detected_media_type = _detect_media_type(content, request.declared_media_type)
            before_profile = self._clamd.profile_version()
            scan_result = self._clamd.scan(content)
            after_profile = self._clamd.profile_version()
            if before_profile != after_profile:
                raise UploadInspectionUnavailable("clamd profile changed during inspection")

        rejection_code: str | None = None
        if scan_result.infected:
            rejection_code = "MALWARE_DETECTED"
        elif detected_media_type != request.declared_media_type:
            rejection_code = "MEDIA_TYPE_MISMATCH"
        elif (
            actual_length != request.declared_content_length
            or actual_sha256 != request.declared_content_sha256
        ):
            rejection_code = "CONTENT_IDENTITY_MISMATCH"
        outcome = (
            UploadInspectionOutcome.REJECTED
            if rejection_code is not None
            else UploadInspectionOutcome.CLEAN
        )
        observed_at = self._clock()
        canonical = "\0".join(
            (
                str(request.inspection_request_id),
                request.provider_object_version,
                request.provider_checksum,
                before_profile,
                outcome.value,
                detected_media_type,
                str(actual_length),
                actual_sha256,
                rejection_code or "",
            )
        )
        return UploadInspectionResponse(
            contractVersion="1.0",
            inspectionRequestId=request.inspection_request_id,
            providerObjectVersion=request.provider_object_version,
            providerChecksum=request.provider_checksum,
            scannerFactId=uuid5(_SCANNER_FACT_NAMESPACE, canonical),
            outcome=outcome,
            detectedMediaType=detected_media_type,
            contentLength=actual_length,
            contentSha256=actual_sha256,
            inspectionProfileVersion=before_profile,
            rejectionCode=rejection_code,
            scannerId="clamav",
            requestedAt=request.requested_at,
            observedAt=observed_at,
        )

    def _require_safe_source(self, request: UploadInspectionRequest) -> None:
        if _contains_ascii_control(request.source_read_url):
            raise UploadInspectionSourceConflict(
                "source read capability is not allowed"
            )
        parsed = urlsplit(request.source_read_url)
        host = parsed.hostname.lower() if parsed.hostname else None
        try:
            port = parsed.port
        except ValueError:
            raise UploadInspectionSourceConflict(
                "source read capability is not allowed"
            ) from None
        if (
            parsed.scheme.lower() != "https"
            or host is None
            or host not in self._settings.allowed_source_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in (None, 443)
        ):
            raise UploadInspectionSourceConflict("source read capability is not allowed")
        if self._clock() >= request.source_expires_at:
            raise UploadInspectionSourceConflict("source read capability has expired")

    def _download(
        self,
        request: UploadInspectionRequest,
        target: BinaryIO,
    ) -> tuple[int, str]:
        digest = sha256()
        length = 0
        try:
            with self._http_client.stream(
                "GET",
                request.source_read_url,
                headers={
                    "Accept": "application/octet-stream",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code != 200:
                    raise UploadInspectionSourceConflict(
                        "source read capability did not return the exact object"
                    )
                content_encoding = response.headers.get("content-encoding")
                if content_encoding not in (None, "identity"):
                    raise UploadInspectionSourceConflict(
                        "source read capability returned encoded content"
                    )
                for chunk in response.iter_raw():
                    length += len(chunk)
                    if length > request.declared_content_length:
                        raise UploadInspectionSourceConflict(
                            "source object exceeds upload-policy-v1"
                        )
                    digest.update(chunk)
                    target.write(chunk)
        except (UploadInspectionSourceConflict, UploadInspectionUnsupportedMedia):
            raise
        except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError, OSError):
            # httpx 异常可能包含签名 URL，禁止将原异常链带入日志或响应。
            raise UploadInspectionUnavailable("source object is unavailable") from None
        if length == 0:
            raise UploadInspectionSourceConflict("source object is empty")
        if self._clock() >= request.source_expires_at:
            raise UploadInspectionSourceConflict("source read capability expired during transfer")
        target.flush()
        target.seek(0)
        return length, digest.hexdigest()


def _receive_bounded(connection: socket.socket) -> str:
    response = bytearray()
    while len(response) <= 4096:
        chunk = connection.recv(1024)
        if not chunk:
            break
        response.extend(chunk)
        if b"\0" in chunk or b"\n" in chunk:
            break
    if not response or len(response) > 4096:
        raise UploadInspectionUnavailable("clamd response is missing or too large")
    try:
        return bytes(response).split(b"\0", 1)[0].split(b"\n", 1)[0].decode(
            "utf-8", errors="strict"
        )
    except UnicodeDecodeError:
        raise UploadInspectionUnavailable("clamd response is not UTF-8") from None


def _detect_media_type(content: BinaryIO, declared_media_type: str) -> str:
    content.seek(0)
    head = content.read(16)
    tail_window = min(_file_size(content), 4096)
    content.seek(-tail_window, 2)
    tail = content.read(tail_window)
    content.seek(0)
    if head.startswith(b"%PDF-") and _has_safe_trailer(
        tail,
        b"%%EOF",
        b"\t\n\r\f ",
    ):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff") and _has_safe_trailer(
        tail,
        b"\xff\xd9",
        b"\x00\t\n\r\f ",
    ):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in tail:
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"PK\x03\x04"):
        return _detect_ooxml(content)
    if declared_media_type in {"text/plain", "text/markdown"} and _is_utf8_text(content):
        return declared_media_type
    raise UploadInspectionUnsupportedMedia("source media type is unsupported or malformed")


def _file_size(content: BinaryIO) -> int:
    content.seek(0, 2)
    size = content.tell()
    content.seek(0)
    return size


def _has_safe_trailer(tail: bytes, marker: bytes, allowed_padding: bytes) -> bool:
    """只允许终止标记后的有限安全填充，避免接受任意尾随载荷。"""

    marker_index = tail.rfind(marker)
    if marker_index < 0:
        return False
    trailer = tail[marker_index + len(marker) :]
    return all(byte in allowed_padding for byte in trailer)


def _contains_ascii_control(value: str) -> bool:
    """拒绝 HTTP 客户端可能延迟报错的 ASCII 控制字符。"""

    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _detect_ooxml(content: BinaryIO) -> str:
    try:
        content.seek(0)
        with zipfile.ZipFile(content) as archive:
            infos = archive.infolist()
            if len(infos) > 20_000 or any(info.flag_bits & 0x1 for info in infos):
                raise UploadInspectionUnsupportedMedia("OOXML package is unsafe")
            names = {info.filename for info in infos}
    except UploadInspectionUnsupportedMedia:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise UploadInspectionUnsupportedMedia("OOXML package is malformed") from None
    matches = [media for marker, media in _OOXML_MEDIA_BY_MARKER.items() if marker in names]
    if len(matches) != 1 or "[Content_Types].xml" not in names:
        raise UploadInspectionUnsupportedMedia("OOXML package identity is ambiguous")
    return matches[0]


def _is_utf8_text(content: BinaryIO) -> bool:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    content.seek(0)
    try:
        while chunk := content.read(64 * 1024):
            if b"\0" in chunk:
                return False
            decoder.decode(chunk, final=False)
        decoder.decode(b"", final=True)
        return True
    except UnicodeDecodeError:
        return False
    finally:
        content.seek(0)
