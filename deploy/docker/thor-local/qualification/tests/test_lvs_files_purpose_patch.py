# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[5]
PATCH_PATH = (
    REPO_ROOT
    / "deploy/docker/thor-local/patches/patch_lvs_files_purpose.py"
)
SPEC = importlib.util.spec_from_file_location("patch_lvs_files_purpose", PATCH_PATH)
assert SPEC and SPEC.loader
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


def fixture_source(block: str) -> str:
    return (
        "class Fixture:\n    def build(self):\n"
        + block
        + "            return None\n"
    )


class LvsFilesPurposePatchTests(unittest.TestCase):
    def test_exact_ga_block_is_replaced_with_upstream_main_block(self) -> None:
        source = fixture_source(patcher.OLD_BLOCK)
        patched = patcher.patch_source(source)
        self.assertEqual(patched, fixture_source(patcher.NEW_BLOCK))
        self.assertNotIn('if purpose != "vision"', patched)
        self.assertIn("Purpose,", patched)
        self.assertIn("Must be 'vision'", patched)
        ast.parse(patched)

    def test_missing_or_duplicate_marker_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            patcher.patch_source("class Unrelated:\n    pass\n")
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            patcher.patch_source(
                fixture_source(patcher.OLD_BLOCK + patcher.OLD_BLOCK)
            )

    def test_file_patch_is_atomic_and_preserves_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "via_server.py"
            target.write_text(fixture_source(patcher.OLD_BLOCK), encoding="utf-8")
            target.chmod(0o640)
            patcher.patch_file(target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertEqual(target.read_text(), fixture_source(patcher.NEW_BLOCK))
            self.assertEqual(list(target.parent.glob(".*.thor-purpose")), [])

    def test_symlink_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            actual = root / "actual.py"
            actual.write_text(fixture_source(patcher.OLD_BLOCK), encoding="utf-8")
            link = root / "via_server.py"
            link.symlink_to(actual.name)
            with self.assertRaisesRegex(RuntimeError, "not a regular file"):
                patcher.patch_file(link)


if __name__ == "__main__":
    unittest.main()
