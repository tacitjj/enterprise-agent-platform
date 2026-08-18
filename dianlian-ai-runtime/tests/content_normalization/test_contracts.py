from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from dianlian_runtime.content_normalization.contracts import ContentNormalizationRequest


NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)


def test_request_accepts_only_the_exact_content_free_contract() -> None:
    request = _request()

    assert request.source.relation_type == "KNOWLEDGE_DOCUMENT_VERSION"
    assert "signed=secret" not in repr(request)
    assert "objectKey" not in request.model_dump(by_alias=True)["source"]

    with pytest.raises(ValidationError):
        _request(contractVersion="1.1")
    with pytest.raises(ValidationError):
        _request(engine="AUTO")
    with pytest.raises(ValidationError):
        _request(source={**_source(), "mediaType": "application/octet-stream"})
    with pytest.raises(ValidationError):
        _request(source={**_source(), "sourceExpiresAt": NOW})
    with pytest.raises(ValidationError):
        _request(objectKey="must-not-cross-boundary")


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
        "contentLength": 128,
        "contentSha256": "a" * 64,
        "normalizationProfileVersion": "normalization-v1",
        "sourceReadUrl": "https://objects.internal/source?signed=secret",
        "sourceExpiresAt": NOW + timedelta(minutes=2),
    }
