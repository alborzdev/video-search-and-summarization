#!/usr/bin/env python3
"""Offline, fail-closed verification of retained current Search evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
EXPECTED = {
    "contract": "7276e965e723e8beab3dc443ad70caa5927c5c11c6036817610c117a7dd0b658",
    "evidence": "ce8810fc78e80b7bd2e2afd19cb58befe71daaab3fde0e3b8a20561a4bb58d07",
    "executor": "dbe0101ecae506cd167cfdf7e677b90495384f5071b111d98d4ff06c742d20c6",
    "receipt": "57a8d5e9dccaac3d613b842f8aac99c71859734857adb9975bfbbdae54796bae",
    "schema": "e10789d639c53a0badc0a7d217946a76dd938e6ac7d43247cc7889c1e311d86a",
}
RAW_URL_RE = re.compile(r"(?:https?|wss?)://", re.IGNORECASE)
SECRET_RE = re.compile(r"(?:nvapi-|api[_-]?key|authorization\s*[:=]|bearer\s+)", re.IGNORECASE)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class VerificationError(RuntimeError):
    """The retained package is inconsistent, incomplete, or has drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise VerificationError(f"duplicate key in {path.name}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                VerificationError(f"non-finite value in {path.name}: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON in {path.name}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path.name} is not an object")
    return value, raw


def _repo_path(relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise VerificationError("unsafe source-lock path")
    target = (ROOT / relative).resolve(strict=True)
    target.relative_to(ROOT.resolve(strict=True))
    return target


def _verify_source_locks(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    expected = {row["path"]: row["sha256"] for row in contract["source_locks"]}
    if len(expected) != len(contract["source_locks"]):
        raise VerificationError("duplicate source-lock path")
    if receipt["identity"]["source_hashes"] != expected:
        raise VerificationError("receipt source-lock projection drifted")
    for relative, digest in expected.items():
        if _sha(_repo_path(relative).read_bytes()) != digest:
            raise VerificationError(f"source lock drifted: {relative}")


def _verify_runtime(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    before = receipt["pre_state"]["runtime"]
    after = receipt["post_state"]["runtime"]
    if before != after:
        raise VerificationError("related runtime changed during qualification")
    for expected in contract["runtime"].values():
        observed = before[expected["container"]]
        if (
            observed["configured_image"] != expected["configured_image"]
            or observed["image_id"] != expected["image_id"]
            or observed["running"] is not True
            or observed["restart_count"] != 0
            or observed["oom_killed"] is not False
        ):
            raise VerificationError(f"runtime identity drifted: {expected['container']}")


def _verify_observations(receipt: Mapping[str, Any]) -> None:
    expected = [
        ("behavior_prestate", "elasticsearch", "GET", 404),
        ("raw_prestate", "elasticsearch", "GET", 404),
        ("embed_pre_uuid", "elasticsearch", "GET", 200),
        ("embed_pre_count", "elasticsearch", "GET", 200),
        ("vios_sensor_inventory", "ingress", "GET", 200),
        ("vios_storage_timelines", "ingress", "GET", 200),
        ("behavior_template", "elasticsearch", "GET", 200),
        ("raw_template", "elasticsearch", "GET", 200),
        ("rtvi_cv_liveness", "rtvi_cv", "GET", 200),
        ("embedding_query_a", "rtvi_cv", "POST", 200),
        ("embedding_query_b", "rtvi_cv", "POST", 200),
        ("create_behavior_index", "elasticsearch", "PUT", 200),
        ("behavior_owned_uuid", "elasticsearch", "GET", 200),
        ("create_raw_index", "elasticsearch", "PUT", 200),
        ("raw_owned_uuid", "elasticsearch", "GET", 200),
        ("write_behavior_1", "elasticsearch", "PUT", 201),
        ("write_behavior_2", "elasticsearch", "PUT", 201),
        ("write_behavior_3", "elasticsearch", "PUT", 201),
        ("write_raw_frame", "elasticsearch", "PUT", 201),
        ("refresh_behavior", "elasticsearch", "POST", 200),
        ("refresh_raw", "elasticsearch", "POST", 200),
        ("behavior_fixture_count", "elasticsearch", "GET", 200),
        ("raw_fixture_count", "elasticsearch", "GET", 200),
        ("analytics_frames", "ingress", "GET", 200),
        ("search_attribute_single", "search", "POST", 200),
        ("search_attribute_append", "search", "POST", 200),
        ("search_attribute_fused", "search", "POST", 200),
        ("search_base_selected_object", "search", "POST", 200),
        ("search_image_selected_object", "search", "POST", 200),
        ("search_fusion_agent_mode", "search", "POST", 200),
        ("search_invalid_source_type", "search", "POST", 422),
        ("cleanup_uuid_behavior", "elasticsearch", "GET", 200),
        ("cleanup_inventory_behavior", "elasticsearch", "POST", 200),
        ("cleanup_delete_index_behavior", "elasticsearch", "DELETE", 200),
        ("cleanup_uuid_raw", "elasticsearch", "GET", 200),
        ("cleanup_inventory_raw", "elasticsearch", "POST", 200),
        ("cleanup_delete_index_raw", "elasticsearch", "DELETE", 200),
        ("behavior_absent_1", "elasticsearch", "GET", 404),
        ("raw_absent_1", "elasticsearch", "GET", 404),
        ("behavior_absent_2", "elasticsearch", "GET", 404),
        ("raw_absent_2", "elasticsearch", "GET", 404),
        ("embed_post_uuid", "elasticsearch", "GET", 200),
        ("embed_post_count", "elasticsearch", "GET", 200),
        ("analytics_frames_post_cleanup", "ingress", "GET", 200),
    ]
    observed = [
        (row["operation"], row["target"], row["method"], row["status"])
        for row in receipt["observations"]
    ]
    if observed != expected:
        raise VerificationError("HTTP operation sequence drifted")
    if [row["sequence"] for row in receipt["observations"]] != list(range(1, 45)):
        raise VerificationError("HTTP sequence accounting drifted")


def _verify_semantics(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    semantics = receipt["semantics"]
    capability = contract["capability_contract"]
    if semantics["canonical_routes_observed"] != capability["routes"]:
        raise VerificationError("canonical Search route set drifted")
    all_hashes = semantics["all_expected_object_id_hashes"]
    if len(set(all_hashes)) != 2:
        raise VerificationError("fixture object digest set drifted")
    for key in ("single_attribute", "append_multiple_attributes", "fuse_multiple_attributes"):
        if semantics[key]["object_id_hashes"] != all_hashes:
            raise VerificationError(f"object digest projection drifted: {key}")
    selected = semantics["selected_object_knn"]
    if (
        sorted([selected["seed_object_id_hash"], selected["candidate_object_id_hash"]])
        != all_hashes
        or selected["seed_object_id_hash"] == selected["candidate_object_id_hash"]
    ):
        raise VerificationError("selected-object identity boundary drifted")
    if semantics["single_attribute"]["reference_duration_seconds"] != 1.0:
        raise VerificationError("minimum clip duration drifted")
    if semantics["fusion"]["order_observed"] != capability["fusion"]["order"]:
        raise VerificationError("fusion ordering drifted")
    if min(semantics["fusion"]["branch_markers"].values()) < 1:
        raise VerificationError("fusion branch marker missing")
    if receipt["pre_state"]["embed_index"] != receipt["post_state"]["embed_index"]:
        raise VerificationError("read-only embedding corpus changed")
    if receipt["identity"]["query_contracts"] != contract["fixture"]["query_contracts"]:
        raise VerificationError("query digest contract drifted")


def _verify_cleanup(receipt: Mapping[str, Any]) -> None:
    expected_owned = {"created": True, "deleted": True, "foreign_documents_observed": False}
    cleanup = receipt["cleanup"]
    if cleanup["behavior"] != expected_owned or cleanup["raw"] != expected_owned:
        raise VerificationError("owned index cleanup drifted")
    if receipt["pre_state"]["owned_index_status"] != {"behavior": 404, "raw": 404}:
        raise VerificationError("owned index pre-state was not absent")
    if receipt["post_state"]["owned_index_status"] != {"behavior": 404, "raw": 404}:
        raise VerificationError("owned index post-state was not absent")


def _verify_evidence(evidence: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    if evidence["captured_at"] != receipt["captured_at"]:
        raise VerificationError("evidence timestamp drifted")
    if evidence["artifact_digests"] != {
        "contract_sha256": EXPECTED["contract"],
        "executor_sha256": EXPECTED["executor"],
        "receipt_schema_sha256": EXPECTED["schema"],
        "runtime_receipt_sha256": EXPECTED["receipt"],
    }:
        raise VerificationError("evidence artifact projection drifted")
    semantics = receipt["semantics"]
    qualification = evidence["qualification"]
    expected_projection = {
        "canonical_routes_observed": semantics["canonical_routes_observed"],
        "embedding_dimensions": semantics["embedding_dimensions"],
        "selected_bbox_frame_objects": semantics["frames"]["object_count"],
        "selected_object_knn_seed_excluded": semantics["selected_object_knn"]["seed_excluded"],
        "same_object_segments_merged": semantics["single_attribute"]["same_object_merge"],
        "minimum_clip_seconds": semantics["single_attribute"]["reference_duration_seconds"],
        "multiple_attributes_append_passed": semantics["append_multiple_attributes"]["passed"],
        "multiple_attributes_fuse_passed": semantics["fuse_multiple_attributes"]["passed"],
        "fusion_order": semantics["fusion"]["order_observed"],
        "rrf_branch_observed": min(semantics["fusion"]["branch_markers"].values()) >= 1,
        "same_video_top_k": semantics["fusion"]["result_count"],
        "adjacent_invalid_status": semantics["adjacent_invalid_status"],
        "http_requests": receipt["bounds"]["http_requests"],
        "persistent_mutations": receipt["bounds"]["persistent_mutations"],
    }
    if qualification != expected_projection:
        raise VerificationError("evidence semantic projection drifted")


def _verify_retention(receipt_raw: bytes, evidence_raw: bytes) -> None:
    for label, raw in (("receipt", receipt_raw), ("evidence", evidence_raw)):
        text = raw.decode("utf-8")
        if RAW_URL_RE.search(text):
            raise VerificationError(f"raw URL retained in {label}")
        if SECRET_RE.search(text):
            raise VerificationError(f"secret-shaped value retained in {label}")
        if UUID_RE.search(text):
            raise VerificationError(f"raw runtime UUID retained in {label}")
    receipt_text = receipt_raw.decode("utf-8")
    forbidden_keys = (
        '"prompt":',
        '"query":',
        '"request_id":',
        '"session_id":',
        '"sensor_id":',
        '"stream_id":',
        '"object_id":',
        '"vector":',
        '"url":',
    )
    if any(key in receipt_text for key in forbidden_keys):
        raise VerificationError("raw prompt, vector, URL, or runtime identifier retained")


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    schema, schema_raw = _load(HERE / "receipt.schema.json")
    observed = {
        "contract": _sha(contract_raw),
        "evidence": _sha(evidence_raw),
        "executor": _sha((HERE / "executor.py").read_bytes()),
        "receipt": _sha(receipt_raw),
        "schema": _sha(schema_raw),
    }
    if observed != EXPECTED:
        raise VerificationError("retained artifact digest drifted")
    Draft202012Validator.check_schema(schema)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt)
    )
    if errors:
        raise VerificationError("runtime receipt failed schema validation")
    if receipt["contract_sha256"] != EXPECTED["contract"]:
        raise VerificationError("receipt contract digest drifted")
    if receipt["executor_sha256"] != EXPECTED["executor"]:
        raise VerificationError("receipt executor digest drifted")
    if receipt["receipt_schema_sha256"] != EXPECTED["schema"]:
        raise VerificationError("receipt schema digest drifted")
    if receipt["target_commit"] != contract["target_commit"]:
        raise VerificationError("target commit drifted")
    _verify_source_locks(contract, receipt)
    _verify_runtime(contract, receipt)
    _verify_observations(receipt)
    _verify_semantics(contract, receipt)
    _verify_cleanup(receipt)
    _verify_evidence(evidence, receipt)
    _verify_retention(receipt_raw, evidence_raw)
    return {
        "package_id": receipt["package_id"],
        "status": "passed",
        "promotion_eligible": True,
        "http_requests": receipt["bounds"]["http_requests"],
        "persistent_mutations": receipt["bounds"]["persistent_mutations"],
        "warehouse_sample_bundle": "excluded",
    }


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True))
        return 0
    except (VerificationError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
