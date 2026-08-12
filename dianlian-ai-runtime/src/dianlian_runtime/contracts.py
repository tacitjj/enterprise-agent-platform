from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["UP", "OUT_OF_SERVICE"]
    service: str
    version: str
    role: str
    observed_at: datetime = Field(alias="observedAt")

    @classmethod
    def now(
        cls,
        *,
        status: Literal["UP", "OUT_OF_SERVICE"],
        service: str,
        version: str,
        role: str,
    ) -> "HealthResponse":
        return cls(
            status=status,
            service=service,
            version=version,
            role=role,
            observedAt=datetime.now(timezone.utc),
        )


class RuntimeFeatureStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    ready: bool


class RuntimeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    role: str
    context: RuntimeFeatureStatus
    agent: RuntimeFeatureStatus
    supervisor: RuntimeFeatureStatus

