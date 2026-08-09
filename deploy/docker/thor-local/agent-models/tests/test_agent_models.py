from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_model_validator", ROOT / "validate.py"
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class AgentModelContractTests(unittest.TestCase):
    def test_official_oracle_digest_is_locked(self) -> None:
        self.assertEqual(
            VALIDATOR.OFFICIAL_ORACLE_SHA256,
            VALIDATOR.sha256(ROOT / "official-vss-3.2.1.json"),
        )

    def setUp(self) -> None:
        self.manifest = VALIDATOR.load_json(ROOT / "official-vss-3.2.1.json")
        self.state = VALIDATOR.load_json(ROOT / "thor-state.json")

    @staticmethod
    def _write_reviewed_json(root: Path, relative: str, value: object) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return VALIDATOR.sha256(path)

    def _qualify_exact_rows(self, root: Path, state: dict[str, object]) -> None:
        for index, row in enumerate(state["official_model_state"]):
            if row["kind"] not in {"llm", "vlm"}:
                continue
            model_id = row["model_id"]
            stem = f"deploy/docker/thor-local/agent-models/future/{index}"
            artifact_path = f"{stem}.artifact.json"
            backend_path = f"{stem}.backend.json"
            evidence_path = f"{stem}.evidence.json"
            artifact_root = root / "staged-artifacts" / str(index)
            artifact_root.mkdir(parents=True)
            (artifact_root / "weights.bin").write_bytes(
                f"exact weights for {model_id}".encode()
            )
            artifact_files = VALIDATOR._artifact_tree(
                artifact_root, artifact_root, model_id
            )
            common = {
                "schema_version": 1,
                "model_id": model_id,
                "release_commit": VALIDATOR.RELEASE_COMMIT,
                "target_commit": VALIDATOR.TARGET_MAIN_COMMIT,
                "state": "locked_exact",
            }
            artifact_digest = self._write_reviewed_json(
                root,
                artifact_path,
                {
                    **common,
                    "lock_type": "exact-agent-model-artifact",
                    "source": {
                        "kind": "huggingface_snapshot",
                        "model_id": model_id,
                        "uri": f"https://huggingface.co/{model_id}",
                        "revision": f"{index + 1:040x}",
                    },
                    "files": artifact_files,
                    "tree_sha256": VALIDATOR._canonical_sha256(artifact_files),
                    "checks": [
                        {"id": "source-identity", "result": "pass"},
                        {"id": "artifact-tree", "result": "pass"},
                    ],
                },
            )
            image = {
                "reference": f"nvcr.io/reviewed/backend@sha256:{index + 1:064x}",
                "repo_digest": f"nvcr.io/reviewed/backend@sha256:{index + 1:064x}",
                "image_id": f"sha256:{index + 2:064x}",
            }
            command = ["serve", "--model", model_id]
            environment = {"SERVED_MODEL_ID": model_id, "OFFLINE": "1"}
            backend_digest = self._write_reviewed_json(
                root,
                backend_path,
                {
                    **common,
                    "lock_type": "exact-agent-model-backend",
                    "image": image,
                    "command": command,
                    "environment": environment,
                    "contract_sha256": VALIDATOR._canonical_sha256(
                        {
                            "image": image,
                            "command": command,
                            "environment": environment,
                        }
                    ),
                    "checks": [
                        {"id": "image-identity", "result": "pass"},
                        {"id": "command-contract", "result": "pass"},
                        {"id": "environment-contract", "result": "pass"},
                    ],
                },
            )
            evidence = {
                "schema_version": 1,
                "model_id": model_id,
                "result": "passed_current",
                "release_commit": VALIDATOR.RELEASE_COMMIT,
                "target_commit": VALIDATOR.TARGET_MAIN_COMMIT,
                "captured_on": VALIDATOR.CAPTURED_ON,
                "artifact_lock_path": artifact_path,
                "artifact_lock_sha256": artifact_digest,
                "backend_lock_path": backend_path,
                "backend_lock_sha256": backend_digest,
                "collector": {
                    "id": "hand-authored-test-collector",
                    "sha256": "0" * 64,
                },
                "checks": [
                    {"id": "models-endpoint", "result": "pass"},
                    {"id": "served-model-identity", "result": "pass"},
                    {"id": "semantic-request", "result": "pass"},
                    {"id": "agent-workflow", "result": "pass"},
                ],
            }
            evidence_digest = self._write_reviewed_json(root, evidence_path, evidence)
            row.update(
                {
                    "exact_artifact_state": "staged-and-locked",
                    "artifact_lock_path": artifact_path,
                    "artifact_lock_sha256": artifact_digest,
                    "artifact_root_path": str(artifact_root),
                    "artifact_allowed_root_path": str(artifact_root),
                    "agent_backend_state": "staged-and-locked",
                    "backend_lock_path": backend_path,
                    "backend_lock_sha256": backend_digest,
                    "runtime_qualification": "qualified",
                    "evidence_path": evidence_path,
                    "evidence_sha256": evidence_digest,
                }
            )

    def test_checked_in_contract_is_valid_but_not_runtime_complete(self) -> None:
        errors = VALIDATOR.validate_manifest(self.manifest)
        state_errors, blockers = VALIDATOR.validate_state(self.state)
        self.assertEqual(errors, [])
        self.assertEqual(state_errors, [])
        self.assertEqual(len(blockers), 24)

    def test_cli_separates_canonical_thor_and_all_selector_gates(self) -> None:
        normal = subprocess.run(
            [sys.executable, str(ROOT / "validate.py")],
            check=False,
            capture_output=True,
            text=True,
        )
        thor_complete = subprocess.run(
            [sys.executable, str(ROOT / "validate.py"), "--require-thor-complete"],
            check=False,
            capture_output=True,
            text=True,
        )
        selectors_complete = subprocess.run(
            [
                sys.executable,
                str(ROOT / "validate.py"),
                "--require-all-selector-models-complete",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(thor_complete.returncode, 2)
        self.assertEqual(selectors_complete.returncode, 2)
        self.assertIn("Canonical official-edge pair blockers: 1", thor_complete.stdout)
        self.assertIn(
            "All-advertised-selector completeness blockers: 24",
            selectors_complete.stdout,
        )
        self.assertIn("canonical.runtime_evidence", thor_complete.stderr)
        self.assertIn("nvidia/nvidia-nemotron-nano-9b-v2", selectors_complete.stderr)

    def test_missing_local_llm_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.manifest)
        mutated["llm"]["local_models"].pop()
        self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_wrong_agent_defaults_are_rejected(self) -> None:
        for kind in ("llm", "vlm"):
            with self.subTest(kind=kind):
                mutated = copy.deepcopy(self.manifest)
                mutated[kind]["default_model_id"] = "wrong/default"
                self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_local_verification_semantics_cannot_be_promoted(self) -> None:
        mutated = copy.deepcopy(self.manifest)
        mutated["llm"]["local_models"][1]["official_local_verification"] = "verified"
        self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_named_remote_example_omission_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.manifest)
        mutated["vlm"]["remote_contract"]["named_examples"][
            "downloadable_nim_images"
        ].pop()
        self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_omni_setting_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.manifest)
        mutated["vlm"]["remote_contract"]["omni_vllm_settings"]["max_model_len"] = 8192
        self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_ambiguous_model_cannot_be_silently_resolved(self) -> None:
        mutated = copy.deepcopy(self.manifest)
        mutated["vlm"]["repository_only_or_ambiguous_local_references"][0][
            "resolved"
        ] = True
        self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_thor_official_boundary_cannot_be_promoted(self) -> None:
        mutated = copy.deepcopy(self.manifest)
        mutated["thor_platform_boundary"][
            "fully_local_all_agent_workflows_supported"
        ] = True
        self.assertTrue(VALIDATOR.validate_manifest(mutated))

    def test_state_must_cover_every_model(self) -> None:
        mutated = copy.deepcopy(self.state)
        mutated["official_model_state"].pop()
        errors, _ = VALIDATOR.validate_state(mutated)
        self.assertTrue(errors)

    def test_duplicate_state_row_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.state)
        mutated["official_model_state"].append(
            copy.deepcopy(mutated["official_model_state"][0])
        )
        errors, _ = VALIDATOR.validate_state(mutated)
        self.assertTrue(any("rows must be unique" in error for error in errors))

    def test_state_cannot_claim_runtime_qualification(self) -> None:
        mutated = copy.deepcopy(self.state)
        mutated["official_model_state"][0]["runtime_qualification"] = "qualified"
        errors, _ = VALIDATOR.validate_state(mutated)
        self.assertTrue(errors)

    def test_future_qualification_requires_lock_and_evidence_references(self) -> None:
        mutated = copy.deepcopy(self.state)
        row = mutated["official_model_state"][0]
        row["exact_artifact_state"] = "staged-and-locked"
        row["agent_backend_state"] = "staged-and-locked"
        row["runtime_qualification"] = "qualified"
        errors, _ = VALIDATOR.validate_state(mutated)
        self.assertTrue(any("artifact_lock_path" in error for error in errors))
        self.assertTrue(any("evidence_path" in error for error in errors))

    def test_nonexistent_reviewed_references_cannot_clear_complete_gate(self) -> None:
        mutated = copy.deepcopy(self.state)
        for row in mutated["official_model_state"]:
            if row["kind"] not in {"llm", "vlm"}:
                continue
            row.update(
                {
                    "exact_artifact_state": "staged-and-locked",
                    "artifact_lock_path": "deploy/docker/thor-local/does-not-exist.artifact.json",
                    "artifact_lock_sha256": "0" * 64,
                    "agent_backend_state": "staged-and-locked",
                    "backend_lock_path": "deploy/docker/thor-local/does-not-exist.backend.json",
                    "backend_lock_sha256": "0" * 64,
                    "runtime_qualification": "qualified",
                    "evidence_path": "deploy/docker/thor-local/does-not-exist.evidence.json",
                    "evidence_sha256": "0" * 64,
                }
            )
        errors, blockers = VALIDATOR.validate_state(mutated)
        self.assertTrue(any("does not exist" in error for error in errors))
        self.assertEqual(blockers, [])

    def test_hand_authored_pass_checks_cannot_clear_complete_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutated = copy.deepcopy(self.state)
            self._qualify_exact_rows(root, mutated)
            mutated["runtime_qualification"] = "qualified"
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, blockers = VALIDATOR.validate_state(mutated)
            self.assertEqual(blockers, [])
            self.assertTrue(
                any(
                    "no source-locked runtime evidence collector is approved" in error
                    for error in errors
                )
            )

            evidence_path = root / mutated["official_model_state"][0]["evidence_path"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["checks"][0]["result"] = "fail"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            row = mutated["official_model_state"][0]
            row["evidence_sha256"] = VALIDATOR.sha256(evidence_path)
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, _ = VALIDATOR.validate_state(mutated)
            self.assertTrue(any("did not pass" in error for error in errors))

    def test_placeholder_artifact_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutated = copy.deepcopy(self.state)
            self._qualify_exact_rows(root, mutated)
            row = mutated["official_model_state"][0]
            artifact_path = root / row["artifact_lock_path"]
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["source"]["uri"] = "https://huggingface.co/example/model"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            row["artifact_lock_sha256"] = VALIDATOR.sha256(artifact_path)
            evidence_path = root / row["evidence_path"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["artifact_lock_sha256"] = row["artifact_lock_sha256"]
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            row["evidence_sha256"] = VALIDATOR.sha256(evidence_path)
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, _ = VALIDATOR.validate_state(mutated)
            self.assertTrue(
                any(
                    "source URI must bind the exact model identity" in error
                    for error in errors
                )
            )

    def test_placeholder_backend_registry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutated = copy.deepcopy(self.state)
            self._qualify_exact_rows(root, mutated)
            row = mutated["official_model_state"][0]
            backend_path = root / row["backend_lock_path"]
            backend = json.loads(backend_path.read_text(encoding="utf-8"))
            placeholder = "registry.invalid/backend@sha256:" + "1" * 64
            backend["image"]["reference"] = placeholder
            backend["image"]["repo_digest"] = placeholder
            backend["contract_sha256"] = VALIDATOR._canonical_sha256(
                {
                    "image": backend["image"],
                    "command": backend["command"],
                    "environment": backend["environment"],
                }
            )
            backend_path.write_text(json.dumps(backend), encoding="utf-8")
            row["backend_lock_sha256"] = VALIDATOR.sha256(backend_path)
            evidence_path = root / row["evidence_path"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["backend_lock_sha256"] = row["backend_lock_sha256"]
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            row["evidence_sha256"] = VALIDATOR.sha256(evidence_path)
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, _ = VALIDATOR.validate_state(mutated)
            self.assertTrue(any("placeholder registry" in error for error in errors))

    def test_qualified_rows_require_qualified_aggregate_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutated = copy.deepcopy(self.state)
            self._qualify_exact_rows(root, mutated)
            self.assertEqual(mutated["runtime_qualification"], "not-run")
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, blockers = VALIDATOR.validate_state(mutated)
            self.assertEqual(blockers, [])
            self.assertTrue(
                any("aggregate state is not qualified" in error for error in errors)
            )
            self.assertTrue(
                any(
                    "no source-locked runtime evidence collector" in error
                    for error in errors
                )
            )

    def test_artifact_tree_mutation_cannot_clear_complete_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutated = copy.deepcopy(self.state)
            self._qualify_exact_rows(root, mutated)
            mutated["runtime_qualification"] = "qualified"
            row = mutated["official_model_state"][0]
            artifact_root = Path(row["artifact_root_path"])
            (artifact_root / "weights.bin").write_bytes(b"mutated after lock review")
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, blockers = VALIDATOR.validate_state(mutated)
            self.assertEqual(blockers, [])
            self.assertTrue(any("artifact tree differs" in error for error in errors))

    def test_backend_contract_digest_bypass_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutated = copy.deepcopy(self.state)
            self._qualify_exact_rows(root, mutated)
            mutated["runtime_qualification"] = "qualified"
            row = mutated["official_model_state"][0]
            backend_path = root / row["backend_lock_path"]
            backend = json.loads(backend_path.read_text(encoding="utf-8"))
            backend["command"] = ["serve", "--wrong-model", row["model_id"]]
            backend_path.write_text(json.dumps(backend), encoding="utf-8")
            row["backend_lock_sha256"] = VALIDATOR.sha256(backend_path)
            evidence_path = root / row["evidence_path"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["backend_lock_sha256"] = row["backend_lock_sha256"]
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            row["evidence_sha256"] = VALIDATOR.sha256(evidence_path)
            with mock.patch.object(VALIDATOR, "REPO_ROOT", root):
                errors, blockers = VALIDATOR.validate_state(mutated)
            self.assertEqual(blockers, [])
            self.assertTrue(any("contract digest differs" in error for error in errors))

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schema_version": 1, "schema_version": 2}', encoding="utf-8"
            )
            with self.assertRaises(VALIDATOR.DuplicateKeyError):
                VALIDATOR.load_json(path)

    def test_cli_rejects_mutated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            state_path = Path(directory) / "state.json"
            mutated = copy.deepcopy(self.manifest)
            mutated["llm"]["remote_contract"]["named_examples"]["hosted_nim"].pop()
            manifest_path.write_text(json.dumps(mutated), encoding="utf-8")
            state_path.write_text(json.dumps(self.state), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "validate.py"),
                    "--manifest",
                    str(manifest_path),
                    "--state",
                    str(state_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("[ERROR]", result.stderr)


if __name__ == "__main__":
    unittest.main()
