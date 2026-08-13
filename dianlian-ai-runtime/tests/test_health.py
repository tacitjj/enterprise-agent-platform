from fastapi.testclient import TestClient
import pytest

from dianlian_runtime.app import create_app
from dianlian_runtime.config import RuntimeSettings
from tests.internal_auth_testkit import create_test_app


class RecordingRunSupervisor:
    def __init__(
        self,
        *,
        become_ready: bool = True,
        fail_start: bool = False,
    ) -> None:
        self.ready = False
        self.become_ready = become_ready
        self.fail_start = fail_start
        self.start_count = 0
        self.close_count = 0

    async def start(self) -> None:
        self.start_count += 1
        if self.fail_start:
            raise RuntimeError("supervisor startup failed")
        self.ready = self.become_ready

    async def close(self) -> None:
        self.close_count += 1
        self.ready = False


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


def test_agent_worker_flags_cannot_claim_readiness_without_a_supervisor() -> None:
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
    runtime_status = client.get("/internal/v1/runtime/status")

    assert response.status_code == 503
    assert response.json()["status"] == "OUT_OF_SERVICE"
    assert runtime_status.json()["agent"] == {"enabled": True, "ready": False}
    assert runtime_status.json()["supervisor"] == {"enabled": True, "ready": False}


def test_agent_worker_is_ready_only_while_the_injected_supervisor_is_ready() -> None:
    settings = RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="agent-worker",
        context_enabled=False,
        agent_enabled=True,
        supervisor_enabled=True,
    )
    supervisor = RecordingRunSupervisor()

    with TestClient(create_app(settings, run_supervisor=supervisor)) as client:
        assert supervisor.start_count == 1
        assert client.get("/internal/v1/health/readiness").status_code == 200
        runtime_status = client.get("/internal/v1/runtime/status").json()
        assert runtime_status["agent"] == {"enabled": True, "ready": True}
        assert runtime_status["supervisor"] == {"enabled": True, "ready": True}

    assert supervisor.close_count == 1
    assert supervisor.ready is False


def test_started_but_unready_supervisor_fails_closed() -> None:
    settings = RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="agent-worker",
        context_enabled=False,
        agent_enabled=True,
        supervisor_enabled=True,
    )
    supervisor = RecordingRunSupervisor(become_ready=False)

    with TestClient(create_app(settings, run_supervisor=supervisor)) as client:
        assert client.get("/internal/v1/health/readiness").status_code == 503
        assert client.get("/internal/v1/runtime/status").json()["supervisor"] == {
            "enabled": True,
            "ready": False,
        }

    assert supervisor.start_count == 1
    assert supervisor.close_count == 1


def test_supervisor_start_failure_still_closes_the_partial_lifecycle() -> None:
    settings = RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="agent-worker",
        context_enabled=False,
        agent_enabled=True,
        supervisor_enabled=True,
    )
    supervisor = RecordingRunSupervisor(fail_start=True)

    with pytest.raises(RuntimeError, match="supervisor startup failed"):
        with TestClient(create_app(settings, run_supervisor=supervisor)):
            pass

    assert supervisor.start_count == 1
    assert supervisor.close_count == 1


def test_missing_service_jwt_key_ring_keeps_runtime_alive_but_not_ready() -> None:
    client = TestClient(create_app(_settings()))

    assert client.get("/internal/v1/health/liveness").status_code == 200
    readiness = client.get("/internal/v1/health/readiness")

    assert readiness.status_code == 503
    assert readiness.json()["status"] == "OUT_OF_SERVICE"
