from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import struct
from uuid import UUID

import httpx
import pytest

from dianlian_runtime.upload_inspection.contracts import UploadInspectionRequest
from dianlian_runtime.upload_inspection.service import (
    ClamdClient,
    ClamdScanResult,
    ClamAvUploadInspectionService,
    UploadInspectionOutcome,
    UploadInspectionSourceConflict,
    UploadInspectionUnsupportedMedia,
)
from dianlian_runtime.upload_inspection.settings import UploadInspectionSettings


NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)
PDF = b"%PDF-1.7\ncontrolled content\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"payload" + b"IEND\xaeB`\x82"


class RecordingClamd:
    def __init__(self, *, infected: bool = False) -> None:
        self.infected = infected
        self.profile_calls = 0
        self.scanned = b""

    def profile_version(self) -> str:
        self.profile_calls += 1
        return "clamav-1.4.3-db-27678"

    def scan(self, content) -> ClamdScanResult:
        content.seek(0)
        self.scanned = content.read()
        return ClamdScanResult(infected=self.infected)


def test_clean_source_is_rehashed_sniffed_and_scanned_by_clamd() -> None:
    clamd = RecordingClamd()
    service = _service(PDF, clamd)

    response = service.inspect(_request(PDF, "application/pdf"))

    assert response.outcome == UploadInspectionOutcome.CLEAN
    assert response.content_sha256 == sha256(PDF).hexdigest()
    assert response.detected_media_type == "application/pdf"
    assert response.rejection_code is None
    assert clamd.scanned == PDF
    assert clamd.profile_calls == 2


def test_malware_and_allowed_media_mismatch_become_terminal_rejections() -> None:
    infected = _service(PDF, RecordingClamd(infected=True)).inspect(
        _request(PDF, "application/pdf")
    )
    mismatched = _service(PNG, RecordingClamd()).inspect(
        _request(PNG, "application/pdf")
    )

    assert infected.outcome == UploadInspectionOutcome.REJECTED
    assert infected.rejection_code == "MALWARE_DETECTED"
    assert mismatched.outcome == UploadInspectionOutcome.REJECTED
    assert mismatched.rejection_code == "MEDIA_TYPE_MISMATCH"
    assert mismatched.detected_media_type == "image/png"


def test_identity_drift_is_rejected_after_scanning_and_fact_id_is_deterministic() -> None:
    declared = _request(PDF, "application/pdf", declared_sha="b" * 64)
    first = _service(PDF, RecordingClamd()).inspect(declared)
    second = _service(PDF, RecordingClamd()).inspect(declared)

    assert first.outcome == UploadInspectionOutcome.REJECTED
    assert first.rejection_code == "CONTENT_IDENTITY_MISMATCH"
    assert first.scanner_fact_id == second.scanner_fact_id


def test_source_host_expiry_and_malformed_media_fail_closed() -> None:
    with pytest.raises(UploadInspectionSourceConflict):
        _service(PDF, RecordingClamd()).inspect(
            _request(PDF, "application/pdf", source_url="https://metadata.internal/latest")
        )
    with pytest.raises(UploadInspectionSourceConflict):
        _service(PDF, RecordingClamd(), now=NOW + timedelta(minutes=3)).inspect(
            _request(PDF, "application/pdf")
        )
    with pytest.raises(UploadInspectionUnsupportedMedia):
        _service(b"not-a-pdf", RecordingClamd()).inspect(
            _request(b"not-a-pdf", "application/pdf")
        )


def test_clamd_client_uses_version_and_length_framed_instream_protocol() -> None:
    version_socket = FakeSocket(b"ClamAV 1.4.3/27678/Wed Aug 18 00:00:00 2026\0")
    scan_socket = FakeSocket(b"stream: OK\0")
    sockets = iter((version_socket, scan_socket))
    client = ClamdClient(
        "clamd.internal",
        3310,
        connect_timeout_seconds=3,
        scan_timeout_seconds=90,
        socket_factory=lambda target, timeout: next(sockets),
    )

    assert client.profile_version() == "clamav-1.4.3-db-27678"
    assert client.scan(BytesIO(PDF)).infected is False
    assert version_socket.sent == b"zVERSION\0"
    assert scan_socket.sent == (
        b"zINSTREAM\0"
        + struct.pack("!I", len(PDF))
        + PDF
        + struct.pack("!I", 0)
    )


def _settings() -> UploadInspectionSettings:
    return UploadInspectionSettings(
        enabled=True,
        allowed_source_hosts=("objects.internal",),
        clamd_host="clamd.internal",
    )


def _service(
    content: bytes,
    clamd: RecordingClamd,
    *,
    now: datetime = NOW + timedelta(seconds=1),
) -> ClamAvUploadInspectionService:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(content))
    )
    return ClamAvUploadInspectionService(
        _settings(),
        http_client=httpx.Client(transport=transport, follow_redirects=False),
        clamd_client=clamd,
        clock=lambda: now,
    )


def _request(
    content: bytes,
    media_type: str,
    *,
    declared_sha: str | None = None,
    source_url: str = "https://objects.internal/read?signed=secret",
) -> UploadInspectionRequest:
    return UploadInspectionRequest(
        contractVersion="1.0",
        inspectionRequestId="00000000-0000-4000-8000-000000000168",
        providerObjectVersion="object-version-1",
        providerChecksum="provider-etag",
        declaredMediaType=media_type,
        declaredContentLength=len(content),
        declaredContentSha256=declared_sha or sha256(content).hexdigest(),
        sourceReadUrl=source_url,
        sourceExpiresAt=NOW + timedelta(minutes=2),
        requestedAt=NOW,
    )


class FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent = b""
        self.timeout: float | None = None

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        del exception_type, exception, traceback

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, content: bytes) -> None:
        self.sent += content

    def recv(self, maximum: int) -> bytes:
        del maximum
        response, self.response = self.response, b""
        return response
