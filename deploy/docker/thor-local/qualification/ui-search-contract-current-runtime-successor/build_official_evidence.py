#!/usr/bin/env python3
"""Build the retained official projection for the current Search UI contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "official-runtime-evidence.json"
PACKAGE_ID = "thor-ui-search-contract-current-runtime-successor-v1"


class EvidenceError(RuntimeError):
    """The retained receipt cannot support the official evidence projection."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise EvidenceError(f"duplicate key in {path.name}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                EvidenceError(f"non-finite value in {path.name}: {item}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{path.name} must be an object")
    return value, raw


def _artifact_digests() -> dict[str, str]:
    return {
        "contract_sha256": _sha((HERE / "contract.json").read_bytes()),
        "executor_sha256": _sha((HERE / "executor.py").read_bytes()),
        "harness_sha256": _sha((HERE / "harness.mjs").read_bytes()),
        "receipt_schema_sha256": _sha((HERE / "receipt.schema.json").read_bytes()),
        "runtime_receipt_sha256": _sha((HERE / "runtime-receipt.json").read_bytes()),
        "evidence_builder_sha256": _sha(Path(__file__).resolve().read_bytes()),
    }


def build() -> dict[str, Any]:
    contract, _ = _load(HERE / "contract.json")
    receipt, _ = _load(HERE / "runtime-receipt.json")
    schema, _ = _load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt)
    )
    if errors:
        raise EvidenceError(f"runtime receipt failed schema validation: {errors[0].message}")
    artifacts = _artifact_digests()
    if (
        receipt.get("package_id") != PACKAGE_ID
        or receipt.get("status") != "passed_current_candidate"
        or receipt.get("promotion_eligible") is not True
        or receipt.get("target_commit") != contract.get("target_commit")
        or receipt.get("contract_sha256") != artifacts["contract_sha256"]
        or receipt.get("executor_sha256") != artifacts["executor_sha256"]
        or receipt.get("harness_sha256") != artifacts["harness_sha256"]
        or receipt.get("receipt_schema_sha256") != artifacts["receipt_schema_sha256"]
    ):
        raise EvidenceError("receipt identity or artifact binding drifted")

    ui = receipt["ui_semantics"]
    selected = receipt["identity"]["selected_object_evidence"]
    critic = receipt["identity"]["critic_runtime_evidence"]
    selected_official, _ = _load(
        HERE.parent
        / "ui-search-selected-object-current-runtime-successor"
        / "official-runtime-evidence.json"
    )
    selected_qualification = selected_official["qualification"]
    diagnostics = ui["diagnostics"]
    cleanup = receipt["cleanup"]
    evidence = {
        "schema_version": 1,
        "evidence_id": "thor-ui-search-contract-current-runtime-20260810",
        "package_id": PACKAGE_ID,
        "capability_id": contract["capability_id"],
        "supporting_capability_id": contract["supporting_capability_id"],
        "oracle_id": contract["oracle_id"],
        "target_release": "VSS 3.2.1",
        "target_commit": receipt["target_commit"],
        "captured_at": receipt["captured_at"],
        "status": "passed_current",
        "promotion_eligible": True,
        "artifact_digests": artifacts,
        "dependency_evidence": {
            "selected_object": {
                "contract_sha256": selected["contract_sha256"],
                "official_runtime_evidence_sha256": selected[
                    "official_runtime_evidence_sha256"
                ],
                "verifier_sha256": selected["verifier_sha256"],
                "passed": selected["passed"],
            },
            "real_local_critic": {
                "contract_sha256": critic["contract_sha256"],
                "runtime_receipt_sha256": critic["runtime_receipt_sha256"],
                "verifier_sha256": critic["verifier_sha256"],
                "confirmed_card_count": critic["confirmed_card_count"],
                "passed": critic["passed"],
            },
        },
        "qualification": {
            "search_tab_rendered": ui["page_identity"]["search_component_visible"],
            "source_default_video_file": ui["source_contract"]["default_video_file"],
            "source_values": ui["source_contract"]["values"],
            "source_round_trip_passed": ui["source_contract"][
                "rtsp_and_video_file_round_trip"
            ],
            "top_k_default": ui["filter_contract"]["defaults"]["top_k"],
            "top_k_minimum": ui["filter_contract"]["top_k_minimum"],
            "below_minimum_clamped": ui["filter_contract"][
                "top_k_minimum_selected"
            ],
            "similarity_default": ui["filter_contract"]["defaults"]["similarity"],
            "similarity_contract_range": contract["capability_contract"][
                "similarity_range"
            ],
            "search_request_top_k": ui["request_contract"]["top_k"],
            "search_request_video_file": ui["request_contract"][
                "source_type_video_file"
            ],
            "search_request_agent_mode_false": ui["request_contract"][
                "agent_mode_false"
            ],
            "search_request_empty_sources": ui["request_contract"][
                "empty_video_sources"
            ],
            "search_request_null_time_range": ui["request_contract"][
                "null_time_range"
            ],
            "critic_default_enabled": receipt["pre_state"]["critic"][
                "runtime_default_enabled"
            ],
            "critic_disable_env_supported": receipt["pre_state"]["critic"][
                "disable_env_supported"
            ],
            "critic_input_order": ui["critic_contract"]["input_order"],
            "critic_rendered_order": ui["critic_contract"]["rendered_order"],
            "critic_rendered_card_count": ui["critic_contract"][
                "rendered_card_count"
            ],
            "critic_similarities": ui["critic_contract"]["similarities"],
            "real_local_confirmed_critic_cards": critic["confirmed_card_count"],
            "browser_local_time_without_conversion": ui["time_contract"][
                "local_time_without_offset_conversion"
            ],
            "real_vst_picture_status": selected_qualification[
                "real_vst_picture_status"
            ],
            "real_video_analytics_frames_status": selected_qualification[
                "real_video_analytics_frames_status"
            ],
            "selectable_bbox_count": selected_qualification[
                "selectable_bbox_count"
            ],
            "selected_object_seed_excluded": selected_qualification[
                "selected_object_seed_excluded"
            ],
            "human_facing_source_name_preserved": selected_qualification[
                "human_facing_source_name_preserved"
            ],
            "desktop_horizontal_overflow": False,
            "mobile_horizontal_overflow": False,
            "browser_actions": receipt["bounds"]["browser_actions"],
            "loopback_browser_responses": receipt["bounds"][
                "loopback_browser_responses"
            ],
            "persistent_mutations": receipt["bounds"]["persistent_mutations"],
        },
        "browser_diagnostics": {
            "console_errors": len(diagnostics["console_error_hashes"]),
            "console_warnings": len(diagnostics["console_warning_hashes"]),
            "page_errors": len(diagnostics["page_error_hashes"]),
            "unexpected_request_failures": len(
                diagnostics["request_failure_hashes"]
            ),
            "expected_chat_audio_probe_abort_requests": diagnostics[
                "expected_audio_probe_abort_count"
            ],
            "failing_http_responses": len(diagnostics["failing_response_hashes"]),
            "non_loopback_requests": diagnostics["non_loopback_request_count"],
            "non_loopback_responses": diagnostics["non_loopback_response_count"],
            "non_loopback_websockets": diagnostics[
                "non_loopback_websocket_count"
            ],
            "framework_error_overlays": diagnostics[
                "framework_error_overlay_count"
            ],
        },
        "cleanup": {
            "mutation": cleanup["mutation"],
            "runtime_unchanged": cleanup["runtime_unchanged"],
            "selected_object_evidence_reverified": cleanup[
                "selected_object_evidence_reverified"
            ],
            "critic_runtime_evidence_reverified": cleanup[
                "critic_runtime_evidence_reverified"
            ],
            "isolated_browser_closed": cleanup["isolated_browser_closed"],
            "temporary_screenshot_deleted_after_hashing": cleanup[
                "temporary_screenshot_deleted_after_hashing"
            ],
            "persistent_mutations": cleanup["persistent_mutations"],
        },
        "retention": {
            "raw_vectors": False,
            "raw_prompts": False,
            "raw_responses": False,
            "raw_urls": False,
            "raw_runtime_identifiers": False,
        },
        "warehouse_sample_bundle": "excluded",
    }
    return evidence


def _serialized(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")


def _atomic_write(value: Mapping[str, Any]) -> None:
    raw = _serialized(value)
    descriptor, temporary = tempfile.mkstemp(prefix=".official-evidence.", dir=HERE)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, OUTPUT_PATH)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        evidence = build()
        if args.write:
            _atomic_write(evidence)
            print(
                json.dumps(
                    {
                        "package_id": PACKAGE_ID,
                        "status": "written",
                        "promotion_eligible": True,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(_serialized(evidence).decode("ascii"), end="")
        return 0
    except (EvidenceError, KeyError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
