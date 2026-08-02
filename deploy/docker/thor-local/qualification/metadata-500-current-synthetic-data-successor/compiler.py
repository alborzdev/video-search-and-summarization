#!/usr/bin/env python3
"""Compile the checked future Synthetic Data executor-ready oracle registry."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
OUTPUT = PACKAGE / "post-state-capability-oracles.json"
MAX_JSON_BYTES = 8_000_000

SOURCE_ORACLES = (
    "deploy/docker/thor-local/qualification/metadata-500-current-cancellation-search-successor/post-state-capability-oracles.json",
    "355679322116451972cb2366a61bfba23a72762863796aea84c93a7bb412db14",
)
CURRENT_ORACLES = (
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "d782a8cc4456018d45fcb824f30f08e7d9195d01d97639e44b7524b2ba32d6c0",
)
ORACLE_SCHEMA = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.schema.json",
    "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
)
RUNTIME_CONTRACT = (
    "deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/contract.json",
    "a985966163e9bc726abcadf4564b9274657d426ebcd6629e2c8387b79c3ab99c",
)
RUNTIME_CONTRACT_SCHEMA = (
    "deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/contract.schema.json",
    "47c288268b5d6c5e703d8493c5c9e81453db5fe7b8846cf8e3c834c898252e52",
)
FIXTURE_SCHEMA = "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/fixture-manifest.schema.json"
EXECUTOR = "deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/executor.py"
EXPECTED_OUTPUT_SHA256 = (
    "c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6"
)
FINAL_GAP = (
    "No known gap: the current target-bound offline runtime receipt covers the "
    "exact positive semantics, adjacent-negative behavior, determinism, and cleanup "
    "contract without the Warehouse sample bundle."
)

TARGETS: tuple[tuple[str, str, str, str], ...] = (
    (
        "manifest-entry.synthetic-data-tools.00-semantic-label-helpers",
        "semantic_label_helpers",
        "fixtures/00-semantic-label-helpers.json",
        "0a079066c4ad506e8589206c8b51e21a0ecacdecb16fc9785c52033b0d279d27",
    ),
    (
        "manifest-entry.synthetic-data-tools.01-dataset-checks",
        "dataset_checks",
        "fixtures/01-dataset-checks.json",
        "0cc773dd0ec64aa4a45c379b298dc7580eddf89ab7702172fe101807d52c1ff2",
    ),
    (
        "manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion",
        "rgb_depth_video_conversion",
        "fixtures/02-rgb-depth-video-conversion.json",
        "171aef78bdd4738fa78f7114b27b9ca9cd0ec528ed52ae2f8be051c5b14dfd25",
    ),
    (
        "manifest-entry.synthetic-data-tools.03-ground-truth-conversion",
        "ground_truth_conversion",
        "fixtures/03-ground-truth-conversion.json",
        "0a1f7d857d582aa47cd54aa1a956175a67976719443c8a9ed946962d8ef77939",
    ),
)


class SuccessorError(RuntimeError):
    """A source lock, schema, or exact-derivation invariant failed."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SuccessorError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise SuccessorError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise SuccessorError(f"repository input contains symlink: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise SuccessorError(f"repository input is not regular: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SuccessorError(f"repository input escapes root: {relative}") from exc
    return current


def strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise SuccessorError(f"oversized JSON input: {label}")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise SuccessorError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                SuccessorError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except SuccessorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorError(f"invalid JSON in {label}: {exc}") from exc


def load_locked(source: tuple[str, str]) -> Any:
    relative, expected = source
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise SuccessorError(f"unfinalized source lock: {relative}")
    payload = repo_file(relative).read_bytes()
    if sha256(payload) != expected:
        raise SuccessorError(f"raw source digest drift: {relative}")
    return strict_json(payload, relative)


def fixture_relative(relative: str) -> str:
    return str((PACKAGE / relative).relative_to(REPO_ROOT))


def load_fixtures(
    contract: dict[str, Any], fixture_schema: dict[str, Any]
) -> dict[str, tuple[str, str]]:
    contract_rows = {row["capability_id"]: row for row in contract["capabilities"]}
    fixtures: dict[str, tuple[str, str]] = {}
    for capability_id, adapter, relative, expected_sha in TARGETS:
        path = repo_file(fixture_relative(relative))
        payload = path.read_bytes()
        if sha256(payload) != expected_sha:
            raise SuccessorError(f"raw fixture manifest digest drift: {relative}")
        fixture = strict_json(payload, relative)
        errors = sorted(
            Draft202012Validator(fixture_schema).iter_errors(fixture),
            key=lambda error: tuple(map(str, error.absolute_path)),
        )
        if errors:
            raise SuccessorError(
                f"fixture manifest schema failure ({relative}): {errors[0].message}"
            )
        runtime = contract_rows.get(capability_id)
        if runtime is None:
            raise SuccessorError(f"runtime contract lacks capability: {capability_id}")
        expected_identity = {
            "adapter": adapter,
            "capability_id": capability_id,
            "fixture_id": f"fixture.{capability_id}",
            "generated_input_sha256": runtime["generated_input_sha256"],
            "generator": EXECUTOR,
            "origin": "executor-generated tiny custom data",
            "runtime_contract": RUNTIME_CONTRACT[0],
            "schema_version": 1,
            "warehouse_sample_bundle": "excluded",
        }
        if fixture != expected_identity:
            raise SuccessorError(f"fixture manifest identity drift: {relative}")
        if runtime.get("fixture_manifest") != {
            "path": fixture_relative(relative),
            "sha256": expected_sha,
        }:
            raise SuccessorError(f"runtime fixture-manifest binding drift: {relative}")
        fixtures[capability_id] = (fixture_relative(relative), expected_sha)
    return fixtures


def derive() -> tuple[dict[str, Any], dict[str, Any], dict[str, tuple[str, str]]]:
    selected = load_locked(SOURCE_ORACLES)
    current = load_locked(CURRENT_ORACLES)
    schema = load_locked(ORACLE_SCHEMA)
    contract = load_locked(RUNTIME_CONTRACT)
    contract_schema = load_locked(RUNTIME_CONTRACT_SCHEMA)
    fixture_schema = strict_json(repo_file(FIXTURE_SCHEMA).read_bytes(), FIXTURE_SCHEMA)
    contract_errors = sorted(
        Draft202012Validator(contract_schema).iter_errors(contract),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if contract_errors:
        raise SuccessorError(
            f"runtime contract schema failure: {contract_errors[0].message}"
        )
    fixtures = load_fixtures(contract, fixture_schema)
    if len(selected["oracles"]) != 500 or len(current["oracles"]) != 289:
        raise SuccessorError("selected/current oracle denominator drift")
    selected_suffix = copy.deepcopy(selected["oracles"][289:])
    baseline = copy.deepcopy(selected)
    baseline["policy"] = copy.deepcopy(current["policy"])
    baseline["oracles"][:289] = copy.deepcopy(current["oracles"])
    if baseline["oracles"][289:] != selected_suffix:
        raise SuccessorError("selected 211-row candidate suffix changed during rebase")
    selected_ids = [row["capability_id"] for row in selected["oracles"][:289]]
    current_ids = [row["capability_id"] for row in current["oracles"]]
    if selected_ids != current_ids or len(set(current_ids)) != 289:
        raise SuccessorError(
            "current 289-row identity/order differs from selected prefix"
        )
    output = copy.deepcopy(baseline)
    target_ids = {row[0] for row in TARGETS}
    found: set[str] = set()
    for row in output["oracles"]:
        capability_id = row["capability_id"]
        if capability_id not in target_ids:
            continue
        found.add(capability_id)
        fixture_path, fixture_sha = fixtures[capability_id]
        row["ledger_binding"]["runtime_state"] = "passed_current"
        row["ledger_binding"]["gap"] = FINAL_GAP
        row["fixture"]["materialization"] = {
            "generator": EXECUTOR,
            "path": fixture_path,
            "sha256": fixture_sha,
        }
        row["execution_bounds"]["executor"] = EXECUTOR
        row["execution_bounds"]["collectors"] = [EXECUTOR]
        row["cleanup"]["executor"] = EXECUTOR
        row["cleanup"]["postcondition_collectors"] = [EXECUTOR]
        row["acceptance_readiness"] = {
            "blockers": [],
            "classification": "executor_ready",
        }
    if found != target_ids:
        raise SuccessorError("selected Metadata-500 source lacks exact target set")
    validate(baseline, output, schema, fixtures)
    return baseline, output, fixtures


def validate(
    source: dict[str, Any],
    output: dict[str, Any],
    schema: dict[str, Any],
    fixtures: dict[str, tuple[str, str]],
) -> dict[str, int]:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(output),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        path = "/".join(map(str, errors[0].absolute_path))
        raise SuccessorError(f"oracle schema failure at {path}: {errors[0].message}")
    before = {row["capability_id"]: row for row in source["oracles"]}
    after = {row["capability_id"]: row for row in output["oracles"]}
    if (
        len(before) != 500
        or list(before) != list(after)
        or len(set(before)) != 500
        or output.get("policy") != source.get("policy")
    ):
        raise SuccessorError("Metadata-500 denominator, order, or policy drift")
    target_ids = {row[0] for row in TARGETS}
    executor_ready = 0
    passed_bindings = 0
    for capability_id, old in before.items():
        new = after[capability_id]
        if capability_id not in target_ids:
            if canonical_bytes(new) != canonical_bytes(old):
                raise SuccessorError(f"non-target oracle changed: {capability_id}")
            continue
        expected = copy.deepcopy(old)
        fixture_path, fixture_sha = fixtures[capability_id]
        expected["ledger_binding"]["runtime_state"] = "passed_current"
        expected["ledger_binding"]["gap"] = FINAL_GAP
        expected["fixture"]["materialization"] = {
            "generator": EXECUTOR,
            "path": fixture_path,
            "sha256": fixture_sha,
        }
        expected["execution_bounds"]["executor"] = EXECUTOR
        expected["execution_bounds"]["collectors"] = [EXECUTOR]
        expected["cleanup"]["executor"] = EXECUTOR
        expected["cleanup"]["postcondition_collectors"] = [EXECUTOR]
        expected["acceptance_readiness"] = {
            "blockers": [],
            "classification": "executor_ready",
        }
        if canonical_bytes(new) != canonical_bytes(expected):
            raise SuccessorError(
                f"target oracle has an undeclared change: {capability_id}"
            )
        if new["current_state"] != "open_unexecuted" or new["evidence"] != []:
            raise SuccessorError(f"future oracle invented evidence: {capability_id}")
        fixture_file = repo_file(fixture_path)
        if sha256(fixture_file.read_bytes()) != fixture_sha:
            raise SuccessorError(f"fixture materialization drift: {capability_id}")
        for path in (
            new["fixture"]["materialization"]["generator"],
            new["execution_bounds"]["executor"],
            *new["execution_bounds"]["collectors"],
            new["cleanup"]["executor"],
            *new["cleanup"]["postcondition_collectors"],
        ):
            repo_file(path)
        executor_ready += (
            new["acceptance_readiness"]["classification"] == "executor_ready"
        )
        passed_bindings += new["ledger_binding"]["runtime_state"] == "passed_current"
    if executor_ready != 4 or passed_bindings != 4:
        raise SuccessorError("exact four-row future readiness invariant failed")
    return {
        "oracles": len(after),
        "preserved_oracles": len(after) - len(target_ids),
        "synthetic_executor_ready": executor_ready,
        "synthetic_passed_current_bindings": passed_bindings,
        "runtime_evidence": sum(len(row["evidence"]) for row in after.values()),
    }


def check_output(derived: bytes) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", EXPECTED_OUTPUT_SHA256) is None:
        raise SuccessorError("unfinalized checked output digest")
    payload = repo_file(str(OUTPUT.relative_to(REPO_ROOT))).read_bytes()
    if payload != derived or sha256(payload) != EXPECTED_OUTPUT_SHA256:
        raise SuccessorError("checked future oracle output differs from derivation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the deterministic checked output"
    )
    args = parser.parse_args(argv)
    try:
        baseline, output, fixtures = derive()
        payload = encoded(output)
        if args.write:
            OUTPUT.write_bytes(payload)
        else:
            check_output(payload)
        counts = validate(baseline, output, load_locked(ORACLE_SCHEMA), fixtures)
        print(json.dumps({"status": "pass", **counts}, sort_keys=True))
        return 0
    except (SuccessorError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
