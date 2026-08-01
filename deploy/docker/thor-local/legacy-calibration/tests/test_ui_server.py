# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from email.message import Message
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

LANE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LANE))
import backend  # noqa: E402
import ui_server as server  # noqa: E402

PROJECT_FIELDS = {
    "id",
    "sensor_set",
    "intersection_set",
    "city_set",
    "placeTypes_set",
    "corridor_set",
    "created",
    "modified",
    "name",
    "calibrationType",
    "mapAPIKey",
    "mapFile",
    "webApiUrl",
    "scaleFactor",
    "calibrationJsonTemp",
    "imageMetaDataJsonTemp",
    "imageFiles",
    "calibrationJson",
    "sensorMetadataCsv",
    "imageMetaDataJson",
    "roadNetworkJson",
    "mmsURL",
    "placeTypeHierarchy",
    "floorPlanImageUrl",
    "floorPlanImHeight",
    "floorPlanImWidth",
    "rtspURL",
    "coordinates",
    "mapCoordinates",
    "mapZoom",
    "mapCenter",
    "originLat",
    "originLng",
    "cityPlace",
    "roomPlace",
}


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def payload(response: server.Response) -> object:
    return json.loads(response.body)


def app(tmp_path: Path) -> server.Application:
    return server.Application(server.LocalUIStore(tmp_path.resolve()))


def create(application: server.Application, name: str = "Operator project") -> dict:
    response = application.dispatch(
        "POST",
        "/api/projects/",
        encoded({"name": name, "calibrationType": "cartesian"}),
        content_type="application/json",
    )
    assert response.status == 201
    return payload(response)  # type: ignore[return-value]


def stage_and_import(
    application: server.Application,
    tmp_path: Path,
    project_id: int = 1,
    sensor_id: str = "sensor-01",
) -> dict:
    store = application.store
    assert store.stage_sensors(
        project_id,
        {
            "sensors": [
                {
                    "id": sensor_id,
                    "sensorId": sensor_id,
                    "sensorName": "Local camera",
                    "rtspURL": "rtsp://127.0.0.1/operator-camera",
                    "width": 640,
                    "height": 480,
                }
            ]
        },
    ) == {"project_id": project_id, "staged": 1}
    response = application.dispatch("GET", f"/api/importSensors/{project_id}/")
    assert response.status == 200
    assert response.body == b"Imported 1 locally staged sensor(s)\n"
    project = payload(application.dispatch("GET", f"/api/projects/{project_id}/"))
    return project["sensor_set"][0]  # type: ignore[index,return-value]


def multipart(image: bytes, *, boundary: str = "thor-boundary") -> tuple[str, bytes]:
    fields = {
        "sensorPolygon": "[]",
        "homography": "[]",
        "imHomography": "[]",
        "edgeLengths": "[]",
        "isCalibrated": "false",
        "isValidated": "false",
    }
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="imageUrl"; filename="camera.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
        + image
        + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def tiny_png() -> bytes:
    # The compatibility store does not decode operator images. It requires
    # PNG identity plus IHDR and confines the exact bytes by SHA-256.
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20


def test_default_plan_is_inert_and_uses_non_conflicting_private_port(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert server.main([]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["mode"] == "inert_plan_only"
    assert value["started"] is False
    assert value["bind"] == {"host": "127.0.0.1", "port": 8013, "loopback_only": True}
    assert value["provider_egress"] == "forbidden"
    assert value["runtime_evidence"] == []
    assert "same_origin_proxy_and_ui_route" in value["pending"]


def test_project_crud_is_bare_array_and_exact_ui_shape(tmp_path: Path) -> None:
    application = app(tmp_path)
    project = create(application)
    assert set(project) == PROJECT_FIELDS
    assert project["id"] == 1
    assert project["sensor_set"] == []
    assert project["mapAPIKey"] == ""
    response = application.dispatch("GET", "/api/projects/")
    assert response.status == 200
    assert payload(response) == [project]
    patched = application.dispatch(
        "PATCH",
        "/api/projects/1/",
        encoded({"originLat": 43.65, "originLng": -79.38, "cityPlace": "Toronto"}),
    )
    assert patched.status == 200
    assert payload(patched)["cityPlace"] == "Toronto"  # type: ignore[index]
    assert application.dispatch("DELETE", "/api/projects/1/").status == 200
    assert payload(application.dispatch("GET", "/api/projects/")) == []


@pytest.mark.parametrize("calibration_type", sorted(server.CALIBRATION_TYPES))
def test_project_create_accepts_all_checked_in_client_types(
    tmp_path: Path, calibration_type: str
) -> None:
    response = app(tmp_path).dispatch(
        "POST",
        "/api/projects/",
        encoded({"name": calibration_type, "calibrationType": calibration_type}),
    )
    assert response.status == 201
    assert payload(response)["calibrationType"] == calibration_type  # type: ignore[index]


def test_project_contract_rejects_provider_key_and_unknown_or_nonfinite_data(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    assert (
        application.dispatch(
            "POST",
            "/api/projects/",
            encoded(
                {"name": "x", "calibrationType": "cartesian", "provider": "google"}
            ),
        ).status
        == 400
    )
    create(application)
    assert (
        application.dispatch(
            "PATCH", "/api/projects/1/", encoded({"mapAPIKey": "secret"})
        ).status
        == 400
    )
    assert (
        application.dispatch("PATCH", "/api/projects/1/", b'{"originLat":NaN}').status
        == 400
    )
    assert (
        application.dispatch(
            "POST", "/api/projects/", b'{"name":"a","name":"b"}'
        ).status
        == 400
    )


def test_local_staged_import_populates_full_sensor_and_never_uses_mms_url(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application)
    application.dispatch(
        "PATCH", "/api/projects/1/", encoded({"mmsURL": "https://example.invalid"})
    )
    sensor = stage_and_import(application, tmp_path)
    assert set(sensor) == server.SENSOR_FIELDS
    assert sensor["project"] == 1
    assert sensor["sensorId"] == "sensor-01"
    assert sensor["imageUrl"] is None
    source = (LANE / "ui_server.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "urllib.request",
        "http.client",
        "subprocess",
        "socket.create_connection",
    ):
        assert forbidden not in source


def test_partial_and_full_echo_sensor_patch_are_client_compatible(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application)
    stage_and_import(application, tmp_path)
    response = application.dispatch(
        "PATCH",
        "/api/sensors/sensor-01/",
        encoded({"width": 1920, "height": 1080, "isValidated": True}),
    )
    assert response.status == 200
    updated = payload(response)
    assert updated["width"] == 1920 and updated["isValidated"] is True  # type: ignore[index]
    # SensorEditDialog spreads the complete GET response back into its PATCH.
    echoed = {**updated, "sensorName": "Edited locally"}  # type: ignore[arg-type]
    response = application.dispatch("PATCH", "/api/sensors/sensor-01/", encoded(echoed))
    assert response.status == 200
    assert payload(response)["sensorName"] == "Edited locally"  # type: ignore[index]
    assert payload(application.dispatch("GET", "/api/sensors/sensor-01/"))["sensorName"] == "Edited locally"  # type: ignore[index]


def test_sensor_server_owned_fields_and_identity_collisions_fail_closed(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application, "one")
    stage_and_import(application, tmp_path, sensor_id="one")
    create(application, "two")
    stage_and_import(application, tmp_path, project_id=2, sensor_id="two")
    assert (
        application.dispatch(
            "PATCH", "/api/sensors/one/", encoded({"id": "changed"})
        ).status
        == 409
    )
    assert (
        application.dispatch(
            "PATCH", "/api/sensors/one/", encoded({"sensorId": "two"})
        ).status
        == 409
    )
    with pytest.raises(server.UIError, match="conflicts"):
        application.store.stage_sensors(2, {"sensors": [{"sensorId": "one"}]})


def test_homography_route_persists_json_string_for_followup_sensor_get(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application)
    stage_and_import(application, tmp_path)
    image_points = [
        {"lat": 0, "lng": 0},
        {"lat": 0, "lng": 100},
        {"lat": 100, "lng": 100},
        {"lat": 100, "lng": 0},
    ]
    world_points = [
        {"lat": -5, "lng": 10},
        {"lat": -5, "lng": 110},
        {"lat": 95, "lng": 110},
        {"lat": 95, "lng": 10},
    ]
    patch = {
        "sensorPolygon": json.dumps(
            [{"id": "p", "class": "cartCalib", "points": image_points}]
        ),
        "edgeLengths": json.dumps(world_points),
    }
    assert (
        application.dispatch("PATCH", "/api/sensors/sensor-01/", encoded(patch)).status
        == 200
    )
    calculated = application.dispatch("GET", "/api/approxHomography/sensor-01/")
    assert calculated.status == 200
    matrix = payload(calculated)["homography"]  # type: ignore[index]
    assert matrix == [[1.0, 0.0, 10.0], [0.0, 1.0, -5.0], [0.0, 0.0, 1.0]]
    sensor = payload(application.dispatch("GET", "/api/sensors/sensor-01/"))
    assert json.loads(sensor["homography"]) == matrix  # type: ignore[index]


def test_homography_rejects_incomplete_and_degenerate_incremental_state(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application)
    stage_and_import(application, tmp_path)
    assert application.dispatch("GET", "/api/homography/sensor-01/").status == 422
    line = [{"lat": 0, "lng": value} for value in (0, 1, 2, 3)]
    patch = {
        "sensorPolygon": json.dumps([{"class": "cartCalib", "points": line}]),
        "edgeLengths": json.dumps([{"lat": 0, "lng": value} for value in (0, 1, 2, 3)]),
    }
    application.dispatch("PATCH", "/api/sensors/sensor-01/", encoded(patch))
    assert application.dispatch("GET", "/api/homography/sensor-01/").status == 422


def test_bounded_multipart_upload_and_confined_static_media_round_trip(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application)
    stage_and_import(application, tmp_path)
    image = tiny_png()
    content_type, body = multipart(image)
    uploaded = application.dispatch(
        "PATCH", "/api/sensors/sensor-01/", body, content_type=content_type
    )
    assert uploaded.status == 200
    url = payload(uploaded)["imageUrl"]  # type: ignore[index]
    assert url.startswith("media/projects/1/sensors/sensor-01/")
    response = application.dispatch("GET", "/" + url)
    assert response.status == 200
    assert response.body == image
    assert response.content_type == "image/png"
    assert response.headers["Content-Length"] == str(len(image))
    assert (
        application.dispatch(
            "GET", "/media/projects/1/sensors/sensor-01/" + "0" * 64 + ".png"
        ).status
        == 404
    )


@pytest.mark.parametrize(
    "mutator,expected",
    [
        (lambda _content, body: ("multipart/form-data", body), 415),
        (lambda content, body: (content, body.replace(b"\x89PNG", b"BADPNG")), 415),
        (
            lambda content, body: (
                content,
                body.replace(b'name="edgeLengths"', b'name="unknown"'),
            ),
            400,
        ),
        (lambda content, body: (content, body.replace(b"false", b"maybe", 1)), 400),
    ],
)
def test_multipart_contract_rejects_malformed_inputs(
    tmp_path: Path, mutator, expected: int
) -> None:
    application = app(tmp_path)
    create(application)
    stage_and_import(application, tmp_path)
    content_type, body = mutator(*multipart(tiny_png()))
    assert (
        application.dispatch(
            "PATCH", "/api/sensors/sensor-01/", body, content_type=content_type
        ).status
        == expected
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/invertImage/sensor-01/",
        "/api/getWarpedFiles/1/",
        "/api/getImageFiles/1/",
        "/api/uploadWebApi/1/",
    ],
)
def test_unsafe_or_unimplemented_routes_remain_explicit_501(
    tmp_path: Path, path: str
) -> None:
    response = app(tmp_path).dispatch("GET", path)
    assert response.status == 501
    assert "pending" in payload(response)["message"]  # type: ignore[index]


def test_delete_refuses_unmanaged_files_but_removes_owned_media_and_stage(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    create(application)
    stage_and_import(application, tmp_path)
    content_type, body = multipart(tiny_png())
    application.dispatch(
        "PATCH", "/api/sensors/sensor-01/", body, content_type=content_type
    )
    project_dir = tmp_path / "ui-projects" / "1"
    unmanaged = project_dir / "operator-note.txt"
    unmanaged.write_text("preserve")
    assert application.dispatch("DELETE", "/api/projects/1/").status == 409
    assert unmanaged.is_file()
    unmanaged.unlink()
    assert application.dispatch("DELETE", "/api/projects/1/").status == 200
    assert not project_dir.exists()


def test_symlink_roots_and_media_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(server.UIError, match="symlinks"):
        server.LocalUIStore(link)
    application = app(target)
    create(application)
    stage_and_import(application, target)
    media = target / "ui-projects" / "1" / "media"
    media.symlink_to(tmp_path / "elsewhere")
    content_type, body = multipart(tiny_png())
    assert (
        application.dispatch(
            "PATCH", "/api/sensors/sensor-01/", body, content_type=content_type
        ).status
        == 500
    )


def test_stage_sensors_cli_is_local_bounded_and_serve_requires_exact_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    application = app(tmp_path)
    create(application)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"sensors":[{"sensorId":"cli-sensor"}]}')
    assert (
        server.main(
            [
                "stage-sensors",
                "--data-root",
                str(tmp_path),
                "--project-id",
                "1",
                "--input",
                str(manifest),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"project_id": 1, "staged": 1}
    called = []
    monkeypatch.setattr(
        server, "serve", lambda root, origins: called.append((root, origins))
    )
    assert server.main(["serve", "--data-root", str(tmp_path)]) == 1
    assert called == []
    assert (
        server.main(
            [
                "serve",
                "--data-root",
                str(tmp_path),
                "--acknowledgement",
                server.ACKNOWLEDGEMENT,
                "--allowed-origin",
                "http://127.0.0.1:7777",
            ]
        )
        == 0
    )
    assert called == [(tmp_path, frozenset({"http://127.0.0.1:7777"}))]


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:7777",
        "http://192.0.2.1:7777",
        "http://127.0.0.1",
        "http://127.0.0.1:7777/path",
        "ftp://127.0.0.1:7777",
    ],
)
def test_direct_cors_allowlist_accepts_only_explicit_numeric_loopback_origins(
    origin: str,
) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        server._loopback_origin(origin)
    assert server._loopback_origin("http://127.0.0.1:7777") == "http://127.0.0.1:7777"


def test_handler_cors_preflight_is_exact_and_never_wildcarded() -> None:
    def preflight(method: str, headers: str, origin: str) -> server.Response:
        handler = server.RequestHandler.__new__(server.RequestHandler)
        request_headers = Message()
        request_headers["Origin"] = origin
        request_headers["Access-Control-Request-Method"] = method
        request_headers["Access-Control-Request-Headers"] = headers
        handler.headers = request_headers
        handler.server = SimpleNamespace(
            allowed_origins=frozenset({"http://127.0.0.1:7777"})
        )
        responses = []
        handler._respond = responses.append
        server.RequestHandler.do_OPTIONS(handler)
        assert len(responses) == 1
        return responses[0]

    accepted = preflight("PATCH", "Content-Type, streamId", "http://127.0.0.1:7777")
    assert accepted.status == 204
    assert accepted.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:7777"
    assert "*" not in accepted.headers.values()
    assert preflight("PUT", "Content-Type", "http://127.0.0.1:7777").status == 403
    assert preflight("PATCH", "Authorization", "http://127.0.0.1:7777").status == 403
    assert preflight("PATCH", "Content-Type", "http://127.0.0.1:9999").status == 403


def test_strict_export_compiler_remains_separate_from_incremental_ui_state(
    tmp_path: Path,
) -> None:
    application = app(tmp_path)
    project = create(application)
    assert set(project) != backend.ALLOWED_TOP_COMMON | {"camera"}
    assert not (tmp_path / "ui-projects" / "1" / "calibration.json").exists()
    assert "compile_project" not in server.LocalUIStore.patch.__code__.co_names


def test_contract_claims_only_the_implemented_client_subset() -> None:
    contract = json.loads((LANE / "contract.json").read_text(encoding="utf-8"))
    assert {
        "separate_incremental_VIOS_UI_state_store",
        "bare_project_array_and_numeric_project_CRUD",
        "bounded_partial_sensor_JSON_patch",
        "homography_persisted_as_client_JSON_string",
        "bounded_multipart_PNG_JPEG_upload",
        "digest_verified_confined_static_media",
        "provider_free_locally_staged_sensor_import",
        "private_loopback_port_8013_inert_server",
    }.issubset(contract["implemented"])
    assert {
        "interactive_browser_editor",
        "checked_in_CalibrationWorkflow_route_and_navigation",
        "same_origin_VIOS_proxy_to_private_port_8013",
        "image_inversion_endpoint",
        "warped_and_original_image_ZIP_endpoints",
        "safe_local_only_uploadWebApi_endpoint",
        "incremental_UI_state_to_strict_VSS_export_bridge",
        "runtime_qualification_on_Thor",
    }.issubset(contract["not_implemented"])
    assert contract["can_mark_capability_passed"] is False
    assert contract["runtime_evidence"] == []


def test_response_errors_use_client_observed_message_key(tmp_path: Path) -> None:
    response = app(tmp_path).dispatch("GET", "/api/projects/999/")
    assert response.status == 404
    assert set(payload(response)) == {"message"}  # type: ignore[arg-type]
