#!/usr/bin/env python3

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import merge_live


class MergeLiveTests(unittest.TestCase):
    def test_pinned_baseline_build_is_exact_and_planning_only(self) -> None:
        ledger, manifest, acceptance, oracles, receipt = merge_live.build_unmerged(
            from_baseline=True
        )
        self.assertEqual(len(ledger["capabilities"]), 276)
        self.assertEqual(len(manifest["features"]), 55)
        self.assertEqual(len(acceptance["wave3_contracts"]["planning_requirements"]), 110)
        self.assertTrue(all(not item["executor_ready"] for item in acceptance["wave3_contracts"]["planning_requirements"]))
        self.assertTrue(all(not item["evidence"] for item in oracles["oracles"]))
        self.assertEqual(receipt["lifecycle"], "wholly_merged")
        by_id = {item["id"]: item for item in ledger["capabilities"]}
        self.assertEqual(
            by_id["deployment.network.bridge-firewall"]["feature_id"],
            "offline-security",
        )
        external = next(
            item for item in acceptance["coverage"]["features"]
            if item["feature_id"] == "synthetic-data-workflows-external"
        )
        self.assertIn("external-simulation-toolchain-required", external["blocker_ids"])
        self.assertNotIn("external-managed-model-endpoint-required", external["blocker_ids"])

    def test_output_and_receipt_co_tamper_is_rejected(self) -> None:
        values = merge_live.build_unmerged(from_baseline=True)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = [root / name for name in ("ledger.json", "manifest.json", "acceptance.json", "oracles.json", "receipt.json")]
            for path, value in zip(paths, values, strict=True):
                path.write_bytes(merge_live.encoded(value))
            ledger = json.loads(paths[0].read_text())
            ledger["capabilities"][0]["title"] += " tampered"
            paths[0].write_bytes(merge_live.encoded(ledger))
            receipt = json.loads(paths[4].read_text())
            receipt["outputs"]["official-capabilities.json"] = merge_live.sha_file(paths[0])
            paths[4].write_bytes(merge_live.encoded(receipt))
            with mock.patch.multiple(
                merge_live,
                LEDGER=paths[0], MANIFEST=paths[1], ACCEPTANCE=paths[2],
                ORACLES=paths[3], RECEIPT=paths[4],
            ):
                with self.assertRaises(merge_live.MergeError):
                    merge_live.validate_merged_state()

    def test_feature_map_semantic_mutation_is_rejected(self) -> None:
        plan = merge_live.load(merge_live.PLAN)
        feature_map = copy.deepcopy(merge_live.load(merge_live.FEATURE_MAP))
        feature_map["runtime.rtvi.input-codec-boundary"] = "rt-vlm"
        with self.assertRaises(merge_live.MergeError):
            merge_live.validate_bound_inputs(plan, feature_map)


if __name__ == "__main__":
    unittest.main()
