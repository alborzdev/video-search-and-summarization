# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[5]
PATCH_PATH = REPO_ROOT / "deploy/docker/thor-local/patches/patch_lvs_file_management.py"
SPEC = importlib.util.spec_from_file_location("patch_lvs_file_management", PATCH_PATH)
assert SPEC and SPEC.loader
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


def server_fixture() -> str:
    return (
        patcher.SERVER_IP_IMPORT_OLD
        + "from fixture_models import (\n"
        + patcher.SERVER_IMPORT_OLD
        + ")\n"
        + patcher.SERVER_GUARD_HELPERS_OLD
        + "\n\nclass ViaServer:\n"
        + "    def setup(self, args):\n"
        + patcher.SERVER_MIDDLEWARE_OLD
        + "        async def add_video_file(\n"
        + "            file=None, id=None, sensor_name='', filename=''\n"
        + "        ) -> AddFileInfoResponse:\n"
        + "            logger.info(\n"
        + "                'add'\n"
        + "            )\n"
        + "            self.pipeline.upload_file(\n"
        + patcher.SERVER_UPLOAD_OLD
        + patcher.SERVER_ROUTE_OLD
        + "            summary='Delete',\n"
        + "        )\n"
        + "        async def delete_video_file(file_id):\n"
        + "            return None\n"
    )


def client_fixture() -> str:
    return (
        "class Fixture:\n"
        + "    def upload_file(\n"
        + "        self,\n"
        + "        file_obj_or_path,\n"
        + patcher.CLIENT_SIGNATURE_OLD
        + "        if hasattr(file_obj_or_path, 'read'):\n"
        + patcher.CLIENT_FILENAME_OLD
        + "            return fname\n\n"
        + patcher.CLIENT_OLD
        + '\n\n        Sticky-routed.\n        """\n'
        + "        return None\n"
    )


class LvsFileManagementPatchTests(unittest.TestCase):
    def test_patch_output_matches_reviewed_checkout_sources(self) -> None:
        server = (
            REPO_ROOT / "services/video-summarization/src/via_server.py"
        ).read_text(encoding="utf-8")
        client = (
            REPO_ROOT / "services/video-summarization/src/rtvi_vlm_client.py"
        ).read_text(encoding="utf-8")
        baseline_server = server
        for new, old in (
            (patcher.SERVER_IP_IMPORT_NEW, patcher.SERVER_IP_IMPORT_OLD),
            (patcher.SERVER_GUARD_HELPERS_NEW, patcher.SERVER_GUARD_HELPERS_OLD),
            (patcher.SERVER_MIDDLEWARE_NEW, patcher.SERVER_MIDDLEWARE_OLD),
            (patcher.SERVER_IMPORT_NEW, patcher.SERVER_IMPORT_OLD),
            (patcher.SERVER_UPLOAD_NEW, patcher.SERVER_UPLOAD_OLD),
            (patcher.SERVER_FILENAME_GUARD_NEW, patcher.SERVER_FILENAME_GUARD_OLD),
            (patcher.SERVER_ROUTE_NEW, patcher.SERVER_ROUTE_OLD),
        ):
            self.assertEqual(baseline_server.count(new), 1)
            baseline_server = baseline_server.replace(new, old, 1)
        baseline_client = client
        for new, old in (
            (patcher.CLIENT_SIGNATURE_NEW, patcher.CLIENT_SIGNATURE_OLD),
            (patcher.CLIENT_FILENAME_NEW, patcher.CLIENT_FILENAME_OLD),
            (patcher.CLIENT_NEW, patcher.CLIENT_OLD),
        ):
            self.assertEqual(baseline_client.count(new), 1)
            baseline_client = baseline_client.replace(new, old, 1)
        self.assertEqual(patcher.patch_server_source(baseline_server), server)
        self.assertEqual(patcher.patch_client_source(baseline_client), client)

    def test_exact_server_markers_add_proxy_and_preserve_upload_name(self) -> None:
        patched = patcher.patch_server_source(server_fixture())
        self.assertIn("async def get_video_file_info", patched)
        self.assertIn("upload_filename=file.filename if file else None", patched)
        self.assertIn("    FileInfo,", patched)
        self.assertIn("async def restrict_file_api", patched)
        self.assertIn("not _file_api_request_allowed(", patched)
        self.assertIn("if filename and not self._file_api_allow_filename", patched)
        ast.parse(patched)

    def test_guard_helpers_are_strict_and_numeric(self) -> None:
        namespace = {
            "os": __import__("os"),
            "ip_address": __import__("ipaddress").ip_address,
            "API_PREFIX": "/v1",
        }
        module = ast.parse(patcher.SERVER_GUARD_HELPERS_NEW + "    pass\n")
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<guard>", "exec"), namespace)
        strict_flag = namespace["_strict_environment_flag"]
        is_loopback = namespace["_is_numeric_loopback"]
        request_allowed = namespace["_file_api_request_allowed"]
        with mock.patch.dict(namespace["os"].environ, {"FLAG": "invalid"}, clear=False):
            with self.assertRaisesRegex(ValueError, "FLAG must be"):
                strict_flag("FLAG", False)
        self.assertTrue(is_loopback("127.0.0.1"))
        self.assertTrue(is_loopback("::1"))
        for host in ("localhost", "0.0.0.0", "10.0.0.1", "172.17.0.1", ""):
            with self.subTest(host=host):
                self.assertFalse(is_loopback(host))
        for path in ("/v1/files", "/v1/files/asset-id"):
            self.assertTrue(request_allowed(path, "127.0.0.1", True))
            self.assertTrue(request_allowed(path, "::1", True))
            self.assertFalse(request_allowed(path, "10.0.0.1", True))
            self.assertFalse(request_allowed(path, "", True))
            self.assertTrue(request_allowed(path, "10.0.0.1", False))
        self.assertTrue(request_allowed("/v1/metrics", "10.0.0.1", True))
        self.assertTrue(request_allowed("/v1/ready", "", True))

    def test_exact_client_markers_add_sticky_get_and_upload_name(self) -> None:
        patched = patcher.patch_client_source(client_fixture())
        self.assertIn("def get_file_info", patched)
        self.assertIn('headers={"x-stream-id": str(file_id)}', patched)
        self.assertIn("upload_filename=None", patched)
        self.assertIn("fname = upload_filename or", patched)
        ast.parse(patched)

    def test_missing_or_duplicate_markers_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            patcher.patch_server_source("class Unrelated:\n    pass\n")
        duplicated = client_fixture() + "\n" + client_fixture()
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            patcher.patch_client_source(duplicated)

    def test_two_file_patch_is_atomic_per_target_and_preserves_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            server = root / "via_server.py"
            client = root / "rtvi_vlm_client.py"
            server.write_text(server_fixture(), encoding="utf-8")
            client.write_text(client_fixture(), encoding="utf-8")
            server.chmod(0o640)
            client.chmod(0o640)
            self.assertEqual(
                patcher.main([str(PATCH_PATH), str(server), str(client)]), 0
            )
            self.assertEqual(server.stat().st_mode & 0o777, 0o640)
            self.assertEqual(client.stat().st_mode & 0o777, 0o640)
            self.assertIn("get_video_file_info", server.read_text())
            self.assertIn("def get_file_info", client.read_text())
            self.assertEqual(list(root.glob(".*.thor-file-management")), [])

    def test_symlink_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual.py"
            actual.write_text(server_fixture(), encoding="utf-8")
            link = root / "via_server.py"
            link.symlink_to(actual.name)
            with self.assertRaisesRegex(RuntimeError, "not a regular file"):
                patcher.patch_file(
                    link, patcher.patch_server_source, ".thor-file-management"
                )


if __name__ == "__main__":
    unittest.main()
