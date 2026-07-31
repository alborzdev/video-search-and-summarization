#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Thor-local domain-pack contract."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_DIR = REPO_ROOT / "deploy/docker/thor-local/domain-packs"
MODULE_PATH = PACK_DIR / "domain_pack.py"
SPEC = importlib.util.spec_from_file_location("thor_domain_pack", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
domain_pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(domain_pack)


class DomainPackTests(unittest.TestCase):
    def test_all_versioned_packs_validate(self) -> None:
        packs = domain_pack.load_all(PACK_DIR)
        self.assertEqual(
            {pack["id"] for pack in packs},
            {"general", "industrial-safety", "retail", "site-security"},
        )
        for pack in packs:
            self.assertGreaterEqual(len(pack["demo_questions"]), 1)
            self.assertGreaterEqual(len(pack["search_prompts"]), 1)
            for rule in pack["verification_rules"]:
                self.assertIn(rule["vlm_params"]["num_frames"], range(1, 5))

    def test_rejects_unsafe_or_unsupported_data(self) -> None:
        raw = json.loads((PACK_DIR / "general.json").read_text(encoding="utf-8"))
        raw["verification_rules"][0]["vlm_params"]["num_frames"] = 5
        with self.assertRaisesRegex(domain_pack.DomainPackError, "integer from 1 to 4"):
            domain_pack.validate_pack(raw, Path("general.json"))

        raw = json.loads((PACK_DIR / "general.json").read_text(encoding="utf-8"))
        raw["branding"]["title"] = "unsafe\nvalue"
        with self.assertRaisesRegex(domain_pack.DomainPackError, "single line"):
            domain_pack.validate_pack(raw, Path("general.json"))

    def test_alert_bridge_must_be_loopback(self) -> None:
        self.assertEqual(
            domain_pack._validate_local_api_url("http://127.0.0.1:9080/api/v1"),
            "http://127.0.0.1:9080/api/v1",
        )
        with self.assertRaisesRegex(domain_pack.DomainPackError, "non-loopback"):
            domain_pack._validate_local_api_url("http://example.com/api/v1")

    def test_conflicting_operator_rule_is_preserved(self) -> None:
        desired_pack = domain_pack.load_pack(PACK_DIR, "general")
        operator_rule = dict(desired_pack["verification_rules"][0])
        operator_rule["prompt"] = "Operator-authored prompt"
        calls: list[tuple[str, str]] = []

        def fake_request(url: str, method: str = "GET", body=None):  # noqa: ANN001, ANN202
            calls.append((method, url))
            return {"status": "success", "configs": [operator_rule]}

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(domain_pack, "_api_request", side_effect=fake_request),
        ):
            state_path = Path(directory) / "state.json"
            self.assertEqual(
                domain_pack.apply_rules(
                    desired_pack, "http://127.0.0.1:9080/api/v1", state_path
                ),
                (0, 0, 0),
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["managed_rules"], {})
            self.assertEqual(state["current_pack"], "general")
            self.assertEqual(
                calls, [("GET", "http://127.0.0.1:9080/api/v1/verification/config")]
            )
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)

    def test_exact_rule_is_adopted_then_updated_idempotently(self) -> None:
        industrial = domain_pack.load_pack(PACK_DIR, "industrial-safety")
        general = domain_pack.load_pack(PACK_DIR, "general")
        current_rule = industrial["verification_rules"][0]

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            def adopt_request(url: str, method: str = "GET", body=None):  # noqa: ANN001, ANN202
                self.assertEqual(method, "GET")
                return {"status": "success", "configs": [current_rule]}

            with patch.object(domain_pack, "_api_request", side_effect=adopt_request):
                self.assertEqual(
                    domain_pack.apply_rules(
                        industrial, "http://localhost:9080/api/v1", state_path
                    ),
                    (0, 0, 1),
                )

            desired_general = general["verification_rules"][0]

            def update_request(url: str, method: str = "GET", body=None):  # noqa: ANN001, ANN202
                if method == "GET":
                    return {"status": "success", "configs": [current_rule]}
                self.assertEqual(method, "PUT")
                self.assertTrue(url.endswith("/fov%20count%20violation"))
                return {"alert_type": "fov count violation", **body}

            with patch.object(domain_pack, "_api_request", side_effect=update_request):
                self.assertEqual(
                    domain_pack.apply_rules(
                        general, "http://localhost:9080/api/v1", state_path
                    ),
                    (0, 1, 0),
                )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["current_pack"], "general")
            self.assertEqual(
                state["managed_rules"]["fov count violation"]["applied"],
                desired_general,
            )


if __name__ == "__main__":
    unittest.main()
