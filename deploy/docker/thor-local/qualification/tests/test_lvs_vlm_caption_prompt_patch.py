# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
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
    / "deploy/docker/thor-local/patches/patch_lvs_vlm_caption_prompt.py"
)
SPEC = importlib.util.spec_from_file_location(
    "patch_lvs_vlm_caption_prompt", PATCH_PATH
)
assert SPEC and SPEC.loader
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


class LvsVlmCaptionPromptPatchTests(unittest.TestCase):
    def test_patch_output_matches_reviewed_checkout_source(self) -> None:
        current = (
            REPO_ROOT / "services/video-summarization/src/via_server.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(current.count(patcher.NEW_BLOCK), 1)
        released = current.replace(patcher.NEW_BLOCK, patcher.OLD_BLOCK, 1)
        self.assertEqual(patcher.patch_source(released), current)

    def test_patch_preserves_caption_prompt(self) -> None:
        fixture = "def convert(query):\n    query_dict = {\n" + patcher.OLD_BLOCK + "    }\n"
        patched = patcher.patch_source(fixture)
        tree = ast.parse(patched)
        override = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == "override_vlm_prompt"
        ]
        self.assertEqual(len(override), 1)
        self.assertIn('"override_vlm_prompt": True', patched)

    def test_missing_and_duplicate_markers_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            patcher.patch_source("class Unrelated:\n    pass\n")
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            patcher.patch_source(patcher.OLD_BLOCK + patcher.OLD_BLOCK)

    def test_atomic_patch_preserves_mode_and_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "via_server.py"
            target.write_text(
                "def convert(query):\n    query_dict = {\n"
                + patcher.OLD_BLOCK
                + "    }\n",
                encoding="utf-8",
            )
            target.chmod(0o640)
            patcher.patch_file(target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertIn('"override_vlm_prompt": True', target.read_text())
            self.assertEqual(
                list(root.glob(".*.thor-vlm-caption-prompt")), []
            )

            actual = root / "actual.py"
            actual.write_text(patcher.OLD_BLOCK, encoding="utf-8")
            link = root / "link.py"
            link.symlink_to(actual.name)
            with self.assertRaisesRegex(RuntimeError, "not a regular file"):
                patcher.patch_file(link)


if __name__ == "__main__":
    unittest.main()
