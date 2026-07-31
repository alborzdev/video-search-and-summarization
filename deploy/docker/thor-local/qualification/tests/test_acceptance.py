# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUALIFICATION_DIR))

import acceptance  # noqa: E402


class AcceptancePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = acceptance.load_json(acceptance.DEFAULT_INVENTORY)
        cls.fixtures = acceptance.load_json(acceptance.DEFAULT_FIXTURES)
        cls.manifest = acceptance.load_json(acceptance.DEFAULT_PARITY_MANIFEST)
        cls.api_inventory = acceptance.load_json(acceptance.DEFAULT_API_INVENTORY)

    def validate(
        self,
        *,
        inventory: dict | None = None,
        fixtures: dict | None = None,
        manifest: dict | None = None,
        api_inventory: dict | None = None,
    ) -> dict:
        return acceptance.validate_inventory(
            inventory or copy.deepcopy(self.inventory),
            fixtures or copy.deepcopy(self.fixtures),
            manifest or copy.deepcopy(self.manifest),
            api_inventory or copy.deepcopy(self.api_inventory),
            acceptance.DEFAULT_EXPECTED_DIR,
        )

    def test_default_compiles_complete_current_plan_without_execution(self) -> None:
        plan = acceptance.compile_plan(run_id="unit-plan-001")
        expected_rest = self.api_inventory["expected_totals"][
            "declared_rest_operations"
        ]
        expected_tools = self.api_inventory["expected_totals"]["mcp_tools"]
        expected_prompts = self.api_inventory["expected_totals"]["mcp_prompts"]

        self.assertEqual(plan["mode"], "plan-only")
        self.assertFalse(plan["execution_enabled"])
        self.assertEqual(plan["network_requests_made"], 0)
        self.assertEqual(plan["processes_started"], 0)
        self.assertEqual(plan["resources_mutated"], 0)
        self.assertEqual(
            plan["coverage"]["feature_families"], len(self.manifest["features"])
        )
        self.assertEqual(
            plan["coverage"]["feature_capabilities"],
            sum(len(item["advertised"]) for item in self.manifest["features"]),
        )
        self.assertEqual(plan["coverage"]["skills"], len(self.manifest["skills"]))
        self.assertEqual(plan["coverage"]["rest_operations"], expected_rest)
        self.assertEqual(plan["coverage"]["mcp_tools"], expected_tools)
        self.assertEqual(plan["coverage"]["mcp_prompts"], expected_prompts)

    def test_vios_mcp_prompt_names_and_schemas_are_exactly_pinned(self) -> None:
        record = next(
            item
            for item in self.inventory["coverage"]["api_surfaces"]
            if item["surface_id"] == "vios-mcp"
        )
        self.assertEqual(record["expected_prompt_count"], 5)
        self.assertEqual(
            record["prompt_names"],
            [
                "picture_for_camera",
                "picture_url_for_camera",
                "sensors_count",
                "sensors_recording_status",
                "video_for_sensor",
            ],
        )
        self.assertRegex(record["prompts_sha256"], r"^[0-9a-f]{64}$")

    def test_source_has_no_execution_or_external_client_primitives(self) -> None:
        source = Path(acceptance.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue(
            {"socket", "subprocess", "requests", "docker"}.isdisjoint(imported)
        )
        self.assertNotIn("urlopen(", source)
        self.assertNotIn("os.system(", source)
        self.assertFalse(hasattr(acceptance, "execute"))

    def test_numeric_loopback_http_origins_only(self) -> None:
        self.assertEqual(
            acceptance.validate_origin("http://127.0.0.1:8100"),
            "http://127.0.0.1:8100",
        )
        self.assertEqual(
            acceptance.validate_origin("http://[::1]:8100"),
            "http://[::1]:8100",
        )
        rejected = [
            "https://127.0.0.1:8100",
            "http://localhost:8100",
            "http://0.0.0.0:8100",
            "http://192.0.2.1:8100",
            "http://user:secret@127.0.0.1:8100",
            "http://127.0.0.1:8100/path",
            "http://127.0.0.1:8100?next=http://example.test",
        ]
        for origin in rejected:
            with (
                self.subTest(origin=origin),
                self.assertRaises(acceptance.AcceptanceConfigError),
            ):
                acceptance.validate_origin(origin)

    def test_opener_disables_proxies_and_refuses_redirects_without_network(
        self,
    ) -> None:
        with mock.patch.object(
            acceptance, "ProxyHandler", wraps=acceptance.ProxyHandler
        ) as proxy_factory:
            opener = acceptance.build_safe_opener()
        proxy_factory.assert_called_once_with({})
        redirects = next(
            item for item in opener.handlers if isinstance(item, acceptance.NoRedirects)
        )
        self.assertIsNone(
            redirects.redirect_request(
                object(), object(), 302, "redirect", {}, "http://192.0.2.1/"
            )
        )

    def test_bounded_body_fails_on_one_extra_byte(self) -> None:
        self.assertEqual(acceptance.read_bounded(io.BytesIO(b"abcd"), 4), b"abcd")
        with self.assertRaisesRegex(
            acceptance.ResponseBoundError, "response_too_large"
        ):
            acceptance.read_bounded(io.BytesIO(b"abcde"), 4)
        with self.assertRaisesRegex(acceptance.ResponseBoundError, "invalid_limit"):
            acceptance.read_bounded(io.BytesIO(b""), "4")  # type: ignore[arg-type]

    def test_sse_has_independent_byte_event_and_time_bounds(self) -> None:
        body = b"data: one\n\n: heartbeat\n\ndata: two\n\n"
        self.assertEqual(
            acceptance.read_sse_bounded(
                io.BytesIO(body), max_bytes=len(body), max_events=2, max_seconds=1
            ),
            body,
        )
        with self.assertRaisesRegex(
            acceptance.ResponseBoundError, "too_many_sse_events"
        ):
            acceptance.read_sse_bounded(
                io.BytesIO(body), max_bytes=len(body), max_events=1, max_seconds=1
            )
        clock_values = iter((0.0, 2.0))
        with self.assertRaisesRegex(acceptance.ResponseBoundError, "sse_timeout"):
            acceptance.read_sse_bounded(
                io.BytesIO(b"data: one\n\n"),
                max_bytes=100,
                max_events=2,
                max_seconds=1,
                clock=lambda: next(clock_values),
            )

    def test_namespace_is_fixed_and_injection_safe(self) -> None:
        self.assertEqual(
            acceptance.build_namespace("run-000001"),
            "thor-vss-accept-run-000001",
        )
        for run_id in ("short", "../escape", "UPPER-0001", "run_000001", "run\n000001"):
            with (
                self.subTest(run_id=run_id),
                self.assertRaises(acceptance.AcceptanceConfigError),
            ):
                acceptance.build_namespace(run_id)

    def test_embedded_fixtures_have_exact_hashes_and_ffprobe_oracles(self) -> None:
        fixtures = acceptance.validate_fixture_catalog(copy.deepcopy(self.fixtures))
        self.assertEqual(
            set(fixtures), {"tiny-blue-image", "tiny-h264-aac", "tiny-hevc-aac"}
        )
        self.assertEqual(fixtures["tiny-h264-aac"]["byte_length"], 8706)
        self.assertEqual(
            [
                stream["codec_name"]
                for stream in fixtures["tiny-h264-aac"]["ffprobe_oracle"]["streams"]
            ],
            ["h264", "aac"],
        )

    def test_fixture_hash_or_oracle_drift_fails_closed(self) -> None:
        bad_hash = copy.deepcopy(self.fixtures)
        bad_hash["fixtures"][0]["sha256"] = "0" * 64
        with self.assertRaises(acceptance.AcceptanceConfigError):
            acceptance.validate_fixture_catalog(bad_hash)

        bad_probe = copy.deepcopy(self.fixtures)
        bad_probe["policy"]["ffprobe_command"].insert(1, "http://example.test/a.mp4")
        with self.assertRaises(acceptance.AcceptanceConfigError):
            acceptance.validate_fixture_catalog(bad_probe)

        no_oracle = copy.deepcopy(self.fixtures)
        del no_oracle["fixtures"][0]["ffprobe_oracle"]
        with self.assertRaises(acceptance.AcceptanceConfigError):
            acceptance.validate_fixture_catalog(no_oracle)

        false_media_type = copy.deepcopy(self.fixtures)
        false_media_type["fixtures"][0]["media_type"] = "image/png"
        with self.assertRaises(acceptance.AcceptanceConfigError):
            acceptance.validate_fixture_catalog(false_media_type)

    def test_foreign_or_unnamespaced_resource_is_rejected(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["scenarios"][0]["owned_resources"][0]["name_template"] = (
            "shared-video"
        )
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=inventory)

        unbound_create = copy.deepcopy(self.inventory)
        del unbound_create["scenarios"][0]["actions"][0]["request_name_from"]
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=unbound_create)

    def test_cleanup_must_be_exact_reverse_creation_order(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        core = inventory["scenarios"][0]
        core["cleanup"] = list(reversed(core["cleanup"]))
        core["cleanup_order"] = [item["id"] for item in core["cleanup"]]
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=inventory)

    def test_cleanup_must_use_the_exact_registered_target(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["scenarios"][0]["cleanup"][0]["exact_target_from"] = (
            "upload-agent-video.response.video_id"
        )
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=inventory)

    def test_remote_action_and_phase0_executable_class_are_rejected(self) -> None:
        remote = copy.deepcopy(self.inventory)
        remote["scenarios"][0]["actions"][0]["transport"]["origin"] = (
            "http://192.0.2.1:8100"
        )
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=remote)

        executable = copy.deepcopy(self.inventory)
        executable["policies"]["safety_classes"][0]["phase0_executable"] = True
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=executable)

    def test_feature_skill_and_api_drift_each_fail_coverage(self) -> None:
        missing_feature = copy.deepcopy(self.inventory)
        missing_feature["coverage"]["features"].pop()
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=missing_feature)

        missing_skill = copy.deepcopy(self.inventory)
        missing_skill["coverage"]["skills"].pop()
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=missing_skill)

        missing_surface = copy.deepcopy(self.inventory)
        missing_surface["coverage"]["api_surfaces"].pop()
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=missing_surface)

    def test_new_authoritative_feature_requires_new_assignment(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["features"].append(
            {
                "id": "future-feature",
                "acceptance_class": "required_local",
                "runtime_state": "not_qualified",
                "advertised": ["new behavior"],
            }
        )
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(manifest=manifest)

    def test_new_capability_in_existing_family_requires_fingerprint_review(
        self,
    ) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["features"][0]["advertised"].append("future capability")
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(manifest=manifest)

    def test_open_local_feature_requires_non_phase0_blocker(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        record = next(
            item
            for item in inventory["coverage"]["features"]
            if item["feature_id"] == "base-agent-workflow"
        )
        record["blocker_ids"] = ["phase1-execution-disabled"]
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=inventory)

    def test_every_api_matrix_remains_blocked_until_semantically_classified(
        self,
    ) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["coverage"]["api_surfaces"][0]["blocker_ids"].remove(
            "operation-classification-required"
        )
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=inventory)

        prompt_drift = copy.deepcopy(self.inventory)
        vios = next(
            item
            for item in prompt_drift["coverage"]["api_surfaces"]
            if item["surface_id"] == "vios-mcp"
        )
        vios["prompt_names"].pop()
        with self.assertRaises(acceptance.AcceptanceConfigError):
            self.validate(inventory=prompt_drift)

    def test_openclaw_staging_is_not_reported_as_an_asset_blocker(self) -> None:
        blocker_ids = {item["id"] for item in self.inventory["blockers"]}
        self.assertNotIn("openclaw-sandbox-missing", blocker_ids)
        scenario = next(
            item
            for item in self.inventory["scenarios"]
            if item["id"] == "openclaw-workflows"
        )
        self.assertEqual(
            set(scenario["blocker_ids"]),
            {
                "current-runtime-evidence-required",
                "operator-lifecycle-approval",
                "phase1-execution-disabled",
            },
        )

    def test_default_cli_failure_is_redacted_and_plan_only(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = acceptance.main(["--run-id", "../../unsafe"])
        report = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(report["error"], "configuration_error")
        self.assertFalse(report["execution_enabled"])
        self.assertNotIn("unsafe", json.dumps(report))

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaises(acceptance.AcceptanceConfigError):
                acceptance.load_json(path)


class AcceptanceLedgerTests(unittest.TestCase):
    def append(self, path: Path, **overrides: object) -> dict:
        values: dict[str, object] = {
            "run_id": "ledger-000001",
            "namespace": "thor-vss-accept-ledger-000001",
            "event": "run-started",
            "scenario_id": "core-agent-workflows",
            "action_id": "begin-run",
            "recorded_at": "2026-07-31T12:00:00Z",
        }
        values.update(overrides)
        return acceptance.append_ledger_event(path, **values)  # type: ignore[arg-type]

    def test_ledger_is_mode_0600_append_only_and_hash_chained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acceptance.jsonl"
            first = self.append(path)
            second = self.append(
                path,
                event="created",
                action_id="upload-agent-video",
                resource_id="agent-video",
                target_sha256="a" * 64,
                recorded_at="2026-07-31T12:00:01Z",
            )
            raw = path.read_bytes()

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(first["sequence"], 1)
            self.assertEqual(second["sequence"], 2)
            self.assertEqual(second["previous_sha256"], first["record_sha256"])
            self.assertEqual(
                acceptance._validate_ledger_records(raw), (2, second["record_sha256"])
            )

    def test_ledger_refuses_wrong_mode_symlink_hardlink_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "acceptance.jsonl"
            self.append(path)
            path.chmod(0o644)
            with self.assertRaisesRegex(acceptance.LedgerError, "unsafe_ledger_file"):
                self.append(path)

            path.chmod(0o600)
            hardlink = root / "hardlink.jsonl"
            os.link(path, hardlink)
            with self.assertRaisesRegex(acceptance.LedgerError, "unsafe_ledger_file"):
                self.append(path)
            hardlink.unlink()

            symlink = root / "symlink.jsonl"
            symlink.symlink_to(path)
            with self.assertRaisesRegex(acceptance.LedgerError, "unsafe_ledger_path"):
                self.append(symlink)

            path.write_bytes(
                path.read_bytes().replace(b'"sequence":1', b'"sequence":9')
            )
            with self.assertRaisesRegex(acceptance.LedgerError, "invalid_ledger"):
                self.append(path)

    def test_ledger_refuses_unbound_resources_and_control_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acceptance.jsonl"
            with self.assertRaisesRegex(acceptance.LedgerError, "invalid_record"):
                self.append(path, event="created")
            with self.assertRaisesRegex(acceptance.LedgerError, "invalid_record"):
                self.append(path, scenario_id="core\nagent")
            with self.assertRaisesRegex(acceptance.LedgerError, "invalid_record"):
                self.append(path, namespace="thor-vss-accept-someone-else")

    def test_ledger_enforces_exact_target_and_lifo_cleanup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acceptance.jsonl"
            self.append(path)
            self.append(
                path,
                event="created",
                action_id="create-first",
                resource_id="first-resource",
                target_sha256="a" * 64,
                recorded_at="2026-07-31T12:00:01Z",
            )
            self.append(
                path,
                event="created",
                action_id="create-second",
                resource_id="second-resource",
                target_sha256="b" * 64,
                recorded_at="2026-07-31T12:00:02Z",
            )
            before = path.read_bytes()
            with self.assertRaisesRegex(acceptance.LedgerError, "invalid_ledger"):
                self.append(
                    path,
                    event="cleanup-started",
                    action_id="delete-first",
                    resource_id="first-resource",
                    target_sha256="a" * 64,
                    recorded_at="2026-07-31T12:00:03Z",
                )
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(acceptance.LedgerError, "invalid_ledger"):
                self.append(
                    path,
                    event="updated",
                    action_id="update-second",
                    resource_id="second-resource",
                    target_sha256="c" * 64,
                    recorded_at="2026-07-31T12:00:03Z",
                )
            self.assertEqual(path.read_bytes(), before)

            self.append(
                path,
                event="cleanup-started",
                action_id="delete-second",
                resource_id="second-resource",
                target_sha256="b" * 64,
                recorded_at="2026-07-31T12:00:03Z",
            )
            self.append(
                path,
                event="cleanup-succeeded",
                action_id="delete-second",
                resource_id="second-resource",
                target_sha256="b" * 64,
                recorded_at="2026-07-31T12:00:04Z",
            )
            self.append(
                path,
                event="cleanup-started",
                action_id="delete-first",
                resource_id="first-resource",
                target_sha256="a" * 64,
                recorded_at="2026-07-31T12:00:05Z",
            )
            self.append(
                path,
                event="cleanup-succeeded",
                action_id="delete-first",
                resource_id="first-resource",
                target_sha256="a" * 64,
                recorded_at="2026-07-31T12:00:06Z",
            )
            final = self.append(
                path,
                event="run-finished",
                action_id="finish-run",
                recorded_at="2026-07-31T12:00:07Z",
            )
            self.assertEqual(final["sequence"], 8)


if __name__ == "__main__":
    unittest.main()
