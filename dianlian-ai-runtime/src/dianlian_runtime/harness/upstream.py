from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import types


class DeerFlowUpstreamError(RuntimeError):
    pass


def load_pinned_deerflow(
    source_root: Path,
    *,
    lock_file: Path | None = None,
) -> dict[str, object]:
    """Load only the pinned Harness packages and fence eager App imports.

    DeerFlow's ``deerflow.runtime`` package initializer imports the full worker and
    model stack. H0 deliberately exercises only the Gateway persistence kernel, so
    this loader exposes the runtime namespace without importing the App/UI/model
    entrypoints. All such internal handling remains inside this adapter module.
    """

    root = source_root.resolve()
    lock_path = lock_file or Path(__file__).parents[3] / "upstream" / "deerflow.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected_commit = str(lock["commit"])
    actual_commit = _read_checkout_commit(root)
    if actual_commit != expected_commit:
        raise DeerFlowUpstreamError(
            f"DeerFlow checkout must be pinned to {expected_commit}; got {actual_commit}"
        )

    harness_path = root / "backend" / "packages" / "harness"
    extension_path = root / "backend" / "packages" / "extension-api"
    for package_path in (harness_path, extension_path):
        if not package_path.is_dir():
            raise DeerFlowUpstreamError(
                f"Pinned DeerFlow package directory is missing: {package_path}"
            )
        package_text = str(package_path)
        if package_text not in sys.path:
            sys.path.insert(0, package_text)

    runtime_path = harness_path / "deerflow" / "runtime"
    _install_namespace("deerflow.runtime", runtime_path)
    _install_namespace("deerflow.runtime.runs", runtime_path / "runs")
    return lock


def _read_checkout_commit(source_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exception:
        raise DeerFlowUpstreamError(
            f"Cannot verify DeerFlow checkout at {source_root}"
        ) from exception
    return completed.stdout.strip()


def _install_namespace(name: str, path: Path) -> None:
    existing = sys.modules.get(name)
    if existing is not None:
        existing_paths = tuple(str(value) for value in getattr(existing, "__path__", ()))
        if str(path) not in existing_paths:
            raise DeerFlowUpstreamError(
                f"Conflicting module {name} was imported before the pinned adapter"
            )
        return
    module = types.ModuleType(name)
    module.__package__ = name
    module.__path__ = [str(path)]
    sys.modules[name] = module
