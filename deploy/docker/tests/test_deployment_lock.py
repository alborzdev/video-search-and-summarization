"""Focused behaviour tests for the static deployment compatibility validator."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_deployment_lock.py"
SPEC = importlib.util.spec_from_file_location("deployment_lock_validator", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class DeploymentLockValidatorTests(unittest.TestCase):
    def write_fixture(self, reference: str = "registry.example/worker:1.2.3", *, declared: str | None = None) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        compose = root / "deploy/docker/compose.yml"
        compose.parent.mkdir(parents=True)
        compose.write_text(f"services:\n  worker:\n    image: {reference}\n", encoding="utf-8")
        context = root / "local-build"
        context.mkdir()
        (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        manifest = {"schema_version": 1, "scope": {"name": "fixture", "entrypoint": "none", "compose_files": ["deploy/docker/compose.yml"]}, "images": [{"id": "worker", "source_file": "deploy/docker/compose.yml", "source_reference": declared or reference, "pin_status": "unresolved-tag"}], "local_builds": [{"compose_file": "deploy/docker/compose.yml", "context": "local-build", "dockerfile": "Dockerfile"}]}
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return temporary, root, manifest_path

    def test_tagged_reference_and_local_build_validate_without_side_effects(self) -> None:
        temporary, root, manifest = self.write_fixture()
        self.addCleanup(temporary.cleanup)
        status, messages = validator.validate(manifest, root)
        self.assertEqual(status, 0)
        self.assertTrue(any(message.startswith("WARN: image worker remains unresolved-tag") for message in messages))

    def test_missing_manifest_reference_is_an_error(self) -> None:
        temporary, root, manifest = self.write_fixture(declared="registry.example/other:1")
        self.addCleanup(temporary.cleanup)
        status, messages = validator.validate(manifest, root)
        self.assertEqual(status, 1)
        self.assertTrue(any("missing from manifest" in message for message in messages))

    def test_untagged_reference_is_flagged_and_strict_mode_fails(self) -> None:
        temporary, root, manifest = self.write_fixture(reference="registry.example/worker")
        self.addCleanup(temporary.cleanup)
        status, messages = validator.validate(manifest, root, strict=True)
        self.assertEqual(status, 1)
        self.assertTrue(any("untagged or unresolved" in message for message in messages))

    def test_missing_build_dockerfile_is_an_error(self) -> None:
        temporary, root, manifest = self.write_fixture()
        self.addCleanup(temporary.cleanup)
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["local_builds"][0]["dockerfile"] = "Missing.Dockerfile"
        manifest.write_text(json.dumps(document), encoding="utf-8")
        status, messages = validator.validate(manifest, root)
        self.assertEqual(status, 1)
        self.assertTrue(any("Dockerfile is missing" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
