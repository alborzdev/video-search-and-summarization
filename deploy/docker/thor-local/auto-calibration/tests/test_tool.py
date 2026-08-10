#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import stat
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


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


def write_test_zip(path: Path, members: list[tuple[str, bytes, int]]) -> list[dict]:
    with ZipFile(path, "w") as archive:
        for name, payload, mode in members:
            info = ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, payload)
    expected = []
    with ZipFile(path, "r") as archive:
        for info in archive.infolist():
            expected.append(
                {
                    "path": info.filename,
                    "kind": "directory" if info.is_dir() else "file",
                    "size_bytes": info.file_size,
                    "compressed_size_bytes": info.compress_size,
                    "crc32": f"{info.CRC:08x}",
                    "sha256": TOOL._zip_member_sha256(archive, info),
                    "compression_method": info.compress_type,
                    "unix_mode": f"{((info.external_attr >> 16) & 0xFFFF):06o}",
                }
            )
    return expected


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
            with mock.patch.object(
                TOOL, "_probe_video", side_effect=lambda path: values[path.name]
            ):
                with self.assertRaisesRegex(TOOL.ValidationError, "duration differs"):
                    TOOL.validate_video_dir(root)

    def test_detects_alignment_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "cam_00.mp4").touch()
            (root / "alignment_data.json").write_text("[[[1, 2]]]\n", encoding="utf-8")
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
                        "streams": [
                            {"camera_name": "cam_00", "rtsp_url": "rtsp://camera/live"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TOOL.ValidationError, "at least 60"):
                TOOL.validate_rtsp_plan(plan)

    def test_resolves_local_rtsp_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "alignment_data.json").write_text("[[[1, 2]]]\n", encoding="utf-8")
            (root / "layout.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            plan = root / "rtsp.json"
            plan.write_text(
                json.dumps(
                    {
                        "duration_seconds": 180,
                        "streams": [
                            {"camera_name": "cam_00", "rtsp_url": "rtsp://camera/live"}
                        ],
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
                        "streams": [
                            {
                                "camera_name": "cam_00",
                                "rtsp_url": "rtsp://camera:not-a-port/live",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                TOOL.ValidationError, "invalid RTSP port"
            ) as raised:
                TOOL.validate_rtsp_plan(plan)
        self.assertNotIn("not-a-port", str(raised.exception))


class ArtifactAndComposeTests(unittest.TestCase):
    def test_official_fixture_identity_is_exact_and_separate_from_warehouse(
        self,
    ) -> None:
        fixture = TOOL._official_fixture_declaration()
        self.assertEqual(fixture["commit"], "0cfd2b790fd77598b0543340a65c2a0e1d192327")
        self.assertEqual(fixture["expected_size_bytes"], 160499115)
        self.assertEqual(
            fixture["expected_sha256"],
            "0dceb0cc8324f5775b0c2007efe7a3e7c36fda10c5964b88e20712b002d98bdb",
        )
        self.assertEqual(fixture["archive"]["member_count"], 10)
        self.assertTrue(fixture["required_for_base_amc_acceptance"])
        self.assertFalse(fixture["required_for_service_start"])
        self.assertNotIn("warehouse-app-data", fixture["download_url"])

    def test_backend_lock_fields_are_atomic(self) -> None:
        declared = json.loads(TOOL.INVENTORY_PATH.read_text(encoding="utf-8"))
        backend = declared["images"]["backend"]
        self.assertEqual(
            backend["immutable_ref"] is None, backend["expected_image_id"] is None
        )
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


class OfficialFixtureTests(unittest.TestCase):
    def test_offline_verifier_rejects_outer_size_before_zip_parsing(self) -> None:
        fixture = {
            **TOOL._official_fixture_declaration(),
            "expected_size_bytes": 4,
            "expected_sha256": hashlib.sha256(b"bad").hexdigest(),
        }
        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                TOOL, "_official_fixture_declaration", return_value=fixture
            ),
        ):
            path = Path(raw) / "fixture.zip"
            path.write_bytes(b"bad")
            with self.assertRaisesRegex(TOOL.ValidationError, "size differs"):
                TOOL.verify_official_fixture(Path(raw), fixture_path=path)

    def test_offline_verifier_rejects_outer_digest_before_zip_parsing(self) -> None:
        fixture = {
            **TOOL._official_fixture_declaration(),
            "expected_size_bytes": 3,
            "expected_sha256": "0" * 64,
        }
        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                TOOL, "_official_fixture_declaration", return_value=fixture
            ),
        ):
            path = Path(raw) / "fixture.zip"
            path.write_bytes(b"bad")
            with self.assertRaisesRegex(TOOL.ValidationError, "digest differs"):
                TOOL.verify_official_fixture(Path(raw), fixture_path=path)

    def test_zip_member_oracle_accepts_exact_safe_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "safe.zip"
            expected = write_test_zip(
                path,
                [
                    ("fixture/", b"", stat.S_IFDIR | 0o755),
                    ("fixture/value.json", b'{"ok": true}\n', stat.S_IFREG | 0o644),
                ],
            )
            with ZipFile(path) as archive:
                observed = TOOL._verify_zip_members(
                    archive,
                    expected,
                    label="test ZIP",
                    expected_count=2,
                    expected_uncompressed=sum(item["size_bytes"] for item in expected),
                    expected_compressed=sum(
                        item["compressed_size_bytes"] for item in expected
                    ),
                )
        self.assertEqual(observed, expected)

    def test_zip_member_oracle_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "unsafe.zip"
            expected = write_test_zip(
                path, [("../escape", b"bad", stat.S_IFREG | 0o644)]
            )
            with ZipFile(path) as archive:
                with self.assertRaisesRegex(TOOL.ValidationError, "unsafe member path"):
                    TOOL._verify_zip_members(
                        archive,
                        expected,
                        label="test ZIP",
                        expected_count=1,
                        expected_uncompressed=3,
                        expected_compressed=expected[0]["compressed_size_bytes"],
                    )

    def test_zip_member_oracle_rejects_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "unsafe.zip"
            expected = write_test_zip(path, [("link", b"target", stat.S_IFLNK | 0o777)])
            with ZipFile(path) as archive:
                with self.assertRaisesRegex(TOOL.ValidationError, "symbolic-link"):
                    TOOL._verify_zip_members(
                        archive,
                        expected,
                        label="test ZIP",
                        expected_count=1,
                        expected_uncompressed=6,
                        expected_compressed=expected[0]["compressed_size_bytes"],
                    )

    def test_zip_member_oracle_rejects_duplicate_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with ZipFile(path, "w") as archive:
                    archive.writestr("same", b"one")
                    archive.writestr("same", b"two")
            with ZipFile(path) as archive:
                with self.assertRaisesRegex(TOOL.ValidationError, "duplicate"):
                    TOOL._verify_zip_members(
                        archive,
                        [],
                        label="test ZIP",
                        expected_count=2,
                        expected_uncompressed=6,
                        expected_compressed=sum(
                            item.compress_size for item in archive.infolist()
                        ),
                    )

    def test_atomic_stage_downloads_verifies_and_publishes(self) -> None:
        fixture_bytes = b"fixture"
        fixture = {
            **TOOL._official_fixture_declaration(),
            "filename": "fixture.zip",
            "cache_relative_path": "vss/amc/test/fixture.zip",
            "expected_size_bytes": len(fixture_bytes),
            "expected_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        }

        def download(_url: str, target: Path) -> None:
            target.write_bytes(fixture_bytes)

        def verify(_root: Path, *, fixture_path: Path | None = None) -> dict:
            assert fixture_path is not None
            self.assertEqual(fixture_path.read_bytes(), fixture_bytes)
            return {"state": "locked", "sha256": fixture["expected_sha256"]}

        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                TOOL, "_official_fixture_declaration", return_value=fixture
            ),
            mock.patch.object(TOOL, "_download_official_fixture", side_effect=download),
            mock.patch.object(TOOL, "verify_official_fixture", side_effect=verify),
        ):
            result = TOOL.stage_official_fixture(Path(raw), 0)
            target = Path(raw) / fixture["cache_relative_path"]
            self.assertEqual(target.read_bytes(), fixture_bytes)
            self.assertEqual(
                result["publish_state"], "downloaded_verified_and_published"
            )
            self.assertEqual(list(target.parent.glob("*.partial")), [])

    def test_atomic_stage_fails_disk_guard_before_download(self) -> None:
        fixture = {
            **TOOL._official_fixture_declaration(),
            "filename": "fixture.zip",
            "cache_relative_path": "vss/amc/test/fixture.zip",
            "expected_size_bytes": 100,
        }
        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                TOOL, "_official_fixture_declaration", return_value=fixture
            ),
            mock.patch.object(
                TOOL.shutil, "disk_usage", return_value=SimpleNamespace(free=99)
            ),
            mock.patch.object(TOOL, "_download_official_fixture") as download,
        ):
            with self.assertRaisesRegex(TOOL.Unavailable, "insufficient free space"):
                TOOL.stage_official_fixture(Path(raw), 0)
        download.assert_not_called()

    def test_atomic_stage_removes_partial_on_verification_failure(self) -> None:
        fixture = {
            **TOOL._official_fixture_declaration(),
            "filename": "fixture.zip",
            "cache_relative_path": "vss/amc/test/fixture.zip",
            "expected_size_bytes": 3,
        }

        def download(_url: str, target: Path) -> None:
            target.write_bytes(b"bad")

        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                TOOL, "_official_fixture_declaration", return_value=fixture
            ),
            mock.patch.object(TOOL, "_download_official_fixture", side_effect=download),
            mock.patch.object(
                TOOL,
                "verify_official_fixture",
                side_effect=TOOL.ValidationError("bad fixture"),
            ),
        ):
            with self.assertRaisesRegex(TOOL.ValidationError, "bad fixture"):
                TOOL.stage_official_fixture(Path(raw), 0)
            target = Path(raw) / fixture["cache_relative_path"]
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("*.partial")), [])


class RuntimeContractTests(unittest.TestCase):
    def test_contract_covers_complete_skill_advertised_surface(self) -> None:
        self.assertEqual(len(TOOL.REQUIRED_OPENAPI), 26)
        required = {
            ("/v1/upload_alignment/{project_id}", "post"),
            ("/v1/upload_layout/{project_id}", "post"),
            ("/v1/{type}/calibrate/{project_id}/log", "get"),
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
        with (
            mock.patch.object(
                TOOL,
                "_get_json",
                side_effect=[(200, {"code": 0}), (200, {"paths": paths})],
            ) as get_json,
            mock.patch.object(TOOL, "_get_status", return_value=200),
        ):
            result = TOOL.qualify_runtime(
                "http://127.0.0.1:8010/v1", "http://127.0.0.1:5000", None, 0.1
            )
        self.assertEqual(
            [call.args[0] for call in get_json.call_args_list],
            [
                "http://127.0.0.1:8010/v1/ready",
                "http://127.0.0.1:8010/openapi.yaml",
            ],
        )
        self.assertEqual(result["method"], "GET-only")
        self.assertEqual(
            result["openapi_required_operations"], len(TOOL.REQUIRED_OPENAPI)
        )

    def test_accepts_numeric_ipv4_and_ipv6_loopback_origins(self) -> None:
        paths = {path: {method: {}} for path, method in TOOL.REQUIRED_OPENAPI.items()}
        with (
            mock.patch.object(
                TOOL,
                "_get_json",
                side_effect=[(200, {"code": 0}), (200, {"paths": paths}), (200, [])],
            ),
            mock.patch.object(TOOL, "_get_status", return_value=200),
        ):
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
            (
                "http://127.0.0.1:8010/v1",
                "http://127.0.0.1:5000",
                "http://127.0.0.1:30888/vst",
            ),
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
