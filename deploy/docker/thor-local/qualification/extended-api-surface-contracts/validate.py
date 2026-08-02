#!/usr/bin/env python3
"""Fail-closed static validator for the Thor extended API surface contract."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
DEFAULT_CONTRACT = HERE / "contract.json"
DEFAULT_SCHEMA = HERE / "contract.schema.json"
CORE_API_INVENTORY_PATH = "deploy/docker/thor-local/qualification/api_inventory.json"
CORE_SURFACE_IDS = {
    "agent",
    "alerts",
    "lvs",
    "lvs-mcp",
    "rt-cv",
    "rt-embed",
    "rt-vlm",
    "va-mcp",
    "video-analytics",
    "vios-live",
    "vios-mcp",
    "vios-proxy",
    "vios-recorder",
    "vios-replay",
    "vios-sensor",
    "vios-storage",
    "vios-stream-bridge",
}
EXCLUDED_OFFICIAL_SURFACES = [
    "auto-calibration",
    "deepstream-configurator",
    "legacy-calibration",
    "sdrc-controller-router-workload-coordinator",
    "vss-configurator-sensor-management",
]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_OPERATIONS: dict[str, list[tuple[str, str]]] = {
    "vss-configurator-sensor": [
        ("POST", "/calibration"),
        ("GET", "/download"),
        ("GET", "/cameras"),
        ("GET", "/groups"),
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("GET", "/video-upload-status"),
    ],
    "sdrc-controller": [
        ("GET", "/healthz"),
        ("GET", "/metrics"),
        ("POST", "/report"),
        ("GET", "/get_agent_data"),
        ("GET", "/yy"),
        ("GET", "/stream2"),
        ("GET", "/stream"),
    ],
    "sdrc-router": [
        ("GET", "/openapi.json"),
        ("GET", "/"),
        ("POST", "/v3/discovery:clusters"),
        ("POST", "/v3/discovery:routes"),
        ("GET", "/dashboard"),
        ("GET", "/dashboard/health"),
        ("GET", "/dashboard/clusterxds"),
        ("GET", "/dashboard/config_yml"),
        ("POST", "/dashboard/global_add"),
        ("GET", "/sdrc/{wl_obj_name}"),
        ("POST", "/sdrc/{wl_obj_name}"),
        ("PUT", "/sdrc/{wl_obj_name}"),
        ("PATCH", "/sdrc/{wl_obj_name}"),
        ("DELETE", "/sdrc/{wl_obj_name}"),
        ("HEAD", "/sdrc/{wl_obj_name}"),
        ("OPTIONS", "/sdrc/{wl_obj_name}"),
    ],
    "sdrc-workload-coordinator": [
        ("GET", "/openapi.json"),
        ("GET", "/"),
        ("GET", "/healthz"),
        ("GET", "/reset"),
        ("GET", "/get_config"),
        ("GET", "/replicas"),
        ("GET", "/getwl"),
        ("GET", "/getpoddns"),
        ("POST", "/v3/discovery:routes"),
        ("POST", "/v3/discovery:clusters"),
        ("GET", "/stream"),
        ("GET", "/current_distributed_streams_cache"),
        ("GET", "/current_distributed_streams_name_id_url"),
        ("GET", "/current_streamid_address_mapping"),
        ("GET", "/redis_cache_data"),
        ("POST", "/cache_metadata_update"),
        ("GET", "/metrics"),
        ("POST", "/apply_metadata_payload"),
        ("POST", "/remove_stream"),
        ("GET", "/get_wl_replica_data"),
        ("GET", "/pod_list"),
        ("GET", "/down_pods"),
        ("GET", "/getpodInfo"),
    ],
    "deepstream-configurator": [("POST", "/config")],
    "auto-calibration": [
        ("GET", "/v1/ready"),
        ("POST", "/v1/create_project"),
        ("POST", "/v1/upload_video_files/{project_id}"),
        ("POST", "/v1/config/{project_id}"),
        ("POST", "/v1/upload_alignment/{project_id}"),
        ("POST", "/v1/upload_layout/{project_id}"),
        ("POST", "/v1/upload_gt_file/{project_id}"),
        ("POST", "/v1/upload_focal_length/{project_id}"),
        ("POST", "/v1/verify_project/{project_id}"),
        ("POST", "/v1/calibrate/{project_id}"),
        ("POST", "/v1/stop_calibration/{id}"),
        ("GET", "/v1/get_project_info/{project_id}"),
        ("GET", "/v1/result/{project_id}/evaluation_statistics"),
        ("GET", "/v1/result/{project_id}/overlay_image"),
        ("GET", "/v1/amc/calibrate/{project_id}/log"),
        ("GET", "/v1/calibrate/{project_id}/log/{type}/stream"),
        ("POST", "/v1/vggt/calibrate/{project_id}"),
        ("GET", "/v1/vggt_results/{project_id}/evaluation_statistics"),
        ("GET", "/v1/result/{project_id}/mv3dt_result"),
        ("POST", "/v1/rtsp/capture/{project_id}"),
        ("GET", "/v1/rtsp/capture/{project_id}/{session_id}"),
        ("POST", "/v1/rtsp/capture/{project_id}/{session_id}/ingest"),
        ("POST", "/v1/rtsp/capture/{project_id}/{session_id}/stop"),
        ("GET", "/v1/rtsp/sessions/{project_id}"),
        ("DELETE", "/v1/rtsp/session/{project_id}/{session_id}"),
        ("DELETE", "/v1/delete_project/{id}"),
    ],
    "legacy-calibration": [
        ("GET", "/api/projects/"),
        ("POST", "/api/projects/"),
        ("GET", "/api/projects/{project_id}/"),
        ("PATCH", "/api/projects/{project_id}/"),
        ("DELETE", "/api/projects/{project_id}/"),
        ("GET", "/api/sensors/{sensor_id}/"),
        ("PATCH", "/api/sensors/{sensor_id}/"),
        ("GET", "/api/approxHomography/{sensor_id}/"),
        ("GET", "/api/homography/{sensor_id}/"),
        ("GET", "/api/invertImage/{sensor_id}/"),
        ("GET", "/api/importSensors/{project_id}/"),
        ("GET", "/api/getWarpedFiles/{project_id}/"),
        ("GET", "/api/getImageFiles/{project_id}/"),
        ("GET", "/api/uploadWebApi/{project_id}/"),
    ],
}

EXPECTED_IMAGES = {
    "vss-configurator-image": {
        "digest": "sha256:35e3e31e7d9e62b298d6dbcb91244d54b0686845227f26e46f886493e9fe4504",
        "size": 149205524,
        "files": {
            "usr/src/app/mtmc_configurator.py": (
                "9ad445b445c0eb3631f4b52ad020410e1071889010c6c1a5de6f3c870f2b9d6b",
                71728,
            )
        },
    },
    "sdrc-image": {
        "digest": "sha256:7f98d296295a60ccd59c23b4c23ff0c72bfa01a669279c43896ed8d196f14069",
        "size": 1214578191,
        "files": {
            "wdm/lib/controller/__init__.py": (
                "15e854e135304526a502aeccf0764b0ebad82dc0bcc1ef74e39b41ba973a6ab0",
                18223,
            ),
            "wdm/static/controller-swagger.json": (
                "44ee8a5e67cacbb242c780bc3d7c1f8fc762bb0675b28cdc3571a020eabeb778",
                3499,
            ),
            "wdm/lib/wdm_router_openapi.py": (
                "6d38387c8c3ae239bfe911c24aa403d1308fc862777d600b18920bee4eedd5cf",
                16477,
            ),
            "wdm/app.py": (
                "c02f9e485dd2876e404263cac10f404d690a4b8648c612d88bad25b6fbcd8dd7",
                132863,
            ),
            "wdm/static/agent-swagger.json": (
                "5ff1b701a08fb7599ba8b6a82a784568e6cb2812f8a3ada8d6c91d5baff5a526",
                4500,
            ),
            "wdm/static/swagger.json": (
                "32bc5fc1c0a8971b3e179e4306ba2f5e5b967c0221da8525a33f12aa18cc4db8",
                4484,
            ),
        },
    },
    "deepstream-configurator-image": {
        "digest": "sha256:f7967b26377313fe0131c251ae203f70b9743b3edf61fa5b68d21f822dbbb340",
        "size": 33689003,
        "files": {
            "usr/src/app/app.py": (
                "85d15b4c7135fe338ca8f23249045c126cd2b77fcad60b86a9fb2578a4faabfe",
                5944,
            )
        },
    },
}

LEGACY_REGISTRY_CHILD_DIGEST = (
    "sha256:92dc91595316e10a85d0e6bc0bf9c2f2921b07030a246f9c0854ae6b61426ad8"
)
LEGACY_REGISTRY_NON_RUNTIME_DIGEST = (
    "sha256:a1660162ab57e5639a2a838b8b5a791327d2584801e00847f85dae6db059856b"
)
LEGACY_REGISTRY_REFERENCE = (
    "nvcr.io/nvidia/vss-core/calibration@" + LEGACY_REGISTRY_CHILD_DIGEST
)
LEGACY_REGISTRY_METADATA_SOURCE = (
    "https://api.ngc.nvidia.com/v2/repos/nvidia/vss-core/calibration"
    "?resolve-labels=true&remove-unresolved-labels=true"
)
LEGACY_PULL_COMMAND = "docker pull --platform=linux/amd64 " + LEGACY_REGISTRY_REFERENCE


class ContractError(ValueError):
    """Raised when the reviewed contract is incomplete or has drifted."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path}: {exc}") from exc


def canonical_contract_hash(document: dict[str, Any]) -> str:
    payload = {
        key: value for key, value in document.items() if key != "contract_set_sha256"
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _resolve_source(repo_root: Path, relative: str) -> Path:
    _require(
        relative and not relative.startswith("/"), f"unsafe source path: {relative!r}"
    )
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ContractError(f"source escapes repository: {relative}") from exc
    _require(candidate.is_file(), f"source is missing or not a file: {relative}")
    _require(not candidate.is_symlink(), f"source is a symlink: {relative}")
    return candidate


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324 - Git object identity


def _validate_schema(document: dict[str, Any], schema_path: Path) -> None:
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ContractError(f"schema validation failed at {location}: {first.message}")


def _validate_checkout_provenance(
    provenance: dict[str, Any], repo_root: Path, label: str
) -> None:
    for index, source in enumerate(provenance["files"]):
        path = _resolve_source(repo_root, source["path"])
        content = path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        _require(
            HEX64.fullmatch(source["content_sha256"]) is not None,
            f"{label}[{index}]: invalid SHA-256",
        )
        _require(
            actual_sha == source["content_sha256"],
            f"{label}[{index}]: source SHA-256 drift: {source['path']}",
        )
        _require(
            HEX40.fullmatch(source["git_blob_oid"]) is not None,
            f"{label}[{index}]: invalid Git blob OID",
        )
        _require(
            _git_blob_oid(content) == source["git_blob_oid"],
            f"{label}[{index}]: Git blob drift: {source['path']}",
        )


def _validate_image_provenance(provenance: dict[str, Any]) -> None:
    expected = EXPECTED_IMAGES.get(provenance["id"])
    _require(expected is not None, f"unexpected image provenance: {provenance['id']}")
    digest = expected["digest"]
    _require(
        provenance["image_digest"] == digest, f"{provenance['id']}: image digest drift"
    )
    _require(provenance["image_id"] == digest, f"{provenance['id']}: image ID drift")
    _require(
        provenance["image_reference"].endswith("@" + digest),
        f"{provenance['id']}: reference is not digest-pinned",
    )
    _require(
        provenance["local_size_bytes"] == expected["size"],
        f"{provenance['id']}: image size drift",
    )
    _require(
        provenance["architecture"] == "arm64" and provenance["os"] == "linux",
        f"{provenance['id']}: platform drift",
    )
    _require(
        provenance["required_at_validation"] is False,
        f"{provenance['id']}: validation must remain image-independent",
    )
    actual_files = {
        item["path"]: (item["content_sha256"], item["size_bytes"])
        for item in provenance["files"]
    }
    _require(
        actual_files == expected["files"],
        f"{provenance['id']}: extracted file lock drift",
    )


def _validate_registry_provenance(provenance: dict[str, Any]) -> None:
    _require(
        provenance["id"] == "legacy-calibration-registry",
        "unexpected registry provenance",
    )
    _require(
        provenance["metadata_source"] == LEGACY_REGISTRY_METADATA_SOURCE,
        "legacy registry metadata source drift",
    )
    _require(
        provenance["mutable_tag"] == "nvcr.io/nvidia/vss-core/calibration:3.2.1",
        "legacy registry mutable tag drift",
    )
    _require(
        provenance["pinned_child_reference"] == LEGACY_REGISTRY_REFERENCE
        and provenance["child_manifest_digest"] == LEGACY_REGISTRY_CHILD_DIGEST,
        "legacy registry child digest drift",
    )
    _require(
        provenance["child_os"] == "linux"
        and provenance["child_architecture"] == "amd64",
        "legacy registry child platform drift",
    )
    _require(
        provenance["compressed_size_bytes"] == 981287603,
        "legacy registry compressed size drift",
    )
    _require(
        provenance["published_runtime_variants"]
        == [
            {
                "digest": LEGACY_REGISTRY_CHILD_DIGEST,
                "os": "linux",
                "architecture": "amd64",
                "compressed_size_bytes": 981287603,
            }
        ],
        "legacy registry runnable variants drift",
    )
    _require(
        provenance["non_runtime_descriptors"]
        == [
            {
                "digest": LEGACY_REGISTRY_NON_RUNTIME_DIGEST,
                "os": "unknown",
                "architecture": "unknown",
                "compressed_size_bytes": 1166,
            }
        ],
        "legacy registry non-runtime descriptor drift",
    )
    _require(
        provenance["registry_repository_multi_architecture"] is True
        and provenance["arm64_variant_present"] is False,
        "legacy registry ARM64 availability drift",
    )
    _require(
        provenance["local_presence_observed"] is False
        and provenance["runtime_state"] == "blocked_architecture",
        "legacy local/runtime architecture boundary drift",
    )
    _require(
        provenance["manifest_access_state"] == "denied"
        and provenance["tag_index_digest"] is None
        and provenance["unpacked_size_bytes"] is None,
        "legacy unresolved registry fields must remain fail-closed",
    )
    _require(
        provenance["observed_at"] == "2026-08-01"
        and provenance["required_at_validation"] is False,
        "legacy registry observation boundary drift",
    )
    _require(
        provenance["lower_bound_provenance_id"] == "legacy-calibration-checkout",
        "legacy registry lower-bound provenance drift",
    )
    _require(
        provenance["approval_boundaries"]
        == {
            "pull_requires_explicit_approval": True,
            "pull_approved_at_audit": False,
            "pull_performed_at_audit": False,
            "pull_platform": "linux/amd64",
            "pull_reference": LEGACY_REGISTRY_REFERENCE,
            "pull_command_after_approval": LEGACY_PULL_COMMAND,
            "container_create_or_run_requires_separate_approval": True,
            "host_emulation_requires_separate_approval": True,
            "image_removal_or_prune_requires_separate_approval": True,
            "runtime_qualification_allowed_from_registry_metadata": False,
        },
        "legacy registry approval boundary drift",
    )


def _extract_amc_catalog(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name, value = node.targets[0].id, node.value
        if name == "REQUIRED_OPENAPI" and value is not None:
            catalog = ast.literal_eval(value)
            _require(
                isinstance(catalog, dict), "AMC REQUIRED_OPENAPI is not a dictionary"
            )
            return [(method.upper(), route) for route, method in catalog.items()]
    raise ContractError("AMC REQUIRED_OPENAPI catalog is missing")


def _validate_core_denominator(
    provenance: dict[str, Any],
    repo_root: Path,
    scope: dict[str, Any],
    recoverable_total: int,
) -> None:
    files = provenance["files"]
    _require(
        len(files) == 1 and files[0]["path"] == CORE_API_INVENTORY_PATH,
        "core API inventory provenance drift",
    )
    inventory = load_json(_resolve_source(repo_root, CORE_API_INVENTORY_PATH))
    surfaces = inventory.get("surfaces")
    _require(isinstance(surfaces, list), "core API inventory surfaces are invalid")
    surface_ids = [item.get("id") for item in surfaces if isinstance(item, dict)]
    _require(
        len(surface_ids) == 17
        and len(set(surface_ids)) == 17
        and set(surface_ids) == CORE_SURFACE_IDS,
        "core API inventory surface denominator drift",
    )
    inventory_scope = inventory.get("scope")
    _require(isinstance(inventory_scope, dict), "core API inventory scope is invalid")
    _require(
        inventory_scope.get("complete_product_api") is False
        and inventory_scope.get("excluded_official_surfaces")
        == EXCLUDED_OFFICIAL_SURFACES,
        "core API inventory incomplete-product boundary drift",
    )
    totals = inventory.get("expected_totals")
    _require(
        totals
        == {
            "declared_rest_operations": 342,
            "normalized_unique_rest_operations": 341,
            "official_declared_rest_operations": 338,
            "official_normalized_unique_rest_operations": 337,
            "thor_local_extension_operations": 4,
            "mcp_tools": 42,
            "mcp_prompts": 5,
        },
        "core API inventory totals drift",
    )
    declared = totals["declared_rest_operations"]
    normalized = totals["normalized_unique_rest_operations"]
    official_declared = totals["official_declared_rest_operations"]
    official_normalized = totals["official_normalized_unique_rest_operations"]
    local_extensions = totals["thor_local_extension_operations"]
    legacy_minimum = scope["legacy_minimum_operation_count"]
    _require(
        scope["core_surface_count_observed"] == len(surface_ids)
        and scope["core_declared_rest_operations_observed"] == declared
        and scope["core_normalized_rest_operations_observed"] == normalized
        and scope["core_official_declared_rest_operations_observed"]
        == official_declared
        and scope["core_official_normalized_rest_operations_observed"]
        == official_normalized
        and scope["core_thor_local_extension_operations_observed"] == local_extensions,
        "scope core API denominator drift",
    )
    _require(
        scope["complete_declared_rest_formula"] == f"{declared + recoverable_total} + L"
        and scope["complete_normalized_rest_formula"]
        == f"{normalized + recoverable_total} + L",
        "complete API formula drift",
    )
    _require(
        scope["complete_official_declared_rest_formula"]
        == f"{official_declared + recoverable_total} + L"
        and scope["complete_official_normalized_rest_formula"]
        == f"{official_normalized + recoverable_total} + L",
        "complete official API formula drift",
    )
    _require(
        scope["minimum_declared_rest_operations"]
        == declared + recoverable_total + legacy_minimum
        and scope["minimum_normalized_rest_operations"]
        == normalized + recoverable_total + legacy_minimum,
        "minimum API denominator drift",
    )
    _require(
        scope["minimum_official_declared_rest_operations"]
        == official_declared + recoverable_total + legacy_minimum
        and scope["minimum_official_normalized_rest_operations"]
        == official_normalized + recoverable_total + legacy_minimum,
        "minimum official API denominator drift",
    )


def validate(document: dict[str, Any], schema_path: Path, repo_root: Path) -> None:
    _validate_schema(document, schema_path)
    _require(
        document["contract_set_sha256"] == canonical_contract_hash(document),
        "contract_set_sha256 mismatch",
    )

    surfaces = document["surfaces"]
    by_id = {surface["id"]: surface for surface in surfaces}
    _require(
        len(by_id) == 7 and set(by_id) == set(EXPECTED_OPERATIONS),
        "seven-surface denominator drift",
    )
    _require(
        len({surface["claim_id"] for surface in surfaces}) == 5,
        "advertised claim-family denominator drift",
    )

    recoverable_total = 0
    for surface_id, expected_operations in EXPECTED_OPERATIONS.items():
        surface = by_id[surface_id]
        actual = [(item["method"], item["path"]) for item in surface["operations"]]
        _require(len(actual) == len(set(actual)), f"{surface_id}: duplicate operation")
        _require(
            actual == expected_operations,
            f"{surface_id}: exact operation descriptor drift",
        )
        _require(
            surface["minimum_operation_count"] == len(actual),
            f"{surface_id}: minimum count drift",
        )
        _require(
            surface["runtime_state"] == "not_qualified"
            and not surface["runtime_evidence"],
            f"{surface_id}: static descriptor must not claim runtime evidence",
        )
        if surface_id == "legacy-calibration":
            _require(
                surface["contract_state"] == "authoritative_unknown",
                "legacy contract must remain authoritative_unknown",
            )
            _require(
                surface["operation_count"] is None, "legacy L must remain unresolved"
            )
            _require(
                all(
                    item["evidence"] == "client_lower_bound"
                    for item in surface["operations"]
                ),
                "legacy operations must remain lower-bound witnesses",
            )
            _require(
                surface["provenance_id"] == "legacy-calibration-registry",
                "legacy registry provenance link drift",
            )
        else:
            _require(
                surface["contract_state"] == "exact_descriptor",
                f"{surface_id}: exact state drift",
            )
            _require(
                surface["operation_count"] == len(actual),
                f"{surface_id}: exact count drift",
            )
            recoverable_total += len(actual)

    _require(recoverable_total == 80, "recoverable operation denominator is not 80")
    scope = document["scope"]
    _require(
        scope["recoverable_operation_count"] == recoverable_total,
        "scope recoverable total drift",
    )
    _require(
        scope["complete_product_api"] is False,
        "package must not claim complete product API",
    )
    _require(
        scope["warehouse_sample_required"] is False, "warehouse sample exclusion drift"
    )
    _require(
        scope["shared_ledgers_modified"] is False,
        "isolated package must not claim shared-ledger integration",
    )

    reset = next(
        item
        for item in by_id["sdrc-workload-coordinator"]["operations"]
        if item["path"] == "/reset"
    )
    _require(
        reset
        == {
            "method": "GET",
            "path": "/reset",
            "evidence": "published_schema_and_implementation",
            "mutation": "mutating",
        },
        "GET /reset mutation guard drift",
    )
    implementation_only = {
        (item["method"], item["path"])
        for item in by_id["sdrc-workload-coordinator"]["operations"]
        if item["evidence"] == "implementation_only"
    }
    _require(
        implementation_only
        == {
            ("GET", "/openapi.json"),
            ("GET", "/"),
            ("GET", "/redis_cache_data"),
            ("POST", "/remove_stream"),
            ("GET", "/pod_list"),
            ("GET", "/down_pods"),
        },
        "SDRC 17-schema/23-implementation discrepancy drift",
    )

    provenance = {item["id"]: item for item in document["extraction_provenance"]}
    _require(len(provenance) == 7, "provenance denominator drift")
    _require(
        set(provenance)
        == set(EXPECTED_IMAGES)
        | {
            "auto-calibration-checkout",
            "core-api-inventory-checkout",
            "legacy-calibration-checkout",
            "legacy-calibration-registry",
        },
        "provenance identity drift",
    )
    for item in provenance.values():
        if item["type"] == "pinned_local_image_snapshot":
            _validate_image_provenance(item)
        elif item["type"] == "checked_in_source_snapshot":
            _validate_checkout_provenance(item, repo_root, item["id"])
        else:
            _validate_registry_provenance(item)
    _require(
        {surface["provenance_id"] for surface in surfaces} <= set(provenance),
        "surface references unknown provenance",
    )

    _validate_core_denominator(
        provenance["core-api-inventory-checkout"],
        repo_root,
        scope,
        recoverable_total,
    )

    amc_source = _resolve_source(
        repo_root, provenance["auto-calibration-checkout"]["files"][0]["path"]
    )
    _require(
        _extract_amc_catalog(amc_source) == EXPECTED_OPERATIONS["auto-calibration"],
        "AMC checked-in catalog differs from descriptor",
    )


def run(
    contract_path: Path, schema_path: Path, repo_root: Path, *, json_output: bool
) -> int:
    try:
        document = load_json(contract_path)
        validate(document, schema_path, repo_root)
    except (ContractError, ast.SyntaxError, ValueError, TypeError, KeyError) as exc:
        if json_output:
            print(json.dumps({"result": "fail", "error": str(exc)}, sort_keys=True))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    result = {
        "result": "pass",
        "surface_count": 7,
        "recoverable_surface_count": 6,
        "recoverable_operation_count": 80,
        "legacy_contract_state": "authoritative_unknown",
        "legacy_minimum_operation_count": 14,
        "legacy_registry_child_architecture": "amd64",
        "legacy_registry_arm64_variant_present": False,
        "legacy_registry_local_presence_observed": False,
        "legacy_registry_runtime_state": "blocked_architecture",
        "legacy_registry_tag_index_digest": None,
        "legacy_registry_unpacked_size_bytes": None,
        "legacy_registry_pull_approved": False,
        "complete_product_api": False,
        "docker_required": False,
        "warehouse_sample_required": False,
    }
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "PASS: validated 7 extended API surfaces — 6 exact descriptors / "
            "80 operations; legacy remains authoritative_unknown with L>=14"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return run(args.contract, args.schema, args.repo_root, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
