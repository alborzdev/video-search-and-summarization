from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "thor_model_requirements", ROOT / "verify_thor_requirements.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class ThorRequirementsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requirements = VERIFIER.load_json(ROOT / "thor-requirements.json")

    def _validate_mutated(
        self, value: dict[str, object]
    ) -> tuple[list[str], list[str], list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return VERIFIER.validate_requirements(path)

    def test_checked_in_contract_is_coherent_and_fail_closed(self) -> None:
        errors, canonical, selectors = VERIFIER.validate_requirements()
        self.assertEqual(errors, [])
        self.assertEqual(
            canonical,
            [
                (
                    "canonical.runtime_evidence: approved semantic runtime receipt is "
                    "absent"
                )
            ],
        )
        self.assertEqual(len(selectors), 24)

    def test_cli_static_passes_but_canonical_complete_gate_fails(self) -> None:
        static = subprocess.run(
            [sys.executable, str(ROOT / "verify_thor_requirements.py"), "static"],
            check=False,
            capture_output=True,
            text=True,
        )
        complete = subprocess.run(
            [
                sys.executable,
                str(ROOT / "verify_thor_requirements.py"),
                "static",
                "--require-thor-complete",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(static.returncode, 0, static.stderr)
        self.assertEqual(complete.returncode, 2)
        self.assertIn("canonical official-edge blockers: 1", static.stdout)
        self.assertIn("canonical.runtime_evidence", complete.stderr)

    def test_denominators_cannot_be_conflated(self) -> None:
        mutated = copy.deepcopy(self.requirements)
        mutated["denominators"]["canonical_official_edge_pair"]["llm"]["repository"] = (
            "nvidia/nvidia-nemotron-nano-9b-v2"
        )
        errors, _, _ = self._validate_mutated(mutated)
        self.assertTrue(
            any("canonical Thor LLM denominator changed" in error for error in errors)
        )

    def test_all_selector_denominator_cannot_become_thor_required(self) -> None:
        mutated = copy.deepcopy(self.requirements)
        mutated["denominators"]["all_advertised_agent_selectors"][
            "required_for_thor_feature_parity"
        ] = True
        errors, _, _ = self._validate_mutated(mutated)
        self.assertTrue(
            any(
                "must remain distinct from Thor feature parity" in error
                for error in errors
            )
        )

    def test_source_lock_cannot_be_repointed_or_rehashed(self) -> None:
        mutated = copy.deepcopy(self.requirements)
        mutated["source_locks"][0]["sha256"] = "0" * 64
        errors, _, _ = self._validate_mutated(mutated)
        self.assertIn("source-lock inventory or digest changed", errors)

    def test_readiness_only_cannot_be_promoted_to_runtime_evidence(self) -> None:
        mutated = copy.deepcopy(self.requirements)
        runtime = mutated["denominators"]["canonical_official_edge_pair"][
            "runtime_evidence"
        ]
        runtime["state"] = "qualified"
        runtime["accepted_evidence_contract"] = (
            "deploy/docker/thor-local/qualification/official-edge-readiness/staging-plan.json"
        )
        runtime["readiness_only_is_sufficient"] = True
        errors, _, _ = self._validate_mutated(mutated)
        self.assertTrue(
            any("changed without a reviewed collector" in error for error in errors)
        )

    def test_runtime_receipt_path_and_digest_are_required_together(self) -> None:
        errors, canonical, _ = VERIFIER.validate_requirements(
            runtime_receipt_path=Path("/tmp/fake-receipt.json")
        )
        self.assertIn(
            "runtime receipt path and SHA-256 must be supplied together", errors
        )
        self.assertTrue(any("runtime_evidence" in item for item in canonical))

    def test_runtime_receipt_must_be_absolute_and_source_approved(self) -> None:
        errors, _, _ = VERIFIER.validate_requirements(
            runtime_receipt_path=Path("relative.json"),
            runtime_receipt_sha256="0" * 64,
        )
        self.assertIn("runtime receipt path must be absolute", errors)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            errors, canonical, _ = VERIFIER.validate_requirements(
                runtime_receipt_path=receipt,
                runtime_receipt_sha256=VERIFIER.sha256(receipt),
            )
        self.assertIn("runtime receipt is not source-approved", errors)
        self.assertTrue(any("runtime_evidence" in item for item in canonical))

    def test_approval_authority_is_verifier_pinned_and_empty(self) -> None:
        authority = VERIFIER.load_json(ROOT / "approved-runtime-receipt.json")
        self.assertEqual(authority["state"], "none_approved")
        self.assertEqual(authority["approvals"], [])
        self.assertEqual(
            VERIFIER.sha256(ROOT / "approved-runtime-receipt.json"),
            VERIFIER.APPROVAL_AUTHORITY_SHA256,
        )

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
            with self.assertRaises(VERIFIER.DuplicateKeyError):
                VERIFIER.load_json(path)


if __name__ == "__main__":
    unittest.main()
