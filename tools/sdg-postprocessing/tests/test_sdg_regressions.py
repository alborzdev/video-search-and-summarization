import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid

import numpy as np
import pytest


SDG_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    module_name = f"sdg_test_{path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_ground_truth_converter(monkeypatch: pytest.MonkeyPatch):
    class FakeMatrix4d:
        def __init__(self, value=None) -> None:
            if isinstance(value, FakeMatrix4d):
                self.translation = value.translation
            else:
                self.translation = (0.0, 0.0, 0.0)

        def SetIdentity(self):
            self.translation = (0.0, 0.0, 0.0)
            return self

        def SetTranslate(self, value):
            self.translation = tuple(float(item) for item in value)
            return self

        def SetRotate(self, _rotation):
            return self

        def __mul__(self, other):
            result = FakeMatrix4d()
            result.translation = tuple(
                left + right for left, right in zip(self.translation, other.translation)
            )
            return result

    class FakeUsdQuaternion:
        def GetReal(self) -> float:
            return 1.0

        def GetImaginary(self) -> tuple[float, float, float]:
            return (0.0, 0.0, 0.0)

    class FakeRotation:
        def GetQuat(self) -> FakeUsdQuaternion:
            return FakeUsdQuaternion()

    class FakeTransform:
        def __init__(self, matrix: FakeMatrix4d) -> None:
            self.matrix = matrix

        def GetTranslation(self) -> tuple[float, float, float]:
            return self.matrix.translation

        def GetRotation(self) -> FakeRotation:
            return FakeRotation()

        def GetScale(self) -> np.ndarray:
            return np.ones(3, dtype=float)

    class FakeQuaternion:
        def __init__(self, *_args) -> None:
            self.yaw_pitch_roll = (0.0, 0.0, 0.0)

    fake_pxr = types.ModuleType("pxr")

    def fake_vec3d(*value):
        items = value[0] if len(value) == 1 else value
        return tuple(float(item) for item in items)

    fake_pxr.Gf = types.SimpleNamespace(
        Matrix4d=FakeMatrix4d,
        Rotation=lambda axis, degrees: (axis, degrees),
        Transform=FakeTransform,
        Vec3d=fake_vec3d,
    )
    fake_pyquaternion = types.ModuleType("pyquaternion")
    fake_pyquaternion.Quaternion = FakeQuaternion
    fake_matplotlib = types.ModuleType("matplotlib")
    fake_pyplot = types.ModuleType("matplotlib.pyplot")
    fake_patches = types.ModuleType("matplotlib.patches")
    fake_matplotlib.pyplot = fake_pyplot
    fake_matplotlib.patches = fake_patches
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pyquaternion", fake_pyquaternion)
    monkeypatch.setitem(sys.modules, "matplotlib", fake_matplotlib)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", fake_pyplot)
    monkeypatch.setitem(sys.modules, "matplotlib.patches", fake_patches)
    return load_module(SDG_ROOT / "data_conversion" / "convert_ground_truth.py")


def write_tiny_ground_truth_fixture(root: Path) -> None:
    annotations = root / "_World_Cameras_Camera" / "object_detection"
    annotations.mkdir(parents=True)
    identity = np.eye(4, dtype=float).tolist()
    payload = {
        "boxes": {
            "/World/CustomBox": {
                "label": {"class": "box"},
                "annotators": {
                    "bounding_box_2d_tight_fast": {
                        "x_min": 1,
                        "y_min": 2,
                        "x_max": 5,
                        "y_max": 6,
                        "semanticId": 7,
                        "occlusionRatio": 0.0,
                    },
                    "bounding_box_2d_loose_fast": {
                        "x_min": 0,
                        "y_min": 1,
                        "x_max": 6,
                        "y_max": 7,
                        "semanticId": 7,
                        "occlusionRatio": 0.0,
                    },
                    "bounding_box_3d_fast": {
                        "x_min": -1.0,
                        "x_max": 1.0,
                        "y_min": -2.0,
                        "y_max": 2.0,
                        "z_min": 0.0,
                        "z_max": 2.0,
                        "transform": identity,
                        "semanticId": 7,
                        "occlusionRatio": 0.0,
                    },
                },
            }
        }
    }
    (annotations / "object_detection_00000.json").write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )


def run_tiny_ground_truth_conversion(
    converter, root: Path, output: Path, xform_info: Path | None = None
) -> dict[str, bytes]:
    arguments = [str(root), "--output", str(output), "--skip-visualization"]
    if xform_info is not None:
        arguments.extend(["--xform_info", str(xform_info)])
    converter.main(arguments)
    expected_names = {
        "ground_truth.json",
        "bounding_boxes.json",
        "rotation_keys_with_rot.json",
        "corners_comparison_dict.json",
    }
    assert {path.name for path in output.iterdir()} == expected_names
    return {name: (output / name).read_bytes() for name in sorted(expected_names)}


def test_ground_truth_conversion_only_cli_is_tiny_deterministic_and_sample_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    converter = load_ground_truth_converter(monkeypatch)
    source = (SDG_ROOT / "data_conversion" / "convert_ground_truth.py").read_text()
    assert "warehouse-4cams-20mx20m-synthetic" not in source
    assert "warehouse-loading-dock-3cams-synthetic" not in source

    fixture_roots = [tmp_path / f"custom-sdg-fixture-{suffix}" for suffix in "abcd"]
    for fixture_root in fixture_roots:
        write_tiny_ground_truth_fixture(fixture_root)
    xform_info = tmp_path / "custom-xform-info.json"
    xform_info.write_text(
        json.dumps({"/World/CustomBox": {"rotate": [10.0, 20.0, 30.0]}}),
        encoding="utf-8",
    )

    without_xform_a = run_tiny_ground_truth_conversion(
        converter, fixture_roots[0], tmp_path / "output-a"
    )
    without_xform_b = run_tiny_ground_truth_conversion(
        converter, fixture_roots[1], tmp_path / "output-b"
    )
    with_xform_a = run_tiny_ground_truth_conversion(
        converter, fixture_roots[2], tmp_path / "output-c", xform_info
    )
    with_xform_b = run_tiny_ground_truth_conversion(
        converter, fixture_roots[3], tmp_path / "output-d", xform_info
    )

    for fixture_root in fixture_roots:
        assert (fixture_root / "_World_Cameras_Camera").is_dir()
        assert not (fixture_root / "Camera").exists()
    assert without_xform_a == without_xform_b
    assert with_xform_a == with_xform_b
    ground_truth = json.loads(without_xform_a["ground_truth.json"])
    assert ground_truth["0"][0]["object name"] == "/World/CustomBox"
    assert ground_truth["0"][0]["object id"] == 0
    assert ground_truth["0"][0]["3d location"] == [0.0, 0.0, 1.0]
    assert ground_truth["0"][0]["3d bounding box scale"] == [2.0, 4.0, 2.0]
    assert (
        len(json.loads(without_xform_a["bounding_boxes.json"])["0"]["/World/CustomBox"])
        == 1
    )


def test_ground_truth_visualization_mode_requires_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    converter = load_ground_truth_converter(monkeypatch)
    fixture = tmp_path / "custom-sdg-fixture"
    write_tiny_ground_truth_fixture(fixture)

    with pytest.raises(SystemExit, match="2"):
        converter.main([str(fixture), "--output", str(tmp_path / "output")])

    assert (fixture / "_World_Cameras_Camera").is_dir()
    assert not (tmp_path / "output").exists()


def test_ground_truth_default_cli_preserves_image_and_video_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    converter = load_ground_truth_converter(monkeypatch)
    fixture = tmp_path / "custom-sdg-fixture"
    output = tmp_path / "output"
    calibration = tmp_path / "custom-calibration.json"
    write_tiny_ground_truth_fixture(fixture)
    calibration.write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        converter.utils_for_vis,
        "process_image",
        lambda _self, scene, calibration_path, destination, frame_id_list: calls.append(
            ("image", scene, calibration_path, destination, tuple(frame_id_list))
        ),
    )
    monkeypatch.setattr(
        converter.utils_for_vis,
        "process_video_across_cameras",
        lambda _self, scene, calibration_path, destination, max_frames=None: (
            calls.append(("video", scene, calibration_path, destination, max_frames))
        ),
    )

    converter.main(
        [
            str(fixture),
            "--calibration",
            str(calibration),
            "--output",
            str(output),
            "--max_frames",
            "1",
        ]
    )

    assert [call[0] for call in calls] == ["image", "video"]
    assert calls[0][4] == (0, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000)
    assert calls[1][4] == 1


def test_hdf5_wrapper_resolves_helper_relative_to_script(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    camera = dataset / "_World_Cameras_Camera"
    (camera / "rgb").mkdir(parents=True)
    (camera / "distance_to_image_plane_png").mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invocation_log = tmp_path / "python-args.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$FAKE_PYTHON_LOG"\n')
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_PYTHON_LOG"] = str(invocation_log)
    wrapper = SDG_ROOT / "data_conversion" / "convert_depth_rgb_to_h5_restarable.sh"
    result = subprocess.run(
        ["bash", str(wrapper), str(dataset)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    args = invocation_log.read_text().splitlines()
    assert args == [
        str(SDG_ROOT / "data_conversion" / "convert_single_camera_rgb_depth_to_h5.py"),
        "--input",
        str(camera),
    ]
    assert (camera / "convert_done.txt").is_file()


def test_hdf5_converter_imports_and_uses_concurrency_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written_datasets = {}

    class FakeGroup:
        def __init__(self, name: str) -> None:
            self.name = name

        def create_dataset(
            self, name, *, data, dtype, compression, track_times
        ) -> None:
            written_datasets[(self.name, name)] = (
                data.copy(),
                dtype,
                compression,
                track_times,
            )

    class FakeFile:
        def __init__(self, path, mode) -> None:
            self.path = path
            self.mode = mode

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def create_group(self, name: str) -> FakeGroup:
            return FakeGroup(name)

    fake_h5py = types.ModuleType("h5py")
    fake_h5py.File = FakeFile
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.imread = lambda path, flags: (
        np.ones((2, 2, 3), dtype=np.uint8)
        if str(path).endswith(".jpg")
        else np.ones((2, 2), dtype=np.uint16)
    )
    fake_tqdm = types.ModuleType("tqdm")
    fake_tqdm.tqdm = lambda iterable, **kwargs: iterable
    monkeypatch.setitem(sys.modules, "h5py", fake_h5py)
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setitem(sys.modules, "tqdm", fake_tqdm)

    converter = load_module(
        SDG_ROOT / "data_conversion" / "convert_single_camera_rgb_depth_to_h5.py"
    )
    camera = tmp_path / "Camera01"
    (camera / "rgb").mkdir(parents=True)
    (camera / "distance_to_image_plane_png").mkdir()
    (camera / "rgb" / "rgb_00000.jpg").touch()
    (camera / "distance_to_image_plane_png" / "depth_00000.png").touch()

    converter.convert_camera_to_h5(str(camera))

    assert set(written_datasets) == {
        ("rgb", "rgb_00000.jpg"),
        ("distance_to_image_plane_png", "depth_00000.png"),
    }
    assert all(value[2] == "gzip" for value in written_datasets.values())
    assert all(value[3] is False for value in written_datasets.values())


def test_velocity_step_uses_frame_argument_and_requested_interval() -> None:
    velocity = load_module(
        SDG_ROOT / "data_sanity_check" / "dataset_sanity_check_velocity.py"
    )
    frames = {
        str(index): [
            {
                "object name": "obj1",
                "3d location": [float(index), 0.0, 0.0],
            }
        ]
        for index in range(3)
    }

    speeds = velocity.process_frames(frames, step=2)

    assert speeds == {"Frame 0 -> Frame 2": {"obj1": [30.0, 0.0]}}
    with pytest.raises(ValueError, match="greater than zero"):
        velocity.process_frames(frames, step=0)


def test_png_check_accepts_canonical_and_legacy_camera_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.imread = lambda path, flags: object()
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    checker = load_module(
        SDG_ROOT / "data_sanity_check" / "dataset_sanity_check_png.py"
    )

    for camera_name in ("_World_Cameras_Camera", "Camera01"):
        depth_dir = tmp_path / camera_name / "distance_to_image_plane_png"
        depth_dir.mkdir(parents=True)
        (depth_dir / "distance_to_image_plane_00000.png").touch()

    output_log = tmp_path / "png-check.log"
    checker.sanity_check(str(tmp_path), 1, str(output_log))

    log = output_log.read_text()
    assert "Found 2 camera directories." in log
    assert str(tmp_path / "_World_Cameras_Camera") in log
    assert str(tmp_path / "Camera01") in log


def test_video_check_accepts_canonical_and_legacy_camera_names(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    for camera_name in ("_World_Cameras_Camera", "Camera01"):
        camera = dataset / camera_name
        camera.mkdir(parents=True)
        (camera / "video.mp4").touch()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ffprobe_log = tmp_path / "ffprobe-calls.txt"
    fake_ffprobe = fake_bin / "ffprobe"
    fake_ffprobe.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FFPROBE_LOG"\n')
    fake_ffprobe.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FFPROBE_LOG"] = str(ffprobe_log)
    checker = SDG_ROOT / "data_sanity_check" / "dataset_sanity_check_videos.sh"

    result = subprocess.run(
        ["bash", str(checker), str(dataset)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = (dataset / "bframes_check_results.txt").read_text()
    assert (
        f"No B-frames found in: {dataset / '_World_Cameras_Camera' / 'video.mp4'}"
        in report
    )
    assert f"No B-frames found in: {dataset / 'Camera01' / 'video.mp4'}" in report
    assert len(ffprobe_log.read_text().splitlines()) == 2


def test_headless_openusd_semantic_label_roundtrip(tmp_path: Path) -> None:
    Usd = pytest.importorskip("pxr.Usd")
    UsdGeom = pytest.importorskip("pxr.UsdGeom")
    UsdSemantics = pytest.importorskip("pxr.UsdSemantics")

    box_check = load_module(SDG_ROOT / "semantic_labeling" / "box_check.py")
    remove_label = load_module(SDG_ROOT / "semantic_labeling" / "remove_label.py")
    exporter = load_module(SDG_ROOT / "utils" / "export_xform_semantics.py")

    stage_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(stage_path))
    world = UsdGeom.Xform.Define(stage, "/World")
    world.AddRotateXYZOp().Set((10.0, 20.0, 30.0))
    visible = UsdGeom.Mesh.Define(stage, "/World/FlatBox_body").GetPrim()
    hidden_parent = UsdGeom.Xform.Define(stage, "/World/Hidden")
    hidden_parent.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
    UsdGeom.Mesh.Define(stage, "/World/Hidden/CardBox")

    categorized, hidden = box_check.categorize_boxes(stage, apply_labels=True)

    assert categorized == {"flatbox": ["/World/FlatBox_body"]}
    assert hidden == ["/World/Hidden/CardBox"]
    assert list(UsdSemantics.LabelsAPI.Get(visible, "class").GetLabelsAttr().Get()) == [
        "flatbox"
    ]
    exported = exporter.collect_semantics(stage)
    assert exported["/World/FlatBox_body"] == {
        "xform_path": "/World",
        "rotate": [10.0, 20.0, 30.0],
    }
    assert remove_label.remove_all_semantics(stage) == 1
    assert not UsdSemantics.LabelsAPI.GetDirectTaxonomies(visible)


def test_thor_local_conda_lock_preserves_literal_epoch_filename(tmp_path: Path) -> None:
    materializer = load_module(SDG_ROOT / "thor" / "materialize_local_lock.py")
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    package = package_dir / "x264-1!164.3095-h4e544f5_2.tar.bz2"
    package.touch()
    source = tmp_path / "source.lock"
    source.write_text(
        "@EXPLICIT\n"
        "https://conda.example/linux-aarch64/"
        "x264-1%21164.3095-h4e544f5_2.tar.bz2#" + "a" * 64 + "\n"
    )
    output = tmp_path / "local.lock"

    assert materializer.materialize(source, package_dir, output) == 1

    rendered = output.read_text()
    assert "x264-1!164.3095-h4e544f5_2.tar.bz2#" in rendered
    assert "%21" not in rendered


def write_wheel_contract(
    tmp_path: Path, *, wheel_name: str = "example_pkg-1.2.3-py3-none-any.whl"
) -> tuple[object, Path, Path, Path]:
    verifier = load_module(SDG_ROOT / "thor" / "verify_offline_cache.py")
    cache = tmp_path / "cache"
    wheels = cache / "wheels"
    wheels.mkdir(parents=True)
    artifact = wheels / wheel_name
    artifact.write_bytes(b"locked wheel bytes")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-pkg==1.2.3\n", encoding="utf-8")
    lock = tmp_path / "wheels.sha256"
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    lock.write_text(f"{digest}  wheels/{wheel_name}\n", encoding="utf-8")
    return verifier, cache, requirements, lock


def test_thor_wheel_lock_rejects_missing_wheel(tmp_path: Path) -> None:
    verifier, cache, requirements, lock = write_wheel_contract(tmp_path)
    (cache / "wheels/example_pkg-1.2.3-py3-none-any.whl").unlink()

    with pytest.raises(ValueError, match="Committed wheel inventory mismatch"):
        verifier.verify_wheels(cache, requirements, lock)


def test_thor_wheel_lock_rejects_substituted_wheel(tmp_path: Path) -> None:
    verifier, cache, requirements, lock = write_wheel_contract(tmp_path)
    original = cache / "wheels/example_pkg-1.2.3-py3-none-any.whl"
    original.rename(cache / "wheels/example_pkg-1.2.3-evil-any.whl")

    with pytest.raises(ValueError, match="Committed wheel inventory mismatch"):
        verifier.verify_wheels(cache, requirements, lock)


def test_thor_wheel_lock_rejects_tampered_bytes(tmp_path: Path) -> None:
    verifier, cache, requirements, lock = write_wheel_contract(tmp_path)
    artifact = cache / "wheels/example_pkg-1.2.3-py3-none-any.whl"
    artifact.write_bytes(b"different wheel bytes")

    with pytest.raises(ValueError, match="Committed wheel checksum mismatch"):
        verifier.verify_wheels(cache, requirements, lock)
