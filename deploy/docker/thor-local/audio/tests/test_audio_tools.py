# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


AUDIO_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


codec_bundle = load_module("thor_codec_bundle", AUDIO_DIR / "codec_bundle.py")
omni_snapshot = load_module("thor_omni_snapshot", AUDIO_DIR / "omni_snapshot.py")


class CodecSourceTests(unittest.TestCase):
    def test_vss_321_arm64_package_set_is_exact(self):
        packages = codec_bundle.source_packages()
        self.assertEqual(59, len(packages))
        self.assertEqual(59, len(set(packages)))
        self.assertEqual(codec_bundle.PACKAGE_SET_SHA256, codec_bundle.package_set_digest(packages))
        self.assertIn("gstreamer1.0-libav", packages)
        self.assertIn("libavcodec60", packages)
        self.assertIn("libmp3lame0", packages)


class CodecFrozenManifestTests(unittest.TestCase):
    packages = ("alpha", "beta")

    def manifest(self) -> dict:
        entries = []
        for package in self.packages:
            filename = f"{package}_1.0_arm64.deb"
            entries.append(
                {
                    "architecture": "arm64",
                    "filename": filename,
                    "package": package,
                    "sha256": "a" * 64,
                    "size": 1,
                    "url": f"https://ports.ubuntu.com/ubuntu-ports/pool/test/{filename}",
                    "version": "1.0",
                }
            )
        return {
            "schema_version": codec_bundle.SCHEMA_VERSION,
            "source": "VSS v3.2.1 services/rtvi/rt-embed/src/scripts/install_codecs_nonroot.sh",
            "source_installer_sha256": codec_bundle.SOURCE_INSTALLER_SHA256,
            "package_set_sha256": codec_bundle.package_set_digest(list(self.packages)),
            "architecture": "arm64",
            "package_count": len(entries),
            "packages": entries,
        }

    def contract(self):
        return (
            mock.patch.object(codec_bundle, "PACKAGE_COUNT", len(self.packages)),
            mock.patch.object(
                codec_bundle,
                "PACKAGE_SET_SHA256",
                codec_bundle.package_set_digest(list(self.packages)),
            ),
        )

    def test_manifest_rejects_duplicate_and_traversing_archive_names(self):
        count_patch, digest_patch = self.contract()
        with count_patch, digest_patch:
            duplicate = self.manifest()
            duplicate["packages"][1]["filename"] = duplicate["packages"][0]["filename"]
            duplicate["packages"][1]["package"] = duplicate["packages"][0]["package"]
            with self.assertRaisesRegex(codec_bundle.BundleError, "duplicate archive"):
                codec_bundle.validate_manifest(duplicate)

            traversal = self.manifest()
            traversal["packages"][0]["filename"] = "../alpha_1.0_arm64.deb"
            with self.assertRaisesRegex(codec_bundle.BundleError, "unsafe archive"):
                codec_bundle.validate_manifest(traversal)

    def test_frozen_verifier_requires_exact_regular_file_inventory(self):
        count_patch, digest_patch = self.contract()
        with tempfile.TemporaryDirectory() as directory, count_patch, digest_patch:
            bundle = Path(directory)
            document = self.manifest()
            payload = json.dumps(document, sort_keys=True) + "\n"
            (bundle / "manifest.json").write_text(payload, encoding="utf-8")
            lock_path = bundle.parent / "codec-bundle.lock.json"
            lock_path.write_text(payload, encoding="utf-8")
            for entry in document["packages"]:
                (bundle / entry["filename"]).write_bytes(b"x")
            with mock.patch.object(codec_bundle, "build_manifest", return_value=document):
                self.assertEqual(
                    codec_bundle.verify_bundle(bundle, frozen=True, lock_path=lock_path),
                    document,
                )
                extra = bundle / "unlisted_arm64.deb"
                extra.write_bytes(b"x")
                with self.assertRaisesRegex(codec_bundle.BundleError, "inventory mismatch"):
                    codec_bundle.verify_bundle(bundle, frozen=True, lock_path=lock_path)
                extra.unlink()

                missing = bundle / document["packages"][0]["filename"]
                missing.unlink()
                with self.assertRaisesRegex(codec_bundle.BundleError, "inventory mismatch"):
                    codec_bundle.verify_bundle(bundle, frozen=True, lock_path=lock_path)

    def test_frozen_verifier_rejects_linked_or_directory_entries(self):
        count_patch, digest_patch = self.contract()
        with tempfile.TemporaryDirectory() as directory, count_patch, digest_patch:
            bundle = Path(directory)
            document = self.manifest()
            payload = json.dumps(document, sort_keys=True) + "\n"
            (bundle / "manifest.json").write_text(payload, encoding="utf-8")
            lock_path = bundle.parent / "codec-bundle.lock.json"
            lock_path.write_text(payload, encoding="utf-8")
            for entry in document["packages"]:
                (bundle / entry["filename"]).write_bytes(b"x")
            (bundle / "unexpected-directory").mkdir()
            with self.assertRaisesRegex(codec_bundle.BundleError, "non-regular"):
                codec_bundle.verify_bundle(bundle, frozen=True, lock_path=lock_path)

    def test_frozen_verifier_rejects_manifest_not_equal_to_canonical_lock(self):
        count_patch, digest_patch = self.contract()
        with tempfile.TemporaryDirectory() as directory, count_patch, digest_patch:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            document = self.manifest()
            payload = json.dumps(document, sort_keys=True) + "\n"
            (bundle / "manifest.json").write_text(payload, encoding="utf-8")
            lock_path = root / "codec-bundle.lock.json"
            lock_path.write_text(payload, encoding="utf-8")
            document["packages"][0]["sha256"] = "b" * 64
            (bundle / "manifest.json").write_text(
                json.dumps(document, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(codec_bundle.BundleError, "canonical lock"):
                codec_bundle.verify_bundle(bundle, frozen=True, lock_path=lock_path)

    def test_stage_refuses_automatic_canonical_lock_refresh(self):
        count_patch, digest_patch = self.contract()
        with tempfile.TemporaryDirectory() as directory, count_patch, digest_patch:
            root = Path(directory)
            canonical = self.manifest()
            lock_path = root / "codec-bundle.lock.json"
            lock_path.write_text(json.dumps(canonical, sort_keys=True) + "\n")
            drifted = json.loads(json.dumps(canonical))
            drifted["packages"][0]["version"] = "1.1"
            with (
                mock.patch.object(codec_bundle, "source_packages", return_value=list(self.packages)),
                mock.patch.object(
                    codec_bundle,
                    "resolve_and_download",
                    return_value=[entry["url"] for entry in canonical["packages"]],
                ),
                mock.patch.object(codec_bundle, "build_manifest", return_value=drifted),
                self.assertRaisesRegex(codec_bundle.BundleError, "refusing an automatic"),
            ):
                codec_bundle.stage_bundle(
                    root / "bundle",
                    retries=1,
                    timeout=1,
                    lock_path=lock_path,
                )


class OmniSnapshotTests(unittest.TestCase):
    repository = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8"
    revision = "1" * 40

    def make_snapshot(self, root: Path) -> None:
        (root / "config.json").write_text(
            json.dumps({"architectures": ["NemotronH_Nano_VL_V2"], "model_type": "nemotron_h"}) + "\n",
            encoding="utf-8",
        )
        (root / "tokenizer_config.json").write_text("{}\n", encoding="utf-8")
        (root / "modeling_nemotron_h.py").write_text("# pinned remote implementation\n", encoding="utf-8")
        (root / "model-00001-of-00001.safetensors").write_bytes(b"test-only-weight-bytes")

    def test_manifest_detects_any_snapshot_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_snapshot(root)
            manifest = omni_snapshot.build_manifest(root.resolve(), self.repository, self.revision)
            manifest_path = root.parent / f"{root.name}.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            verified = omni_snapshot.verify_manifest(root.resolve(), manifest_path.resolve())
            self.assertEqual(self.repository, verified["repository"])
            self.assertEqual(self.revision, verified["revision"])

            (root / "modeling_nemotron_h.py").write_text("# changed\n", encoding="utf-8")
            with self.assertRaises(omni_snapshot.SnapshotError):
                omni_snapshot.verify_manifest(root.resolve(), manifest_path.resolve())

    def test_symlink_and_unpinned_revision_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_snapshot(root)
            (root / "escaped").symlink_to("/etc/passwd")
            with self.assertRaises(omni_snapshot.SnapshotError):
                omni_snapshot.build_manifest(root.resolve(), self.repository, self.revision)
            (root / "escaped").unlink()
            with self.assertRaises(omni_snapshot.SnapshotError):
                omni_snapshot.build_manifest(root.resolve(), self.repository, "main")

    def test_non_omni_repository_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_snapshot(root)
            with self.assertRaises(omni_snapshot.SnapshotError):
                omni_snapshot.build_manifest(root.resolve(), "Qwen/Qwen3-VL-8B-Instruct", self.revision)

    def test_distinct_ga0420_repository_is_supported_without_aliasing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_snapshot(root)
            repository = "nvidia/Nemotron-Nano-V3-Omni-GA0420-FP8"
            manifest = omni_snapshot.build_manifest(root.resolve(), repository, self.revision)
            self.assertEqual(repository, manifest["repository"])

    def test_canonical_huggingface_links_are_hashed_without_materializing(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "models--nvidia--Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8"
            root = cache / "snapshots" / self.revision
            blobs = cache / "blobs"
            root.mkdir(parents=True)
            blobs.mkdir()
            materialized = Path(directory) / "materialized"
            materialized.mkdir()
            self.make_snapshot(materialized)
            for source in materialized.iterdir():
                data = source.read_bytes()
                digest = __import__("hashlib").sha256(data).hexdigest()
                (blobs / digest).write_bytes(data)
                (root / source.name).symlink_to(f"../../blobs/{digest}")
            manifest = omni_snapshot.build_manifest(root.resolve(), self.repository, self.revision)
            self.assertTrue(all(entry.get("type") == "symlink" for entry in manifest["files"]))
            self.assertEqual(
                manifest,
                omni_snapshot.build_manifest(root.resolve(), self.repository, self.revision),
            )


if __name__ == "__main__":
    unittest.main()
