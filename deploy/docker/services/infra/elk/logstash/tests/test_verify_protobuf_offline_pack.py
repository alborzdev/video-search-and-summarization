# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "verify-protobuf-offline-pack.py"
SPEC = importlib.util.spec_from_file_location("verify_protobuf_offline_pack", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OfflinePackVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.pack = self.directory / "pack.zip"
        self.checksum = self.directory / "pack.zip.sha256"
        self.expected_checksum = self.directory / "pack.zip.expected.sha256"

    def write_pack(self, names: list[str]) -> None:
        with zipfile.ZipFile(self.pack, "w") as archive:
            for name in names:
                archive.writestr(f"vendor/cache/{name}", b"fixture")
        digest = hashlib.sha256(self.pack.read_bytes()).hexdigest()
        self.checksum.write_text(f"{digest}  {self.pack.name}\n", encoding="utf-8")
        self.expected_checksum.write_text(
            f"{digest}  {self.pack.name}\n", encoding="utf-8"
        )

    def test_accepts_exact_pinned_dependency_set(self) -> None:
        self.write_pack(list(MODULE.EXPECTED_GEMS.values()))
        MODULE.verify(self.pack, self.checksum, self.expected_checksum)

    def test_rejects_expected_digest_drift(self) -> None:
        self.write_pack(list(MODULE.EXPECTED_GEMS.values()))
        self.expected_checksum.write_text(
            f"{'0' * 64}  {self.pack.name}\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "does not match expected checksum lock"):
            MODULE.verify(self.pack, self.checksum, self.expected_checksum)

    def test_rejects_dependency_version_drift(self) -> None:
        names = list(MODULE.EXPECTED_GEMS.values())
        names[names.index("google-protobuf-3.23.4-java.gem")] = (
            "google-protobuf-4.0.0-java.gem"
        )
        self.write_pack(names)
        with self.assertRaisesRegex(ValueError, "unexpected google-protobuf"):
            MODULE.verify(self.pack, self.checksum)

    def test_rejects_checksum_mismatch(self) -> None:
        self.write_pack(list(MODULE.EXPECTED_GEMS.values()))
        self.checksum.write_text(f"{'0' * 64}  {self.pack.name}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            MODULE.verify(self.pack, self.checksum)

    def test_rejects_path_traversal(self) -> None:
        with zipfile.ZipFile(self.pack, "w") as archive:
            archive.writestr("../escape.gem", b"fixture")
            for name in MODULE.EXPECTED_GEMS.values():
                archive.writestr(f"vendor/cache/{name}", b"fixture")
        digest = hashlib.sha256(self.pack.read_bytes()).hexdigest()
        self.checksum.write_text(f"{digest}  {self.pack.name}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe archive member"):
            MODULE.verify(self.pack, self.checksum)


if __name__ == "__main__":
    unittest.main()
