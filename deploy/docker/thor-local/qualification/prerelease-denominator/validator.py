#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate the exact prerelease commit/path denominator without Git or network."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
DENOMINATOR_PATH = HERE / "denominator.json"
DENOMINATOR_SCHEMA_PATH = HERE / "denominator.schema.json"
RULES_PATH = HERE / "classification-rules.json"
RULES_SCHEMA_PATH = HERE / "classification-rules.schema.json"
PATH_STATUS_PATH = HERE / "path-status.jsonl.gz"
PATH_STATUS_SCHEMA_PATH = HERE / "path-status-record.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
HEAD_DELTA_PATH = HERE / "head-delta.json"
HEAD_DELTA_SCHEMA_PATH = HERE / "head-delta.schema.json"
WATCHLIST_MANIFEST_PATH = HERE.parent / "prerelease-watchlist" / "manifest.json"

EXPECTED_DENOMINATOR_CANONICAL_SHA256 = (
    "64e4c4cdcb802201652c21db815f8d1f8594dcb840a795339cb4e132aba96224"
)
EXPECTED_RULES_CANONICAL_SHA256 = (
    "775fcf800abda55d793d2e74df792f68337fffde927501124553cbf155ba402f"
)
EXPECTED_HEAD_DELTA_CANONICAL_SHA256 = (
    "dc7dc44d7e7a83a4aed2c53ed707cb90b48f5972775b2140d9b8796ee731a9d9"
)
EXPECTED_PATH_STATUS_GZIP_SHA256 = (
    "3e4010f2264396a7b86f4932b3126463bab5b66c1966d86a6f44107d275b4118"
)
EXPECTED_PATH_STATUS_JSONL_SHA256 = (
    "137329738d0a2d2bcd7dc9c30ae9c6c21bfb36f38d81126491ba5bc8bbe8685e"
)
EXPECTED_DEVELOP_SEQUENCE_SHA256 = (
    "609ea564effe9c1bbebdd9e538bf546d843990d499757fc54826af77efabda0a"
)
EXPECTED_MAIN_SEQUENCE_SHA256 = (
    "601be158b38bcb039f3fa4e09487b4541fba9c576f3d257963724448636bd889"
)
EXPECTED_MAIN_EXCEPTIONS = (
    "dc3746db57a008a0be203eaa0c130c6cb94a2661",
    "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
)


class DenominatorError(RuntimeError):
    """The prerelease denominator is malformed, incomplete, or drifted."""


def _load(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DenominatorError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DenominatorError(f"cannot load JSON {path}: {exc}") from exc


def _load_line(raw: bytes, line_number: int) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DenominatorError(
                    f"duplicate JSON key on path-status line {line_number}: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DenominatorError(
            f"invalid path-status JSON on line {line_number}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise DenominatorError(f"path-status line {line_number} is not an object")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _load(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise DenominatorError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise DenominatorError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def _compile_rules(rules: dict[str, Any]) -> list[dict[str, Any]]:
    compiled = []
    seen_rule_ids: set[str] = set()
    all_ids = rules["candidate_family_ids"] + rules["watchlist_category_ids"]
    for rule in rules["rules"]:
        if rule["rule_id"] in seen_rule_ids:
            raise DenominatorError(f"duplicate classification rule: {rule['rule_id']}")
        seen_rule_ids.add(rule["rule_id"])
        if rule["classification_id"] not in all_ids:
            raise DenominatorError(
                f"unknown classification target: {rule['classification_id']}"
            )
        try:
            compiled.append(
                {
                    **rule,
                    "path_patterns": [
                        re.compile(pattern, re.IGNORECASE)
                        for pattern in rule["path_regexes"]
                    ],
                    "subject_patterns": [
                        re.compile(pattern, re.IGNORECASE)
                        for pattern in rule["subject_regexes"]
                    ],
                    "deleted_path_patterns": [
                        re.compile(pattern, re.IGNORECASE)
                        for pattern in rule["deleted_path_regexes"]
                    ],
                }
            )
        except re.error as exc:
            raise DenominatorError(
                f"invalid regex in classification rule {rule['rule_id']}: {exc}"
            ) from exc
    if {rule["classification_id"] for rule in rules["rules"]} != set(all_ids):
        raise DenominatorError("classification rules do not cover the exact universe")
    return compiled


def _classify(
    subject: str,
    changes: list[dict[str, str]],
    compiled_rules: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    classifications: list[str] = []
    matched_rule_ids: list[str] = []
    for rule in compiled_rules:
        matches = any(
            pattern.search(change["path"])
            for pattern in rule["path_patterns"]
            for change in changes
        ) or any(pattern.search(subject) for pattern in rule["subject_patterns"])
        matches = matches or any(
            change["status"] == "D" and pattern.search(change["path"])
            for pattern in rule["deleted_path_patterns"]
            for change in changes
        )
        if matches:
            matched_rule_ids.append(rule["rule_id"])
            if rule["classification_id"] not in classifications:
                classifications.append(rule["classification_id"])
    return classifications, matched_rule_ids


def _safe_path(value: str, line_number: int) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise DenominatorError(
            f"unsafe path on path-status line {line_number}: {value!r}"
        )


def validate_denominator() -> dict[str, Any]:
    denominator = _load(DENOMINATOR_PATH)
    rules = _load(RULES_PATH)
    head_delta = _load(HEAD_DELTA_PATH)
    _validate_schema(denominator, DENOMINATOR_SCHEMA_PATH, "denominator")
    _validate_schema(rules, RULES_SCHEMA_PATH, "classification rules")
    _validate_schema(head_delta, HEAD_DELTA_SCHEMA_PATH, "head delta")

    if _sha256(_canonical_bytes(denominator)) != EXPECTED_DENOMINATOR_CANONICAL_SHA256:
        raise DenominatorError("canonical denominator lock drifted")
    if _sha256(_canonical_bytes(rules)) != EXPECTED_RULES_CANONICAL_SHA256:
        raise DenominatorError("canonical classification-rules lock drifted")
    if _sha256(_canonical_bytes(head_delta)) != EXPECTED_HEAD_DELTA_CANONICAL_SHA256:
        raise DenominatorError("canonical head-delta lock drifted")
    if (
        denominator["classification_contract"]["rules_canonical_sha256"]
        != EXPECTED_RULES_CANONICAL_SHA256
    ):
        raise DenominatorError(
            "denominator does not bind the exact classification rules"
        )

    watchlist = _load(WATCHLIST_MANIFEST_PATH)
    watchlist_family_ids = [family["family_id"] for family in watchlist["families"]]
    if watchlist_family_ids != rules["candidate_family_ids"]:
        raise DenominatorError(
            "candidate families drifted from the 14-family watchlist"
        )
    compiled_rules = _compile_rules(rules)

    compressed = PATH_STATUS_PATH.read_bytes()
    if len(compressed) != denominator["path_status_sidecar"]["compressed_bytes"]:
        raise DenominatorError("compressed path-status byte count drifted")
    if _sha256(compressed) != EXPECTED_PATH_STATUS_GZIP_SHA256:
        raise DenominatorError("compressed path-status digest drifted")
    if denominator["digests"]["path_status_gzip_sha256"] != _sha256(compressed):
        raise DenominatorError("denominator gzip digest does not match sidecar")
    if len(compressed) < 10 or compressed[:2] != b"\x1f\x8b":
        raise DenominatorError("path-status sidecar is not gzip")
    if struct.unpack("<I", compressed[4:8])[0] != 0:
        raise DenominatorError("path-status gzip mtime must be zero")
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise DenominatorError(f"cannot decompress path-status sidecar: {exc}") from exc
    if len(raw) != denominator["path_status_sidecar"]["uncompressed_bytes"]:
        raise DenominatorError("uncompressed path-status byte count drifted")
    if _sha256(raw) != EXPECTED_PATH_STATUS_JSONL_SHA256:
        raise DenominatorError("uncompressed path-status digest drifted")
    if denominator["digests"]["path_status_jsonl_sha256"] != _sha256(raw):
        raise DenominatorError("denominator JSONL digest does not match sidecar")
    if raw and not raw.endswith(b"\n"):
        raise DenominatorError("path-status JSONL lacks a final newline")

    develop = denominator["develop_side_commits"]
    main_exceptions = denominator["main_only_exceptions"]
    if tuple(item["sha"] for item in main_exceptions) != EXPECTED_MAIN_EXCEPTIONS:
        raise DenominatorError("the two main-only divergence exceptions drifted")
    develop_sequence = ("\n".join(item["sha"] for item in develop) + "\n").encode()
    main_sequence = ("\n".join(item["sha"] for item in main_exceptions) + "\n").encode()
    if _sha256(develop_sequence) != EXPECTED_DEVELOP_SEQUENCE_SHA256:
        raise DenominatorError("develop commit sequence digest drifted")
    if _sha256(main_sequence) != EXPECTED_MAIN_SEQUENCE_SHA256:
        raise DenominatorError("main exception sequence digest drifted")
    if develop[-1]["sha"] != denominator["upstream_locks"]["prerelease_sha"]:
        raise DenominatorError("develop sequence does not terminate at the locked tip")
    if main_exceptions[-1]["sha"] != denominator["upstream_locks"]["stable_main_sha"]:
        raise DenominatorError(
            "main exception sequence does not terminate at stable main"
        )

    latest = develop[-1]
    delta_commit = head_delta["commits"][0]
    if (
        head_delta["develop_head_sha"] != latest["sha"]
        or head_delta["base_nightly_sha"] != delta_commit["parent"]
        or delta_commit["sha"] != latest["sha"]
        or delta_commit["tree"] != latest["tree"]
        or delta_commit["parent"] not in latest["parents"]
        or delta_commit["subject"] != latest["subject"]
        or delta_commit["path_count"] != latest["change_count"]
        or delta_commit["path_status_sha256"] != latest["path_status_sha256"]
    ):
        raise DenominatorError("head delta is not bound to the latest develop commit")

    ordered_commits = develop + main_exceptions
    commit_by_sha = {item["sha"]: item for item in ordered_commits}
    if len(commit_by_sha) != len(ordered_commits):
        raise DenominatorError("duplicate commit SHA in denominator")
    expected_ranges = {item["sha"]: "develop_side" for item in develop} | {
        item["sha"]: "main_only_exception" for item in main_exceptions
    }
    expected_positions = {
        item["sha"]: index for index, item in enumerate(ordered_commits)
    }
    changes_by_commit: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_changes_by_commit: dict[str, set[tuple[str, str]]] = defaultdict(set)
    raw_by_commit: dict[str, bytearray] = defaultdict(bytearray)
    status_counts: Counter[str] = Counter()
    unique_paths: set[str] = set()
    last_position = -1
    sidecar_schema = _load(PATH_STATUS_SCHEMA_PATH)
    try:
        Draft202012Validator.check_schema(sidecar_schema)
    except SchemaError as exc:
        raise DenominatorError("invalid path-status record schema") from exc
    lines = raw.splitlines(keepends=True)
    for line_number, line in enumerate(lines, start=1):
        if not line.endswith(b"\n"):
            raise DenominatorError(f"path-status line {line_number} lacks newline")
        record = _load_line(line, line_number)
        if (
            set(record) != {"commit", "path", "range", "status"}
            or not all(isinstance(value, str) for value in record.values())
            or not re.fullmatch(r"[0-9a-f]{40}", record["commit"])
            or not record["path"]
            or record["range"] not in {"develop_side", "main_only_exception"}
            or record["status"] not in {"A", "D", "M", "T"}
        ):
            raise DenominatorError(
                f"path-status schema validation failed on line {line_number}"
            )
        if line != _canonical_bytes(record) + b"\n":
            raise DenominatorError(f"non-canonical path-status line {line_number}")
        sha = record["commit"]
        if sha not in commit_by_sha:
            raise DenominatorError(
                f"unknown commit on path-status line {line_number}: {sha}"
            )
        position = expected_positions[sha]
        if position < last_position:
            raise DenominatorError("path-status records are not in locked commit order")
        last_position = position
        if record["range"] != expected_ranges[sha]:
            raise DenominatorError(f"wrong range for path-status commit {sha}")
        _safe_path(record["path"], line_number)
        change_key = (record["path"], record["status"])
        if change_key in seen_changes_by_commit[sha]:
            raise DenominatorError(f"duplicate path/status record in commit {sha}")
        seen_changes_by_commit[sha].add(change_key)
        change = {"path": record["path"], "status": record["status"]}
        changes_by_commit[sha].append(change)
        raw_by_commit[sha].extend(line)
        status_counts[record["status"]] += 1
        unique_paths.add(record["path"])

    if delta_commit["paths"] != [
        change["path"] for change in changes_by_commit[latest["sha"]]
    ]:
        raise DenominatorError("head-delta paths drifted from the exact sidecar")

    classification_counts: Counter[str] = Counter()
    develop_change_count = 0
    for expected_range, commits in (
        ("develop_side", develop),
        ("main_only_exception", main_exceptions),
    ):
        for expected_ordinal, commit in enumerate(commits, start=1):
            if commit["ordinal"] != expected_ordinal:
                raise DenominatorError(
                    f"non-contiguous {expected_range} ordinal at {commit['sha']}"
                )
            changes = changes_by_commit[commit["sha"]]
            if len(changes) != commit["change_count"]:
                raise DenominatorError(f"change count drifted for {commit['sha']}")
            if (
                _sha256(bytes(raw_by_commit[commit["sha"]]))
                != commit["path_status_sha256"]
            ):
                raise DenominatorError(
                    f"path-status digest drifted for {commit['sha']}"
                )
            classifications, rule_ids = _classify(
                commit["subject"], changes, compiled_rules
            )
            if not classifications:
                raise DenominatorError(f"unclassified commit: {commit['sha']}")
            if classifications != commit["classifications"]:
                raise DenominatorError(f"classification drifted for {commit['sha']}")
            if rule_ids != commit["classification_rule_ids"]:
                raise DenominatorError(
                    f"classification rule trace drifted for {commit['sha']}"
                )
            classification_counts.update(classifications)
            if expected_range == "develop_side":
                develop_change_count += len(changes)

    counts = denominator["counts"]
    if len(lines) != counts["all_path_status_records"]:
        raise DenominatorError("total path-status record count drifted")
    if develop_change_count != counts["develop_side_path_status_records"]:
        raise DenominatorError("develop path-status record count drifted")
    if len(lines) - develop_change_count != counts["main_only_path_status_records"]:
        raise DenominatorError("main exception path-status record count drifted")
    if len(unique_paths) != counts["unique_paths"]:
        raise DenominatorError("unique path count drifted")
    if dict(sorted(status_counts.items())) != counts["status_counts"]:
        raise DenominatorError("path status totals drifted")
    all_ids = rules["candidate_family_ids"] + rules["watchlist_category_ids"]
    actual_classification_counts = {
        identifier: classification_counts.get(identifier, 0) for identifier in all_ids
    }
    if actual_classification_counts != counts["classification_counts"]:
        raise DenominatorError("classification totals drifted")

    result = {
        "schema_version": 1,
        "status": "static_denominator_valid",
        "scope": denominator["scope"],
        "evidence_ceiling": denominator["evidence_ceiling"],
        "counts": counts,
        "digests": denominator["digests"],
        "all_develop_commits_classified": True,
        "main_divergence_exceptions_preserved": True,
        "runtime_parity_claimed": False,
        "runtime_evidence": [],
        "official_capability_promotions": 0,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit the strict JSON result"
    )
    args = parser.parse_args()
    try:
        result = validate_denominator()
    except DenominatorError as exc:
        print(f"FAIL: {exc}")
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        counts = result["counts"]
        print(
            "PASS: exact static prerelease denominator; "
            f"{counts['develop_side_commits']} develop commits, "
            f"{counts['develop_side_path_status_records']} develop path/status records, "
            f"{counts['main_only_exceptions']} main-only exceptions; "
            "zero runtime parity claims or promotions"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
