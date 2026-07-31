# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock


_SCRIPT = Path(__file__).resolve().parents[2] / "thor-local" / "openclaw" / "toolchain.py"
_LOCK = _SCRIPT.with_name("toolchain.lock.json")
_SPEC = importlib.util.spec_from_file_location("thor_openclaw_toolchain", _SCRIPT)
assert _SPEC and _SPEC.loader
toolchain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(toolchain)


class ThorOpenClawToolchainTest(unittest.TestCase):
    def _cache_fixture(self, root: Path) -> tuple[Path, Path, dict[str, Path]]:
        cache = root / "cache"
        source = cache / "downloads" / "nemoclaw-source.tar.gz"
        openshell = cache / "downloads" / "openshell-arm64.tar.gz"
        package = cache / "artifacts" / "nemoclaw-test.tgz"
        package_lock = cache / "artifacts" / "nemoclaw-package-lock.json"
        for path, content in (
            (source, b"source"),
            (openshell, b"openshell"),
            (package, b"package"),
            (package_lock, b"package-lock"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        lock_data = {
            "nemoclaw": {
                "source": {"filename": source.name, "sha256": toolchain.sha256(source)},
                "package_filename": package.name,
                "package_sha256": toolchain.sha256(package),
                "root_package_lock_sha256": toolchain.sha256(package_lock),
            },
            "openshell": {
                "artifacts": [
                    {"filename": openshell.name, "sha256": toolchain.sha256(openshell)}
                ]
            },
            "openclaw": {
                "archive_filename": "sandbox.tar",
                "arm64_config_digest": "sha256:" + "a" * 64,
            },
        }
        lock = root / "input-lock.json"
        lock.write_text(json.dumps(lock_data, sort_keys=True) + "\n")
        cached_lock = cache / "toolchain.lock.json"
        cached_lock.write_bytes(lock.read_bytes())
        tracked = [source, openshell, package, package_lock, cached_lock]
        manifest = {
            "schema_version": toolchain.MANIFEST_SCHEMA_VERSION,
            "lock_sha256": toolchain.sha256(lock),
            "npm_registry": "https://registry.npmjs.org/",
            "npm_cache_verified_offline": True,
            "sandbox_image_staged": False,
            "artifacts": toolchain.manifest_entries(cache, tracked),
        }
        (cache / toolchain.MANIFEST_NAME).write_text(json.dumps(manifest))
        return lock, cache, {
            "source": source,
            "openshell": openshell,
            "package": package,
            "package_lock": package_lock,
            "cached_lock": cached_lock,
        }

    def test_lock_is_immutable_arm64_compatibility_set(self) -> None:
        lock = toolchain.load_json(_LOCK)
        self.assertEqual(lock["platform"], "linux/arm64")
        self.assertEqual(lock["nemoclaw"]["tag"], "v0.0.48")
        self.assertRegex(lock["nemoclaw"]["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(lock["openshell"]["version"], "0.0.39")
        self.assertEqual(lock["openclaw"]["version"], "2026.4.24")
        self.assertRegex(lock["openclaw"]["sandbox_image"], r"@sha256:[0-9a-f]{64}$")
        self.assertRegex(lock["openclaw"]["arm64_config_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(lock["nemoclaw"]["package_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(lock["provider"]["model"], "datasheet-chat")
        self.assertEqual(
            lock["provider"]["sandbox_base_url"],
            "http://host.openshell.internal:8000/v1",
        )
        self.assertEqual(len(lock["openshell"]["artifacts"]), 3)
        for artifact in lock["openshell"]["artifacts"]:
            self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")

    def test_provider_env_contains_no_external_or_secret_provider(self) -> None:
        lock = toolchain.load_json(_LOCK)
        args = type("Args", (), {"prefix": Path("/opt/vss-openclaw"), "sandbox_name": "vss-thor"})
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertEqual(toolchain.cmd_provider_env(lock, args), 0)
        text = output.getvalue()
        self.assertIn("NEMOCLAW_PROVIDER=custom", text)
        self.assertIn("NEMOCLAW_MODEL=datasheet-chat", text)
        self.assertIn("host.openshell.internal:8000/v1", text)
        self.assertIn("COMPATIBLE_API_KEY=local", text)
        self.assertNotIn("NVIDIA_API_KEY", text)
        self.assertNotIn("integrate.api.nvidia.com", text)

    def test_provider_env_quotes_shell_metacharacters_in_prefix(self) -> None:
        lock = toolchain.load_json(_LOCK)
        args = type(
            "Args",
            (),
            {
                "prefix": Path("/tmp/colon:$(touch openclaw-injection)"),
                "sandbox_name": "vss-thor",
            },
        )
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertEqual(toolchain.cmd_provider_env(lock, args), 0)
        self.assertIn(
            "export PATH='/tmp/colon:$(touch openclaw-injection)/bin':\"$PATH\"",
            output.getvalue(),
        )

    def test_npm_pack_parser_accepts_leading_progress_json(self) -> None:
        output = (
            '{"added": 0, "removed": 0}\n'
            '[{"id": "nemoclaw@0.1.0", "filename": "nemoclaw-0.1.0.tgz"}]\n'
        )
        self.assertEqual(
            toolchain.package_name_from_output(output), "nemoclaw-0.1.0.tgz"
        )

    def test_npm_pack_parser_rejects_unsafe_filename(self) -> None:
        with self.assertRaisesRegex(toolchain.ToolchainError, "unsafe"):
            toolchain.package_name_from_output('[{"filename": "../bad.tgz"}]')

    def test_npm_cache_uses_explicit_registry_not_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ", {"npm_config_registry": "https://example.invalid/"}
            ):
                env = toolchain.npm_environment(
                    Path(tmp),
                    offline=True,
                    registry="https://registry.example.test/",
                )
        self.assertEqual(env["npm_config_registry"], "https://registry.example.test/")
        self.assertEqual(env["npm_config_replace_registry_host"], "always")
        self.assertEqual(env["npm_config_offline"], "true")

    def test_registry_validation_requires_credential_free_https(self) -> None:
        self.assertEqual(
            toolchain.validated_registry("https://registry.example.test/npm"),
            "https://registry.example.test/npm/",
        )
        for value in (
            "http://registry.example.test/",
            "https://user:pass@registry.example.test/",
            "https://registry.example.test/?token=secret",
        ):
            with self.subTest(value=value):
                with self.assertRaises(toolchain.ToolchainError):
                    toolchain.validated_registry(value)

    def test_manifest_rejects_artifact_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock, cache, files = self._cache_fixture(Path(tmp))
            files["package"].write_bytes(b"evil")
            with self.assertRaisesRegex(toolchain.ToolchainError, "SHA-256 mismatch"):
                toolchain.verify_manifest(lock, cache, require_image=False)

    def test_manifest_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock, cache, _ = self._cache_fixture(root)
            outside = root.parent / "outside-openclaw-test"
            outside.write_bytes(b"outside")
            self.addCleanup(outside.unlink, missing_ok=True)
            manifest_path = cache / toolchain.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"].append(
                {
                    "path": "../outside-openclaw-test",
                    "sha256": toolchain.sha256(outside),
                    "size": 7,
                }
            )
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(toolchain.ToolchainError, "escapes cache"):
                toolchain.verify_manifest(lock, cache, require_image=False)

    def test_complete_verification_requires_image_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock, cache, _ = self._cache_fixture(Path(tmp))
            with self.assertRaisesRegex(toolchain.ToolchainError, "not air-gap complete"):
                toolchain.verify_manifest(lock, cache, require_image=True)

    def test_manifest_requires_exact_committed_artifact_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock, cache, _ = self._cache_fixture(Path(tmp))
            manifest_path = cache / toolchain.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"] = []
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(toolchain.ToolchainError, "inventory mismatch"):
                toolchain.verify_manifest(lock, cache, require_image=False)

    def test_manifest_rejects_unlisted_package_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock, cache, _ = self._cache_fixture(Path(tmp))
            (cache / "artifacts" / "nemoclaw-evil.tgz").write_bytes(b"evil")
            with self.assertRaisesRegex(toolchain.ToolchainError, "filesystem inventory mismatch"):
                toolchain.verify_manifest(lock, cache, require_image=False)

    def test_tar_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "bad.tar"
            with tarfile.open(archive, "w") as bundle:
                member = tarfile.TarInfo("../escape")
                payload = b"bad"
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
            with self.assertRaises((tarfile.TarError, OSError)):
                toolchain.extract_tar(archive, root / "out")

    def test_sandbox_archive_is_bound_to_committed_arm64_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "sandbox.tar"
            layer_name = "layer/layer.tar"
            layer = b"layer"
            layer_hash = toolchain.hashlib.sha256(layer).hexdigest()
            config = json.dumps(
                {
                    "architecture": "arm64",
                    "os": "linux",
                    "rootfs": {"diff_ids": [f"sha256:{layer_hash}"]},
                },
                sort_keys=True,
            ).encode()
            config_hash = toolchain.hashlib.sha256(config).hexdigest()
            manifest = json.dumps(
                [{"Config": f"{config_hash}.json", "Layers": [layer_name]}]
            ).encode()
            with tarfile.open(archive, "w") as bundle:
                for name, payload in (
                    ("manifest.json", manifest),
                    (f"{config_hash}.json", config),
                    (layer_name, layer),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
            lock = {"openclaw": {"arm64_config_digest": f"sha256:{config_hash}"}}
            toolchain.verify_sandbox_archive(lock, archive)
            lock["openclaw"]["arm64_config_digest"] = "sha256:" + "c" * 64
            with self.assertRaisesRegex(toolchain.ToolchainError, "committed ARM64 image"):
                toolchain.verify_sandbox_archive(lock, archive)

    def test_sandbox_archive_rejects_mutable_tags_and_layer_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "sandbox.tar"
            layer_name = "layer/layer.tar"
            layer = b"tampered-layer"
            expected_layer_hash = toolchain.hashlib.sha256(b"expected-layer").hexdigest()
            config = json.dumps(
                {
                    "architecture": "arm64",
                    "os": "linux",
                    "rootfs": {"diff_ids": [f"sha256:{expected_layer_hash}"]},
                },
                sort_keys=True,
            ).encode()
            config_hash = toolchain.hashlib.sha256(config).hexdigest()
            manifest = json.dumps(
                [
                    {
                        "Config": f"{config_hash}.json",
                        "Layers": [layer_name],
                        "RepoTags": ["victim/image:latest"],
                    }
                ]
            ).encode()
            with tarfile.open(archive, "w") as bundle:
                for name, payload in (
                    ("manifest.json", manifest),
                    (f"{config_hash}.json", config),
                    (layer_name, layer),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
            lock = {"openclaw": {"arm64_config_digest": f"sha256:{config_hash}"}}
            with self.assertRaisesRegex(toolchain.ToolchainError, "mutable repository tags"):
                toolchain.verify_sandbox_archive(lock, archive)

            manifest = json.dumps(
                [{"Config": f"{config_hash}.json", "Layers": [layer_name]}]
            ).encode()
            with tarfile.open(archive, "w") as bundle:
                for name, payload in (
                    ("manifest.json", manifest),
                    (f"{config_hash}.json", config),
                    (layer_name, layer),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
            with self.assertRaisesRegex(toolchain.ToolchainError, "diff ID"):
                toolchain.verify_sandbox_archive(lock, archive)

    def test_verify_host_is_read_only_and_reports_blockers(self) -> None:
        lock = toolchain.load_json(_LOCK)
        args = type("Args", (), {"prefix": Path("/definitely/missing")})
        output = io.StringIO()
        with (
            mock.patch.object(toolchain, "image_present", return_value=False),
            mock.patch.object(toolchain, "model_ids", return_value=["datasheet-chat"]),
            mock.patch("sys.stdout", output),
        ):
            result = toolchain.cmd_verify_host(lock, args)
        self.assertEqual(result, 2)
        self.assertIn("BLOCKED nemoclaw", output.getvalue())
        self.assertIn("PASS local-provider", output.getvalue())
        self.assertIn("no sandbox/chat/tool/MCP/hook action was performed", output.getvalue())

    def test_install_refuses_existing_toolchain_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            target = prefix / "bin" / "openshell"
            target.parent.mkdir(parents=True)
            target.write_text("user file")
            with self.assertRaisesRegex(toolchain.ToolchainError, "refusing to overwrite"):
                toolchain.require_fresh_prefix(prefix)


if __name__ == "__main__":
    unittest.main()
