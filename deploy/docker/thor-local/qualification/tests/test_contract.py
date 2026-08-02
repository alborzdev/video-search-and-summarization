#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = QUALIFICATION_DIR.parents[3]
sys.path.insert(0, str(QUALIFICATION_DIR))

import contract  # noqa: E402
import qualify  # noqa: E402


class ContractNormalizationTests(unittest.TestCase):
    def test_openapi_prose_does_not_change_contract_hash(self) -> None:
        first = {
            "openapi": "3.0.0",
            "paths": {
                "/items": {
                    "post": {
                        "summary": "First wording",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "required": ["name"]}
                                }
                            }
                        },
                        "responses": {"200": {"description": "okay"}},
                    }
                }
            },
        }
        second = json.loads(json.dumps(first))
        second["paths"]["/items"]["post"]["summary"] = "Different wording"
        second["paths"]["/items"]["post"]["responses"]["200"]["description"] = (
            "Changed prose"
        )
        self.assertEqual(
            contract.normalize_openapi_document(first),
            contract.normalize_openapi_document(second),
        )

    def test_openapi_validation_change_changes_contract_hash(self) -> None:
        first = {
            "paths": {
                "/items": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "string", "maxLength": 8}
                                }
                            }
                        },
                        "responses": {"200": {}},
                    }
                }
            }
        }
        second = json.loads(json.dumps(first))
        second["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]["maxLength"] = 9
        self.assertNotEqual(
            contract.normalize_openapi_document(first),
            contract.normalize_openapi_document(second),
        )

    def test_path_prefix_and_parameter_normalization_are_separate(self) -> None:
        document = {
            "paths": {"/v1/file/{sensorId}": {"get": {"responses": {"200": {}}}}}
        }
        operations, _ = contract.normalize_openapi_document(
            document, path_prefix="/vst/api"
        )
        self.assertEqual(operations[0]["path"], "/vst/api/v1/file/{sensorId}")
        self.assertEqual(
            contract.canonical_route(operations[0]["path"]), "/vst/api/v1/file/{}"
        )

    def test_manifest_diff_reports_route_drift(self) -> None:
        expected = contract.build_rest_manifest(
            "sample",
            [
                {
                    "method": "GET",
                    "path": "/old",
                    "operation_id": None,
                    "schema_hash": None,
                }
            ],
            source_files=[],
        )
        actual = contract.build_rest_manifest(
            "sample",
            [
                {
                    "method": "GET",
                    "path": "/new",
                    "operation_id": None,
                    "schema_hash": None,
                }
            ],
            source_files=[],
        )
        difference = "\n".join(contract.compare_manifest(expected, actual))
        self.assertIn("missing operations: GET /old", difference)
        self.assertIn("extra operations: GET /new", difference)

    def test_fastmcp_extractor_pins_names_and_input_signatures(self) -> None:
        first = """
mcp = object()

@mcp.tool()
async def lookup(sensor_id: str, refresh: bool = False):
    pass

@mcp.prompt(name="sensor_help", title="Sensor help")
def help_prompt():
    pass
"""
        second = first.replace("refresh: bool = False", "refresh: bool = True")
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.py"
            second_path = Path(directory) / "second.py"
            first_path.write_text(first, encoding="utf-8")
            second_path.write_text(second, encoding="utf-8")
            first_tools, first_prompts = contract.extract_fastmcp_declarations(
                first_path
            )
            second_tools, second_prompts = contract.extract_fastmcp_declarations(
                second_path
            )
        self.assertEqual([item["name"] for item in first_tools], ["lookup"])
        self.assertEqual([item["name"] for item in first_prompts], ["sensor_help"])
        self.assertNotEqual(
            first_tools[0]["input_schema_hash"],
            second_tools[0]["input_schema_hash"],
        )
        self.assertEqual(first_prompts, second_prompts)

    def test_manifest_diff_reports_prompt_drift(self) -> None:
        expected = contract.build_mcp_manifest(
            "sample",
            [],
            prompts=[{"name": "old", "input_schema_hash": "a"}],
            source_files=[],
        )
        actual = contract.build_mcp_manifest(
            "sample",
            [],
            prompts=[{"name": "new", "input_schema_hash": "a"}],
            source_files=[],
        )
        difference = "\n".join(contract.compare_manifest(expected, actual))
        self.assertIn("missing prompts: old", difference)
        self.assertIn("extra prompts: new", difference)


class CheckedInInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = qualify.load_inventory(QUALIFICATION_DIR / "api_inventory.json")
        cls.surfaces = {surface["id"]: surface for surface in cls.inventory["surfaces"]}
        cls.manifests = {
            surface_id: qualify.derive_surface(surface)
            for surface_id, surface in cls.surfaces.items()
        }

    def test_all_checked_in_manifests_match_sources(self) -> None:
        for surface_id, surface in self.surfaces.items():
            with self.subTest(surface=surface_id):
                expected = json.loads(
                    (
                        QUALIFICATION_DIR / "expected" / surface["expected_manifest"]
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    contract.compare_manifest(expected, self.manifests[surface_id]), []
                )

    def test_inventory_totals_are_exact(self) -> None:
        rest = [item for item in self.manifests.values() if item["kind"] == "rest"]
        mcp = [item for item in self.manifests.values() if item["kind"] == "mcp"]
        self.assertEqual(sum(item["declared_operation_count"] for item in rest), 342)
        self.assertEqual(
            sum(item["normalized_unique_operation_count"] for item in rest), 341
        )
        self.assertEqual(sum(item["tool_count"] for item in mcp), 42)
        self.assertEqual(sum(item["prompt_count"] for item in mcp), 5)

    def test_vios_mcp_declarations_are_exact(self) -> None:
        manifest = self.manifests["vios-mcp"]
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(
            [item["name"] for item in manifest["tools"]],
            [
                "get_live_picture_base64",
                "get_live_picture_url",
                "get_replay_picture_base64",
                "get_replay_picture_url",
                "get_video_storage_url",
                "record_stream_start",
                "record_stream_status",
                "record_stream_stop",
                "record_stream_timelines",
                "sensor_health_check",
                "sensor_info_by_id",
                "sensor_list",
                "sensor_network_by_id",
                "sensor_scan",
                "sensor_settings_by_id",
                "sensor_status",
                "sensor_status_by_id",
                "storage_file_list",
                "storage_file_list_by_sensor",
                "storage_file_path",
                "storage_file_path_by_sensor",
                "storage_file_upload",
            ],
        )
        self.assertEqual(
            [item["name"] for item in manifest["prompts"]],
            [
                "picture_for_camera",
                "picture_url_for_camera",
                "sensors_count",
                "sensors_recording_status",
                "video_for_sensor",
            ],
        )
        self.assertEqual(
            self.surfaces["vios-mcp"]["direct"],
            {
                "port_env": "VST_MCP_PORT",
                "default_port": 8001,
                "transport": "streamable-http",
                "path": "/mcp",
            },
        )
        self.assertIsNone(self.surfaces["vios-mcp"]["public"])
        self.assertEqual(
            self.surfaces["vios-mcp"]["thor_runtime"],
            {
                "state": "wired-local-derivative",
                "runtime_inventory": True,
                "reason": (
                    "Thor supplies the omitted service with an exact Python base digest, "
                    "checksum-locked Linux/AArch64 wheel closure, networkless image build, "
                    "loopback-only Compose endpoint, and read-only runtime probe."
                ),
            },
        )

    def test_all_mcp_manifests_use_prompt_aware_schema(self) -> None:
        for surface_id in ("lvs-mcp", "va-mcp", "vios-mcp"):
            with self.subTest(surface=surface_id):
                manifest = self.manifests[surface_id]
                self.assertEqual(manifest["schema_version"], 2)
                self.assertEqual(manifest["prompt_count"], len(manifest["prompts"]))

    def test_vios_storage_collision_is_explicit(self) -> None:
        storage = self.manifests["vios-storage"]
        self.assertEqual(storage["declared_operation_count"], 26)
        self.assertEqual(storage["normalized_unique_operation_count"], 25)
        colliding = [
            operation
            for operation in storage["operations"]
            if operation["method"] == "GET"
            and contract.canonical_route(operation["path"])
            == "/vst/api/v1/storage/file/{}"
        ]
        self.assertEqual(len(colliding), 2)

    def test_lvs_source_and_documented_gap_are_exact(self) -> None:
        self.assertEqual(self.manifests["lvs"]["declared_operation_count"], 18)
        qualify._validate_lvs_documented_gap(self.inventory, self.manifests)

    def test_contract_cli_passes_without_regeneration(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = qualify.run_contract(
                QUALIFICATION_DIR / "api_inventory.json",
                QUALIFICATION_DIR / "expected",
            )
        self.assertEqual(status, 0, output.getvalue())
        self.assertIn("342 declared REST operations", output.getvalue())
        self.assertIn("42 MCP tools plus 5 MCP prompts", output.getvalue())

    def test_local_live_openapi_helper_does_not_accept_urls(self) -> None:
        with self.assertRaises(contract.ContractError):
            qualify._compare_live_openapi(
                "alerts=https://example.invalid/openapi.json",
                self.surfaces,
                self.manifests,
            )

    def test_qualification_code_has_no_network_or_container_imports(self) -> None:
        banned_imports = {
            "docker",
            "httpx",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
        for filename in ("contract.py", "qualify.py"):
            tree = ast.parse((QUALIFICATION_DIR / filename).read_text(encoding="utf-8"))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.partition(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.partition(".")[0])
            self.assertFalse(
                imports & banned_imports,
                f"{filename}: banned imports {imports & banned_imports}",
            )


if __name__ == "__main__":
    unittest.main()
