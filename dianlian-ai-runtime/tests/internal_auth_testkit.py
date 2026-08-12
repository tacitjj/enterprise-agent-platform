from __future__ import annotations

from typing import Any
from uuid import UUID

from dianlian_runtime.app import create_app
from dianlian_runtime.auth import (
    InternalServicePrincipal,
    InternalServiceScope,
)


class TrustedTestInternalServiceAuthenticator:
    @property
    def ready(self) -> bool:
        return True

    def authorize(
        self,
        token: str,
        required_scope: InternalServiceScope,
    ) -> InternalServicePrincipal:
        del token
        return InternalServicePrincipal(
            subject="dianlian-platform",
            token_id=UUID("00000000-0000-4000-8000-000000000043"),
            scopes=frozenset({required_scope}),
            issued_at=0,
            expires_at=60,
        )


def create_test_app(*args: Any, **kwargs: Any):
    kwargs["internal_service_authenticator"] = (
        TrustedTestInternalServiceAuthenticator()
    )
    return create_app(*args, **kwargs)
