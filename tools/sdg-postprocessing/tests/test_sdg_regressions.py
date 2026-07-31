import importlib.util
import hashlib
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


def test_hdf5_wrapper_resolves_helper_relative_to_script(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    camera = dataset / "_World_Cameras_Camera"
    (camera / "rgb").mkdir(parents=True)
    (camera / "distance_to_image_plane_png").mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invocation_log = tmp_path / "python-args.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_PYTHON_LOG\"\n"
    )
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

        def create_dataset(self, name, *, data, dtype, compression) -> None:
            written_datasets[(self.name, name)] = (data.copy(), dtype, compression)

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
    fake_ffprobe.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$FFPROBE_LOG\"\n"
    )
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
    assert f"No B-frames found in: {dataset / '_World_Cameras_Camera' / 'video.mp4'}" in report
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
    assert list(
        UsdSemantics.LabelsAPI.Get(visible, "class").GetLabelsAttr().Get()
    ) == ["flatbox"]
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
        "x264-1%21164.3095-h4e544f5_2.tar.bz2#"
        + "a" * 64
        + "\n"
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
