#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = ROOT / "vios-mcp"
SPEC = importlib.util.spec_from_file_location("vios_mcp_wheels", TOOL_DIR / "verify_wheelhouse.py")
assert SPEC is not None and SPEC.loader is not None
WHEELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WHEELS)


class ViosMcpWheelhouseTests(unittest.TestCase):
    def make_contract(self, root: Path, *, unsafe_member: bool = False) -> tuple[Path, Path, Path]:
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        wheel = wheelhouse / "demo_pkg-1.2.3-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "demo_pkg-1.2.3.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.2.3\n",
            )
            if unsafe_member:
                archive.writestr("../escape", "no")
        lock = root / "lock.json"
        lock.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "platform": "linux-aarch64",
                    "python": "cp312",
                    "files": [
                        {
                            "filename": wheel.name,
                            "size": wheel.stat().st_size,
                            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        requirements = root / "requirements.txt"
        requirements.write_text("demo-pkg==1.2.3\n", encoding="utf-8")
        return lock, requirements, wheelhouse

    def test_checked_in_contract_has_exact_dependency_closure(self) -> None:
        locked = WHEELS.load_lock(TOOL_DIR / "wheels-linux-aarch64.lock.json")
        requirements = WHEELS.load_requirements(TOOL_DIR / "requirements-linux-aarch64.txt")
        self.assertEqual(len(locked), 31)
        self.assertEqual(len(requirements), 31)
        self.assertEqual(requirements["mcp"], "1.23.0")
        self.assertEqual(requirements["python-multipart"], "0.0.22")

    def test_accepts_exact_safe_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, requirements, wheelhouse = self.make_contract(Path(temporary))
            self.assertEqual(WHEELS.verify(lock, requirements, wheelhouse), 1)

    def test_rejects_hash_and_membership_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock, requirements, wheelhouse = self.make_contract(root)
            (wheelhouse / "demo_pkg-1.2.3-py3-none-any.whl").write_bytes(b"changed")
            with self.assertRaisesRegex(WHEELS.VerificationError, "size drift"):
                WHEELS.verify(lock, requirements, wheelhouse)
            (wheelhouse / "extra.whl").write_bytes(b"extra")
            with self.assertRaisesRegex(WHEELS.VerificationError, "membership drift"):
                WHEELS.verify(lock, requirements, wheelhouse)

    def test_rejects_unsafe_archive_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, requirements, wheelhouse = self.make_contract(
                Path(temporary), unsafe_member=True
            )
            with self.assertRaisesRegex(WHEELS.VerificationError, "unsafe archive member"):
                WHEELS.verify(lock, requirements, wheelhouse)


if __name__ == "__main__":
    unittest.main()
