from io import BytesIO
import json

import httpx
import pytest

from dianlian_runtime.content_normalization.contracts import ParserEngine
from dianlian_runtime.content_normalization.service import (
    ContentNormalizationContractRejected,
    DoclingServeParser,
    TikaServerParser,
)
from dianlian_runtime.content_normalization.settings import ContentNormalizationSettings


PDF = b"%PDF-1.7\ncontrolled content\n%%EOF\n"


def test_tika_uses_the_single_official_text_extraction_endpoint() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(
            method=request.method,
            path=request.url.path,
            accept=request.headers.get("accept"),
            content_type=request.headers.get("content-type"),
            body=request.read(),
        )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"  normalized by tika  "),
        )

    parser = TikaServerParser(_settings(ParserEngine.TIKA), _client(handler))

    assert parser.extract(BytesIO(PDF), "application/pdf") == "  normalized by tika  "
    assert observed == {
        "method": "PUT",
        "path": "/tika",
        "accept": "text/plain",
        "content_type": "application/pdf",
        "body": PDF,
    }


def test_docling_uses_one_file_conversion_and_requires_markdown() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        observed.update(method=request.method, path=request.url.path, body=body)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(
                json.dumps(
                    {"status": "success", "document": {"md_content": "# Document"}}
                ).encode()
            ),
        )

    parser = DoclingServeParser(_settings(ParserEngine.DOCLING), _client(handler))

    assert parser.extract(BytesIO(PDF), "application/pdf") == "# Document"
    assert observed["method"] == "POST"
    assert observed["path"] == "/v1/convert/file"
    assert b'name="to_formats"' in observed["body"]
    assert b"md" in observed["body"]

    rejected = DoclingServeParser(
        _settings(ParserEngine.DOCLING),
        _client(
            lambda request: httpx.Response(
                200,
                stream=httpx.ByteStream(json.dumps({"status": "failure"}).encode()),
            )
        ),
    )
    with pytest.raises(ContentNormalizationContractRejected):
        rejected.extract(BytesIO(PDF), "application/pdf")


def _settings(engine: ParserEngine) -> ContentNormalizationSettings:
    return ContentNormalizationSettings(
        enabled=True,
        engine=engine,
        allowed_source_hosts=("objects.internal",),
        parser_base_url="https://parser.internal",
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://parser.internal",
        transport=httpx.MockTransport(handler),
    )
