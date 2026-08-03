from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "vios_core_inert_producer", HERE / "producer.py"
)
assert SPEC is not None and SPEC.loader is not None
producer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = producer
SPEC.loader.exec_module(producer)


def _mutated_contract(tmp_path: Path, mutate) -> Path:
    value = json.loads((HERE / "contract.json").read_text())
    mutate(value)
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value))
    return path


def test_plan_is_inert_and_nonpromotable() -> None:
    plan = producer.compile_plan()
    assert plan["status"] == "pass"
    assert plan["runtime_evidence"] is False
    assert plan["aggregate_promotable"] is False
    assert plan["eligible_capability_ids"] == []
    assert all(
        plan[key] == 0
        for key in (
            "runtime_actions",
            "runtime_requests",
            "product_calls",
            "network_calls",
            "docker_calls",
            "service_lifecycle_calls",
            "model_calls",
            "subprocess_calls",
        )
    )
    assert len(plan["cases"]) == 6
    assert all(case["bound_satisfiable"] is False for case in plan["cases"])
    assert all(case["runtime_evidence"] is False for case in plan["cases"])


def test_product_fix_and_full_future_surfaces_are_explicit() -> None:
    plan = producer.compile_plan()
    gap = plan["effective_limit_product_gap"]
    assert gap["detected"] is False
    assert gap["source_fix_verified"] is True
    assert gap["requires_code_fix_before_runtime_qualification"] is False
    assert gap["runtime_qualified"] is False
    assert gap["unknown_length_policy"] == "reject"
    assert not any("product-gap fix" in blocker for blocker in plan["blockers"])
    assert any("asymmetric-limit evidence" in blocker for blocker in plan["blockers"])
    nvstreamer = next(
        case
        for case in plan["cases"]
        if case["capability_id"] == "runtime.nvstreamer.file-streaming"
    )
    assert {
        "exercise-upload-input",
        "exercise-ui-input",
        "exercise-local-mount-input",
        "verify-actual-webrtc-playback",
    }.issubset(nvstreamer["planned_steps"])
    assert all(fixture["ffmpeg_invoked"] is False for fixture in plan["fixture_plans"])


def test_source_digest_drift_fails_closed(tmp_path: Path) -> None:
    path = _mutated_contract(
        tmp_path, lambda value: value["source_locks"][0].update(sha256="0" * 64)
    )
    with pytest.raises(producer.ProducerError, match="source lock digest drift"):
        producer.compile_plan(path)


def test_oracle_index_substitution_fails_closed(tmp_path: Path) -> None:
    path = _mutated_contract(
        tmp_path, lambda value: value["oracle_bindings"][0].update(index=74)
    )
    with pytest.raises(producer.ProducerError, match="oracle binding drift"):
        producer.compile_plan(path)


def test_recorded_image_substitution_fails_closed(tmp_path: Path) -> None:
    path = _mutated_contract(
        tmp_path,
        lambda value: value["recorded_image_identities"][0].update(
            digest="sha256:" + "0" * 64
        ),
    )
    with pytest.raises(producer.ProducerError, match="recorded image identity drift"):
        producer.compile_plan(path)


def test_cli_has_no_execute_mode() -> None:
    with pytest.raises(SystemExit) as raised:
        producer.main(["execute"])
    assert raised.value.code == 2
