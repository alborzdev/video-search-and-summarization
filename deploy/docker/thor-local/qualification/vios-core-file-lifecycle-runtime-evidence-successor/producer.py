#!/usr/bin/env python3
"""Compile a source-locked, inert VIOS core future-runtime plan.

There is deliberately no product transport or execution adapter in this module.
The only CLI path verifies repository sources and prints a nonpromotable plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
EXPECTED_IDS = [
    "behavior.vios.upload-playback-remediation",
    "behavior.vios.byte-identical-download",
    "behavior.vios.sensor-add-conflicts",
    "configuration.vios.upload-effective-limit",
    "runtime.nvstreamer.file-streaming",
    "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support",
]
CPU_MULTIMEDIA_ID = "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"
CPU_MULTIMEDIA_RUNTIME_EVIDENCE = [
    {
        "capability_id": CPU_MULTIMEDIA_ID,
        "json_pointer": "/capability_results/0",
        "path": (
            "deploy/docker/thor-local/qualification/vios-codecs-runtime/"
            "official-runtime-evidence.json"
        ),
        "sha256": "a4bfd3a6562f95214624f7f84f8115162031285dc231b3f2e168ecb7233addab",
    }
]
ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
OFFICIAL_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
IMAGE_EVIDENCE_PATHS = {
    "deploy/docker/thor-local/parity/evidence/2026-07-31-industry-staging.md",
    "deploy/docker/thor-local/parity/evidence/2026-07-31-vios-media-offline.md",
    "deploy/docker/thor-local/parity/evidence/2026-07-31-vios-ui-audit.md",
}


class ProducerError(RuntimeError):
    """Fail-closed source or contract error."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _bounded_read(path: Path, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    if type(maximum) is not int or not 1 <= maximum <= MAX_SOURCE_BYTES:
        raise ProducerError("invalid source read bound")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProducerError(f"cannot open locked source: {path.name}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ProducerError(f"invalid locked source: {path.name}")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise ProducerError(f"locked source changed while reading: {path.name}")
        return raw
    finally:
        os.close(descriptor)


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProducerError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode(),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ProducerError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except ProducerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProducerError(f"invalid JSON: {label}") from exc


def _validate(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json(_bounded_read(schema_path), f"{label} schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ProducerError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: [str(item) for item in error.absolute_path],
    )
    if errors:
        location = "/" + "/".join(str(item) for item in errors[0].absolute_path)
        raise ProducerError(f"{label} schema violation at {location}")


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ProducerError("unsafe source lock path")
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ProducerError(f"missing source lock: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise ProducerError(f"symlinked source lock: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise ProducerError(f"source lock escaped repository: {relative}") from exc
    return current


def _load_contract(contract_path: Path) -> dict[str, Any]:
    contract = _strict_json(_bounded_read(contract_path), "contract")
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    return contract


def _load_sources(contract: dict[str, Any]) -> dict[str, bytes]:
    locks = contract["source_locks"]
    paths = [lock["path"] for lock in locks]
    if len(paths) != len(set(paths)):
        raise ProducerError("duplicate source lock path")
    sources: dict[str, bytes] = {}
    for lock in locks:
        raw = _bounded_read(_repo_file(lock["path"]))
        if _sha256(raw) != lock["sha256"]:
            raise ProducerError(f"source lock digest drift: {lock['path']}")
        sources[lock["path"]] = raw
    return sources


def _unique(items: Any, key: str, expected: Any, label: str) -> dict[str, Any]:
    if not isinstance(items, list):
        raise ProducerError(f"invalid {label} collection")
    matches = [
        item for item in items if isinstance(item, dict) and item.get(key) == expected
    ]
    if len(matches) != 1:
        raise ProducerError(f"expected exactly one {label}: {expected}")
    return matches[0]


def _verify_canonical_bindings(
    contract: dict[str, Any], sources: dict[str, bytes]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if contract["capability_ids"] != EXPECTED_IDS:
        raise ProducerError("capability set or order drift")
    if len({item["capability_id"] for item in contract["oracle_bindings"]}) != 6:
        raise ProducerError("oracle binding capability collision")

    oracle_doc = _strict_json(sources[ORACLES_PATH], "capability oracles")
    official_doc = _strict_json(sources[OFFICIAL_PATH], "official capabilities")
    oracle_by_id: dict[str, dict[str, Any]] = {}
    official_by_id: dict[str, dict[str, Any]] = {}
    for binding in contract["oracle_bindings"]:
        capability_id = binding["capability_id"]
        try:
            oracle = oracle_doc["oracles"][binding["index"]]
            official = official_doc["capabilities"][binding["official_index"]]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProducerError(
                f"canonical index does not resolve: {capability_id}"
            ) from exc
        if (
            oracle.get("capability_id") != capability_id
            or oracle.get("oracle_id") != binding["oracle_id"]
            or _sha256(_canonical_bytes(oracle)) != binding["oracle_canonical_sha256"]
        ):
            raise ProducerError(f"oracle binding drift: {capability_id}")
        if (
            official.get("id") != capability_id
            or _sha256(_canonical_bytes(official))
            != binding["official_canonical_sha256"]
        ):
            raise ProducerError(f"official capability binding drift: {capability_id}")
        if (
            oracle.get("current_state") != "open_unexecuted"
            or oracle.get("evidence") != []
            or oracle.get("execution_bounds", {}).get("warehouse_sample_bundle")
            != "excluded"
        ):
            raise ProducerError(f"unexpected runtime evidence state: {capability_id}")
        expected_runtime_state = (
            "passed_current" if capability_id == CPU_MULTIMEDIA_ID else "not_qualified"
        )
        if (
            official.get("acceptance_class") != "required_local"
            or official.get("runtime_state") != expected_runtime_state
        ):
            raise ProducerError(f"unexpected acceptance state: {capability_id}")
        if capability_id == CPU_MULTIMEDIA_ID:
            if official.get("runtime_evidence") != CPU_MULTIMEDIA_RUNTIME_EVIDENCE:
                raise ProducerError(
                    f"unexpected current runtime evidence: {capability_id}"
                )
        elif official.get("runtime_evidence"):
            raise ProducerError(f"unexpected open runtime evidence: {capability_id}")
        oracle_by_id[capability_id] = oracle
        official_by_id[capability_id] = official
    if set(oracle_by_id) != set(EXPECTED_IDS):
        raise ProducerError("canonical capability coverage drift")
    return oracle_by_id, official_by_id


def _verify_case_bounds(
    contract: dict[str, Any], oracle_by_id: dict[str, dict[str, Any]]
) -> None:
    cases = contract["cases"]
    if [case["capability_id"] for case in cases] != EXPECTED_IDS:
        raise ProducerError("case set or order drift")
    recipe_ids = {recipe["recipe_id"] for recipe in contract["fixture_recipes"]}
    for case in cases:
        oracle_bounds = oracle_by_id[case["capability_id"]]["execution_bounds"]
        if (
            case["max_actions"] != oracle_bounds["max_actions"]
            or case["max_requests"] != oracle_bounds["max_requests"]
        ):
            raise ProducerError(f"case bound drift: {case['capability_id']}")
        if not set(case["fixture_ids"]).issubset(recipe_ids):
            raise ProducerError(f"unknown fixture recipe: {case['capability_id']}")


def _verify_fixture_and_plan_bindings(
    contract: dict[str, Any], sources: dict[str, bytes]
) -> None:
    manifest_path = (
        "deploy/docker/thor-local/qualification/local20-fixture-pack/manifest.json"
    )
    manifest = _strict_json(sources[manifest_path], "Local20 manifest")
    manifest_recipes = {
        item.get("recipe_id"): item for item in manifest.get("media_recipes", [])
    }
    for recipe_id in (
        "tiny-identity-mp4-v1",
        "tiny-bframe-failing-mp4-v1",
        "tiny-bframe-reference-mp4-v1",
    ):
        if recipe_id not in manifest_recipes:
            raise ProducerError(f"missing Local20 recipe: {recipe_id}")

    remediation_path = (
        "deploy/docker/thor-local/qualification/"
        "systems-vios-playback-remediation/contract.json"
    )
    remediation = _strict_json(sources[remediation_path], "remediation plan")
    case = _unique(
        contract["cases"],
        "capability_id",
        "behavior.vios.upload-playback-remediation",
        "producer case",
    )
    if (
        [step["id"] for step in remediation.get("workflow", [])]
        != case["planned_steps"]
        or remediation.get("execution_bounds", {}).get("max_actions") != 9
        or remediation.get("execution_bounds", {}).get("max_requests") != 8
        or remediation.get("execution_bounds", {}).get("warehouse_sample_bundle")
        != "excluded"
    ):
        raise ProducerError("Local20 remediation plan binding drift")


def _verify_recorded_images(
    contract: dict[str, Any], sources: dict[str, bytes]
) -> None:
    if {
        identity["evidence_path"] for identity in contract["recorded_image_identities"]
    } != IMAGE_EVIDENCE_PATHS:
        raise ProducerError("image evidence path drift")
    for identity in contract["recorded_image_identities"]:
        if identity["kind"] != "repository_evidence_only":
            raise ProducerError("image identity is not repository-evidence-only")
        evidence = sources[identity["evidence_path"]].decode()
        if identity["image"] not in evidence or identity["digest"] not in evidence:
            raise ProducerError(f"recorded image identity drift: {identity['image']}")


def _verify_effective_limit_fix(sources: dict[str, bytes]) -> dict[str, Any]:
    source_path = (
        "services/vios/src/framework/web/http_server/HttpServerRequestHandler.cpp"
    )
    handler = sources[source_path].decode()
    route_marker = "const bool isUploadRequest = isFileUploadAPI("
    limit_marker = "MAX_FILE_UPLOAD_SIZE_MB_TO_BYTES("
    policy_marker = (
        "validateUploadContentLength(req_info->content_length, maxAllowedLength)"
    )
    bypass_marker = 'LOG(info) << "Upload API, skip parsing message"'
    route = handler.find(route_marker)
    configured_limit = handler.find(limit_marker, route)
    policy = handler.find(policy_marker, configured_limit)
    bypass = handler.find(bypass_marker, policy)
    if not 0 <= route < configured_limit < policy < bypass:
        raise ProducerError("effective-limit fix source ordering drift")
    upload_region = handler[route:bypass]
    if (
        "UploadContentLengthPolicy::Missing" not in upload_region
        or "Content-Length is required for file uploads" not in upload_region
        or "VmsErrorCode::InvalidParameterError" not in upload_region
        or "UploadContentLengthPolicy::TooLarge" not in upload_region
        or "VmsErrorCode::PayloadTooLargeError" not in upload_region
    ):
        raise ProducerError("effective-limit source fix no longer verified")
    if handler.count(route_marker) != 1:
        raise ProducerError("upload route must be computed exactly once")
    vst_config = _strict_json(
        sources["deploy/docker/thor-local/vios/vst_config.json"], "VST config"
    )
    if vst_config.get("data", {}).get("nv_streamer_max_upload_file_size_MB") != 25600:
        raise ProducerError("nvStreamer configured limit drift")
    nginx = sources["deploy/docker/services/vios/configs/nginx-vst.conf"].decode()
    if "client_max_body_size 25G;" not in nginx:
        raise ProducerError("nginx configured limit drift")
    return {
        "detected": False,
        "previous_gap": "upload-handler-early-return-bypassed-nvstreamer-content-length-gate",
        "source_fix_verified": True,
        "enforcement_scope": "per-request Content-Length",
        "unknown_length_policy": "reject",
        "current_nginx_limit": "25G",
        "current_nvstreamer_limit_mb": 25600,
        "current_equality_still_requires_asymmetric_runtime_matrix": True,
        "required_runtime_matrix": [
            "nginx_limit_below_nvstreamer_limit",
            "nvstreamer_limit_below_nginx_limit",
        ],
        "requires_code_fix_before_runtime_qualification": False,
        "runtime_qualified": False,
    }


def _ffmpeg_recipe_plan(recipe: dict[str, Any]) -> list[str]:
    video_encoder = "libx265" if recipe["codec"] == "h265" else "libx264"
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x120:rate=5:duration=2",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=48000",
        "-t",
        "2",
        "-map_metadata",
        "-1",
        "-c:v",
        video_encoder,
        "-threads",
        "1",
        "-bf",
        str(recipe["b_frames"]),
        "-g",
        str(recipe["keyint"]),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-metadata",
        "creation_time=1970-01-01T00:00:00Z",
        f"<authorized-output>/{recipe['recipe_id']}.mp4",
    ]


def compile_plan(contract_path: Path = CONTRACT_PATH) -> dict[str, Any]:
    """Verify all immutable inputs and return an inert non-evidence plan."""
    contract = _load_contract(contract_path)
    sources = _load_sources(contract)
    oracle_by_id, _ = _verify_canonical_bindings(contract, sources)
    _verify_case_bounds(contract, oracle_by_id)
    _verify_fixture_and_plan_bindings(contract, sources)
    _verify_recorded_images(contract, sources)
    effective_limit_gap = _verify_effective_limit_fix(sources)

    cases = []
    for case in contract["cases"]:
        cases.append(
            {
                **case,
                "runtime_evidence": False,
                "promotion_eligible": False,
            }
        )
    plan = {
        "schema_version": 1,
        "producer_id": contract["producer_id"],
        "mode": "offline-inert-plan-only",
        "status": "pass",
        "runtime_evidence": False,
        "aggregate_promotable": False,
        "promotion_eligible": False,
        "eligible_capability_ids": [],
        "runtime_actions": 0,
        "runtime_requests": 0,
        "product_calls": 0,
        "network_calls": 0,
        "docker_calls": 0,
        "service_lifecycle_calls": 0,
        "model_calls": 0,
        "subprocess_calls": 0,
        "warehouse_data_used": False,
        "source_preflight": {
            "verified": True,
            "source_lock_count": len(sources),
            "oracle_binding_count": len(contract["oracle_bindings"]),
            "recorded_image_identity_count": len(contract["recorded_image_identities"]),
            "image_identity_source": "repository-evidence-only",
        },
        "effective_limit_product_gap": effective_limit_gap,
        "fixture_plans": [
            {
                **recipe,
                "ffmpeg_invoked": False,
                "planned_argv": _ffmpeg_recipe_plan(recipe),
                "byte_identity_requires_authorized_same-tool-run": True,
            }
            for recipe in contract["fixture_recipes"]
        ],
        "cases": cases,
        "blockers": [
            "no VIOS or NvStreamer product/service response was observed",
            "cached image records contain no sensor-service digest or live service identity readback",
            "no media fixture was materialized, uploaded, streamed, played, downloaded, or removed",
            "five canonical two-request bounds are insufficient for their full contract plus ownership-safe restoration",
            "NvStreamer qualification requires upload, UI, and local-mount inputs plus RTSP, actual WebRTC, and removal",
            "VPN transport behavior is not proven by a local B-frame remediation run",
            "the corrected upload content-length gate has no Thor runtime response or asymmetric-limit evidence",
            "CPU multimedia is independently current-qualified by the source-locked codec runtime receipt; this inert VIOS-core producer neither duplicates nor supersedes that evidence",
            "a separately authorized service run and reviewed execution bounds are required before promotion",
        ],
    }
    _validate(plan, PLAN_SCHEMA_PATH, "plan")
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        plan = compile_plan()
    except ProducerError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
