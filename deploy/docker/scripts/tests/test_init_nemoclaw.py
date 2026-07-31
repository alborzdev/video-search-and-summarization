# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import unittest
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "nemoclaw" / "init_nemoclaw.sh"


class InitNemoClawArgumentsTest(unittest.TestCase):
    def run_script(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        clean_env = os.environ.copy()
        clean_env.pop("NEMOCLAW_PROVIDER", None)
        clean_env.pop("NEMOCLAW_ENDPOINT_URL", None)
        clean_env.pop("COMPATIBLE_API_KEY", None)
        if env:
            clean_env.update(env)
        return subprocess.run(
            ["bash", str(_SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=clean_env,
            timeout=10,
            check=False,
        )

    def test_help_does_not_require_provider(self) -> None:
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--provider NAME", result.stdout)

    def test_provider_flag_is_accepted_before_help(self) -> None:
        result = self.run_script("--provider", "custom", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_provider_fails_before_install(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("NEMOCLAW_PROVIDER is required", result.stdout)

    def test_unknown_provider_fails_before_install(self) -> None:
        result = self.run_script("--provider", "other")
        self.assertEqual(result.returncode, 1)
        self.assertIn("is invalid", result.stdout)

    def test_custom_provider_rejects_non_http_endpoint(self) -> None:
        result = self.run_script(
            "--provider",
            "custom",
            "--endpoint-url",
            "host.openshell.internal:8000/v1",
            "--compatible-api-key",
            "EMPTY",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be a valid http:// or https:// URL", result.stdout)

    def test_custom_provider_rejects_http_url_without_host(self) -> None:
        result = self.run_script(
            "--provider",
            "custom",
            "--endpoint-url",
            "http://",
            "--compatible-api-key",
            "EMPTY",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be a valid http:// or https:// URL", result.stdout)

    def test_custom_provider_rejects_invalid_port(self) -> None:
        result = self.run_script(
            "--provider",
            "custom",
            "--endpoint-url",
            "http://host.openshell.internal:not-a-port/v1",
            "--compatible-api-key",
            "EMPTY",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be a valid http:// or https:// URL", result.stdout)


if __name__ == "__main__":
    unittest.main()
