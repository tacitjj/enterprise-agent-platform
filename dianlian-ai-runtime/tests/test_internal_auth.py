from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
import pytest

from dianlian_runtime.app import create_app
from dianlian_runtime.config import RuntimeSettings


KEY_ID = "service-test-current"


def _settings(public_key_ring_json: str | None) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        service_jwt_public_key_ring_json=public_key_ring_json,
    )


def _key_pair(public_key_path: Path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_key


def _claims(*, scope: str) -> dict[str, object]:
    now = int(time.time())
    return {
        "iss": "dianlian-platform",
        "sub": "dianlian-platform",
        "aud": "dianlian-ai-runtime",
        "iat": now,
        "exp": now + 30,
        "jti": str(uuid4()),
        "token_use": "service",
        "scope": scope,
    }


def _token(private_key, claims: dict[str, object], *, key_id: str = KEY_ID) -> str:
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"alg": "RS256", "typ": "JWT", "kid": key_id},
    )


def _client(tmp_path: Path):
    public_key_path = tmp_path / "temporary-public-key.pem"
    private_key = _key_pair(public_key_path)
    ring = json.dumps({KEY_ID: str(public_key_path)})
    return TestClient(create_app(_settings(ring))), private_key


def test_context_endpoints_require_their_exact_service_scopes(tmp_path: Path) -> None:
    client, private_key = _client(tmp_path)
    retrieval_token = _token(private_key, _claims(scope="context.retrieve"))
    indexing_token = _token(private_key, _claims(scope="context.index.write"))

    assert client.post(
        "/internal/v1/retrieval/search",
        headers={"Authorization": f"Bearer {retrieval_token}"},
        json={},
    ).status_code == 422
    assert client.post(
        "/internal/v1/indexing/apply",
        headers={"Authorization": f"Bearer {retrieval_token}"},
        json={},
    ).status_code == 403
    assert client.post(
        "/internal/v1/indexing/apply",
        headers={"Authorization": f"Bearer {indexing_token}"},
        json={},
    ).status_code == 422
    assert client.post(
        "/internal/v1/retrieval/search",
        headers={"Authorization": f"Bearer {indexing_token}"},
        json={},
    ).status_code == 403


def test_missing_token_is_unauthorized_without_leaking_validation_details(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.post("/internal/v1/retrieval/search", json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "code": "INTERNAL_SERVICE_AUTHENTICATION_REQUIRED",
        "message": "A valid internal service token is required",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda claims: claims.update({"iss": "dianlian-public-api"}),
        lambda claims: claims.update({"aud": "dianlian-public-api"}),
        lambda claims: claims.update(
            {"aud": ["dianlian-ai-runtime", "dianlian-public-api"]}
        ),
        lambda claims: claims.update({"sub": "enterprise-user"}),
        lambda claims: claims.update({"token_use": "user"}),
        lambda claims: claims.pop("scope"),
        lambda claims: claims.update({"scope": "context.retrieve unknown.scope"}),
        lambda claims: claims.update({"jti": "not-a-uuid"}),
        lambda claims: claims.update(
            {"iat": int(time.time()) - 120, "exp": int(time.time()) - 60}
        ),
        lambda claims: claims.update({"exp": int(claims["iat"]) + 61}),
        lambda claims: claims.update({"iat": int(time.time()) + 11}),
    ],
)
def test_wrong_claims_expiry_and_oversized_ttl_are_rejected(
    tmp_path: Path,
    mutate,
) -> None:
    client, private_key = _client(tmp_path)
    claims = deepcopy(_claims(scope="context.retrieve"))
    mutate(claims)

    response = client.post(
        "/internal/v1/retrieval/search",
        headers={"Authorization": f"Bearer {_token(private_key, claims)}"},
        json={},
    )

    assert response.status_code == 401


def test_nimbus_single_audience_array_is_accepted(tmp_path: Path) -> None:
    client, private_key = _client(tmp_path)
    claims = _claims(scope="context.retrieve")
    claims["aud"] = ["dianlian-ai-runtime"]

    response = client.post(
        "/internal/v1/retrieval/search",
        headers={"Authorization": f"Bearer {_token(private_key, claims)}"},
        json={},
    )

    assert response.status_code == 422


def test_generated_openapi_declares_service_bearer_and_operation_scopes(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)

    schema = client.get("/internal/v1/openapi.json").json()

    security_scheme = schema["components"]["securitySchemes"][
        "InternalServiceBearer"
    ]
    assert security_scheme["type"] == "http"
    assert security_scheme["scheme"] == "bearer"
    assert security_scheme["bearerFormat"] == "JWT"
    assert schema["paths"]["/internal/v1/retrieval/search"]["post"][
        "security"
    ] == [{"InternalServiceBearer": []}]
    assert schema["paths"]["/internal/v1/retrieval/search"]["post"][
        "x-required-scopes"
    ] == ["context.retrieve"]
    assert schema["paths"]["/internal/v1/indexing/apply"]["post"][
        "x-required-scopes"
    ] == ["context.index.write"]


def test_user_hmac_token_and_unknown_key_id_are_rejected(tmp_path: Path) -> None:
    client, private_key = _client(tmp_path)
    user_token = jwt.encode(
        _claims(scope="context.retrieve"),
        "temporary-test-user-secret-that-is-not-used-outside-this-test",
        algorithm="HS256",
        headers={"typ": "JWT", "kid": KEY_ID},
    )
    unknown_key_token = _token(
        private_key,
        _claims(scope="context.retrieve"),
        key_id="service-test-unknown",
    )

    assert client.post(
        "/internal/v1/retrieval/search",
        headers={"Authorization": f"Bearer {user_token}"},
        json={},
    ).status_code == 401
    assert client.post(
        "/internal/v1/retrieval/search",
        headers={"Authorization": f"Bearer {unknown_key_token}"},
        json={},
    ).status_code == 401


def test_public_key_ring_accepts_both_kids_during_rotation(tmp_path: Path) -> None:
    old_public_key_path = tmp_path / "old-public-key.pem"
    new_public_key_path = tmp_path / "new-public-key.pem"
    old_private_key = _key_pair(old_public_key_path)
    new_private_key = _key_pair(new_public_key_path)
    ring = json.dumps(
        {
            "service-old": str(old_public_key_path),
            "service-new": str(new_public_key_path),
        }
    )
    client = TestClient(create_app(_settings(ring)))

    for key_id, private_key in (
        ("service-old", old_private_key),
        ("service-new", new_private_key),
    ):
        token = _token(
            private_key,
            _claims(scope="context.retrieve"),
            key_id=key_id,
        )
        response = client.post(
            "/internal/v1/retrieval/search",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 422


def test_missing_or_invalid_key_ring_fails_closed(tmp_path: Path) -> None:
    missing_ring_client = TestClient(create_app(_settings(None)))
    invalid_ring = json.dumps({KEY_ID: str(tmp_path / "missing-public-key.pem")})
    invalid_ring_client = TestClient(create_app(_settings(invalid_ring)))

    for client in (missing_ring_client, invalid_ring_client):
        response = client.post("/internal/v1/retrieval/search", json={})
        assert response.status_code == 503
        assert response.json()["code"] == "INTERNAL_SERVICE_AUTH_UNAVAILABLE"
        assert client.get("/internal/v1/health/liveness").status_code == 200
        assert client.get("/internal/v1/health/readiness").status_code == 503
