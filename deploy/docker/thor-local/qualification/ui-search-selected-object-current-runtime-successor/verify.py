#!/usr/bin/env python3
"""Offline, fail-closed verification of retained UI Search-by-Image evidence."""

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
    "contract": "2d5d087e60c132b2d38e2d15a8c6c449dc1020a77309ca9b0ac47d120ad65b64",
    "evidence": "b24996b847de95e6d573787e971025638a0ba67ec9fca8daaaac7d9e26e4e1a5",
    "executor": "7a7d7c28dfa57da8f735ebe15e97283f385fce1357801f8ce2f8af766c989e8d",
    "harness": "e3e2b9365e0dd8c3711b6aac5a729e59ec04358f61ae6c822e85bf6e6148cf8b",
    "receipt": "04fd46737a84ca85ee81b1a51aa93668b559ebe0a6cde7955974791321b817a9",
    "schema": "3f43fbdf81c9a35e22df56993b404d5e9f3eb15722b133800a6424fafc04ac1a",
}
RAW_URL_RE = re.compile(r"(?:https?|wss?)://", re.IGNORECASE)
SECRET_RE = re.compile(r"(?:nvapi-|api[_-]?key|authorization\s*[:=]|bearer\s+)", re.IGNORECASE)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class VerificationError(RuntimeError):
    """Retained evidence is inconsistent, incomplete, or drifted."""


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
        ("embedding_query", "rtvi_cv", "POST", 200),
        ("create_behavior_index", "elasticsearch", "PUT", 200),
        ("behavior_owned_uuid", "elasticsearch", "GET", 200),
        ("create_raw_index", "elasticsearch", "PUT", 200),
        ("raw_owned_uuid", "elasticsearch", "GET", 200),
        ("write_behavior_1", "elasticsearch", "PUT", 201),
        ("write_behavior_2", "elasticsearch", "PUT", 201),
        ("write_raw_frame", "elasticsearch", "PUT", 201),
        ("refresh_behavior", "elasticsearch", "POST", 200),
        ("refresh_raw", "elasticsearch", "POST", 200),
        ("behavior_fixture_count", "elasticsearch", "GET", 200),
        ("raw_fixture_count", "elasticsearch", "GET", 200),
        ("analytics_frames", "ingress", "GET", 200),
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
    if [row["sequence"] for row in receipt["observations"]] != list(range(1, 36)):
        raise VerificationError("HTTP sequence accounting drifted")


def _verify_ui_semantics(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    ui = receipt["ui_semantics"]
    direct = ui["direct_search"]
    frame = ui["frame_selection"]
    selected = ui["selected_search"]
    diagnostics = ui["diagnostics"]
    if direct["query_sha256"] != contract["fixture"]["query_contract"]["sha256"]:
        raise VerificationError("query digest contract drifted")
    if direct["filter_defaults"] != {"top_k": 10, "similarity": -1}:
        raise VerificationError("Search filter defaults drifted")
    if not all(
        direct[key]
        for key in (
            "exact_local_source_selected",
            "top_k_5_selected",
            "result_aligned_to_fixture_start",
            "playback_modal_opened",
            "playback_metadata_loaded",
            "playback_duration_positive",
        )
    ):
        raise VerificationError("direct Search or playback semantics drifted")
    if [frame["frame_width"], frame["frame_height"]] != contract["fixture"]["frame_dimensions"]:
        raise VerificationError("frame dimensions drifted")
    if frame["frame_count"] != 1 or frame["object_count"] != 2:
        raise VerificationError("frame or bbox count drifted")
    if not frame["select_hint_visible"] or not frame["reference_bbox_clicked"]:
        raise VerificationError("bbox selection was not proven")
    if selected["seed_object_id_sha256"] != frame["selected_object_id_sha256"]:
        raise VerificationError("selected seed digest drifted")
    if selected["candidate_object_id_sha256"] == selected["seed_object_id_sha256"]:
        raise VerificationError("candidate and seed identities collapsed")
    for key in (
        "exact_composite_identity",
        "agent_mode_false",
        "source_type_video_file",
        "seed_excluded",
        "candidate_only",
        "result_card_rerendered",
        "human_facing_source_name_preserved",
        "modal_closed",
        "overlay_closed",
    ):
        if selected[key] is not True:
            raise VerificationError(f"selected-object semantic drifted: {key}")
    if selected["result_count"] != 1 or selected["rendered_card_count"] != 1:
        raise VerificationError("selected-object result count drifted")
    if diagnostics["response_status_counts"] != {"200": 41, "206": 2}:
        raise VerificationError("browser response accounting drifted")
    if diagnostics["expected_abort_request_count"] != 1 or diagnostics["expected_abort_console_count"] != 0:
        raise VerificationError("modal media cancellation boundary drifted")
    for key in (
        "console_error_hashes",
        "console_warning_hashes",
        "page_error_hashes",
        "request_failure_hashes",
        "failing_response_hashes",
    ):
        if diagnostics[key] != []:
            raise VerificationError(f"browser diagnostic present: {key}")
    for key in (
        "non_loopback_request_count",
        "non_loopback_response_count",
        "non_loopback_websocket_count",
        "framework_error_overlay_count",
    ):
        if diagnostics[key] != 0:
            raise VerificationError(f"browser boundary drifted: {key}")
    mobile = ui["mobile"]
    if mobile["overflow"]["document"] > 390 or mobile["overflow"]["body"] > 390:
        raise VerificationError("mobile horizontal overflow")


def _verify_cleanup(receipt: Mapping[str, Any]) -> None:
    expected_owned = {"created": True, "deleted": True, "foreign_documents_observed": False}
    cleanup = receipt["cleanup"]
    if cleanup["behavior"] != expected_owned or cleanup["raw"] != expected_owned:
        raise VerificationError("owned index cleanup drifted")
    if cleanup["absence_checks"] != [
        {"behavior": 404, "raw": 404},
        {"behavior": 404, "raw": 404},
    ]:
        raise VerificationError("owned index absence checks drifted")
    if receipt["pre_state"]["embed_index"] != receipt["post_state"]["embed_index"]:
        raise VerificationError("read-only embedding corpus changed")
    if receipt["pre_state"]["owned_index_status"] != receipt["post_state"]["owned_index_status"]:
        raise VerificationError("owned index state did not restore")


def _verify_evidence(evidence: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    if evidence["captured_at"] != receipt["captured_at"]:
        raise VerificationError("evidence timestamp drifted")
    if evidence["artifact_digests"] != {
        "contract_sha256": EXPECTED["contract"],
        "executor_sha256": EXPECTED["executor"],
        "harness_sha256": EXPECTED["harness"],
        "receipt_schema_sha256": EXPECTED["schema"],
        "runtime_receipt_sha256": EXPECTED["receipt"],
    }:
        raise VerificationError("evidence artifact projection drifted")
    ui = receipt["ui_semantics"]
    expected_qualification = {
        "search_tab_rendered": ui["page_identity"]["search_component_visible"],
        "exact_local_recorded_source_selected": ui["direct_search"]["exact_local_source_selected"],
        "direct_semantic_result_count": ui["direct_search"]["result_count"],
        "playback_modal_opened": ui["direct_search"]["playback_modal_opened"],
        "playback_metadata_loaded": ui["direct_search"]["playback_metadata_loaded"],
        "playback_duration_positive": ui["direct_search"]["playback_duration_positive"],
        "real_vst_picture_status": ui["frame_selection"]["picture_http_status"],
        "real_video_analytics_frames_status": ui["frame_selection"]["frames_http_status"],
        "frame_count": ui["frame_selection"]["frame_count"],
        "selectable_bbox_count": ui["frame_selection"]["object_count"],
        "frame_dimensions": [ui["frame_selection"]["frame_width"], ui["frame_selection"]["frame_height"]],
        "reference_bbox_clicked": ui["frame_selection"]["reference_bbox_clicked"],
        "selected_object_exact_composite_identity": ui["selected_search"]["exact_composite_identity"],
        "selected_object_agent_mode_false": ui["selected_search"]["agent_mode_false"],
        "selected_object_source_type_video_file": ui["selected_search"]["source_type_video_file"],
        "selected_object_result_count": ui["selected_search"]["result_count"],
        "selected_object_seed_excluded": ui["selected_search"]["seed_excluded"],
        "selected_object_candidate_only": ui["selected_search"]["candidate_only"],
        "human_facing_source_name_preserved": ui["selected_search"]["human_facing_source_name_preserved"],
        "selected_result_card_rerendered": ui["selected_search"]["result_card_rerendered"],
        "selected_result_similarity": ui["selected_search"]["similarity"],
        "desktop_horizontal_overflow": False,
        "mobile_horizontal_overflow": False,
        "browser_actions": receipt["bounds"]["browser_actions"],
        "loopback_browser_responses": receipt["bounds"]["loopback_browser_responses"],
        "fixture_http_requests": receipt["bounds"]["fixture_http_requests"],
        "persistent_mutations": receipt["bounds"]["persistent_mutations"],
    }
    if evidence["qualification"] != expected_qualification:
        raise VerificationError("evidence qualification projection drifted")
    expected_backend = {
        key: receipt["identity"]["backend_evidence"][key]
        for key in (
            "runtime_receipt_sha256",
            "official_runtime_evidence_sha256",
            "verifier_sha256",
            "passed",
        )
    }
    if evidence["backend_evidence"] != expected_backend:
        raise VerificationError("backend evidence projection drifted")


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
        '"reference_object":',
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
        "harness": _sha((HERE / "harness.mjs").read_bytes()),
        "receipt": _sha(receipt_raw),
        "schema": _sha(schema_raw),
    }
    if observed != EXPECTED:
        raise VerificationError("retained artifact digest drifted")
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt))
    if errors:
        raise VerificationError("runtime receipt failed schema validation")
    if receipt["contract_sha256"] != EXPECTED["contract"]:
        raise VerificationError("receipt contract digest drifted")
    if receipt["executor_sha256"] != EXPECTED["executor"]:
        raise VerificationError("receipt executor digest drifted")
    if receipt["harness_sha256"] != EXPECTED["harness"]:
        raise VerificationError("receipt harness digest drifted")
    if receipt["receipt_schema_sha256"] != EXPECTED["schema"]:
        raise VerificationError("receipt schema digest drifted")
    if receipt["target_commit"] != contract["target_commit"]:
        raise VerificationError("target commit drifted")
    _verify_source_locks(contract, receipt)
    _verify_runtime(contract, receipt)
    _verify_observations(receipt)
    _verify_ui_semantics(contract, receipt)
    _verify_cleanup(receipt)
    _verify_evidence(evidence, receipt)
    _verify_retention(receipt_raw, evidence_raw)
    return {
        "package_id": receipt["package_id"],
        "status": "passed",
        "promotion_eligible": True,
        "fixture_http_requests": receipt["bounds"]["fixture_http_requests"],
        "browser_actions": receipt["bounds"]["browser_actions"],
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
