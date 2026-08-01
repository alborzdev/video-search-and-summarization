#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate the offline VSS 3.2.1 documentation-drift metadata observation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
OBSERVATION = LANE / "observation.json"
MAX_JSON_BYTES = 4 * 1024 * 1024
SOURCE_BINDINGS = {
    "deploy/docker/thor-local/parity/source-lock/source-lock.json": (
        "fbf21f64f13dc22328c4a01c79e427042c3112885073dc32bb0ebd6700f0fd07"
    ),
    "deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/recursive-targets.json": (
        "30e42ca2d085aa6e4b3ea99e537f9e2897864da1463979bb4768d06b8027a3aa"
    ),
    "deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/crawl-graph.json": (
        "7f8fff1f1a540afe8663e461b687eeb24ba8b229f2d867d4bcf18ff83a157f99"
    ),
}
URL_SET_SHA256 = "74a1d6ae1f520049202e47dce69fa56d10c28c48aa3aa24a3a2c4214dad4b208"
RECORD_SET_SHA256 = "b37a617f351dbd32673983eee2299daed0db1f04b387db5d89ec2a89511d79eb"
EDGE_SET_SHA256 = "58759d1dc9b060c90518aa2928190381d2838558d170746e9af783a0dbc35a55"


class ObservationError(RuntimeError):
    """The metadata observation or its immutable baseline failed closed."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObservationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ObservationError(f"non-finite JSON number: {token}")


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ObservationError(f"not a regular non-symlink JSON file: {path}")
        if metadata.st_size > MAX_JSON_BYTES:
            raise ObservationError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ObservationError(f"opened JSON is not a regular file: {path}")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_JSON_BYTES:
            raise ObservationError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except ObservationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError(f"invalid strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ObservationError(f"JSON root must be an object: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ObservationError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    unresolved = root / candidate
    metadata = unresolved.lstat()
    if unresolved.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ObservationError(f"repository path is not a regular file: {relative}")
    resolved = unresolved.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ObservationError(f"repository path escaped: {relative}") from exc
    return resolved


def _validate_document(document: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _strict_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ObservationError(f"{label} schema rejection: {errors[0].message}")


def _verify_graph(graph: dict[str, Any], targets: list[str]) -> None:
    scans = graph.get("scans")
    if not isinstance(scans, list) or [row.get("url_index") for row in scans] != list(
        range(172)
    ):
        raise ObservationError("crawl graph does not cover URL indexes 0 through 171")
    edges: list[list[str]] = []
    self_edges = 0
    for scan in scans:
        source = scan["url_index"]
        outbound = scan.get("outbound_target_indexes")
        if (
            not isinstance(outbound, list)
            or outbound != sorted(outbound)
            or len(outbound) != len(set(outbound))
            or any(not isinstance(index, int) or index < 0 or index >= 172 for index in outbound)
        ):
            raise ObservationError(f"invalid crawl adjacency for URL index {source}")
        for target in outbound:
            edges.append([targets[source], targets[target]])
            self_edges += int(source == target)
    edges.sort()
    summary = graph.get("graph_summary", {})
    if (
        len(edges) != 26449
        or summary.get("canonical_directed_edge_count") != 26449
        or self_edges != 172
        or summary.get("self_edge_count") != 172
        or _canonical_sha256(edges) != EDGE_SET_SHA256
        or summary.get("canonical_url_pair_edge_set_sha256") != EDGE_SET_SHA256
        or summary.get("all_outbound_targets_in_reachable_set") is not True
    ):
        raise ObservationError("immutable 26,449-edge topology drift")


def _verify_baseline(document: dict[str, Any]) -> dict[str, str]:
    observed_hashes: dict[str, str] = {}
    loaded: dict[str, dict[str, Any]] = {}
    for relative, expected in SOURCE_BINDINGS.items():
        path = _repo_file(relative)
        digest = _sha256_file(path)
        if digest != expected:
            raise ObservationError(f"immutable baseline hash drift: {relative}")
        observed_hashes[relative] = digest
        loaded[relative] = _strict_json(path)

    source_lock = loaded[next(iter(SOURCE_BINDINGS))]
    target_path = list(SOURCE_BINDINGS)[1]
    graph_path = list(SOURCE_BINDINGS)[2]
    targets_doc = loaded[target_path]
    graph = loaded[graph_path]
    targets = targets_doc.get("targets")
    if (
        not isinstance(targets, list)
        or targets != sorted(targets)
        or len(targets) != 172
        or len(set(targets)) != 172
        or _canonical_sha256(targets) != URL_SET_SHA256
        or targets_doc.get("canonical_reachable_set_sha256") != URL_SET_SHA256
        or targets_doc.get("reachable_count_including_start") != 172
    ):
        raise ObservationError("immutable 172-URL denominator drift")

    records = source_lock.get("records")
    if not isinstance(records, list) or len(records) != 172:
        raise ObservationError("immutable source lock does not contain 172 records")
    if [row.get("url") for row in records] != targets:
        raise ObservationError("source-lock URLs differ from the recursive target set")
    if any(
        row.get("outcome") != "success"
        or row.get("http_status") != 200
        or not isinstance(row.get("byte_count"), int)
        or row["byte_count"] <= 0
        or not isinstance(row.get("sha256"), str)
        or len(row["sha256"]) != 64
        for row in records
    ):
        raise ObservationError("immutable source-lock success records drift")
    summary = source_lock.get("summary", {})
    if (
        source_lock.get("captured_on") != "2026-07-31"
        or source_lock.get("product_version") != "3.2.1"
        or summary.get("url_count") != 172
        or summary.get("success_count") != 172
        or summary.get("failure_count") != 0
        or sum(row["byte_count"] for row in records) != 13351947
        or summary.get("total_byte_count") != 13351947
        or _canonical_sha256(sorted(records, key=lambda row: row["url"]))
        != RECORD_SET_SHA256
        or summary.get("aggregate_sha256") != RECORD_SET_SHA256
    ):
        raise ObservationError("immutable source-lock aggregate drift")
    if graph.get("target_binding") != {
        "path": target_path,
        "sha256": SOURCE_BINDINGS[target_path],
    }:
        raise ObservationError("crawl graph target binding drift")
    _verify_graph(graph, targets)

    baseline = document["immutable_baseline"]
    if baseline["total_byte_count"] != summary["total_byte_count"]:
        raise ObservationError("observation baseline byte total is not source-locked")
    return observed_hashes


def validate(path: Path = OBSERVATION) -> dict[str, Any]:
    if path.resolve(strict=True) != OBSERVATION.resolve(strict=True):
        raise ObservationError("only the lane-owned observation may be validated")
    document = _strict_json(path)
    _validate_document(document, LANE / "observation.schema.json", "observation")
    source_hashes = _verify_baseline(document)
    comparison = document["reviewed_drift_observation"]
    if (
        comparison["raw_sha256_changed_count"]
        + comparison["raw_sha256_unchanged_count"]
        != 172
        or comparison["per_page_byte_count_match_count"]
        + comparison["per_page_byte_count_mismatch_count"]
        != 172
    ):
        raise ObservationError("reviewed aggregate comparison denominator drift")
    result = {
        "schema_version": 1,
        "package_id": document["package_id"],
        "mode": "offline_metadata_validation_non_advancing",
        "source_hashes": source_hashes,
        "verified_baseline": {
            "captured_on": "2026-07-31",
            "url_count": 172,
            "total_byte_count": 13351947,
            "canonical_url_set_sha256": URL_SET_SHA256,
            "canonical_directed_edge_count": 26449,
            "canonical_url_pair_edge_set_sha256": EDGE_SET_SHA256,
        },
        "recorded_observation": {
            "observed_on": "2026-08-01",
            "raw_sha256_changed_count": 172,
            "per_page_byte_count_match_count": 172,
            "canonical_url_set_identical": True,
            "directed_edge_topology_identical": True,
            "semantic_equality": "unproven",
        },
        "evidence_boundary": {
            "august_per_page_sha256_values_available": False,
            "exact_august_relock_materialized": False,
            "external_observation_reproduced_by_validator": False,
            "validator_scope": "checked_in_july_baseline_and_strict_aggregate_metadata_only",
        },
        "confinement": {
            "network_calls": 0,
            "downloads": 0,
            "docker_calls": 0,
            "runtime_calls": 0,
            "filesystem_writes": 0,
            "canonical_files_modified": 0,
        },
        "promotion": {
            "runtime_evidence": [],
            "feature_evidence": [],
            "official_capability_effect": "none_metadata_only",
            "feature_or_runtime_promotion": False,
        },
        "result": document["result"],
    }
    _validate_document(result, LANE / "result.schema.json", "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--observation", type=Path, default=OBSERVATION)
    args = parser.parse_args()
    try:
        result = validate(args.observation)
    except (ObservationError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print("PASS: VSS 3.2.1 documentation drift metadata observation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
