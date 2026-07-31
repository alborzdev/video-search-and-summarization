#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tool.py"
SPEC = importlib.util.spec_from_file_location("thor_amc_tool", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def probe(*, duration: float = 180.0, width: int = 1920, height: int = 1080) -> dict:
    return {
        "codec": "h264",
        "width": width,
        "height": height,
        "fps": 30.0,
        "frames": int(duration * 30),
        "duration_seconds": duration,
        "start_time_seconds": 0.0,
    }


class VideoValidationTests(unittest.TestCase):
    def test_accepts_contiguous_synchronized_videos(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "cam_00.mp4").touch()
            (root / "cam_01.mp4").touch()
            with mock.patch.object(TOOL, "_probe_video", return_value=probe()):
                result = TOOL.validate_video_dir(root)
        self.assertEqual(result["camera_count"], 2)
        self.assertFalse(result["api_upload_ready"])

    def test_rejects_camera_index_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "cam_00.mp4").touch()
            (root / "cam_02.mp4").touch()
            with self.assertRaisesRegex(TOOL.ValidationError, "contiguous"):
                TOOL.validate_video_dir(root)

    def test_rejects_duration_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "cam_00.mp4"
            second = root / "cam_01.mp4"
            first.touch()
            second.touch()
            values = {first.name: probe(), second.name: probe(duration=179.0)}
            with mock.patch.object(TOOL, "_probe_video", side_effect=lambda path: values[path.name]):
                with self.assertRaisesRegex(TOOL.ValidationError, "duration differs"):
                    TOOL.validate_video_dir(root)

    def test_detects_alignment_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "cam_00.mp4").touch()
            (root / "alignment_data.json").write_text("{}\n", encoding="utf-8")
            (root / "layout.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            with mock.patch.object(TOOL, "_probe_video", return_value=probe()):
                result = TOOL.validate_video_dir(root)
        self.assertTrue(result["api_upload_ready"])


class RtspValidationTests(unittest.TestCase):
    def test_redacts_rtsp_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            plan = Path(raw) / "rtsp.json"
            secret = "not-for-output"
            plan.write_text(
                json.dumps(
                    {
                        "duration_seconds": 180,
                        "streams": [
                            {
                                "camera_name": "loading-dock",
                                "rtsp_url": f"rtsp://operator:{secret}@camera.example:554/live",
                                "sensor_id": None,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = TOOL.validate_rtsp_plan(plan)
        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)
        self.assertTrue(result["streams"][0]["credentials_present"])

    def test_rejects_short_capture(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            plan = Path(raw) / "rtsp.json"
            plan.write_text(
                json.dumps(
                    {
                        "duration_seconds": 59,
                        "streams": [{"camera_name": "cam_00", "rtsp_url": "rtsp://camera/live"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TOOL.ValidationError, "at least 60"):
                TOOL.validate_rtsp_plan(plan)

    def test_resolves_local_rtsp_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "alignment_data.json").write_text("{}\n", encoding="utf-8")
            (root / "layout.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            plan = root / "rtsp.json"
            plan.write_text(
                json.dumps(
                    {
                        "duration_seconds": 180,
                        "streams": [{"camera_name": "cam_00", "rtsp_url": "rtsp://camera/live"}],
                        "alignment_json": "alignment_data.json",
                        "layout_png": "layout.png",
                    }
                ),
                encoding="utf-8",
            )
            result = TOOL.validate_rtsp_plan(plan)
        self.assertTrue(result["api_upload_ready"])

    def test_rejects_invalid_rtsp_port_without_echoing_url(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            plan = Path(raw) / "rtsp.json"
            plan.write_text(
                json.dumps(
                    {
                        "duration_seconds": 180,
                        "streams": [{"camera_name": "cam_00", "rtsp_url": "rtsp://camera:not-a-port/live"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TOOL.ValidationError, "invalid RTSP port") as raised:
                TOOL.validate_rtsp_plan(plan)
        self.assertNotIn("not-a-port", str(raised.exception))


class ArtifactAndComposeTests(unittest.TestCase):
    def test_backend_lock_fields_are_atomic(self) -> None:
        declared = json.loads(TOOL.INVENTORY_PATH.read_text(encoding="utf-8"))
        backend = declared["images"]["backend"]
        self.assertEqual(backend["immutable_ref"] is None, backend["expected_image_id"] is None)
        self.assertTrue(backend["required"])
        if backend["immutable_ref"] is not None:
            self.assertIn("@sha256:", backend["immutable_ref"])

    def test_ui_is_content_locked(self) -> None:
        declared = json.loads(TOOL.INVENTORY_PATH.read_text(encoding="utf-8"))
        ui = declared["images"]["ui"]
        self.assertIn("@sha256:", ui["immutable_ref"])
        self.assertTrue(ui["expected_image_id"].startswith("sha256:"))

    def test_thor_overlay_resolves_loopback_and_bounded_logs(self) -> None:
        backend = "nvcr.io/nvidia/vss-core/vss-auto-calibration@sha256:" + "a" * 64
        environment = {
            "COMPOSE_PROFILES": "auto_calib",
            "THOR_AMC_BACKEND_IMAGE": backend,
            "VSS_APPS_DIR": str(TOOL.DOCKER_ROOT),
            "VSS_DATA_DIR": str(TOOL.DOCKER_ROOT / "data-dir"),
            "HOST_IP": "127.0.0.1",
        }
        with mock.patch.dict("os.environ", environment, clear=False):
            completed = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(TOOL.UPSTREAM_COMPOSE),
                    "-f",
                    str(TOOL.THOR_COMPOSE),
                    "config",
                    "--format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
                env={**__import__("os").environ, **environment},
            )
        resolved = json.loads(completed.stdout)["services"]
        backend_service = resolved["vss-auto-calibration"]
        ui_service = resolved["vss-auto-calibration-ui"]
        self.assertEqual(backend_service["image"], backend)
        self.assertIn("127.0.0.1", backend_service["command"])
        self.assertEqual(ui_service["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(backend_service["logging"]["options"]["max-size"], "20m")
        self.assertEqual(ui_service["restart"], "no")


class RuntimeContractTests(unittest.TestCase):
    def test_contract_covers_complete_skill_advertised_surface(self) -> None:
        self.assertEqual(len(TOOL.REQUIRED_OPENAPI), 26)
        required = {
            ("/v1/upload_alignment/{project_id}", "post"),
            ("/v1/upload_layout/{project_id}", "post"),
            ("/v1/rtsp/capture/{project_id}/{session_id}", "get"),
            ("/v1/rtsp/capture/{project_id}/{session_id}/ingest", "post"),
            ("/v1/rtsp/capture/{project_id}/{session_id}/stop", "post"),
            ("/v1/rtsp/session/{project_id}/{session_id}", "delete"),
            ("/v1/vggt/calibrate/{project_id}", "post"),
            ("/v1/delete_project/{id}", "delete"),
        }
        self.assertTrue(required.issubset(set(TOOL.REQUIRED_OPENAPI.items())))

    def test_openapi_parameter_names_are_normalized(self) -> None:
        paths = {}
        for index, (path, method) in enumerate(TOOL.REQUIRED_OPENAPI.items()):
            renamed = __import__("re").sub(r"\{[^{}]+\}", f"{{value_{index}}}", path)
            paths[renamed] = {method: {}}
        self.assertEqual(TOOL._missing_openapi_operations(paths), [])

    def test_get_only_qualification_checks_declared_operations(self) -> None:
        paths = {path: {method: {}} for path, method in TOOL.REQUIRED_OPENAPI.items()}
        with mock.patch.object(
            TOOL,
            "_get_json",
            side_effect=[(200, {"code": 0}), (200, {"paths": paths})],
        ), mock.patch.object(TOOL, "_get_status", return_value=200):
            result = TOOL.qualify_runtime("http://127.0.0.1:8010/v1", "http://127.0.0.1:5000", None, 0.1)
        self.assertEqual(result["method"], "GET-only")
        self.assertEqual(result["openapi_required_operations"], len(TOOL.REQUIRED_OPENAPI))

    def test_accepts_numeric_ipv4_and_ipv6_loopback_origins(self) -> None:
        paths = {path: {method: {}} for path, method in TOOL.REQUIRED_OPENAPI.items()}
        with mock.patch.object(
            TOOL,
            "_get_json",
            side_effect=[(200, {"code": 0}), (200, {"paths": paths}), (200, [])],
        ), mock.patch.object(TOOL, "_get_status", return_value=200):
            result = TOOL.qualify_runtime(
                "http://[::1]:8010/v1/",
                "http://127.0.0.2:5000/",
                "http://127.0.0.1:30888",
                0.1,
            )
        self.assertTrue(result["vios_sensor_list_reachable"])

    def test_rejects_non_loopback_before_any_request(self) -> None:
        caller = "http://192.0.2.44:8010/v1"
        with mock.patch.object(TOOL, "_get_json") as get_json:
            with self.assertRaises(TOOL.ValidationError) as raised:
                TOOL.qualify_runtime(caller, "http://127.0.0.1:5000", None, 0.1)
        get_json.assert_not_called()
        self.assertNotIn(caller, str(raised.exception))
        self.assertIn("numeric loopback", str(raised.exception))

    def test_rejects_credentials_without_echoing_secret(self) -> None:
        secret = "do-not-echo"
        caller = f"http://operator:{secret}@127.0.0.1:8010/v1"
        with mock.patch.object(TOOL, "_get_json") as get_json:
            with self.assertRaises(TOOL.ValidationError) as raised:
                TOOL.qualify_runtime(caller, "http://127.0.0.1:5000", None, 0.1)
        get_json.assert_not_called()
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(caller, str(raised.exception))

    def test_rejects_hostname_query_fragment_and_non_root_ui_path(self) -> None:
        cases = [
            ("http://localhost:8010/v1", "http://127.0.0.1:5000", None),
            ("http://127.0.0.1:8010/v1?token=secret", "http://127.0.0.1:5000", None),
            ("http://127.0.0.1:8010/v1#secret", "http://127.0.0.1:5000", None),
            (" http://127.0.0.1:8010/v1", "http://127.0.0.1:5000", None),
            ("http://[::1%25lo]:8010/v1", "http://127.0.0.1:5000", None),
            ("http://127.0.0.1:8010/v1", "http://127.0.0.1:5000/admin", None),
            ("http://127.0.0.1:8010/v1", "http://127.0.0.1:5000", "http://127.0.0.1:30888/vst"),
        ]
        for backend, ui, vios in cases:
            with self.subTest(backend=backend, ui=ui, vios=vios):
                with mock.patch.object(TOOL, "_get_json") as get_json:
                    with self.assertRaises(TOOL.ValidationError) as raised:
                        TOOL.qualify_runtime(backend, ui, vios, 0.1)
                get_json.assert_not_called()
                message = str(raised.exception)
                self.assertNotIn("secret", message)
                self.assertNotIn(backend, message)
                self.assertNotIn(ui, message)
                if vios:
                    self.assertNotIn(vios, message)


if __name__ == "__main__":
    unittest.main()
