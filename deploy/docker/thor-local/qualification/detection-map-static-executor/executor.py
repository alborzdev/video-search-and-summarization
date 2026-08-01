#!/usr/bin/env python3
"""Fail-closed candidate receipt for the advertised ``detection mAP`` literal.

This lane executes a bounded, deterministic AP semantic oracle on custom tiny
data and verifies the checked-in production evaluator plus its real end-to-end
tests by exact digest and AST structure.  It deliberately does not claim that
the optional nuScenes-backed production evaluator ran on this host.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import tomllib
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
ENTRY_ID = "manifest-gap.spatial-ai-utils.03-detection-map"
MAX_INPUT_BYTES = 1_000_000
EXPECTED_CONTRACT_SHA256 = (
    "5ca96f6923dee872182ad6af782270d4df14cec17044eebbfd0121601b84bdbc"
)
EXPECTED_POLICY = {
    "candidate_only": True,
    "can_mark_passed_current": False,
    "official_capability_effect": "none_candidate_only",
    "runtime_evidence": [],
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "lifecycle_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "warehouse_sample_bundle": "excluded",
    "writes": "executor_owned_private_temporary_directory_only",
}
EXPECTED_SOURCE_PATHS = {
    "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/detection/evaluate.py",
    "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/detection/loaders.py",
    "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/detection/data_classes.py",
    "libs/analytics/spatialai-data-utils/tests/eval/detection/test_evaluate.py",
    "libs/analytics/spatialai-data-utils/release/pyproject.toml",
}


class QualificationError(RuntimeError):
    """A lock, safety boundary, semantic assertion, or output lock failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _repo_file(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    path = REPO_ROOT.joinpath(*pure.parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(f"repository input unavailable: {relative}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(
            f"repository input must be a regular non-symlink: {relative}"
        )
    resolved = path.resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise QualificationError(f"repository input escaped root: {relative}")
    if metadata.st_size > MAX_INPUT_BYTES:
        raise QualificationError(f"repository input exceeds size bound: {relative}")
    return path


def _read_repo_bytes(relative: str) -> bytes:
    data = _repo_file(relative).read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise QualificationError(f"repository input exceeds size bound: {relative}")
    return data


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        where = "/" + "/".join(str(part) for part in error.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {error.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise QualificationError(f"invalid JSON pointer: {pointer}")
    value = document
    try:
        for raw in pointer.split("/")[1:]:
            token = raw.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise QualificationError(f"unresolved JSON pointer: {pointer}") from exc
    return value


def _load_contract() -> dict[str, Any]:
    raw = CONTRACT_PATH.read_bytes()
    if _sha256(raw) != EXPECTED_CONTRACT_SHA256:
        raise QualificationError("contract lock mismatch")
    contract = _strict_json_bytes(raw, CONTRACT_PATH.name)
    _validate_schema(contract, CONTRACT_SCHEMA_PATH, "contract")
    if contract["policy"] != EXPECTED_POLICY:
        raise QualificationError("candidate-only safety policy drift")
    if contract["entry"]["entry_id"] != ENTRY_ID:
        raise QualificationError("entry binding drift")
    source_paths = {item["path"] for item in contract["source_locks"]}
    if source_paths != EXPECTED_SOURCE_PATHS:
        raise QualificationError("source-lock path set drift")
    return contract


def _verify_bindings(contract: dict[str, Any]) -> dict[str, str]:
    entry = contract["entry"]
    if (
        _sha256(_canonical_bytes(entry["advertised"]))
        != entry["advertised_canonical_sha256"]
    ):
        raise QualificationError("advertised canonical digest mismatch")
    if _sha256(entry["advertised"].encode("utf-8")) != entry["advertised_utf8_sha256"]:
        raise QualificationError("advertised UTF-8 digest mismatch")

    manifest_path = "deploy/docker/thor-local/parity/manifest.json"
    manifest = _strict_json_bytes(_read_repo_bytes(manifest_path), manifest_path)
    if _resolve_pointer(manifest, entry["manifest_pointer"]) != entry["advertised"]:
        raise QualificationError("live manifest advertised literal drift")

    plan_lock = contract["plan_binding"]
    raw_plan = _read_repo_bytes(plan_lock["path"])
    if _sha256(raw_plan) != plan_lock["raw_sha256"]:
        raise QualificationError("advertised gap plan raw lock mismatch")
    plan = _strict_json_bytes(raw_plan, plan_lock["path"])
    entries = [
        item for item in plan.get("entries", []) if item.get("entry_id") == ENTRY_ID
    ]
    if len(entries) != 1:
        raise QualificationError("plan must contain exactly one detection mAP entry")
    plan_entry = entries[0]
    if _sha256(_canonical_bytes(plan_entry)) != plan_lock["entry_canonical_sha256"]:
        raise QualificationError("plan entry canonical lock mismatch")
    if (
        plan_entry.get("manifest_pointer") != entry["manifest_pointer"]
        or plan_entry.get("advertised") != entry["advertised"]
        or plan_entry.get("required_oracle", {}).get("status") != "open_unexecuted"
        or plan_entry.get("runtime_evidence") != []
        or plan_entry.get("warehouse_scope")
        != {"custom_data_capability_in_scope": False, "sample_bundle_required": False}
    ):
        raise QualificationError("plan entry boundary drift")
    return {plan_lock["path"]: _sha256(raw_plan)}


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise QualificationError(f"expected one function definition: {name}")
    return matches[0]


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def _has_person_ap_one_assertion(function: ast.FunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Assert):
            continue
        rendered = ast.unparse(node.test).replace('"', "'")
        if "summary['mean_dist_aps']['Person'] == 1.0" in rendered:
            return True
    return False


def _verify_source_evidence(
    contract: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    locks = {item["path"]: item["sha256"] for item in contract["source_locks"]}
    observed: dict[str, str] = {}
    sources: dict[str, bytes] = {}
    for path, expected in locks.items():
        raw = _read_repo_bytes(path)
        actual = _sha256(raw)
        if actual != expected:
            raise QualificationError(f"source lock mismatch for {path}: {actual}")
        observed[path] = actual
        sources[path] = raw

    evaluate_path = next(path for path in locks if path.endswith("/evaluate.py"))
    loaders_path = next(path for path in locks if path.endswith("/loaders.py"))
    tests_path = next(path for path in locks if path.endswith("/test_evaluate.py"))
    pyproject_path = next(path for path in locks if path.endswith("/pyproject.toml"))
    try:
        evaluate_tree = ast.parse(sources[evaluate_path], filename=evaluate_path)
        loaders_tree = ast.parse(sources[loaders_path], filename=loaders_path)
        tests_tree = ast.parse(sources[tests_path], filename=tests_path)
    except SyntaxError as exc:
        raise QualificationError(
            "locked evaluator evidence is not valid Python"
        ) from exc

    evaluate_calls = _called_names(_function(evaluate_tree, "evaluate_detection"))
    if not {"accumulate", "calc_ap", "add_label_ap"}.issubset(evaluate_calls):
        raise QualificationError("production evaluate_detection AP call graph drift")
    save_function = _function(evaluate_tree, "save_detection_results")
    save_literals = {
        node.value
        for node in ast.walk(save_function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    if not {"metrics_summary.json", "metrics_details.json"}.issubset(save_literals):
        raise QualificationError("production detection result contract drift")
    loader_calls = _called_names(_function(loaders_tree, "load_boxes_from_jsonl"))
    if not {"EvalBoxes", "DetectionBox", "add_boxes"}.issubset(loader_calls):
        raise QualificationError("production JSONL detection loader call graph drift")

    test_names = (
        "test_evaluate_detection_per_bev_sensor_writes_outputs",
        "test_evaluate_detection_for_all_bev_sensors_creates_outputs",
    )
    test_functions = [_function(tests_tree, name) for name in test_names]
    expected_calls = ("_run_detection_per_sensor", "evaluate_detection_all_BEV_sensors")
    for function, expected_call in zip(test_functions, expected_calls, strict=True):
        if expected_call not in _called_names(function):
            raise QualificationError(
                f"integration test no longer calls {expected_call}"
            )
        if not _has_person_ap_one_assertion(function):
            raise QualificationError(
                f"integration test no longer asserts Person AP=1.0: {function.name}"
            )

    try:
        pyproject = tomllib.loads(sources[pyproject_path].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise QualificationError("locked pyproject is invalid") from exc
    eval_dependencies = (
        pyproject.get("project", {}).get("optional-dependencies", {}).get("eval")
    )
    if eval_dependencies != ["nuscenes-devkit==1.2.0", "motmetrics==1.4.0"]:
        raise QualificationError("optional eval dependency declaration drift")

    evidence = {
        "production_evaluator_functions": [
            "evaluate_detection",
            "save_detection_results",
            "load_boxes_from_jsonl",
        ],
        "checked_in_end_to_end_tests": list(test_names),
        "locked_test_semantic": "real loader + real evaluator + real save asserts Person AP=1.0",
        "optional_eval_dependencies_declared": eval_dependencies,
        "production_evaluator_executed": False,
    }
    return observed, evidence


def _validate_box(box: Any, *, prediction: bool) -> None:
    required = {"sample_token", "class_name", "translation"}
    if prediction:
        required.add("confidence")
    if not isinstance(box, dict) or set(box) != required:
        raise QualificationError("fixture box schema drift")
    if not all(
        isinstance(box[key], str) and box[key] for key in ("sample_token", "class_name")
    ):
        raise QualificationError("fixture identity fields must be non-empty strings")
    translation = box["translation"]
    if (
        not isinstance(translation, list)
        or len(translation) != 3
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in translation
        )
        or any(not math.isfinite(float(value)) for value in translation)
    ):
        raise QualificationError(
            "fixture translation must contain three finite numbers"
        )
    if prediction:
        confidence = box["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise QualificationError(
                "fixture confidence must be finite and within [0,1]"
            )


def _interpolated_ap(tp: list[int], fp: list[int], ground_truth_count: int) -> float:
    if ground_truth_count <= 0:
        raise QualificationError("AP fixture requires ground truth")
    cumulative_tp = 0
    cumulative_fp = 0
    recalls: list[float] = []
    precisions: list[float] = []
    for is_tp, is_fp in zip(tp, fp, strict=True):
        cumulative_tp += is_tp
        cumulative_fp += is_fp
        recalls.append(cumulative_tp / ground_truth_count)
        precisions.append(cumulative_tp / (cumulative_tp + cumulative_fp))
    values = []
    for index in range(101):
        threshold = index / 100
        candidates = [
            p for r, p in zip(recalls, precisions, strict=True) if r >= threshold
        ]
        values.append(max(candidates, default=0.0))
    return round(sum(values) / len(values), 12)


def _execute_fixture_case(
    case: dict[str, Any], threshold: float, classes: list[str]
) -> dict[str, Any]:
    if not isinstance(case, dict) or set(case) != {
        "id",
        "ground_truth",
        "predictions",
        "expected",
    }:
        raise QualificationError("fixture case schema drift")
    ground_truth = case["ground_truth"]
    predictions = case["predictions"]
    if not isinstance(ground_truth, list) or not isinstance(predictions, list):
        raise QualificationError("fixture detections must be arrays")
    for box in ground_truth:
        _validate_box(box, prediction=False)
    for box in predictions:
        _validate_box(box, prediction=True)

    matched: set[int] = set()
    per_class: dict[str, Any] = {}
    total_tp = total_fp = 0
    for class_name in classes:
        class_gt = [
            (index, box)
            for index, box in enumerate(ground_truth)
            if box["class_name"] == class_name
        ]
        class_predictions = sorted(
            (box for box in predictions if box["class_name"] == class_name),
            key=lambda box: (-float(box["confidence"]), box["sample_token"]),
        )
        tp: list[int] = []
        fp: list[int] = []
        match_distances: list[float] = []
        for prediction in class_predictions:
            candidates = []
            for gt_index, gt_box in class_gt:
                if (
                    gt_index in matched
                    or gt_box["sample_token"] != prediction["sample_token"]
                ):
                    continue
                distance = math.dist(
                    gt_box["translation"][:2], prediction["translation"][:2]
                )
                candidates.append((distance, gt_index))
            distance, gt_index = min(candidates, default=(math.inf, -1))
            if distance <= threshold:
                matched.add(gt_index)
                tp.append(1)
                fp.append(0)
                match_distances.append(round(distance, 12))
            else:
                tp.append(0)
                fp.append(1)
        ap = _interpolated_ap(tp, fp, len(class_gt))
        total_tp += sum(tp)
        total_fp += sum(fp)
        per_class[class_name] = {
            "ground_truth_count": len(class_gt),
            "prediction_count": len(class_predictions),
            "true_positives": sum(tp),
            "false_positives": sum(fp),
            "false_negatives": len(class_gt) - sum(tp),
            "match_distances": match_distances,
            "average_precision": ap,
        }
    mean_ap = round(
        sum(value["average_precision"] for value in per_class.values()) / len(classes),
        12,
    )
    semantic = {
        "case_id": case["id"],
        "distance_threshold": threshold,
        "per_class": per_class,
        "true_positives": total_tp,
        "false_positives": total_fp,
        "false_negatives": len(ground_truth) - total_tp,
        "mean_ap": mean_ap,
    }
    if {
        "true_positives": semantic["true_positives"],
        "false_positives": semantic["false_positives"],
        "false_negatives": semantic["false_negatives"],
        "mean_ap": semantic["mean_ap"],
    } != case["expected"]:
        raise QualificationError(f"fixture semantic expectation failed: {case['id']}")
    return semantic


def _tree_hash(root: Path) -> tuple[str, dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        raise QualificationError("output root is not a real directory")
    records: list[dict[str, str]] = []
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise QualificationError("unexpected output file type")
        relative = path.relative_to(root).as_posix()
        digest = _sha256(path.read_bytes())
        files[relative] = digest
        records.append({"path": relative, "sha256": digest})
    return _sha256(_canonical_bytes(records)), files


def _run_once(fixture: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(mode=0o700)
    threshold = fixture["distance_threshold"]
    classes = fixture["classes"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0.0 < float(threshold) < math.inf
        or classes != ["Person"]
        or fixture.get("warehouse_sample_bundle") is not False
    ):
        raise QualificationError("fixture top-level semantic boundary drift")
    results = []
    seen_ids: set[str] = set()
    for case in fixture["cases"]:
        case_id = case.get("id") if isinstance(case, dict) else None
        if (
            case_id not in {"perfect-single-detection", "distance-threshold-miss"}
            or case_id in seen_ids
        ):
            raise QualificationError("fixture case identity drift")
        seen_ids.add(case_id)
        result = _execute_fixture_case(case, float(threshold), classes)
        path = output / f"{case_id}.json"
        path.write_bytes(_canonical_bytes(result) + b"\n")
        results.append(result)
    if seen_ids != {"perfect-single-detection", "distance-threshold-miss"}:
        raise QualificationError("fixture must contain the exact two-case set")
    tree_sha, file_sha = _tree_hash(output)
    return {"file_sha256": file_sha, "tree_sha256": tree_sha, "semantic": results}


def _validate_output_locks(run: dict[str, Any], expected: dict[str, str]) -> None:
    if run["tree_sha256"] != expected["tree_sha256"]:
        raise QualificationError("deterministic output tree lock mismatch")
    expected_files = {
        key: value for key, value in expected.items() if key != "tree_sha256"
    }
    if run["file_sha256"] != expected_files:
        raise QualificationError("deterministic output file lock mismatch")


def _validate_result(result: dict[str, Any]) -> None:
    if result["deterministic_runs"][0] != result["deterministic_runs"][1]:
        raise QualificationError("two deterministic runs must be identical")
    if result["policy"] != EXPECTED_POLICY:
        raise QualificationError("result safety policy drift")
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")


def execute(selected: list[str] | None = None) -> dict[str, Any]:
    if selected is not None:
        if len(selected) != len(set(selected)):
            raise QualificationError("duplicate --case selection")
        if selected != [ENTRY_ID]:
            raise QualificationError(f"unknown or unsupported selection: {selected}")
    contract = _load_contract()
    observed = _verify_bindings(contract)
    source_hashes, test_evidence = _verify_source_evidence(contract)
    observed.update(source_hashes)

    fixture_path = contract["fixture"]["path"]
    fixture_raw = _read_repo_bytes(fixture_path)
    fixture_sha = _sha256(fixture_raw)
    if fixture_sha != contract["fixture"]["sha256"]:
        raise QualificationError("fixture lock mismatch")
    fixture = _strict_json_bytes(fixture_raw, fixture_path)
    observed[fixture_path] = fixture_sha

    parent: Path | None = None
    sentinel_unchanged = False
    runs: list[dict[str, Any]] = []
    try:
        parent = Path(tempfile.mkdtemp(prefix="vss-detection-map-"))
        sentinel = parent / "executor-owned-sentinel"
        sentinel.write_bytes(b"detection-map-sentinel-v1\n")
        sentinel_sha = _sha256(sentinel.read_bytes())
        for index in range(2):
            runs.append(_run_once(fixture, parent / f"run-{index + 1}"))
        sentinel_unchanged = _sha256(sentinel.read_bytes()) == sentinel_sha
    finally:
        if parent is not None:
            shutil.rmtree(parent)
    parent_removed = parent is not None and not parent.exists()
    if len(runs) != 2 or not sentinel_unchanged or not parent_removed:
        raise QualificationError("owned temporary execution cleanup failed")
    for run in runs:
        _validate_output_locks(run, contract["output_locks"])

    result = {
        "schema_version": 1,
        "mode": contract["mode"],
        "entry_id": ENTRY_ID,
        "capability_id": contract["entry"]["capability_id"],
        "advertised_binding": contract["entry"],
        "candidate_only": True,
        "observation": "observed_candidate_contract_match",
        "official_capability_effect": "none_candidate_only",
        "runtime_evidence": [],
        "policy": contract["policy"],
        "command_contract": {
            "operation": "bounded_reference_detection_map",
            "runs": 2,
            "fixture_id": fixture["fixture_id"],
            "distance_threshold": fixture["distance_threshold"],
            "interpolation": "101_point_precision_envelope",
        },
        "input_sha256": observed,
        "integration_test_evidence": test_evidence,
        "claim_boundary": contract["claim_boundary"],
        "deterministic_runs": runs,
        "cleanup": {
            "owned_root_removed": parent_removed,
            "executor_owned_sentinel_unchanged": sentinel_unchanged,
        },
    }
    _validate_result(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=[ENTRY_ID])
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        if args.case:
            parser.error("--list cannot be combined with --case")
        print(ENTRY_ID)
        return 0
    print(json.dumps(execute(args.case), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
