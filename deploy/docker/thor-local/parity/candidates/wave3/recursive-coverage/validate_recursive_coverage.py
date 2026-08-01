#!/usr/bin/env python3

"""Offline validation for the VSS 3.2.1 recursive docs fixed point."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[6]
TARGETS = SCRIPT_DIR / "recursive-targets.json"
TARGETS_SCHEMA = SCRIPT_DIR / "recursive-targets.schema.json"
GRAPH = SCRIPT_DIR / "crawl-graph.json"
GRAPH_SCHEMA = SCRIPT_DIR / "crawl-graph.schema.json"
COVERAGE = SCRIPT_DIR / "recursive-coverage.json"
COVERAGE_SCHEMA = SCRIPT_DIR / "recursive-coverage.schema.json"
BASE_URL = "https://docs.nvidia.com/vss/3.2.1/"
START_URL = BASE_URL + "index.html"

EXPECTED_SEMANTIC = frozenset(
    BASE_URL + path
    for path in """warehouse-docs/2D-profile-with-agents.html
warehouse-docs/2D-profile.html
warehouse-docs/2D-single-camera-detection-and-tracking-RTDETR.html
warehouse-docs/3D-multi-camera-detection-and-tracking-MV3DT.html
warehouse-docs/3D-multi-camera-detection-and-tracking-Sparse4D.html
warehouse-docs/3D-profile.html
warehouse-docs/CR.html
warehouse-docs/MV3DT-profile.html""".splitlines()
)
EXPECTED_EXTERNAL = frozenset(
    BASE_URL + path
    for path in """warehouse-docs/Camera-Calibration.html
warehouse-docs/Camera-Placement.html
warehouse-docs/Customized-Scene-Saving.html
warehouse-docs/Dataset-Post-Processing.html
warehouse-docs/Development-Tools-Setup.html
warehouse-docs/NavMesh-Setup.html
warehouse-docs/Quick-Start-for-SDG.html
warehouse-docs/Semantic-Label-Setup.html
warehouse-docs/Sim2Real-Data-Transfer.html""".splitlines()
)
EXPECTED_NAVIGATION = frozenset(
    {
        BASE_URL + "warehouse-docs/Scene-Customization.html",
        BASE_URL + "warehouse-docs/Synthetic-Data-Generation.html",
    }
)
EXPECTED_CORRECTED_SMARTCITY = frozenset(
    {
        BASE_URL + "smartcity-docs/License-Information.html",
        BASE_URL + "smartcity-docs/Troubleshooting-Guide.html",
    }
)
EXPECTED_STALE_SMARTCITY = frozenset(
    {
        BASE_URL + "smartcity-docs/License.html",
        BASE_URL + "smartcity-docs/Troubleshooting.html",
    }
)


class RecursiveCoverageError(ValueError):
    """The recursive denominator is malformed, stale, or overclaims semantics."""


def _reject_constant(value: str) -> None:
    raise RecursiveCoverageError(f"non-finite JSON number is forbidden: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecursiveCoverageError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except OSError as exc:
        raise RecursiveCoverageError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RecursiveCoverageError(f"invalid JSON in {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_schema(document: Any, schema: Any, label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
    except (SchemaError, ValidationError) as exc:
        raise RecursiveCoverageError(
            f"{label} schema validation failed: {exc.message}"
        ) from exc


def repo_file(binding: dict[str, Any]) -> Path:
    relative = Path(binding["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise RecursiveCoverageError(f"unsafe repository path: {relative}")
    path = REPO_ROOT / relative
    if relative.as_posix() == "deploy/docker/thor-local/parity/official-capabilities.json":
        sys.path.insert(0, str(SCRIPT_DIR.parent))
        import lifecycle as wave3_lifecycle

        path = wave3_lifecycle.validation_path(path)
    if path.is_symlink() or not path.is_file():
        raise RecursiveCoverageError(
            f"bound input is not a regular non-symlink file: {relative}"
        )
    if not path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise RecursiveCoverageError(f"bound input escapes repository: {relative}")
    observed = sha256_file(path)
    if observed != binding["sha256"]:
        raise RecursiveCoverageError(
            f"bound input hash drift for {relative}: {observed} != {binding['sha256']}"
        )
    return path


def breadth_first_depths(
    targets: list[str], adjacency: dict[int, list[int]], start_index: int
) -> tuple[dict[int, int], list[dict[str, int]]]:
    depths = {start_index: 0}
    frontier = {start_index}
    rounds: list[dict[str, int]] = []
    round_number = 0
    while frontier:
        new_targets: set[int] = set()
        for source in frontier:
            for target in adjacency[source]:
                if target not in depths:
                    new_targets.add(target)
        for target in new_targets:
            depths[target] = round_number + 1
        rounds.append(
            {
                "round": round_number,
                "frontier_count": len(frontier),
                "new_url_count": len(new_targets),
                "discovered_total": len(depths),
            }
        )
        frontier = new_targets
        round_number += 1
    rounds.append(
        {
            "round": round_number,
            "frontier_count": 0,
            "new_url_count": 0,
            "discovered_total": len(depths),
        }
    )
    if len(depths) != len(targets):
        raise RecursiveCoverageError(
            f"crawl graph is not fully reachable: {len(depths)} of {len(targets)}"
        )
    return depths, rounds


def validate() -> dict[str, Any]:
    targets_doc = load_json(TARGETS)
    graph = load_json(GRAPH)
    coverage = load_json(COVERAGE)
    validate_schema(targets_doc, load_json(TARGETS_SCHEMA), "recursive targets")
    validate_schema(graph, load_json(GRAPH_SCHEMA), "crawl graph")
    validate_schema(coverage, load_json(COVERAGE_SCHEMA), "recursive coverage")

    targets = targets_doc["targets"]
    if targets != sorted(targets) or len(set(targets)) != 172:
        raise RecursiveCoverageError("recursive targets must be 172 unique sorted URLs")
    if START_URL not in targets:
        raise RecursiveCoverageError("recursive targets omit the start index")
    if canonical_sha256(targets) != targets_doc["canonical_reachable_set_sha256"]:
        raise RecursiveCoverageError("recursive target-set hash drift")
    excluding_start = sorted(set(targets) - {START_URL})
    if canonical_sha256(excluding_start) != targets_doc[
        "canonical_reachable_excluding_start_sha256"
    ]:
        raise RecursiveCoverageError("171-page target-set hash drift")

    target_path = repo_file(graph["target_binding"])
    if target_path != TARGETS:
        raise RecursiveCoverageError("crawl graph binds a different recursive target file")
    scans = graph["scans"]
    scan_indexes = [item["url_index"] for item in scans]
    if scan_indexes != list(range(172)):
        raise RecursiveCoverageError("crawl scans must cover sorted indexes 0 through 171")
    adjacency: dict[int, list[int]] = {}
    edges: list[list[str]] = []
    self_edges = 0
    for scan in scans:
        source = scan["url_index"]
        outbound = scan["outbound_target_indexes"]
        if outbound != sorted(outbound) or len(set(outbound)) != len(outbound):
            raise RecursiveCoverageError(f"outbound indexes are not unique/sorted: {source}")
        adjacency[source] = outbound
        for target in outbound:
            edges.append([targets[source], targets[target]])
            if source == target:
                self_edges += 1
    edges.sort()
    summary = graph["graph_summary"]
    if len(edges) != summary["canonical_directed_edge_count"]:
        raise RecursiveCoverageError("directed edge count drift")
    if self_edges != summary["self_edge_count"]:
        raise RecursiveCoverageError("self-edge count drift")
    if canonical_sha256(edges) != summary["canonical_url_pair_edge_set_sha256"]:
        raise RecursiveCoverageError("canonical directed edge-set hash drift")

    start_index = targets.index(START_URL)
    depths, rounds = breadth_first_depths(targets, adjacency, start_index)
    if rounds != graph["fixed_point_rounds"]:
        raise RecursiveCoverageError("stored fixed-point rounds differ from graph BFS")
    depth_counts = Counter(depths.values())
    expected_depth_counts = {
        int(depth): count for depth, count in targets_doc["depth_counts"].items()
    }
    if depth_counts != expected_depth_counts:
        raise RecursiveCoverageError(f"crawl depth counts drift: {dict(depth_counts)}")
    if rounds[-2]["new_url_count"] != 0 or rounds[-1]["frontier_count"] != 0:
        raise RecursiveCoverageError("crawl does not have an explicit empty fixed point")

    recursive_target_path = repo_file(coverage["recursive_target_binding"])
    crawl_graph_path = repo_file(coverage["crawl_graph_binding"])
    if recursive_target_path != TARGETS or crawl_graph_path != GRAPH:
        raise RecursiveCoverageError("coverage binds different recursive proof files")
    direct_targets_path = repo_file(coverage["direct_index_bindings"]["targets"])
    repo_file(coverage["direct_index_bindings"]["coverage"])
    direct_targets_doc = load_json(direct_targets_path)
    direct_targets = set(direct_targets_doc["targets"])
    if len(direct_targets) != 152 or START_URL in direct_targets:
        raise RecursiveCoverageError("direct-index binding no longer has 152 descendants")
    if not direct_targets.issubset(targets):
        raise RecursiveCoverageError("direct-index URLs are not a subset of fixed point")
    added = set(targets) - direct_targets - {START_URL}
    if len(added) != 19 or canonical_sha256(sorted(added)) != coverage["comparison"][
        "canonical_added_descendant_set_sha256"
    ]:
        raise RecursiveCoverageError("exact 19-page descendant set drift")

    ledger = load_json(repo_file(coverage["live_ledger_binding"]))
    if len(ledger["sources"]) != 55 or len(ledger["capabilities"]) != 161:
        raise RecursiveCoverageError("live ledger binding differs from 55/161")
    uri_sources: dict[str, list[str]] = {}
    for source in ledger["sources"]:
        uri_sources.setdefault(source.get("uri", ""), []).append(source["id"])
    if added & set(uri_sources):
        raise RecursiveCoverageError("an added descendant is already a live source")

    descendants = coverage["new_descendants"]
    descendant_urls = [item["url"] for item in descendants]
    if descendant_urls != sorted(descendant_urls) or set(descendant_urls) != added:
        raise RecursiveCoverageError("new-descendant records are incomplete or unsorted")
    category_sets = {
        category: {
            item["url"] for item in descendants if item["category"] == category
        }
        for category in (
            "semantic_omission",
            "external_workflow_dependency",
            "navigation_duplicate_reference",
        )
    }
    if category_sets["semantic_omission"] != EXPECTED_SEMANTIC:
        raise RecursiveCoverageError("exact 8-page semantic set drift")
    if category_sets["external_workflow_dependency"] != EXPECTED_EXTERNAL:
        raise RecursiveCoverageError("exact 9-page external set drift")
    if category_sets["navigation_duplicate_reference"] != EXPECTED_NAVIGATION:
        raise RecursiveCoverageError("exact 2-page navigation set drift")
    target_index = {url: index for index, url in enumerate(targets)}
    for item in descendants:
        url_index = target_index[item["url"]]
        referrer_index = target_index[item["first_referrer"]]
        if url_index not in adjacency[referrer_index]:
            raise RecursiveCoverageError(f"referrer edge is absent: {item['url']}")
        if depths[url_index] != item["depth"] or depths[referrer_index] >= item["depth"]:
            raise RecursiveCoverageError(f"referrer/depth proof drift: {item['url']}")
        if item["live_source_ids"] != uri_sources.get(item["url"], []):
            raise RecursiveCoverageError(f"live source linkage drift: {item['url']}")
        if item["semantic_proof_from_crawl_reachability"] is not False:
            raise RecursiveCoverageError("crawl reachability is not semantic proof")

    agent_binding = coverage["agent_smartcity_binding"]
    agent_candidate = load_json(repo_file(agent_binding))
    agent_urls = {
        source["uri"]
        for source in agent_candidate["sources"]
        if source["uri"].startswith(BASE_URL)
    }
    if len(agent_urls) != 40 or not agent_urls.issubset(targets):
        raise RecursiveCoverageError(
            "agent-smartcity docs sources are not 40 recursive-graph members"
        )
    if set(agent_binding["corrected_urls"]) != EXPECTED_CORRECTED_SMARTCITY:
        raise RecursiveCoverageError("corrected Smart City URL set drift")
    if set(agent_binding["stale_404_urls"]) != EXPECTED_STALE_SMARTCITY:
        raise RecursiveCoverageError("stale Smart City URL set drift")
    if not EXPECTED_CORRECTED_SMARTCITY.issubset(agent_urls):
        raise RecursiveCoverageError("corrected Smart City sources are absent")
    if EXPECTED_STALE_SMARTCITY & agent_urls:
        raise RecursiveCoverageError("stale Smart City 404 sources returned")

    return {
        "network_requests": 0,
        "recursive_targets_including_index": 172,
        "recursive_targets_excluding_index": 171,
        "direct_index_targets": 152,
        "added_descendants": 19,
        "added_categories": {
            "semantic_omission": 8,
            "external_workflow_dependency": 9,
            "navigation_duplicate_reference": 2,
        },
        "depth_counts": dict(sorted(depth_counts.items())),
        "directed_edges": len(edges),
        "fixed_point": True,
        "agent_smartcity_recursive_sources": len(agent_urls),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        report = validate()
    except RecursiveCoverageError as exc:
        print(f"recursive coverage: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "recursive coverage: PASS: 172 URLs including index, "
            "171 docs, 19 added descendants, fixed point proven offline"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
