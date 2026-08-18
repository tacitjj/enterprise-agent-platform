import pytest

from dianlian_runtime.content_normalization.contracts import ParserEngine
from dianlian_runtime.content_normalization.settings import ContentNormalizationSettings


def test_service_is_closed_by_default_and_enabled_mode_is_explicit() -> None:
    disabled = ContentNormalizationSettings()
    enabled = ContentNormalizationSettings(
        enabled=True,
        engine=ParserEngine.DOCLING,
        allowed_source_hosts=("objects.internal",),
        parser_base_url="https://docling.internal",
    )

    assert disabled.enabled is False
    assert enabled.engine == ParserEngine.DOCLING

    with pytest.raises(ValueError):
        ContentNormalizationSettings(enabled=True)
    with pytest.raises(ValueError):
        ContentNormalizationSettings(
            enabled=True,
            engine=ParserEngine.TIKA,
            allowed_source_hosts=("objects.internal",),
            parser_base_url="http://tika.internal",
        )


def test_loopback_http_requires_an_explicit_development_exception() -> None:
    settings = ContentNormalizationSettings(
        enabled=True,
        engine=ParserEngine.TIKA,
        allowed_source_hosts=("objects.internal",),
        parser_base_url="http://127.0.0.1:9998",
        allow_loopback_http=True,
    )

    assert settings.parser_base_url == "http://127.0.0.1:9998"
