from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from fastapi.testclient import TestClient

from dianlian_runtime.auth import InternalServicePrincipal, InternalServiceScope
from dianlian_runtime.upload_inspection.app import (
    UPLOAD_INSPECTION_ROUTE,
    create_upload_inspection_app,
)
from dianlian_runtime.upload_inspection.contracts import (
    UploadInspectionOutcome,
    UploadInspectionResponse,
)
from dianlian_runtime.upload_inspection.settings import UploadInspectionSettings


NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)
PDF = b"%PDF-1.7\ncontrolled content\n%%EOF\n"


class Authenticator:
    ready = True

    def __init__(self, *, extra_scope: bool = False) -> None:
        self.extra_scope = extra_scope
        self.required: list[InternalServiceScope] = []

    def authorize(self, token: str, required_scope: InternalServiceScope):
        del token
        self.required.append(required_scope)
        scopes = {required_scope}
        if self.extra_scope:
            scopes.add(InternalServiceScope.CONTEXT_RETRIEVE)
        return InternalServicePrincipal(
            subject="dianlian-platform",
            token_id=UUID("10000000-0000-4000-8000-000000000168"),
            scopes=frozenset(scopes),
            issued_at=0,
            expires_at=60,
        )


class ReadyService:
    ready = True

    def inspect(self, request) -> UploadInspectionResponse:
        return UploadInspectionResponse(
            contractVersion="1.0",
            inspectionRequestId=request.inspection_request_id,
            providerObjectVersion=request.provider_object_version,
            providerChecksum=request.provider_checksum,
            scannerFactId="20000000-0000-4000-8000-000000000168",
            outcome=UploadInspectionOutcome.CLEAN,
            detectedMediaType="application/pdf",
            contentLength=len(PDF),
            contentSha256=sha256(PDF).hexdigest(),
            inspectionProfileVersion="clamav-1.4.3-db-27678",
            rejectionCode=None,
            scannerId="clamav",
            requestedAt=request.requested_at,
            observedAt=NOW + timedelta(seconds=1),
        )


def test_endpoint_requires_one_exact_scope_and_returns_strict_receipt() -> None:
    authenticator = Authenticator()
    client = TestClient(
        create_upload_inspection_app(
            UploadInspectionSettings(),
            service=ReadyService(),
            authenticator=authenticator,
        )
    )

    response = client.post(
        UPLOAD_INSPECTION_ROUTE,
        headers={"Authorization": "Bearer inspection-test"},
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "CLEAN"
    assert authenticator.required == [InternalServiceScope.UPLOAD_INSPECT]
    operation = client.get("/internal/v1/openapi.json").json()["paths"][
        UPLOAD_INSPECTION_ROUTE
    ]["post"]
    assert operation["x-required-scopes"] == ["upload.inspect"]
    assert {"409", "413", "415", "422", "503"}.issubset(operation["responses"])


def test_default_service_is_closed_and_overbroad_scope_is_rejected() -> None:
    disabled = TestClient(
        create_upload_inspection_app(
            UploadInspectionSettings(),
            authenticator=Authenticator(),
        )
    ).post(
        UPLOAD_INSPECTION_ROUTE,
        headers={"Authorization": "Bearer inspection-test"},
        json=_payload(),
    )
    overbroad = TestClient(
        create_upload_inspection_app(
            UploadInspectionSettings(),
            service=ReadyService(),
            authenticator=Authenticator(extra_scope=True),
        )
    ).post(
        UPLOAD_INSPECTION_ROUTE,
        headers={"Authorization": "Bearer inspection-test"},
        json=_payload(),
    )

    assert disabled.status_code == 503
    assert disabled.json()["code"] == "UPLOAD_INSPECTION_DISABLED"
    assert overbroad.status_code == 403
    assert overbroad.json()["code"] == "INTERNAL_SERVICE_SCOPE_DENIED"


def test_duplicate_unknown_and_oversized_json_fail_before_service() -> None:
    client = TestClient(
        create_upload_inspection_app(
            UploadInspectionSettings(),
            service=ReadyService(),
            authenticator=Authenticator(),
        )
    )
    duplicate = client.post(
        UPLOAD_INSPECTION_ROUTE,
        headers={
            "Authorization": "Bearer inspection-test",
            "Content-Type": "application/json",
        },
        content='{"contractVersion":"1.0","contractVersion":"1.0"}',
    )
    unknown = client.post(
        UPLOAD_INSPECTION_ROUTE,
        headers={"Authorization": "Bearer inspection-test"},
        json={**_payload(), "objectKey": "must-not-cross-boundary"},
    )
    oversized = client.post(
        UPLOAD_INSPECTION_ROUTE,
        headers={"Authorization": "Bearer inspection-test"},
        json={**_payload(), "padding": "x" * (17 * 1024)},
    )

    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "UPLOAD_INSPECTION_REQUEST_INVALID"
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "UPLOAD_INSPECTION_REQUEST_INVALID"
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "UPLOAD_INSPECTION_REQUEST_TOO_LARGE"


def _payload() -> dict[str, object]:
    return {
        "contractVersion": "1.0",
        "inspectionRequestId": "00000000-0000-4000-8000-000000000168",
        "providerObjectVersion": "object-version-1",
        "providerChecksum": "provider-etag",
        "declaredMediaType": "application/pdf",
        "declaredContentLength": len(PDF),
        "declaredContentSha256": sha256(PDF).hexdigest(),
        "sourceReadUrl": "https://objects.internal/read?signed=secret",
        "sourceExpiresAt": (NOW + timedelta(minutes=2)).isoformat(),
        "requestedAt": NOW.isoformat(),
    }
