# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).parents[1] / "audit_track_lifecycle.py"
spec = importlib.util.spec_from_file_location("audit_track_lifecycle", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(
    source,
    sequence,
    ns,
    identifier,
    *,
    session="current",
    observed=True,
    ambiguity=None,
):
    return {
        "sourceId": source,
        "sourceSessionId": session,
        "sourceTimeNs": str(ns),
        "sequence": str(sequence),
        "objects": [
            {
                "localTrackId": identifier,
                "class": "person",
                "bboxPx": [10, 10, 20, 40],
                "observedThisFrame": observed,
                "confidence": 0.9 if observed else None,
            }
        ],
        "nativeTrackAmbiguity": ambiguity or {},
    }


class AuditTrackLifecycleTests(unittest.TestCase):
    def audit(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.ndjson"
            path.write_text("".join(json.dumps(item) + "\n" for item in rows))
            before = path.read_bytes()
            result = module.audit(path, **kwargs)
            self.assertEqual(path.read_bytes(), before)
            return result

    def test_exact_prefix_excludes_later_appends_and_retains_input_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.ndjson"
            prefix = (json.dumps(row("a", 0, 1_000_000_000, "7")) + "\n").encode()
            path.write_bytes(
                prefix + (json.dumps(row("a", 1, 2_000_000_000, "8")) + "\n").encode()
            )
            result = module.audit(path, snapshot_bytes=len(prefix))
            self.assertEqual(result["rows"], 1)
            self.assertEqual(
                result["sourceSegment"]["sha256"], hashlib.sha256(prefix).hexdigest()
            )
            self.assertEqual(result["bySource"]["a"]["personIdNumericRange"], [7, 7])

    def test_latest_session_selection_reports_exclusions_and_censoring(self):
        result = self.audit(
            [
                row("a", 0, 1_000_000_000, "42", session="retired"),
                row("a", 0, 2_000_000_000, "18446744073709551614"),
                row("a", 1, 2_100_000_000, "18446744073709551613"),
            ]
        )
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["selection"]["olderSessionRowsExcluded"], 1)
        self.assertEqual(
            result["selection"]["sourceSessionCountsBeforeSelection"], {"a": 2}
        )
        source = result["bySource"]["a"]
        self.assertEqual(source["windowCensoring"]["leftCensoredIds"], 1)
        self.assertEqual(source["windowCensoring"]["rightCensoredIds"], 1)
        self.assertEqual(source["windowCensoring"]["uncensoredWithinWindowIds"], 0)
        self.assertEqual(
            source["replacementExamples"][0]["oldId"], "18446744073709551614"
        )

    def test_adjacent_replacement_reports_existing_peer_without_creating_alias(self):
        result = self.audit(
            [
                row("a", 0, 1_000_000_000, "56"),
                row("b", 0, 1_000_000_010, "28"),
                row("a", 1, 1_100_000_000, "28"),
                row("b", 1, 1_100_000_010, "28"),
            ]
        )
        source = result["bySource"]["a"]
        self.assertEqual(source["uniqueIdsByClass"]["person"], 2)
        self.assertEqual(source["highIouAdjacentReplacements"]["iouAtLeast0.8"], 1)
        example = source["replacementExamples"][0]
        self.assertTrue(example["toLowerId"])
        self.assertTrue(example["newPreviouslyPresentPeer"])
        self.assertEqual(example["iou"], 1)
        self.assertNotIn("aliases", result)

    def test_time_filter_is_inclusive_and_counts_both_boundaries_as_censored(self):
        result = self.audit(
            [
                row("a", 0, 1_000_000_000, "1"),
                row("a", 1, 2_000_000_000, "1"),
                row("a", 2, 3_000_000_000, "2"),
            ],
            start_ns=2_000_000_000,
            end_ns=3_000_000_000,
        )
        self.assertEqual(result["rows"], 2)
        source = result["bySource"]["a"]
        self.assertEqual(source["durationSeconds"], 1)
        self.assertEqual(source["newPersonIdsExcludingLeftCensoredPerMinute"], 60)
        self.assertEqual(source["windowCensoring"]["leftCensoredIds"], 1)
        self.assertEqual(source["windowCensoring"]["rightCensoredIds"], 1)

    def test_prediction_and_sdk_ambiguity_remain_distinct_diagnostics(self):
        result = self.audit(
            [
                row(
                    "a",
                    0,
                    1,
                    "1",
                    observed=False,
                    ambiguity={"omittedObjectCount": 2, "duplicateIdCount": 1},
                )
            ]
        )
        source = result["bySource"]["a"]
        self.assertEqual(source["observedPersonSamples"], 0)
        self.assertEqual(source["ambiguousFrames"], 1)
        self.assertEqual(source["ambiguousOmittedObjects"], 2)
        self.assertEqual(source["duplicateIdCountTotal"], 1)
        self.assertEqual(result["diagnosticRows"], 0)

    def test_invalid_or_unavailable_bounds_fail_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.ndjson"
            path.write_text("")
            with self.assertRaises(ValueError):
                module.audit(path, snapshot_bytes=1)
            with self.assertRaises(ValueError):
                module.audit(path, start_ns=2, end_ns=1)
            self.assertEqual(path.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
