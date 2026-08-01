#!/usr/bin/env python3
"""Execute digest-bound, file-only source-contract assertions.

This isolated tranche materializes executor candidates only.  Its observations
are deterministic static evidence, never runtime evidence, and cannot advance
an official capability or mark one ``passed_current``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import stat
import sys
import time
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
INVENTORY_PATH = LANE / "inventory.json"
INVENTORY_SCHEMA_PATH = LANE / "inventory.schema.json"
RESULT_SCHEMA_PATH = LANE / "result.schema.json"
OFFICIAL_LEDGER_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
MAX_BYTES = 4 * 1024 * 1024
MAX_FILES = 16
DEADLINE_SECONDS = 5
INVENTORY_CANONICAL_SHA256 = (
    "7c9d65fee42f0f6089ec705972ae900a001ab68eaafad23d3c983425b305fe7f"
)
INVENTORY_SCHEMA_RAW_SHA256 = (
    "8cf3261a8785d376af2d9bd1b9b5a4216e06f5408cb724af0db485ad2091f81f"
)
RESULT_SCHEMA_RAW_SHA256 = (
    "ed542c6c39a2bcf9e754cada2d6b7d4114019dbeaa3a14789f907ca3c6d4fcd0"
)
EXPECTED_CASE_IDS = {
    "source-contract-case.performance-alert-verification",
    "source-contract-case.performance-lvs",
    "source-contract-case.performance-search",
    "source-contract-case.performance-rt-cv",
    "source-contract-case.performance-rt-vlm",
    "source-contract-case.performance-rt-embed",
    "source-contract-case.performance-vios",
    "source-contract-case.alert-parser",
    "source-contract-case.behavior-dynamic-config",
    "source-contract-case.rt-cv-compose",
    "source-contract-case.va-bootstrap",
    "source-contract-case.elk-indices",
    "source-contract-case.observability-stack",
    "source-contract-case.release-tags",
    "source-contract-case.nvstreamer-full-config",
    "source-contract-case.vios-modules",
}
EXCLUDED_SAMPLE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)


class SourceContractError(RuntimeError):
    """Fail-closed package, binding, source-lock, or execution error."""


class BoundError(SourceContractError):
    """A file, byte, or time bound was exceeded."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SourceContractError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _load_package_json(path: Path, raw_sha256: str | None = None) -> Any:
    if path.is_symlink() or not path.is_file():
        raise SourceContractError(f"package JSON is not a regular file: {path}")
    payload = path.read_bytes()
    if len(payload) > MAX_BYTES:
        raise BoundError(f"package JSON exceeds {MAX_BYTES} bytes: {path}")
    if raw_sha256 is not None and _sha_bytes(payload) != raw_sha256:
        raise SourceContractError(f"package JSON raw digest drift: {path.name}")
    return _strict_json(payload, str(path))


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise SourceContractError(f"unsafe repository-relative path: {relative!r}")
    root = REPO_ROOT.resolve()
    cursor = root
    for component in candidate.parts:
        cursor /= component
        if cursor.is_symlink():
            raise SourceContractError(f"repository path contains a symlink: {cursor}")
    try:
        mode = cursor.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise SourceContractError(f"source is unavailable: {relative}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise SourceContractError(f"source is not a regular file: {relative}")
    return cursor


@dataclass
class Budget:
    started: float = field(default_factory=time.monotonic)
    bytes_read: int = 0
    files_read: int = 0
    hashes: dict[str, str] = field(default_factory=dict)
    payloads: dict[str, bytes] = field(default_factory=dict)

    def check_time(self) -> None:
        if time.monotonic() - self.started > DEADLINE_SECONDS:
            raise BoundError(f"case exceeded {DEADLINE_SECONDS} seconds")

    def read(self, relative: str) -> bytes:
        self.check_time()
        path = _repo_file(relative)
        if relative in self.payloads:
            size = path.stat(follow_symlinks=False).st_size
            if size < 0 or size > MAX_BYTES:
                raise BoundError(f"source exceeds {MAX_BYTES} bytes: {relative}")
            current = path.read_bytes()
            if len(current) != size:
                raise SourceContractError(
                    f"source size changed while rereading: {relative}"
                )
            if _sha_bytes(current) != self.hashes[relative]:
                raise SourceContractError(f"source changed while executing: {relative}")
            return self.payloads[relative]
        if self.files_read >= MAX_FILES:
            raise BoundError(f"case exceeds {MAX_FILES} source files")
        size = path.stat(follow_symlinks=False).st_size
        if size < 0 or size > MAX_BYTES - self.bytes_read:
            raise BoundError(f"case exceeds {MAX_BYTES} source bytes")
        payload = path.read_bytes()
        if len(payload) != size:
            raise SourceContractError(f"source size changed while reading: {relative}")
        self.bytes_read += len(payload)
        self.files_read += 1
        self.hashes[relative] = _sha_bytes(payload)
        self.payloads[relative] = payload
        self.check_time()
        return payload

    def rehash(self) -> dict[str, str]:
        self.check_time()
        observed: dict[str, str] = {}
        for relative in self.hashes:
            path = _repo_file(relative)
            size = path.stat(follow_symlinks=False).st_size
            if size < 0 or size > MAX_BYTES:
                raise BoundError(f"source exceeds {MAX_BYTES} bytes: {relative}")
            payload = path.read_bytes()
            if len(payload) != size:
                raise SourceContractError(
                    f"source size changed while rehashing: {relative}"
                )
            observed[relative] = _sha_bytes(payload)
            self.check_time()
        return observed


def _pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw in pointer.split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdigit() or int(part) >= len(value):
                raise SourceContractError(f"list pointer does not resolve: {pointer}")
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise SourceContractError(f"JSON pointer does not resolve: {pointer}")
    return value


def _planning_binding(
    case: dict[str, Any], inventory: dict[str, Any], budget: Budget
) -> list[dict[str, Any]]:
    source_path = inventory["planning_source"]["path"]
    planning = _strict_json(budget.read(source_path), source_path)
    records = planning.get("wave3_contracts", {}).get("planning_requirements", [])
    if len(records) != inventory["planning_source"]["denominator"]:
        raise SourceContractError("planning requirement denominator drift")
    matches = [
        item for item in records if item.get("id") == case["planning_requirement_id"]
    ]
    if len(matches) != 1:
        raise SourceContractError(
            "planning requirement binding is missing or ambiguous"
        )
    record = matches[0]
    for key, expected in inventory["planning_source"]["required_source_state"].items():
        if record.get(key) != expected:
            raise SourceContractError(
                f"planning source state drift: {case['planning_requirement_id']}/{key}"
            )
    live_integrated = (
        record.get("materialized") is True
        and record.get("executor_ready") is True
        and isinstance(record.get("static_executor_binding"), dict)
    )
    isolated = (
        record.get("materialized") is False
        and record.get("executor_ready") is False
        and "static_executor_binding" not in record
    )
    if not (live_integrated or isolated):
        raise SourceContractError("partial planning materialization state")
    if live_integrated:
        binding = record["static_executor_binding"]
        if (
            binding.get("case", {}).get("case_id") != case["case_id"]
            or binding.get("case", {}).get("planning_requirement_id")
            != case["planning_requirement_id"]
            or binding.get("case", {}).get("capability_id")
            != case["capability_id"]
            or binding.get("case", {}).get("planning_payload_sha256")
            != case["planning_payload_sha256"]
            or binding.get("result", {}).get("runtime_evidence") != []
            or binding.get("result", {}).get("can_advance_capability") is not False
            or binding.get("result", {}).get("can_mark_passed_current") is not False
        ):
            raise SourceContractError("live planning executor binding drift")
    if record.get("owner_id") != case["capability_id"]:
        raise SourceContractError("planning owner/capability binding drift")
    if record.get("payload_canonical_sha256") != case["planning_payload_sha256"]:
        raise SourceContractError("planning payload hash binding drift")
    if _sha_json(record.get("payload")) != case["planning_payload_sha256"]:
        raise SourceContractError("planning payload content does not match its hash")

    official = _strict_json(budget.read(OFFICIAL_LEDGER_PATH), OFFICIAL_LEDGER_PATH)
    capabilities = [
        item
        for item in official.get("capabilities", [])
        if item.get("id") == case["capability_id"]
    ]
    if len(capabilities) != 1:
        raise SourceContractError("official capability binding is missing or ambiguous")
    capability = capabilities[0]
    if capability.get("runtime_state") == "passed_current":
        raise SourceContractError(
            "static tranche cannot bind a passed_current capability"
        )
    wave3 = capability.get("contract", {}).get("wave3_acceptance", {})
    if (
        wave3.get("materialized") is not False
        or wave3.get("executor_ready") is not False
    ):
        raise SourceContractError("official capability advanced outside this tranche")
    if case["planning_requirement_id"] not in wave3.get("planning_requirement_ids", []):
        raise SourceContractError("official capability lacks planning binding")

    return [
        {
            "assertion_id": "planning-payload-binding",
            "adapter": "canonical_payload_binding",
            "status": "match",
            "expected": case["planning_payload_sha256"],
            "observed": _sha_json(record["payload"]),
            "sources": [source_path],
        },
        {
            "assertion_id": "planning-state-isolated",
            "adapter": "live_integration_guard",
            "status": "match",
            "expected": (
                "live_planning_integration" if live_integrated else "isolated_candidate"
            ),
            "observed": (
                "live_planning_integration" if live_integrated else "isolated_candidate"
            ),
            "sources": [source_path],
        },
        {
            "assertion_id": "runtime-state-preserved",
            "adapter": "capability_state_guard",
            "status": "match",
            "expected": "not_passed_current",
            "observed": capability.get("runtime_state"),
            "sources": [OFFICIAL_LEDGER_PATH],
        },
    ]


def _verify_source_locks(case: dict[str, Any], budget: Budget) -> dict[str, Any]:
    locks = {item["path"]: item["sha256"] for item in case["source_locks"]}
    if len(locks) != len(case["source_locks"]):
        raise SourceContractError("duplicate source lock path")
    assertion_sources = {
        source for assertion in case["assertions"] for source in assertion["sources"]
    }
    if assertion_sources != set(locks):
        raise SourceContractError("source locks do not exactly cover assertion sources")
    observed: dict[str, str] = {}
    for path, expected in locks.items():
        observed[path] = _sha_bytes(budget.read(path))
        if observed[path] != expected:
            raise SourceContractError(f"assertion source digest drift: {path}")
    return {
        "assertion_id": "source-digest-locks",
        "adapter": "sha256_lock_set",
        "status": "match",
        "expected": locks,
        "observed": observed,
        "sources": sorted(locks),
    }


def _evaluate(assertion: dict[str, Any], budget: Budget) -> dict[str, Any]:
    payloads = [budget.read(path) for path in assertion["sources"]]
    adapter = assertion["adapter"]
    expected = assertion["expected"]
    if adapter == "text_contains_all":
        texts = [payload.decode("utf-8") for payload in payloads]
        missing = [
            token for token in expected if not any(token in text for text in texts)
        ]
        observed: Any = {
            "missing": missing,
            "matched_count": len(expected) - len(missing),
        }
        matched = not missing
    elif adapter == "json_pointer_equals":
        if len(payloads) != 1:
            raise SourceContractError("json_pointer_equals requires one source")
        document = _strict_json(payloads[0], assertion["sources"][0])
        observed = _pointer(document, assertion["pointer"])
        matched = observed == expected
    else:
        raise SourceContractError(f"unsupported adapter: {adapter}")
    return {
        "assertion_id": assertion["assertion_id"],
        "adapter": adapter,
        "status": "match" if matched else "mismatch",
        "expected": expected,
        "observed": observed,
        "sources": assertion["sources"],
    }


def load_and_validate_inventory() -> dict[str, Any]:
    inventory = _load_package_json(INVENTORY_PATH)
    schema = _load_package_json(INVENTORY_SCHEMA_PATH, INVENTORY_SCHEMA_RAW_SHA256)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(inventory),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "; ".join(error.message for error in errors[:5])
        raise SourceContractError(f"inventory schema validation failed: {detail}")
    if _sha_json(inventory) != INVENTORY_CANONICAL_SHA256:
        raise SourceContractError("source-contract inventory canonical digest drift")
    _load_package_json(RESULT_SCHEMA_PATH, RESULT_SCHEMA_RAW_SHA256)
    ids = [case["case_id"] for case in inventory["cases"]]
    planning_ids = [case["planning_requirement_id"] for case in inventory["cases"]]
    capability_ids = [case["capability_id"] for case in inventory["cases"]]
    if set(ids) != EXPECTED_CASE_IDS or len(ids) != len(set(ids)):
        raise SourceContractError("exact sixteen-case tranche denominator drift")
    if len(planning_ids) != len(set(planning_ids)):
        raise SourceContractError("planning requirement bindings are not unique")
    if len(capability_ids) != len(set(capability_ids)):
        raise SourceContractError("capability bindings are not unique")
    inventory_text = INVENTORY_PATH.read_text(encoding="utf-8")
    forbidden = [
        marker for marker in EXCLUDED_SAMPLE_MARKERS if marker in inventory_text
    ]
    if forbidden:
        raise SourceContractError(
            f"excluded Warehouse sample marker present: {forbidden}"
        )
    return inventory


def run_case(inventory: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [case for case in inventory["cases"] if case["case_id"] == case_id]
    if len(matches) != 1:
        raise SourceContractError(f"unknown or ambiguous case ID: {case_id}")
    case = matches[0]
    budget = Budget()
    observations = _planning_binding(case, inventory, budget)
    observations.append(_verify_source_locks(case, budget))
    observations.extend(
        _evaluate(assertion, budget) for assertion in case["assertions"]
    )
    hashes_after = budget.rehash()
    if hashes_after != budget.hashes:
        raise SourceContractError("a source changed during execution")
    outcome = (
        "observed_match"
        if all(item["status"] == "match" for item in observations)
        else "observed_mismatch"
    )
    result = {
        "schema_version": 1,
        "case_id": case["case_id"],
        "planning_requirement_id": case["planning_requirement_id"],
        "capability_id": case["capability_id"],
        "materialized": True,
        "materialization_scope": (
            "live_planning_requirement"
            if any(
                item["assertion_id"] == "planning-state-isolated"
                and item["observed"] == "live_planning_integration"
                for item in observations
            )
            else "isolated_candidate_only"
        ),
        "executor_ready": True,
        "advancement_scope": "static_assertion_only",
        "can_advance_capability": False,
        "can_mark_passed_current": False,
        "evidence_class": "deterministic_file_static_evidence_not_runtime",
        "outcome": outcome,
        "observations": observations,
        "bounds": {
            "max_bytes": MAX_BYTES,
            "max_files": MAX_FILES,
            "deadline_seconds": DEADLINE_SECONDS,
            "bytes_read": budget.bytes_read,
            "files_read": budget.files_read,
        },
        "source_hashes_before": dict(budget.hashes),
        "source_hashes_after": hashes_after,
        "runtime_evidence": [],
    }
    result_schema = _load_package_json(RESULT_SCHEMA_PATH, RESULT_SCHEMA_RAW_SHA256)
    errors = list(Draft202012Validator(result_schema).iter_errors(result))
    if errors:
        raise SourceContractError(
            f"result schema validation failed: {errors[0].message}"
        )
    return result


def run_all(inventory: dict[str, Any]) -> dict[str, Any]:
    results = [run_case(inventory, case["case_id"]) for case in inventory["cases"]]
    outcomes = {name: 0 for name in inventory["policy"]["allowed_outcomes"]}
    for result in results:
        outcomes[result["outcome"]] += 1
    return {
        "schema_version": 1,
        "mode": "isolated_source_contract_static_execution",
        "candidate_materialized_count": len(results),
        "candidate_executor_ready_count": len(results),
        "live_requirement_materialized_count": sum(
            result["materialization_scope"] == "live_planning_requirement"
            for result in results
        ),
        "live_requirement_executor_ready_count": sum(
            result["materialization_scope"] == "live_planning_requirement"
            and result["executor_ready"] is True
            for result in results
        ),
        "runtime_evidence_count": 0,
        "can_advance_capability_count": 0,
        "can_mark_passed_current_count": 0,
        "outcomes": outcomes,
        "results": results,
    }


def plan(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "isolated_source_contract_executor_candidate_plan",
        "case_count": len(inventory["cases"]),
        "executor_ready_count": len(inventory["cases"]),
        "evidence_class": inventory["policy"]["evidence_class"],
        "can_advance_capability": False,
        "can_mark_passed_current": False,
        "network": "forbidden",
        "docker": "forbidden",
        "subprocess": "forbidden",
        "environment_mutation": "forbidden",
        "cases": [
            {
                "case_id": case["case_id"],
                "planning_requirement_id": case["planning_requirement_id"],
                "capability_id": case["capability_id"],
                "materialized": True,
                "materialization_scope": "isolated_candidate_only",
                "executor_ready": True,
            }
            for case in inventory["cases"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("plan")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("case_id")
    subparsers.add_parser("run-all")
    args = parser.parse_args()
    try:
        inventory = load_and_validate_inventory()
        if args.command == "validate":
            print("PASS: 16 isolated source-contract executor cases validated")
        elif args.command == "plan":
            print(json.dumps(plan(inventory), indent=2, sort_keys=True))
        elif args.command == "run":
            print(
                json.dumps(run_case(inventory, args.case_id), indent=2, sort_keys=True)
            )
        else:
            print(json.dumps(run_all(inventory), indent=2, sort_keys=True))
    except SourceContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
