from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import readiness as rd  # noqa: E402


class PlanTests(unittest.TestCase):
    def test_checked_in_plan_and_source_locks_are_exact(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        rd.validate_plan(plan)
        result = rd.verify_source_locks(plan)
        self.assertEqual(result["state"], "match")
        self.assertGreaterEqual(len(result["files"]), 7)

    def test_plan_mode_is_inert(self) -> None:
        output = io.StringIO()
        with mock.patch.object(rd.subprocess, "run") as run:
            with redirect_stdout(output):
                result = rd.main(["plan"])
        self.assertEqual(result, 0)
        run.assert_not_called()
        payload = json.loads(output.getvalue())
        schema = rd._load_json(rd.HERE / "result.schema.json")
        jsonschema.Draft202012Validator(schema).validate(payload)
        self.assertEqual(payload["qualification_state"], "plan_only")
        self.assertFalse(payload["runtime_qualification_performed"])
        self.assertRegex(
            payload["captured_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$",
        )

    def test_capture_time_is_generated_inside_each_result(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        with mock.patch.object(
            rd,
            "_captured_at_utc",
            side_effect=[
                "2026-08-02T15:00:00.000001Z",
                "2026-08-02T15:00:00.000002Z",
            ],
        ):
            first = rd.build_plan_result(plan)
            second = rd.build_plan_result(plan)
        self.assertEqual(first["captured_at_utc"], "2026-08-02T15:00:00.000001Z")
        self.assertEqual(second["captured_at_utc"], "2026-08-02T15:00:00.000002Z")
        self.assertNotEqual(first["captured_at_utc"], second["captured_at_utc"])

    def test_schema_rejects_missing_or_non_utc_capture_time(self) -> None:
        schema = rd._load_json(rd.HERE / "result.schema.json")
        result = rd.build_plan_result(rd._load_json(rd.DEFAULT_PLAN))
        missing = deepcopy(result)
        del missing["captured_at_utc"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(missing)
        result["captured_at_utc"] = "2026-08-02T15:00:00+00:00"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(result)

    def test_main_rejects_fabricated_invalid_result_before_printing(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        fabricated = rd.build_plan_result(rd._load_json(rd.DEFAULT_PLAN))
        fabricated["runtime_qualification_performed"] = True
        with (
            mock.patch.object(rd, "build_plan_result", return_value=fabricated),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = rd.main(["plan"])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("result schema validation failed", errors.getvalue())

    def test_main_fails_closed_when_checked_in_result_schema_is_invalid(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            invalid_schema = Path(temporary) / "result.schema.json"
            invalid_schema.write_text(
                json.dumps({"type": "not-a-valid-json-schema-type"}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(rd, "RESULT_SCHEMA", invalid_schema),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                result = rd.main(["plan"])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("checked-in result schema is invalid", errors.getvalue())

    def test_plan_cannot_replace_official_images_or_lower_memory_gate(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        mutations = (
            ("edge_vllm", "exact_reference", "example.invalid/x@sha256:" + "1" * 64),
            ("edge_vllm", "required_image_id", "sha256:" + "2" * 64),
            ("rt_vlm", "exact_reference", "example.invalid/y@sha256:" + "3" * 64),
        )
        for image, key, value in mutations:
            tampered = deepcopy(plan)
            tampered["images"][image][key] = value
            with self.subTest(image=image, key=key):
                with self.assertRaises(rd.ReadinessError):
                    rd.validate_plan(tampered)
        tampered = deepcopy(plan)
        tampered["admission"]["minimum_available_memory_fraction"] = "0.0"
        with self.assertRaises(rd.ReadinessError):
            rd.validate_plan(tampered)

        tampered = deepcopy(plan)
        tampered["source_locks"] = [{"path": "README.md", "sha256": "0" * 64}]
        with self.assertRaisesRegex(rd.ReadinessError, "checked-in plan"):
            rd.validate_plan(tampered)
        tampered = deepcopy(plan)
        tampered["identities"]["llm"][
            "standard_hf_cache_directory"
        ] = "../../credential-area"
        with self.assertRaisesRegex(rd.ReadinessError, "checked-in plan"):
            rd.validate_plan(tampered)

    def test_wrong_acknowledgement_fails_before_host_reads(self) -> None:
        errors = io.StringIO()
        with mock.patch.object(rd, "build_host_result") as build:
            with redirect_stderr(errors):
                result = rd.main(["inspect", "--acknowledgement", "yes"])
        self.assertEqual(result, 1)
        build.assert_not_called()
        self.assertIn(rd.ACKNOWLEDGEMENT, errors.getvalue())

    def test_remote_metadata_is_never_local_readiness_evidence(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        remote = plan["reviewed_remote_staging_metadata"]
        self.assertFalse(remote["local_readiness_evidence"])
        self.assertEqual(remote["edge_llm"]["total_bytes"], 5_284_569_483)
        self.assertEqual(
            remote["edge_vllm_image"]["manifest_payload_bytes"], 14_586_467_388
        )
        self.assertEqual(remote["cosmos3_nano_bf16"]["file_count"], 34)
        self.assertEqual(remote["cosmos3_nano_bf16"]["total_bytes"], 17_545_910_496)
        self.assertEqual(
            remote["cosmos3_nano_bf16"]["access_state"],
            "signed_manifest_verified",
        )
        self.assertIsNone(remote["edge_vllm_image"]["installed_or_unpacked_size"])

    def test_forbidden_docker_operation_is_rejected_without_execution(self) -> None:
        with mock.patch.object(rd.subprocess, "run") as run:
            with self.assertRaisesRegex(rd.ReadinessError, "forbidden Docker"):
                rd._docker(["image", "pull", "forbidden"])
        run.assert_not_called()

    def test_source_lock_symlink_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.write_text("outside", encoding="utf-8")
            (root / "escape").symlink_to(outside)
            plan = {"source_locks": [{"path": "escape", "sha256": rd._sha256(outside)}]}
            with mock.patch.object(rd, "REPO_ROOT", root):
                with self.assertRaisesRegex(
                    rd.ReadinessError, "resolves outside the repository"
                ):
                    rd.verify_source_locks(plan)


class ArtifactTests(unittest.TestCase):
    @staticmethod
    def _reviewed(
        root: Path, filename: str, identity: dict[str, str]
    ) -> dict[str, object]:
        relative = Path("deploy/docker/thor-local/official-edge/provenance") / filename
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence = {
            "schema_version": 1,
            "state": "independently_reviewed_upstream_provenance",
            "identity": identity,
            "reviewed_by": "unit-test-trust-root",
            "sources": ["https://example.nvidia.com/reviewed-artifact"],
            "upstream_sha256": ["2" * 64],
        }
        path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        return {
            "state": "independently_reviewed_upstream_provenance",
            "identity": identity,
            "evidence_path": relative.as_posix(),
            "evidence_sha256": rd._sha256(path),
            "reviewed_by": "unit-test-trust-root",
        }

    def test_exact_hf_cache_name_discovers_only_immutable_snapshot_candidates(
        self,
    ) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        with tempfile.TemporaryDirectory() as temporary:
            hf_hub = Path(temporary)
            repository = (
                hf_hub / plan["identities"]["llm"]["standard_hf_cache_directory"]
            )
            revision = plan["reviewed_remote_staging_metadata"]["edge_llm"]["revision"]
            snapshot = repository / "snapshots" / revision
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
            mutable = repository / "snapshots" / "main"
            mutable.mkdir()
            result = rd.inspect_edge_artifact(plan, hf_hub)
        self.assertEqual(result["state"], "candidate_present_unlocked")
        self.assertEqual(
            [item["revision"] for item in result["snapshot_candidates"]], [revision]
        )
        self.assertEqual(result["snapshot_candidates"][0]["tree_summary"]["bytes"], 3)
        self.assertFalse(result["reviewed_remote_metadata_is_local_readiness_evidence"])

    def test_missing_and_unreadable_cosmos_paths_do_not_pass(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        self.assertEqual(
            rd.inspect_cosmos_artifact(plan, None)["state"],
            "exact_cache_path_not_supplied",
        )
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            result = rd.inspect_cosmos_artifact(plan, missing)
        self.assertEqual(result["state"], "missing_or_unreadable_exact_cache")

        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary)
            result = rd.inspect_cosmos_artifact(plan, empty)
        self.assertEqual(result["state"], "empty_candidate_directory")

    def test_tree_summary_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            outside = root / "outside"
            outside.write_text("secret", encoding="utf-8")
            (cache / "escape").symlink_to(outside)
            result = rd._tree_summary(cache, cache)
        self.assertEqual(result["state"], "unsafe_symlink_escape")

    def test_same_revision_tampered_tree_cannot_pass_exact_verifier(self) -> None:
        verifier = rd._load_official_verifier()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            revision = verifier.EDGE_REVISION
            repository = root / verifier.EDGE_CACHE_DIRECTORY
            snapshot = repository / "snapshots" / revision
            snapshot.mkdir(parents=True)
            blobs = repository / "blobs"
            blobs.mkdir()
            (blobs / ("a" * 64)).write_bytes(b"edge")
            (snapshot / "config.json").write_text("original\n", encoding="utf-8")
            cosmos = root / "cosmos"
            cosmos.mkdir()
            (cosmos / "weights.bin").write_bytes(b"cosmos")
            lock = root / "lock.json"
            payload = {
                "schema_version": 1,
                "lock_state": "complete_exact",
                "artifacts": {
                    "edge4b": {
                        "kind": "huggingface_snapshot",
                        "identity": {
                            "repository": verifier.EDGE_REPOSITORY,
                            "revision": revision,
                        },
                        "state": "locked_exact",
                        "provenance": self._reviewed(
                            root,
                            "edge.json",
                            {
                                "repository": verifier.EDGE_REPOSITORY,
                                "revision": revision,
                            },
                        ),
                        "tree": {
                            "entries": verifier._actual_tree_entries(
                                snapshot, repository
                            )
                        },
                        "blob_tree": {
                            "entries": verifier._actual_tree_entries(
                                repository / "blobs", repository / "blobs"
                            )
                        },
                    },
                    "cosmos3_nano_bf16": {
                        "kind": "ngc_model_cache",
                        "identity": {"artifact_id": verifier.COSMOS_ARTIFACT},
                        "state": "locked_exact",
                        "provenance": self._reviewed(
                            root,
                            "cosmos.json",
                            {"artifact_id": verifier.COSMOS_ARTIFACT},
                        ),
                        "tree": {
                            "entries": verifier._actual_tree_entries(cosmos, cosmos)
                        },
                    },
                },
            }
            for entry in payload["artifacts"].values():
                entry["tree"]["entry_count"] = len(entry["tree"]["entries"])
            payload["artifacts"]["edge4b"]["blob_tree"]["entry_count"] = len(
                payload["artifacts"]["edge4b"]["blob_tree"]["entries"]
            )
            lock.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                rd.verify_candidate_trees(lock, snapshot, cosmos, provenance_root=root)[
                    "state"
                ],
                "exact_match",
            )
            (snapshot / "config.json").write_text("tampered\n", encoding="utf-8")
            result = rd.verify_candidate_trees(
                lock, snapshot, cosmos, provenance_root=root
            )
        self.assertEqual(result["state"], "mismatch_or_unqualified")
        self.assertIn("tree differs", result["detail"])


class DockerTests(unittest.TestCase):
    def test_exact_image_requires_digest_and_architecture(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        entry = plan["images"]["rt_vlm"]
        reference = entry["exact_reference"]
        output = "|".join(
            json.dumps(value)
            for value in (
                entry["required_image_id"],
                [reference],
                ["tag"],
                123,
                "arm64",
                "linux",
            )
        )
        with mock.patch.object(rd, "_docker", return_value=(output, "")):
            result = rd.inspect_image(entry)
        self.assertEqual(result["state"], "present_exact")

        wrong = output.replace('"arm64"', '"amd64"')
        with mock.patch.object(rd, "_docker", return_value=(wrong, "")):
            result = rd.inspect_image(entry)
        self.assertEqual(result["state"], "present_but_not_exact")

        arbitrary_id = output.replace(entry["required_image_id"], "sha256:" + "a" * 64)
        with mock.patch.object(rd, "_docker", return_value=(arbitrary_id, "")):
            result = rd.inspect_image(entry)
        self.assertEqual(result["state"], "present_but_not_exact")

    def test_contract_image_must_be_explicitly_graduated(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        locks = rd.inspect_contract_image_locks(plan)
        self.assertEqual(locks["edge_vllm"]["state"], "locked_exact")
        self.assertEqual(locks["rt_vlm"]["state"], "locked_exact")

    def test_missing_container_is_classified_as_absent(self) -> None:
        with mock.patch.object(
            rd,
            "_docker",
            return_value=("", "Error response from daemon: No such container: exact"),
        ):
            result = rd.inspect_container("exact", "image@sha256:digest")
        self.assertEqual(result["state"], "absent")


class HostResultTests(unittest.TestCase):
    def _ready_result(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": "vss-3.2.1-thor-official-edge-readiness",
            "captured_at_utc": "2026-08-02T15:00:00.000000Z",
            "inspection_mode": "read_only_host",
            "qualification_state": "prelaunch_ready_not_runtime_qualified",
            "runtime_qualification_performed": False,
            "source_locks": {"state": "match"},
            "artifact_lock": {
                "lock_state": "complete_exact",
                "entries": {
                    "edge_snapshot": {
                        "state": "locked_exact",
                        "tree_present": True,
                    },
                    "cosmos_cache": {
                        "state": "locked_exact",
                        "tree_present": True,
                    },
                },
            },
            "artifacts": {
                "edge_snapshot": {"state": "candidate_present_unlocked"},
                "cosmos_cache": {"state": "candidate_present_unlocked"},
                "exact_tree_verification": {"state": "exact_match"},
            },
            "images": {
                "edge_vllm": {
                    "state": "present_exact",
                    "reference": rd.EDGE_VLLM_REFERENCE,
                    "image_id": rd.EDGE_VLLM_IMAGE_ID,
                    "contract_lock": {"state": "locked_exact"},
                },
                "rt_vlm": {
                    "state": "present_exact",
                    "reference": rd.RT_VLM_REFERENCE,
                    "image_id": rd.RT_VLM_IMAGE_ID,
                    "contract_lock": {"state": "locked_exact"},
                },
            },
            "memory": {"state": "pass"},
            "disk": {
                "state": "pass_no_additional_staging_required",
                "capacity_qualified": True,
                "required_additional_bytes": 0,
            },
            "containers": {},
            "blockers": [
                {
                    "id": "runtime.not_performed",
                    "state": "unverified",
                    "detail": "Prelaunch readiness is not runtime qualification.",
                }
            ],
        }

    def test_read_only_result_cannot_claim_runtime_qualification(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        exact_image = {
            "state": "present_exact",
            "reference": "exact",
            "inspect_size_bytes": 1,
        }
        absent = {"state": "absent", "name": "container"}
        with (
            mock.patch.object(
                rd, "verify_source_locks", return_value={"state": "match"}
            ),
            mock.patch.object(
                rd,
                "inspect_artifact_lock",
                return_value={"lock_state": "incomplete_fail_closed"},
            ),
            mock.patch.object(
                rd,
                "inspect_edge_artifact",
                return_value={"state": "missing_exact_artifact"},
            ),
            mock.patch.object(
                rd,
                "inspect_cosmos_artifact",
                return_value={"state": "exact_cache_path_not_supplied"},
            ),
            mock.patch.object(
                rd,
                "inspect_volume",
                return_value={"state": "present_metadata_only_not_identity_evidence"},
            ),
            mock.patch.object(rd, "inspect_image", return_value=exact_image.copy()),
            mock.patch.object(
                rd, "inspect_mutable_tag", return_value={"state": "missing"}
            ),
            mock.patch.object(
                rd,
                "inspect_memory",
                return_value={"state": "blocked_below_admission_threshold"},
            ),
            mock.patch.object(rd, "inspect_disk", return_value={"state": "unknown"}),
            mock.patch.object(rd, "inspect_container", return_value=absent.copy()),
        ):
            result = rd.build_host_result(
                plan,
                hf_hub=Path("/hf"),
                cosmos_cache=None,
                meminfo=rd.DEFAULT_MEMINFO,
                disk_path=Path("/disk"),
            )
        self.assertEqual(result["qualification_state"], "blocked_not_runtime_qualified")
        self.assertFalse(result["runtime_qualification_performed"])
        self.assertTrue(
            any(
                item["id"] == "artifacts.lock_incomplete" for item in result["blockers"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "artifacts.exact_tree_verification"
                for item in result["blockers"]
            )
        )
        schema = rd._load_json(rd.HERE / "result.schema.json")
        jsonschema.Draft202012Validator(schema).validate(result)

    def test_host_readiness_rejects_fabricated_meminfo_path(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary) / "meminfo"
            fake.write_text(
                "MemTotal: 100000 kB\nMemAvailable: 100000 kB\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(rd.ReadinessError, "canonical /proc/meminfo"):
                rd.build_host_result(
                    plan,
                    hf_hub=Path("/hf"),
                    cosmos_cache=None,
                    meminfo=fake,
                    disk_path=Path("/disk"),
                )

    def test_complete_lock_and_candidates_still_block_on_tree_mismatch(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        exact_image = {"state": "present_exact", "reference": "exact"}
        running = {"state": "running", "name": "container"}
        with (
            mock.patch.object(
                rd, "verify_source_locks", return_value={"state": "match"}
            ),
            mock.patch.object(
                rd,
                "inspect_artifact_lock",
                return_value={"lock_state": "complete_exact"},
            ),
            mock.patch.object(
                rd,
                "inspect_edge_artifact",
                return_value={
                    "state": "candidate_present_unlocked",
                    "selected_candidate_path": "/hf/revision",
                },
            ),
            mock.patch.object(
                rd,
                "inspect_cosmos_artifact",
                return_value={"state": "candidate_present_unlocked"},
            ),
            mock.patch.object(
                rd,
                "verify_candidate_trees",
                return_value={"state": "mismatch_or_unqualified"},
            ),
            mock.patch.object(rd, "inspect_volume", return_value={"state": "missing"}),
            mock.patch.object(rd, "inspect_image", return_value=exact_image.copy()),
            mock.patch.object(
                rd, "inspect_mutable_tag", return_value={"state": "missing"}
            ),
            mock.patch.object(rd, "inspect_memory", return_value={"state": "pass"}),
            mock.patch.object(rd, "inspect_disk", return_value={"state": "unknown"}),
            mock.patch.object(rd, "inspect_container", return_value=running.copy()),
        ):
            result = rd.build_host_result(
                plan,
                hf_hub=Path("/hf"),
                cosmos_cache=Path("/cosmos"),
                meminfo=rd.DEFAULT_MEMINFO,
                disk_path=Path("/disk"),
            )
        self.assertEqual(result["qualification_state"], "blocked_not_runtime_qualified")
        self.assertTrue(
            any(
                item["id"] == "artifacts.exact_tree_verification"
                and item["state"] == "blocked"
                for item in result["blockers"]
            )
        )
        fabricated = json.loads(json.dumps(result))
        fabricated["qualification_state"] = "prelaunch_ready_not_runtime_qualified"
        fabricated["blockers"] = [
            item for item in fabricated["blockers"] if item["state"] != "blocked"
        ]
        schema = rd._load_json(rd.HERE / "result.schema.json")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(fabricated)

    def test_source_drift_prevents_loading_tree_verifier(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        exact_image = {"state": "present_exact", "reference": "exact"}
        with (
            mock.patch.object(
                rd, "verify_source_locks", return_value={"state": "drift"}
            ),
            mock.patch.object(
                rd,
                "inspect_artifact_lock",
                return_value={"lock_state": "complete_exact"},
            ),
            mock.patch.object(
                rd,
                "inspect_edge_artifact",
                return_value={
                    "state": "candidate_present_unlocked",
                    "selected_candidate_path": "/hf/revision",
                },
            ),
            mock.patch.object(
                rd,
                "inspect_cosmos_artifact",
                return_value={"state": "candidate_present_unlocked"},
            ),
            mock.patch.object(rd, "verify_candidate_trees") as verify,
            mock.patch.object(rd, "inspect_volume", return_value={"state": "missing"}),
            mock.patch.object(rd, "inspect_image", return_value=exact_image.copy()),
            mock.patch.object(
                rd, "inspect_mutable_tag", return_value={"state": "missing"}
            ),
            mock.patch.object(rd, "inspect_memory", return_value={"state": "pass"}),
            mock.patch.object(rd, "inspect_disk", return_value={"state": "unknown"}),
            mock.patch.object(
                rd, "inspect_container", return_value={"state": "running"}
            ),
        ):
            result = rd.build_host_result(
                plan,
                hf_hub=Path("/hf"),
                cosmos_cache=Path("/cosmos"),
                meminfo=rd.DEFAULT_MEMINFO,
                disk_path=Path("/disk"),
            )
        verify.assert_not_called()
        self.assertEqual(
            result["artifacts"]["exact_tree_verification"]["state"],
            "not_evaluated_source_lock_drift",
        )

    def test_schema_rejects_ready_claim_with_blocked_gate(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        result = rd.build_plan_result(plan)
        result["qualification_state"] = "prelaunch_ready_not_runtime_qualified"
        result["blockers"][0]["state"] = "blocked"
        schema = rd._load_json(rd.HERE / "result.schema.json")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(result)

    def test_schema_couples_plan_and_host_modes_to_qualification_state(self) -> None:
        schema = rd._load_json(rd.HERE / "result.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        plan = rd.build_plan_result(rd._load_json(rd.DEFAULT_PLAN))
        fabricated = deepcopy(plan)
        fabricated["qualification_state"] = "prelaunch_ready_not_runtime_qualified"
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(fabricated)
        ready = self._ready_result()
        ready["inspection_mode"] = "plan"
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(ready)

    def test_schema_requires_every_prelaunch_ready_gate(self) -> None:
        schema = rd._load_json(rd.HERE / "result.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        ready = self._ready_result()
        validator.validate(ready)

        mutations = [
            ("source_locks", "state", "drift"),
            ("artifact_lock", "lock_state", "incomplete_fail_closed"),
            ("memory", "state", "blocked_below_admission_threshold"),
            ("disk", "capacity_qualified", False),
        ]
        for section, key, value in mutations:
            fabricated = deepcopy(ready)
            fabricated[section][key] = value  # type: ignore[index]
            with self.subTest(section=section, key=key):
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate(fabricated)

        nested_mutations = [
            (["artifact_lock", "entries", "edge_snapshot", "state"], "missing"),
            (
                ["artifact_lock", "entries", "cosmos_cache", "tree_present"],
                False,
            ),
            (["artifacts", "exact_tree_verification", "state"], "mismatch"),
            (["images", "edge_vllm", "state"], "missing"),
            (["images", "edge_vllm", "image_id"], "sha256:" + "f" * 64),
            (["images", "edge_vllm", "contract_lock", "state"], "not_locked_exact"),
            (["images", "rt_vlm", "state"], "present_but_not_exact"),
        ]
        for path, value in nested_mutations:
            fabricated = deepcopy(ready)
            target = fabricated
            for key in path[:-1]:
                target = target[key]  # type: ignore[index,assignment]
            target[path[-1]] = value  # type: ignore[index]
            with self.subTest(path=path):
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate(fabricated)

    def test_disk_can_pass_only_after_every_staging_input_is_local(self) -> None:
        plan = rd._load_json(rd.DEFAULT_PLAN)
        with tempfile.TemporaryDirectory() as temporary:
            blocked = rd.inspect_disk(Path(temporary), plan, staging_complete=False)
            ready = rd.inspect_disk(Path(temporary), plan, staging_complete=True)
        self.assertFalse(blocked["capacity_qualified"])
        self.assertIsNone(blocked["required_additional_bytes"])
        self.assertTrue(ready["capacity_qualified"])
        self.assertEqual(ready["required_additional_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
