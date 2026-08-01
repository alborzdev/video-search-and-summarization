"""Adversarial tests for the offline recursive VSS documentation proof."""

from __future__ import annotations

import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[6]
SPEC = importlib.util.spec_from_file_location(
    "validate_recursive_coverage", PACKAGE / "validate_recursive_coverage.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def read_json(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


class RecursiveCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=PACKAGE)
        self.temp_dir = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_json(self, name: str, document: object) -> Path:
        path = self.temp_dir / name
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return path

    def repo_binding(self, path: Path) -> dict[str, str]:
        return {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": VALIDATOR.sha256_file(path),
        }

    def coverage_with_agent_candidate(self, candidate: dict) -> Path:
        candidate_path = self.write_json("agent-candidate.json", candidate)
        coverage = read_json("recursive-coverage.json")
        old_binding = coverage["agent_smartcity_binding"]
        coverage["agent_smartcity_binding"] = {
            **old_binding,
            **self.repo_binding(candidate_path),
        }
        return self.write_json("coverage.json", coverage)

    def graph_with_updated_summary(self, graph: dict) -> Path:
        targets = read_json("recursive-targets.json")["targets"]
        edges: list[list[str]] = []
        self_edges = 0
        for scan in graph["scans"]:
            source = scan["url_index"]
            for target in scan["outbound_target_indexes"]:
                edges.append([targets[source], targets[target]])
                if source == target:
                    self_edges += 1
        edges.sort()
        graph["graph_summary"]["canonical_directed_edge_count"] = len(edges)
        graph["graph_summary"]["self_edge_count"] = self_edges
        graph["graph_summary"]["canonical_url_pair_edge_set_sha256"] = (
            VALIDATOR.canonical_sha256(edges)
        )
        return self.write_json("graph.json", graph)

    def assert_validation_fails(self, message: str | None = None) -> None:
        with self.assertRaises(VALIDATOR.RecursiveCoverageError) as raised:
            VALIDATOR.validate()
        if message:
            self.assertIn(message, str(raised.exception))

    def test_exact_package_validates_without_network(self) -> None:
        with (
            mock.patch.object(socket, "socket", side_effect=AssertionError("network")),
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")),
        ):
            report = VALIDATOR.validate()
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["recursive_targets_including_index"], 172)
        self.assertEqual(report["added_descendants"], 19)
        self.assertTrue(report["fixed_point"])

    def test_duplicate_json_key_fails_closed(self) -> None:
        malformed = self.temp_dir / "duplicate.json"
        malformed.write_text('{"schema_version": 1, "schema_version": 1}\n')
        with mock.patch.object(VALIDATOR, "COVERAGE", malformed):
            self.assert_validation_fails("duplicate JSON key")

    def test_missing_recursive_target_fails(self) -> None:
        targets = read_json("recursive-targets.json")
        targets["targets"].pop()
        target_path = self.write_json("targets.json", targets)
        with mock.patch.object(VALIDATOR, "TARGETS", target_path):
            self.assert_validation_fails()

    def test_directed_edge_mutation_fails_hash_check(self) -> None:
        graph = read_json("crawl-graph.json")
        graph["scans"][0]["outbound_target_indexes"].pop()
        graph_path = self.write_json("graph.json", graph)
        with mock.patch.object(VALIDATOR, "GRAPH", graph_path):
            self.assert_validation_fails("directed edge count drift")

    def test_disconnected_graph_fails_fixed_point_algorithm(self) -> None:
        with self.assertRaisesRegex(
            VALIDATOR.RecursiveCoverageError,
            "crawl graph is not fully reachable",
        ):
            VALIDATOR.breadth_first_depths(
                ["start", "reachable", "disconnected"],
                {0: [1], 1: [], 2: []},
                0,
            )

    def test_category_swap_preserving_counts_fails_exact_sets(self) -> None:
        coverage = read_json("recursive-coverage.json")
        semantic = next(
            item
            for item in coverage["new_descendants"]
            if item["category"] == "semantic_omission"
        )
        external = next(
            item
            for item in coverage["new_descendants"]
            if item["category"] == "external_workflow_dependency"
        )
        semantic["category"], external["category"] = (
            external["category"],
            semantic["category"],
        )
        coverage_path = self.write_json("coverage.json", coverage)
        with mock.patch.object(VALIDATOR, "COVERAGE", coverage_path):
            self.assert_validation_fails("exact 8-page semantic set drift")

    def test_live_ledger_hash_drift_fails(self) -> None:
        coverage = read_json("recursive-coverage.json")
        coverage["live_ledger_binding"]["sha256"] = "0" * 64
        coverage_path = self.write_json("coverage.json", coverage)
        with mock.patch.object(VALIDATOR, "COVERAGE", coverage_path):
            self.assert_validation_fails("bound input hash drift")

    def test_stale_smartcity_candidate_url_fails(self) -> None:
        coverage = read_json("recursive-coverage.json")
        candidate_path = REPO_ROOT / coverage["agent_smartcity_binding"]["path"]
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        corrected = next(
            source
            for source in candidate["sources"]
            if source["uri"].endswith("/License-Information.html")
        )
        corrected["uri"] = VALIDATOR.BASE_URL + "smartcity-docs/License.html"
        mutated_coverage = self.coverage_with_agent_candidate(candidate)
        with mock.patch.object(VALIDATOR, "COVERAGE", mutated_coverage):
            self.assert_validation_fails(
                "agent-smartcity docs sources are not 40 recursive-graph members"
            )

    def test_missing_corrected_smartcity_candidate_url_fails(self) -> None:
        coverage = read_json("recursive-coverage.json")
        candidate_path = REPO_ROOT / coverage["agent_smartcity_binding"]["path"]
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["sources"] = [
            source
            for source in candidate["sources"]
            if not source["uri"].endswith("/Troubleshooting-Guide.html")
        ]
        mutated_coverage = self.coverage_with_agent_candidate(candidate)
        with mock.patch.object(VALIDATOR, "COVERAGE", mutated_coverage):
            self.assert_validation_fails(
                "agent-smartcity docs sources are not 40 recursive-graph members"
            )

    def test_semantic_reachability_overclaim_fails(self) -> None:
        coverage = read_json("recursive-coverage.json")
        coverage["new_descendants"][0][
            "semantic_proof_from_crawl_reachability"
        ] = True
        coverage_path = self.write_json("coverage.json", coverage)
        with mock.patch.object(VALIDATOR, "COVERAGE", coverage_path):
            self.assert_validation_fails()

    def test_unknown_field_fails_strict_schema(self) -> None:
        coverage = read_json("recursive-coverage.json")
        coverage["unreviewed"] = True
        coverage_path = self.write_json("coverage.json", coverage)
        with mock.patch.object(VALIDATOR, "COVERAGE", coverage_path):
            self.assert_validation_fails("schema validation failed")


if __name__ == "__main__":
    unittest.main()
