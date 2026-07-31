# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from pathlib import Path


_REPO = Path(__file__).resolve().parents[4]
_PLUGIN = _REPO / ".openclaw"


class OpenClawPackageTest(unittest.TestCase):
    def test_package_stages_every_current_vss_skill(self) -> None:
        package = json.loads((_PLUGIN / "package.json").read_text(encoding="utf-8"))
        plugin = json.loads((_PLUGIN / "openclaw.plugin.json").read_text(encoding="utf-8"))
        skill_names = sorted(path.parent.name for path in (_REPO / "skills").glob("*/SKILL.md"))

        self.assertGreater(len(skill_names), 0)
        self.assertIn("skills/", package["files"])
        self.assertIn("cp -r ../skills skills", package["scripts"]["prepack"])
        self.assertIn("./skills", plugin["skills"])

        readme = (_PLUGIN / "README.md").read_text(encoding="utf-8")
        for skill_name in skill_names:
            with self.subTest(skill=skill_name):
                self.assertIn(skill_name, readme)

    def test_workspace_bootstrap_only_names_existing_skills(self) -> None:
        bootstrap = (_PLUGIN / "workspace" / "BOOTSTRAP.md").read_text(encoding="utf-8")
        self.assertNotIn("`vss-prerequisites`", bootstrap)
        self.assertNotIn("`ngc` skill", bootstrap)
        self.assertIn("`vss-deploy-profile`", bootstrap)

    def test_nemoclaw_overlay_and_policy_cover_local_orchestrator(self) -> None:
        overlay = (_PLUGIN / "workspace" / "_nemoclaw" / "TOOLS.md").read_text(
            encoding="utf-8"
        )
        policy = (_REPO / "assets" / "vss_nemoclaw_policy.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("http://host.openshell.internal:9988/mcp", overlay)
        self.assertIn("host: host.openshell.internal", policy)
        for port in (8000, 9988, 18789):
            with self.subTest(port=port):
                self.assertIn(f"port: {port}", policy)


if __name__ == "__main__":
    unittest.main()
