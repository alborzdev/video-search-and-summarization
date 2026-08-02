#!/usr/bin/env python3
"""Fail-closed compiler for the additive request-cancellation static rebase."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "contract.schema.json"
RECEIPT_PATH = HERE / "static-receipt.json"
RECEIPT_SCHEMA_PATH = HERE / "static-receipt.schema.json"
MAX_FILE_BYTES = 96_000_000

EXPECTED_SOURCE_PATHS = {
    "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py": "production",
    "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py": "production",
    "services/rtvi/rt-vlm/src/vlm_pipeline/process_base.py": "production",
    "services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py": "production",
    "services/video-summarization/src/lvs_mcp.py": "production",
    "services/video-summarization/src/rtvi_vlm_client.py": "production",
    "services/video-summarization/src/via_server.py": "production",
    "services/video-summarization/src/via_stream_handler.py": "production",
    "services/rtvi/rt-vlm/tests/rtvi_vlm/test_request_abort.py": "test",
    "services/video-summarization/tests/test_lvs_delete_cleanup.py": "test",
    "services/video-summarization/tests/test_lvs_mcp.py": "test",
    "services/video-summarization/tests/test_lvs_request_ownership.py": "test",
    "services/video-summarization/tests/test_rtvi_vlm_abort.py": "test",
}
EXPECTED_PREDECESSORS = {
    "lvs-mcp-static-adapter-integration",
    "advertised-entry-executors-wave8",
    "successor-500-executable-subsets-wave1",
    "protocol-cases-v1",
    "protocol-cases-v2-candidates",
    "candidate-execution-binding-registry-rebase-successor",
    "candidate-execution-bindings-wave1-rebase-successor",
    "lvs-mcp-candidate-workload-repair-successor",
}
EXPECTED_TEST_INVOCATIONS = [
    [
        "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest",
        "services/rtvi/rt-vlm/tests/rtvi_vlm/test_request_abort.py",
    ],
    [
        "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "services/video-summarization/tests/test_lvs_delete_cleanup.py",
        "services/video-summarization/tests/test_lvs_mcp.py",
        "services/video-summarization/tests/test_lvs_request_ownership.py",
        "services/video-summarization/tests/test_rtvi_vlm_abort.py",
    ],
]
EXPECTED_COUNTS = {
    "lvs-mcp": ("tool_count", 13, 13, 0),
    "lvs": ("declared_operation_count", 18, 18, 0),
    "rt-vlm": ("declared_operation_count", 28, 27, 1),
}
EXPECTED_LEDGER_COUNTS = {
    "api-inventory": {"declared_rest_operations": 330, "normalized_unique_rest_operations": 329},
    "live-official-capabilities": {"capabilities": 289},
    "live-capability-oracles": {"oracles": 289},
}
RT_LOCAL_EXTENSION_CONTRACT = {
    "operation_count": 28,
    "documented_operation_count": 27,
    "thor_local_operation_count": 28,
    "thor_local_extension": {
        "method": "DELETE",
        "path": "/v1/generate_captions/requests/{request_id}",
    },
}


class QualificationError(RuntimeError):
    """A source identity or static qualification invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"{label}: non-finite token {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label}: root must be an object")
    return value


def resolve_regular(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in pure.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise QualificationError(f"missing repository path: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationError(f"repository path traverses symlink: {relative}")
    if not stat.S_ISREG(current.stat().st_mode):
        raise QualificationError(f"repository path is not a regular file: {relative}")
    if current.stat().st_size > MAX_FILE_BYTES:
        raise QualificationError(f"repository file exceeds size bound: {relative}")
    return current


def load_and_validate(path: Path, schema_path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    document = strict_json(payload, path.name)
    schema = strict_json(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid schema {schema_path.name}: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise QualificationError(f"{path.name}: schema validation failed: {errors[0].message}")
    return document


def verify_source_locks(contract: dict[str, Any]) -> dict[str, str]:
    locks = contract["source_locks"]
    observed_paths = {row["path"]: row["role"] for row in locks}
    if observed_paths != EXPECTED_SOURCE_PATHS:
        raise QualificationError("source lock path/role set is not the frozen 8+5 set")
    if len(observed_paths) != len(locks):
        raise QualificationError("source locks contain duplicate paths")

    observed_hashes: dict[str, str] = {}
    for row in locks:
        digest = sha256(resolve_regular(row["path"]).read_bytes())
        if digest != row["raw_sha256"]:
            raise QualificationError(f"source raw hash drift: {row['path']}")
        observed_hashes[row["path"]] = digest
    return observed_hashes


def _canonical_file_bytes(path: Path, payload: bytes) -> bytes:
    if path.suffix != ".json":
        return payload
    return canonical_bytes(strict_json(payload, path.as_posix()))


def package_identity(relative: str) -> dict[str, Any]:
    package_dir = (REPO_ROOT / relative).resolve(strict=True)
    if not package_dir.is_dir() or REPO_ROOT not in package_dir.parents:
        raise QualificationError(f"unsafe predecessor package: {relative}")

    files: list[dict[str, Any]] = []
    raw_identity = hashlib.sha256()
    canonical_identity = hashlib.sha256()
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        if path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise QualificationError(f"predecessor contains symlink: {path}")
        payload = path.read_bytes()
        if len(payload) > MAX_FILE_BYTES:
            raise QualificationError(f"predecessor file exceeds size bound: {path}")
        rel = path.relative_to(package_dir).as_posix()
        canonical = _canonical_file_bytes(path, payload)
        prefix = rel.encode("utf-8") + b"\0"
        raw_identity.update(prefix + payload + b"\0")
        canonical_identity.update(prefix + canonical + b"\0")
        files.append(
            {
                "path": rel,
                "byte_count": len(payload),
                "raw_sha256": sha256(payload),
                "canonical_sha256": sha256(canonical),
            }
        )
    return {
        "file_count": len(files),
        "raw_identity_sha256": raw_identity.hexdigest(),
        "canonical_identity_sha256": canonical_identity.hexdigest(),
        "tree_sha256": sha256(canonical_bytes(files)),
    }


def verify_predecessors(contract: dict[str, Any]) -> None:
    rows = contract["predecessor_packages"]
    ids = {row["id"] for row in rows}
    if ids != EXPECTED_PREDECESSORS or len(ids) != len(rows):
        raise QualificationError("predecessor package set is incomplete or duplicated")
    for row in rows:
        expected = {key: row[key] for key in (
            "file_count",
            "raw_identity_sha256",
            "canonical_identity_sha256",
            "tree_sha256",
        )}
        if package_identity(row["path"]) != expected:
            raise QualificationError(f"predecessor package identity drift: {row['id']}")


def verify_current_contracts(
    contract: dict[str, Any], source_hashes: dict[str, str]
) -> None:
    rows = contract["current_contracts"]
    if {row["id"] for row in rows} != set(EXPECTED_COUNTS) or len(rows) != 3:
        raise QualificationError("current expected-contract set is incomplete or duplicated")

    for row in rows:
        payload = resolve_regular(row["path"]).read_bytes()
        document = strict_json(payload, row["path"])
        if sha256(payload) != row["current_raw_sha256"]:
            raise QualificationError(f"current contract raw drift: {row['id']}")
        if sha256(canonical_bytes(document)) != row["current_canonical_sha256"]:
            raise QualificationError(f"current contract canonical drift: {row['id']}")
        surface = {key: value for key, value in document.items() if key != "source_files"}
        if sha256(canonical_bytes(surface)) != row["surface_canonical_sha256"]:
            raise QualificationError(f"current contract surface drift: {row['id']}")

        field, count, denominator, extensions = EXPECTED_COUNTS[row["id"]]
        if (
            row["count_field"],
            row["current_count"],
            row["official_denominator"],
            row["local_extension_count"],
        ) != (field, count, denominator, extensions):
            raise QualificationError(f"count policy drift: {row['id']}")
        if document.get(field) != count:
            raise QualificationError(f"current contract count drift: {row['id']}")
        if document.get("normalized_unique_operation_count", count) != count:
            raise QualificationError(f"unique operation count drift: {row['id']}")
        for source in document.get("source_files", []):
            current_digest = source_hashes.get(source.get("path"))
            if current_digest and source.get("sha256") != current_digest:
                raise QualificationError(f"current contract source drift: {row['id']}")

        extension = row["local_extension"]
        if row["id"] == "rt-vlm":
            if extension != {
                "method": "DELETE",
                "path": "/v1/generate_captions/requests/{request_id}",
                "reason": (
                    "Thor-local exact request-id cancellation adapter; "
                    "the documented denominator remains 27"
                ),
            }:
                raise QualificationError("RT-VLM local-extension explanation drift")
            operations = {
                (operation.get("method"), operation.get("path"))
                for operation in document.get("operations", [])
            }
            if (extension["method"], extension["path"]) not in operations:
                raise QualificationError("RT-VLM exact DELETE extension is absent")
        elif extension is not None:
            raise QualificationError(f"unexpected local extension: {row['id']}")


def verify_current_ledgers(contract: dict[str, Any]) -> None:
    rows = contract["current_ledger_inputs"]
    if {row["id"] for row in rows} != set(EXPECTED_LEDGER_COUNTS) or len(rows) != 3:
        raise QualificationError("current ledger input set is incomplete or duplicated")
    for row in rows:
        payload = resolve_regular(row["path"]).read_bytes()
        document = strict_json(payload, row["path"])
        if sha256(payload) != row["raw_sha256"]:
            raise QualificationError(f"current ledger raw drift: {row['id']}")
        if sha256(canonical_bytes(document)) != row["canonical_sha256"]:
            raise QualificationError(f"current ledger canonical drift: {row['id']}")
        if row["required_counts"] != EXPECTED_LEDGER_COUNTS[row["id"]]:
            raise QualificationError(f"current ledger count policy drift: {row['id']}")
        if row["id"] == "api-inventory":
            observed = document.get("expected_totals", {})
        else:
            observed = {
                name: len(document.get(name, [])) for name in row["required_counts"]
            }
        for name, expected in row["required_counts"].items():
            if observed.get(name) != expected:
                raise QualificationError(f"current ledger count drift: {row['id']}.{name}")
        if row["id"] == "api-inventory":
            difference = document.get("known_contract_differences", {}).get(
                "rt_vlm_exact_request_abort", {}
            )
            observed_extension = {
                "operation_count": difference.get("thor_local_operation_count"),
                "documented_operation_count": difference.get(
                    "documented_operation_count"
                ),
                "thor_local_operation_count": difference.get(
                    "thor_local_operation_count"
                ),
                "thor_local_extension": {
                    "method": (difference.get("thor_local_extension") or [None, None])[0],
                    "path": (difference.get("thor_local_extension") or [None, None])[1],
                },
            }
            verify_rt_local_extension(observed_extension, "api inventory")
        elif row["id"] == "live-official-capabilities":
            matches = [
                item for item in document.get("capabilities", [])
                if item.get("id") == "api.core.rt-vlm-27"
            ]
            if len(matches) != 1:
                raise QualificationError("live official RT-VLM capability is not unique")
            verify_rt_local_extension(matches[0].get("contract", {}), "live official")
        else:
            matches = [
                item for item in document.get("oracles", [])
                if item.get("capability_id") == "api.core.rt-vlm-27"
            ]
            if len(matches) != 1:
                raise QualificationError("live RT-VLM oracle is not unique")
            oracle = matches[0]
            verify_rt_local_extension(
                oracle.get("ledger_binding", {}).get("contract", {}), "live oracle"
            )
            if oracle.get("evidence") != [] or oracle.get("current_state") != "open_unexecuted":
                raise QualificationError("live RT-VLM oracle improperly claims execution")


def verify_rt_local_extension(observed: dict[str, Any], label: str) -> None:
    projection = {key: observed.get(key) for key in RT_LOCAL_EXTENSION_CONTRACT}
    if projection != RT_LOCAL_EXTENSION_CONTRACT:
        raise QualificationError(f"{label} RT-VLM 27/28 extension drift")


def verify_policy(contract: dict[str, Any]) -> None:
    if contract["test_policy"]["allowed_invocations"] != EXPECTED_TEST_INVOCATIONS:
        raise QualificationError("static test invocation drift")
    state = contract["qualification_state"]
    if state != {
        "runtime_evidence": [],
        "passed_current_promotions": 0,
        "admission_state_changed": False,
        "executable_state_changed": False,
        "authorization_state_changed": False,
        "warehouse_sample_bundle": "excluded",
    }:
        raise QualificationError("non-promoting or Warehouse boundary drift")
    if len(contract["deployed_runtime_blockers"]) < 4:
        raise QualificationError("deployed/runtime blockers are incomplete")


def verify_receipt(contract: dict[str, Any]) -> None:
    receipt = load_and_validate(RECEIPT_PATH, RECEIPT_SCHEMA_PATH)
    contract_payload = CONTRACT_PATH.read_bytes()
    if receipt["contract_raw_sha256"] != sha256(contract_payload):
        raise QualificationError("receipt contract raw identity drift")
    if receipt["contract_canonical_sha256"] != sha256(canonical_bytes(contract)):
        raise QualificationError("receipt contract canonical identity drift")
    if receipt["validated_test_invocations"] != EXPECTED_TEST_INVOCATIONS:
        raise QualificationError("receipt test invocation drift")
    if not receipt["tests_executed_by_receipt"] or receipt["static_test_results"] != [
        {"lane": "rt-vlm-isolated", "passed": 18, "subtests_passed": 0, "failed": 0},
        {
            "lane": "lvs-normal-conftest",
            "passed": 97,
            "subtests_passed": 82,
            "failed": 0,
        },
    ]:
        raise QualificationError("receipt static test results drift")
    if receipt["runtime_evidence"] or receipt["passed_current_promotions"] != 0:
        raise QualificationError("receipt improperly claims runtime evidence or promotion")


def check() -> dict[str, Any]:
    contract = load_and_validate(CONTRACT_PATH, SCHEMA_PATH)
    source_hashes = verify_source_locks(contract)
    verify_predecessors(contract)
    verify_current_contracts(contract, source_hashes)
    verify_current_ledgers(contract)
    verify_policy(contract)
    verify_receipt(contract)
    return {
        "status": "passed",
        "successor_id": contract["successor_id"],
        "source_lock_count": len(contract["source_locks"]),
        "production_source_count": sum(
            row["role"] == "production" for row in contract["source_locks"]
        ),
        "test_source_count": sum(
            row["role"] == "test" for row in contract["source_locks"]
        ),
        "predecessor_package_count": len(contract["predecessor_packages"]),
        "current_contract_counts": {
            row["id"]: row["current_count"] for row in contract["current_contracts"]
        },
        "runtime_evidence": [],
        "passed_current_promotions": 0,
        "warehouse_sample_bundle": "excluded",
    }


def execute_allowed_tests(contract: dict[str, Any]) -> None:
    verify_policy(contract)
    for invocation in EXPECTED_TEST_INVOCATIONS:
        command = [sys.executable, *invocation[1:]]
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        if completed.returncode:
            raise QualificationError(
                f"allowed static test executor failed with {completed.returncode}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate all static bindings")
    parser.add_argument(
        "--execute-tests",
        action="store_true",
        help="run only the exact source-locked static pytest invocation",
    )
    args = parser.parse_args()
    if not args.check and not args.execute_tests:
        parser.error("one of --check or --execute-tests is required")
    try:
        result = check()
        if args.execute_tests:
            execute_allowed_tests(load_and_validate(CONTRACT_PATH, SCHEMA_PATH))
    except (OSError, QualificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
