#!/usr/bin/env python3
"""Self-contained adversarial tests for the offline environment package."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
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
            ):
                with self.assertRaisesRegex(
                    materializer.MaterializationError, "injected"
                ):
                    materializer.materialize(lock, [parent], parent)
            names = sorted(path.name for path in parent.iterdir())
            self.assertEqual(["source.body"], names)


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


class InterfaceTests(unittest.TestCase):
    def test_default_invocation_is_inert(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, materializer.main([]))
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["writes_performed"])
        self.assertEqual("inert_plan", plan["mode"])

    def test_publish_is_exclusive_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            materializer.publish_exclusive(path, "{}\n")
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            with self.assertRaisesRegex(materializer.MaterializationError, "exists"):
                materializer.publish_exclusive(path, "{}\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
