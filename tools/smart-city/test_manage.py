# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest


def test_recorded_preset_uses_current_site_revision(root, monkeypatch):
    media = root / ".spark/city/media"
    media.mkdir(parents=True)
    (media / "traffic-sample.mp4").write_bytes(b"test-only")
    (media / "pedestrian-sample.mp4").write_bytes(b"test-only")
    request = Mock(
        side_effect=[{"id": "recorded-traffic-tests", "revision": 8}, {}, {}]
    )
    monkeypatch.setattr(module, "request", request)
    module.recorded("spark")
    assert request.call_args_list[0].args == ("site",)
    site = request.call_args_list[1].args[1]
    assert site["revision"] == 9
    assert site["expectedRevision"] == 8


def test_live_tuning_rejects_arbitrary_flags_and_invalid_timeouts(root):
    assert module.live_mux_timeout("spark") is None
    path = root / ".spark/city/state/runtime-tuning.json"
    path.parent.mkdir(parents=True)
    for value in (
        {"muxTimeoutUs": True},
        {"muxTimeoutUs": 999},
        {"muxTimeoutUs": 1000001},
        {"args": ["--unsafe"]},
    ):
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            module.live_mux_timeout("spark")
    path.write_text('{"muxTimeoutUs":10000}')
    assert module.live_mux_timeout("spark") == 10000


spec = importlib.util.spec_from_file_location(
    "city_manage_under_test", Path(__file__).with_name("manage.py")
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return tmp_path


def test_profile_activation_is_additive_and_recreates_only_agent(root, monkeypatch):
    base = root / ".spark/compose.json"
    base.parent.mkdir(parents=True)
    original = '{"services":{"vss-agent":{"environment":{"EXISTING":"keep"}},"model":{"image":"unchanged"}}}'
    base.write_text(original)
    run = Mock()
    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module, "ensure_headroom", Mock())
    monkeypatch.setattr(module, "controller_health", lambda: {"ready": True})
    module.profile_activate("spark", True)
    overlay = json.loads((root / ".spark/city/agent-city-overlay.json").read_text())
    assert overlay == {
        "services": {
            "vss-agent": {
                "environment": {"VSS_CITY_RTVI_CV_URL": "http://127.0.0.1:9190"}
            }
        }
    }
    assert base.read_text() == original
    arguments = run.call_args.args
    assert arguments[-10:] == ("-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "--wait", "--wait-timeout", "120", "vss-agent")
    assert "model" not in arguments
    module.profile_activate("spark", False)
    assert (
        json.loads((root / ".spark/city/agent-city-overlay.json").read_text())[
            "services"
        ]["vss-agent"]["environment"]["VSS_CITY_RTVI_CV_URL"]
        == ""
    )


def test_profile_disable_keeps_active_worker_control_url(root, monkeypatch):
    run = Mock()
    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module, "ensure_headroom", Mock())
    monkeypatch.setattr(module, "controller_health", lambda: {
        "stream-info": {"stream-info": [{"camera_id": "owned-camera", "status": "running"}]}
    })
    with pytest.raises(RuntimeError, match="Pause all Smart City sources"):
        module.profile_activate("spark", False)
    run.assert_not_called()
    assert not (root / ".spark/city/agent-city-overlay.json").exists()


def test_controller_stop_never_signals_reused_or_unrelated_pid(root, monkeypatch):
    directory = module.state_dir("spark")
    ticks = (Path("/proc") / str(os.getpid()) / "stat").read_text().split()[21]
    (directory / "runtime/controller-process.json").write_text(
        json.dumps({"pid": os.getpid(), "startTicks": ticks})
    )
    kill = Mock()
    monkeypatch.setattr(module.os, "kill", kill)
    assert module.controller_process("spark") is None
    module.controller_stop("spark")
    kill.assert_not_called()


def test_cpu_controller_setup_does_not_start_docker_or_models(root, monkeypatch):
    run = Mock()
    monkeypatch.setattr(module, "run", run)
    python = module.controller_setup("spark")
    assert python == root / ".spark/city/control-env/bin/python"
    assert run.call_count == 2
    assert run.call_args_list[0].args[1:3] == ("-m", "venv")
    assert (
        run.call_args_list[1]
        .args[-1]
        .endswith("tools/smart-city/controller-requirements.txt")
    )
    assert all("docker" not in call.args for call in run.call_args_list)


def test_user_service_is_reviewable_local_host_process(root, tmp_path, monkeypatch):
    python = root / ".spark/city/control-env/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    path = module.controller_service("spark")
    text = path.read_text()
    assert "controller.py --device spark" in text
    assert "MemoryMax=512M" in text
    assert "docker.sock" not in text
    assert "EnvironmentFile=" in text


def test_source_analysis_routes_through_canonical_agent_and_escapes_identity(
    monkeypatch,
):
    request = Mock(return_value={"state": "active"})
    monkeypatch.setattr(module, "agent_request", request)
    module.source_analysis("source/id", "recorded", "smart-city", "", "configure")
    request.assert_called_with(
        "videos/source%2Fid/analysis", {"analysisProfileId": "smart-city"}
    )
    module.source_analysis(
        "live-id", "live", "smart-city", "Exact source name", "pause"
    )
    request.assert_called_with(
        "rtsp-streams/live-id/analysis",
        {
            "action": "pause",
            "name": "Exact source name",
            "analysisProfileId": "smart-city",
        },
    )
    with pytest.raises(ValueError, match="exact registered"):
        module.source_analysis("live-id", "live", "smart-city", "", "configure")


def test_thor_runtime_changes_rejected_on_actual_spark(root, monkeypatch):
    monkeypatch.setattr(
        module,
        "hardware_inventory",
        lambda: {"platform": "spark", "gpu": "NVIDIA GB10"},
    )
    with pytest.raises(RuntimeError, match="actual Thor host"):
        module.build("thor", True)
    with pytest.raises(RuntimeError, match="actual Thor host"):
        module.controller_start("thor")
    with pytest.raises(RuntimeError, match="actual Thor host"):
        module.native("thor", 10, False)
    assert module.compose_file("thor").is_file()


def test_thor_engine_requires_target_build_receipt_and_rejects_spark_binary(root):
    directory = root / ".thor/city/models"
    directory.mkdir(parents=True)
    engine = directory / "rfdetr-small-fp16-b2.engine"
    engine.write_bytes(b"target engine")
    with pytest.raises(RuntimeError, match="engine-build.json"):
        module.require_native_engine("thor")
    digest = module.hashlib.sha256(engine.read_bytes()).hexdigest()
    (directory / "engine-build.json").write_text(
        json.dumps({"device": "thor", "gpu": "NVIDIA Thor", "engineSha256": digest})
    )
    module.require_native_engine("thor")
    spark = root / ".spark/city/models/rfdetr-small-fp16-b2.engine"
    spark.parent.mkdir(parents=True)
    spark.write_bytes(engine.read_bytes())
    with pytest.raises(RuntimeError, match="Spark TensorRT engine"):
        module.require_native_engine("thor")


def test_model_module_retains_digest_cache_but_invalidates_changed_artifact(tmp_path):
    module.city_model_module.cache_clear()
    try:
        first = module.city_model_module()
        assert module.city_model_module() is first
        artifact = tmp_path / "private-artifact"
        artifact.write_bytes(b"first artifact")
        initial = first.digest(artifact)
        assert module.city_model_module().digest(artifact) == initial
        assert first._digest_at_stat.cache_info().misses == 1
        assert first._digest_at_stat.cache_info().hits == 1

        artifact.write_bytes(b"changed artifact with different size")
        assert module.city_model_module().digest(artifact) != initial
        assert first._digest_at_stat.cache_info().misses == 2
    finally:
        module.city_model_module.cache_clear()


@pytest.mark.parametrize("live", [False, True])
def test_only_live_launch_uses_stable_bounded_output_family(root, monkeypatch, live):
    directory = module.state_dir("spark")
    (directory / "media/fixture.mp4").write_bytes(b"private CPU fixture")
    historical = directory / "state/observations-preserved.ndjson"
    historical.write_bytes(b"existing qualification bytes\n")
    monkeypatch.setattr(module, "require_actual_device", Mock())
    monkeypatch.setattr(module, "require_native_engine", Mock())
    monkeypatch.setattr(module, "ensure_headroom", Mock())
    monkeypatch.setattr(module, "request", lambda path: {
        "id": "test-city", "mode": "live" if live else "recorded-inference",
        "sources": [{"id": "camera", "width": 1280, "height": 720,
            "inputUri": "rtsp://127.0.0.1/test" if live else "file:///media/fixture.mp4"}],
    })
    monkeypatch.setattr(module, "city_model_module", lambda: SimpleNamespace(
        config_for_launch=lambda root, device: {"nativeArgs": []}
    ))
    process = SimpleNamespace(poll=lambda: 0, returncode=0)
    popen = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    module.native("spark", 0 if live else 20, False, live)
    arguments = popen.call_args.args[0]
    output = arguments[arguments.index("--output") + 1]
    assert arguments[arguments.index("--width") + 1] == "1280"
    assert arguments[arguments.index("--height") + 1] == "720"
    if live:
        assert output == "/state/live-observations.ndjson"
        assert arguments[arguments.index("--output-max-bytes") + 1] == str(256 * 1024**2)
        assert arguments[arguments.index("--output-retained-files") + 1] == "2"
        assert arguments[arguments.index("--preview-fps") + 1] == "15"
        # Sessions reuse the same new family, rather than leave another 768 MiB.
        module.native("spark", 0, False, True)
        repeated = popen.call_args.args[0]
        assert repeated[repeated.index("--output") + 1] == output
        (directory / "state/runtime-tuning.json").write_text('{"muxTimeoutUs":10000,"previewFps":30}')
        module.native("spark", 0, False, True)
        tuned = popen.call_args.args[0]
        assert tuned[tuned.index("--preview-fps") + 1] == "30"
        assert tuned[tuned.index("--mux-timeout-us") + 1] == "10000"
    else:
        assert output.startswith("/state/observations-") and output.endswith(".ndjson")
        assert "--output-max-bytes" not in arguments
        assert "--output-retained-files" not in arguments
    assert historical.read_bytes() == b"existing qualification bytes\n"


def test_trafficcam_adapter_mounts_precede_compose_service(root, monkeypatch):
    directory = module.state_dir('spark')
    (directory/'media/fixture.mp4').write_bytes(b'fixture')
    monkeypatch.setattr(module, 'require_actual_device', Mock())
    monkeypatch.setattr(module, 'require_native_engine', Mock())
    monkeypatch.setattr(module, 'ensure_headroom', Mock())
    monkeypatch.setattr(module, 'request', lambda path: {'id':'fixture','mode':'recorded-inference',
        'sources':[{'id':'camera','width':960,'height':540,'inputUri':'file:///media/fixture.mp4'}]})
    monkeypatch.setattr(module, 'city_model_module', lambda: SimpleNamespace(config_for_launch=lambda *args: {
        'nativeArgs':[], 'adapterMounts':[{'hostPath':'/adapter/city-worker','containerPath':'/opt/city/city-worker'}]}))
    monkeypatch.setattr(module, 'city_demo_module', lambda: SimpleNamespace(load=lambda *args:None, native_args=lambda *args,**kwargs:[]))
    popen=Mock(return_value=SimpleNamespace(poll=lambda:0,returncode=0))
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    module.native('spark', 20, False)
    args=popen.call_args.args[0]
    index=args.index('--volume')
    assert args[index+1] == '/adapter/city-worker:/opt/city/city-worker:ro'
    assert index < args.index('city-detector')


@pytest.mark.parametrize("dimensions,expected", [
    ([(1280, 720), (1280, 720)], (1280, 720)),
    ([(960, 540), (960, 540)], (960, 540)),
    ([(1920, 1080), (768, 576)], (1920, 1080)),
    ([(768, 576)], (768, 576)),
])
def test_mux_geometry_preserves_source_and_tracker_calibration_dimensions(dimensions, expected):
    sources = [{"width": width, "height": height, "calibrationRevision": "unchanged"} for width, height in dimensions]
    before = json.loads(json.dumps(sources))
    assert module.mux_dimensions(sources) == expected
    assert sources == before  # No camera/calibration/model mutation to remove mux upscaling.


@pytest.mark.parametrize("sources", [[], [{"width": 1280}], [{"width": True, "height": 720}],
    [{"width": 0, "height": 720}], [{"width": 16385, "height": 720}],
    [{"width": 1280, "height": 720}] * 3])
def test_mux_geometry_rejects_missing_or_invalid_decoded_dimensions(sources):
    with pytest.raises(ValueError, match="geometry|decoded"):
        module.mux_dimensions(sources)


@pytest.mark.parametrize("fps", [1, 5, 15, 30])
def test_explicit_preview_cap_is_bounded_and_independent_of_mux_timeout(root, fps):
    directory = root / ".spark/city/state"
    directory.mkdir(parents=True)
    (directory / "runtime-tuning.json").write_text(json.dumps({"previewFps": fps}))
    assert module.live_runtime_tuning("spark") == {"previewFps": fps}
    assert module.live_mux_timeout("spark") is None


@pytest.mark.parametrize("value", [{}, {"previewFps": True}, {"previewFps": 0}, {"previewFps": 31},
    {"previewFps": 5.5}, {"previewFps": "30"}, {"previewFps": 30, "args": ["unsafe"]}])
def test_runtime_tuning_never_accepts_unvalidated_display_caps_or_arbitrary_flags(root, value):
    directory = root / ".spark/city/state"
    directory.mkdir(parents=True)
    (directory / "runtime-tuning.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        module.live_runtime_tuning("spark")


@pytest.mark.parametrize("value", [None, True, 0, [], {}, "auto", "Hardware", "hardware "])
def test_decoder_tuning_rejects_nonexplicit_choices(root, value):
    directory = root / ".spark/city/state"
    directory.mkdir(parents=True)
    (directory / "runtime-tuning.json").write_text(json.dumps({"decoder": value}))
    with pytest.raises(ValueError, match="decoder"):
        module.live_runtime_tuning("spark")


@pytest.mark.parametrize("device,live,decoder,cpu", [
    ("spark", True, None, True), ("spark", True, "cpu", True), ("spark", True, "hardware", False),
    ("thor", True, None, False), ("thor", True, "cpu", True), ("thor", True, "hardware", False),
    ("spark", False, "hardware", True), ("thor", False, "cpu", False),
])
def test_decoder_choice_is_live_only_and_preserves_platform_defaults(root, monkeypatch, device, live, decoder, cpu):
    directory = module.state_dir(device)
    (directory / "media/fixture.mp4").write_bytes(b"CPU launch fixture")
    if decoder is not None:
        (directory / "state/runtime-tuning.json").write_text(json.dumps({"decoder": decoder}))
    monkeypatch.setattr(module, "require_actual_device", Mock())
    monkeypatch.setattr(module, "require_native_engine", Mock())
    monkeypatch.setattr(module, "ensure_headroom", Mock())
    monkeypatch.setattr(module, "request", lambda path: {"id": "test-city", "mode": "live" if live else "recorded-inference",
        "sources": [{"id": "camera", "width": 960, "height": 540,
            "inputUri": "rtsp://127.0.0.1/fixture" if live else "file:///media/fixture.mp4"}]})
    monkeypatch.setattr(module, "city_model_module", lambda: SimpleNamespace(config_for_launch=lambda *args: {"nativeArgs": []}))
    popen = Mock(return_value=SimpleNamespace(poll=lambda: 0, returncode=0))
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    module.native(device, 0 if live else 20, False, live)
    args = popen.call_args.args[0]
    assert ("--cpu-decode" in args) is cpu
    assert args[args.index("--width") + 1] == "960"
    assert args[args.index("--height") + 1] == "540"


@pytest.mark.parametrize("value", [0, 1, 2, True, None, "1"])
def test_tensor_input_interval_is_rejected_not_silently_claimed(root, value):
    directory = root / ".spark/city/state"
    directory.mkdir(parents=True)
    (directory / "runtime-tuning.json").write_text(json.dumps({"inferenceInterval": value}))
    with pytest.raises(ValueError, match="unsupported with preprocessed tensor input"):
        module.live_runtime_tuning("spark")


def test_city_profile_keeps_the_local_evidence_route(root):
    directory = root / '.spark/city'
    directory.mkdir(parents=True)
    path = directory / 'agent-city-overlay.json'
    path.write_text(json.dumps({'services': {'vss-agent': {'environment': {'VST_CLIP_FALLBACK_MEDIA_URL': 'http://172.17.0.1:7777/api/vision/evidence-media'}}}}))
    module.profile_overlay('spark', True)
    env = json.loads(path.read_text())['services']['vss-agent']['environment']
    assert env['VSS_CITY_RTVI_CV_URL'] == 'http://127.0.0.1:9190'
    assert env['VST_CLIP_FALLBACK_MEDIA_URL'] == 'http://172.17.0.1:7777/api/vision/evidence-media'


@pytest.mark.parametrize("available,allowed", [(4.99, False), (5, True), (5.1, True)])
def test_admission_honors_five_gib_reserve_without_startup_allowance(root, monkeypatch, available, allowed):
    (root / ".spark").mkdir(exist_ok=True)
    (root / ".spark/settings.json").write_text('{"reserve_gib":5}')
    (root / ".spark/guard-status.json").write_text('{}')
    monkeypatch.setattr(module, "available_gib", lambda: available)
    if allowed:
        module.ensure_headroom("spark")
    else:
        with pytest.raises(RuntimeError, match="saved 5.0 GiB reserve"):
            module.ensure_headroom("spark")


@pytest.mark.parametrize('value', [True, None, 'WebRTC', 'webrtc ', [], {}])
def test_preview_transport_is_an_explicit_validated_choice(root, value):
    directory = module.state_dir('spark')
    (directory / 'state/runtime-tuning.json').write_text(json.dumps({'previewTransport': value}))
    with pytest.raises(ValueError, match='previewTransport'):
        module.live_runtime_tuning('spark')


def test_webrtc_cannot_launch_without_a_pinned_native_profile(root, monkeypatch):
    directory = module.state_dir('spark')
    (directory / 'state/runtime-tuning.json').write_text('{"previewTransport":"webrtc"}')
    monkeypatch.setattr(module, 'city_demo_module', lambda: SimpleNamespace(load=lambda *args: None))
    with pytest.raises(ValueError, match='pinned native camera profile'):
        module.compose_file('spark')


def test_webrtc_starts_only_shared_relay_before_worker_with_matching_native_identity_endpoint(root, monkeypatch):
    directory = module.state_dir('spark')
    (directory / 'state/runtime-tuning.json').write_text('{"previewTransport":"webrtc","previewFps":30}')
    for name in ('require_actual_device', 'require_native_engine', 'ensure_headroom'):
        monkeypatch.setattr(module, name, Mock())
    monkeypatch.setattr(module, 'request', lambda *args: {'id':'city', 'mode':'live', 'sources':[
        {'id':'camera','width':1280,'height':480,'inputUri':'rtsp://127.0.0.1/fixture'}]})
    monkeypatch.setattr(module, 'city_model_module', lambda: SimpleNamespace(config_for_launch=lambda *args: {'nativeArgs':[]}))
    monkeypatch.setattr(module, 'city_demo_module', lambda: SimpleNamespace(load=lambda *args: {}, native_args=lambda *args, **kwargs: []))
    monkeypatch.setattr(module, 'compose_file', lambda *args: directory / 'compose.json')
    order = []
    run = Mock(side_effect=lambda *args: order.append('relay'))
    process = Mock(side_effect=lambda *args, **kwargs: (order.append('worker') or SimpleNamespace(poll=lambda:0,returncode=0)))
    monkeypatch.setattr(module,'run',run); monkeypatch.setattr(module.subprocess,'Popen',process)
    module.native('spark',0,False,True)
    assert order == ['relay','worker']
    assert run.call_args.args[-5:] == ('-d','--no-build','--pull','never','city-video')
    arguments = process.call_args.args[0]
    assert arguments[arguments.index('--preview-url')+1].endswith('/video/frame')
    assert arguments[arguments.index('--preview-transport')+1] == 'webrtc'
    assert arguments[arguments.index('--preview-fps')+1] == '30'
