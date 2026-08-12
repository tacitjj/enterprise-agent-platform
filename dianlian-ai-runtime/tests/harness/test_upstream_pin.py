import json
import re
from pathlib import Path


LOCK_FILE = Path(__file__).parents[2] / "upstream" / "deerflow.lock.json"


def test_deerflow_poc_candidate_is_an_immutable_non_production_pin() -> None:
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))

    assert lock["status"] == "poc-candidate"
    assert re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
    assert lock["repository"] == "https://github.com/bytedance/deer-flow.git"
    assert lock["integrationMode"] == "gateway-runtime-kernel-behind-dianlian-adapter"
    assert lock["productionApproved"] is False
    assert lock["memoryPolicy"] == {
        "enabled": False,
        "injectionEnabled": False,
        "managerClass": "noop",
    }
    assert "upstream-compatibility" in lock["requiredGates"]
    assert "scope-isolation" in lock["requiredGates"]
