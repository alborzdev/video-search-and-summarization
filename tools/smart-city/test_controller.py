# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location(
    "city_controller_under_test", Path(__file__).with_name("controller.py")
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Process:
    def poll(self):
        return None


class Runtime:
    ready = True

    def __init__(self):
        self.site = {
            "id": "smart-city",
            "revision": 1,
            "mode": "live",
            "sources": [],
            "map": {"bounds": [-10, -10, 10, 10]},
        }
        self.started = 0
        self.stopped = 0
        self.registered_media = []
        self.records = [
            {
                "sensorId": name,
                "name": name,
                "location": f"/vios/{name}.mp4",
                "type": "sensor_file",
            }
            for name in ("cam-1", "cam-2", "cam-3")
        ]
        self.rules = {"rules": [], "revision": 0}

    def readiness(self):
        return self.ready, "mock readiness"

    def inventory(self):
        return self.records

    def json(self, url, payload=None, method="GET"):
        if url.endswith("/site"):
            if method == "PUT":
                self.site = payload
                source_ids = {source["id"] for source in payload["sources"]}
                self.rules["rules"] = [
                    rule
                    for rule in self.rules["rules"]
                    if rule["sourceId"] in source_ids
                ]
                self.rules["revision"] += 1
            return self.site
        if url.endswith("/rules"):
            if method == "PUT":
                assert payload["expectedRevision"] == self.rules["revision"]
                self.rules = {
                    "rules": payload["rules"],
                    "revision": self.rules["revision"] + 1,
                }
            return self.rules
        if url.endswith("/media-registration"):
            self.registered_media = payload["sources"]
            return {}
        if "/vst/api/v1/sensor/" in url and url.endswith("/streams"):
            source_id = url.split("/sensor/", 1)[1].split("/", 1)[0]
            record = next(
                (item for item in self.records if item["sensorId"] == source_id), {}
            )
            return [{"streamId": source_id, "url": record.get("location", "")}]
        raise AssertionError(f"unexpected service request {url}")

    def probe(self, path):
        return {"width": 768, "height": 576, "durationSeconds": 79.5}

    def start(self, log, *, live=False):
        self.started += 1
        return Process()

    def stop(self, process):
        self.stopped += 1

    def download(self, url, path):
        raise AssertionError("existing registered local media should not be downloaded")


@pytest.fixture
def controller(tmp_path):
    settings = module.Settings(root=tmp_path)
    media = settings.directory / "media"
    media.mkdir(parents=True)
    for name in ("cam-1", "cam-2", "cam-3"):
        (media / f"{name}.mp4").write_bytes(b"controlled fixture")
    return module.CityController(settings, Runtime())


def sensor(source="cam-1", url=None):
    return module.SensorValue(
        camera_id=source,
        camera_name="Test camera",
        camera_url=url or f"file:///media/{source}.mp4",
    )


def test_detection_switch_preserves_cameras_calibration_rules_and_explicit_pause(
    controller,
):
    controller.add(sensor())
    controller.sources["cam-1"]["kind"] = "live"
    controller._save()
    before_site = __import__("copy").deepcopy(controller.runtime.site)
    before_rules = __import__("copy").deepcopy(controller.runtime.rules)
    assert controller.control_detections("stop")["state"] == "paused"
    assert controller.process is None
    assert controller.runtime.site == before_site
    assert controller.runtime.rules == before_rules
    assert "cam-1" in controller.sources
    reloaded = module.CityController(controller.settings, controller.runtime)
    assert reloaded.detection_status()["state"] == "paused"
    started = controller.runtime.started
    reloaded.supervise()
    assert controller.runtime.started == started
    with pytest.raises(ValueError, match="Detections are off"):
        reloaded.recover_analysis()
    assert reloaded.control_detections("start")["state"] == "running"
    assert controller.runtime.started == started + 1
    assert not module.CityController(
        controller.settings, controller.runtime
    ).detections_paused


def test_detection_restart_recovers_failed_live_worker_once_and_start_is_idempotent(
    controller,
):
    controller.add(sensor())
    controller.sources["cam-1"]["kind"] = "live"
    controller.process = SimpleNamespace(poll=lambda: 1, returncode=1)
    assert controller.detection_status()["lastExitCode"] == 1
    before = controller.runtime.started
    controller.supervise()
    assert controller.runtime.started == before
    assert controller.control_detections("start")["state"] == "running"
    assert controller.runtime.started == before + 1
    controller.control_detections("start")
    assert controller.runtime.started == before + 1
    controller.control_detections("restart")
    assert controller.runtime.started == before + 2


def test_detection_start_keeps_memory_admission_and_reports_failure(
    controller, monkeypatch
):
    controller.add(sensor())
    controller.sources["cam-1"]["kind"] = "live"
    controller.control_detections("stop")
    started = controller.runtime.started

    def no_headroom():
        raise module.HTTPException(503, "saved memory reserve")

    monkeypatch.setattr(controller, "_wait_cold_readiness", no_headroom)
    with pytest.raises(module.HTTPException, match="saved memory reserve"):
        controller.control_detections("start")
    assert controller.runtime.started == started
    assert controller.detections_paused


def test_registered_source_reconciliation_does_not_undo_explicit_detection_stop(
    controller,
):
    controller.add(sensor())
    controller.control_detections("stop")
    started = controller.runtime.started
    controller.add(sensor())
    assert controller.runtime.started == started
    assert controller.process is None
    assert controller.detection_status()["state"] == "paused"


def test_detection_api_rejects_broad_actions_and_never_returns_camera_urls(controller):
    controller.add(sensor())
    controller.sources["cam-1"]["kind"] = "live"
    with TestClient(module.create_app(controller)) as client:
        status = client.get("/api/v1/detections").json()
        assert status["schemaVersion"] == "city.detections.v1"
        assert status["sources"] == [{"id": "cam-1", "name": "Test camera"}]
        assert "camera_url" not in str(status) and "inputUri" not in str(status)
        assert (
            client.post(
                "/api/v1/detections", json={"action": "stop", "command": "docker"}
            ).status_code
            == 422
        )
        assert (
            client.post("/api/v1/detections", json={"action": "delete"}).status_code
            == 422
        )
        assert (
            client.post("/api/v1/detections", json={"action": "stop"}).json()["state"]
            == "paused"
        )


def test_host_stop_does_not_claim_success_when_docker_still_reports_running(
    tmp_path, monkeypatch
):
    runtime = module.HostRuntime(module.Settings(root=tmp_path))
    replies = iter(
        [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0, stdout="true\n")]
    )
    monkeypatch.setattr(runtime, "command", lambda _: next(replies))
    with pytest.raises(RuntimeError, match="stop was not confirmed"):
        runtime.stop(None)


def test_actual_agent_shapes_idempotency_and_capacity(controller):
    with TestClient(module.create_app(controller)) as client:
        assert client.get("/api/v1/health/get-dsready-state").status_code == 200
        for source in ("cam-1", "cam-2"):
            body = {
                "key": "sensor",
                "value": sensor(source).model_dump(),
                "headers": {"source": "vst"},
            }
            assert client.post("/api/v1/stream/add", json=body).status_code == 200
        listing = client.get("/api/v1/stream/get-stream-info").json()
        assert {
            source["camera_id"] for source in listing["stream-info"]["stream-info"]
        } == {"cam-1", "cam-2"}
        assert listing["capacity"]["availableSources"] == 0
        assert (
            client.post(
                "/api/v1/stream/add", json={"value": sensor("cam-3").model_dump()}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/stream/remove", json={"value": sensor("absent").model_dump()}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/stream/remove", json={"value": sensor("cam-1").model_dump()}
            ).status_code
            == 200
        )
        assert set(controller.sources) == {"cam-2"}


def test_readiness_never_claimed_without_engine_image_guard(controller):
    controller.runtime.ready = False
    with TestClient(module.create_app(controller)) as client:
        assert client.get("/api/v1/health/get-dsready-state").status_code == 503
        assert (
            client.post(
                "/api/v1/stream/add", json={"value": sensor().model_dump()}
            ).status_code
            == 503
        )
    assert controller.runtime.started == 0


def test_host_readiness_validates_selected_model_instead_of_fixed_small(
    tmp_path, monkeypatch
):
    seen = []
    runtime = module.HostRuntime(module.Settings(root=tmp_path))
    runtime.command = lambda args: SimpleNamespace(returncode=0)
    runtime.json = lambda url: {}
    model = SimpleNamespace(
        selected_city_model=lambda device: seen.append(("selected", device)),
        require_actual_device=lambda device: None,
        ensure_headroom=lambda device: seen.append(("guard", device)),
    )
    monkeypatch.setattr(
        module.importlib.util,
        "spec_from_file_location",
        lambda *args: SimpleNamespace(
            loader=SimpleNamespace(exec_module=lambda target: None)
        ),
    )
    monkeypatch.setattr(module.importlib.util, "module_from_spec", lambda spec: model)
    assert runtime.readiness()[0] is True
    assert seen == [("selected", "spark"), ("guard", "spark")]

    def invalid(device):
        raise ValueError("Selected engine hash does not match")

    model.selected_city_model = invalid
    assert runtime.readiness() == (False, "Detections unavailable: Selected engine hash does not match")


def test_readiness_retains_module_but_rechecks_model_guard_and_gateway(
    tmp_path, monkeypatch
):
    module._manage_module.cache_clear()
    loaded, checks = [], []
    runtime = module.HostRuntime(module.Settings(root=tmp_path))
    runtime.command = lambda args: SimpleNamespace(returncode=0)
    runtime.json = lambda url: checks.append("gateway")
    guard = SimpleNamespace(
        selected_city_model=lambda device: checks.append("model"),
        require_actual_device=lambda device: checks.append("device"),
        ensure_headroom=lambda device: checks.append(("reserve", device)),
    )
    monkeypatch.setattr(
        module.importlib.util,
        "spec_from_file_location",
        lambda *args: SimpleNamespace(
            loader=SimpleNamespace(exec_module=lambda target: loaded.append(target))
        ),
    )
    monkeypatch.setattr(module.importlib.util, "module_from_spec", lambda spec: guard)
    try:
        assert runtime.readiness()[0] is True
        assert runtime.readiness()[0] is True
        assert loaded == [guard]
        assert checks == [
            "model", "device", ("reserve", "spark"), "gateway",
            "model", "device", ("reserve", "spark"), "gateway",
        ]

        def changed_model(device):
            raise ValueError("Changed artifact no longer qualifies")

        guard.selected_city_model = changed_model
        assert runtime.readiness()[0] is False
        assert loaded == [guard]
    finally:
        module._manage_module.cache_clear()


@pytest.mark.parametrize(
    "uri",
    [
        "file:///etc/passwd",
        "file:///media/other.mp4",
        "http://example.com/vst/clip.mp4",
        "http://127.0.0.1:9999/vst/clip.mp4",
        "http://127.0.0.1:30888/admin",
        "http://user:secret@127.0.0.1:30888/vst/clip.mp4",
        "data:video/mp4;base64,AAAA",
        "$(touch /tmp/not-executed)",
    ],
)
def test_unregistered_files_arbitrary_http_and_shell_text_rejected(controller, uri):
    with pytest.raises(ValueError):
        controller.add(sensor(url=uri))
    assert controller.runtime.started == 0


def test_unregistered_source_rejected_even_existing_filename(controller):
    with pytest.raises(ValueError, match="not registered"):
        controller.add(sensor("not-in-vios", "file:///media/cam-1.mp4"))


def test_http_storage_source_uses_actual_probe_and_vss_ids(controller):
    controller.add(sensor(url="http://127.0.0.1:30888/vst/storage/clip.mp4"))
    source = controller.runtime.site["sources"][0]
    assert source["id"] == source["vssSensorId"] == "cam-1"
    assert source["width"] == 768 and source["height"] == 576
    assert source["inputUri"] == "file:///media/cam-1.mp4"
    assert controller.runtime.registered_media == [
        {"sourceId": "cam-1", "filename": "cam-1.mp4"}
    ]


@pytest.mark.parametrize("alias", ["host.docker.internal", "vst-ingress"])
def test_actual_agent_local_storage_aliases_are_normalized(controller, alias):
    uri = f"http://{alias}:30888/vst/storage/temp_files/clip.mp4"
    runtime = module.HostRuntime(controller.settings)
    assert (
        runtime.vss_storage_uri(uri)
        == "http://127.0.0.1:30888/vst/storage/temp_files/clip.mp4"
    )
    controller.add(sensor(url=uri))
    assert controller.runtime.started == 1


def test_remote_vss_origin_does_not_admit_local_compose_aliases(tmp_path):
    runtime = module.HostRuntime(
        module.Settings(root=tmp_path, vss_origin="https://vios.example:30888")
    )
    with pytest.raises(ValueError):
        runtime.vss_storage_uri(
            "http://host.docker.internal:30888/vst/storage/clip.mp4"
        )


def test_existing_source_add_is_not_a_capacity_increment_and_persists(controller):
    controller.add(sensor())
    controller.add(sensor())
    assert len(controller.sources) == 1
    assert controller.runtime.started == 1
    restored = module.CityController(controller.settings, Runtime())
    assert restored.sources["cam-1"]["id"] == "cam-1"
    assert (
        restored.process is None
    )  # process/worker health is never invented from state files


def test_registered_rtsp_requires_exact_url_and_host_allowlist(controller, monkeypatch):
    controller.runtime.records.append(
        {"sensorId": "live", "type": "sensor_rtsp", "location": "rtsp://sim.local/city"}
    )
    with pytest.raises(ValueError, match="does not match"):
        controller.add(sensor("live", "rtsp://sim.local/other"))
    with pytest.raises(ValueError, match="not enabled"):
        controller.add(sensor("live", "rtsp://sim.local/city"))
    monkeypatch.setenv("CITY_RTSP_ALLOWED_HOSTS", "sim.local")
    controller.add(sensor("live", "rtsp://sim.local/city"))
    assert controller.runtime.site["mode"] == "live"


def test_command_boundary_uses_fixed_subprocess_arguments(tmp_path, monkeypatch):
    runtime = module.HostRuntime(module.Settings(root=tmp_path))
    seen = {}

    def popen(arguments, **kwargs):
        seen.update(arguments=arguments, kwargs=kwargs)
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    runtime.start(tmp_path / "worker.log")
    assert seen["arguments"][1:] == [
        str(tmp_path / "tools/smart-city/manage.py"),
        "--device",
        "spark",
        "analyze",
        "--frames",
        "18000",
    ]
    assert "shell" not in seen["kwargs"] and seen["kwargs"]["start_new_session"] is True


def test_live_supervision_renews_only_successful_guarded_segments(controller):
    class Ended:
        returncode = 0

        def poll(self):
            return self.returncode

    controller.sources = {"live": {"kind": "live"}}
    controller.process = Ended()
    controller.supervise()
    assert controller.runtime.started == 1
    controller.process = Ended()
    controller.process.returncode = 1
    controller.supervise()
    assert controller.runtime.started == 1
    controller.process = Ended()
    controller.runtime.ready = False
    controller.supervise()
    assert controller.runtime.started == 1


def test_controller_preserves_existing_real_site_map_and_calibration(controller):
    controller.runtime.site = {
        "id": "calibrated-expo",
        "revision": 3,
        "mode": "recorded-inference",
        "sources": [
            {
                "id": "cam-1",
                "calibrationRevision": "cal-5",
                "imageToGroundHomography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            }
        ],
        "map": {"bounds": [0, 0, 100, 100], "roads": [{"id": "original-street"}]},
    }
    controller.add(sensor())
    assert controller.runtime.site["id"] == "calibrated-expo"
    assert controller.runtime.site["map"]["roads"][0]["id"] == "original-street"
    assert controller.runtime.site["sources"][0]["calibrationRevision"] == "cal-5"


def test_incremental_profile_activation_keeps_second_camera_calibration(controller):
    source = lambda source_id: {
        "id": source_id,
        "width": 768,
        "height": 576,
        "calibrationRevision": "known-2",
        "imageToGroundHomography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "classImageToGroundHomographies": {"person": [[1, 0, 1], [0, 1, 2], [0, 0, 1]]},
        "projectionMatrix3x4": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
        "cameraPositionWorldM": [10, 10, 8],
    }
    controller.runtime.site.update(
        id="expo", mode="recorded-inference", sources=[source("cam-1"), source("cam-2")]
    )
    controller.add(sensor("cam-1"))
    controller.add(sensor("cam-2"))
    second = next(
        item for item in controller.runtime.site["sources"] if item["id"] == "cam-2"
    )
    assert second["calibrationRevision"] == "known-2"
    assert second["imageToGroundHomography"] is not None
    assert second["classImageToGroundHomographies"]["person"][0][2] == 1
    assert second["projectionMatrix3x4"][2] == [0, 0, 1, 0]
    assert second["cameraPositionWorldM"] == [10, 10, 8]


def test_manual_calibration_revocation_survives_remove_and_readd(controller):
    controller.runtime.site["sources"] = [
        {
            "id": "cam-1",
            "width": 768,
            "height": 576,
            "imageToGroundHomography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "validGroundPolygon": [[0, 0], [1, 0], [1, 1]],
            "calibrationRevision": "revoked-old-calibration",
        }
    ]
    controller.add(sensor("cam-1"))
    assert controller.calibrations["cam-1"]["imageToGroundHomography"] is not None
    current = controller.runtime.site["sources"][0]
    current.update(
        imageToGroundHomography=None, validGroundPolygon=None, calibrationRevision=None
    )
    controller.runtime.rules = {
        "rules": [
            {
                "id": "ground-queue",
                "sourceId": "cam-1",
                "kind": "queue",
                "enabled": True,
                "calibrationRevision": "revoked-old-calibration",
                "geometry": {"space": "site-metres"},
            }
        ],
        "revision": 10,
    }
    controller.remove("cam-1")
    controller.add(sensor("cam-1"))
    source = controller.runtime.site["sources"][0]
    assert source["imageToGroundHomography"] is None
    assert source["validGroundPolygon"] is None
    assert source["calibrationRevision"] is None
    assert controller.calibrations["cam-1"]["imageToGroundHomography"] is None
    assert controller.runtime.rules["rules"][0]["enabled"] is False


def test_incremental_profile_activation_retains_rules_and_empty_site_map(controller):
    controller.runtime.site.update(
        id="expo", sources=[{"id": "cam-1"}, {"id": "cam-2"}]
    )
    controller.runtime.rules = {
        "rules": [
            {
                "id": "rule-2",
                "sourceId": "cam-2",
                "kind": "dwell",
                "enabled": True,
                "geometry": {"space": "image-normalized"},
            }
        ],
        "revision": 3,
    }
    controller.add(sensor("cam-1"))
    assert controller.runtime.rules["rules"] == []
    controller.add(sensor("cam-2"))
    assert controller.runtime.rules["rules"][0]["id"] == "rule-2"
    controller.remove("cam-1")
    controller.remove("cam-2")
    assert controller.runtime.site["id"] == "expo"
    assert controller.runtime.site["sources"] == []
    controller.add(sensor("cam-2"))
    assert controller.runtime.rules["rules"][0]["id"] == "rule-2"
    controller.runtime.rules["rules"] = []  # deliberate deletion in UI
    controller.remove("cam-2")
    controller.add(sensor("cam-2"))
    assert controller.runtime.rules["rules"] == []


def test_loaded_worker_reconfiguration_rechecks_saved_reserve(
    controller,
):
    budgets = []

    def readiness():
        budgets.append("saved reserve")
        return True, "guarded"

    controller.runtime.readiness = readiness
    controller.add(sensor("cam-1"))
    controller.add(sensor("cam-2"))
    assert budgets == ["saved reserve"] * 4
    assert controller.runtime.stopped == 2


def test_failed_post_stop_headroom_does_not_commit_second_source(
    controller, monkeypatch
):
    controller.add(sensor("cam-1"))
    old_site = controller.runtime.site
    readiness = iter([True, False, False])
    controller.runtime.readiness = lambda: (
        next(readiness), "saved reserve unavailable",
    )
    times = iter([0, 11])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    with pytest.raises(module.HTTPException) as failure:
        controller.add(sensor("cam-2"))
    assert failure.value.status_code == 503
    assert set(controller.sources) == {"cam-1"}
    assert controller.runtime.site is old_site
    assert controller.runtime.started == 1
    assert controller.process is None


@pytest.mark.parametrize("stage", ["read-site", "write-rules", "save-ownership"])
def test_failed_remove_restores_retryable_ownership_and_canonical_sources(
    controller, monkeypatch, stage
):
    controller.add(sensor("cam-1"))
    controller.add(sensor("cam-2"))
    saved_rule = {
        "id": "cam-1-dwell",
        "sourceId": "cam-1",
        "kind": "dwell",
        "enabled": True,
        "durationSeconds": 3,
        "geometry": {"space": "image-normalized"},
    }
    controller.runtime.rules["rules"] = [saved_rule]
    original_json, original_save = controller.runtime.json, controller._save
    failures = []

    def gateway(url, payload=None, method="GET"):
        fail = (stage == "read-site" and url.endswith("/site") and method == "GET") or (
            stage == "write-rules" and url.endswith("/rules") and method == "PUT"
        )
        if fail and not failures:
            failures.append(stage)
            raise OSError("Private mocked gateway outage")
        return original_json(url, payload, method)

    def save():
        if stage == "save-ownership" and not failures:
            failures.append(stage)
            raise OSError("Private mocked storage outage")
        original_save()

    monkeypatch.setattr(controller.runtime, "json", gateway)
    monkeypatch.setattr(controller, "_save", save)
    starts = controller.runtime.started
    with pytest.raises(OSError):
        controller.remove("cam-1")
    assert set(controller.sources) == {"cam-1", "cam-2"}
    assert set(module.json.loads(controller.state_file.read_text())) == {"cam-1", "cam-2"}
    assert {source["id"] for source in controller.runtime.site["sources"]} == {
        "cam-1", "cam-2"
    }
    assert controller.runtime.rules["rules"] == [saved_rule]
    assert controller.process is None
    assert controller.runtime.started == starts

    assert controller.remove("cam-1")["message"] == "Removed"
    assert set(controller.sources) == {"cam-2"}
    assert set(module.json.loads(controller.state_file.read_text())) == {"cam-2"}
    assert controller.remove("cam-1")["message"] == "Already absent"


def test_remove_gateway_outage_keeps_ownership_when_rollback_also_fails(
    controller, monkeypatch
):
    controller.add(sensor("cam-1"))
    original_json = controller.runtime.json

    def unavailable(*args, **kwargs):
        raise OSError("Private mocked sustained gateway outage")

    monkeypatch.setattr(controller.runtime, "json", unavailable)
    with pytest.raises(OSError):
        controller.remove("cam-1")
    assert set(controller.sources) == {"cam-1"}
    assert set(module.json.loads(controller.state_file.read_text())) == {"cam-1"}
    assert controller.process is None
    monkeypatch.setattr(controller.runtime, "json", original_json)
    assert controller.remove("cam-1")["message"] == "Removed"


def test_restart_uses_exact_aggregate_stream_registration_when_per_sensor_route_is_missing(controller):
    from urllib.error import HTTPError
    controller.runtime.records = [{'sensorId':'live','type':'sensor_rtsp','location':'Registered camera'}]
    target = 'rtsp://127.0.0.1:30557/live/live'
    calls = []
    def inventory(url, *args):
        calls.append(url)
        if url.endswith('/sensor/live/streams'):
            raise HTTPError(url,404,'CameraNotFoundError',{},None)
        assert url.endswith('/sensor/streams')
        return [{'another-camera':[{'streamId':'another-camera','url':'rtsp://127.0.0.1/other'}]},
                {'live':[{'streamId':'live','url':target}]}]
    controller.runtime.json = inventory
    assert controller._resolve(sensor('live',target))['inputUri'] == target
    assert len(calls) == 2
    with pytest.raises(ValueError,match='does not match'):
        controller._resolve(sensor('live','rtsp://127.0.0.1/other'))


def test_stream_registration_does_not_fallback_on_authorization_or_network_errors(controller):
    from urllib.error import HTTPError
    controller.runtime.records = [{'sensorId':'live','type':'sensor_rtsp','location':'Registered camera'}]
    calls = []
    def unavailable(url, *args):
        calls.append(url)
        raise HTTPError(url,403,'Forbidden',{},None)
    controller.runtime.json = unavailable
    with pytest.raises(HTTPError):
        controller._resolve(sensor('live','rtsp://127.0.0.1/live'))
    assert len(calls) == 1
