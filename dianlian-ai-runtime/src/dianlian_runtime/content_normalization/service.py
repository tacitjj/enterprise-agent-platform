from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import tempfile
from typing import BinaryIO, Callable, Protocol
from unicodedata import normalize as unicode_normalize
from urllib.parse import urlsplit

import httpx

from dianlian_runtime.content_normalization.contracts import (
    MAX_CONTENT_LENGTH,
    MAX_NORMALIZED_TEXT_LENGTH,
    ContentNormalizationRequest,
    ContentNormalizationResponse,
    NormalizedSegmentResponse,
    ParserEngine,
)
from dianlian_runtime.content_normalization.settings import ContentNormalizationSettings


_MAX_PARSER_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_SEGMENT_TEXT_LENGTH = 900_000


class ContentNormalizationError(RuntimeError):
    pass


class ContentNormalizationDisabled(ContentNormalizationError):
    pass


class ContentNormalizationSourceConflict(ContentNormalizationError):
    pass


class ContentNormalizationContractRejected(ContentNormalizationError):
    pass


class ContentNormalizationUnavailable(ContentNormalizationError):
    pass


class ContentNormalizationService(Protocol):
    @property
    def ready(self) -> bool: ...

    def normalize(self, request: ContentNormalizationRequest) -> ContentNormalizationResponse: ...


class DisabledContentNormalizationService:
    @property
    def ready(self) -> bool:
        return False

    def normalize(self, request: ContentNormalizationRequest) -> ContentNormalizationResponse:
        del request
        raise ContentNormalizationDisabled("content normalization is disabled")


class ParserPort(Protocol):
    @property
    def ready(self) -> bool: ...

    def extract(self, content: BinaryIO, media_type: str) -> str: ...


class TikaServerParser:
    """使用官方 Tika Server `/tika` 字节上传端点提取纯文本。"""

    def __init__(self, settings: ContentNormalizationSettings, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or _parser_client(settings)

    @property
    def ready(self) -> bool:
        return _probe(self._client, "/version")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def extract(self, content: BinaryIO, media_type: str) -> str:
        content.seek(0)
        try:
            with self._client.stream(
                "PUT",
                "/tika",
                headers={
                    "Accept": "text/plain",
                    "Content-Type": media_type,
                    "X-Tika-Skip-Embedded": "true",
                },
                content=_iter_file(content),
            ) as response:
                if response.status_code != 200:
                    raise ContentNormalizationContractRejected(
                        "Tika rejected the document"
                    )
                return _read_text_response(response)
        except (ContentNormalizationContractRejected, ContentNormalizationUnavailable):
            raise
        except httpx.HTTPError:
            raise ContentNormalizationUnavailable("Tika Server is unavailable") from None


class DoclingServeParser:
    """使用官方 Docling Serve v1 文件上传端点导出 Markdown。"""

    def __init__(self, settings: ContentNormalizationSettings, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or _parser_client(settings)
        self._api_key = settings.parser_api_key

    @property
    def ready(self) -> bool:
        return _probe(self._client, "/health")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def extract(self, content: BinaryIO, media_type: str) -> str:
        content.seek(0)
        headers = {"Accept": "application/json"}
        if self._api_key is not None:
            headers["X-Api-Key"] = self._api_key
        try:
            with self._client.stream(
                "POST",
                "/v1/convert/file",
                headers=headers,
                files={"files": ("source", content, media_type)},
                data={
                    "to_formats": "md",
                    "image_export_mode": "placeholder",
                    "abort_on_error": "true",
                },
            ) as response:
                if response.status_code != 200:
                    raise ContentNormalizationContractRejected(
                        "Docling Serve rejected the document"
                    )
                payload = _read_json_response(response)
        except (ContentNormalizationContractRejected, ContentNormalizationUnavailable):
            raise
        except httpx.HTTPError:
            raise ContentNormalizationUnavailable("Docling Serve is unavailable") from None
        if payload.get("status") != "success" or not isinstance(payload.get("document"), dict):
            raise ContentNormalizationContractRejected(
                "Docling Serve did not return one successful document"
            )
        markdown = payload["document"].get("md_content")
        if not isinstance(markdown, str):
            raise ContentNormalizationContractRejected(
                "Docling Serve did not return Markdown"
            )
        return markdown


class IsolatedContentNormalizationService:
    """精确读取已验证对象、重算身份，并将临时文件交给单一解析引擎。"""

    def __init__(
        self,
        settings: ContentNormalizationSettings,
        parser: ParserPort,
        *,
        source_client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not settings.enabled or settings.engine is None:
            raise ValueError("content normalization requires enabled settings")
        self._settings = settings
        self._parser = parser
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._owns_source_client = source_client is None
        self._source_client = source_client or httpx.Client(
            timeout=httpx.Timeout(settings.source_fetch_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    @property
    def ready(self) -> bool:
        return self._parser.ready

    def close(self) -> None:
        if self._owns_source_client:
            self._source_client.close()
        close = getattr(self._parser, "close", None)
        if close is not None:
            close()

    def normalize(self, request: ContentNormalizationRequest) -> ContentNormalizationResponse:
        if request.engine != self._settings.engine:
            raise ContentNormalizationSourceConflict("parser engine does not match deployment")
        self._require_safe_source(request)
        with tempfile.TemporaryFile(mode="w+b") as content:
            length, digest = self._download(request, content)
            if (
                length != request.source.content_length
                or digest != request.source.content_sha256
            ):
                raise ContentNormalizationSourceConflict(
                    "source object identity does not match the verified receipt"
                )
            extracted = self._parser.extract(content, request.source.media_type)
        segments = [
            NormalizedSegmentResponse(
                ordinal=index,
                kind="TEXT",
                normalizedText=text,
            )
            for index, text in enumerate(_normalize_and_split(extracted))
        ]
        return ContentNormalizationResponse(
            contractVersion="1.0",
            requestId=request.request_id,
            engine=request.engine,
            providerObjectVersion=request.source.provider_object_version,
            contentSha256=request.source.content_sha256,
            normalizationProfileVersion=request.source.normalization_profile_version,
            segments=segments,
        )

    def _require_safe_source(self, request: ContentNormalizationRequest) -> None:
        parsed = urlsplit(request.source.source_read_url)
        host = parsed.hostname.lower() if parsed.hostname else None
        try:
            port = parsed.port
        except ValueError:
            raise ContentNormalizationSourceConflict("source read capability is not allowed") from None
        if (
            parsed.scheme.lower() != "https"
            or host is None
            or host not in self._settings.allowed_source_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in (None, 443)
        ):
            raise ContentNormalizationSourceConflict("source read capability is not allowed")
        if self._clock() >= request.source.source_expires_at:
            raise ContentNormalizationSourceConflict("source read capability has expired")

    def _download(
        self, request: ContentNormalizationRequest, target: BinaryIO
    ) -> tuple[int, str]:
        digest = sha256()
        length = 0
        try:
            with self._source_client.stream(
                "GET",
                request.source.source_read_url,
                headers={"Accept": "application/octet-stream", "Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    raise ContentNormalizationSourceConflict(
                        "source read capability did not return the exact object"
                    )
                if response.headers.get("content-encoding") not in (None, "identity"):
                    raise ContentNormalizationSourceConflict(
                        "source read capability returned encoded content"
                    )
                for chunk in response.iter_raw():
                    length += len(chunk)
                    if length > MAX_CONTENT_LENGTH:
                        raise ContentNormalizationSourceConflict(
                            "source object exceeds upload-policy-v1"
                        )
                    digest.update(chunk)
                    target.write(chunk)
        except ContentNormalizationSourceConflict:
            raise
        except (httpx.HTTPError, OSError):
            # HTTP 异常可能包含签名 URL，禁止传播原异常链。
            raise ContentNormalizationUnavailable("source object is unavailable") from None
        if length == 0 or self._clock() >= request.source.source_expires_at:
            raise ContentNormalizationSourceConflict(
                "source read capability expired or returned an empty object"
            )
        target.flush()
        target.seek(0)
        return length, digest.hexdigest()


def create_parser(
    settings: ContentNormalizationSettings,
    client: httpx.Client | None = None,
) -> ParserPort:
    if settings.engine == ParserEngine.TIKA:
        return TikaServerParser(settings, client)
    if settings.engine == ParserEngine.DOCLING:
        return DoclingServeParser(settings, client)
    raise ValueError("content normalization requires one parser engine")


def _parser_client(settings: ContentNormalizationSettings) -> httpx.Client:
    return httpx.Client(
        base_url=settings.parser_base_url or "",
        timeout=httpx.Timeout(
            settings.parser_read_timeout_seconds,
            connect=settings.parser_connect_timeout_seconds,
        ),
        follow_redirects=False,
        trust_env=False,
    )


def _probe(client: httpx.Client, path: str) -> bool:
    try:
        return client.get(path).status_code == 200
    except httpx.HTTPError:
        return False


def _iter_file(content: BinaryIO):
    while chunk := content.read(64 * 1024):
        yield chunk


def _read_text_response(response: httpx.Response) -> str:
    raw = _read_bounded_response(response)
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ContentNormalizationContractRejected(
            "parser response is not UTF-8"
        ) from None


def _read_json_response(response: httpx.Response) -> dict[str, object]:
    raw = _read_bounded_response(response)
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ContentNormalizationContractRejected("parser response is not valid JSON") from None
    if not isinstance(payload, dict):
        raise ContentNormalizationContractRejected("parser response is not one object")
    return payload


def _read_bounded_response(response: httpx.Response) -> bytes:
    body = bytearray()
    for chunk in response.iter_raw():
        body.extend(chunk)
        if len(body) > _MAX_PARSER_RESPONSE_BYTES:
            raise ContentNormalizationContractRejected("parser response is too large")
    return bytes(body)


def _normalize_and_split(value: str) -> list[str]:
    normalized = unicode_normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if "\0" in normalized:
        raise ContentNormalizationContractRejected("normalized text contains NUL")
    normalized = normalized.strip()
    if not normalized or len(normalized) > MAX_NORMALIZED_TEXT_LENGTH:
        raise ContentNormalizationContractRejected("normalized text is empty or too large")
    segments: list[str] = []
    remaining = normalized
    while len(remaining) > _MAX_SEGMENT_TEXT_LENGTH:
        boundary = remaining.rfind("\n\n", 0, _MAX_SEGMENT_TEXT_LENGTH)
        if boundary < _MAX_SEGMENT_TEXT_LENGTH // 2:
            boundary = _MAX_SEGMENT_TEXT_LENGTH
        segment = remaining[:boundary].strip()
        if segment:
            segments.append(segment)
        remaining = remaining[boundary:].lstrip()
    if remaining:
        segments.append(remaining)
    if not segments:
        raise ContentNormalizationContractRejected("parser returned no normalized text")
    return segments
