from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
SPEC = importlib.util.spec_from_file_location(
    "nvstreamer_sync_playback_execute", HERE / "execute.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._strict_json(b'{"status":"pass","status":"fail"}', "test")


def test_config_overrides_are_exact_and_non_secret() -> None:
    overrides = json.loads((HERE / "config-overrides.json").read_text())
    assert overrides["data"] == {
        "nv_streamer_loop_playback": True,
        "nv_streamer_sync_file_count": 2,
        "nv_streamer_sync_playback": False,
    }
    assert overrides["network"]["http_port"] == "31010"
    assert overrides["network"]["rtsp_server_port"] == 31654
    assert overrides["network"]["rtsp_server_instances_count"] == 1
    assert overrides["network"]["server_domain_name"] == "127.0.0.1"
    assert overrides["notifications"]["enable_notification"] is False
    assert overrides["observability"]["enable_telemetry"] is False
    source = (HERE / "config-overrides.json").read_text().lower()
    assert "nvapi-" not in source
    assert "api_key" not in source


def test_deep_merge_rejects_unknown_keys_or_type_changes() -> None:
    assert executor._deep_merge({"data": {"count": 0}}, {"data": {"count": 2}}) == {
        "data": {"count": 2}
    }
    with pytest.raises(executor.QualificationError, match="unknown key"):
        executor._deep_merge({"data": {}}, {"missing": 2})
    with pytest.raises(executor.QualificationError, match="object type"):
        executor._deep_merge({"data": 1}, {"data": {"count": 2}})


def test_ffmpeg_target_must_remain_on_reserved_loopback() -> None:
    command = executor._ffmpeg_command(
        "rtsp://127.0.0.1:31654/nvstream/home/vst/vst_release/streamer_videos/a.mp4"
    )
    assert "tcp" in command
    assert "-frames:v" in command
    with pytest.raises(executor.QualificationError, match="escaped"):
        executor._ffmpeg_command(
            "rtsp://192.0.2.1:31654/nvstream/home/vst/vst_release/streamer_videos/a.mp4"
        )


def test_executor_is_isolated_and_fail_closed() -> None:
    source = (HERE / "execute.py").read_text()
    assert '"--network",\n        "bridge"' in source
    assert '"--cap-drop",\n        "ALL"' in source
    assert '"no-new-privileges"' in source
    assert '"warehouse_sample_bundle_used": False' in source
    assert '"main_vios_sensor_added": False' in source
    assert '"rt_cv_stream_added": False' in source
    assert '"agent_generate_called": False' in source
    assert "SYNC_MARKER" in source
    assert "completion_skew_ms > 250" in source


def test_retained_receipt_proves_barrier_and_cleanup_when_present() -> None:
    path = HERE / "runtime-receipt.json"
    if not path.exists():
        pytest.skip("runtime receipt is created only by an explicit qualification run")
    receipt = json.loads(path.read_text())
    contract = json.loads((HERE / "fixture-contract.json").read_text())
    barrier = receipt["observations"]["barrier"]
    assert receipt["status"] == "passed"
    assert receipt["capability_results"][executor.CAPABILITY_ID] == "passed_current"
    assert receipt["fixture"]["files_byte_identical"] is True
    assert receipt["fixture"]["file_count"] == 2
    assert receipt["fixture"]["bytes"] == contract["expected_bytes"]
    assert receipt["fixture"]["sha256"] == contract["expected_media_sha256"]
    assert receipt["fixture"]["profile"] == contract["video"]["profile"]
    assert receipt["fixture"]["b_frames"] == 0
    assert receipt["fixture"]["keyint"] == 30
    assert barrier["single_client_barrier_held"] is True
    assert barrier["pre_barrier_sync_start_count"] == 0
    assert barrier["second_client_released_barrier"] is True
    assert barrier["decoded_frame_count_per_client"] == [1, 1]
    assert barrier["shared_clock_start_count"] == 1
    assert barrier["first_frame_completion_skew_ms"] <= 250
    assert receipt["cleanup"]["result"] == "passed"
    assert receipt["cleanup"]["exact_container_inventory_restored"] is True
    assert receipt["cleanup"]["exact_running_set_restored"] is True
    assert receipt["cleanup"]["all_reserved_ports_released"] is True


def test_official_evidence_is_hash_bound_to_current_oracle_and_ledger() -> None:
    evidence_path = HERE / "official-runtime-evidence.json"
    fixture_path = HERE / "fixture-contract.json"
    receipt_path = HERE / "runtime-receipt.json"
    evidence = json.loads(evidence_path.read_text())
    ledger = json.loads(
        (REPO / "deploy/docker/thor-local/parity/official-capabilities.json").read_text()
    )
    oracles = json.loads(
        (REPO / "deploy/docker/thor-local/parity/capability-oracles.json").read_text()
    )
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == executor.CAPABILITY_ID
    )
    oracle = next(
        row for row in oracles["oracles"] if row["capability_id"] == executor.CAPABILITY_ID
    )
    contract_identity = next(
        row for row in evidence["observations"] if row["id"] == "contract_identity"
    )

    assert capability["runtime_state"] == "passed_current"
    assert capability["thor_state"] == "wired"
    assert capability["runtime_evidence"] == [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "nvstreamer-sync-playback-runtime/official-runtime-evidence.json"
            ),
            "sha256": executor._sha(evidence_path.read_bytes()),
        }
    ]
    assert evidence["oracle_sha256"] == executor._sha(executor._canonical(oracle))
    assert evidence["fixture"]["sha256"] == executor._sha(fixture_path.read_bytes())
    assert contract_identity["value"]["raw_receipt_sha256"] == executor._sha(
        receipt_path.read_bytes()
    )
    assert len(evidence["assertions"]) == len(oracle["assertions"]) == 11
    assert oracle["acceptance_readiness"] == {
        "classification": "executor_ready",
        "blockers": [],
    }
