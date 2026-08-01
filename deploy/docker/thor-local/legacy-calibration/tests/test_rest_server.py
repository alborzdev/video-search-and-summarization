# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

LANE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LANE))
import rest_server as server  # noqa: E402


def project(project_id: str = "rest-gis") -> dict:
    image = [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
        [50, 0],
        [100, 50],
        [50, 100],
        [0, 50],
    ]
    return {
        "schema_version": 1,
        "project_id": project_id,
        "project_type": "geo",
        "provider": "local_coordinate_plane",
        "calibration_type": "geo",
        "osm_url": "",
        "road_city": "Operator City",
        "road_intersection": "Operator Intersection",
        "camera": {
            "id": f"sensor-{project_id}",
            "image_size": [1920, 1080],
            "correspondences": [
                {"image": point, "world": [point[0] + 10, point[1] - 5]}
                for point in image
            ],
            "origin": {"lat": 0, "lng": 0},
            "geo_location": {"lat": 37.39, "lng": -121.95},
            "coordinates": {"x": 0, "y": 0},
            "scale_factor": 1,
            "attributes": [{"name": "source", "value": "operator-custom"}],
            "place": [{"name": "city", "value": "Operator City"}],
        },
        "rois": [
            {
                "id": "roi-01",
                "points": [
                    [0, 0],
                    [25, 0],
                    [50, 0],
                    [50, 25],
                    [50, 50],
                    [25, 50],
                    [0, 50],
                    [0, 25],
                ],
            }
        ],
        "tripwires": [
            {
                "id": "tripwire-01",
                "points": [[10, 10], [40, 40]],
                "direction": [[20, 10], [20, 40]],
            }
        ],
        "road_links": [
            {
                "id": "road-01",
                "direction": "E",
                "points": [
                    {"lat": 37.39, "lon": -121.96, "alt": 0},
                    {"lat": 37.39, "lon": -121.95, "alt": 0},
                    {"lat": 37.39, "lon": -121.94, "alt": 0},
                ],
            }
        ],
    }


def encoded(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def application(tmp_path: Path) -> server.Application:
    return server.Application(server.LocalProjectStore(tmp_path.resolve()))


def test_default_cli_is_inert_plan_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert server.main([]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["mode"] == "inert_plan_only"
    assert value["started"] is False
    assert value["bind"] == {"host": "127.0.0.1", "port": 8003, "loopback_only": True}
    assert value["provider_egress"] == "forbidden"
    assert value["runtime_evidence"] == []


def test_serve_requires_exact_ack_and_absolute_data_root(
    monkeypatch, tmp_path: Path
) -> None:
    called = []
    monkeypatch.setattr(server, "serve", lambda root: called.append(root))
    assert server.main(["serve", "--data-root", str(tmp_path)]) == 1
    assert called == []
    assert (
        server.main(
            [
                "serve",
                "--acknowledgement",
                server.ACKNOWLEDGEMENT,
                "--data-root",
                "relative",
            ]
        )
        == 1
    )
    assert called == []
    assert (
        server.main(
            [
                "serve",
                "--acknowledgement",
                server.ACKNOWLEDGEMENT,
                "--data-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert called == [tmp_path]


def test_project_crud_persists_only_bounded_local_files(tmp_path: Path) -> None:
    app = application(tmp_path)
    value = project()
    assert app.dispatch("POST", "/api/projects/", encoded(value)) == (201, value)
    assert app.dispatch("GET", "/api/projects/") == (200, {"projects": [value]})
    assert app.dispatch("GET", "/api/projects/rest-gis/") == (200, value)
    status, patched = app.dispatch(
        "PATCH", "/api/projects/rest-gis/", encoded({"tripwires": []})
    )
    assert status == 200 and patched["tripwires"] == []
    directory = tmp_path / "rest-gis"
    assert {item.name for item in directory.iterdir()} == set(server.PROJECT_FILES)
    restarted = application(tmp_path)
    assert restarted.dispatch("GET", "/api/projects/rest-gis/")[1]["tripwires"] == []
    assert restarted.dispatch("DELETE", "/api/projects/rest-gis/") == (
        200,
        {"deleted": "rest-gis"},
    )
    assert not directory.exists()


def test_sensor_and_homography_subset_round_trip(tmp_path: Path) -> None:
    app = application(tmp_path)
    value = project()
    app.dispatch("POST", "/api/projects/", encoded(value))
    sensor_id = "sensor-rest-gis"
    status, sensor = app.dispatch("GET", f"/api/sensors/{sensor_id}/")
    assert status == 200 and sensor["project_id"] == "rest-gis"
    sensor_patch = value["camera"] | {"image_size": [1280, 720]}
    assert (
        app.dispatch("PATCH", f"/api/sensors/{sensor_id}/", encoded(sensor_patch))[0]
        == 200
    )
    exact = app.dispatch("GET", f"/api/homography/{sensor_id}/")
    approximate = app.dispatch("GET", f"/api/approxHomography/{sensor_id}/")
    assert exact[0] == approximate[0] == 200
    assert exact[1]["homography"] == [
        [1.0, 0.0, 10.0],
        [0.0, 1.0, -5.0],
        [0.0, 0.0, 1.0],
    ]
    assert exact[1]["approximate"] is False
    assert approximate[1]["approximate"] is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/invertImage/sensor-rest/",
        "/api/importSensors/rest-gis/",
        "/api/getWarpedFiles/rest-gis/",
        "/api/getImageFiles/rest-gis/",
        "/api/uploadWebApi/rest-gis/",
    ],
)
def test_missing_upload_warp_import_endpoints_are_explicit_501(
    tmp_path: Path, path: str
) -> None:
    status, payload = application(tmp_path).dispatch("GET", path)
    assert status == 501
    assert "not implemented" in payload["error"]


def test_strict_bounded_json_and_provider_free_backend_fail_closed(
    tmp_path: Path,
) -> None:
    app = application(tmp_path)
    assert app.dispatch("POST", "/api/projects/", b'{"a":1,"a":2}')[0] == 400
    assert app.dispatch("POST", "/api/projects/", b'{"a":NaN}')[0] == 400
    assert (
        app.dispatch("POST", "/api/projects/", b"x" * (server.MAX_BODY_BYTES + 1))[0]
        == 413
    )
    value = project()
    value["provider"] = "google_maps"
    status, payload = app.dispatch("POST", "/api/projects/", encoded(value))
    assert status == 422
    assert "provider-free" in payload["error"]


def test_duplicate_sensor_identity_and_unmanaged_delete_fail_closed(
    tmp_path: Path,
) -> None:
    app = application(tmp_path)
    first = project("first")
    second = project("second")
    second["camera"]["id"] = first["camera"]["id"]
    assert app.dispatch("POST", "/api/projects/", encoded(first))[0] == 201
    assert app.dispatch("POST", "/api/projects/", encoded(second))[0] == 201
    assert app.dispatch("GET", f'/api/sensors/{first["camera"]["id"]}/')[0] == 409
    extra = tmp_path / "first" / "operator-note.txt"
    extra.write_text("preserve")
    assert app.dispatch("DELETE", "/api/projects/first/")[0] == 409
    assert extra.is_file()


def test_data_root_symlinks_relative_roots_and_unmanaged_entries_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(server.RestError, match="absolute"):
        server.LocalProjectStore(Path("relative"))
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(server.RestError, match="symlinks"):
        server.LocalProjectStore(link)
    store = server.LocalProjectStore(target)
    (target / "unexpected.txt").write_text("unmanaged")
    with pytest.raises(server.RestError, match="unmanaged"):
        store.list()


def test_route_and_runtime_surface_is_exact_without_client_egress() -> None:
    assert len(server.IMPLEMENTED_ENDPOINTS) == 9
    assert len(server.MISSING_ENDPOINTS) == 5
    assert server.HOST == "127.0.0.1" and server.PORT == 8003
    source = (LANE / "rest_server.py").read_text()
    for forbidden in (
        "requests",
        "urllib.request",
        "http.client",
        "subprocess",
        "docker",
    ):
        assert forbidden not in source
    assert "serve_forever()" in source
    assert "ThreadingHTTPServer((HOST, PORT)" in source
