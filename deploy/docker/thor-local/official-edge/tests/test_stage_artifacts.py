from __future__ import annotations

import builtins
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stage_artifacts as staging  # noqa: E402


def completed(
    command: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class StageArtifactsTests(unittest.TestCase):
    def _execute_argv(self, root: Path, tools: dict[str, Path]) -> list[str]:
        return [
            "execute",
            "--acknowledgement",
            staging.ACKNOWLEDGEMENT,
            "--staging-root",
            str(root),
            "--hf-executable",
            str(tools["hf"]),
            "--ngc-executable",
            str(tools["ngc"]),
            "--docker-executable",
            str(tools["docker"]),
            "--hf-credential-source",
            "env:HF_TOKEN",
            "--ngc-credential-source",
            "env:NGC_CLI_API_KEY",
            "--edge-repository",
            staging.EDGE_REPOSITORY,
            "--edge-revision",
            staging.EDGE_REVISION,
            "--cosmos-artifact",
            staging.COSMOS_ARTIFACT,
            "--vllm-image",
            staging.EDGE_IMAGE,
            "--additional-headroom-bytes",
            "1",
            "--minimum-free-after-bytes",
            "1",
        ]

    def _tools(self, root: Path) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for name in ("hf", "ngc", "docker"):
            path = root / name
            path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            path.chmod(0o700)
            result[name] = path
        return result

    def test_default_plan_performs_no_reads_subprocesses_network_or_writes(
        self,
    ) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(staging, "execute") as execute,
            mock.patch.object(staging.subprocess, "run") as run,
            mock.patch.object(Path, "read_text") as read_text,
            mock.patch.object(Path, "write_text") as write_text,
            mock.patch.object(builtins, "open") as open_file,
            mock.patch.object(staging.shutil, "disk_usage") as disk_usage,
            redirect_stdout(output),
        ):
            result = staging.main([])
        self.assertEqual(result, 0)
        execute.assert_not_called()
        run.assert_not_called()
        read_text.assert_not_called()
        write_text.assert_not_called()
        open_file.assert_not_called()
        disk_usage.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["state"], "inert_no_action")
        for field in (
            "reads_performed",
            "network_performed",
            "filesystem_writes_performed",
            "docker_mutation_performed",
            "credential_reads_performed",
            "subprocesses_performed",
        ):
            self.assertFalse(payload[field])
        hf_resume = payload["resumability"]["huggingface"]
        self.assertIn("matching_prior_review_candidate_tree", hf_resume)
        self.assertIn("operator_recovery_or_new_staging_root", hf_resume)

    def test_wrong_ack_and_identity_fail_before_execute_or_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = self._tools(root)
            argv = self._execute_argv(root / "stage", tools)

            argv[argv.index(staging.ACKNOWLEDGEMENT)] = "yes"
            errors = io.StringIO()
            with (
                mock.patch.object(staging, "execute") as execute,
                mock.patch.object(staging.subprocess, "run") as run,
                redirect_stderr(errors),
            ):
                self.assertEqual(staging.main(argv), 1)
            execute.assert_not_called()
            run.assert_not_called()
            self.assertIn(staging.ACKNOWLEDGEMENT, errors.getvalue())

            argv = self._execute_argv(root / "stage", tools)
            argv[argv.index(staging.EDGE_IMAGE)] = (
                "ghcr.io/nvidia-ai-iot/vllm:latest-jetson-thor"
            )
            with (
                mock.patch.object(staging, "execute") as execute,
                mock.patch.object(staging.subprocess, "run") as run,
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(staging.main(argv), 1)
            execute.assert_not_called()
            run.assert_not_called()

    def test_contract_constants_are_the_exact_official_identities(self) -> None:
        contract = json.loads(staging.CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contract["llm"]["repository"], staging.EDGE_REPOSITORY)
        self.assertEqual(contract["llm"]["revision"], staging.EDGE_REVISION)
        self.assertEqual(contract["vlm"]["artifact_id"], staging.COSMOS_ARTIFACT)
        image = contract["images"]["edge4b_vllm"]
        self.assertEqual(image["reference"], staging.EDGE_IMAGE)
        self.assertEqual(
            image["manifest_config_digest"], staging.EDGE_IMAGE_CONFIG_DIGEST
        )
        self.assertIn("@sha256:", staging.EDGE_IMAGE)
        self.assertNotIn(":latest-", staging.EDGE_IMAGE)
        self.assertEqual(staging.KNOWN_PLANNING_FLOOR_BYTES, 49_871_036_871)

    def test_headroom_and_credential_sources_are_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            tools = self._tools(base)
            argv = self._execute_argv(base / "stage", tools)
            argv[argv.index("1")] = "0"
            with self.assertRaisesRegex(staging.StagingError, "headroom"):
                staging._request_from_args(staging._parser().parse_args(argv))

            argv = self._execute_argv(base / "stage", tools)
            source_index = argv.index("env:HF_TOKEN")
            argv[source_index] = "token:secret-on-command-line"
            with self.assertRaisesRegex(staging.StagingError, "credential source"):
                staging._request_from_args(staging._parser().parse_args(argv))

    def test_existing_root_and_child_redirects_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "stage"
            root.mkdir(mode=0o700)
            root.chmod(0o710)
            with self.assertRaisesRegex(staging.StagingError, "mode 0700"):
                staging._resolve_staging_root(str(root))

            root.chmod(0o700)
            outside = base / "outside"
            outside.mkdir()
            (root / "huggingface").symlink_to(outside, target_is_directory=True)
            with (
                mock.patch.object(staging, "_run_checked") as run,
                self.assertRaisesRegex(staging.StagingError, "redirect"),
            ):
                staging._stage_nemotron(
                    root,
                    base / "hf",
                    "secret",
                    {},
                    None,
                )
            run.assert_not_called()

    def test_untrusted_exact_named_artifact_directories_do_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "stage"
            root.mkdir(mode=0o700)
            snapshot = (
                root
                / "huggingface"
                / "hub"
                / staging.EDGE_CACHE_DIRECTORY
                / "snapshots"
                / staging.EDGE_REVISION
            )
            snapshot.mkdir(parents=True)
            (snapshot / "untrusted.bin").write_bytes(b"tampered")
            with (
                mock.patch.object(staging, "_run_checked") as run,
                self.assertRaisesRegex(staging.StagingError, "name-only resume"),
            ):
                staging._stage_nemotron(root, base / "hf", "secret", {}, None)
            run.assert_not_called()

            cosmos = root / "ngc" / "model-cache" / staging.COSMOS_CACHE_DIRECTORY
            cosmos.mkdir(parents=True)
            (cosmos / "untrusted.bin").write_bytes(b"tampered")
            with (
                mock.patch.object(staging, "_run_checked") as run,
                self.assertRaisesRegex(staging.StagingError, "name-only resume"),
            ):
                staging._stage_cosmos(root, base / "ngc", "secret", {}, None)
            run.assert_not_called()

    def test_execution_uses_mocked_tools_is_resumable_and_never_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "stage"
            docker_root = base / "docker-root"
            docker_root.mkdir()
            tools = self._tools(base)
            argv = self._execute_argv(root, tools)
            lock_before = staging.LOCK_PATH.read_bytes()
            pulled = False
            calls: list[tuple[list[str], dict[str, str]]] = []

            def fake_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                nonlocal pulled
                command = list(command)
                env = dict(kwargs.get("env") or {})
                calls.append((command, env))
                if command[-1:] == ["version"] and command[0] == str(tools["hf"]):
                    return completed(command, stdout="huggingface_hub version: test\n")
                if command[-1:] == ["--version"] and command[0] == str(tools["ngc"]):
                    return completed(command, stdout="NGC CLI test\n")
                if command[-1:] == ["--version"] and command[0] == str(tools["docker"]):
                    return completed(command, stdout="Docker version test\n")
                if command[1:3] == ["info", "--format"]:
                    return completed(command, stdout=str(docker_root) + "\n")
                if command[1:3] == ["image", "inspect"]:
                    if not pulled:
                        return completed(command, returncode=1, stderr="not present")
                    image = [
                        {
                            "Id": staging.EDGE_IMAGE_CONFIG_DIGEST,
                            "RepoDigests": [staging.EDGE_IMAGE],
                            "Architecture": "arm64",
                            "Os": "linux",
                            "Size": 123,
                        }
                    ]
                    return completed(command, stdout=json.dumps(image))
                if command[1:2] == ["download"]:
                    cache = Path(command[command.index("--cache-dir") + 1])
                    repo = cache / staging.EDGE_CACHE_DIRECTORY
                    snapshot = repo / "snapshots" / staging.EDGE_REVISION
                    blobs = repo / "blobs"
                    snapshot.mkdir(parents=True)
                    blobs.mkdir()
                    blob = "b" * 64
                    (blobs / blob).write_bytes(b"edge")
                    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
                    (snapshot / "model.safetensors").symlink_to(f"../../blobs/{blob}")
                    return completed(command, stdout=str(snapshot) + "\n")
                if command[1:5] == [
                    "registry",
                    "model",
                    "download-version",
                    staging.COSMOS_NGC_TARGET,
                ]:
                    destination = Path(command[command.index("--dest") + 1])
                    downloaded = destination / staging.COSMOS_NGC_DOWNLOAD_DIRECTORY
                    downloaded.mkdir(parents=True)
                    (downloaded / "weights.bin").write_bytes(b"cosmos")
                    return completed(command)
                if command[1:3] == ["pull", staging.EDGE_IMAGE]:
                    pulled = True
                    return completed(command)
                raise AssertionError(f"unexpected subprocess: {command!r}")

            environment = {
                "HF_TOKEN": "hf_super_secret",
                "NGC_CLI_API_KEY": "ngc_super_secret",
                "NVIDIA_API_KEY": "must_not_be_forwarded",
            }
            disk = {
                "same_filesystem": True,
                "staging_free_before_bytes": 100_000_000_000,
                "docker_free_before_bytes": 100_000_000_000,
                "known_planning_floor_bytes": staging.KNOWN_PLANNING_FLOOR_BYTES,
                "additional_unknown_image_headroom_bytes": 1,
                "minimum_free_after_bytes": 1,
                "capacity_state": "operator_headroom_admitted_planning_floor_not_exact_size",
            }
            output = io.StringIO()
            with (
                mock.patch.object(staging.subprocess, "run", side_effect=fake_run),
                mock.patch.object(staging, "_disk_admission", return_value=disk),
                mock.patch.dict(os.environ, environment, clear=True),
                redirect_stdout(output),
            ):
                self.assertEqual(staging.main(argv), 0)

            candidate = json.loads(output.getvalue())
            serialized = json.dumps(candidate, sort_keys=True)
            self.assertEqual(
                candidate["candidate_state"],
                "review_candidate_only_not_promoted",
            )
            self.assertFalse(candidate["artifact_lock_mutated"])
            self.assertFalse(candidate["promotion_performed"])
            self.assertFalse(candidate["runtime_qualification_performed"])
            self.assertNotIn("hf_super_secret", serialized)
            self.assertNotIn("ngc_super_secret", serialized)
            self.assertNotIn("must_not_be_forwarded", serialized)
            self.assertEqual(staging.LOCK_PATH.read_bytes(), lock_before)
            self.assertTrue((root / staging.CANDIDATE_FILENAME).is_file())

            network_calls = [
                (command, env)
                for command, env in calls
                if any("download" in part for part in command) or "pull" in command
            ]
            self.assertEqual(len(network_calls), 3)
            for command, child_env in network_calls:
                joined = " ".join(command)
                self.assertNotIn("hf_super_secret", joined)
                self.assertNotIn("ngc_super_secret", joined)
                self.assertNotIn("NVIDIA_API_KEY", child_env)
                self.assertNotIn("latest-jetson-thor", joined)

            # A resumed execution re-verifies identities and performs no network action.
            calls.clear()
            output = io.StringIO()
            with (
                mock.patch.object(staging.subprocess, "run", side_effect=fake_run),
                mock.patch.object(staging, "_disk_admission", return_value=disk),
                mock.patch.dict(os.environ, environment, clear=True),
                redirect_stdout(output),
            ):
                self.assertEqual(staging.main(argv), 0)
            resumed_network_calls = [
                command
                for command, _ in calls
                if any("download" in part for part in command) or "pull" in command
            ]
            self.assertEqual(resumed_network_calls, [])
            self.assertEqual(staging.LOCK_PATH.read_bytes(), lock_before)

            # A tree changed after the candidate was emitted cannot use that
            # candidate as resume evidence, even though its exact directory
            # name and non-empty state still look plausible.
            snapshot = (
                root
                / "huggingface"
                / "hub"
                / staging.EDGE_CACHE_DIRECTORY
                / "snapshots"
                / staging.EDGE_REVISION
            )
            (snapshot / "config.json").write_text(
                '{"tampered":true}\n', encoding="utf-8"
            )
            calls.clear()
            errors = io.StringIO()
            with (
                mock.patch.object(staging.subprocess, "run", side_effect=fake_run),
                mock.patch.object(staging, "_disk_admission", return_value=disk),
                mock.patch.dict(os.environ, environment, clear=True),
                redirect_stderr(errors),
            ):
                self.assertEqual(staging.main(argv), 1)
            self.assertIn("name-only resume", errors.getvalue())
            self.assertFalse(
                any(
                    any("download" in part for part in command) or "pull" in command
                    for command, _ in calls
                )
            )

            (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
            cosmos = (
                root
                / "ngc"
                / "model-cache"
                / staging.COSMOS_CACHE_DIRECTORY
                / "weights.bin"
            )
            cosmos.write_bytes(b"tampered-cosmos")
            calls.clear()
            errors = io.StringIO()
            with (
                mock.patch.object(staging.subprocess, "run", side_effect=fake_run),
                mock.patch.object(staging, "_disk_admission", return_value=disk),
                mock.patch.dict(os.environ, environment, clear=True),
                redirect_stderr(errors),
            ):
                self.assertEqual(staging.main(argv), 1)
            self.assertIn("name-only resume", errors.getvalue())
            self.assertEqual(staging.LOCK_PATH.read_bytes(), lock_before)


if __name__ == "__main__":
    unittest.main()
