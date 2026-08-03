#!/usr/bin/env python3
"""Self-contained adversarial tests for the offline environment package."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import py_compile
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "spatial_ai_materializer", HERE / "materializer.py"
)
assert SPEC is not None and SPEC.loader is not None
materializer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(materializer)


def make_wheel(
    root: Path, body_name: str = "arbitrary.body"
) -> tuple[Path, dict[str, object]]:
    metadata = b"Metadata-Version: 2.1\nName: example-pkg\nVersion: 1.2.3\n\n"
    wheel_metadata = (
        b"Wheel-Version: 1.0\nGenerator: offline-test\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n\n"
    )
    path = root / body_name
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("example_pkg-1.2.3.dist-info/METADATA", metadata)
        archive.writestr("example_pkg-1.2.3.dist-info/WHEEL", wheel_metadata)
        archive.writestr("example_pkg/__init__.py", "VALUE = 1\n")
    artifact: dict[str, object] = {
        "name": "example-pkg",
        "version": "1.2.3",
        "canonical_filename": "example_pkg-1.2.3-py3-none-any.whl",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
        "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
        "dist_info": "example_pkg-1.2.3.dist-info",
        "root_is_purelib": True,
        "wheel_tags": ["py3-none-any"],
        "cache_identity": {
            "kind": "content-addressed-pip-cache-wheel-body",
            "project": "example-pkg",
            "version": "1.2.3",
            "package_type": "bdist_wheel",
        },
    }
    return path, artifact


def make_valid_receipt() -> tuple[
    dict[str, object], dict[str, object], dict[str, int], str
]:
    lock = materializer.load_lock()
    scan = {
        "configured_roots": 1,
        "existing_roots": 1,
        "regular_candidates_examined": 657,
        "matched_artifacts": len(lock["artifacts"]),
        "duplicate_content_sources": 0,
    }
    temporary_root = "vss-spatial-ai-offline-env.abc123_4"
    versions = materializer._locked_versions(lock)
    receipt: dict[str, object] = {
        "schema_version": 1,
        "package_id": lock["package_id"],
        "mode": "offline_materialization",
        "status": "pass",
        "captured_at_utc": "2026-08-03T01:48:06.323881Z",
        "bindings": materializer._base_receipt_bindings(lock),
        "target": lock["target"],
        "policy": lock["policy"],
        "cache_scan": scan,
        "wheelhouse": materializer._locked_wheelhouse(lock),
        "environment": {
            "python": materializer.platform.python_version(),
            "machine": lock["target"]["machine"],
            "soabi": lock["target"]["soabi"],
            "pip": lock["target"]["bootstrap_pip"],
            "pip_check": "No broken requirements found.",
            "installed_artifact_count": len(versions),
            "installed_versions_sha256": materializer.sha_bytes(
                materializer.canonical_bytes(versions)
            ),
            "smoke_imports": lock["smoke_imports"],
        },
        "confinement": materializer._confinement_policy(),
        "cleanup": {
            "temporary_root": temporary_root,
            "pre_state": "absent",
            "removed": True,
            "sentinel_unchanged": True,
            "source_artifacts_unchanged": True,
        },
        "promotion": materializer._promotion_policy(),
    }
    receipt["bindings"]["execution_sha256"] = materializer._execution_sha256(receipt)
    return receipt, lock, scan, temporary_root


def make_valid_producer_receipt(
    root: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    lock = materializer.load_producer_lock()
    contract = materializer.strict_json(materializer.PRODUCER_CONTRACT_PATH)
    contract_by_id = {row["capability_id"]: row for row in contract["capabilities"]}
    calls = lock["expectations"]["product_function_calls_by_capability"]
    captured_at = "2026-08-03T01:48:06.323881Z"
    executor_sha = materializer._producer_lock_row(
        lock, materializer.PRODUCER_EXECUTOR_PATH
    )["sha256"]
    contract_sha = materializer._producer_lock_row(
        lock, materializer.PRODUCER_CONTRACT_PATH
    )["sha256"]
    rows = []
    for capability_id in materializer.CAPABILITY_IDS:
        capability = contract_by_id[capability_id]
        short_id = capability_id.split(".")[2][:2]
        count = calls[capability_id]
        target_action_ids = [
            "positive-run-1",
            "positive-run-2",
            *materializer.NEGATIVE_CASE_IDS[short_id],
        ]
        positive_observations = {"synthetic": capability_id}
        observation_hash = materializer.sha_bytes(
            materializer.canonical_bytes(positive_observations)
        )
        rows.append(
            {
                "capability_id": capability_id,
                "oracle_id": capability["oracle_id"],
                "fixture_sha256": capability["fixture_manifest"]["sha256"],
                "status": "pass",
                "independent_runs": 2,
                "bounded_capability_actions": 7,
                "requests": 7,
                "target_action_ids": target_action_ids,
                "deterministic_output": True,
                "run_output_sha256": [observation_hash, observation_hash],
                "adjacent_negatives": [
                    {
                        "case_id": case_id,
                        "rejected": True,
                        "exception_type": "ValueError",
                        "message_sha256": materializer.sha_bytes(
                            f"rejected:{case_id}".encode("utf-8")
                        ),
                    }
                    for case_id in materializer.NEGATIVE_CASE_IDS[short_id]
                ],
                "imported_product_function_invocations": count,
                "imported_product_function_counts": materializer.PRODUCT_FUNCTION_COUNTS[
                    short_id
                ],
                "positive_observations": positive_observations,
                "cleanup": {
                    "namespace": f"spatial-ai-{capability_id.split('.')[2]}",
                    "pre_state_captured": "absent",
                    "temporary_files_only": True,
                    "removed": True,
                    "siblings_unchanged": True,
                    "owned_tree_sha256": "c" * 64,
                    "post_cleanup_tree_sha256": materializer.EMPTY_TREE_SHA256,
                },
                "runtime_evidence_binding": {
                    "captured_at_utc": captured_at,
                    "executor_sha256": executor_sha,
                    "contract_sha256": contract_sha,
                    "current_oracle_sha256": capability["current_oracle_sha256"],
                    "current_ledger_row_sha256": capability[
                        "current_ledger_row_sha256"
                    ],
                    "fixture_sha256": capability["fixture_manifest"]["sha256"],
                    "capability_evidence_sha256": observation_hash,
                    "target_case_actions": 7,
                    "requests": 7,
                    "target_action_ids_sha256": materializer.sha_bytes(
                        materializer.canonical_bytes(target_action_ids)
                    ),
                    "imported_product_function_invocations": count,
                    "imported_product_function_counts_sha256": materializer.sha_bytes(
                        materializer.canonical_bytes(
                            materializer.PRODUCT_FUNCTION_COUNTS[short_id]
                        )
                    ),
                },
            }
        )
    temporary_root = root / "tmp" / "vss-spatial-ai-runtime.synthetic"
    metadata = lock["metadata_selection"]
    metadata_hashes = {row["path"]: row["sha256"] for row in lock["metadata_controls"]}
    receipt: dict[str, object] = {
        "schema_version": 1,
        "package_id": "thor-spatial-ai-utils-runtime-evidence-successor-v1",
        "mode": "target_bound_offline_runtime_evidence",
        "status": "pass",
        "captured_at_utc": captured_at,
        "bindings": {
            "contract_sha256": contract_sha,
            "executor_sha256": executor_sha,
            "ledger_document_sha256": lock["canonical_controls"][0]["sha256"],
            "oracle_document_sha256": lock["canonical_controls"][1]["sha256"],
            "checkout_clean": True,
            "checkout_head": "a" * 40,
            "checkout_tree": "b" * 40,
            "checkout_status_porcelain_sha256": materializer.sha_bytes(b""),
            "invocation_allow_dirty_development": False,
            "target_upstream_commit": metadata["target_main_commit"],
            "target_ancestry_merge_base": metadata["target_main_commit"],
            "metadata_selector_path": metadata["selector_path"],
            "metadata_selector_raw_sha256": metadata_hashes[metadata["selector_path"]],
            "selected_metadata_set_id": metadata["selected_set_id"],
            "selected_descriptor_path": metadata["descriptor_path"],
            "selected_descriptor_raw_sha256": metadata_hashes[
                metadata["descriptor_path"]
            ],
            "selected_ledger_path": metadata["selected_ledger_path"],
            "selected_ledger_raw_sha256": metadata_hashes[
                metadata["selected_ledger_path"]
            ],
            "selected_oracle_path": metadata["selected_oracle_path"],
            "selected_oracle_raw_sha256": metadata_hashes[
                metadata["selected_oracle_path"]
            ],
            "selected_target_main_commit": metadata["target_main_commit"],
            "selected_target_product_version": metadata["target_product_version"],
            "canonical_rows_are_open_unexecuted": True,
            "executor_ready_capabilities": materializer.EXECUTOR_READY_CAPABILITY_IDS,
        },
        "capability_results": rows,
        "confinement": {
            "bounded_capability_actions": 49,
            "requests": 49,
            "imported_product_function_invocations": 122,
            "product_execution_deadline_seconds": 900,
            "external_activity_instrumented": True,
            "whole_temp_root_scanned": True,
            **{key: 0 for key in materializer.EXTERNAL_ACTIVITY_KEYS},
        },
        "environment": {
            "platform": "linux-aarch64",
            "system": "Linux",
            "machine": "aarch64",
            "python_major_minor": "3.12",
            "python_full": materializer.platform.python_version(),
            "capability_preflight": {
                capability_id: {
                    "ready": True,
                    "required_modules": materializer.REQUIRED_MODULES[
                        contract_by_id[capability_id]["adapter"]
                    ],
                    "observed_versions": {
                        module: "test"
                        for module in materializer.REQUIRED_MODULES[
                            contract_by_id[capability_id]["adapter"]
                        ]
                    },
                    "missing_modules": [],
                    "import_failures": [],
                }
                for capability_id in materializer.CAPABILITY_IDS
            },
        },
        "cleanup": {
            "executor_owned_temporary_root": os.fspath(temporary_root),
            "pre_execution_tree_sha256": materializer.EMPTY_TREE_SHA256,
            "post_execution_tree_sha256": materializer.EMPTY_TREE_SHA256,
            "sentinel_sha256": "d" * 64,
            "checkout_status_before_sha256": materializer.sha_bytes(b""),
            "checkout_status_after_sha256": materializer.sha_bytes(b""),
            "removed": True,
            "siblings_unchanged": True,
        },
        "promotion": materializer._expected_producer_promotion(),
    }
    return receipt, lock


def make_valid_integrated_receipt(
    root: Path,
) -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, int], str
]:
    environment_receipt, environment_lock, scan, temporary_root = make_valid_receipt()
    producer_receipt, producer_lock = make_valid_producer_receipt(root)
    producer_raw = (
        json.dumps(producer_receipt, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    accounting = {
        key: producer_lock["expectations"][key]
        for key in (
            "capabilities_passed",
            "bounded_capability_actions",
            "requests",
            "product_function_calls",
            "independent_positive_runs",
            "adjacent_negatives",
        )
    }
    receipt: dict[str, object] = {
        "schema_version": 1,
        "package_id": "thor-spatial-ai-offline-integrated-runtime-v1",
        "mode": "offline_environment_with_canonical_spatial_ai_all",
        "status": "pass",
        "captured_at_utc": "2026-08-03T01:48:06.323881Z",
        "bindings": {
            "environment_receipt_sha256": materializer.sha_bytes(
                materializer.canonical_bytes(environment_receipt)
            ),
            "producer_lock_sha256": materializer.sha_file(
                materializer.PRODUCER_LOCK_PATH
            ),
            "producer_contract_sha256": materializer._producer_lock_row(
                producer_lock, materializer.PRODUCER_CONTRACT_PATH
            )["sha256"],
            "producer_executor_sha256": materializer._producer_lock_row(
                producer_lock, materializer.PRODUCER_EXECUTOR_PATH
            )["sha256"],
            "producer_result_schema_sha256": materializer._producer_lock_row(
                producer_lock, materializer.PRODUCER_RESULT_SCHEMA_PATH
            )["sha256"],
            "import_sensitive_manifests_sha256": materializer._import_sensitive_manifests_sha256(
                producer_lock
            ),
            "producer_receipt_sha256": materializer.sha_bytes(producer_raw),
        },
        "selection": {"kind": "all", "capability_ids": materializer.CAPABILITY_IDS},
        "environment_receipt": environment_receipt,
        "producer_receipt": producer_receipt,
        "accounting": accounting,
        "confinement": {
            "inherited_kernel_network_denial": True,
            "import_shadow_scan_passed": True,
            "outer_timeout_seconds": 930,
            **{key: 0 for key in materializer.EXTERNAL_ACTIVITY_KEYS},
        },
        "cleanup": {
            "materializer_temporary_root": temporary_root,
            "materializer_temporary_root_removed": True,
            "producer_temporary_root_removed": True,
            "producer_bundle_unchanged": True,
            "canonical_controls_unchanged": True,
            "product_sources_unchanged": True,
            "import_sensitive_roots_unchanged": True,
        },
        "promotion": materializer._mirrored_integrated_promotion(producer_receipt),
    }
    receipt["bindings"]["execution_sha256"] = materializer._integrated_execution_sha256(
        receipt
    )
    return receipt, environment_lock, producer_lock, scan, temporary_root


class LockTests(unittest.TestCase):
    def test_canonical_lock_and_inventory(self) -> None:
        lock = materializer.load_lock()
        self.assertEqual(56, len(lock["artifacts"]))
        self.assertEqual(23, len(lock["root_requirements"]))
        self.assertEqual(18, len(lock["smoke_imports"]))
        self.assertEqual(
            sorted(row["name"] for row in lock["artifacts"]),
            [row["name"] for row in lock["artifacts"]],
        )

    def test_alternate_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            alternate = Path(directory) / "lock.json"
            shutil.copyfile(materializer.LOCK_PATH, alternate)
            with self.assertRaisesRegex(materializer.MaterializationError, "canonical"):
                materializer.load_lock(alternate)

    def test_repository_package_contains_no_wheel_bodies(self) -> None:
        forbidden = [
            path
            for path in HERE.rglob("*")
            if path.is_file() and path.suffix in {".whl", ".body"}
        ]
        self.assertEqual([], forbidden)

    def test_producer_lock_is_contract_derived_and_complete(self) -> None:
        lock = materializer.load_producer_lock()
        self.assertEqual(4, len(lock["producer_bundle"]))
        self.assertEqual(2, len(lock["canonical_controls"]))
        self.assertEqual(6, len(lock["metadata_controls"]))
        self.assertEqual(7, len(lock["fixture_controls"]))
        self.assertEqual(30, len(lock["product_source_controls"]))
        self.assertEqual(252, len(lock["product_root_manifest"]))
        self.assertEqual(14, len(lock["producer_root_manifest"]))
        self.assertEqual(122, lock["expectations"]["product_function_calls"])
        rows = sum(
            (
                lock[key]
                for key in (
                    "producer_bundle",
                    "canonical_controls",
                    "metadata_controls",
                    "fixture_controls",
                    "product_source_controls",
                    "product_root_manifest",
                    "producer_root_manifest",
                )
            ),
            [],
        )
        self.assertEqual(315, len(rows))
        self.assertEqual(274, len({row["path"] for row in rows}))

    def test_producer_lock_hash_mutation_fails_closed(self) -> None:
        lock = materializer.load_producer_lock()
        forged = copy.deepcopy(lock)
        forged["fixture_controls"][0]["sha256"] = "0" * 64
        original_strict_json = materializer.strict_json

        def substitute(path: Path) -> object:
            if path == materializer.PRODUCER_LOCK_PATH:
                return forged
            return original_strict_json(path)

        with (
            mock.patch.object(materializer, "strict_json", side_effect=substitute),
            self.assertRaisesRegex(materializer.MaterializationError, "fixture lock"),
        ):
            materializer.load_producer_lock()

    def test_zero_and_nonexistent_binding_commits_fail_closed(self) -> None:
        lock = materializer.load_producer_lock()
        original_strict_json = materializer.strict_json
        for commit in ("0" * 40, "f" * 40):
            forged = copy.deepcopy(lock)
            forged["producer_binding_commit"] = commit

            def substitute(path: Path) -> object:
                if path == materializer.PRODUCER_LOCK_PATH:
                    return forged
                return original_strict_json(path)

            with (
                self.subTest(commit=commit),
                mock.patch.object(materializer, "strict_json", side_effect=substitute),
                self.assertRaisesRegex(
                    materializer.MaterializationError, "commit object"
                ),
            ):
                materializer.load_producer_lock()

    def test_nonancestor_binding_commit_fails_closed(self) -> None:
        commit = "a" * 40
        responses = (
            subprocess.CompletedProcess(
                ["git", "rev-parse"], 0, stdout=commit + "\n", stderr=""
            ),
            subprocess.CompletedProcess(["git", "merge-base"], 1, stdout="", stderr=""),
        )
        with (
            mock.patch.object(materializer.subprocess, "run", side_effect=responses),
            self.assertRaisesRegex(
                materializer.MaterializationError, "not an ancestor"
            ),
        ):
            materializer._validated_ancestor_commit(commit)

    def test_binding_commit_blob_drift_fails_closed(self) -> None:
        lock = materializer.load_producer_lock()
        with (
            mock.patch.object(
                materializer,
                "_validated_ancestor_commit",
                return_value=lock["producer_binding_commit"],
            ),
            mock.patch.object(materializer, "_blob_at_commit", return_value=b"drift"),
            self.assertRaisesRegex(materializer.MaterializationError, "blob drift"),
        ):
            materializer._validate_producer_binding_commit(lock)

    def test_import_manifest_omission_and_addition_fail_closed(self) -> None:
        lock = materializer.load_producer_lock()
        tracked_by_root = {
            materializer.PRODUCT_ROOT_REL: [
                row["path"] for row in lock["product_root_manifest"]
            ],
            materializer.PRODUCER_ROOT_REL: [
                row["path"] for row in lock["producer_root_manifest"]
            ],
        }
        for key, tracked in (
            ("product_root_manifest", tracked_by_root[materializer.PRODUCT_ROOT_REL]),
            (
                "producer_root_manifest",
                tracked_by_root[materializer.PRODUCER_ROOT_REL],
            ),
        ):
            for forged_paths in (tracked[:-1], [*tracked, tracked[-1] + ".added"]):
                forged = copy.deepcopy(lock)
                forged[key] = [
                    {"path": path, "sha256": "0" * 64} for path in forged_paths
                ]
                with (
                    self.subTest(key=key, count=len(forged_paths)),
                    mock.patch.object(
                        materializer,
                        "_tracked_root_paths",
                        side_effect=lambda root: tracked_by_root[root],
                    ),
                    mock.patch.object(materializer, "_verify_import_tree"),
                    self.assertRaisesRegex(
                        materializer.MaterializationError, "manifest"
                    ),
                ):
                    materializer.verify_import_roots(forged)


class CacheResolutionTests(unittest.TestCase):
    def test_content_addressed_resolution_and_exact_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "opaque-cache" / "7" / "f"
            cache.mkdir(parents=True)
            source, artifact = make_wheel(cache)
            lock = {"artifacts": [artifact]}
            sources, scan = materializer.resolve_cache_artifacts(lock, [root])
            self.assertEqual(source, sources["example-pkg"])
            self.assertEqual(1, scan["matched_artifacts"])
            wheelhouse = root / "output"
            result = materializer.materialize_wheelhouse(lock, sources, wheelhouse)
            copied = wheelhouse / artifact["canonical_filename"]
            self.assertEqual(artifact["sha256"], materializer.sha_file(copied))
            self.assertEqual(1, result["artifact_count"])

    def test_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, artifact = make_wheel(root)
            artifact["sha256"] = "0" * 64
            with self.assertRaisesRegex(materializer.MaterializationError, "absent"):
                materializer.resolve_cache_artifacts({"artifacts": [artifact]}, [root])

    def test_symlink_cache_candidate_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            source, artifact = make_wheel(real)
            isolated = root / "isolated"
            isolated.mkdir()
            (isolated / "link.body").symlink_to(source)
            with self.assertRaisesRegex(materializer.MaterializationError, "absent"):
                materializer.resolve_cache_artifacts(
                    {"artifacts": [artifact]}, [isolated]
                )


class ConfinementTests(unittest.TestCase):
    def test_kernel_seccomp_denies_socket_without_python_guard(self) -> None:
        result = subprocess.run(
            [sys.executable, "-s", "-c", "import socket; socket.socket()"],
            env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"},
            text=True,
            capture_output=True,
            check=False,
            preexec_fn=materializer._install_no_network_seccomp,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Operation not permitted", result.stderr)

    def test_python_guard_has_explicit_denial_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = root / "guard"
            guard.mkdir()
            (guard / "sitecustomize.py").write_text(
                materializer.NETWORK_GUARD_SOURCE, encoding="utf-8"
            )
            env = {
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": os.fspath(guard),
                "PYTHONNOUSERSITE": "1",
            }
            result = subprocess.run(
                [sys.executable, "-s", "-c", "import socket; socket.socket()"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn(materializer.NETWORK_DENIAL_MARKER, result.stderr)

    def test_failed_build_removes_only_owned_temporary_paths(self) -> None:
        lock = materializer.load_lock()
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, _ = make_wheel(parent, "source.body")
            sources = {row["name"]: source for row in lock["artifacts"]}
            with (
                mock.patch.object(
                    materializer,
                    "resolve_cache_artifacts",
                    return_value=(sources, {}),
                ),
                mock.patch.object(
                    materializer,
                    "materialize_wheelhouse",
                    return_value={},
                ),
                mock.patch.object(
                    materializer,
                    "build_environment",
                    side_effect=materializer.MaterializationError("injected"),
                ),
                mock.patch.object(materializer, "require_isolated_execution"),
            ):
                with self.assertRaisesRegex(
                    materializer.MaterializationError, "injected"
                ):
                    materializer.materialize(lock, [parent], parent)
            names = sorted(path.name for path in parent.iterdir())
            self.assertEqual(["source.body"], names)

    def test_child_timeout_is_a_closed_failure(self) -> None:
        with (
            mock.patch.object(
                materializer.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["python"], 930),
            ),
            self.assertRaisesRegex(materializer.MaterializationError, "930-second"),
        ):
            materializer.run_child(["python"], {}, Path("/tmp"), timeout=930)

    def test_valid_ignored_bytecode_is_rejected_in_import_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            cache = root / "__pycache__"
            cache.mkdir()
            py_compile.compile(
                os.fspath(source),
                cfile=os.fspath(cache / "module.cpython-312.pyc"),
                doraise=True,
            )
            with self.assertRaisesRegex(
                materializer.MaterializationError, "__pycache__"
            ):
                materializer._verify_import_tree(root, {"module.py"})

    def test_fake_native_extension_and_untracked_python_are_rejected(self) -> None:
        for name in (
            "shadow" + importlib.machinery.EXTENSION_SUFFIXES[0],
            "shadow.py",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "listed.py").write_text("VALUE = 1\n", encoding="utf-8")
                (root / name).write_bytes(b"shadow")
                with self.assertRaisesRegex(
                    materializer.MaterializationError, "executable import shadow"
                ):
                    materializer._verify_import_tree(root, {"listed.py"})

    def test_product_and_producer_top_level_native_shadows_are_rejected(self) -> None:
        for shadow in (
            "numpy" + importlib.machinery.EXTENSION_SUFFIXES[0],
            "jsonschema" + importlib.machinery.EXTENSION_SUFFIXES[0],
        ):
            with (
                self.subTest(shadow=shadow),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "listed.txt").write_text("tracked\n", encoding="utf-8")
                (root / shadow).write_bytes(b"shadow")
                with self.assertRaisesRegex(
                    materializer.MaterializationError, "executable import shadow"
                ):
                    materializer._verify_import_tree(root, {"listed.txt"})

    def test_import_root_symlink_and_special_file_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "listed.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            (root / "shadow.py").symlink_to(target)
            with self.assertRaisesRegex(materializer.MaterializationError, "symlink"):
                materializer._verify_import_tree(root, {"listed.py"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.mkfifo(root / "shadow")
            with self.assertRaisesRegex(
                materializer.MaterializationError, "special file"
            ):
                materializer._verify_import_tree(root, set())

    def test_unlisted_package_data_and_missing_manifest_file_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "extra.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                materializer.MaterializationError, "unlisted package data"
            ):
                materializer._verify_import_tree(root, set())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                materializer.MaterializationError, "manifest files are absent"
            ):
                materializer._verify_import_tree(Path(directory), {"missing.py"})

    def test_ignored_cache_outside_import_root_is_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "spatialai_data_utils"
            root.mkdir()
            (root / "listed.py").write_text("VALUE = 1\n", encoding="utf-8")
            sibling_cache = parent / "outside" / "__pycache__"
            sibling_cache.mkdir(parents=True)
            cache_file = sibling_cache / "ignored.pyc"
            cache_file.write_bytes(b"ignored outside import root")
            materializer._verify_import_tree(root, {"listed.py"})
            self.assertTrue(cache_file.is_file())

    def test_child_environment_disables_bytecode_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = root / "guard"
            wheelhouse = root / "wheelhouse"
            guard.mkdir()
            wheelhouse.mkdir()
            env = materializer._child_environment(root, guard, wheelhouse)
            self.assertEqual("1", env["PYTHONDONTWRITEBYTECODE"])


class IntegratedProducerTests(unittest.TestCase):
    def test_exact_all_seven_bounded_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            receipt, lock = make_valid_producer_receipt(root)
            self.assertEqual(
                [],
                materializer.schema_errors(
                    receipt, materializer.PRODUCER_RESULT_SCHEMA_PATH
                ),
            )
            captured: dict[str, object] = {}

            def fake_child(
                argv: list[str], env: dict[str, str], cwd: Path, timeout: int = 900
            ) -> subprocess.CompletedProcess[str]:
                captured.update(argv=argv, env=env, cwd=cwd, timeout=timeout)
                output = Path(argv[argv.index("--output") + 1])
                output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
                output.chmod(0o600)
                return subprocess.CompletedProcess(argv, 0, "", "")

            with (
                mock.patch.object(materializer, "run_child", side_effect=fake_child),
                mock.patch.object(
                    materializer,
                    "_checkout_state",
                    return_value=("a" * 40, "b" * 40, ""),
                ),
                mock.patch.object(
                    materializer,
                    "_merge_base",
                    return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                ),
            ):
                result, _, accounting = materializer.run_canonical_producer(
                    root / "venv/bin/python", {}, root, lock
                )
            argv = captured["argv"]
            self.assertEqual(930, captured["timeout"])
            self.assertEqual("-I", argv[1])
            self.assertEqual(
                materializer.CAPABILITY_IDS,
                [
                    argv[index + 1]
                    for index, value in enumerate(argv)
                    if value == "--select"
                ],
            )
            self.assertNotIn("--allow-dirty-development", argv)
            self.assertNotIn("--contract", argv)
            self.assertEqual("pass", result["status"])
            self.assertEqual(122, accounting["product_function_calls"])

    def test_every_required_aggregate_is_independently_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            receipt, lock = make_valid_producer_receipt(root)
            with (
                mock.patch.object(
                    materializer,
                    "_checkout_state",
                    return_value=("a" * 40, "b" * 40, ""),
                ),
                mock.patch.object(
                    materializer,
                    "_merge_base",
                    return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                ),
            ):
                materializer.validate_producer_receipt(receipt, lock, root)
                mutations = (
                    ("status", "partial"),
                    ("confinement", "requests", 48),
                    ("confinement", "network_calls", 1),
                    ("promotion", "aggregate_is_promotable", False),
                    ("cleanup", "removed", False),
                )
                for mutation in mutations:
                    with self.subTest(mutation=mutation):
                        forged = copy.deepcopy(receipt)
                        target = forged
                        for key in mutation[:-2]:
                            target = target[key]
                        if len(mutation) == 2:
                            target[mutation[0]] = mutation[1]
                        else:
                            target[mutation[-2]] = mutation[-1]
                        with self.assertRaises(materializer.MaterializationError):
                            materializer.validate_producer_receipt(forged, lock, root)

    def test_every_new_authority_binding_is_independently_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            receipt, lock = make_valid_producer_receipt(root)
            mutations = {
                "checkout_tree": "0" * 40,
                "invocation_allow_dirty_development": True,
                "target_upstream_commit": "0" * 40,
                "target_ancestry_merge_base": "0" * 40,
                "metadata_selector_path": "forged-selector.json",
                "metadata_selector_raw_sha256": "0" * 64,
                "selected_metadata_set_id": "forged-set",
                "selected_descriptor_path": "forged-descriptor.json",
                "selected_descriptor_raw_sha256": "0" * 64,
                "selected_ledger_path": "forged-ledger.json",
                "selected_ledger_raw_sha256": "0" * 64,
                "selected_oracle_path": "forged-oracle.json",
                "selected_oracle_raw_sha256": "0" * 64,
                "selected_target_main_commit": "0" * 40,
                "selected_target_product_version": "0.0.0",
            }
            with (
                mock.patch.object(
                    materializer,
                    "_checkout_state",
                    return_value=("a" * 40, "b" * 40, ""),
                ),
                mock.patch.object(
                    materializer,
                    "_merge_base",
                    return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                ),
            ):
                for field, value in mutations.items():
                    with self.subTest(field=field):
                        forged = copy.deepcopy(receipt)
                        forged["bindings"][field] = value
                        with self.assertRaises(materializer.MaterializationError):
                            materializer.validate_producer_receipt(forged, lock, root)

    def test_authority_cleanup_proofs_are_independently_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            receipt, lock = make_valid_producer_receipt(root)
            mutations = {
                "pre_execution_tree_sha256": "0" * 64,
                "post_execution_tree_sha256": "0" * 64,
                "sentinel_sha256": None,
                "checkout_status_before_sha256": "0" * 64,
                "checkout_status_after_sha256": "0" * 64,
            }
            with (
                mock.patch.object(
                    materializer,
                    "_checkout_state",
                    return_value=("a" * 40, "b" * 40, ""),
                ),
                mock.patch.object(
                    materializer,
                    "_merge_base",
                    return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                ),
            ):
                for field, value in mutations.items():
                    with self.subTest(field=field):
                        forged = copy.deepcopy(receipt)
                        forged["cleanup"][field] = value
                        with self.assertRaises(materializer.MaterializationError):
                            materializer.validate_producer_receipt(forged, lock, root)

    def test_producer_cleanup_root_is_canonical_parent_bound_and_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            receipt, lock = make_valid_producer_receipt(root)
            with (
                mock.patch.object(
                    materializer,
                    "_checkout_state",
                    return_value=("a" * 40, "b" * 40, ""),
                ),
                mock.patch.object(
                    materializer,
                    "_merge_base",
                    return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                ),
            ):
                for forged in (
                    "vss-spatial-ai-runtime.relative",
                    os.fspath(
                        root / "tmp" / ".." / "tmp" / "vss-spatial-ai-runtime.dotdot"
                    ),
                    "/var/tmp/vss-spatial-ai-runtime.wrong-parent",
                ):
                    with self.subTest(forged=forged):
                        value = copy.deepcopy(receipt)
                        value["cleanup"]["executor_owned_temporary_root"] = forged
                        with self.assertRaises(materializer.MaterializationError):
                            materializer.validate_producer_receipt(value, lock, root)

                existing = root / "tmp" / "vss-spatial-ai-runtime.existing"
                existing.mkdir()
                value = copy.deepcopy(receipt)
                value["cleanup"]["executor_owned_temporary_root"] = os.fspath(existing)
                with self.assertRaises(materializer.MaterializationError):
                    materializer.validate_producer_receipt(value, lock, root)
                existing.rmdir()

                dangling = root / "tmp" / "vss-spatial-ai-runtime.dangling"
                dangling.symlink_to(root / "tmp" / "absent-target")
                try:
                    value = copy.deepcopy(receipt)
                    value["cleanup"]["executor_owned_temporary_root"] = os.fspath(
                        dangling
                    )
                    with self.assertRaises(materializer.MaterializationError):
                        materializer.validate_producer_receipt(value, lock, root)
                finally:
                    dangling.unlink()

    def test_row_level_positive_negative_and_call_mutations_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            receipt, lock = make_valid_producer_receipt(root)
            with (
                mock.patch.object(
                    materializer,
                    "_checkout_state",
                    return_value=("a" * 40, "b" * 40, ""),
                ),
                mock.patch.object(
                    materializer,
                    "_merge_base",
                    return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                ),
            ):
                for key, value in (
                    ("independent_runs", 1),
                    ("bounded_capability_actions", 6),
                    ("requests", 6),
                    ("deterministic_output", False),
                    ("imported_product_function_invocations", 10),
                ):
                    with self.subTest(key=key):
                        forged = copy.deepcopy(receipt)
                        forged["capability_results"][0][key] = value
                        with self.assertRaises(materializer.MaterializationError):
                            materializer.validate_producer_receipt(forged, lock, root)
                forged = copy.deepcopy(receipt)
                forged["capability_results"][0]["adjacent_negatives"][0]["case_id"] = (
                    "forged-negative"
                )
                with self.assertRaises(materializer.MaterializationError):
                    materializer.validate_producer_receipt(forged, lock, root)
                forged = copy.deepcopy(receipt)
                forged["capability_results"][0]["imported_product_function_counts"][
                    "group.parse_moves"
                ] = 4
                with self.assertRaises(materializer.MaterializationError):
                    materializer.validate_producer_receipt(forged, lock, root)

    def test_locked_bundle_drift_fails_and_removes_owned_root(self) -> None:
        environment_receipt, environment_lock, _, _ = make_valid_receipt()
        producer_lock = materializer.load_producer_lock()
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, _ = make_wheel(parent, "source.body")
            sources = {row["name"]: source for row in environment_lock["artifacts"]}
            before = {"locked": "1" * 64}
            after = {"locked": "2" * 64}
            with (
                mock.patch.object(
                    materializer, "load_producer_lock", return_value=producer_lock
                ),
                mock.patch.object(materializer, "verify_import_roots"),
                mock.patch.object(materializer, "require_isolated_execution"),
                mock.patch.object(
                    materializer,
                    "_producer_snapshot",
                    side_effect=(before, after, before),
                ),
                mock.patch.object(
                    materializer,
                    "resolve_cache_artifacts",
                    return_value=(sources, {"matched_artifacts": 56}),
                ),
                mock.patch.object(
                    materializer,
                    "materialize_wheelhouse",
                    return_value=environment_receipt["wheelhouse"],
                ),
                mock.patch.object(
                    materializer,
                    "build_environment",
                    return_value=(
                        environment_receipt["environment"],
                        parent / "venv/bin/python",
                        {},
                    ),
                ),
                mock.patch.object(
                    materializer,
                    "run_canonical_producer",
                    return_value=({}, "3" * 64, {}),
                ),
                self.assertRaisesRegex(
                    materializer.MaterializationError, "producer bundle"
                ),
            ):
                materializer.materialize(
                    environment_lock, [parent], parent, run_producer=True
                )
            self.assertEqual(
                ["source.body"], sorted(path.name for path in parent.iterdir())
            )


class ReceiptIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt, self.lock, self.scan, self.temporary_root = make_valid_receipt()

    def validate(self, receipt: dict[str, object]) -> None:
        materializer.validate_receipt(
            receipt,
            self.lock,
            expected_cache_scan=self.scan,
            expected_temporary_root=self.temporary_root,
        )

    def mutate_and_rebind(self, *path_and_value: object) -> dict[str, object]:
        *path, value = path_and_value
        receipt = copy.deepcopy(self.receipt)
        target = receipt
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        receipt["bindings"]["execution_sha256"] = materializer._execution_sha256(
            receipt
        )
        return receipt

    def assert_mutation_rejected(self, *path_and_value: object) -> None:
        with self.assertRaises(materializer.MaterializationError):
            self.validate(self.mutate_and_rebind(*path_and_value))

    def test_unmodified_receipt_passes(self) -> None:
        self.validate(self.receipt)

    def test_locked_wheelhouse_fields_are_independently_derived(self) -> None:
        self.assert_mutation_rejected("wheelhouse", "artifact_count", 55)
        self.assert_mutation_rejected("wheelhouse", "aggregate_bytes", 151492797)
        self.assert_mutation_rejected("wheelhouse", "inventory_sha256", "0" * 64)

    def test_installed_environment_fields_are_independently_derived(self) -> None:
        self.assert_mutation_rejected("environment", "installed_artifact_count", 55)
        self.assert_mutation_rejected(
            "environment", "installed_versions_sha256", "0" * 64
        )
        self.assert_mutation_rejected("environment", "smoke_imports", ["numpy"])

    def test_cleanup_identity_and_every_state_field_are_exact(self) -> None:
        self.assert_mutation_rejected(
            "cleanup", "temporary_root", "vss-spatial-ai-offline-env.forged00"
        )
        self.assert_mutation_rejected("cleanup", "pre_state", "present")
        self.assert_mutation_rejected("cleanup", "removed", False)
        self.assert_mutation_rejected("cleanup", "sentinel_unchanged", False)
        self.assert_mutation_rejected("cleanup", "source_artifacts_unchanged", False)

    def test_every_cache_scan_field_is_bound_to_observation(self) -> None:
        mutations = {
            "configured_roots": 2,
            "existing_roots": 2,
            "regular_candidates_examined": 658,
            "matched_artifacts": 55,
            "duplicate_content_sources": 1,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                self.assert_mutation_rejected("cache_scan", field, value)

    def test_source_lock_materializer_and_execution_bindings_are_exact(self) -> None:
        for field in (
            "source_inventory_sha256",
            "lock_sha256",
            "materializer_sha256",
        ):
            with self.subTest(field=field):
                self.assert_mutation_rejected("bindings", field, "0" * 64)
        receipt = copy.deepcopy(self.receipt)
        receipt["bindings"]["execution_sha256"] = "0" * 64
        with self.assertRaises(materializer.MaterializationError):
            self.validate(receipt)

    def test_every_lock_policy_field_is_exact(self) -> None:
        for field, original in self.lock["policy"].items():
            value = not original if isinstance(original, bool) else "forged"
            if isinstance(original, int) and not isinstance(original, bool):
                value = original + 1
            with self.subTest(field=field):
                self.assert_mutation_rejected("policy", field, value)

    def test_every_confinement_and_promotion_policy_field_is_exact(self) -> None:
        for section in ("confinement", "promotion"):
            for field, original in self.receipt[section].items():
                value = not original if isinstance(original, bool) else original + 1
                with self.subTest(section=section, field=field):
                    self.assert_mutation_rejected(section, field, value)


class IntegratedReceiptIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "tmp").mkdir()
        (
            self.receipt,
            self.environment_lock,
            self.producer_lock,
            self.scan,
            self.temporary_root,
        ) = make_valid_integrated_receipt(self.root)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def validate(self, receipt: dict[str, object]) -> None:
        with (
            mock.patch.object(
                materializer,
                "_checkout_state",
                return_value=("a" * 40, "b" * 40, ""),
            ),
            mock.patch.object(
                materializer,
                "_merge_base",
                return_value="7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            ),
        ):
            materializer.validate_integrated_receipt(
                receipt,
                self.environment_lock,
                self.producer_lock,
                expected_cache_scan=self.scan,
                expected_temporary_root=self.temporary_root,
            )

    def rebind(self, receipt: dict[str, object]) -> None:
        receipt["bindings"]["environment_receipt_sha256"] = materializer.sha_bytes(
            materializer.canonical_bytes(receipt["environment_receipt"])
        )
        receipt["bindings"]["producer_receipt_sha256"] = materializer.sha_bytes(
            (
                json.dumps(receipt["producer_receipt"], indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
        )
        receipt["bindings"]["execution_sha256"] = (
            materializer._integrated_execution_sha256(receipt)
        )

    def test_valid_integrated_envelope_passes_direct_validation(self) -> None:
        self.validate(self.receipt)

    def test_outer_rebinding_cannot_hide_independently_derived_mutations(self) -> None:
        mutations = (
            ("accounting", "capabilities_passed", 6),
            ("confinement", "network_calls", 1),
            ("cleanup", "producer_temporary_root_removed", False),
            ("bindings", "producer_executor_sha256", "0" * 64),
            ("promotion", "aggregate_is_promotable", False),
        )
        for section, field, value in mutations:
            with self.subTest(section=section, field=field):
                forged = copy.deepcopy(self.receipt)
                forged[section][field] = value
                self.rebind(forged)
                with self.assertRaises(materializer.MaterializationError):
                    self.validate(forged)

    def test_nested_cleanup_root_must_remain_canonical_and_absent(self) -> None:
        for forged_path in (
            "vss-spatial-ai-runtime.relative",
            "/tmp/../tmp/vss-spatial-ai-runtime.dotdot",
        ):
            with self.subTest(forged_path=forged_path):
                forged = copy.deepcopy(self.receipt)
                forged["producer_receipt"]["cleanup"][
                    "executor_owned_temporary_root"
                ] = forged_path
                self.rebind(forged)
                with self.assertRaises(materializer.MaterializationError):
                    self.validate(forged)

    def test_nested_accounting_mutations_fail_even_after_raw_and_outer_rebind(
        self,
    ) -> None:
        mutations = (
            ("bounded_capability_actions", 6),
            ("requests", 6),
            ("imported_product_function_invocations", 10),
            ("independent_runs", 1),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                forged = copy.deepcopy(self.receipt)
                forged["producer_receipt"]["capability_results"][0][field] = value
                self.rebind(forged)
                with self.assertRaises(materializer.MaterializationError):
                    self.validate(forged)
        forged = copy.deepcopy(self.receipt)
        forged["producer_receipt"]["capability_results"][0]["adjacent_negatives"].pop()
        self.rebind(forged)
        with self.assertRaises(materializer.MaterializationError):
            self.validate(forged)

    def test_nested_raw_sha_and_environment_mutations_fail(self) -> None:
        forged = copy.deepcopy(self.receipt)
        forged["bindings"]["producer_receipt_sha256"] = "0" * 64
        forged["bindings"]["execution_sha256"] = (
            materializer._integrated_execution_sha256(forged)
        )
        with self.assertRaises(materializer.MaterializationError):
            self.validate(forged)

        forged = copy.deepcopy(self.receipt)
        forged["environment_receipt"]["environment"]["installed_artifact_count"] = 55
        forged["environment_receipt"]["bindings"]["execution_sha256"] = (
            materializer._execution_sha256(forged["environment_receipt"])
        )
        self.rebind(forged)
        with self.assertRaises(materializer.MaterializationError):
            self.validate(forged)

    def test_nested_and_outer_authority_cannot_be_upgraded_independently(self) -> None:
        nested_mutations = {
            "development_smoke_only": True,
            "family_id": "forged-family",
            "eligible_capability_ids": [],
            "requires_separate_reviewed_metadata_integration": False,
            "receipt_is_runtime_evidence": False,
            "aggregate_is_promotable": False,
        }
        for field, value in nested_mutations.items():
            with self.subTest(scope="nested", field=field):
                forged = copy.deepcopy(self.receipt)
                forged["producer_receipt"]["promotion"][field] = value
                if field in forged["promotion"]:
                    forged["promotion"][field] = value
                self.rebind(forged)
                with self.assertRaises(materializer.MaterializationError):
                    self.validate(forged)
        outer_mutations = {
            "canonical_parity_mutated": True,
            "runtime_producer_mutated": True,
            **nested_mutations,
        }
        for field, value in outer_mutations.items():
            with self.subTest(scope="outer", field=field):
                forged = copy.deepcopy(self.receipt)
                forged["promotion"][field] = value
                self.rebind(forged)
                with self.assertRaises(materializer.MaterializationError):
                    self.validate(forged)


class InterfaceTests(unittest.TestCase):
    def test_default_invocation_is_inert(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, materializer.main([]))
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["writes_performed"])
        self.assertEqual("inert_plan", plan["mode"])

    def test_direct_nonisolated_cli_rejects_before_shadowable_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "materializer.py"
            shutil.copyfile(materializer.HERE / "materializer.py", script)
            (root / "json.py").write_text(
                "raise RuntimeError('shadow imported')\n", encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, os.fspath(script)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("requires isolated mode", result.stderr)
            self.assertNotIn("shadow imported", result.stderr)

    def test_materialize_api_rejects_nonisolated_runtime(self) -> None:
        if sys.flags.isolated:
            self.skipTest("test runner itself is isolated")
        with self.assertRaisesRegex(materializer.MaterializationError, "isolated"):
            materializer.materialize(materializer.load_lock(), [], Path("/tmp"))

    def test_publish_is_exclusive_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            materializer.publish_exclusive(path, "{}\n")
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            with self.assertRaisesRegex(materializer.MaterializationError, "exists"):
                materializer.publish_exclusive(path, "{}\n")

    def test_publish_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(materializer.MaterializationError, "secure"):
                materializer.publish_exclusive(link / "receipt.json", "{}\n")

    def test_publish_rejects_repository_destination(self) -> None:
        with self.assertRaisesRegex(materializer.MaterializationError, "outside"):
            materializer.publish_exclusive(HERE / "forbidden-receipt.json", "{}\n")
        self.assertFalse((HERE / "forbidden-receipt.json").exists())

    def test_publish_callback_failure_removes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"

            def drifted() -> None:
                raise materializer.MaterializationError("post-write drift")

            with self.assertRaisesRegex(
                materializer.MaterializationError, "post-write drift"
            ):
                materializer.publish_exclusive(
                    path, "{}\n", validate_after_write=drifted
                )
            self.assertFalse(path.exists())

    def test_publish_reread_and_fsync_failures_remove_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reread = root / "reread.json"
            with (
                mock.patch.object(materializer.os, "read", return_value=b"x"),
                self.assertRaisesRegex(
                    materializer.MaterializationError, "bytes differ"
                ),
            ):
                materializer.publish_exclusive(reread, "{}\n")
            self.assertFalse(reread.exists())
            fsync = root / "fsync.json"
            with (
                mock.patch.object(
                    materializer.os, "fsync", side_effect=OSError("fsync failed")
                ),
                self.assertRaisesRegex(
                    materializer.MaterializationError, "secure output"
                ),
            ):
                materializer.publish_exclusive(fsync, "{}\n")
            self.assertFalse(fsync.exists())

    def test_publish_does_not_delete_an_actor_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "receipt.json"
            displaced = root / "displaced.json"

            def replace_after_write() -> None:
                path.rename(displaced)
                path.write_text("actor replacement\n", encoding="utf-8")
                path.chmod(0o600)

            with self.assertRaisesRegex(
                materializer.MaterializationError, "identity changed"
            ):
                materializer.publish_exclusive(
                    path, "{}\n", validate_after_write=replace_after_write
                )
            self.assertEqual("actor replacement\n", path.read_text(encoding="utf-8"))
            self.assertTrue(displaced.is_file())

    def test_existing_output_preflight_skips_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            output.write_text("existing\n", encoding="utf-8")
            with (
                mock.patch.object(materializer, "materialize") as run,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                status = materializer.main(
                    [
                        "--execute",
                        "--acknowledge",
                        materializer.ACK,
                        "--output",
                        os.fspath(output),
                    ]
                )
            self.assertEqual(1, status)
            run.assert_not_called()

    def test_integrated_cli_requires_exact_all_and_acknowledgement(self) -> None:
        base = [
            "--execute",
            "--acknowledge",
            materializer.ACK,
            "--output",
            "/tmp/unused-integrated-receipt.json",
            "--run-canonical-spatial-ai-producer",
        ]
        for extra in ([], ["--producer-selection", "all"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(1, materializer.main(base + extra))

    def test_plain_execution_rejects_producer_only_flags(self) -> None:
        argv = [
            "--execute",
            "--acknowledge",
            materializer.ACK,
            "--output",
            "/tmp/unused-integrated-receipt.json",
            "--producer-selection",
            "all",
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, materializer.main(argv))


if __name__ == "__main__":
    unittest.main(verbosity=2)
