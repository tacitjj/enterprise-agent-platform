from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from dianlian_runtime.app import create_app
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.harness.structured_run_driver import StructuredRunExecutionDriver


class RecordingRunSupervisor:
    def __init__(self) -> None:
        self.ready = False
        self.start_count = 0
        self.close_count = 0

    async def start(self) -> None:
        self.start_count += 1
        self.ready = True

    async def close(self) -> None:
        self.close_count += 1
        self.ready = False


def _settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test-runtime-v1",
        role="agent-worker",
        context_enabled=False,
        agent_enabled=True,
        supervisor_enabled=True,
        governed_h12_driver_enabled=True,
        runtime_environment="local",
        governed_h12_store_backend="local",
        run_supervisor_database_dsn=(
            "postgresql://executor:secret@database.invalid/runtime"
        ),
        run_supervisor_agent_name="governed-h12-v1",
        governed_h12_data_dir=tmp_path / "h12",
        runtime_model_service_base_url="https://java.internal",
        runtime_model_service_jwt_key_id="runtime-key-1",
        runtime_model_service_jwt_private_key_path=tmp_path / "private.pem",
    )


def _structured_settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="structured-runtime-v1",
        role="agent-worker",
        context_enabled=False,
        agent_enabled=True,
        supervisor_enabled=True,
        structured_driver_enabled=True,
        run_supervisor_database_dsn=(
            "postgresql://executor:secret@database.invalid/runtime"
        ),
        run_supervisor_agent_name="structured-capability-v1",
        runtime_model_service_base_url="https://java.internal",
        runtime_model_service_jwt_key_id="runtime-key-1",
        runtime_model_service_jwt_private_key_path=tmp_path / "private.pem",
    )


def test_governed_worker_settings_are_explicit_and_hide_the_executor_dsn(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    assert settings.governed_h12_driver_enabled is True
    assert settings.governed_h12_permit_ttl_seconds == 10
    assert settings.run_supervisor_lease_seconds == 30
    assert "secret" not in repr(settings)

    with pytest.raises(ValueError, match="agent-worker"):
        replace(settings, role="runtime-api")
    with pytest.raises(ValueError, match="shorter than the Run lease"):
        replace(settings, governed_h12_permit_ttl_seconds=30)
    with pytest.raises(ValueError, match="GOVERNED_H12_DATA_DIR"):
        replace(settings, governed_h12_data_dir=None)
    with pytest.raises(ValueError, match="local runtime environment"):
        replace(settings, runtime_environment="production")
    postgres = replace(
        settings,
        runtime_environment="production",
        governed_h12_store_backend="postgres",
        governed_h12_data_dir=None,
    )
    assert postgres.governed_h12_store_backend == "postgres"
    with pytest.raises(ValueError, match="does not accept a local data directory"):
        replace(settings, governed_h12_store_backend="postgres")


def test_environment_reads_the_governed_worker_composition_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "agent-worker")
    monkeypatch.setenv("DIANLIAN_RUNTIME_VERSION", "runtime-v2")
    monkeypatch.setenv("DIANLIAN_AGENT_ENABLED", "true")
    monkeypatch.setenv("DIANLIAN_RUN_SUPERVISOR_ENABLED", "true")
    monkeypatch.setenv("DIANLIAN_GOVERNED_H12_DRIVER_ENABLED", "true")
    monkeypatch.setenv("DIANLIAN_RUNTIME_ENVIRONMENT", "local")
    monkeypatch.setenv("DIANLIAN_GOVERNED_H12_STORE_BACKEND", "local")
    monkeypatch.setenv(
        "DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN",
        "postgresql://executor:secret@database.invalid/runtime",
    )
    monkeypatch.setenv("DIANLIAN_RUN_SUPERVISOR_AGENT_NAME", "governed-h12-v2")
    monkeypatch.setenv("DIANLIAN_GOVERNED_H12_DATA_DIR", str(tmp_path / "h12"))
    monkeypatch.setenv(
        "DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL",
        "https://java.internal",
    )
    monkeypatch.setenv("DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID", "runtime-key-1")
    monkeypatch.setenv(
        "DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH",
        str(tmp_path / "private.pem"),
    )

    settings = RuntimeSettings.from_environment()

    assert settings.service_version == "runtime-v2"
    assert settings.runtime_environment == "local"
    assert settings.governed_h12_store_backend == "local"
    assert settings.run_supervisor_agent_name == "governed-h12-v2"
    assert settings.governed_h12_data_dir == tmp_path / "h12"
    assert "secret" not in repr(settings)


def test_app_composes_and_owns_the_opted_in_supervisor_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    supervisor = RecordingRunSupervisor()
    recorded: list[RuntimeSettings] = []

    def compose(candidate: RuntimeSettings) -> RecordingRunSupervisor:
        recorded.append(candidate)
        return supervisor

    monkeypatch.setattr(
        "dianlian_runtime.supervisor.composition.create_governed_h12_run_supervisor",
        compose,
    )

    app = create_app(settings)
    assert app.state.run_supervisor is supervisor
    with TestClient(app) as client:
        assert client.get("/internal/v1/health/liveness").status_code == 200
        assert supervisor.start_count == 1
        assert supervisor.ready is True

    assert recorded == [settings]
    assert supervisor.close_count == 1
    assert supervisor.ready is False


def test_structured_worker_settings_are_explicit_and_mutually_exclusive(
    tmp_path: Path,
) -> None:
    settings = _structured_settings(tmp_path)

    assert settings.structured_driver_enabled is True
    assert settings.structured_driver_permit_ttl_seconds == 10
    assert "secret" not in repr(settings)

    with pytest.raises(ValueError, match="mutually exclusive"):
        replace(settings, governed_h12_driver_enabled=True)
    with pytest.raises(ValueError, match="shorter than the Run lease"):
        replace(settings, structured_driver_permit_ttl_seconds=30)
    with pytest.raises(ValueError, match="agent-worker"):
        replace(settings, role="runtime-api")


def test_environment_reads_the_structured_worker_composition_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "agent-worker")
    monkeypatch.setenv("DIANLIAN_RUNTIME_VERSION", "structured-runtime-v2")
    monkeypatch.setenv("DIANLIAN_AGENT_ENABLED", "true")
    monkeypatch.setenv("DIANLIAN_RUN_SUPERVISOR_ENABLED", "true")
    monkeypatch.setenv("DIANLIAN_STRUCTURED_DRIVER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN",
        "postgresql://executor:secret@database.invalid/runtime",
    )
    monkeypatch.setenv(
        "DIANLIAN_RUN_SUPERVISOR_AGENT_NAME",
        "structured-capability-v2",
    )
    monkeypatch.setenv(
        "DIANLIAN_STRUCTURED_DRIVER_PERMIT_TTL_SECONDS",
        "12",
    )
    monkeypatch.setenv(
        "DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL",
        "https://java.internal",
    )
    monkeypatch.setenv("DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID", "runtime-key-1")
    monkeypatch.setenv(
        "DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH",
        str(tmp_path / "private.pem"),
    )

    settings = RuntimeSettings.from_environment()

    assert settings.structured_driver_enabled is True
    assert settings.structured_driver_permit_ttl_seconds == 12
    assert settings.run_supervisor_agent_name == "structured-capability-v2"
    assert "secret" not in repr(settings)


def test_app_composes_the_structured_supervisor_only_after_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _structured_settings(tmp_path)
    supervisor = RecordingRunSupervisor()
    recorded: list[RuntimeSettings] = []

    def compose(candidate: RuntimeSettings) -> RecordingRunSupervisor:
        recorded.append(candidate)
        return supervisor

    monkeypatch.setattr(
        "dianlian_runtime.supervisor.composition.create_structured_run_supervisor",
        compose,
    )

    app = create_app(settings)
    assert app.state.run_supervisor is supervisor
    with TestClient(app) as client:
        assert client.get("/internal/v1/health/readiness").status_code == 200
        assert supervisor.start_count == 1

    assert recorded == [settings]
    assert supervisor.close_count == 1


def test_structured_composition_builds_an_exact_30_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from dianlian_runtime.supervisor import composition

    settings = _structured_settings(tmp_path)
    supervisor = RecordingRunSupervisor()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        composition,
        "H12RuntimeServiceJwtIssuer",
        lambda **_kwargs: object(),
    )

    def worker_factory(
        _repository: object,
        driver: object,
        **kwargs: object,
    ) -> RecordingRunSupervisor:
        captured["driver"] = driver
        captured.update(kwargs)
        return supervisor

    monkeypatch.setattr(composition, "DormantRunSupervisorWorker", worker_factory)

    result = composition.create_structured_run_supervisor(settings)

    assert result is supervisor
    assert isinstance(captured["driver"], StructuredRunExecutionDriver)
    assert captured["admission_contract_version"] == "3.0"
    assert captured["agent_name"] == "structured-capability-v1"
