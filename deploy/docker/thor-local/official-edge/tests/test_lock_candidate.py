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

import lock_candidate as lc  # noqa: E402


def artifact_fixture(root: Path) -> tuple[Path, Path]:
    repository = root / lc.verifier.EDGE_CACHE_DIRECTORY
    snapshot = repository / "snapshots" / lc.verifier.EDGE_REVISION
    blobs = repository / "blobs"
    snapshot.mkdir(parents=True)
    blobs.mkdir()
    blob_name = "b" * 64
    (blobs / blob_name).write_bytes(b"edge")
    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.safetensors").symlink_to(f"../../blobs/{blob_name}")
    cosmos = root / "cosmos"
    cosmos.mkdir()
    (cosmos / "weights.bin").write_bytes(b"cosmos")
    return snapshot, cosmos


class LockCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (lc.HERE / "lock-candidate.schema.json").read_text(encoding="utf-8")
        )

    def test_plan_is_inert_and_schema_valid(self) -> None:
        with mock.patch.object(lc, "build_candidate") as build:
            output = io.StringIO()
            with redirect_stdout(output):
                result = lc.main(["plan"])
        self.assertEqual(result, 0)
        build.assert_not_called()
        payload = json.loads(output.getvalue())
        jsonschema.Draft202012Validator(self.schema).validate(payload)
        self.assertFalse(payload["filesystem_reads_performed"])

    def test_wrong_acknowledgement_fails_before_hashing(self) -> None:
        errors = io.StringIO()
        with mock.patch.object(lc, "build_candidate") as build:
            with redirect_stderr(errors):
                result = lc.main(
                    [
                        "generate",
                        "--acknowledgement",
                        "yes",
                        "--edge4b-snapshot",
                        "/edge",
                        "--cosmos3-cache",
                        "/cosmos",
                    ]
                )
        self.assertEqual(result, 1)
        build.assert_not_called()
        self.assertIn(lc.ACKNOWLEDGEMENT, errors.getvalue())

    def test_candidate_is_read_only_schema_valid_and_not_a_promoted_lock(self) -> None:
        before = lc.verifier.DEFAULT_ARTIFACT_LOCK.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            snapshot, cosmos = artifact_fixture(Path(temporary))
            with mock.patch.object(lc.verifier.subprocess, "run") as run:
                payload = lc.build_candidate(snapshot, cosmos)
            run.assert_not_called()
            jsonschema.Draft202012Validator(self.schema).validate(payload)
            self.assertEqual(payload["candidate_state"], "candidate_only_not_promoted")
            self.assertFalse(payload["promotion_performed"])
            proposed = payload["proposed_artifact_lock"]
            self.assertEqual(proposed["lock_state"], "candidate_only_unqualified")
            for artifact in proposed["artifacts"].values():
                self.assertEqual(artifact["state"], "local_bytes_only_unqualified")
                self.assertEqual(
                    artifact["provenance"]["state"],
                    "local_bytes_only_not_independently_verified",
                )
            self.assertIn("blob_tree", proposed["artifacts"]["edge4b"])
            self.assertEqual(
                proposed["artifacts"]["edge4b"]["identity"]["revision"],
                lc.verifier.EDGE_REVISION,
            )
            wrapper = Path(temporary) / "candidate.json"
            wrapper.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                lc.verifier.ContractError, "artifact lock must contain"
            ):
                lc.verifier.verify_artifacts(wrapper, snapshot, cosmos)
            proposed_path = Path(temporary) / "proposed-lock.json"
            proposed_path.write_text(json.dumps(proposed), encoding="utf-8")
            with self.assertRaisesRegex(
                lc.verifier.ContractError, "intentionally incomplete"
            ):
                lc.verifier.verify_artifacts(proposed_path, snapshot, cosmos)
        self.assertEqual(before, lc.verifier.DEFAULT_ARTIFACT_LOCK.read_bytes())

    def test_wrong_revision_and_noncanonical_blob_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, cosmos = artifact_fixture(root)
            wrong = snapshot.parent / ("f" * 40)
            snapshot.rename(wrong)
            with self.assertRaisesRegex(lc.CandidateError, "snapshot revision"):
                lc.build_candidate(wrong, cosmos)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, cosmos = artifact_fixture(root)
            symlink = snapshot / "model.safetensors"
            symlink.unlink()
            (snapshot.parent.parent / "blobs" / "short").write_bytes(b"bad")
            symlink.symlink_to("../../blobs/short")
            with self.assertRaisesRegex(lc.CandidateError, "canonical HF blob target"):
                lc.build_candidate(snapshot, cosmos)


if __name__ == "__main__":
    unittest.main()
