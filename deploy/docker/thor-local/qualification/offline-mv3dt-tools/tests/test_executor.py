from __future__ import annotations

import ast
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest
import yaml
from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
REPO_ROOT = LANE.parents[4]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module("offline_mv3dt_executor_test", LANE / "executor.py")
CAM = load_module(
    "offline_mv3dt_cam_test",
    REPO_ROOT / "tools/rtvi-cv-mv3dt-utils/generate_cam_info_configs.py",
)
PUB = load_module(
    "offline_mv3dt_pub_test",
    REPO_ROOT / "tools/rtvi-cv-mv3dt-utils/generate_pub_sub_configs.py",
)


def write_calibration(path: Path, sensors: list[dict]) -> None:
    path.write_text(json.dumps({"sensors": sensors}), encoding="utf-8")


def valid_sensor(sensor_id: str = "camera_a") -> dict:
    return {
        "type": "camera",
        "id": sensor_id,
        "cameraMatrix": [
            [100.0, 70.710678, -70.710678, 707.10678],
            [0.0, 0.0, -141.421356, 707.10678],
            [0.0, 0.70710678, -0.70710678, 7.0710678],
        ],
    }


def model_entries():
    return CAM._parse_model_args([["0", "1.7", "0.3"]])


def test_candidate_executor_runs_twice_with_exact_locks_and_cleanup() -> None:
    result = EXECUTOR.execute()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(result)) == []
    assert result["candidate_only"] is True
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["runtime_evidence"] == []
    assert result["capability_ids"] == [
        "tool.mv3dt.cam-info-generator",
        "tool.mv3dt.pub-sub-generator",
    ]
    assert result["run_count"] == 2
    assert result["deterministic_runs"][0] == result["deterministic_runs"][1]
    assert result["cleanup"] == {
        "owned_root_removed": True,
        "adjacent_sentinel_unchanged": True,
        "parent_removed_after_observation": True,
    }
    assert not any(
        result[key]
        for key in ("network_used", "docker_used", "subprocess_used", "lifecycle_used")
    )
    assert result["warehouse_sample_bundle_used"] is False


def test_result_schema_rejects_fabricated_lock_keys_values_and_semantics() -> None:
    result = EXECUTOR.execute()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    mutations = []
    bad_source_value = copy.deepcopy(result)
    source_key = next(iter(bad_source_value["source_and_fixture_sha256"]))
    bad_source_value["source_and_fixture_sha256"][source_key] = "0" * 64
    mutations.append(bad_source_value)

    bad_source_key = copy.deepcopy(result)
    source_value = bad_source_key["source_and_fixture_sha256"].pop(source_key)
    bad_source_key["source_and_fixture_sha256"]["fabricated/source.py"] = source_value
    mutations.append(bad_source_key)

    bad_output = copy.deepcopy(result)
    bad_output["deterministic_runs"][0]["output_locks"]["full_output_tree_sha256"] = (
        "0" * 64
    )
    mutations.append(bad_output)

    bad_semantic = copy.deepcopy(result)
    bad_semantic["deterministic_runs"][0]["semantic"]["pub_sub"][
        "self_subscriptions"
    ] = 1
    mutations.append(bad_semantic)

    for fabricated in mutations:
        assert list(validator.iter_errors(fabricated))


def test_executor_rejects_unequal_runs_even_before_schema_validation() -> None:
    result = EXECUTOR.execute()
    result["deterministic_runs"][1]["file_sha256"]["camInfo/custom_cam_a.yml"] = (
        "0" * 64
    )
    with pytest.raises(EXECUTOR.QualificationError, match="identical runs"):
        EXECUTOR._validate_result(result)


def test_schema_embedded_locks_match_the_candidate_contract() -> None:
    contract = EXECUTOR._load_contract()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))
    source_properties = schema["properties"]["source_and_fixture_sha256"]["properties"]
    expected_sources = {
        item["path"]: item["sha256"] for item in contract["source_locks"]
    }
    expected_sources[contract["fixture"]["path"]] = contract["fixture"]["sha256"]
    assert {
        path: definition["const"] for path, definition in source_properties.items()
    } == expected_sources

    output_properties = schema["$defs"]["run"]["properties"]["output_locks"][
        "properties"
    ]
    assert {
        name: definition["const"] for name, definition in output_properties.items()
    } == contract["output_locks"]


def test_executor_rejects_dependency_version_digest_mismatch() -> None:
    result = EXECUTOR.execute()
    result["dependency_lock"]["observed_distribution_versions"]["numpy"] = "fake"
    with pytest.raises(EXECUTOR.QualificationError, match="version digest mismatch"):
        EXECUTOR._validate_result(result)


def test_candidate_semantics_cover_schema_matrix_ids_and_mqtt_topology() -> None:
    semantic = EXECUTOR.execute()["deterministic_runs"][0]["semantic"]
    assert set(semantic["cam_info"]) == {"custom_cam_a", "custom_cam_b"}
    for camera in semantic["cam_info"].values():
        assert camera == {
            "projection_shape": [3, 4],
            "projection_value_count": 12,
            "class_ids": [0, 1],
        }
    assert semantic["pub_sub"] == {
        "broker": "localhost:1883",
        "camera_ids": ["custom_cam_a", "custom_cam_b"],
        "topics": [
            "localhost:1883;/trck/custom_cam_a",
            "localhost:1883;/trck/custom_cam_b",
        ],
        "peer_counts": {"custom_cam_a": 1, "custom_cam_b": 1},
        "self_subscriptions": 0,
    }


def test_dependency_evidence_locks_declaration_and_observed_local_versions() -> None:
    lock = EXECUTOR.execute()["dependency_lock"]
    assert lock["requirements_sha256"] == (
        "8965115b8284cf715a14dcec429401b25c323685370a3d8bf05341ce19e028b4"
    )
    assert lock["declared_requirements"] == [
        "numpy==2.2.6",
        "opencv-python~=4.12.0",
        "PyYAML==6.0.2",
        "tqdm==4.67.1",
    ]
    assert set(lock["observed_distribution_versions"]) == {
        "numpy",
        "opencv-python",
        "PyYAML",
        "tqdm",
    }
    assert set(lock["observed_module_versions"]) == {"cv2", "numpy", "tqdm", "yaml"}
    assert lock["observed_versions_sha256"] == EXECUTOR._sha256(
        EXECUTOR._canonical_bytes(
            {
                "distributions": lock["observed_distribution_versions"],
                "modules": lock["observed_module_versions"],
            }
        )
    )


@pytest.mark.parametrize("sensor_id", ["../escape", "a/b", "a\\b", "..", "."])
def test_cam_generator_rejects_path_traversal_before_writing(
    tmp_path: Path, sensor_id: str
) -> None:
    calibration = tmp_path / "calibration.json"
    output = tmp_path / "output"
    write_calibration(calibration, [valid_sensor(sensor_id)])
    with pytest.raises(ValueError, match="unsafe"):
        CAM.generate_cam_info_files(calibration, output, model_entries())
    assert not output.exists()
    assert sorted(tmp_path.iterdir()) == [calibration]


def test_cam_generator_rejects_duplicate_ids_before_writing(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.json"
    output = tmp_path / "output"
    write_calibration(calibration, [valid_sensor("dup"), valid_sensor("dup")])
    with pytest.raises(ValueError, match="Duplicate camera sensor id"):
        CAM.generate_cam_info_files(calibration, output, model_entries())
    assert not output.exists()


@pytest.mark.parametrize("nonfinite", [math.nan, math.inf, -math.inf])
def test_cam_generator_rejects_nonfinite_projection_before_writing(
    tmp_path: Path, nonfinite: float
) -> None:
    calibration = tmp_path / "calibration.json"
    output = tmp_path / "output"
    sensor = valid_sensor()
    sensor["cameraMatrix"][0][0] = nonfinite
    write_calibration(calibration, [sensor])
    with pytest.raises(ValueError, match="Non-finite projection"):
        CAM.generate_cam_info_files(calibration, output, model_entries())
    assert not output.exists()


@pytest.mark.parametrize("token", ["nan", "inf", "-inf"])
def test_cam_generator_rejects_nonfinite_model_values(token: str) -> None:
    with pytest.raises(ValueError, match="Must be finite"):
        CAM._parse_model_args([["0", token, "0.3"]])


@pytest.mark.parametrize(
    "model_args,match",
    [
        ([["-1", "1.7", "0.3"]], "non-negative"),
        ([["0", "0", "0.3"]], "positive"),
        ([["0", "-0", "0.3"]], "positive"),
        ([["0", "-1.7", "0.3"]], "positive"),
        ([["0", "1.7", "0"]], "positive"),
        ([["0", "1.7", "-0"]], "positive"),
        ([["0", "1.7", "-0.3"]], "positive"),
        ([["0", "1.7", "0.3"], ["0", "1.2", "0.2"]], "Duplicate classID"),
    ],
)
def test_cam_generator_rejects_invalid_model_ranges_and_duplicate_ids(
    model_args: list[list[str]], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        CAM._parse_model_args(model_args)


def test_cam_generator_direct_call_cannot_bypass_model_validation(
    tmp_path: Path,
) -> None:
    calibration = tmp_path / "calibration.json"
    output = tmp_path / "output"
    write_calibration(calibration, [valid_sensor()])
    entries = [CAM.ModelInfoEntry(class_id=0, height_raw="-1", radius_raw="0.3")]
    with pytest.raises(ValueError, match="positive"):
        CAM.generate_cam_info_files(calibration, output, entries)
    assert not output.exists()


def test_cam_generator_accepts_sparse_unique_nonnegative_class_ids() -> None:
    entries = CAM._parse_model_args([["0", "1.7", "0.3"], ["99", "0.1", "2"]])
    assert [entry.class_id for entry in entries] == [0, 99]


def test_cam_generator_refuses_symlink_output(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.json"
    write_calibration(calibration, [valid_sensor()])
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "output"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symlink"):
        CAM.generate_cam_info_files(calibration, link, model_entries())
    assert list(real.iterdir()) == []


def test_cam_generator_preflights_all_output_symlinks_before_any_write(
    tmp_path: Path,
) -> None:
    calibration = tmp_path / "calibration.json"
    write_calibration(calibration, [valid_sensor("camera_a"), valid_sensor("camera_b")])
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside.yml"
    outside.write_text("unchanged\n", encoding="utf-8")
    (output / "camera_b.yml").symlink_to(outside)
    with pytest.raises(ValueError, match="Refusing to overwrite symlink"):
        CAM.generate_cam_info_files(calibration, output, model_entries())
    assert not (output / "camera_a.yml").exists()
    assert outside.read_text(encoding="utf-8") == "unchanged\n"


@pytest.mark.parametrize("with_dotdot", [False, True])
def test_cam_generator_rejects_symlinked_output_ancestor(
    tmp_path: Path, with_dotdot: bool
) -> None:
    calibration = tmp_path / "calibration.json"
    write_calibration(calibration, [valid_sensor()])
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    nested = outside / "nested"
    base.mkdir()
    nested.mkdir(parents=True)
    (base / "link").symlink_to(nested, target_is_directory=True)
    output = base / "link" / ("../escaped" if with_dotdot else "new/output")
    with pytest.raises(ValueError, match="symlink component"):
        CAM.generate_cam_info_files(calibration, output, model_entries())
    assert not (outside / "escaped").exists()
    assert not (nested / "new").exists()


def test_pub_sub_generator_rejects_empty_camera_input(tmp_path: Path) -> None:
    cam_info = tmp_path / "camInfo"
    cam_info.mkdir()
    with pytest.raises(ValueError, match="No camera info YAML files"):
        PUB.generate_pub_sub_config(cam_info, output_path=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_pub_sub_generator_rejects_unsafe_camera_name(tmp_path: Path) -> None:
    cam_info = tmp_path / "camInfo"
    cam_info.mkdir()
    (cam_info / "bad name.yml").write_text("modelInfo: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe camera name"):
        PUB.load_and_process_camera_matrices(cam_info)


def test_pub_sub_generator_rejects_duplicate_yaml_stems(tmp_path: Path) -> None:
    cam_info = tmp_path / "camInfo"
    cam_info.mkdir()
    payload = {
        "projectionMatrix_3x4_w2p": sum(valid_sensor()["cameraMatrix"], []),
        "modelInfo": [{"classID": 0, "height": 1.7, "radius": 0.3}],
    }
    text = yaml.safe_dump(payload)
    (cam_info / "same.yml").write_text(text, encoding="utf-8")
    (cam_info / "same.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate camera name"):
        PUB.load_and_process_camera_matrices(cam_info)


@pytest.mark.parametrize("with_dotdot", [False, True])
def test_pub_sub_generator_rejects_symlinked_output_ancestor(
    tmp_path: Path, with_dotdot: bool
) -> None:
    calibration = tmp_path / "calibration.json"
    cam_info = tmp_path / "camInfo"
    write_calibration(calibration, [valid_sensor()])
    CAM.generate_cam_info_files(calibration, cam_info, model_entries())
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    nested = outside / "nested"
    base.mkdir()
    nested.mkdir(parents=True)
    (base / "link").symlink_to(nested, target_is_directory=True)
    output = base / "link" / ("../escaped" if with_dotdot else "new/output")
    with pytest.raises(ValueError, match="symlink component"):
        PUB.generate_pub_sub_config(
            cam_info,
            minimum_object_size=1,
            neighbor_criteria="top_N:0",
            output_path=output,
            range_of_interest=[-4, -2, 6, 10],
        )
    assert not (outside / "escaped").exists()
    assert not (nested / "new").exists()


@pytest.mark.parametrize(
    "broker", ["", "localhost", "localhost:0", "localhost:65536", "bad;host:1883"]
)
def test_pub_sub_generator_rejects_invalid_broker(broker: str) -> None:
    with pytest.raises(ValueError, match="MQTT broker|broker port"):
        PUB._parse_brokers(broker)


def test_subscription_selection_is_deterministic_on_ties() -> None:
    overlap = {
        1: {2: 0.5, 3: 0.5},
        2: {1: 0.5, 3: 0.5},
        3: {1: 0.5, 2: 0.5},
    }
    assert PUB.get_subscription_map(overlap, "top_N:1") == {1: [2], 2: [1], 3: [1]}
    with pytest.raises(ValueError, match="between 0 and 1"):
        PUB.get_subscription_map(overlap, "overlap_threshold:nan")


def test_executor_source_has_no_network_docker_subprocess_or_lifecycle_primitive() -> (
    None
):
    source = (LANE / "executor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {"docker", "http", "requests", "socket", "subprocess", "urllib"}
    )
    for forbidden in ("os.system", "Popen", "compose up", "compose down"):
        assert forbidden not in source


def test_contract_is_exactly_candidate_only_and_excludes_sample_bundle() -> None:
    contract = EXECUTOR._load_contract()
    assert contract["planned_non_compose_role"] == "repository-tooling"
    assert (
        contract["acceptance_boundary"] == "alternate_local_lane_custom_data_warehouse"
    )
    assert contract["policy"]["warehouse_sample_bundle"] == "excluded"
    assert contract["fixture"]["warehouse_sample_bundle"] is False
    assert contract["policy"]["runtime_evidence"] == []
    tampered = copy.deepcopy(contract)
    tampered["policy"]["candidate_only"] = False
    original = EXECUTOR._strict_json
    try:
        EXECUTOR._strict_json = lambda _path: tampered
        with pytest.raises(EXECUTOR.QualificationError, match="policy drift"):
            EXECUTOR._load_contract()
    finally:
        EXECUTOR._strict_json = original
