#!/usr/bin/env python3
"""Compile the future MV3DT config-utils receipt-authority oracle projection."""

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

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
OUTPUT = PACKAGE / "post-state-capability-oracles.json"
MAX_JSON_BYTES = 8_000_000

CURRENT_ORACLES = (
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "c45bc270163b2369b1650d638f5fa0e3f53aa327e4b0375e6773246ca35fbbf5",
)
SELECTED_ORACLES = (
    "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/post-state-capability-oracles.json",
    "c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6",
)
ORACLE_SCHEMA = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.schema.json",
    "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
)
INTERFACE = (
    "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/runtime-interface.json",
    "599851800c45a54854237dccf24caf031e698c054c44b68a5fcc949d480054ba",
)
INTERFACE_SCHEMA = (
    "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/runtime-interface.schema.json",
    "c9e23911a010d6e1e97b1e214dd259dc8cc46ae7a6339ae40f5f92fefdd6fb20",
)
EXPECTED_OUTPUT_SHA256 = (
    "53fe977aa208cdc78604e214817dac7d3683edea4402b160b9d3cf46571b49e3"
)
FINAL_GAP = (
    "No known gap: a current target-bound offline runtime receipt covers the exact "
    "MV3DT configuration generator contract twice, including adjacent-negative "
    "behavior, determinism, and exact cleanup without the Warehouse sample bundle."
)
TARGET_IDS = (
    "tool.mv3dt.cam-info-generator",
    "tool.mv3dt.pub-sub-generator",
)


class ProjectionError(RuntimeError):
    """A source lock, runtime interface, schema, or exact delta failed."""


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
        raise ProjectionError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ProjectionError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise ProjectionError(f"repository input contains symlink: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ProjectionError(f"repository input is not regular: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectionError(f"repository input escapes root: {relative}") from exc
    return current


def strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise ProjectionError(f"oversized JSON input: {label}")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise ProjectionError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ProjectionError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except ProjectionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"invalid JSON in {label}: {exc}") from exc


def load_locked(source: tuple[str, str]) -> Any:
    relative, expected = source
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ProjectionError(f"unfinalized source lock: {relative}")
    payload = repo_file(relative).read_bytes()
    if sha256(payload) != expected:
        raise ProjectionError(f"raw source digest drift: {relative}")
    return strict_json(payload, relative)


def load_interface() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    interface = load_locked(INTERFACE)
    schema = load_locked(INTERFACE_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(interface),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        path = "/".join(map(str, errors[0].absolute_path))
        raise ProjectionError(
            f"runtime interface schema failure at {path}: {errors[0].message}"
        )
    role_paths = {
        interface[name]["path"]
        for name in (
            "fixture_generator",
            "executor",
            "request_collector",
            "postcondition_collector",
        )
    }
    if len(role_paths) != 1:
        raise ProjectionError("runtime roles do not resolve to one reviewed executor")
    executor_source = interface["executor_source"]
    if (
        role_paths != {executor_source["path"]}
        or sha256(repo_file(executor_source["path"]).read_bytes())
        != executor_source["sha256"]
    ):
        raise ProjectionError("runtime executor source binding drift")
    runtime_contract = interface["runtime_contract"]
    if (
        sha256(repo_file(runtime_contract["path"]).read_bytes())
        != runtime_contract["sha256"]
    ):
        raise ProjectionError("runtime contract source binding drift")
    shared = interface["shared_source_payload"]
    if sha256(repo_file(shared["path"]).read_bytes()) != shared["sha256"]:
        raise ProjectionError("shared source payload digest drift")
    capabilities = interface["capabilities"]
    if [row["capability_id"] for row in capabilities] != list(TARGET_IDS):
        raise ProjectionError("runtime interface target identity/order drift")
    indexed: dict[str, dict[str, Any]] = {}
    for row in capabilities:
        capability_id = row["capability_id"]
        lock = row["fixture_manifest"]
        payload = repo_file(lock["path"]).read_bytes()
        if sha256(payload) != lock["sha256"]:
            raise ProjectionError(f"fixture manifest digest drift: {capability_id}")
        fixture = strict_json(payload, lock["path"])
        if (
            fixture.get("capability_id") != capability_id
            or fixture.get("fixture_id") != row["fixture_id"]
            or fixture.get("namespace") != row["namespace"]
            or fixture.get("warehouse_sample_bundle") != "excluded"
            or fixture.get("source_payload") != shared
            or fixture.get("positive", {}).get("runs") != row["positive_runs"]
            or len(fixture.get("adjacent_negative_case_ids", [])) != 5
        ):
            raise ProjectionError(f"fixture manifest identity drift: {capability_id}")
        bounds = row["execution_bounds"]
        workload = bounds["workload"]
        calculated = (
            workload["units"] * workload["requests_per_unit"]
            + workload["overhead_requests"]
        )
        action_count = row["positive_runs"] + len(fixture["adjacent_negative_case_ids"])
        expected_supporting_calls = 0 if capability_id == TARGET_IDS[0] else 3
        if (
            calculated != workload["calculated_max_requests"]
            or bounds["max_requests"] != calculated
            or calculated != action_count
            or bounds["supporting_cam_generation_actions"] != expected_supporting_calls
            or bounds["max_actions"] != action_count + expected_supporting_calls
        ):
            raise ProjectionError(
                f"runtime action/request arithmetic drift: {capability_id}"
            )
        indexed[capability_id] = {**copy.deepcopy(row), "fixture": fixture}
    accounting = interface["aggregate_execution_accounting"]
    target_case_actions = sum(
        row["positive_runs"]
        + len(indexed[row["capability_id"]]["fixture"]["adjacent_negative_case_ids"])
        for row in capabilities
    )
    supporting_calls = sum(
        row["execution_bounds"]["supporting_cam_generation_actions"]
        for row in capabilities
    )
    requests = sum(row["execution_bounds"]["max_requests"] for row in capabilities)
    if (
        accounting["target_case_actions"] != target_case_actions
        or accounting["supporting_cam_generation_actions"] != supporting_calls
        or accounting["bounded_capability_actions"]
        != target_case_actions + supporting_calls
        or accounting["requests"] != requests
        or accounting["total_imported_source_function_invocations"]
        != accounting["bounded_capability_actions"]
        + accounting["imported_helper_invocations"]
    ):
        raise ProjectionError("aggregate execution accounting drift")
    return interface, indexed


def derive() -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    current = load_locked(CURRENT_ORACLES)
    selected = load_locked(SELECTED_ORACLES)
    interface, bindings = load_interface()
    del interface
    if len(current["oracles"]) != 289 or len(selected["oracles"]) != 500:
        raise ProjectionError("current/selected oracle denominator drift")
    current_ids = [row["capability_id"] for row in current["oracles"]]
    selected_ids = [row["capability_id"] for row in selected["oracles"]]
    if current_ids != selected_ids[:289] or len(set(selected_ids)) != 500:
        raise ProjectionError("current 289-row prefix identity/order drift")
    selected_suffix = copy.deepcopy(selected["oracles"][289:])
    baseline = copy.deepcopy(selected)
    baseline["policy"] = copy.deepcopy(current["policy"])
    baseline["oracles"][:289] = copy.deepcopy(current["oracles"])
    if baseline["oracles"][289:] != selected_suffix:
        raise ProjectionError("selected 211-row candidate suffix changed during rebase")
    output = copy.deepcopy(baseline)
    executor = load_locked(INTERFACE)["executor"]["path"]
    found: list[str] = []
    for row in output["oracles"]:
        capability_id = row["capability_id"]
        binding = bindings.get(capability_id)
        if binding is None:
            continue
        found.append(capability_id)
        if (
            row["fixture"]["id"] != binding["fixture_id"]
            or row["fixture"]["input"]["namespace"] != binding["namespace"]
            or row["ledger_binding"]["contract"]["wave3_acceptance"]
            != {
                "contributions": [
                    {
                        "package": "calibration-warehouse",
                        "planning_requirement_ids": ["warehouse-mv3dt-custom-media"],
                    }
                ],
                "executor_ready": False,
                "materialized": False,
                "planning_requirement_ids": ["warehouse-mv3dt-custom-media"],
            }
        ):
            raise ProjectionError(f"canonical target contract drift: {capability_id}")
        row["ledger_binding"]["thor_state"] = "wired"
        row["ledger_binding"]["runtime_state"] = "passed_current"
        row["ledger_binding"]["gap"] = FINAL_GAP
        row["fixture"]["materialization"] = {
            "generator": executor,
            "path": binding["fixture_manifest"]["path"],
            "sha256": binding["fixture_manifest"]["sha256"],
        }
        row["execution_bounds"]["executor"] = executor
        row["execution_bounds"]["collectors"] = [executor]
        row["execution_bounds"]["max_actions"] = binding["execution_bounds"][
            "max_actions"
        ]
        row["execution_bounds"]["max_requests"] = binding["execution_bounds"][
            "max_requests"
        ]
        row["execution_bounds"]["workload"] = copy.deepcopy(
            binding["execution_bounds"]["workload"]
        )
        row["cleanup"]["executor"] = executor
        row["cleanup"]["postcondition_collectors"] = [executor]
        row["acceptance_readiness"] = {
            "blockers": [],
            "classification": "executor_ready",
        }
    if found != list(TARGET_IDS):
        raise ProjectionError("selected Metadata-500 target identity/order drift")
    validate(baseline, output, bindings)
    return baseline, output, bindings


def expected_target(
    source: dict[str, Any], binding: dict[str, Any], executor: str
) -> dict[str, Any]:
    expected = copy.deepcopy(source)
    expected["ledger_binding"]["thor_state"] = "wired"
    expected["ledger_binding"]["runtime_state"] = "passed_current"
    expected["ledger_binding"]["gap"] = FINAL_GAP
    expected["fixture"]["materialization"] = {
        "generator": executor,
        "path": binding["fixture_manifest"]["path"],
        "sha256": binding["fixture_manifest"]["sha256"],
    }
    expected["execution_bounds"]["executor"] = executor
    expected["execution_bounds"]["collectors"] = [executor]
    expected["execution_bounds"]["max_actions"] = binding["execution_bounds"][
        "max_actions"
    ]
    expected["execution_bounds"]["max_requests"] = binding["execution_bounds"][
        "max_requests"
    ]
    expected["execution_bounds"]["workload"] = copy.deepcopy(
        binding["execution_bounds"]["workload"]
    )
    expected["cleanup"]["executor"] = executor
    expected["cleanup"]["postcondition_collectors"] = [executor]
    expected["acceptance_readiness"] = {
        "blockers": [],
        "classification": "executor_ready",
    }
    return expected


def validate(
    baseline: dict[str, Any],
    output: dict[str, Any],
    bindings: dict[str, dict[str, Any]],
) -> dict[str, int]:
    schema = load_locked(ORACLE_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(output),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        path = "/".join(map(str, errors[0].absolute_path))
        raise ProjectionError(f"oracle schema failure at {path}: {errors[0].message}")
    before = {row["capability_id"]: row for row in baseline["oracles"]}
    after = {row["capability_id"]: row for row in output["oracles"]}
    if (
        len(before) != 500
        or list(before) != list(after)
        or output["policy"] != baseline["policy"]
    ):
        raise ProjectionError("Metadata-500 denominator, order, or policy drift")
    executor = load_locked(INTERFACE)["executor"]["path"]
    changed: set[str] = set()
    for capability_id, old in before.items():
        new = after[capability_id]
        if canonical_bytes(old) != canonical_bytes(new):
            changed.add(capability_id)
        if capability_id not in TARGET_IDS:
            if canonical_bytes(old) != canonical_bytes(new):
                raise ProjectionError(f"non-target oracle changed: {capability_id}")
            continue
        expected = expected_target(old, bindings[capability_id], executor)
        if canonical_bytes(expected) != canonical_bytes(new):
            raise ProjectionError(f"target has undeclared change: {capability_id}")
        if new["current_state"] != "open_unexecuted" or new["evidence"] != []:
            raise ProjectionError(f"projection invented evidence: {capability_id}")
        if new["fixture"]["availability"] != old["fixture"]["availability"]:
            raise ProjectionError(f"fixture availability changed: {capability_id}")
        if new["ledger_binding"]["contract"] != old["ledger_binding"][
            "contract"
        ] or new.get("offline_tool_observation_bindings") != old.get(
            "offline_tool_observation_bindings"
        ):
            raise ProjectionError(f"historical contract changed: {capability_id}")
    if changed != set(TARGET_IDS):
        raise ProjectionError("projection did not change exactly two target rows")
    return {
        "oracles": len(after),
        "preserved_oracles": len(after) - len(TARGET_IDS),
        "projected_executor_ready": len(TARGET_IDS),
        "projected_actions": sum(
            after[capability_id]["execution_bounds"]["max_actions"]
            for capability_id in TARGET_IDS
        ),
        "projected_requests": sum(
            after[capability_id]["execution_bounds"]["max_requests"]
            for capability_id in TARGET_IDS
        ),
        "runtime_evidence": sum(len(row["evidence"]) for row in after.values()),
        "selected_suffix": len(output["oracles"][289:]),
    }


def check_output(derived: bytes) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", EXPECTED_OUTPUT_SHA256) is None:
        raise ProjectionError("unfinalized checked output digest")
    payload = repo_file(str(OUTPUT.relative_to(REPO_ROOT))).read_bytes()
    if payload != derived or sha256(payload) != EXPECTED_OUTPUT_SHA256:
        raise ProjectionError("checked future oracle output differs from derivation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the deterministic projection"
    )
    args = parser.parse_args(argv)
    try:
        baseline, output, bindings = derive()
        payload = encoded(output)
        if args.write:
            OUTPUT.write_bytes(payload)
        else:
            check_output(payload)
        counts = validate(baseline, output, bindings)
        print(json.dumps({"status": "pass", **counts}, sort_keys=True))
        return 0
    except (ProjectionError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
