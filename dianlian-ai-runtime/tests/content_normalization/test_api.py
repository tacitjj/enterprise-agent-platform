from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from fastapi.testclient import TestClient

from dianlian_runtime.auth import InternalServicePrincipal, InternalServiceScope
from dianlian_runtime.content_normalization.app import (
    CONTENT_NORMALIZATION_ROUTE,
    create_content_normalization_app,
)
from dianlian_runtime.content_normalization.contracts import (
    ContentNormalizationResponse,
    NormalizedSegmentResponse,
)
from dianlian_runtime.content_normalization.settings import ContentNormalizationSettings


NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
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
            token_id=UUID("10000000-0000-4000-8000-000000000169"),
            scopes=frozenset(scopes),
            issued_at=0,
            expires_at=60,
        )


class ReadyService:
    ready = True

    def normalize(self, request) -> ContentNormalizationResponse:
        return ContentNormalizationResponse(
            contractVersion="1.0",
            requestId=request.request_id,
            engine=request.engine,
            providerObjectVersion=request.source.provider_object_version,
            contentSha256=request.source.content_sha256,
            normalizationProfileVersion=request.source.normalization_profile_version,
            segments=[
                NormalizedSegmentResponse(
                    ordinal=0,
                    kind="TEXT",
                    normalizedText="normalized content",
                )
            ],
        )


def test_endpoint_requires_one_exact_scope_and_returns_strict_response() -> None:
    authenticator = Authenticator()
    client = TestClient(
        create_content_normalization_app(
            ContentNormalizationSettings(),
            service=ReadyService(),
            authenticator=authenticator,
        )
    )

    response = client.post(
        CONTENT_NORMALIZATION_ROUTE,
        headers={"Authorization": "Bearer normalization-test"},
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["segments"][0]["normalizedText"] == "normalized content"
    assert authenticator.required == [InternalServiceScope.CONTENT_NORMALIZE]
    operation = client.get("/internal/v1/openapi.json").json()["paths"][
        CONTENT_NORMALIZATION_ROUTE
    ]["post"]
    assert operation["x-required-scopes"] == ["content.normalize"]
    assert {"409", "413", "415", "422", "503"}.issubset(operation["responses"])


def test_default_service_is_closed_and_overbroad_scope_is_rejected() -> None:
    disabled = TestClient(
        create_content_normalization_app(
            ContentNormalizationSettings(),
            authenticator=Authenticator(),
        )
    ).post(
        CONTENT_NORMALIZATION_ROUTE,
        headers={"Authorization": "Bearer normalization-test"},
        json=_payload(),
    )
    overbroad = TestClient(
        create_content_normalization_app(
            ContentNormalizationSettings(),
            service=ReadyService(),
            authenticator=Authenticator(extra_scope=True),
        )
    ).post(
        CONTENT_NORMALIZATION_ROUTE,
        headers={"Authorization": "Bearer normalization-test"},
        json=_payload(),
    )

    assert disabled.status_code == 503
    assert disabled.json()["code"] == "CONTENT_NORMALIZATION_DISABLED"
    assert overbroad.status_code == 403
    assert overbroad.json()["code"] == "INTERNAL_SERVICE_SCOPE_DENIED"


def test_duplicate_unknown_and_oversized_json_fail_before_service() -> None:
    client = TestClient(
        create_content_normalization_app(
            ContentNormalizationSettings(),
            service=ReadyService(),
            authenticator=Authenticator(),
        )
    )
    duplicate = client.post(
        CONTENT_NORMALIZATION_ROUTE,
        headers={
            "Authorization": "Bearer normalization-test",
            "Content-Type": "application/json",
        },
        content='{"contractVersion":"1.0","contractVersion":"1.0"}',
    )
    unknown = client.post(
        CONTENT_NORMALIZATION_ROUTE,
        headers={"Authorization": "Bearer normalization-test"},
        json={**_payload(), "objectKey": "must-not-cross-boundary"},
    )
    oversized = client.post(
        CONTENT_NORMALIZATION_ROUTE,
        headers={"Authorization": "Bearer normalization-test"},
        json={**_payload(), "padding": "x" * (33 * 1024)},
    )

    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "CONTENT_NORMALIZATION_REQUEST_INVALID"
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "CONTENT_NORMALIZATION_REQUEST_INVALID"
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "CONTENT_NORMALIZATION_REQUEST_TOO_LARGE"


def _payload() -> dict[str, object]:
    return {
        "contractVersion": "1.0",
        "requestId": "00000000-0000-4000-8000-000000000169",
        "engine": "DOCLING",
        "requestedAt": NOW.isoformat(),
        "source": {
            "tenantId": "10000000-0000-4000-8000-000000000169",
            "relationType": "KNOWLEDGE_DOCUMENT_VERSION",
            "relationId": "20000000-0000-4000-8000-000000000169",
            "uploadReceiptId": "30000000-0000-4000-8000-000000000169",
            "uploadId": "40000000-0000-4000-8000-000000000169",
            "uploadPurpose": "KNOWLEDGE_SOURCE",
            "providerObjectVersion": "object-version-1",
            "mediaType": "application/pdf",
            "contentLength": len(PDF),
            "contentSha256": sha256(PDF).hexdigest(),
            "normalizationProfileVersion": "normalization-v1",
            "sourceReadUrl": "https://objects.internal/source?signed=secret",
            "sourceExpiresAt": (NOW + timedelta(minutes=2)).isoformat(),
        },
    }
