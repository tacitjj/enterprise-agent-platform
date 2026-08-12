from fastapi.testclient import TestClient

from dianlian_runtime.app import create_app
from dianlian_runtime.config import RuntimeSettings
from tests.internal_auth_testkit import create_test_app


def _settings(*, role: str = "runtime-api") -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role=role,
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
    )


def test_runtime_api_is_live_and_ready_without_claiming_ai_features() -> None:
    client = TestClient(create_test_app(_settings()))

    liveness = client.get("/internal/v1/health/liveness")
    readiness = client.get("/internal/v1/health/readiness")
    runtime_status = client.get("/internal/v1/runtime/status")

    assert liveness.status_code == 200
    assert readiness.status_code == 200
    assert runtime_status.status_code == 200
    assert runtime_status.json()["context"] == {"enabled": False, "ready": False}
    assert runtime_status.json()["agent"] == {"enabled": False, "ready": False}
    assert runtime_status.json()["supervisor"] == {"enabled": False, "ready": False}


def test_disabled_worker_role_is_not_ready() -> None:
    client = TestClient(create_test_app(_settings(role="agent-worker")))

    response = client.get("/internal/v1/health/readiness")

    assert response.status_code == 503
    assert response.json()["status"] == "OUT_OF_SERVICE"


def test_agent_worker_readiness_does_not_depend_on_context_ingress_keys() -> None:
    settings = RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="agent-worker",
        context_enabled=False,
        agent_enabled=True,
        supervisor_enabled=True,
    )
    client = TestClient(create_app(settings))

    response = client.get("/internal/v1/health/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "UP"


def test_missing_service_jwt_key_ring_keeps_runtime_alive_but_not_ready() -> None:
    client = TestClient(create_app(_settings()))

    assert client.get("/internal/v1/health/liveness").status_code == 200
    readiness = client.get("/internal/v1/health/readiness")

    assert readiness.status_code == 503
    assert readiness.json()["status"] == "OUT_OF_SERVICE"
