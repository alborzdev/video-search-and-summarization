from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
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
        self.assertEqual(len(result["files"]), 7)

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
        self.assertIsNone(remote["cosmos3_nano_bf16"]["total_bytes"])
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
            revision = "a" * 40
            repository = root / "models--nvidia--nemotron"
            snapshot = repository / "snapshots" / revision
            snapshot.mkdir(parents=True)
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
                        "tree": {
                            "entries": verifier._actual_tree_entries(
                                snapshot, repository
                            )
                        },
                    },
                    "cosmos3_nano_bf16": {
                        "kind": "ngc_model_cache",
                        "identity": {"artifact_id": verifier.COSMOS_ARTIFACT},
                        "state": "locked_exact",
                        "tree": {
                            "entries": verifier._actual_tree_entries(cosmos, cosmos)
                        },
                    },
                },
            }
            for entry in payload["artifacts"].values():
                entry["tree"]["entry_count"] = len(entry["tree"]["entries"])
            lock.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                rd.verify_candidate_trees(lock, snapshot, cosmos)["state"],
                "exact_match",
            )
            (snapshot / "config.json").write_text("tampered\n", encoding="utf-8")
            result = rd.verify_candidate_trees(lock, snapshot, cosmos)
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
                "sha256:image-id",
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

    def test_missing_container_is_classified_as_absent(self) -> None:
        with mock.patch.object(
            rd,
            "_docker",
            return_value=("", "Error response from daemon: No such container: exact"),
        ):
            result = rd.inspect_container("exact", "image@sha256:digest")
        self.assertEqual(result["state"], "absent")


class HostResultTests(unittest.TestCase):
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
                meminfo=Path("/meminfo"),
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
                meminfo=Path("/meminfo"),
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
                meminfo=Path("/meminfo"),
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


if __name__ == "__main__":
    unittest.main()
