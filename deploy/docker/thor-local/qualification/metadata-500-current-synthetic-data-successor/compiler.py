#!/usr/bin/env python3
"""Compile the checked future Synthetic Data executor-ready oracle registry."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime
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
LEDGER_OUTPUT = PACKAGE / "post-state-official-capabilities.json"
MANIFEST_OUTPUT = PACKAGE / "post-state-manifest.json"
MAX_JSON_BYTES = 8_000_000

SOURCE_ORACLES = (
    "deploy/docker/thor-local/qualification/metadata-500-current-cancellation-search-successor/post-state-capability-oracles.json",
    "355679322116451972cb2366a61bfba23a72762863796aea84c93a7bb412db14",
)
CURRENT_ORACLES = (
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "c45bc270163b2369b1650d638f5fa0e3f53aa327e4b0375e6773246ca35fbbf5",
)
CURRENT_LEDGER = (
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "e94599599f8442f884aa4b184deafe3c5ce59aae310dd91ad0552133740c29e7",
)
SELECTED_LEDGER = (
    "deploy/docker/thor-local/qualification/metadata-500-current-cancellation-search-successor/post-state-official-capabilities.json",
    "bb03840d8ec05339758a9788f406d78b5c412eb1d56cdc90028bea5ad887d6a2",
)
SELECTED_MANIFEST = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-manifest.json",
    "f0efb35c49b2f6b5e23692203aa0e5e6588046927f35ab2725250e27a0d1faad",
)
SELECTED_ACCEPTANCE = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-acceptance-inventory.json",
    "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
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
RUNTIME_RESULT_SCHEMA = (
    "deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/result.schema.json",
    "40a60bd049941ed9110703f321c0a6d0cdbb207d7b5a312872f07171b1ff8834",
)
OFFICIAL_SCHEMA = (
    "deploy/docker/thor-local/parity/official-capabilities.schema.json",
    "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
)
AGGREGATE_RECEIPT = (
    "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/aggregate-runtime-receipt.json",
    "1e207198c907fde4f7370c3de814b88ebcd171e616be5f833e50509fb4b85362",
)
FIXTURE_SCHEMA = "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/fixture-manifest.schema.json"
EXECUTOR = "deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/executor.py"
EXPECTED_OUTPUT_SHA256 = (
    "c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6"
)
EXPECTED_LEDGER_SHA256 = (
    "6698f904f93fbefa7c2bc9c7512ccf4765d3ba27200843a86ea1e6522375ae73"
)
EXPECTED_MANIFEST_SHA256 = (
    "b2fa6b72ca756b37103178cb3d40aeed9e8d4d5c137883812ff0600f62168fb8"
)
EXPECTED_RECEIPT_SHA256: dict[str, str] = {
    "manifest-entry.synthetic-data-tools.00-semantic-label-helpers": "91afcd30bf85fdfe6cbc29ac0792707ee459912c900f2e2e6c6ade9dd66d9324",
    "manifest-entry.synthetic-data-tools.01-dataset-checks": "dbf1a3a21ae063b4b4eeb19553482cf245e98cdcbb32b5c3221f46deb8cc5a20",
    "manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion": "dac14785935ed85305b77d73cdd13f6ea953709bec8da83f07f272cd4d0e411b",
    "manifest-entry.synthetic-data-tools.03-ground-truth-conversion": "2611b2a01ac98e5c95a33980c3164811a1ded0c13e5ed0de94e0fa94e7141e7f",
}
CHECKOUT_HEAD = "53998f19f11451f63ef582e1f9d06602229461eb"
CHECKOUT_TREE = "eec19dd141cfa1278ef05754f1be85e51aa4972f"
EXECUTOR_SHA256 = "74b8ad607621a4a796899d7837e65c3f88c8f2b56e404e1942b529e8ddba140b"
AGGREGATE_SHA256 = AGGREGATE_RECEIPT[1]
RECEIPT_PREFIX = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-synthetic-data-successor/receipts"
)
FINAL_GAP = (
    "No known gap: the current target-bound offline runtime receipt covers the "
    "exact positive semantics, adjacent-negative behavior, determinism, and cleanup "
    "contract without the Warehouse sample bundle."
)
FINAL_FAMILY_GAP = (
    "No known gap: all four Synthetic Data tooling capabilities passed the current "
    "target-bound offline runtime contract twice, including adjacent-negative, "
    "determinism, and exact cleanup checks, without the Warehouse sample bundle."
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


def receipt_relative(capability_id: str) -> str:
    suffix = capability_id.removeprefix("manifest-entry.synthetic-data-tools.")
    return f"{RECEIPT_PREFIX}/{suffix}.json"


def validate_aggregate(
    aggregate: dict[str, Any],
    result_schema: dict[str, Any],
    contract: dict[str, Any],
    oracles: dict[str, dict[str, Any]],
    fixtures: dict[str, tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    errors = sorted(
        Draft202012Validator(result_schema).iter_errors(aggregate),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        raise SuccessorError(f"aggregate receipt schema failure: {errors[0].message}")
    expected_top_keys = {
        "schema_version",
        "package_id",
        "mode",
        "status",
        "captured_at_utc",
        "bindings",
        "environment",
        "capability_results",
        "cleanup",
        "confinement",
        "promotion",
    }
    if set(aggregate) != expected_top_keys:
        raise SuccessorError("aggregate receipt fields are not exact")
    try:
        captured = datetime.fromisoformat(
            aggregate["captured_at_utc"].replace("Z", "+00:00")
        )
    except (AttributeError, ValueError) as exc:
        raise SuccessorError("aggregate capture timestamp is invalid") from exc
    if captured.tzinfo is None:
        raise SuccessorError("aggregate capture timestamp is not timezone-bound")
    if (
        aggregate["schema_version"] != 1
        or aggregate["package_id"]
        != "thor-synthetic-data-runtime-evidence-successor-v1"
        or aggregate["mode"] != "target_bound_offline_runtime_evidence"
        or aggregate["status"] != "pass"
    ):
        raise SuccessorError("aggregate promotion identity is not successful")
    bindings = aggregate["bindings"]
    expected_binding_keys = {
        "checkout_clean",
        "checkout_head",
        "checkout_tree",
        "contract_sha256",
        "execution_oracle_assertion_ids",
        "execution_oracle_document_path",
        "execution_oracle_document_sha256",
        "execution_oracle_fixture_sha256",
        "execution_oracle_observation_ids",
        "execution_oracle_row_sha256",
        "execution_oracles_executor_ready",
        "executor_sha256",
        "product_version",
        "selected_metadata_set",
        "selected_oracle_document_sha256",
        "upstream_commit",
    }
    target_ids = [row[0] for row in TARGETS]
    if set(bindings) != expected_binding_keys:
        raise SuccessorError("aggregate binding fields are not exact")
    if (
        bindings["checkout_clean"] is not True
        or bindings["checkout_head"] != CHECKOUT_HEAD
        or bindings["checkout_tree"] != CHECKOUT_TREE
        or bindings["contract_sha256"] != RUNTIME_CONTRACT[1]
        or bindings["execution_oracle_document_path"]
        != str(OUTPUT.relative_to(REPO_ROOT))
        or bindings["execution_oracle_document_sha256"] != EXPECTED_OUTPUT_SHA256
        or bindings["execution_oracles_executor_ready"] is not True
        or bindings["executor_sha256"] != EXECUTOR_SHA256
        or bindings["product_version"] != "3.2.1"
        or bindings["selected_metadata_set"]
        != "thor-vss-3.2.1-current-cancellation-search-500"
        or bindings["selected_oracle_document_sha256"] != SOURCE_ORACLES[1]
        or bindings["upstream_commit"] != "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
    ):
        raise SuccessorError("aggregate immutable provenance binding drift")
    if sha256(repo_file(EXECUTOR).read_bytes()) != EXECUTOR_SHA256:
        raise SuccessorError("runtime executor differs from clean aggregate binding")

    runtime_rows = {row["capability_id"]: row for row in contract["capabilities"]}
    results = aggregate["capability_results"]
    if [row.get("capability_id") for row in results] != target_ids:
        raise SuccessorError("aggregate result order or target set drift")
    indexed: dict[str, dict[str, Any]] = {}
    for result in results:
        capability_id = result["capability_id"]
        oracle = oracles[capability_id]
        runtime = runtime_rows[capability_id]
        fixture_path, fixture_sha = fixtures[capability_id]
        del fixture_path
        expected_observation_ids = [
            row["id"] for row in oracle["expected_observations"]
        ]
        expected_assertion_ids = [row["id"] for row in oracle["assertions"]]
        namespace = oracle["fixture"]["input"]["namespace"]
        if (
            result.get("oracle_id") != oracle["oracle_id"]
            or result.get("status") != "pass"
            or result.get("fixture_sha256") != fixture_sha
            or result.get("generated_input_sha256") != runtime["generated_input_sha256"]
            or result.get("independent_runs") != 2
            or result.get("deterministic_output") is not True
            or len(result.get("run_output_sha256", [])) != 2
            or len(set(result["run_output_sha256"])) != 1
            or any(
                re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in result["run_output_sha256"]
            )
            or not result.get("positive_observations")
            or not result.get("adjacent_negatives")
            or any(
                row.get("rejected") is not True for row in result["adjacent_negatives"]
            )
            or result.get("cleanup")
            != {"namespace": namespace, "temporary_files_only": True}
        ):
            raise SuccessorError(f"aggregate result semantics drift: {capability_id}")
        observation_results = result.get("expected_observation_results")
        assertion_results = result.get("assertion_results")
        if (
            [row.get("observation_id") for row in observation_results]
            != expected_observation_ids
            or any(row.get("passed") is not True for row in observation_results)
            or [row.get("assertion_id") for row in assertion_results]
            != expected_assertion_ids
            or any(row.get("passed") is not True for row in assertion_results)
            or bindings["execution_oracle_observation_ids"].get(capability_id)
            != expected_observation_ids
            or bindings["execution_oracle_assertion_ids"].get(capability_id)
            != expected_assertion_ids
            or bindings["execution_oracle_fixture_sha256"].get(capability_id)
            != fixture_sha
            or bindings["execution_oracle_row_sha256"].get(capability_id)
            != sha256(canonical_bytes(oracle))
        ):
            raise SuccessorError(
                f"aggregate oracle result binding drift: {capability_id}"
            )
        indexed[capability_id] = result
    if (
        set(bindings["execution_oracle_observation_ids"]) != set(target_ids)
        or set(bindings["execution_oracle_assertion_ids"]) != set(target_ids)
        or set(bindings["execution_oracle_fixture_sha256"]) != set(target_ids)
        or set(bindings["execution_oracle_row_sha256"]) != set(target_ids)
    ):
        raise SuccessorError("aggregate binding maps contain an undeclared capability")

    expected_environment = {
        "distributions": contract["environment"]["expected_distributions"],
        "machine": "aarch64",
        "offline_cache_verified": True,
        "openusd": "26.5",
        "python": contract["environment"]["python"],
    }
    if aggregate["environment"] != expected_environment:
        raise SuccessorError("aggregate exact offline environment drift")
    if aggregate["cleanup"] != {
        "repository_mutations": 0,
        "root_removed": True,
        "sibling_names_unchanged": True,
    }:
        raise SuccessorError("aggregate cleanup envelope did not pass exactly")
    confinement = aggregate["confinement"]
    trace = confinement.get("command_trace")
    if (
        set(confinement)
        != {
            "command_count",
            "command_trace",
            "docker_calls",
            "downloads",
            "model_accesses",
            "network_boundary",
            "network_calls",
            "service_lifecycle_calls",
            "warehouse_sample_accesses",
        }
        or not isinstance(trace, list)
        or confinement["command_count"] != len(trace)
        or confinement["command_count"] != 75
        or any(
            set(row) != {"argument_count", "program", "returncode"}
            or row["program"] not in {"bash", "ffmpeg", "ffprobe", "python"}
            or type(row["argument_count"]) is not int
            or row["argument_count"] < 1
            or type(row["returncode"]) is not int
            for row in trace
        )
        or any(
            confinement[key] != 0
            for key in (
                "docker_calls",
                "downloads",
                "model_accesses",
                "network_calls",
                "service_lifecycle_calls",
                "warehouse_sample_accesses",
            )
        )
        or confinement["network_boundary"]
        != "proxy-free digest-locked local command allowlist; tools contain no network operation"
    ):
        raise SuccessorError("aggregate zero-confinement envelope drift")
    if aggregate["promotion"] != {
        "development_smoke_only": False,
        "eligible_capability_ids": target_ids,
        "family_id": "synthetic-data-tools",
        "ledger_mutation_performed": False,
        "receipt_is_runtime_evidence": True,
        "requires_separate_reviewed_metadata_integration": True,
    }:
        raise SuccessorError("aggregate promotion boundary drift")
    return indexed


def derive_receipts(
    aggregate_results: dict[str, dict[str, Any]],
    oracles: dict[str, dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    expected_target = {
        key: target[key]
        for key in ("product_version", "ga_commit", "main_commit", "captured_on")
    }
    for capability_id, _, _, _ in TARGETS:
        oracle = oracles[capability_id]
        result = aggregate_results[capability_id]
        result_sha = sha256(canonical_bytes(result))
        common = {
            "aggregate_receipt_sha256": AGGREGATE_SHA256,
            "capability_result_sha256": result_sha,
        }
        observations = []
        for observation in oracle["expected_observations"]:
            observation_id = observation["id"]
            if observation_id == "contract_identity":
                value = {
                    **common,
                    "checkout_head": CHECKOUT_HEAD,
                    "contract_sha256": RUNTIME_CONTRACT[1],
                    "oracle_row_sha256": sha256(canonical_bytes(oracle)),
                }
            elif observation_id == "semantic_result":
                value = {
                    **common,
                    "adjacent_negatives_sha256": sha256(
                        canonical_bytes(result["adjacent_negatives"])
                    ),
                    "positive_observations_sha256": sha256(
                        canonical_bytes(result["positive_observations"])
                    ),
                }
            elif observation_id == "deterministic_output":
                value = {
                    **common,
                    "independent_runs": result["independent_runs"],
                    "run_output_sha256": result["run_output_sha256"],
                }
            else:
                raise SuccessorError(f"unsupported observation: {observation_id}")
            observations.append(
                {"id": observation_id, "result": "pass", "value": value}
            )
        assertions = []
        passed_assertions = {
            row["assertion_id"]: row["passed"] for row in result["assertion_results"]
        }
        for required in oracle["assertions"]:
            if passed_assertions.get(required["id"]) is not True:
                raise SuccessorError(
                    f"aggregate assertion did not pass: {required['id']}"
                )
            observed = (
                required["expected"] if required["operator"] == "equals" else True
            )
            assertions.append(
                {
                    **copy.deepcopy(required),
                    "observed": observed,
                    "result": "pass",
                }
            )
        cleanup = oracle["cleanup"]
        receipts[capability_id] = {
            "schema_version": 1,
            "capability_id": capability_id,
            "oracle_id": oracle["oracle_id"],
            "oracle_sha256": sha256(canonical_bytes(oracle)),
            "result": "passed_current",
            "target": expected_target,
            "scenario_ids": oracle["reviewed_scenario_ids"],
            "fixture": {
                "id": oracle["fixture"]["id"],
                "path": oracle["fixture"]["materialization"]["path"],
                "sha256": oracle["fixture"]["materialization"]["sha256"],
            },
            "observations": observations,
            "assertions": assertions,
            "cleanup": {
                "result": "pass",
                "mutation": cleanup["mutation"],
                "targets": cleanup["targets"],
                "allowlist": cleanup["allowlist"],
                "pre_state_captured": True,
                "postconditions": [
                    {"description": description, "result": "pass"}
                    for description in cleanup["postconditions"]
                ],
            },
        }
    return receipts


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


def refresh_claim_hashes(ledger: dict[str, Any]) -> None:
    for source in ledger["sources"]:
        claims = []
        for capability in ledger["capabilities"]:
            for claim in capability["source_claims"]:
                if claim["source_id"] == source["id"]:
                    claims.append(
                        {
                            "capability_id": capability["id"],
                            "locator": claim["locator"],
                            "contract": capability["contract"],
                        }
                    )
        if not claims:
            raise SuccessorError(f"source has no claims: {source['id']}")
        canonical_claims = sorted(canonical_bytes(claim).decode() for claim in claims)
        source["claim_set_sha256"] = sha256(canonical_bytes(canonical_claims))


def _ledger_baseline() -> dict[str, Any]:
    current_ledger = load_locked(CURRENT_LEDGER)
    selected_ledger = load_locked(SELECTED_LEDGER)
    if (
        len(current_ledger["capabilities"]) != 289
        or len(selected_ledger["capabilities"]) != 500
    ):
        raise SuccessorError("current/selected ledger denominator drift")
    current_ids = [row["id"] for row in current_ledger["capabilities"]]
    selected_ids = [row["id"] for row in selected_ledger["capabilities"]]
    if current_ids != selected_ids[:289] or len(set(selected_ids)) != 500:
        raise SuccessorError("current 289-row ledger prefix identity/order drift")
    selected_suffix = copy.deepcopy(selected_ledger["capabilities"][289:])
    ledger_baseline: dict[str, Any] = copy.deepcopy(selected_ledger)
    ledger_baseline["capabilities"][:289] = copy.deepcopy(
        current_ledger["capabilities"]
    )
    # The live 289-row input is already promoted. Reconstruct the exact review
    # baseline without rolling back any current contract/source field: only the
    # three promotion-owned fields come from the selected unpromoted ledger.
    selected_rows = {row["id"]: row for row in selected_ledger["capabilities"][:289]}
    target_ids = set(target_ids_in_order())
    for row in ledger_baseline["capabilities"][:289]:
        if row["id"] not in target_ids:
            continue
        old = selected_rows[row["id"]]
        row["runtime_state"] = old["runtime_state"]
        row["gap"] = old["gap"]
        row.pop("runtime_evidence", None)
    refresh_claim_hashes(ledger_baseline)
    if ledger_baseline["capabilities"][289:] != selected_suffix:
        raise SuccessorError("selected 211-row ledger suffix changed during rebase")
    return ledger_baseline


def derive_promotion() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    _, future_oracle_document, fixtures = derive()
    future_oracles = {
        row["capability_id"]: row for row in future_oracle_document["oracles"]
    }
    contract = load_locked(RUNTIME_CONTRACT)
    aggregate = load_locked(AGGREGATE_RECEIPT)
    aggregate_results = validate_aggregate(
        aggregate,
        load_locked(RUNTIME_RESULT_SCHEMA),
        contract,
        future_oracles,
        fixtures,
    )

    ledger_baseline = _ledger_baseline()

    receipts = derive_receipts(
        aggregate_results, future_oracles, ledger_baseline["target"]
    )
    ledger = copy.deepcopy(ledger_baseline)
    target_ids = {row[0] for row in TARGETS}
    found: set[str] = set()
    for row in ledger["capabilities"]:
        capability_id = row["id"]
        if capability_id not in target_ids:
            continue
        found.add(capability_id)
        receipt = receipts[capability_id]
        receipt_sha = sha256(encoded(receipt))
        row["runtime_state"] = "passed_current"
        row["gap"] = FINAL_GAP
        row["runtime_evidence"] = [
            {"path": receipt_relative(capability_id), "sha256": receipt_sha}
        ]
    if found != target_ids:
        raise SuccessorError("rebased selected ledger lacks exact target set")
    refresh_claim_hashes(ledger)

    manifest_baseline = load_locked(SELECTED_MANIFEST)
    manifest = copy.deepcopy(manifest_baseline)
    manifest_targets = [
        row for row in manifest["features"] if row["id"] == "synthetic-data-tools"
    ]
    if len(manifest_targets) != 1:
        raise SuccessorError("selected manifest synthetic family identity drift")
    feature = manifest_targets[0]
    feature["runtime_state"] = "passed_current"
    feature["gap"] = FINAL_FAMILY_GAP
    feature["thor_evidence"] = [
        *feature["thor_evidence"],
        AGGREGATE_RECEIPT[0],
        *(receipt_relative(capability_id) for capability_id in target_ids_in_order()),
        str(OUTPUT.relative_to(REPO_ROOT)),
        str((PACKAGE / "EVIDENCE.md").relative_to(REPO_ROOT)),
    ]
    validate_promotion(
        ledger_baseline,
        ledger,
        manifest_baseline,
        manifest,
        receipts,
        future_oracle_document,
        load_locked(OFFICIAL_SCHEMA),
    )
    # Loading the selected acceptance document proves its locked bytes remain the
    # unchanged acceptance input; this successor deliberately emits no replacement.
    load_locked(SELECTED_ACCEPTANCE)
    return ledger, manifest, receipts, future_oracle_document


def target_ids_in_order() -> list[str]:
    return [row[0] for row in TARGETS]


def validate_official_receipt(
    capability: dict[str, Any],
    oracle: dict[str, Any],
    receipt: dict[str, Any],
    target: dict[str, Any],
) -> None:
    expected_keys = {
        "schema_version",
        "capability_id",
        "oracle_id",
        "oracle_sha256",
        "result",
        "target",
        "scenario_ids",
        "fixture",
        "observations",
        "assertions",
        "cleanup",
    }
    expected_target = {
        key: target[key]
        for key in ("product_version", "ga_commit", "main_commit", "captured_on")
    }
    expected_binding = {
        key: capability[key]
        for key in (
            "feature_id",
            "kind",
            "title",
            "source_claims",
            "acceptance_class",
            "thor_state",
            "runtime_state",
            "contract",
            "gap",
        )
    }
    materialization = oracle["fixture"]["materialization"]
    if (
        set(receipt) != expected_keys
        or receipt["schema_version"] != 1
        or receipt["capability_id"] != capability["id"]
        or receipt["oracle_id"] != oracle["oracle_id"]
        or receipt["oracle_sha256"] != sha256(canonical_bytes(oracle))
        or receipt["result"] != "passed_current"
        or receipt["target"] != expected_target
        or receipt["scenario_ids"] != oracle["reviewed_scenario_ids"]
        or set(receipt["scenario_ids"])
        != set(capability["scenario_ids"]) | {oracle["oracle_id"]}
        or receipt["fixture"]
        != {
            "id": oracle["fixture"]["id"],
            "path": materialization["path"],
            "sha256": materialization["sha256"],
        }
        or oracle["ledger_binding"] != expected_binding
        or oracle["acceptance_readiness"]
        != {"blockers": [], "classification": "executor_ready"}
    ):
        raise SuccessorError(f"official receipt metadata drift: {capability['id']}")
    expected_observation_ids = [row["id"] for row in oracle["expected_observations"]]
    if (
        [row.get("id") for row in receipt["observations"]] != expected_observation_ids
        or any(
            set(row) != {"id", "result", "value"} or row["result"] != "pass"
            for row in receipt["observations"]
        )
        or any(
            row["value"].get("aggregate_receipt_sha256") != AGGREGATE_SHA256
            or re.fullmatch(
                r"[0-9a-f]{64}", row["value"].get("capability_result_sha256", "")
            )
            is None
            for row in receipt["observations"]
        )
    ):
        raise SuccessorError(f"official receipt observation drift: {capability['id']}")
    if len(receipt["assertions"]) != len(oracle["assertions"]):
        raise SuccessorError(
            f"official receipt assertion count drift: {capability['id']}"
        )
    for required, observed in zip(
        oracle["assertions"], receipt["assertions"], strict=True
    ):
        if (
            set(observed)
            != {"id", "observation", "operator", "expected", "observed", "result"}
            or observed["id"] != required["id"]
            or observed["observation"] != required["observation"]
            or observed["operator"] != required["operator"]
            or observed["expected"] != required["expected"]
            or observed["result"] != "pass"
            or (
                required["operator"] == "equals"
                and observed["observed"] != required["expected"]
            )
            or (
                required["operator"] == "recorded_pass"
                and observed["observed"] is not True
            )
        ):
            raise SuccessorError(
                f"official receipt assertion drift: {capability['id']}"
            )
    cleanup = oracle["cleanup"]
    if receipt["cleanup"] != {
        "result": "pass",
        "mutation": cleanup["mutation"],
        "targets": cleanup["targets"],
        "allowlist": cleanup["allowlist"],
        "pre_state_captured": True,
        "postconditions": [
            {"description": description, "result": "pass"}
            for description in cleanup["postconditions"]
        ],
    }:
        raise SuccessorError(f"official receipt cleanup drift: {capability['id']}")


def validate_promotion(
    ledger_baseline: dict[str, Any],
    ledger: dict[str, Any],
    manifest_baseline: dict[str, Any],
    manifest: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    oracle_document: dict[str, Any],
    official_schema: dict[str, Any],
) -> dict[str, int]:
    errors = sorted(
        Draft202012Validator(official_schema).iter_errors(ledger),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        raise SuccessorError(f"official ledger schema failure: {errors[0].message}")
    before = {row["id"]: row for row in ledger_baseline["capabilities"]}
    after = {row["id"]: row for row in ledger["capabilities"]}
    target_ids = set(target_ids_in_order())
    if len(after) != 500 or list(after) != list(before) or set(receipts) != target_ids:
        raise SuccessorError("promotion denominator, order, or receipt set drift")
    changed = {
        capability_id
        for capability_id in before
        if canonical_bytes(before[capability_id])
        != canonical_bytes(after[capability_id])
    }
    if changed != target_ids:
        raise SuccessorError("ledger changed outside exact four Synthetic Data rows")
    oracle_rows = {row["capability_id"]: row for row in oracle_document["oracles"]}
    for capability_id in target_ids_in_order():
        capability = after[capability_id]
        receipt = receipts[capability_id]
        if (
            capability["runtime_state"] != "passed_current"
            or capability["gap"] != FINAL_GAP
            or capability["runtime_evidence"]
            != [
                {
                    "path": receipt_relative(capability_id),
                    "sha256": sha256(encoded(receipt)),
                }
            ]
        ):
            raise SuccessorError(f"ledger promotion row drift: {capability_id}")
        validate_official_receipt(
            capability, oracle_rows[capability_id], receipt, ledger["target"]
        )
    before_features = {row["id"]: row for row in manifest_baseline["features"]}
    after_features = {row["id"]: row for row in manifest["features"]}
    feature_changed = {
        feature_id
        for feature_id in before_features
        if canonical_bytes(before_features[feature_id])
        != canonical_bytes(after_features[feature_id])
    }
    if (
        len(after_features) != len(before_features)
        or list(after_features) != list(before_features)
        or feature_changed != {"synthetic-data-tools"}
    ):
        raise SuccessorError("manifest changed outside exact Synthetic Data family")
    synthetic = after_features["synthetic-data-tools"]
    if (
        synthetic["runtime_state"] != "passed_current"
        or synthetic["gap"] != FINAL_FAMILY_GAP
        or synthetic["official_capability_ids"] != target_ids_in_order()
        or len(synthetic["thor_evidence"])
        != len(before_features["synthetic-data-tools"]["thor_evidence"]) + 7
        or len(set(synthetic["thor_evidence"])) != len(synthetic["thor_evidence"])
    ):
        raise SuccessorError("synthetic manifest aggregate drift")
    states = Counter(row["runtime_state"] for row in ledger["capabilities"])
    if (
        states["passed_current"]
        != Counter(row["runtime_state"] for row in ledger_baseline["capabilities"])[
            "passed_current"
        ]
        + 4
    ):
        raise SuccessorError("exact passed-current count did not advance by four")
    return {
        "official_capabilities": len(after),
        "official_receipts": len(receipts),
        "manifest_features": len(after_features),
        "passed_current": states["passed_current"],
        "preserved_ledger_rows": len(after) - len(target_ids),
        "preserved_manifest_features": len(after_features) - 1,
        "selected_suffix": len(ledger["capabilities"][289:]),
    }


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


def check_output(path: Path, derived: bytes, expected: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise SuccessorError(f"unfinalized checked output digest: {path.name}")
    payload = repo_file(str(path.relative_to(REPO_ROOT))).read_bytes()
    if payload != derived or sha256(payload) != expected:
        raise SuccessorError(f"checked output differs from derivation: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the deterministic checked output"
    )
    args = parser.parse_args(argv)
    try:
        baseline, output, fixtures = derive()
        ledger, manifest, receipts, promoted_oracles = derive_promotion()
        if promoted_oracles != output:
            raise SuccessorError("promotion and oracle derivations differ")
        payload = encoded(output)
        ledger_payload = encoded(ledger)
        manifest_payload = encoded(manifest)
        if args.write:
            OUTPUT.write_bytes(payload)
            LEDGER_OUTPUT.write_bytes(ledger_payload)
            MANIFEST_OUTPUT.write_bytes(manifest_payload)
        else:
            check_output(OUTPUT, payload, EXPECTED_OUTPUT_SHA256)
            check_output(LEDGER_OUTPUT, ledger_payload, EXPECTED_LEDGER_SHA256)
            check_output(MANIFEST_OUTPUT, manifest_payload, EXPECTED_MANIFEST_SHA256)
            if set(EXPECTED_RECEIPT_SHA256) != set(target_ids_in_order()):
                raise SuccessorError(
                    "checked official receipt digest set is incomplete"
                )
            for capability_id, receipt in receipts.items():
                check_output(
                    REPO_ROOT / receipt_relative(capability_id),
                    encoded(receipt),
                    EXPECTED_RECEIPT_SHA256[capability_id],
                )
        counts = validate(baseline, output, load_locked(ORACLE_SCHEMA), fixtures)
        counts.update(
            validate_promotion(
                # Re-derive the rebased unpromoted ledger and source manifest for
                # a final exact-delta check independent of checked output bytes.
                _ledger_baseline(),
                ledger,
                load_locked(SELECTED_MANIFEST),
                manifest,
                receipts,
                output,
                load_locked(OFFICIAL_SCHEMA),
            )
        )
        print(json.dumps({"status": "pass", **counts}, sort_keys=True))
        return 0
    except (SuccessorError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
