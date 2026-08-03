#!/usr/bin/env python3
"""Compile the staged SpatialAI 01/04/05 executor-ready oracle projection."""

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
ORACLE_OUTPUT = PACKAGE / "post-state-capability-oracles.json"
LEDGER_OUTPUT = PACKAGE / "post-state-official-capabilities.json"
MAX_JSON_BYTES = 8_000_000

PRODUCER_COMMIT = "c06932bd641b00ac67df4508e5831644544f9ac1"
CURRENT_ORACLES = (
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "856a93bf11bbe4cb77b315fe5ae1884ccedb7dc83107f4142c6721e78688308c",
)
CURRENT_LEDGER = (
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "834bb40b576d9e9e546cecb3bdb866993b7be7fd3bf9d5e9e19a0d852d4e4e39",
)
SELECTED_ORACLES = (
    "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/post-state-capability-oracles.json",
    "53fe977aa208cdc78604e214817dac7d3683edea4402b160b9d3cf46571b49e3",
)
SELECTED_LEDGER = (
    "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/post-state-official-capabilities.json",
    "315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229",
)
ORACLE_SCHEMA = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.schema.json",
    "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
)
LEDGER_SCHEMA = (
    "deploy/docker/thor-local/parity/official-capabilities.schema.json",
    "71f1e0f1d820c3809ea3b55abb504071321f61c6e36978226dd10108c7b2384b",
)
INTERFACE = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-successor/runtime-interface.json",
    "191e883c6bf5d2b1331d2e4555aded50d202dbe2070f7ddfc95c3d7bbf88f2e3",
)
INTERFACE_SCHEMA = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-successor/runtime-interface.schema.json",
    "048cf87b58a5e21763074c77378d3422c9797f3f2bcb0e85987048df7698a831",
)
EXPECTED_ORACLE_OUTPUT_SHA256 = (
    "c2b8d584b4bb00f42d6337bbad31038d016fe02a7cfbf92ac747f42075bdc6c0"
)
EXPECTED_LEDGER_OUTPUT_SHA256 = (
    "315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229"
)

TARGET_IDS = (
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
)
SPATIAL_IDS = tuple(
    f"manifest-entry.spatial-ai-utils.0{index}-{suffix}"
    for index, suffix in enumerate(
        (
            "calibration-and-camera-grouping",
            "3d-2d-geometry",
            "multiview-visualization",
            "detection-map",
            "tracking-hota-clear-identity-count",
            "nvschema-conversion",
            "video-frame-tools",
            "aws-gcs-validation",
        )
    )
)
EXPECTED_ADAPTERS = {
    TARGET_IDS[0]: "geometry_projection",
    TARGET_IDS[1]: "tracking_metrics",
    TARGET_IDS[2]: "nvschema_conversion",
}
EXPECTED_NEGATIVES = {
    TARGET_IDS[0]: [
        "legacy-7dof",
        "fully-offscreen",
        "missing-intrinsic",
        "scalar-box",
        "malformed-world2img",
    ],
    TARGET_IDS[1]: [
        "identity-switch",
        "empty-tracker",
        "empty-ground-truth",
        "similarity-shape-mismatch",
        "missing-required-count",
    ],
    TARGET_IDS[2]: [
        "unknown-class",
        "missing-results",
        "strict-short-coordinates",
        "invalid-output-format",
        "malformed-frame-token",
    ],
}
EXPECTED_PRODUCT_COUNTS = {
    TARGET_IDS[0]: {
        "boxes.box3d_to_corners": 4,
        "projection.project_boxes_3d_to_2d": 4,
        "projection.project_points_3d_to_image": 1,
    },
    TARGET_IDS[1]: {
        "tracking.CLEAR.eval_sequence": 4,
        "tracking.Count.eval_sequence": 4,
        "tracking.HOTA.eval_sequence": 4,
        "tracking.Identity.eval_sequence": 4,
    },
    TARGET_IDS[2]: {
        "nvschema.convert_sparse4d_to_nvschema": 5,
        "nvschema.load_nvschema": 4,
    },
}
FINAL_GAP = (
    "No known gap: the committed target-bound offline SpatialAI runtime producer "
    "covers two positive runs, five named adjacent cases, deterministic output, "
    "exact cleanup, and observed imported-product calls without the Warehouse "
    "sample bundle. Runtime evidence remains a separate, non-promoting stage."
)


class ProjectionError(RuntimeError):
    """A source lock, interface, schema, or exact-delta invariant failed."""


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


def schema_validate(value: Any, schema: dict[str, Any], label: str) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        path = "/".join(map(str, errors[0].absolute_path)) or "<root>"
        raise ProjectionError(f"{label} schema failure at {path}: {errors[0].message}")


def load_interface() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    interface = load_locked(INTERFACE)
    schema_validate(interface, load_locked(INTERFACE_SCHEMA), "runtime interface")
    producer = interface["producer"]
    if producer["commit"] != PRODUCER_COMMIT:
        raise ProjectionError("producer commit drift")
    for role, path in interface["roles"].items():
        if path != producer["executor"]["path"]:
            raise ProjectionError(f"producer role binding drift: {role}")
    for name in ("contract", "contract_schema", "executor", "result_schema"):
        lock = producer[name]
        if sha256(repo_file(lock["path"]).read_bytes()) != lock["sha256"]:
            raise ProjectionError(f"producer source lock drift: {name}")

    contract = strict_json(
        repo_file(producer["contract"]["path"]).read_bytes(), "producer contract"
    )
    contract_schema = strict_json(
        repo_file(producer["contract_schema"]["path"]).read_bytes(),
        "producer contract schema",
    )
    result_schema = strict_json(
        repo_file(producer["result_schema"]["path"]).read_bytes(),
        "producer result schema",
    )
    schema_validate(contract, contract_schema, "producer contract")
    Draft202012Validator.check_schema(result_schema)
    policy = contract["policy"]
    if (
        contract["environment"]
        != {
            "platform": "linux-aarch64",
            "python_major_minor": "3.12",
            "required_modules": contract["environment"]["required_modules"],
            "dependency_policy": "preinstalled_only_no_bootstrap",
        }
        or interface["target_environment"]
        != {"platform": "linux-aarch64", "python_major_minor": "3.12"}
        or policy["independent_positive_runs"] != 2
        or policy["adjacent_negative_count_per_capability"] != 5
        or policy["target_case_actions_per_capability"] != 7
        or policy["product_execution_deadline_seconds"] != 900
        or policy["warehouse_sample_bundle"] != "excluded"
        or any(
            policy[key]
            for key in (
                "network_allowed",
                "docker_allowed",
                "service_lifecycle_allowed",
                "model_access_allowed",
                "downloads_allowed",
                "credentials_allowed",
            )
        )
    ):
        raise ProjectionError("producer target/policy boundary drift")
    if (
        policy["external_provider_entry"] != SPATIAL_IDS[7]
        or policy["external_provider_treatment"]
        != "excluded_external_optional_not_applicable"
        or interface["projection"]
        != {
            "canonical_mutation": False,
            "evidence_added": False,
            "ledger_rows_changed": 0,
            "oracle_rows_changed": 3,
            "promotion_performed": False,
            "selected_oracle_state": "open_unexecuted",
            "selected_readiness": "executor_ready",
        }
    ):
        raise ProjectionError("projection/external-provider boundary drift")

    contract_rows = {row["capability_id"]: row for row in contract["capabilities"]}
    if list(contract_rows) != list(SPATIAL_IDS[:7]):
        raise ProjectionError("producer seven-capability identity/order drift")
    if contract["target"] != {
        "upstream_repository": "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization",
        "upstream_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
        "product_version": "3.2.1",
        "current_oracle_document": CURRENT_ORACLES[0],
        "current_ledger_document": CURRENT_LEDGER[0],
    }:
        raise ProjectionError("producer upstream/current-document target drift")
    current_oracle_rows = {
        row["capability_id"]: row for row in load_locked(CURRENT_ORACLES)["oracles"]
    }
    current_ledger_rows = {
        row["id"]: row for row in load_locked(CURRENT_LEDGER)["capabilities"]
    }
    for capability_id, runtime in contract_rows.items():
        if (
            sha256(canonical_bytes(current_oracle_rows[capability_id]))
            != runtime["current_oracle_sha256"]
            or sha256(canonical_bytes(current_ledger_rows[capability_id]))
            != runtime["current_ledger_row_sha256"]
        ):
            raise ProjectionError(
                f"producer current metadata binding drift: {capability_id}"
            )
    bindings: dict[str, dict[str, Any]] = {}
    if [row["capability_id"] for row in interface["capabilities"]] != list(TARGET_IDS):
        raise ProjectionError("interface target identity/order drift")
    for row in interface["capabilities"]:
        capability_id = row["capability_id"]
        runtime = contract_rows[capability_id]
        if (
            row["oracle_id"] != runtime["oracle_id"]
            or row["adapter"] != EXPECTED_ADAPTERS[capability_id]
            or row["adapter"] != runtime["adapter"]
            or row["fixture_manifest"] != runtime["fixture_manifest"]
            or row["adjacent_negative_case_ids"] != EXPECTED_NEGATIVES[capability_id]
            or row["product_function_counts"] != EXPECTED_PRODUCT_COUNTS[capability_id]
            or row["positive_runs"] != 2
            or row["max_actions"] != 7
            or row["max_requests"] != 7
        ):
            raise ProjectionError(f"runtime interface binding drift: {capability_id}")
        fixture_lock = row["fixture_manifest"]
        fixture_payload = repo_file(fixture_lock["path"]).read_bytes()
        if sha256(fixture_payload) != fixture_lock["sha256"]:
            raise ProjectionError(f"fixture digest drift: {capability_id}")
        fixture = strict_json(fixture_payload, fixture_lock["path"])
        if fixture.get("fixture_id") != row["fixture_payload_id"]:
            raise ProjectionError(f"fixture payload identity drift: {capability_id}")
        for source in runtime["source_controls"]:
            if sha256(repo_file(source["path"]).read_bytes()) != source["sha256"]:
                raise ProjectionError(f"product source-control drift: {source['path']}")
        bindings[capability_id] = {**copy.deepcopy(row), "runtime": runtime}
    accounting = interface["aggregate_execution_accounting"]
    if accounting != {
        "bounded_capability_actions": sum(
            row["max_actions"] for row in interface["capabilities"]
        ),
        "requests": sum(row["max_requests"] for row in interface["capabilities"]),
        "imported_product_function_invocations": sum(
            sum(row["product_function_counts"].values())
            for row in interface["capabilities"]
        ),
    }:
        raise ProjectionError("aggregate execution accounting drift")
    return interface, bindings


def rebase_500(
    current: dict[str, Any],
    selected: dict[str, Any],
    collection: str,
    identity: str,
) -> dict[str, Any]:
    current_rows = current[collection]
    selected_rows = selected[collection]
    if len(current_rows) != 289 or len(selected_rows) != 500:
        raise ProjectionError(f"{collection} denominator drift")
    current_ids = [row[identity] for row in current_rows]
    selected_ids = [row[identity] for row in selected_rows]
    if (
        current_ids != selected_ids[:289]
        or len(set(selected_ids)) != 500
        or len(selected_rows[289:]) != 211
    ):
        raise ProjectionError(f"{collection} prefix/suffix identity drift")
    baseline = copy.deepcopy(selected)
    suffix = copy.deepcopy(selected_rows[289:])
    baseline[collection][:289] = copy.deepcopy(current_rows)
    if baseline[collection][289:] != suffix:
        raise ProjectionError(f"{collection} selected suffix changed during rebase")
    return baseline


def projected_contract(
    source: dict[str, Any], runtime: dict[str, Any]
) -> dict[str, Any]:
    contract = copy.deepcopy(source["ledger_binding"]["contract"])
    contract["source_controls"] = copy.deepcopy(runtime["source_controls"])
    if "required_metrics" in contract:
        contract["required_metrics"] = copy.deepcopy(runtime["required_semantics"])
    elif "required_semantics" in contract:
        contract["required_semantics"] = copy.deepcopy(runtime["required_semantics"])
    else:
        raise ProjectionError(
            f"target contract semantic key absent: {source['capability_id']}"
        )
    return contract


def expected_target(
    source: dict[str, Any], binding: dict[str, Any], executor: str
) -> dict[str, Any]:
    expected = copy.deepcopy(source)
    contract = projected_contract(source, binding["runtime"])
    expected["ledger_binding"]["runtime_state"] = "passed_current"
    expected["ledger_binding"]["gap"] = FINAL_GAP
    expected["ledger_binding"]["contract"] = copy.deepcopy(contract)
    expected["fixture"]["input"]["contract"] = copy.deepcopy(contract)
    expected["fixture"]["input"]["namespace"] = binding["runtime_namespace"]
    expected["fixture"]["materialization"] = {
        "generator": executor,
        "path": binding["fixture_manifest"]["path"],
        "sha256": binding["fixture_manifest"]["sha256"],
    }
    for assertion in expected["assertions"]:
        prefix = "contract_identity/contract/"
        observation = assertion["observation"]
        if observation.startswith(prefix):
            key = observation.removeprefix(prefix)
            if key in contract:
                assertion["expected"] = copy.deepcopy(contract[key])
    workload = {
        "calculated_max_requests": binding["max_requests"],
        "overhead_requests": 0,
        "phases": ["positive_run_1", "positive_run_2", "adjacent_negative"],
        "requests_per_unit": binding["max_requests"],
        "units": 1,
    }
    expected["execution_bounds"]["executor"] = executor
    expected["execution_bounds"]["collectors"] = [executor]
    expected["execution_bounds"]["max_actions"] = binding["max_actions"]
    expected["execution_bounds"]["max_requests"] = binding["max_requests"]
    expected["execution_bounds"]["workload"] = workload
    expected["cleanup"]["allowlist"] = [binding["runtime_namespace"]]
    expected["cleanup"]["targets"] = [binding["runtime_namespace"]]
    expected["cleanup"]["executor"] = executor
    expected["cleanup"]["postcondition_collectors"] = [executor]
    expected["acceptance_readiness"] = {
        "blockers": [],
        "classification": "executor_ready",
    }
    return expected


def derive() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    current_oracles = load_locked(CURRENT_ORACLES)
    selected_oracles = load_locked(SELECTED_ORACLES)
    current_ledger = load_locked(CURRENT_LEDGER)
    selected_ledger = load_locked(SELECTED_LEDGER)
    interface, bindings = load_interface()
    oracle_baseline = rebase_500(
        current_oracles, selected_oracles, "oracles", "capability_id"
    )
    ledger_baseline = rebase_500(current_ledger, selected_ledger, "capabilities", "id")
    output = copy.deepcopy(oracle_baseline)
    executor = interface["producer"]["executor"]["path"]
    found: list[str] = []
    for index, row in enumerate(output["oracles"]):
        capability_id = row["capability_id"]
        if capability_id in bindings:
            found.append(capability_id)
            output["oracles"][index] = expected_target(
                row, bindings[capability_id], executor
            )
    if found != list(TARGET_IDS):
        raise ProjectionError("selected Metadata-500 target identity/order drift")
    ledger_output = copy.deepcopy(ledger_baseline)
    validate(oracle_baseline, output, ledger_baseline, ledger_output, bindings)
    return oracle_baseline, output, ledger_baseline, ledger_output, bindings


def validate(
    oracle_baseline: dict[str, Any],
    oracle_output: dict[str, Any],
    ledger_baseline: dict[str, Any],
    ledger_output: dict[str, Any],
    bindings: dict[str, dict[str, Any]],
) -> dict[str, int]:
    schema_validate(oracle_output, load_locked(ORACLE_SCHEMA), "oracle output")
    schema_validate(ledger_output, load_locked(LEDGER_SCHEMA), "ledger output")
    before = {row["capability_id"]: row for row in oracle_baseline["oracles"]}
    after = {row["capability_id"]: row for row in oracle_output["oracles"]}
    if (
        len(before) != 500
        or list(before) != list(after)
        or oracle_output["policy"] != oracle_baseline["policy"]
        or oracle_output["target"] != oracle_baseline["target"]
    ):
        raise ProjectionError("oracle denominator, order, policy, or target drift")
    executor = load_locked(INTERFACE)["producer"]["executor"]["path"]
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
        if (
            new["current_state"] != "open_unexecuted"
            or new["evidence"] != []
            or new["fixture"]["availability"] != old["fixture"]["availability"]
            or new["acceptance_readiness"]
            != {"blockers": [], "classification": "executor_ready"}
        ):
            raise ProjectionError(
                f"projection invented evidence/state: {capability_id}"
            )
    if changed != set(TARGET_IDS):
        raise ProjectionError("projection did not change exactly three target rows")
    if any(
        canonical_bytes(before[row]) != canonical_bytes(after[row])
        for row in SPATIAL_IDS
        if row not in TARGET_IDS
    ):
        raise ProjectionError("non-core SpatialAI row changed")

    ledger_before = {row["id"]: row for row in ledger_baseline["capabilities"]}
    ledger_after = {row["id"]: row for row in ledger_output["capabilities"]}
    if (
        len(ledger_before) != 500
        or list(ledger_before) != list(ledger_after)
        or ledger_output != ledger_baseline
    ):
        raise ProjectionError("ledger projection performed a promotion or row change")
    if (
        before[SPATIAL_IDS[7]] != after[SPATIAL_IDS[7]]
        or ledger_before[SPATIAL_IDS[7]] != ledger_after[SPATIAL_IDS[7]]
    ):
        raise ProjectionError("external provider entry 07 changed")
    return {
        "oracle_rows": len(after),
        "preserved_oracle_rows": len(after) - len(TARGET_IDS),
        "projected_executor_ready": len(TARGET_IDS),
        "projected_actions": sum(
            after[capability_id]["execution_bounds"]["max_actions"]
            for capability_id in TARGET_IDS
        ),
        "projected_requests": sum(
            after[capability_id]["execution_bounds"]["max_requests"]
            for capability_id in TARGET_IDS
        ),
        "projected_product_calls": sum(
            sum(binding["product_function_counts"].values())
            for binding in bindings.values()
        ),
        "runtime_evidence": sum(len(row["evidence"]) for row in after.values()),
        "ledger_rows": len(ledger_after),
        "preserved_ledger_rows": len(ledger_after),
        "promoted_ledger_rows": 0,
        "selected_suffix": len(oracle_output["oracles"][289:]),
        "external_provider_rows_changed": 0,
    }


def check_output(path: Path, derived: bytes, expected: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None or expected == "0" * 64:
        raise ProjectionError(f"unfinalized checked output digest: {path.name}")
    payload = repo_file(str(path.relative_to(REPO_ROOT))).read_bytes()
    if payload != derived or sha256(payload) != expected:
        raise ProjectionError(f"checked output differs from derivation: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write package-local deterministic outputs"
    )
    args = parser.parse_args(argv)
    try:
        (
            oracle_baseline,
            oracle_output,
            ledger_baseline,
            ledger_output,
            bindings,
        ) = derive()
        oracle_payload = encoded(oracle_output)
        ledger_payload = encoded(ledger_output)
        if args.write:
            ORACLE_OUTPUT.write_bytes(oracle_payload)
            LEDGER_OUTPUT.write_bytes(ledger_payload)
        else:
            check_output(ORACLE_OUTPUT, oracle_payload, EXPECTED_ORACLE_OUTPUT_SHA256)
            check_output(LEDGER_OUTPUT, ledger_payload, EXPECTED_LEDGER_OUTPUT_SHA256)
        counts = validate(
            oracle_baseline,
            oracle_output,
            ledger_baseline,
            ledger_output,
            bindings,
        )
        print(json.dumps({"status": "pass", **counts}, sort_keys=True))
        return 0
    except (
        ProjectionError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
