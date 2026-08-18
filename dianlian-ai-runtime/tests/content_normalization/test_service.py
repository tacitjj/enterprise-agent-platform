from datetime import datetime, timedelta, timezone
from hashlib import sha256

import httpx
import pytest

from dianlian_runtime.content_normalization.contracts import (
    ContentNormalizationRequest,
    ParserEngine,
)
from dianlian_runtime.content_normalization.service import (
    ContentNormalizationSourceConflict,
    IsolatedContentNormalizationService,
)
from dianlian_runtime.content_normalization.settings import ContentNormalizationSettings


NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
PDF = b"%PDF-1.7\ncontrolled content\n%%EOF\n"


class Parser:
    ready = True

    def __init__(self, text: str = " First paragraph.\r\n\r\nSecond paragraph. ") -> None:
        self.text = text
        self.observed: bytes | None = None

    def extract(self, content, media_type: str) -> str:
        assert media_type == "application/pdf"
        self.observed = content.read()
        return self.text


def test_service_reads_one_allowlisted_object_and_rebinds_the_response() -> None:
    parser = Parser()
    service = IsolatedContentNormalizationService(
        _settings(),
        parser,
        source_client=_source_client(PDF),
        clock=lambda: NOW,
    )

    response = service.normalize(_request())

    assert parser.observed == PDF
    assert response.request_id == _request().request_id
    assert response.content_sha256 == sha256(PDF).hexdigest()
    assert [segment.normalized_text for segment in response.segments] == [
        "First paragraph.\n\nSecond paragraph."
    ]
    assert response.segments[0].locator_payload is None


def test_service_rejects_engine_host_redirect_and_object_identity_drift() -> None:
    with pytest.raises(ContentNormalizationSourceConflict):
        _service(PDF).normalize(_request(engine="TIKA"))
    with pytest.raises(ContentNormalizationSourceConflict):
        _service(PDF).normalize(
            _request(
                source={
                    **_source(),
                    "sourceReadUrl": "https://attacker.invalid/source?signed=secret",
                }
            )
        )
    with pytest.raises(ContentNormalizationSourceConflict):
        _service(PDF, status_code=302).normalize(_request())
    with pytest.raises(ContentNormalizationSourceConflict):
        _service(PDF + b"drift").normalize(_request())
    with pytest.raises(ContentNormalizationSourceConflict):
        _service(PDF).normalize(
            _request(
                source={
                    **_source(),
                    "sourceReadUrl": "https://objects.internal/source\x01?signed=secret",
                }
            )
        )


def _service(content: bytes, status_code: int = 200) -> IsolatedContentNormalizationService:
    return IsolatedContentNormalizationService(
        _settings(),
        Parser(),
        source_client=_source_client(content, status_code),
        clock=lambda: NOW,
    )


def _settings() -> ContentNormalizationSettings:
    return ContentNormalizationSettings(
        enabled=True,
        engine=ParserEngine.DOCLING,
        allowed_source_hosts=("objects.internal",),
        parser_base_url="https://parser.internal",
    )


def _source_client(content: bytes, status_code: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status_code,
                stream=httpx.ByteStream(content),
            )
        )
    )


def _request(**updates: object) -> ContentNormalizationRequest:
    values: dict[str, object] = {
        "contractVersion": "1.0",
        "requestId": "00000000-0000-4000-8000-000000000169",
        "engine": "DOCLING",
        "requestedAt": NOW,
        "source": _source(),
    }
    values.update(updates)
    return ContentNormalizationRequest(**values)


def _source() -> dict[str, object]:
    return {
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
        "sourceExpiresAt": NOW + timedelta(minutes=2),
    }
