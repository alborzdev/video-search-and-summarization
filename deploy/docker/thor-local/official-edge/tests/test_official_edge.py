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


def make_edge_cache(root: Path) -> tuple[Path, Path]:
    repository = root / oe.EDGE_CACHE_DIRECTORY
    snapshot = repository / "snapshots" / oe.EDGE_REVISION
    blobs = repository / "blobs"
    snapshot.mkdir(parents=True)
    blobs.mkdir()
    blob_name = "a" * 64
    (blobs / blob_name).write_bytes(b"edge-weights")
    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.safetensors").symlink_to(f"../../blobs/{blob_name}")
    return snapshot, blobs


def reviewed_provenance(
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
        "evidence_sha256": oe._sha256_file(path),
        "reviewed_by": "unit-test-trust-root",
    }


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
        self.assertEqual(
            discrepancy["checkout_skill_state"], "older_fallback_unqualified"
        )
        self.assertEqual(
            contract["images"]["edge4b_vllm"]["state"],
            "locked_exact",
        )
        self.assertEqual(
            contract["images"]["edge4b_vllm"]["image_id"],
            oe.EDGE_IMAGE_MANIFEST_DIGEST,
        )
        self.assertEqual(
            contract["images"]["edge4b_vllm"]["manifest_config_digest"],
            oe.EDGE_IMAGE_CONFIG_DIGEST,
        )

    def test_exact_edge_image_contract_can_graduate_but_not_claim_wrong_id(
        self,
    ) -> None:
        contract = deepcopy(oe._load_json(oe.DEFAULT_CONTRACT))
        image = contract["images"]["edge4b_vllm"]
        image["state"] = "locked_exact"
        image["image_id"] = oe.EDGE_IMAGE_CONFIG_DIGEST
        oe.verify_contract_identity(contract)

        image["image_id"] = oe.EDGE_IMAGE_MANIFEST_DIGEST
        oe.verify_contract_identity(contract)

        image["image_id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(oe.ContractError, "manifest or manifest config"):
            oe.verify_contract_identity(contract)

    def test_thor_operator_guidance_routes_to_exact_current_contract(self) -> None:
        contract = oe._load_json(oe.DEFAULT_CONTRACT)
        oe.verify_operator_guidance(contract)
        guidance = oe.THOR_OPERATOR_GUIDANCE.read_text(encoding="utf-8")
        self.assertIn(oe.EDGE_MODEL_ID, guidance)
        self.assertIn(oe.COSMOS_ARTIFACT, guidance)
        self.assertIn("MUST NOT run its AGX/IGX Thor model command", guidance)

    def test_thor_operator_guidance_rejects_current_model_drift(self) -> None:
        contract = oe._load_json(oe.DEFAULT_CONTRACT)
        with tempfile.TemporaryDirectory() as temporary:
            drifted = Path(temporary) / "thor-official-edge.md"
            guidance = oe.THOR_OPERATOR_GUIDANCE.read_text(encoding="utf-8")
            drifted.write_text(
                guidance.replace(oe.EDGE_MODEL_ID, "nvidia/drifted-model"),
                encoding="utf-8",
            )
            with mock.patch.object(oe, "THOR_OPERATOR_GUIDANCE", drifted):
                with self.assertRaisesRegex(
                    oe.ContractError, "operator precedence guidance is incomplete"
                ):
                    oe.verify_operator_guidance(contract)

    def test_json_loader_rejects_duplicate_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"contract_id":"first","contract_id":"second"}\n')
            with self.assertRaisesRegex(oe.ContractError, "duplicate object key"):
                oe._load_json(path)

    def test_checked_in_lock_is_complete_and_exact(self) -> None:
        lock = oe._load_json(oe.DEFAULT_ARTIFACT_LOCK)
        self.assertEqual(lock["lock_state"], "complete_exact")
        self.assertEqual(
            {entry["state"] for entry in lock["artifacts"].values()},
            {"locked_exact"},
        )

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
        with tempfile.TemporaryDirectory() as temporary:
            edge, blobs = make_edge_cache(Path(temporary))
            command = oe.render_pull_free_command(
                oe.DEFAULT_RUNTIME_ENV, edge, Path("/verified/cosmos")
            )
        self.assertIn("--no-build", command)
        self.assertIn("--pull never", command)
        self.assertNotIn("docker pull", command)
        self.assertNotIn("docker build", command)
        self.assertTrue(command.endswith("up -d --no-build --pull never"))
        self.assertIn(f"THOR_OFFICIAL_EDGE4B_SNAPSHOT={edge}", command)
        self.assertIn(f"THOR_OFFICIAL_EDGE4B_BLOBS_DIR={blobs}", command)
        self.assertIn("THOR_OFFICIAL_COSMOS3_CACHE_DIR=/verified/cosmos", command)

    def test_renderer_cli_fails_before_printing_command_with_incomplete_lock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            incomplete = Path(temporary) / "artifacts.lock.json"
            payload = oe._load_json(oe.DEFAULT_ARTIFACT_LOCK)
            payload["lock_state"] = "incomplete_fail_closed"
            incomplete.write_text(json.dumps(payload), encoding="utf-8")
            output = io.StringIO()
            errors = io.StringIO()
            with (
                mock.patch.object(oe, "DEFAULT_ARTIFACT_LOCK", incomplete),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
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
            edge, _ = make_edge_cache(root)
            cosmos = root / "cosmos"
            cosmos.mkdir()
            tracked_env = (
                oe.DEPLOY_DOCKER / "developer-profiles/dev-profile-thor-full/.env"
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

    def test_resolved_compose_rejects_credentials_and_shadow_mounts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edge, _ = make_edge_cache(root)
            cosmos = root / "cosmos"
            cosmos.mkdir()
            tracked_env = (
                oe.DEPLOY_DOCKER / "developer-profiles/dev-profile-thor-full/.env"
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

            leaked = deepcopy(resolved)
            leaked["services"]["nemotron-edge"]["environment"]["HF_TOKEN"] = "secret"
            with (
                mock.patch.object(oe, "_run", return_value=json.dumps(leaked)),
                self.assertRaisesRegex(oe.ContractError, "credential environment"),
            ):
                oe.verify_resolved_compose(tracked_env, edge, cosmos)

            shadowed = deepcopy(resolved)
            shadowed["services"]["nemotron-edge"]["volumes"].append(
                {
                    "type": "bind",
                    "source": str(root),
                    "target": "/models/edge4b/config.json",
                    "read_only": False,
                }
            )
            with (
                mock.patch.object(oe, "_run", return_value=json.dumps(shadowed)),
                self.assertRaisesRegex(oe.ContractError, "shadow mounts"),
            ):
                oe.verify_resolved_compose(tracked_env, edge, cosmos)

            consumer_leak = deepcopy(resolved)
            consumer_leak["services"]["vss-agent"]["environment"][
                "OPENAI_API_KEY"
            ] = "secret"
            with (
                mock.patch.object(oe, "_run", return_value=json.dumps(consumer_leak)),
                self.assertRaisesRegex(oe.ContractError, "credential environment"),
            ):
                oe.verify_resolved_compose(tracked_env, edge, cosmos)

            config_shadow = deepcopy(resolved)
            config_shadow["services"]["vss-agent"]["volumes"].append(
                {
                    "type": "bind",
                    "source": str(root),
                    "target": oe.AGENT_CONFIG_CONTAINER,
                    "read_only": False,
                }
            )
            with (
                mock.patch.object(oe, "_run", return_value=json.dumps(config_shadow)),
                self.assertRaisesRegex(
                    oe.ContractError,
                    "duplicate mount destinations|shadow mounts|config shadow mount",
                ),
            ):
                oe.verify_resolved_compose(tracked_env, edge, cosmos)

    def test_image_gate_requires_id_and_repository_digest(self) -> None:
        contract = deepcopy(oe._load_json(oe.DEFAULT_CONTRACT))
        contract["images"]["edge4b_vllm"]["state"] = "missing_exact_image_unqualified"
        contract["images"]["edge4b_vllm"]["image_id"] = None
        with self.assertRaisesRegex(oe.ContractError, "not locked_exact"):
            oe.verify_images(contract)

        contract["images"]["edge4b_vllm"]["state"] = "locked_exact"
        contract["images"]["edge4b_vllm"]["image_id"] = oe.EDGE_IMAGE_MANIFEST_DIGEST

        def inspect(command: list[str], **_: object) -> str:
            reference = command[-1]
            for entry in contract["images"].values():
                if entry["reference"] == reference:
                    return f"{entry['image_id']}|{json.dumps([reference])}\n"
            raise AssertionError(reference)

        with mock.patch.object(oe, "_run", side_effect=inspect):
            oe.verify_images(contract)

        def wrong_digest(command: list[str], **_: object) -> str:
            return f"sha256:edge-config-id|{json.dumps(['wrong@sha256:digest'])}\n"

        with mock.patch.object(oe, "_run", side_effect=wrong_digest):
            with self.assertRaises(oe.ContractError):
                oe.verify_images(contract)


class OfficialEdgeArtifactTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        revision = oe.EDGE_REVISION
        repository = root / oe.EDGE_CACHE_DIRECTORY
        snapshot = repository / "snapshots" / revision
        blobs = repository / "blobs"
        snapshot.mkdir(parents=True)
        blobs.mkdir()
        blob_name = "a" * 64
        blob = blobs / blob_name
        blob.write_bytes(b"edge-weights")
        (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
        (snapshot / "model.safetensors").symlink_to(f"../../blobs/{blob_name}")

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
                    "provenance": reviewed_provenance(
                        root,
                        "edge.json",
                        {"repository": oe.EDGE_REPOSITORY, "revision": revision},
                    ),
                    "tree": {
                        "entry_count": 0,
                        "entries": oe._actual_tree_entries(snapshot, repository),
                    },
                    "blob_tree": {
                        "entry_count": 0,
                        "entries": oe._actual_tree_entries(blobs, blobs),
                    },
                },
                "cosmos3_nano_bf16": {
                    "kind": "ngc_model_cache",
                    "identity": {"artifact_id": oe.COSMOS_ARTIFACT},
                    "state": "locked_exact",
                    "provenance": reviewed_provenance(
                        root, "cosmos.json", {"artifact_id": oe.COSMOS_ARTIFACT}
                    ),
                    "tree": {
                        "entry_count": 0,
                        "entries": oe._actual_tree_entries(cosmos, cosmos),
                    },
                },
            },
        }
        for artifact in payload["artifacts"].values():
            artifact["tree"]["entry_count"] = len(artifact["tree"]["entries"])
        payload["artifacts"]["edge4b"]["blob_tree"]["entry_count"] = len(
            payload["artifacts"]["edge4b"]["blob_tree"]["entries"]
        )
        lock.write_text(json.dumps(payload), encoding="utf-8")
        return lock, snapshot, cosmos

    def test_exact_locked_trees_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            oe.verify_artifacts(lock, snapshot, cosmos, provenance_root=Path(temporary))

    def test_changed_content_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            (cosmos / "model" / "weights.bin").write_bytes(b"changed")
            with self.assertRaisesRegex(oe.ContractError, "tree differs"):
                oe.verify_artifacts(
                    lock, snapshot, cosmos, provenance_root=Path(temporary)
                )

    def test_extra_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            (snapshot / "unreviewed.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(oe.ContractError, "extra=.*unreviewed"):
                oe.verify_artifacts(
                    lock, snapshot, cosmos, provenance_root=Path(temporary)
                )

    def test_unreferenced_mounted_blob_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            (snapshot.parent.parent / "blobs" / ("b" * 64)).write_bytes(b"extra")
            with self.assertRaisesRegex(oe.ContractError, "mounted blob tree differs"):
                oe.verify_artifacts(
                    lock, snapshot, cosmos, provenance_root=Path(temporary)
                )

    def test_local_tree_without_reviewed_provenance_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock, snapshot, cosmos = self._fixture(Path(temporary))
            payload = json.loads(lock.read_text(encoding="utf-8"))
            payload["artifacts"]["cosmos3_nano_bf16"]["provenance"] = {
                "state": "local_bytes_only_not_independently_verified",
                "promotion_requires": "reviewed_upstream_identity_and_hash_evidence",
            }
            lock.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(oe.ContractError, "provenance"):
                oe.verify_artifacts(
                    lock, snapshot, cosmos, provenance_root=Path(temporary)
                )

    def test_asserted_provenance_without_bound_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock, snapshot, cosmos = self._fixture(root)
            payload = json.loads(lock.read_text(encoding="utf-8"))
            provenance = payload["artifacts"]["cosmos3_nano_bf16"]["provenance"]
            provenance["evidence_path"] = (
                "deploy/docker/thor-local/official-edge/provenance/missing.json"
            )
            provenance["evidence_sha256"] = "f" * 64
            provenance["reviewed_by"] = "arbitrary"
            lock.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(oe.ContractError, "cannot resolve"):
                oe.verify_artifacts(lock, snapshot, cosmos, provenance_root=root)

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

    def test_noncanonical_hf_symlink_target_fails_even_when_bytes_are_local(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, blobs = make_edge_cache(root)
            (snapshot / "model.safetensors").unlink()
            (blobs / "weights").write_bytes(b"other")
            (snapshot / "model.safetensors").symlink_to("../../blobs/weights")
            entries = oe._actual_tree_entries(snapshot, snapshot.parent.parent)
            with self.assertRaisesRegex(oe.ContractError, "canonical HF blob target"):
                oe._verify_edge_snapshot_layout(snapshot, entries)

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
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edge_snapshot, edge_blobs = make_edge_cache(root)
            cosmos_cache = root / "cosmos"
            cosmos_cache.mkdir()
            edge_container = {
                "Image": oe.EDGE_IMAGE_CONFIG_DIGEST,
                "State": {"Running": True},
                "Config": {
                    "Image": oe.EDGE_IMAGE,
                    "Cmd": oe.EDGE_COMMAND,
                    "Env": ["HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1"],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(edge_snapshot),
                        "Destination": "/models/edge4b",
                        "RW": False,
                    },
                    {
                        "Type": "bind",
                        "Source": str(edge_blobs),
                        "Destination": "/blobs",
                        "RW": False,
                    },
                ],
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
                        "NVIDIA_API_KEY=",
                        "HF_TOKEN=",
                        "OPENAI_API_KEY=",
                    ],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(cosmos_cache),
                        "Destination": "/opt/nvidia/rtvi/.rtvi/ngc_model_cache",
                        "RW": False,
                    }
                ],
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
                    model_id = (
                        oe.EDGE_MODEL_ID if "30081" in url else oe.COSMOS_MODEL_ID
                    )
                    return {"data": [{"id": model_id}]}
                return {"status": "ok"}

            with (
                mock.patch.object(oe, "_docker_container", side_effect=container),
                mock.patch.object(oe, "_get_json", side_effect=response),
            ):
                contract = oe._load_json(oe.DEFAULT_CONTRACT)
                contract["images"]["edge4b_vllm"][
                    "image_id"
                ] = oe.EDGE_IMAGE_CONFIG_DIGEST
                oe.verify_readiness(contract, 1.0, edge_snapshot, cosmos_cache)

    def test_alias_model_id_is_rejected(self) -> None:
        with mock.patch.object(
            oe,
            "_get_json",
            return_value={"data": [{"id": "nvidia/cosmos3-nano-reasoner"}]},
        ):
            with self.assertRaisesRegex(oe.ContractError, "expected only"):
                oe._verify_model_endpoint(oe.COSMOS_BASE_URL, oe.COSMOS_MODEL_ID, 1.0)

    def test_model_container_rejects_credential_leak_and_shadow_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, _ = make_edge_cache(root)
            base = {
                "Image": oe.EDGE_IMAGE_CONFIG_DIGEST,
                "State": {"Running": True},
                "Config": {
                    "Image": oe.EDGE_IMAGE,
                    "Cmd": oe.EDGE_COMMAND,
                    "Env": ["HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1"],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(snapshot),
                        "Destination": "/models/edge4b",
                        "RW": False,
                    }
                ],
            }
            leaked = json.loads(json.dumps(base))
            leaked["Config"]["Env"].append("HF_TOKEN=secret")
            with (
                mock.patch.object(oe, "_docker_container", return_value=leaked),
                self.assertRaisesRegex(oe.ContractError, "credential environment"),
            ):
                oe._verify_running_container(
                    "vss-nemotron-edge-4b",
                    oe.EDGE_IMAGE,
                    oe.EDGE_IMAGE_CONFIG_DIGEST,
                    oe.EDGE_COMMAND,
                    {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
                    {"/models/edge4b": snapshot},
                )

            shadowed = json.loads(json.dumps(base))
            shadowed["Mounts"].append(
                {
                    "Type": "bind",
                    "Source": str(root),
                    "Destination": "/models/edge4b/model.safetensors",
                    "RW": True,
                }
            )
            with (
                mock.patch.object(oe, "_docker_container", return_value=shadowed),
                self.assertRaisesRegex(oe.ContractError, "overlapping protected"),
            ):
                oe._verify_running_container(
                    "vss-nemotron-edge-4b",
                    oe.EDGE_IMAGE,
                    oe.EDGE_IMAGE_CONFIG_DIGEST,
                    oe.EDGE_COMMAND,
                    {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
                    {"/models/edge4b": snapshot},
                )


if __name__ == "__main__":
    unittest.main()
