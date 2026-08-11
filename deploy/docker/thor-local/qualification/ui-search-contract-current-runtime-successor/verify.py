#!/usr/bin/env python3
"""Offline, fail-closed verification of the complete current Search UI contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
EXPECTED = {
    "builder": "07cd40213183e2afb4e6c85df5afa4f214c054d3d0eb85010cce4c1811649297",
    "contract": "71dec2ac7077970df573a6d09181db546ff21d58ac7783fb42601eb75e111230",
    "evidence": "5e0fcda66f79fca334cc03e1e65b54a68e861e47a75ea7c11afcafb372ceab40",
    "executor": "d9c4a7608f4bb55847f4b46eb00251e298d38b86ba9666e1399dffcecf4d5057",
    "harness": "de42182a83702bf5d9960220dd380bd9999fe5f34a2194a2e57c1b6abc4d8537",
    "receipt": "314c314b6250310d6ab2a7cd0ed5d92463a971dac829599e240c506d06fc0867",
    "schema": "a90b00352474426b20815bccdc7bc7e340056ebcd1469b31b42c557a8d8aa413",
}
RAW_URL_RE = re.compile(r"(?:https?|wss?)://", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:nvapi-|api[_-]?key|authorization\s*[:=]|bearer\s+)", re.IGNORECASE
)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class VerificationError(RuntimeError):
    """Retained Search UI evidence is inconsistent, incomplete, or drifted."""


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
            parse_constant=lambda item: (_ for _ in ()).throw(
                VerificationError(f"non-finite value in {path.name}: {item}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    if len(expected) != 20 or len(expected) != len(contract["source_locks"]):
        raise VerificationError("source-lock inventory drifted")
    if receipt["identity"]["source_hashes"] != expected:
        raise VerificationError("receipt source-lock projection drifted")
    for relative, digest in expected.items():
        if _sha(_repo_path(relative).read_bytes()) != digest:
            raise VerificationError(f"source lock drifted: {relative}")


def _verify_runtime(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    before = receipt["pre_state"]
    after = receipt["post_state"]
    if before != after:
        raise VerificationError("runtime or critic state changed during qualification")
    expected_critic = {
        "runtime_default_enabled": True,
        "compose_default_enabled": True,
        "profile_default_enabled": True,
        "request_default_enabled": True,
        "disable_env_supported": True,
    }
    if before["critic"] != expected_critic:
        raise VerificationError("critic default/disable contract drifted")
    for expected in contract["runtime"].values():
        observed = before["runtime"][expected["container"]]
        if (
            observed["configured_image"] != expected["configured_image"]
            or observed["image_id"] != expected["image_id"]
            or observed["running"] is not True
            or observed["restart_count"] != 0
            or observed["oom_killed"] is not False
        ):
            raise VerificationError(f"runtime identity drifted: {expected['container']}")


def _verify_dependencies(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    selected = receipt["identity"]["selected_object_evidence"]
    critic = receipt["identity"]["critic_runtime_evidence"]
    expected_selected = contract["selected_object_evidence"]
    expected_critic = contract["critic_runtime_evidence"]
    if (
        selected["contract_sha256"] != expected_selected["contract_sha256"]
        or selected["official_runtime_evidence_sha256"]
        != expected_selected["official_runtime_evidence_sha256"]
        or selected["verifier_sha256"] != expected_selected["verifier_sha256"]
        or selected["passed"] is not True
    ):
        raise VerificationError("selected-object dependency drifted")
    if (
        critic["contract_sha256"] != expected_critic["contract_sha256"]
        or critic["runtime_receipt_sha256"]
        != expected_critic["runtime_receipt_sha256"]
        or critic["verifier_sha256"] != expected_critic["verifier_sha256"]
        or critic["confirmed_card_count"] < expected_critic["required_confirmed_cards"]
        or critic["passed"] is not True
    ):
        raise VerificationError("real local critic dependency drifted")


def _verify_semantics(contract: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    ui = receipt["ui_semantics"]
    if ui["source_contract"] != {
        "default_video_file": True,
        "values": ["Video File", "RTSP"],
        "rtsp_and_video_file_round_trip": True,
    }:
        raise VerificationError("source contract drifted")
    if ui["filter_contract"] != {
        "defaults": {"top_k": 10, "similarity": -1},
        "top_k_minimum": 1,
        "top_k_minimum_selected": True,
    }:
        raise VerificationError("filter contract drifted")
    request = ui["request_contract"]
    if (
        request["query_sha256"] != contract["fixture"]["query_contract"]["sha256"]
        or request["query_bytes"] != contract["fixture"]["query_contract"]["bytes"]
        or request["top_k"] != 1
        or any(
            request[key] is not True
            for key in (
                "source_type_video_file",
                "agent_mode_false",
                "empty_video_sources",
                "null_time_range",
            )
        )
    ):
        raise VerificationError("Search request contract drifted")
    critic = ui["critic_contract"]
    if (
        critic["fixture_response_status"] != 200
        or critic["fixture_response_intercepted_once"] is not True
        or critic["input_order"] != contract["fixture"]["response_input_order"]
        or critic["rendered_order"] != contract["fixture"]["expected_render_order"]
        or critic["rendered_card_count"] != 3
        or critic["similarities"] != [-1, 0.25, 1]
    ):
        raise VerificationError("critic ordering or similarity contract drifted")
    if ui["time_contract"]["local_time_without_offset_conversion"] is not True:
        raise VerificationError("browser-local time contract drifted")
    for viewport in ("desktop", "mobile"):
        overflow = ui[viewport]["overflow"]
        if overflow["document"] > overflow["viewport"] or overflow["body"] > overflow["viewport"]:
            raise VerificationError("horizontal overflow")
    diagnostics = ui["diagnostics"]
    for key in (
        "console_error_hashes",
        "console_warning_hashes",
        "page_error_hashes",
        "request_failure_hashes",
        "failing_response_hashes",
    ):
        if diagnostics[key] != []:
            raise VerificationError(f"unexpected browser diagnostic: {key}")
    if diagnostics["expected_audio_probe_abort_count"] != 1:
        raise VerificationError("Chat audio-probe boundary drifted")
    for key in (
        "non_loopback_request_count",
        "non_loopback_response_count",
        "non_loopback_websocket_count",
        "framework_error_overlay_count",
    ):
        if diagnostics[key] != 0:
            raise VerificationError(f"browser boundary drifted: {key}")
    response_count = sum(diagnostics["response_status_counts"].values())
    if response_count != receipt["bounds"]["loopback_browser_responses"]:
        raise VerificationError("browser response accounting drifted")


def _verify_cleanup(receipt: Mapping[str, Any]) -> None:
    if receipt["cleanup"] != {
        "mutation": "read_only",
        "isolated_browser_closed": True,
        "temporary_screenshot_deleted_after_hashing": True,
        "runtime_unchanged": True,
        "selected_object_evidence_reverified": True,
        "critic_runtime_evidence_reverified": True,
        "persistent_mutations": 0,
        "warehouse_sample_bundle": "excluded",
    }:
        raise VerificationError("read-only cleanup contract drifted")


def _builder_projection() -> dict[str, Any]:
    path = HERE / "build_official_evidence.py"
    spec = importlib.util.spec_from_file_location("ui_search_contract_evidence_builder", path)
    if spec is None or spec.loader is None:
        raise VerificationError("evidence builder cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    value = module.build()
    if not isinstance(value, dict):
        raise VerificationError("evidence builder returned an invalid projection")
    return value


def _verify_retention(receipt_raw: bytes, evidence_raw: bytes) -> None:
    for label, raw in (("receipt", receipt_raw), ("evidence", evidence_raw)):
        text = raw.decode("utf-8")
        if RAW_URL_RE.search(text):
            raise VerificationError(f"raw URL retained in {label}")
        if SECRET_RE.search(text):
            raise VerificationError(f"secret-shaped value retained in {label}")
        if UUID_RE.search(text):
            raise VerificationError(f"raw runtime UUID retained in {label}")
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
    if any(key in receipt_raw.decode("utf-8") for key in forbidden_keys):
        raise VerificationError("raw prompt, vector, URL, or runtime identifier retained")


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    schema, schema_raw = _load(HERE / "receipt.schema.json")
    observed = {
        "builder": _sha((HERE / "build_official_evidence.py").read_bytes()),
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
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt)
    )
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
    _verify_dependencies(contract, receipt)
    _verify_semantics(contract, receipt)
    _verify_cleanup(receipt)
    if evidence != _builder_projection():
        raise VerificationError("official evidence projection drifted")
    _verify_retention(receipt_raw, evidence_raw)
    return {
        "package_id": receipt["package_id"],
        "status": "passed",
        "promotion_eligible": True,
        "browser_actions": receipt["bounds"]["browser_actions"],
        "persistent_mutations": receipt["bounds"]["persistent_mutations"],
        "warehouse_sample_bundle": "excluded",
    }


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True))
        return 0
    except (VerificationError, KeyError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
