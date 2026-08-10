# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


AUDIO_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = AUDIO_DIR.parents[3]
INSTALLER = REPO_ROOT / "deploy/docker/thor-local/vios-codecs/install-codec-bundle.sh"
LOCK = AUDIO_DIR / "codec-bundle.lock.json"
CANONICAL_BUNDLE = REPO_ROOT / "deploy/docker/thor-local/vios-codecs/bundle"


class CodecInstallerAdversarialTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> tuple[Path, dict]:
        bundle = root / "bundle"
        bundle.mkdir()
        document = json.loads(LOCK.read_text(encoding="utf-8"))
        shutil.copy2(LOCK, bundle / "manifest.json")
        for entry in document["packages"]:
            (bundle / entry["filename"]).write_bytes(b"test-placeholder")
        return bundle, document

    def run_verifier(
        self, bundle: Path, lock: Path = LOCK
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALLER), str(bundle), "/", "verify-only", str(lock)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_shell_verifier_rejects_duplicate_traversal_unlisted_and_missing_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, original = self.build_fixture(root)

            manifest_path = bundle / "manifest.json"
            duplicate = json.loads(json.dumps(original))
            duplicate["packages"][1]["filename"] = duplicate["packages"][0]["filename"]
            duplicate["packages"][1]["sha256"] = duplicate["packages"][0]["sha256"]
            manifest_path.write_text(json.dumps(duplicate, indent=2, sort_keys=True) + "\n")
            result = self.run_verifier(bundle)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match the canonical lock", result.stderr)

            traversal = json.loads(json.dumps(original))
            traversal["packages"][0]["filename"] = "../escaped_1.0_arm64.deb"
            manifest_path.write_text(json.dumps(traversal, indent=2, sort_keys=True) + "\n")
            result = self.run_verifier(bundle)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match the canonical lock", result.stderr)

            shutil.copy2(LOCK, manifest_path)
            source = bundle / original["packages"][0]["filename"]
            extra = bundle / "unexpected_1.0_arm64.deb"
            shutil.copy2(source, extra)
            result = self.run_verifier(bundle)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 63 ARM64 archives, found 64", result.stderr)
            extra.unlink()

            source.unlink()
            result = self.run_verifier(bundle)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 63 ARM64 archives, found 62", result.stderr)

            tampered_lock = root / "codec-bundle.lock.json"
            tampered_lock.write_text(LOCK.read_text() + "\n")
            result = self.run_verifier(bundle, tampered_lock)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lock digest is not trusted", result.stderr)

    def test_staged_canonical_bundle_passes_when_available(self):
        if not (CANONICAL_BUNDLE / "manifest.json").is_file():
            self.skipTest("ignored canonical bundle is not staged on this host")
        result = self.run_verifier(CANONICAL_BUNDLE)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
