from __future__ import annotations

import ast
import copy
import importlib.util
from pathlib import Path
import sys
from typing import Any
import unittest
from unittest import mock


LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_71_current_source_rebase_validator", LANE / "validator.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class CurrentSourceRebaseTest(unittest.TestCase):
    result: dict[str, Any]
    contract: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = VALIDATOR.validate()
        cls.contract = VALIDATOR._contract()

    def test_exact_71_row_partition(self) -> None:
        self.assertEqual(self.result["retained_candidate_rows"], 71)
        self.assertEqual(self.result["unchanged_rows"], 39)
        self.assertEqual(self.result["rebased_rows"], 32)
        self.assertEqual(
            set(self.result["rebased_entry_ids"]), VALIDATOR.EXPECTED_REBASED_IDS
        )
        self.assertIn(
            "manifest-gap.audio-understanding.00-audio-aware-base-workflow",
            self.result["rebased_entry_ids"],
        )

    def test_exact_sixteen_path_overlay_is_current(self) -> None:
        self.assertEqual(self.result["current_source_overlay_paths"], 16)
        self.assertEqual(
            set(self.result["overlay_reference_counts"]),
            set(VALIDATOR.EXPECTED_OVERLAY),
        )
        self.assertEqual(
            self.result["overlay_reference_counts"][
                "services/agent/src/vss_agents/tools/video_report_gen.py"
            ],
            3,
        )
        for path, digest in VALIDATOR.EXPECTED_OVERLAY.items():
            with self.subTest(path=path):
                self.assertEqual(VALIDATOR._sha(VALIDATOR._read(path)), digest)

    def test_all_182_retained_lock_references_resolve(self) -> None:
        self.assertEqual(self.result["current_source_lock_references"], 182)
        self.assertTrue(all(self.result["overlay_reference_counts"].values()))

    def test_kafka_topology_has_guarded_call_chain(self) -> None:
        topology = self.result["kafka_topology"]
        self.assertEqual(
            topology["call_chain"],
            [
                "_on_vlm_chunk_response",
                "_publish_chunk_messages_if_active",
                "_send_protobuf_to_kafka",
            ],
        )
        self.assertEqual(topology["publisher_send_call_count"], 2)
        self.assertEqual(topology["on_response_direct_send_call_count"], 0)
        self.assertEqual(topology["on_response_pre_publish_terminal_rechecks"], 2)
        self.assertTrue(topology["publication_suppressed_after_abort_or_finalized"])

    def test_kafka_direct_send_bypass_is_rejected(self) -> None:
        topology = self.contract["kafka_topology"]
        source = VALIDATOR._read(topology["source_path"])
        mutated = source.replace(
            b"if not self._publish_chunk_messages_if_active(\n",
            b"self._send_protobuf_to_kafka(b'x', chunk_result, req_info)\n\n        if not self._publish_chunk_messages_if_active(\n",
            1,
        )
        with mock.patch.object(
            VALIDATOR,
            "_read",
            side_effect=lambda path: (
                mutated if path == topology["source_path"] else VALIDATOR._read(path)
            ),
        ):
            with self.assertRaisesRegex(VALIDATOR.RebaseError, "bypasses guarded"):
                VALIDATOR._validate_kafka_topology(self.contract)

    def test_nat_inventory_is_exact_64_equals_44_plus_12_plus_8(self) -> None:
        nat = self.result["nat_inventory"]
        self.assertEqual(nat["historical_denominator"], 44)
        self.assertEqual(nat["current_denominator"], 64)
        self.assertEqual(nat["search_addition_count"], 12)
        self.assertEqual(nat["released_route_addition_count"], 8)
        self.assertEqual(
            set(nat["search_additions"]), VALIDATOR.EXPECTED_SEARCH_ADDITIONS
        )
        self.assertEqual(
            set(nat["released_route_additions"]),
            VALIDATOR.EXPECTED_RELEASED_ROUTE_ADDITIONS,
        )

    def test_eight_historical_nat_routes_remain_required(self) -> None:
        nat = self.result["nat_inventory"]
        self.assertEqual(nat["required_nat_generate_chat_route_count"], 8)
        self.assertEqual(
            set(nat["required_nat_generate_chat_routes"]), VALIDATOR.EXPECTED_NAT_ROUTES
        )

    def test_partition_tampering_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["partition"]["rebased_entry_ids"].pop()
        with mock.patch.object(VALIDATOR, "_contract", return_value=contract):
            with self.assertRaisesRegex(VALIDATOR.RebaseError, "partition drift"):
                VALIDATOR.validate()

    def test_overlay_tampering_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["current_source_overlay"][0]["sha256"] = "0" * 64
        with mock.patch.object(VALIDATOR, "_contract", return_value=contract):
            with self.assertRaisesRegex(VALIDATOR.RebaseError, "overlay drift"):
                VALIDATOR.validate()

    def test_runtime_evidence_and_promotion_stay_empty(self) -> None:
        self.assertEqual(self.result["runtime_evidence"], [])
        self.assertFalse(self.result["can_mark_passed_current"])
        self.assertEqual(
            self.result["official_capability_effect"], "none_candidate_only"
        )
        self.assertFalse(self.result["historical_inventory_rewritten"])
        self.assertFalse(self.result["historical_receipt_rewritten"])
        self.assertFalse(self.result["historical_dispatch_replayed"])

    def test_no_effectful_imports_or_calls_exist(self) -> None:
        tree = ast.parse((LANE / "validator.py").read_text())
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertFalse(
            imported
            & {
                "asyncio",
                "docker",
                "httpx",
                "multiprocessing",
                "requests",
                "shutil",
                "socket",
                "subprocess",
                "tempfile",
                "threading",
                "urllib",
            }
        )


if __name__ == "__main__":
    unittest.main()
