from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import official_edge as oe  # noqa: E402


class OfficialEdgeStaticTests(unittest.TestCase):
    def test_checked_in_static_contract_is_source_anchored(self) -> None:
        contract = oe.verify_static()
        self.assertEqual(contract["llm"]["served_model_id"], oe.EDGE_MODEL_ID)
        self.assertEqual(contract["vlm"]["artifact_id"], oe.COSMOS_ARTIFACT)

    def test_versioned_docs_win_and_older_skill_model_stays_unqualified(self) -> None:
        contract = oe._load_json(oe.DEFAULT_CONTRACT)
        discrepancy = contract["documentation_discrepancy"]
        self.assertEqual(
            contract["versioned_documentation"]["llm_repository"], oe.EDGE_MODEL_ID
        )
        self.assertNotEqual(discrepancy["checkout_skill_model"], oe.EDGE_MODEL_ID)
        self.assertEqual(discrepancy["checkout_skill_state"], "older_fallback_unqualified")
        self.assertEqual(
            contract["images"]["edge4b_vllm"]["state"],
            "missing_exact_image_unqualified",
        )
        self.assertIsNone(contract["images"]["edge4b_vllm"]["image_id"])

    def test_json_loader_rejects_duplicate_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"contract_id":"first","contract_id":"second"}\n')
            with self.assertRaisesRegex(oe.ContractError, "duplicate object key"):
                oe._load_json(path)

    def test_checked_in_lock_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(oe.ContractError, "intentionally incomplete"):
                oe.verify_artifacts(oe.DEFAULT_ARTIFACT_LOCK, root / "edge", root / "cosmos")

    def test_memory_gate_enforces_combined_eighty_percent(self) -> None:
        contract = oe._load_json(oe.DEFAULT_CONTRACT)
        with tempfile.TemporaryDirectory() as temporary:
            meminfo = Path(temporary) / "meminfo"
            meminfo.write_text(
                "MemTotal:       100000 kB\nMemAvailable:    80000 kB\n",
                encoding="utf-8",
            )
            oe.verify_memory(contract, meminfo)
            meminfo.write_text(
                "MemTotal:       100000 kB\nMemAvailable:    79999 kB\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(oe.ContractError, "0.25 Edge4B"):
                oe.verify_memory(contract, meminfo)

    def test_pull_free_renderer_is_inert(self) -> None:
        command = oe.render_pull_free_command(
            oe.DEFAULT_RUNTIME_ENV, Path("/verified/edge"), Path("/verified/cosmos")
        )
        self.assertIn("--no-build", command)
        self.assertIn("--pull never", command)
        self.assertNotIn("docker pull", command)
        self.assertNotIn("docker build", command)
        self.assertTrue(command.endswith("up -d --no-build --pull never"))
        self.assertIn("THOR_OFFICIAL_EDGE4B_SNAPSHOT=/verified/edge", command)
        self.assertIn("THOR_OFFICIAL_COSMOS3_CACHE_DIR=/verified/cosmos", command)

    def test_renderer_cli_fails_before_printing_command_with_incomplete_lock(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = oe.main(
                [
                    "--edge4b-snapshot",
                    "/missing/edge",
                    "--cosmos3-cache",
                    "/missing/cosmos",
                    "render-command",
                ]
            )
        self.assertEqual(result, 1)
        self.assertNotIn("docker compose", output.getvalue())
        self.assertIn("intentionally incomplete", errors.getvalue())

    def test_tracked_fixture_resolves_only_official_model_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edge = root / "edge"
            cosmos = root / "cosmos"
            edge.mkdir()
            cosmos.mkdir()
            tracked_env = (
                oe.DEPLOY_DOCKER
                / "developer-profiles/dev-profile-thor-full/.env"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "VSS_APPS_DIR": str(oe.DEPLOY_DOCKER),
                    "VSS_DATA_DIR": str(oe.DEPLOY_DOCKER / "data-dir"),
                },
                clear=False,
            ):
                resolved = oe.verify_resolved_compose(tracked_env, edge, cosmos)
        self.assertIn("nemotron-edge", resolved["services"])
        self.assertNotIn("qwen3-vl-8b-instruct", resolved["services"])

    def test_image_gate_requires_id_and_repository_digest(self) -> None:
        contract = oe._load_json(oe.DEFAULT_CONTRACT)
        with self.assertRaisesRegex(oe.ContractError, "not locked_exact"):
            oe.verify_images(contract)

        contract = deepcopy(contract)
        contract["images"]["edge4b_vllm"]["state"] = "locked_exact"
        contract["images"]["edge4b_vllm"]["image_id"] = "sha256:edge-config-id"

        def inspect(command: list[str], **_: object) -> str:
            reference = command[-1]
            for entry in contract["images"].values():
                if entry["reference"] == reference:
                    return f'{entry["image_id"]}|{json.dumps([reference])}\n'
            raise AssertionError(reference)

        with mock.patch.object(oe, "_run", side_effect=inspect):
            oe.verify_images(contract)

        def wrong_digest(command: list[str], **_: object) -> str:
            return f'sha256:edge-config-id|{json.dumps(["wrong@sha256:digest"])}\n'

        with mock.patch.object(oe, "_run", side_effect=wrong_digest):
            with self.assertRaises(oe.ContractError):
                oe.verify_images(contract)


class OfficialEdgeArtifactTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        revision = "a" * 40
        repository = root / "models--nvidia--edge"
        snapshot = repository / "snapshots" / revision
        blobs = repository / "blobs"
        snapshot.mkdir(parents=True)
        blobs.mkdir()
        blob = blobs / "weights"
        blob.write_bytes(b"edge-weights")
        (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
        (snapshot / "model.safetensors").symlink_to("../../blobs/weights")

        cosmos = root / "cosmos-cache"
        (cosmos / "model").mkdir(parents=True)
        (cosmos / "model" / "weights.bin").write_bytes(b"cosmos-weights")
        lock = root / "lock.json"
        payload = {
            "schema_version": 1,
            "lock_state": "complete_exact",
            "artifacts": {
                "edge4b": {
                    "kind": "huggingface_snapshot",
                    "identity": {
                        "repository": oe.EDGE_REPOSITORY,
                        "revision": revision,
                    },
                    "state": "locked_exact",
                    "tree": {
                        "entry_count": 0,
                        "entries": oe._actual_tree_entries(snapshot, repository),
                    },
                },
                "cosmos3_nano_bf16": {
                    "kind": "ngc_model_cache",
                    "identity": {"artifact_id": oe.COSMOS_ARTIFACT},
                    "state": "locked_exact",
                    "tree": {
                        "entry_count": 0,
                        "entries": oe._actual_tree_entries(cosmos, cosmos),
                    },
                },
            },
        }
        for artifact in payload["artifacts"].values():
            artifact["tree"]["entry_count"] = len(artifact["tree"]["entries"])
        lock.write_text(json.dumps(payload), encoding="utf-8")
        return lock, snapshot, cosmos

    def test_exact_locked_trees_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            oe.verify_artifacts(lock, snapshot, cosmos)

    def test_changed_content_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            (cosmos / "model" / "weights.bin").write_bytes(b"changed")
            with self.assertRaisesRegex(oe.ContractError, "tree differs"):
                oe.verify_artifacts(lock, snapshot, cosmos)

    def test_extra_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            (snapshot / "unreviewed.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(oe.ContractError, "extra=.*unreviewed"):
                oe.verify_artifacts(lock, snapshot, cosmos)

    def test_symlink_escape_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            artifact.mkdir()
            outside = root / "outside"
            outside.write_bytes(b"secret")
            (artifact / "escape").symlink_to(outside)
            with self.assertRaisesRegex(oe.ContractError, "absolute artifact symlink"):
                oe._actual_tree_entries(artifact, artifact)
            (artifact / "escape").unlink()
            (artifact / "escape").symlink_to("../outside")
            with self.assertRaisesRegex(oe.ContractError, "escapes repository"):
                oe._actual_tree_entries(artifact, artifact)

    def test_artifact_root_symlink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual"
            actual.mkdir()
            alias = root / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(oe.ContractError, "real directory"):
                oe._actual_tree_entries(alias, root)

    def test_unsafe_and_duplicate_lock_paths_fail(self) -> None:
        unsafe = {
            "entry_count": 1,
            "entries": [{"path": "../escape", "type": "directory"}],
        }
        with self.assertRaisesRegex(oe.ContractError, "unsafe"):
            oe._validate_expected_tree(unsafe, "test")
        duplicate = {
            "entry_count": 2,
            "entries": [
                {"path": "a", "type": "directory"},
                {"path": "a", "type": "directory"},
            ],
        }
        with self.assertRaisesRegex(oe.ContractError, "duplicate"):
            oe._validate_expected_tree(duplicate, "test")


class OfficialEdgeReadinessTests(unittest.TestCase):
    def test_exact_model_ids_and_container_contract_pass(self) -> None:
        edge_container = {
            "Image": "sha256:edge-config-id",
            "State": {"Running": True},
            "Config": {
                "Image": oe.EDGE_IMAGE,
                "Cmd": oe.EDGE_COMMAND,
                "Env": ["HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1"],
            },
        }
        rtvlm_container = {
            "Image": oe.RTVLM_IMAGE_ID,
            "State": {"Running": True},
            "Config": {
                "Image": oe.RTVLM_IMAGE,
                "Cmd": [],
                "Env": [
                    "VLM_MODEL_TO_USE=cosmos-reason3",
                    f"MODEL_PATH={oe.COSMOS_ARTIFACT}",
                    f"VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME={oe.COSMOS_MODEL_ID}",
                    "VLLM_GPU_MEMORY_UTILIZATION=0.35",
                    "NGC_API_KEY=",
                ],
            },
        }

        application_containers = {
            "vss-agent": {
                "Image": "sha256:agent",
                "State": {"Running": True},
                "Config": {
                    "Image": "agent",
                    "Cmd": [oe.AGENT_CONFIG_CONTAINER],
                    "Env": [
                        "LLM_MODE=remote",
                        "LLM_MODEL_TYPE=vllm",
                        f"LLM_NAME={oe.EDGE_MODEL_ID}",
                        f"LLM_BASE_URL={oe.EDGE_BASE_URL}",
                        "VLM_MODE=local_shared",
                        "VLM_MODEL_TYPE=rtvi",
                        f"VLM_NAME={oe.COSMOS_MODEL_ID}",
                        f"VLM_BASE_URL={oe.COSMOS_BASE_URL}",
                        f"VSS_AGENT_CONFIG_FILE={oe.AGENT_CONFIG_CONTAINER}",
                        f"EVAL_LLM_JUDGE_NAME={oe.EDGE_MODEL_ID}",
                        f"EVAL_LLM_JUDGE_BASE_URL={oe.EDGE_BASE_URL}",
                    ],
                },
            },
            "vss-lvs": {
                "Image": "sha256:lvs",
                "State": {"Running": True},
                "Config": {
                    "Image": "lvs",
                    "Cmd": [],
                    "Env": [
                        f"LVS_LLM_MODEL_NAME={oe.EDGE_MODEL_ID}",
                        f"LVS_LLM_BASE_URL={oe.EDGE_BASE_URL}/v1",
                        "LVS_LLM_MODEL_TYPE=vllm",
                        f"VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME={oe.COSMOS_MODEL_ID}",
                    ],
                },
            },
            "vss-va-mcp": {
                "Image": "sha256:mcp",
                "State": {"Running": True},
                "Config": {
                    "Image": "mcp",
                    "Cmd": [],
                    "Env": [
                        "LLM_MODEL_TYPE=vllm",
                        f"LLM_NAME={oe.EDGE_MODEL_ID}",
                        f"LLM_BASE_URL={oe.EDGE_BASE_URL}",
                    ],
                },
            },
            "vss-alert-bridge": {
                "Image": "sha256:alert",
                "State": {"Running": True},
                "Config": {
                    "Image": "alert",
                    "Cmd": [],
                    "Env": [
                        f"VLM_NAME={oe.COSMOS_MODEL_ID}",
                        f"VLM_BASE_URL={oe.COSMOS_BASE_URL}",
                        "VLM_MODE=local_shared",
                    ],
                },
            },
        }

        def container(name: str) -> dict[str, object]:
            if name == "vss-nemotron-edge-4b":
                return edge_container
            if name == "vss-rtvi-vlm":
                return rtvlm_container
            return application_containers[name]

        def response(url: str, _: float) -> object:
            if url.endswith("/v1/models"):
                model_id = oe.EDGE_MODEL_ID if "30081" in url else oe.COSMOS_MODEL_ID
                return {"data": [{"id": model_id}]}
            return {"status": "ok"}

        with (
            mock.patch.object(oe, "_docker_container", side_effect=container),
            mock.patch.object(oe, "_get_json", side_effect=response),
        ):
            contract = oe._load_json(oe.DEFAULT_CONTRACT)
            contract["images"]["edge4b_vllm"]["image_id"] = "sha256:edge-config-id"
            oe.verify_readiness(contract, 1.0)

    def test_alias_model_id_is_rejected(self) -> None:
        with mock.patch.object(
            oe,
            "_get_json",
            return_value={"data": [{"id": "nvidia/cosmos3-nano-reasoner"}]},
        ):
            with self.assertRaisesRegex(oe.ContractError, "expected only"):
                oe._verify_model_endpoint(oe.COSMOS_BASE_URL, oe.COSMOS_MODEL_ID, 1.0)


if __name__ == "__main__":
    unittest.main()
