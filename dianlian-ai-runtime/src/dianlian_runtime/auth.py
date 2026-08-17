from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
import time
from typing import Protocol
from uuid import UUID

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
import jwt

from dianlian_runtime.config import RuntimeSettings


SERVICE_JWT_ISSUER = "dianlian-platform"
SERVICE_JWT_AUDIENCE = "dianlian-ai-runtime"
SERVICE_JWT_SUBJECT = "dianlian-platform"
SERVICE_JWT_TOKEN_USE = "service"
SERVICE_JWT_MAX_TTL_SECONDS = 60
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MAX_TOKEN_LENGTH = 16_384
_MAX_PUBLIC_KEY_FILE_SIZE = 65_536


class InternalServiceScope(StrEnum):
    CONTEXT_INDEX_WRITE = "context.index.write"
    CONTEXT_RETRIEVE = "context.retrieve"
    AGENT_RUNTIME_EXECUTE = "agent.runtime.execute"
    RUNTIME_EXTERNAL_PERMIT_AUTHORIZE = "runtime.external-permit.authorize"
    RUNTIME_EXTERNAL_DISPATCH_ARM = "runtime.external-dispatch.arm"
    RUNTIME_EXTERNAL_OUTCOME_RECORD = "runtime.external-outcome.record"
    RUNTIME_EXTERNAL_OUTCOME_RECONCILE = "runtime.external-outcome.reconcile"
    RUNTIME_RUN_ADMIT = "runtime.run.admit"
    RUNTIME_RUN_OBSERVE = "runtime.run.observe"
    RUNTIME_RUN_CANCEL = "runtime.run.cancel"


class InternalServiceAuthError(RuntimeError):
    pass


class InternalServiceAuthUnavailable(InternalServiceAuthError):
    pass


class InternalServiceAuthenticationRequired(InternalServiceAuthError):
    pass


class InternalServiceScopeDenied(InternalServiceAuthError):
    pass


class InternalServiceAuthConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InternalServicePrincipal:
    subject: str
    token_id: UUID
    scopes: frozenset[InternalServiceScope]
    issued_at: int
    expires_at: int


class InternalServiceAuthenticator(Protocol):
    @property
    def ready(self) -> bool: ...

    def authorize(
        self,
        token: str,
        required_scope: InternalServiceScope,
    ) -> InternalServicePrincipal: ...


class UnavailableInternalServiceAuthenticator:
    @property
    def ready(self) -> bool:
        return False

    def authorize(
        self,
        token: str,
        required_scope: InternalServiceScope,
    ) -> InternalServicePrincipal:
        del token, required_scope
        raise InternalServiceAuthUnavailable("internal service authentication is unavailable")


class Rs256InternalServiceAuthenticator:
    def __init__(
        self,
        public_keys: dict[str, RSAPublicKey],
        *,
        clock_skew_seconds: int,
    ) -> None:
        if not public_keys:
            raise InternalServiceAuthConfigurationError(
                "internal service JWT public key ring must not be empty"
            )
        if not 0 <= clock_skew_seconds <= 10:
            raise InternalServiceAuthConfigurationError(
                "internal service JWT clock skew must be between 0 and 10 seconds"
            )
        self._public_keys = dict(public_keys)
        self._clock_skew_seconds = clock_skew_seconds

    @property
    def ready(self) -> bool:
        return True

    def authorize(
        self,
        token: str,
        required_scope: InternalServiceScope,
    ) -> InternalServicePrincipal:
        if not token or len(token) > _MAX_TOKEN_LENGTH:
            raise InternalServiceAuthenticationRequired("invalid internal service token")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or header.get("typ") != "JWT":
                raise InternalServiceAuthenticationRequired("invalid internal service token")
            key_id = header.get("kid")
            if not isinstance(key_id, str) or not _KEY_ID_PATTERN.fullmatch(key_id):
                raise InternalServiceAuthenticationRequired("invalid internal service token")
            public_key = self._public_keys.get(key_id)
            if public_key is None:
                raise InternalServiceAuthenticationRequired("invalid internal service token")

            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256"],
                audience=SERVICE_JWT_AUDIENCE,
                issuer=SERVICE_JWT_ISSUER,
                subject=SERVICE_JWT_SUBJECT,
                leeway=self._clock_skew_seconds,
                options={
                    "require": [
                        "iss",
                        "sub",
                        "aud",
                        "iat",
                        "exp",
                        "jti",
                        "token_use",
                        "scope",
                    ],
                    "strict_aud": False,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_jti": True,
                    "verify_sub": True,
                    "enforce_minimum_key_length": True,
                },
            )
            principal = self._validate_claims(claims)
        except InternalServiceAuthError:
            raise
        except (jwt.PyJWTError, TypeError, ValueError, KeyError) as exception:
            raise InternalServiceAuthenticationRequired(
                "invalid internal service token"
            ) from exception

        if required_scope not in principal.scopes:
            raise InternalServiceScopeDenied("internal service token scope is insufficient")
        return principal

    def _validate_claims(self, claims: dict[str, object]) -> InternalServicePrincipal:
        if claims.get("token_use") != SERVICE_JWT_TOKEN_USE:
            raise InternalServiceAuthenticationRequired("invalid internal service token")
        raw_audience = claims.get("aud")
        if raw_audience not in (
            SERVICE_JWT_AUDIENCE,
            [SERVICE_JWT_AUDIENCE],
        ):
            raise InternalServiceAuthenticationRequired("invalid internal service token")

        issued_at = _epoch_claim(claims.get("iat"))
        expires_at = _epoch_claim(claims.get("exp"))
        now = int(time.time())
        if issued_at > now + self._clock_skew_seconds:
            raise InternalServiceAuthenticationRequired("invalid internal service token")
        if expires_at <= issued_at or expires_at - issued_at > SERVICE_JWT_MAX_TTL_SECONDS:
            raise InternalServiceAuthenticationRequired("invalid internal service token")

        raw_token_id = claims.get("jti")
        if not isinstance(raw_token_id, str):
            raise InternalServiceAuthenticationRequired("invalid internal service token")
        token_id = UUID(raw_token_id)

        raw_scope = claims.get("scope")
        if not isinstance(raw_scope, str) or not raw_scope.strip():
            raise InternalServiceAuthenticationRequired("invalid internal service token")
        scope_values = raw_scope.split()
        if len(scope_values) != len(set(scope_values)):
            raise InternalServiceAuthenticationRequired("invalid internal service token")
        try:
            scopes = frozenset(InternalServiceScope(value) for value in scope_values)
        except ValueError as exception:
            raise InternalServiceAuthenticationRequired(
                "invalid internal service token"
            ) from exception

        return InternalServicePrincipal(
            subject=SERVICE_JWT_SUBJECT,
            token_id=token_id,
            scopes=scopes,
            issued_at=issued_at,
            expires_at=expires_at,
        )


def create_internal_service_authenticator(
    settings: RuntimeSettings,
) -> InternalServiceAuthenticator:
    raw_ring = settings.service_jwt_public_key_ring_json
    if raw_ring is None:
        return UnavailableInternalServiceAuthenticator()
    try:
        public_keys = _load_public_key_ring(raw_ring)
        return Rs256InternalServiceAuthenticator(
            public_keys,
            clock_skew_seconds=settings.service_jwt_clock_skew_seconds,
        )
    except (
        InternalServiceAuthConfigurationError,
        OSError,
        UnsupportedAlgorithm,
        ValueError,
        TypeError,
    ):
        return UnavailableInternalServiceAuthenticator()


def _load_public_key_ring(raw_ring: str) -> dict[str, RSAPublicKey]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise InternalServiceAuthConfigurationError(
                    "internal service JWT public key ring contains duplicate key IDs"
                )
            result[key] = value
        return result

    try:
        configured_paths = json.loads(raw_ring, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exception:
        raise InternalServiceAuthConfigurationError(
            "internal service JWT public key ring must be valid JSON"
        ) from exception
    if not isinstance(configured_paths, dict) or not 1 <= len(configured_paths) <= 8:
        raise InternalServiceAuthConfigurationError(
            "internal service JWT public key ring must contain between 1 and 8 keys"
        )

    public_keys: dict[str, RSAPublicKey] = {}
    for key_id, configured_path in configured_paths.items():
        if not _KEY_ID_PATTERN.fullmatch(key_id):
            raise InternalServiceAuthConfigurationError(
                "internal service JWT public key ring contains an invalid key ID"
            )
        if not isinstance(configured_path, str) or not configured_path:
            raise InternalServiceAuthConfigurationError(
                "internal service JWT public key path is invalid"
            )
        public_key_path = Path(configured_path)
        if not public_key_path.is_absolute() or not public_key_path.is_file():
            raise InternalServiceAuthConfigurationError(
                "internal service JWT public key path is unavailable"
            )
        if public_key_path.stat().st_size > _MAX_PUBLIC_KEY_FILE_SIZE:
            raise InternalServiceAuthConfigurationError(
                "internal service JWT public key file is too large"
            )
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(public_key, RSAPublicKey) or public_key.key_size < 2048:
            raise InternalServiceAuthConfigurationError(
                "internal service JWT public key must be RSA with at least 2048 bits"
            )
        public_keys[key_id] = public_key
    return public_keys


def _epoch_claim(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InternalServiceAuthenticationRequired("invalid internal service token")
    return value
