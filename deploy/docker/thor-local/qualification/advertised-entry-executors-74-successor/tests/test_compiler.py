from __future__ import annotations

from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
MODULE_PATH = LANE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_74_compiler", MODULE_PATH
)
assert SPEC and SPEC.loader
COMPILER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COMPILER
SPEC.loader.exec_module(COMPILER)


class AdvertisedEntry74SuccessorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory, cls.migration = COMPILER.check_checked_artifacts()
        cls.plan = json.loads(
            (COMPILER.REPO_ROOT / COMPILER.SOURCE_PLAN["path"]).read_text()
        )
        cls.manifest = json.loads(
            (COMPILER.REPO_ROOT / COMPILER.SOURCE_MANIFEST["path"]).read_text()
        )
        cls.official = json.loads(
            (COMPILER.REPO_ROOT / COMPILER.SOURCE_OFFICIAL["path"]).read_text()
        )
        cls.oracles = json.loads(
            (COMPILER.REPO_ROOT / COMPILER.SOURCE_ORACLES["path"]).read_text()
        )
        cls.inventory_schema = json.loads(COMPILER.INVENTORY_SCHEMA_PATH.read_text())
        cls.migration_schema = json.loads(COMPILER.MIGRATION_SCHEMA_PATH.read_text())

    def test_exact_71_3_13_set_algebra(self) -> None:
        rows = self.inventory["rows"]
        candidates = {
            row["entry_id"] for row in rows if row["disposition"] == "candidate"
        }
        blockers = {
            row["entry_id"] for row in rows if row["disposition"] == "external_blocker"
        }
        migrations = {
            row["former_gap_entry_id"] for row in self.migration["migrations"]
        }
        plan_ids = {row["entry_id"] for row in self.plan["entries"]}
        self.assertEqual(
            (len(rows), len(candidates), len(blockers), len(migrations)),
            (74, 71, 3, 13),
        )
        self.assertFalse(candidates & blockers)
        self.assertEqual(candidates | blockers, plan_ids)
        self.assertEqual(blockers, COMPILER.EXPECTED_BLOCKER_IDS)
        self.assertEqual(migrations, COMPILER.EXPECTED_MIGRATED_IDS)
        self.assertFalse(plan_ids & migrations)

    def test_exact_per_wave_candidate_counts(self) -> None:
        observed = Counter(
            row["legacy_wave"]
            for row in self.inventory["rows"]
            if row["disposition"] == "candidate"
        )
        self.assertEqual(
            observed, Counter({1: 1, 2: 18, 3: 23, 4: 5, 5: 5, 6: 8, 7: 11})
        )

    def test_current_plan_bindings_are_exact(self) -> None:
        by_id = {row["entry_id"]: row for row in self.plan["entries"]}
        for row in self.inventory["rows"]:
            with self.subTest(entry_id=row["entry_id"]):
                plan = by_id[row["entry_id"]]
                self.assertEqual(row["manifest_pointer"], plan["manifest_pointer"])
                self.assertEqual(row["advertised"], plan["advertised"])
                self.assertEqual(
                    row["advertised_utf8_sha256"], plan["advertised_utf8_sha256"]
                )
                self.assertEqual(
                    row["advertised_canonical_sha256"],
                    plan["advertised_canonical_sha256"],
                )
                self.assertEqual(
                    row["proposed_capability_id"], plan["proposed_capability"]["id"]
                )
                self.assertEqual(
                    plan["coverage_state"], "open_missing_entry_capability_and_oracle"
                )
                self.assertEqual(plan["required_oracle"]["status"], "open_unexecuted")
                self.assertEqual(plan["runtime_evidence"], [])
                self.assertEqual(plan["required_oracle"]["runtime_evidence"], [])

    def test_manifest_literal_mismatch_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        first = self.plan["entries"][0]
        family_index = first["family_index"]
        advertised_index = first["advertised_index"]
        manifest["features"][family_index]["advertised"][advertised_index] += " drift"
        with self.assertRaisesRegex(
            COMPILER.CompileError, "plan/manifest literal mismatch"
        ):
            COMPILER._verify_plan_manifest_bindings(self.plan["entries"], manifest)

    def test_historical_waves_are_exactly_locked_and_disjoint(self) -> None:
        seen: set[str] = set()
        for lock in self.inventory["historical_waves"]:
            inventory_path = COMPILER.REPO_ROOT / lock["inventory_path"]
            executor_path = COMPILER.REPO_ROOT / lock["executor_path"]
            self.assertEqual(
                hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
                lock["inventory_sha256"],
            )
            self.assertEqual(
                hashlib.sha256(executor_path.read_bytes()).hexdigest(),
                lock["executor_sha256"],
            )
            historical = json.loads(inventory_path.read_text())
            ids = {row["entry_id"] for row in historical["cases"]}
            self.assertEqual(len(ids), lock["old_case_count"])
            self.assertFalse(seen & ids)
            seen |= ids
        self.assertEqual(len(seen), 82)

    def test_retained_historical_row_digests_are_exact(self) -> None:
        historical: dict[str, dict[str, object]] = {}
        for lock in self.inventory["historical_waves"]:
            value = json.loads(
                (COMPILER.REPO_ROOT / lock["inventory_path"]).read_text()
            )
            historical.update({row["entry_id"]: row for row in value["cases"]})
        for row in self.inventory["rows"]:
            if row["disposition"] != "candidate":
                continue
            self.assertEqual(
                row["legacy_row_canonical_sha256"],
                COMPILER._sha_json(historical[row["entry_id"]]),
            )

    def test_exact_182_source_references_and_88_unique_paths(self) -> None:
        candidates = [
            row for row in self.inventory["rows"] if row["disposition"] == "candidate"
        ]
        self.assertEqual(sum(row["source_lock_count"] for row in candidates), 182)
        self.assertEqual(len(self.inventory["source_files"]), 88)
        paths = [row["path"] for row in self.inventory["source_files"]]
        self.assertEqual(len(paths), len(set(paths)))
        for lock in self.inventory["source_files"]:
            path = COMPILER.REPO_ROOT / lock["path"]
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), lock["sha256"]
            )

    def test_adapter_duplicates_are_only_the_two_intentional_groups(self) -> None:
        adapters = Counter(
            row["adapter_id"]
            for row in self.inventory["rows"]
            if row["disposition"] == "candidate"
        )
        duplicates = {key: value for key, value in adapters.items() if value > 1}
        self.assertEqual(duplicates, {"model_source_contract": 4, "uri_validator": 2})
        self.assertEqual(len(adapters), 67)

    def test_three_blockers_cannot_execute_or_promote(self) -> None:
        blockers = [
            row
            for row in self.inventory["rows"]
            if row["disposition"] == "external_blocker"
        ]
        self.assertEqual(len(blockers), 3)
        for row in blockers:
            self.assertIsNone(row["executor"])
            self.assertFalse(row["candidate_materialized"])
            self.assertFalse(row["can_mark_passed_current"])
            self.assertEqual(row["runtime_evidence"], [])
            self.assertEqual(row["blocker_type"], "external_optional_boundary")

    def test_remote_openai_endpoint_remains_candidate_not_blocker(self) -> None:
        target = "manifest-gap.rt-vlm-models.04-remote-openai-compatible-endpoint"
        rows = {row["entry_id"]: row for row in self.inventory["rows"]}
        self.assertEqual(rows[target]["disposition"], "candidate")
        self.assertEqual(rows[target]["legacy_wave"], 3)

    def test_all_candidates_have_phase_2_direct_dispatch(self) -> None:
        for row in self.inventory["rows"]:
            self.assertFalse(row["can_mark_passed_current"])
            self.assertEqual(row["runtime_evidence"], [])
            if row["disposition"] == "candidate":
                self.assertEqual(row["executor"], "direct_historical_adapter")
                self.assertEqual(row["dispatch_status"], "implemented_phase_2")
            else:
                self.assertIsNone(row["executor"])
        self.assertTrue(self.inventory["policy"]["dispatch_implemented"])

    def test_migrations_bind_exact_live_predecessor_identities(self) -> None:
        official = {row["id"]: row for row in self.official["capabilities"]}
        oracles = {row["capability_id"]: row for row in self.oracles["oracles"]}
        plan_ids = {row["entry_id"] for row in self.plan["entries"]}
        for row in self.migration["migrations"]:
            with self.subTest(entry_id=row["former_gap_entry_id"]):
                self.assertNotIn(row["former_gap_entry_id"], plan_ids)
                capability = official[row["live_capability_id"]]
                oracle = oracles[row["live_capability_id"]]
                self.assertEqual(row["live_oracle_id"], oracle["oracle_id"])
                self.assertEqual(
                    row["live_capability_canonical_sha256"],
                    COMPILER._sha_json(capability),
                )
                self.assertEqual(
                    row["live_oracle_canonical_sha256"], COMPILER._sha_json(oracle)
                )
                self.assertEqual(row["runtime_evidence"], [])

    def test_migration_is_not_runtime_qualification(self) -> None:
        self.assertEqual(
            Counter(row["runtime_state"] for row in self.migration["migrations"]),
            Counter({"not_qualified": 12, "not_applicable": 1}),
        )
        self.assertFalse(self.migration["policy"]["migration_is_runtime_qualification"])
        self.assertFalse(self.migration["policy"]["can_mark_passed_current"])
        self.assertEqual(self.migration["policy"]["runtime_evidence"], [])

    def test_current_74_proposed_ids_are_not_live_predecessors(self) -> None:
        proposed = {row["proposed_capability"]["id"] for row in self.plan["entries"]}
        official = {row["id"] for row in self.official["capabilities"]}
        oracles = {row["capability_id"] for row in self.oracles["oracles"]}
        self.assertFalse(proposed & official)
        self.assertFalse(proposed & oracles)

    def test_safety_policy_is_fail_closed(self) -> None:
        policy = self.inventory["policy"]
        for key in (
            "can_mark_passed_current",
            "network_allowed",
            "docker_allowed",
            "subprocess_allowed",
            "credentials_allowed",
            "lifecycle_allowed",
            "downloads_allowed",
            "host_inspection_allowed",
        ):
            self.assertFalse(policy[key])
        self.assertTrue(policy["dispatch_implemented"])
        self.assertEqual(policy["runtime_evidence"], [])
        self.assertEqual(policy["warehouse_sample_bundle"], "excluded")

    def test_payloads_and_raw_artifact_locks_are_exact(self) -> None:
        self.assertEqual(
            COMPILER._payload(self.inventory, "inventory_payload_sha256"),
            self.inventory["inventory_payload_sha256"],
        )
        self.assertEqual(
            COMPILER._payload(self.migration, "migration_payload_sha256"),
            self.migration["migration_payload_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(COMPILER.INVENTORY_PATH.read_bytes()).hexdigest(),
            COMPILER.EXPECTED_INVENTORY_RAW_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(COMPILER.MIGRATION_PATH.read_bytes()).hexdigest(),
            COMPILER.EXPECTED_MIGRATION_RAW_SHA256,
        )

    def test_compilation_is_deterministic(self) -> None:
        first = COMPILER.compile_artifacts()
        second = COMPILER.compile_artifacts()
        self.assertEqual(first, second)
        self.assertEqual(first, (self.inventory, self.migration))

    def test_strict_json_rejects_duplicate_keys(self) -> None:
        with self.assertRaisesRegex(COMPILER.CompileError, "duplicate JSON key"):
            COMPILER._strict_json(b'{"entry_id":"one","entry_id":"two"}', "duplicate")

    def test_strict_json_rejects_non_finite_numbers(self) -> None:
        for token in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(COMPILER.CompileError, "non-finite"):
                    COMPILER._strict_json(b'{"value":' + token + b"}", "nonfinite")

    def test_schemas_reject_extra_fields_and_denominator_tamper(self) -> None:
        candidates = []
        extra = copy.deepcopy(self.inventory)
        extra["rows"][0]["unexpected"] = True
        candidates.append((extra, self.inventory_schema))
        count = copy.deepcopy(self.inventory)
        count["summary"]["candidate_entries"] = 70
        candidates.append((count, self.inventory_schema))
        migration = copy.deepcopy(self.migration)
        migration["policy"]["can_mark_passed_current"] = True
        candidates.append((migration, self.migration_schema))
        for value, schema in candidates:
            with self.subTest(value=value.get("summary")):
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(value)))

    def test_wrong_source_digest_is_rejected(self) -> None:
        lock = dict(COMPILER.SOURCE_PLAN)
        lock["raw_sha256"] = "0" * 64
        with self.assertRaisesRegex(COMPILER.CompileError, "raw digest drift"):
            COMPILER._load_locked_json(lock, "tampered plan")

    def test_unsafe_and_symlink_repository_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(COMPILER.CompileError, "unsafe repository path"):
            COMPILER._repo_file("../outside")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("{}")
            (root / "link.json").symlink_to(target)
            with mock.patch.object(COMPILER, "REPO_ROOT", root):
                with self.assertRaisesRegex(COMPILER.CompileError, "symlink"):
                    COMPILER._repo_file("link.json")
            real = root / "real"
            real.mkdir()
            (real / "nested.json").write_text("{}")
            (root / "linked-directory").symlink_to(real, target_is_directory=True)
            with mock.patch.object(COMPILER, "REPO_ROOT", root):
                with self.assertRaisesRegex(COMPILER.CompileError, "symlink"):
                    COMPILER._repo_file("linked-directory/nested.json")

    def test_symlinked_package_artifacts_and_schemas_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            artifact = real / "inventory.json"
            artifact.write_text("{}")
            schema = real / "inventory.schema.json"
            schema.write_text("{}")
            artifact_link = root / "artifact-link.json"
            artifact_link.symlink_to(artifact)
            linked_directory = root / "linked-directory"
            linked_directory.symlink_to(real, target_is_directory=True)
            with mock.patch.object(COMPILER, "REPO_ROOT", root):
                with self.assertRaisesRegex(COMPILER.CompileError, "symlink"):
                    COMPILER._read_package_bytes(artifact_link)
                with self.assertRaisesRegex(COMPILER.CompileError, "symlink"):
                    COMPILER._read_package_bytes(
                        linked_directory / "inventory.schema.json"
                    )


if __name__ == "__main__":
    unittest.main()
