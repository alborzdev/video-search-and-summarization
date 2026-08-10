from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_sdr_verify", HERE / "verify.py")
assert SPEC is not None and SPEC.loader is not None
verify_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_module
SPEC.loader.exec_module(verify_module)


def test_checked_in_runtime_and_source_contracts_pass() -> None:
    result = verify_module.verify()
    assert result == {
        "status": "passed",
        "verifier_id": "vios-sdr-compose-runtime",
        "runtime_assertions": 9,
        "cleanup_verified": True,
        "warehouse_sample_used": False,
    }


def test_bridge_redis_exposure_is_narrow_and_explicit() -> None:
    compose = verify_module.yaml.load(
        verify_module.COMPOSE_PATH.read_text(encoding="utf-8"),
        Loader=verify_module.ComposeLoader,
    )
    command = compose["services"]["redis"]["command"]
    assert command[command.index("--bind") + 1 : command.index("--protected-mode")] == [
        "127.0.0.1",
        "${THOR_LOCAL_MODEL_BIND_HOST:-127.0.0.1}",
    ]
    assert not any("0.0.0.0" in str(value) for value in command)


def test_evidence_fails_closed_on_cleanup_drift() -> None:
    evidence = verify_module._load_json(verify_module.EVIDENCE_PATH)
    evidence["cleanup"]["proxy_count_after"] = 1
    with pytest.raises(verify_module.ContractError, match="cleanup drift"):
        verify_module.verify_evidence(evidence)
