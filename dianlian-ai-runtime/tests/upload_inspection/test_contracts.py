from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from dianlian_runtime.upload_inspection.contracts import UploadInspectionRequest


NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)


def test_request_accepts_only_the_exact_bounded_upload_contract() -> None:
    request = _request()

    assert request.inspection_request_id == UUID("00000000-0000-4000-8000-000000000168")
    assert "signed=secret" not in repr(request)

    with pytest.raises(ValidationError):
        _request(contractVersion="1.1")
    with pytest.raises(ValidationError):
        _request(declaredMediaType="application/octet-stream")
    with pytest.raises(ValidationError):
        _request(sourceExpiresAt=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        _request(extraField="not-allowed")


def _request(**updates: object) -> UploadInspectionRequest:
    values: dict[str, object] = {
        "contractVersion": "1.0",
        "inspectionRequestId": "00000000-0000-4000-8000-000000000168",
        "providerObjectVersion": "object-version-1",
        "providerChecksum": "provider-etag",
        "declaredMediaType": "application/pdf",
        "declaredContentLength": 128,
        "declaredContentSha256": "a" * 64,
        "sourceReadUrl": "https://objects.internal/read?signed=secret",
        "sourceExpiresAt": NOW + timedelta(minutes=2),
        "requestedAt": NOW,
    }
    values.update(updates)
    return UploadInspectionRequest(**values)
