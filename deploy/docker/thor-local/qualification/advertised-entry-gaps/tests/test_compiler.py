from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
MODULE_PATH = LANE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_gap_compiler", MODULE_PATH
)
assert SPEC and SPEC.loader
COMPILER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COMPILER
SPEC.loader.exec_module(COMPILER)


class AdvertisedEntryGapCompilerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = COMPILER.check_checked_plan()
        cls.manifest = json.loads(COMPILER.MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.plan_schema = json.loads(
            (LANE / "plan.schema.json").read_text(encoding="utf-8")
        )
        cls.rules_schema = json.loads(
            (LANE / "classification-rules.schema.json").read_text(encoding="utf-8")
        )
        cls.rules = json.loads(
            (LANE / "classification-rules.json").read_text(encoding="utf-8")
        )

    def test_exact_sixteen_family_and_eighty_six_entry_denominator(self) -> None:
        self.assertEqual(len(self.plan["families"]), 16)
        self.assertEqual(len(self.plan["entries"]), 86)
        self.assertEqual(
            {item["family_id"] for item in self.plan["families"]},
            COMPILER.EXPECTED_FAMILY_IDS,
        )
        self.assertEqual(len({item["entry_id"] for item in self.plan["entries"]}), 86)
        self.assertEqual(
            len({item["manifest_pointer"] for item in self.plan["entries"]}), 86
        )

    def test_summary_is_exact_and_all_entries_remain_open(self) -> None:
        summary = self.plan["summary"]
        self.assertEqual(summary["manifest_family_count"], 55)
        self.assertEqual(summary["families_with_uncovered_advertised_entries"], 16)
        self.assertEqual(summary["families_without_official_capability_ids"], 15)
        self.assertEqual(summary["families_with_partial_official_capability_ids"], 1)
        self.assertEqual(
            summary["advertised_entries_without_official_capability_ids"], 86
        )
        self.assertEqual(summary["open_unverified_entries"], 86)
        self.assertEqual(summary["runtime_evidence_count"], 0)
        self.assertEqual(
            summary["acceptance_class_counts"],
            {"alternate_local_lane": 26, "external_optional": 5, "required_local": 55},
        )
        self.assertTrue(
            all(
                item["coverage_state"] == "open_missing_entry_capability_and_oracle"
                for item in self.plan["entries"]
            )
        )

    def test_every_manifest_pointer_string_and_hash_round_trips_exactly(self) -> None:
        for item in self.plan["entries"]:
            with self.subTest(pointer=item["manifest_pointer"]):
                family = self.manifest["features"][item["family_index"]]
                advertised = family["advertised"][item["advertised_index"]]
                self.assertEqual(
                    item["manifest_pointer"],
                    f"/features/{item['family_index']}/advertised/{item['advertised_index']}",
                )
                self.assertEqual(
                    item["family_pointer"], f"/features/{item['family_index']}"
                )
                self.assertEqual(item["family_id"], family["id"])
                self.assertEqual(item["advertised"], advertised)
                self.assertEqual(
                    item["proposed_capability"]["literal_scope"], advertised
                )
                self.assertEqual(
                    item["advertised_utf8_sha256"],
                    hashlib.sha256(advertised.encode("utf-8")).hexdigest(),
                )
                self.assertEqual(
                    item["advertised_canonical_sha256"], COMPILER._sha_json(advertised)
                )
                self.assertEqual(
                    item["family_canonical_sha256"], COMPILER._sha_json(family)
                )

    def test_fifteen_source_families_are_absent_and_vios_is_partial(self) -> None:
        for item in self.plan["families"]:
            family = self.manifest["features"][item["family_index"]]
            self.assertEqual(item["advertised_entry_count"], len(family["advertised"]))
            self.assertEqual(
                item["uncovered_advertised_entry_count"], len(item["entry_ids"])
            )
            self.assertEqual(
                item["covered_advertised_entry_count"]
                + item["uncovered_advertised_entry_count"],
                item["advertised_entry_count"],
            )
            self.assertEqual(
                item["official_capability_ids"],
                family.get("official_capability_ids", []),
            )
        partial = [
            item
            for item in self.plan["families"]
            if item["official_capability_ids_state"] == "partial"
        ]
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0]["family_id"], "vios-codecs-audio")
        self.assertEqual(
            partial[0]["official_capability_ids"],
            ["manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"],
        )
        self.assertEqual(partial[0]["covered_advertised_entry_count"], 1)
        self.assertEqual(partial[0]["uncovered_advertised_entry_count"], 5)
        self.assertTrue(
            all(
                item["official_capability_ids_state"] == "absent"
                for item in self.plan["families"]
                if item["family_id"] != "vios-codecs-audio"
            )
        )

    def test_cpu_multimedia_is_removed_from_gap_plan_only(self) -> None:
        pointers = {item["manifest_pointer"] for item in self.plan["entries"]}
        self.assertNotIn("/features/20/advertised/5", pointers)
        self.assertTrue(
            {f"/features/20/advertised/{index}" for index in range(5)} <= pointers
        )
        self.assertNotIn(
            "manifest-gap.vios-codecs-audio.05-cpu-multimedia-support",
            {item["entry_id"] for item in self.plan["entries"]},
        )

    def test_family_lane_status_is_never_semantic_entry_coverage(self) -> None:
        self.assertIs(
            self.plan["policy"]["family_lane_binding_is_semantic_coverage"], False
        )
        self.assertTrue(
            all(
                item["family_lane_binding_is_semantic_coverage"] is False
                for item in self.plan["families"]
            )
        )
        self.assertTrue(
            all(
                item["family_lane_binding_is_semantic_coverage"] is False
                for item in self.plan["entries"]
            )
        )
        passed_families = {
            item["family_id"]
            for item in self.plan["families"]
            if item["family_runtime_state_snapshot"] == "passed_current"
        }
        self.assertEqual(passed_families, {"spatial-ai-utils", "synthetic-data-tools"})
        passed_family_entries = [
            item
            for item in self.plan["entries"]
            if item["family_id"] in passed_families
        ]
        self.assertEqual(len(passed_family_entries), 12)
        self.assertTrue(
            all(
                item["required_oracle"]["status"] == "open_unexecuted"
                for item in passed_family_entries
            )
        )

    def test_every_entry_has_concrete_capability_and_oracle_plan(self) -> None:
        for item in self.plan["entries"]:
            with self.subTest(entry=item["entry_id"]):
                capability = item["proposed_capability"]
                oracle = item["required_oracle"]
                self.assertTrue(capability["id"].startswith("manifest-entry."))
                self.assertTrue(capability["kind"])
                self.assertTrue(oracle["id"].startswith("oracle.manifest-entry."))
                self.assertTrue(oracle["executor_class"])
                self.assertGreaterEqual(len(oracle["setup_requirements"]), 1)
                self.assertGreaterEqual(len(oracle["required_evidence"]), 2)
                self.assertIn(item["advertised"], oracle["literal_success_condition"])
                self.assertEqual(oracle["runtime_evidence"], [])
                self.assertEqual(item["runtime_evidence"], [])
                self.assertNotEqual(oracle["status"], "passed_current")

    def test_external_optional_classification_is_exactly_five_entries(self) -> None:
        external = {
            (item["family_id"], item["advertised"])
            for item in self.plan["entries"]
            if item["required_oracle"]["type"] == "external_optional_boundary"
        }
        self.assertEqual(
            external,
            {
                ("alert-notifications-slack", "Slack notification"),
                ("rt-vlm-models", "remote OpenAI-compatible endpoint"),
                ("spatial-ai-utils", "AWS/GCS validation"),
                ("enterprise-rag", "RAG report generation"),
                ("enterprise-rag", "frag retrieval integration"),
            },
        )
        self.assertTrue(
            all(
                item["proposed_capability"]["acceptance_class"] == "external_optional"
                for item in self.plan["entries"]
                if item["required_oracle"]["type"] == "external_optional_boundary"
            )
        )

    def test_warehouse_sample_is_excluded_but_custom_data_is_in_scope(self) -> None:
        self.assertEqual(self.plan["policy"]["warehouse_sample_bundle"], "excluded")
        self.assertEqual(
            self.plan["policy"]["custom_data_warehouse_capability"], "in_scope"
        )
        self.assertTrue(
            all(
                item["warehouse_scope"]["sample_bundle_required"] is False
                for item in self.plan["entries"]
            )
        )
        custom = [
            item
            for item in self.plan["entries"]
            if item["warehouse_scope"]["custom_data_capability_in_scope"]
        ]
        self.assertEqual(len(custom), 8)
        self.assertEqual(
            {item["family_id"] for item in custom}, COMPILER.CUSTOM_DATA_FAMILIES
        )
        self.assertTrue(
            all(
                item["required_oracle"]["type"] == "runtime_custom_data_multicamera"
                for item in custom
            )
        )

    def test_no_entry_contains_excluded_warehouse_sample_marker(self) -> None:
        rendered = json.dumps(self.plan, sort_keys=True)
        for marker in COMPILER.EXCLUDED_SAMPLE_MARKERS:
            self.assertNotIn(marker, rendered)

    def test_source_and_output_digest_locks_are_exact(self) -> None:
        locks = self.plan["source_locks"]
        self.assertEqual(locks["manifest"]["raw_sha256"], COMPILER.MANIFEST_RAW_SHA256)
        self.assertEqual(
            locks["manifest"]["canonical_sha256"],
            COMPILER.MANIFEST_CANONICAL_SHA256,
        )
        self.assertEqual(
            locks["classification_rules"]["raw_sha256"], COMPILER.RULES_RAW_SHA256
        )
        self.assertEqual(
            locks["classification_rules"]["canonical_sha256"],
            COMPILER.RULES_CANONICAL_SHA256,
        )
        self.assertEqual(
            locks["official_capabilities"]["raw_sha256"],
            COMPILER.OFFICIAL_CAPABILITIES_RAW_SHA256,
        )
        self.assertEqual(
            locks["official_capabilities"]["canonical_sha256"],
            COMPILER.OFFICIAL_CAPABILITIES_CANONICAL_SHA256,
        )
        self.assertEqual(
            self.plan["plan_payload_sha256"], COMPILER.EXPECTED_PLAN_PAYLOAD_SHA256
        )
        self.assertEqual(
            hashlib.sha256((LANE / "plan.json").read_bytes()).hexdigest(),
            COMPILER.EXPECTED_PLAN_RAW_SHA256,
        )

    def test_compilation_is_deterministic_and_matches_checked_plan(self) -> None:
        first = COMPILER.compile_plan()
        second = COMPILER.compile_plan()
        self.assertEqual(first, second)
        self.assertEqual(first, self.plan)

    def test_plan_and_rules_are_schema_valid(self) -> None:
        self.assertEqual(
            list(Draft202012Validator(self.plan_schema).iter_errors(self.plan)), []
        )
        self.assertEqual(
            list(Draft202012Validator(self.rules_schema).iter_errors(self.rules)), []
        )

    def test_schema_rejects_runtime_evidence_and_false_semantic_coverage(self) -> None:
        promoted = copy.deepcopy(self.plan)
        promoted["entries"][0]["runtime_evidence"] = [{"fake": "pass"}]
        self.assertTrue(
            list(Draft202012Validator(self.plan_schema).iter_errors(promoted))
        )
        falsely_covered = copy.deepcopy(self.plan)
        falsely_covered["entries"][0]["family_lane_binding_is_semantic_coverage"] = True
        self.assertTrue(
            list(Draft202012Validator(self.plan_schema).iter_errors(falsely_covered))
        )

    def test_plan_payload_tamper_fails_even_if_schema_shape_still_valid(self) -> None:
        altered = copy.deepcopy(self.plan)
        altered["entries"][0]["advertised"] = "changed"
        with self.assertRaises(COMPILER.CompileError):
            COMPILER.validate_plan(altered, enforce_pins=False)

    def test_manifest_source_tamper_fails_closed_at_raw_lock(self) -> None:
        original_path = COMPILER.MANIFEST_PATH
        with tempfile.TemporaryDirectory() as temporary_name:
            path = Path(temporary_name) / "manifest.json"
            path.write_bytes(original_path.read_bytes() + b"\n")
            COMPILER.MANIFEST_PATH = path
            try:
                with self.assertRaises(COMPILER.CompileError):
                    COMPILER.compile_plan()
            finally:
                COMPILER.MANIFEST_PATH = original_path

    def test_official_capability_source_tamper_fails_closed_at_raw_lock(self) -> None:
        original_path = COMPILER.OFFICIAL_CAPABILITIES_PATH
        with tempfile.TemporaryDirectory() as temporary_name:
            path = Path(temporary_name) / "official-capabilities.json"
            path.write_bytes(original_path.read_bytes() + b"\n")
            COMPILER.OFFICIAL_CAPABILITIES_PATH = path
            try:
                with self.assertRaises(COMPILER.CompileError):
                    COMPILER.compile_plan()
            finally:
                COMPILER.OFFICIAL_CAPABILITIES_PATH = original_path

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with self.assertRaises(COMPILER.CompileError):
            COMPILER._strict_json(b'{"x":1,"x":2}', "duplicate")

    def test_compiler_ast_has_no_network_docker_or_subprocess_primitives(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            imported.isdisjoint(
                {
                    "asyncio",
                    "docker",
                    "http",
                    "requests",
                    "socket",
                    "subprocess",
                    "urllib",
                }
            )
        )
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)


if __name__ == "__main__":
    unittest.main()
