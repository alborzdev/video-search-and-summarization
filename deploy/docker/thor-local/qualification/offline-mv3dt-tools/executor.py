#!/usr/bin/env python3
"""Bounded, candidate-only execution of the two offline MV3DT config tools.

The executor imports checked-in Python sources directly and writes only below a
fresh private temporary directory.  It has no Docker, network, model, sample,
credential, or service-lifecycle path and cannot update official evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
CONTRACT_PATH = LANE / "contract.json"
RESULT_SCHEMA_PATH = LANE / "result.schema.json"
SAFE_NAMES = {"custom_cam_a", "custom_cam_b"}
SOURCE_PATHS = {
    "cam_info_generator": "tools/rtvi-cv-mv3dt-utils/generate_cam_info_configs.py",
    "pub_sub_generator": "tools/rtvi-cv-mv3dt-utils/generate_pub_sub_configs.py",
    "requirements": "tools/rtvi-cv-mv3dt-utils/requirements.txt",
    "manifest": "deploy/docker/thor-local/parity/manifest.json",
}


class QualificationError(RuntimeError):
    """The offline candidate contract or one of its observations failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {path}")
    return value


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    try:
        resolved = (root / path).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise QualificationError(
            f"path is not a regular repository file: {relative}"
        ) from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise QualificationError(f"path is not a regular repository file: {relative}")
    return resolved


def _load_contract() -> dict[str, Any]:
    contract = _strict_json(CONTRACT_PATH)
    if contract.get("mode") != "candidate_only_offline_mv3dt_tools":
        raise QualificationError("unexpected contract mode")
    expected_policy = {
        "candidate_only": True,
        "official_capability_effect": "none_candidate_only",
        "runtime_evidence": [],
        "network_allowed": False,
        "docker_allowed": False,
        "subprocess_allowed": False,
        "lifecycle_allowed": False,
        "downloads_allowed": False,
        "credentials_allowed": False,
        "warehouse_sample_bundle": "excluded",
        "writes": "private_temporary_directory_only",
    }
    if contract.get("policy") != expected_policy:
        raise QualificationError("candidate-only safety policy drift")
    if contract.get("feature_id") != "mv3dt-config-utils":
        raise QualificationError("feature binding drift")
    entries = contract.get("advertised_entries")
    if not isinstance(entries, list) or len(entries) != 2:
        raise QualificationError("exact two-entry binding is required")
    if {item.get("capability_id") for item in entries} != {
        "tool.mv3dt.cam-info-generator",
        "tool.mv3dt.pub-sub-generator",
    }:
        raise QualificationError("capability binding drift")
    return contract


def _verify_contract_locks(contract: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    source_locks = contract.get("source_locks")
    if not isinstance(source_locks, list) or len(source_locks) != len(SOURCE_PATHS):
        raise QualificationError("source-lock denominator drift")
    by_path = {item.get("path"): item for item in source_locks}
    if set(by_path) != set(SOURCE_PATHS.values()):
        raise QualificationError("source-lock path set drift")
    for relative, lock in by_path.items():
        actual = _sha256(_repo_file(relative).read_bytes())
        if actual != lock.get("sha256"):
            raise QualificationError(f"source lock mismatch for {relative}: {actual}")
        hashes[relative] = actual

    fixture = contract.get("fixture")
    fixture_path = fixture.get("path") if isinstance(fixture, dict) else None
    if not isinstance(fixture_path, str):
        raise QualificationError("fixture path is absent")
    fixture_hash = _sha256(_repo_file(fixture_path).read_bytes())
    if fixture_hash != fixture.get("sha256"):
        raise QualificationError("synthetic fixture lock mismatch")
    if fixture.get("warehouse_sample_bundle") is not False:
        raise QualificationError("Warehouse sample bundle must remain excluded")
    hashes[fixture_path] = fixture_hash

    requirements = (
        _repo_file(SOURCE_PATHS["requirements"])
        .read_text(encoding="utf-8")
        .splitlines()
    )
    if requirements != contract.get("dependency_lock", {}).get("declared_requirements"):
        raise QualificationError(
            "declared dependency lock differs from requirements.txt"
        )

    manifest = _strict_json(_repo_file(SOURCE_PATHS["manifest"]))
    for entry in contract["advertised_entries"]:
        pointer = entry["manifest_pointer"]
        value: Any = manifest
        for token in pointer.split("/")[1:]:
            value = value[int(token)] if isinstance(value, list) else value[token]
        if value != entry["advertised"]:
            raise QualificationError(f"advertised claim drift: {pointer}")
        digest = _sha256(_canonical_bytes({"json_pointer": pointer, "value": value}))
        if digest != entry["manifest_entry_sha256"]:
            raise QualificationError(f"advertised entry lock drift: {pointer}")
        if entry["oracle_id"] != f"oracle.{entry['capability_id']}":
            raise QualificationError("oracle identity drift")
    return hashes


def _load_module(name: str, relative: str):
    path = _repo_file(relative)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError(f"cannot import checked source: {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _tree_hash(root: Path) -> tuple[str, dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        raise QualificationError(f"output root is not a real directory: {root}")
    records: list[dict[str, str]] = []
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise QualificationError(f"unexpected output type: {path}")
        try:
            path.resolve(strict=True).relative_to(root.resolve(strict=True))
        except ValueError as exc:
            raise QualificationError(f"output escaped private root: {path}") from exc
        relative = path.relative_to(root).as_posix()
        digest = _sha256(path.read_bytes())
        files[relative] = digest
        records.append({"path": relative, "sha256": digest})
    return _sha256(_canonical_bytes(records)), files


def _validate_cam_info(root: Path) -> dict[str, Any]:
    files = sorted(root.glob("*.yml"))
    if {path.stem for path in files} != SAFE_NAMES or len(files) != 2:
        raise QualificationError("camInfo output is not the exact safe two-camera set")
    semantic: dict[str, Any] = {}
    for path in files:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "projectionMatrix_3x4_w2p",
            "modelInfo",
        }:
            raise QualificationError(f"invalid camInfo schema: {path.name}")
        projection = value["projectionMatrix_3x4_w2p"]
        if not isinstance(projection, list) or len(projection) != 12:
            raise QualificationError(f"invalid flattened projection: {path.name}")
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in projection
        ):
            raise QualificationError(f"non-finite projection: {path.name}")
        models = value["modelInfo"]
        if models != [
            {"classID": 0, "height": 1.7, "radius": 0.3},
            {"classID": 1, "height": 1.2, "radius": 0.25},
        ]:
            raise QualificationError(f"modelInfo contract drift: {path.name}")
        semantic[path.stem] = {
            "projection_shape": [3, 4],
            "projection_value_count": 12,
            "class_ids": [item["classID"] for item in models],
        }
    return semantic


def _validate_pub_sub(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "pubBrokerTopicStr",
        "subPeerBrokerTopicStrs",
    }:
        raise QualificationError("invalid pub/sub top-level schema")
    pubs = value["pubBrokerTopicStr"]
    subs = value["subPeerBrokerTopicStrs"]
    if set(pubs) != SAFE_NAMES or set(subs) != SAFE_NAMES:
        raise QualificationError("pub/sub camera keys differ from fixture")
    expected_pubs = {
        name: f"localhost:1883;/trck/{name}" for name in sorted(SAFE_NAMES)
    }
    if pubs != expected_pubs:
        raise QualificationError("publication broker/topic mapping drift")
    for name in sorted(SAFE_NAMES):
        peer = next(iter(SAFE_NAMES - {name}))
        expected = [f"localhost:1883;/trck/{peer}"]
        if subs[name] != expected or expected_pubs[name] in subs[name]:
            raise QualificationError(
                f"invalid or self-referential subscriptions: {name}"
            )
        if subs[name] != sorted(subs[name]):
            raise QualificationError(f"subscriptions are not deterministic: {name}")
    return {
        "broker": "localhost:1883",
        "camera_ids": sorted(SAFE_NAMES),
        "topics": [expected_pubs[name] for name in sorted(SAFE_NAMES)],
        "peer_counts": {name: len(subs[name]) for name in sorted(SAFE_NAMES)},
        "self_subscriptions": 0,
    }


def _dependency_observation(
    contract: dict[str, Any], pub_module: Any
) -> dict[str, Any]:
    distributions = contract["dependency_lock"]["distributions"]
    versions: dict[str, str] = {}
    for distribution in distributions:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise QualificationError(
                f"required local distribution missing: {distribution}"
            ) from exc
    module_versions = {
        "cv2": pub_module.cv2.__version__,
        "numpy": pub_module.np.__version__,
        "tqdm": pub_module.tqdm.__version__,
        "yaml": yaml.__version__,
    }
    observed = {"distributions": versions, "modules": module_versions}
    return {
        "requirements_path": SOURCE_PATHS["requirements"],
        "requirements_sha256": next(
            item["sha256"]
            for item in contract["source_locks"]
            if item["path"] == SOURCE_PATHS["requirements"]
        ),
        "declared_requirements": contract["dependency_lock"]["declared_requirements"],
        "observed_distribution_versions": versions,
        "observed_module_versions": module_versions,
        "observed_versions_sha256": _sha256(_canonical_bytes(observed)),
        "note": "candidate execution records local versions; it does not claim they equal the reviewed pins",
    }


def _execute_run(
    run_root: Path,
    contract: dict[str, Any],
    cam_module: Any,
    pub_module: Any,
) -> dict[str, Any]:
    fixture_path = _repo_file(contract["fixture"]["path"])
    cam_root = run_root / "camInfo"
    pub_root = run_root / "peer_configs"
    entries = cam_module._parse_model_args(contract["execution"]["model_classes"])
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        count = cam_module.generate_cam_info_files(fixture_path, cam_root, entries)
        pub_path = pub_module.generate_pub_sub_config(
            cam_info_path=cam_root,
            mqtt_brokers=contract["execution"]["mqtt_broker"],
            minimum_object_size=contract["execution"]["minimum_object_size"],
            neighbor_criteria=contract["execution"]["neighbor_criteria"],
            output_path=pub_root,
            range_of_interest=contract["execution"]["range_of_interest"],
        )
    if count != 2 or pub_path != pub_root / "pub_sub_info_config.yml":
        raise QualificationError("generator return contract drift")
    cam_semantic = _validate_cam_info(cam_root)
    pub_semantic = _validate_pub_sub(pub_path)
    full_hash, file_hashes = _tree_hash(run_root)
    cam_hash, _ = _tree_hash(cam_root)
    pub_hash = _sha256(pub_path.read_bytes())
    expected = contract["output_locks"]
    observed = {
        "cam_info_tree_sha256": cam_hash,
        "pub_sub_file_sha256": pub_hash,
        "full_output_tree_sha256": full_hash,
    }
    if observed != expected:
        raise QualificationError(f"output lock mismatch: {observed}")
    return {
        "output_locks": observed,
        "file_sha256": file_hashes,
        "semantic": {"cam_info": cam_semantic, "pub_sub": pub_semantic},
    }


def _validate_result(result: dict[str, Any]) -> None:
    runs = result.get("deterministic_runs")
    if not isinstance(runs, list) or len(runs) != 2 or runs[0] != runs[1]:
        raise QualificationError(
            "result must contain exactly two byte/semantic-identical runs"
        )
    dependency = result.get("dependency_lock")
    if not isinstance(dependency, dict):
        raise QualificationError("result dependency observation is absent")
    observed_versions = {
        "distributions": dependency.get("observed_distribution_versions"),
        "modules": dependency.get("observed_module_versions"),
    }
    if dependency.get("observed_versions_sha256") != _sha256(
        _canonical_bytes(observed_versions)
    ):
        raise QualificationError("observed dependency-version digest mismatch")
    schema = _strict_json(RESULT_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(result),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        raise QualificationError(f"result schema failed: {first.message}")


def execute() -> dict[str, Any]:
    contract = _load_contract()
    source_hashes_before = _verify_contract_locks(contract)
    cam_module = _load_module(
        "offline_mv3dt_cam_info_generator", SOURCE_PATHS["cam_info_generator"]
    )
    pub_module = _load_module(
        "offline_mv3dt_pub_sub_generator", SOURCE_PATHS["pub_sub_generator"]
    )
    dependency = _dependency_observation(contract, pub_module)

    parent = Path(tempfile.mkdtemp(prefix="vss-mv3dt-candidate-"))
    owned = parent / "owned"
    sentinel = parent / "adjacent-sentinel"
    sentinel.write_bytes(b"do-not-change\n")
    sentinel_before = _sha256(sentinel.read_bytes())
    runs: list[dict[str, Any]] = []
    cleanup_error: Exception | None = None
    try:
        owned.mkdir()
        for index in range(contract["execution"]["runs"]):
            run_root = owned / f"run-{index + 1}"
            run_root.mkdir()
            runs.append(_execute_run(run_root, contract, cam_module, pub_module))
        if len(runs) != 2 or runs[0] != runs[1]:
            raise QualificationError(
                "the two isolated runs are not byte/semantic deterministic"
            )
    finally:
        try:
            if owned.exists():
                shutil.rmtree(owned)
        except Exception as exc:  # pragma: no cover - exercised by injected unit test
            cleanup_error = exc

    cleanup = {
        "owned_root_removed": not owned.exists(),
        "adjacent_sentinel_unchanged": (
            sentinel.is_file() and _sha256(sentinel.read_bytes()) == sentinel_before
        ),
        "parent_removed_after_observation": True,
    }
    try:
        if cleanup_error is not None:
            raise QualificationError(f"owned-root cleanup failed: {cleanup_error}")
        if (
            not cleanup["owned_root_removed"]
            or not cleanup["adjacent_sentinel_unchanged"]
        ):
            raise QualificationError("cleanup postconditions failed")
        source_hashes_after = _verify_contract_locks(contract)
        if source_hashes_before != source_hashes_after:
            raise QualificationError("locked sources changed during execution")
        result = {
            "schema_version": 1,
            "mode": contract["mode"],
            "candidate_only": True,
            "feature_id": contract["feature_id"],
            "capability_ids": sorted(
                item["capability_id"] for item in contract["advertised_entries"]
            ),
            "observation": "observed_match_candidate_only",
            "official_capability_effect": "none_candidate_only",
            "runtime_evidence": [],
            "warehouse_sample_bundle_used": False,
            "network_used": False,
            "docker_used": False,
            "subprocess_used": False,
            "lifecycle_used": False,
            "source_and_fixture_sha256": source_hashes_after,
            "dependency_lock": dependency,
            "run_count": len(runs),
            "deterministic_runs": runs,
            "cleanup": cleanup,
        }
        _validate_result(result)
        return result
    finally:
        shutil.rmtree(parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="execute and emit only a status line"
    )
    args = parser.parse_args(argv)
    try:
        result = execute()
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    if args.check:
        print("VALID: 2 candidate-only offline MV3DT tool observations")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
