#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Qualify the checked-in Thor-local VSS API contract without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from contract import (  # noqa: E402
    ContractError,
    build_mcp_manifest,
    build_rest_manifest,
    canonical_route,
    compare_manifest,
    extract_fastmcp_declarations,
    extract_lvs_mcp_tools,
    extract_markdown_routes,
    extract_python_routes,
    extract_swagger_yaml_operations,
    extract_va_mcp_tools,
    load_json_document,
    normalize_openapi_document,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
DEFAULT_INVENTORY = SCRIPT_DIR / "api_inventory.json"
DEFAULT_EXPECTED_DIR = SCRIPT_DIR / "expected"


def _repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError(f"unsafe repository-relative path: {relative!r}")
    resolved = REPO_ROOT / candidate
    if not resolved.is_file():
        raise ContractError(f"contract source is missing: {relative}")
    return resolved


def _source_files(surface: dict[str, Any]) -> list[tuple[str, Path]]:
    sources = surface.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ContractError(f"{surface.get('id')}: sources must be a non-empty list")
    return [(relative, _repo_path(relative)) for relative in sources]


def _apply_openapi_overrides(
    document: dict[str, Any], surface_id: str, overrides: Any
) -> None:
    """Apply reviewed profile-specific OpenAPI defaults without hiding drift."""

    if overrides is None:
        return
    if not isinstance(overrides, list):
        raise ContractError(f"{surface_id}: openapi_overrides must be a list")
    for index, override in enumerate(overrides):
        if not isinstance(override, dict):
            raise ContractError(
                f"{surface_id}: openapi override {index} must be an object"
            )
        operation = override.get("operation")
        required_keys = {"operation", "path", "value"}
        if operation == "replace":
            required_keys.add("expected")
        if operation not in {"add", "replace"} or set(override) != required_keys:
            raise ContractError(
                f"{surface_id}: openapi override {index} has an invalid shape"
            )
        path = override["path"]
        if (
            not isinstance(path, list)
            or len(path) < 3
            or path[0] != "components"
            or not all(isinstance(part, str) and part for part in path)
        ):
            raise ContractError(
                f"{surface_id}: openapi override {index} has an unsafe path"
            )
        parent: Any = document
        for part in path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise ContractError(
                    f"{surface_id}: openapi override {index} parent is missing"
                )
            parent = parent[part]
        if not isinstance(parent, dict):
            raise ContractError(
                f"{surface_id}: openapi override {index} parent is not an object"
            )
        leaf = path[-1]
        if operation == "add":
            if leaf in parent:
                raise ContractError(
                    f"{surface_id}: openapi override {index} add target exists"
                )
        elif leaf not in parent or parent[leaf] != override["expected"]:
            raise ContractError(
                f"{surface_id}: openapi override {index} expected value drifted"
            )
        parent[leaf] = override["value"]


def _agent_operations(surface: dict[str, Any]) -> list[dict[str, Any]]:
    config_path = _repo_path(surface["config_source"])
    config_lines = config_path.read_text(encoding="utf-8").splitlines()
    in_endpoints = False
    configured_paths: list[str] = []
    for raw_line in config_lines:
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 4 and stripped == "endpoints:":
            in_endpoints = True
            continue
        if in_endpoints and indent == 4 and stripped.startswith("- path:"):
            configured_paths.append(stripped.partition(":")[2].strip().strip("'\""))
            continue
        if in_endpoints and indent == 4 and stripped and stripped != "endpoints:":
            break
    if not configured_paths:
        raise ContractError("agent workflow endpoints could not be extracted")

    default_nat = [
        ("POST", "/v1/workflow"),
        ("POST", "/v1/workflow/stream"),
        ("POST", "/v1/workflow/full"),
        ("POST", "/v1/workflow/atif"),
        ("POST", "/generate"),
        ("POST", "/generate/stream"),
        ("POST", "/generate/full"),
        ("POST", "/v1/chat"),
        ("POST", "/v1/chat/stream"),
        ("POST", "/chat"),
        ("POST", "/chat/stream"),
        ("POST", "/v1/chat/completions"),
    ]
    auxiliary_nat = [
        ("GET", "/auth/redirect"),
        ("GET", "/executions/{execution_id}"),
        ("POST", "/executions/{execution_id}/interactions/{interaction_id}/response"),
        ("POST", "/static/{file_path:path}"),
        ("PUT", "/static/{file_path:path}"),
        ("GET", "/static/{file_path:path}"),
        ("DELETE", "/static/{file_path:path}"),
        ("GET", "/mcp/client/tool/list"),
        ("GET", "/mcp/client/tool/list/per_user"),
        ("POST", "/evaluate/item"),
        ("POST", "/evaluate"),
        ("GET", "/evaluate/jobs"),
        ("GET", "/evaluate/job/last"),
        ("GET", "/evaluate/job/{job_id}"),
        ("POST", "/generate/async"),
        ("GET", "/generate/async/job/{job_id}"),
        ("POST", "/v1/workflow/async"),
        ("GET", "/v1/workflow/async/job/{job_id}"),
    ]
    operations = [
        {"method": method, "path": path, "operation_id": None, "schema_hash": None}
        for method, path in default_nat + auxiliary_nat
    ]
    for path in configured_paths:
        for suffix in ("", "/stream", "/full", "/atif"):
            operations.append(
                {
                    "method": "POST",
                    "path": f"{path}{suffix}",
                    "operation_id": None,
                    "schema_hash": None,
                }
            )
    for relative in surface["route_sources"]:
        operations.extend(extract_python_routes(_repo_path(relative)))

    pyproject = _repo_path("services/agent/pyproject.toml").read_text(encoding="utf-8")
    if (
        "nvidia-nat[async-endpoints,langchain,mcp,opentelemetry,phoenix,profiler,s3]==1.6.0"
        not in pyproject
    ):
        raise ContractError("agent NAT 1.6.0 runtime-extra pin changed")
    lock = _repo_path("services/agent/uv.lock").read_text(encoding="utf-8")
    if 'name = "nvidia-nat"\nversion = "1.6.0"' not in lock:
        raise ContractError("agent uv.lock no longer pins nvidia-nat 1.6.0")
    compose = _repo_path("deploy/docker/services/agent/compose.yml").read_text(
        encoding="utf-8"
    )
    if "NAT_DASK_SCHEDULER_ADDRESS" in compose or "NAT_JOB_STORE_DB_URL" in compose:
        raise ContractError(
            "agent Dask route condition changed; review the expected NAT route set"
        )
    return operations


def derive_surface(surface: dict[str, Any]) -> dict[str, Any]:
    surface_id = surface.get("id")
    kind = surface.get("kind")
    extractor = surface.get("extractor")
    if not isinstance(surface_id, str) or not surface_id:
        raise ContractError("surface id must be a non-empty string")
    sources = _source_files(surface)
    required_feature_flags = surface.get("required_feature_flags", {})
    if required_feature_flags:
        flag_sources = surface.get("feature_flag_sources", [])
        if not isinstance(flag_sources, list) or not flag_sources:
            raise ContractError(
                f"{surface_id}: required feature flags have no source files"
            )
        flag_documents = [
            (relative, _repo_path(relative).read_text(encoding="utf-8"))
            for relative in flag_sources
        ]
        profile_name, profile_document = flag_documents[0]
        profile_lines = set(profile_document.splitlines())
        for key, value in required_feature_flags.items():
            if f"{key}={value}" not in profile_lines:
                raise ContractError(
                    f"{surface_id}: {profile_name} does not set {key}={value}"
                )
            for relative, document in flag_documents[1:]:
                if key not in document:
                    raise ContractError(
                        f"{surface_id}: {relative} does not propagate {key}"
                    )

    if kind == "rest":
        component_hash: str | None = None
        path_prefix = surface.get("path_prefix", "")
        if extractor == "openapi_json":
            document = load_json_document(sources[0][1])
            _apply_openapi_overrides(
                document, surface_id, surface.get("openapi_overrides")
            )
            operations, component_hash = normalize_openapi_document(
                document, path_prefix=path_prefix
            )
        elif extractor == "swagger_yaml":
            operations = extract_swagger_yaml_operations(
                sources[0][1], path_prefix=path_prefix
            )
        elif extractor == "python_routes":
            operations = extract_python_routes(
                _repo_path(surface.get("route_source", sources[0][0])),
                substitutions=surface.get("substitutions", {}),
                excluded_scopes=surface.get("excluded_scopes", []),
            )
        elif extractor == "markdown_routes":
            operations = extract_markdown_routes(sources[0][1])
        elif extractor == "agent_routes":
            operations = _agent_operations(surface)
        else:
            raise ContractError(
                f"{surface_id}: unsupported REST extractor {extractor!r}"
            )
        return build_rest_manifest(
            surface_id,
            operations,
            source_files=sources,
            component_schema_hash=component_hash,
        )

    if kind == "mcp":
        prompts: list[dict[str, Any]] = []
        if extractor == "lvs_mcp":
            tools = extract_lvs_mcp_tools(sources[0][1])
        elif extractor == "va_mcp":
            tools = extract_va_mcp_tools(sources[0][1])
        elif extractor == "fastmcp_python":
            tools, prompts = extract_fastmcp_declarations(sources[0][1])
        else:
            raise ContractError(
                f"{surface_id}: unsupported MCP extractor {extractor!r}"
            )
        return build_mcp_manifest(
            surface_id, tools, source_files=sources, prompts=prompts
        )

    raise ContractError(f"{surface_id}: unsupported surface kind {kind!r}")


def load_inventory(path: Path) -> dict[str, Any]:
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read API inventory {path}: {exc}") from exc
    if not isinstance(inventory, dict) or inventory.get("schema_version") != 1:
        raise ContractError("API inventory schema_version must be 1")
    surfaces = inventory.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise ContractError("API inventory surfaces must be a non-empty list")
    ids = [surface.get("id") for surface in surfaces if isinstance(surface, dict)]
    if len(ids) != len(surfaces) or len(set(ids)) != len(ids):
        raise ContractError("API inventory surface ids must be non-empty and unique")
    return inventory


def _expected_path(surface: dict[str, Any], expected_dir: Path) -> Path:
    filename = surface.get("expected_manifest")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ContractError(
            f"{surface.get('id')}: expected_manifest must be a plain filename"
        )
    return expected_dir / filename


def _load_expected(surface: dict[str, Any], expected_dir: Path) -> dict[str, Any]:
    path = _expected_path(surface, expected_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read expected manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected manifest must be an object: {path}")
    return value


def _validate_lvs_documented_gap(
    inventory: dict[str, Any], actual: dict[str, dict[str, Any]]
) -> None:
    gap = inventory.get("known_contract_differences", {}).get("lvs_openapi")
    if not isinstance(gap, dict):
        return
    document = load_json_document(_repo_path(gap["document"]))
    documented, _ = normalize_openapi_document(document)
    documented_set = {(item["method"], item["path"]) for item in documented}
    source_set = {
        (item["method"], item["path"]) for item in actual["lvs"]["operations"]
    }
    missing = sorted(source_set - documented_set)
    extra = sorted(documented_set - source_set)
    expected_missing = [tuple(item) for item in gap.get("document_missing", [])]
    if missing != expected_missing or extra:
        raise ContractError(
            "LVS checked-in OpenAPI difference changed: "
            f"missing={missing}, extra={extra}; update the document or reviewed inventory"
        )


def _validate_totals(
    inventory: dict[str, Any], manifests: dict[str, dict[str, Any]]
) -> None:
    rest = [manifest for manifest in manifests.values() if manifest["kind"] == "rest"]
    mcp = [manifest for manifest in manifests.values() if manifest["kind"] == "mcp"]
    official_declared = 0
    official_normalized = 0
    extension_count = 0
    for surface_id, manifest in manifests.items():
        if manifest["kind"] != "rest":
            continue
        surface = next(
            item for item in inventory["surfaces"] if item["id"] == surface_id
        )
        extensions = surface.get("thor_local_extensions", [])
        extension_routes: list[tuple[str, str]] = []
        for extension in extensions:
            if not isinstance(extension, dict) or set(extension) != {"method", "path"}:
                raise ContractError(
                    f"{surface_id}: Thor-local extensions must contain exactly method and path"
                )
            route = (extension["method"], extension["path"])
            if route in extension_routes:
                raise ContractError(
                    f"{surface_id}: duplicate Thor-local extension {route}"
                )
            extension_routes.append(route)
        implementation_routes = {
            (item["method"], item["path"]) for item in manifest["operations"]
        }
        missing_extensions = sorted(set(extension_routes) - implementation_routes)
        if missing_extensions:
            raise ContractError(
                f"{surface_id}: Thor-local extensions are absent from the implementation: "
                f"{missing_extensions}"
            )
        official_operations = [
            item
            for item in manifest["operations"]
            if (item["method"], item["path"]) not in set(extension_routes)
        ]
        expected_official = surface.get(
            "official_operation_count", surface["expected_operation_count"]
        )
        if len(official_operations) != expected_official:
            raise ContractError(
                f"{surface_id}: official denominator expects {expected_official}, "
                f"derived {len(official_operations)} after excluding Thor-local extensions"
            )
        official_declared += len(official_operations)
        official_normalized += len(
            {
                (item["method"], canonical_route(item["path"]))
                for item in official_operations
            }
        )
        extension_count += len(extension_routes)

    actual = {
        "declared_rest_operations": sum(
            item["declared_operation_count"] for item in rest
        ),
        "normalized_unique_rest_operations": sum(
            item["normalized_unique_operation_count"] for item in rest
        ),
        "official_declared_rest_operations": official_declared,
        "official_normalized_unique_rest_operations": official_normalized,
        "thor_local_extension_operations": extension_count,
        "mcp_tools": sum(item["tool_count"] for item in mcp),
        "mcp_prompts": sum(item["prompt_count"] for item in mcp),
    }
    expected = inventory.get("expected_totals")
    if actual != expected:
        raise ContractError(
            f"aggregate contract totals changed: expected={expected}, actual={actual}"
        )


def _validate_route_exposure(inventory: dict[str, Any]) -> None:
    routing_source = inventory.get("routing_source")
    if not isinstance(routing_source, str):
        raise ContractError("API inventory routing_source must be set")
    haproxy = _repo_path(routing_source).read_text(encoding="utf-8")
    required_snippets = {
        "agent /api": "use_backend bk_vss_agent if h_main p_api",
        "agent /chat": "use_backend bk_vss_agent if h_main p_chat",
        "agent /static": "use_backend bk_vss_agent if h_main p_static",
        "agent /websocket": "use_backend bk_vss_agent if h_main p_ws",
        "alerts prefix strip": "http-request replace-path ^/alert-bridge/(.*) /\\1",
        "video analytics prefix strip": "http-request replace-path ^/video-analytics-api/(.*) /\\1",
        "VIOS passthrough": "use_backend bk_vst_ingress if h_main p_vst",
        "VA-MCP prefix strip": "http-request replace-path ^/va-mcp/(.*) /\\1",
        "VA-MCP backend": "use_backend bk_va_mcp_strip if h_main p_va_mcp",
    }
    missing = [
        name for name, snippet in required_snippets.items() if snippet not in haproxy
    ]
    if missing:
        raise ContractError("HAProxy exposure contract changed: " + ", ".join(missing))

    surfaces = {surface["id"]: surface for surface in inventory["surfaces"]}
    expected_rewrites = {
        "agent": "none",
        "alerts": "strip-prefix",
        "video-analytics": "strip-prefix",
        "vios-live": "none",
        "vios-replay": "none",
        "vios-proxy": "none",
        "vios-sensor": "none",
        "vios-storage": "none",
        "vios-stream-bridge": "none",
        "vios-recorder": "none",
        "va-mcp": "strip-prefix",
    }
    for surface_id, rewrite in expected_rewrites.items():
        if surfaces[surface_id].get("public", {}).get("rewrite") != rewrite:
            raise ContractError(f"{surface_id}: public rewrite must be {rewrite}")


def _compare_live_openapi(
    assignment: str,
    surfaces: dict[str, dict[str, Any]],
    expected: dict[str, dict[str, Any]],
) -> None:
    surface_id, separator, filename = assignment.partition("=")
    if not separator or surface_id not in surfaces or not filename:
        raise ContractError(
            "--live-openapi must be SURFACE=LOCAL_JSON_FILE for an inventoried surface"
        )
    surface = surfaces[surface_id]
    if surface.get("kind") != "rest":
        raise ContractError(
            f"{surface_id}: live OpenAPI comparison requires a REST surface"
        )
    document_path = Path(filename).expanduser()
    if not document_path.is_file():
        raise ContractError(f"local live OpenAPI file is missing: {document_path}")
    operations, _ = normalize_openapi_document(
        load_json_document(document_path), path_prefix=surface.get("path_prefix", "")
    )
    live_set = {(item["method"], item["path"]) for item in operations}
    expected_set = {
        (item["method"], item["path"]) for item in expected[surface_id]["operations"]
    }
    if live_set != expected_set:
        missing = sorted(expected_set - live_set)
        extra = sorted(live_set - expected_set)
        raise ContractError(
            f"{surface_id}: live OpenAPI route drift: missing={missing}, extra={extra}"
        )


def run_contract(
    inventory_path: Path,
    expected_dir: Path,
    *,
    regenerate: bool = False,
    live_openapi: list[str] | None = None,
    json_output: bool = False,
) -> int:
    inventory = load_inventory(inventory_path)
    surfaces = {surface["id"]: surface for surface in inventory["surfaces"]}
    actual: dict[str, dict[str, Any]] = {}
    failures: list[str] = []

    for surface_id, surface in surfaces.items():
        try:
            manifest = derive_surface(surface)
            actual[surface_id] = manifest
            count_keys = (
                (("expected_operation_count", "declared_operation_count"),)
                if surface["kind"] == "rest"
                else (
                    ("expected_tool_count", "tool_count"),
                    ("expected_prompt_count", "prompt_count"),
                )
            )
            for expected_count_key, actual_count_key in count_keys:
                if manifest[actual_count_key] != surface[expected_count_key]:
                    raise ContractError(
                        f"inventory expects {surface[expected_count_key]} for "
                        f"{expected_count_key}, derived {manifest[actual_count_key]}"
                    )
            expected_path = _expected_path(surface, expected_dir)
            if regenerate:
                expected_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            else:
                expected = _load_expected(surface, expected_dir)
                differences = compare_manifest(expected, manifest)
                if differences:
                    raise ContractError("; ".join(differences))
        except (ContractError, OSError, KeyError, TypeError) as exc:
            failures.append(f"{surface_id}: {exc}")

    if not failures:
        try:
            _validate_totals(inventory, actual)
            _validate_lvs_documented_gap(inventory, actual)
            _validate_route_exposure(inventory)
            expected_manifests = {
                surface_id: actual[surface_id]
                if regenerate
                else _load_expected(surface, expected_dir)
                for surface_id, surface in surfaces.items()
            }
            for assignment in live_openapi or []:
                _compare_live_openapi(assignment, surfaces, expected_manifests)
        except (ContractError, OSError, KeyError, TypeError) as exc:
            failures.append(str(exc))

    report = {
        "tier": "contract",
        "offline": True,
        "surface_count": len(surfaces),
        "expected_totals": inventory.get("expected_totals"),
        "failures": failures,
        "result": "fail" if failures else "pass",
    }
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(
            f"Thor VSS contract qualification failed ({len(failures)} issue(s)).",
            file=sys.stderr,
        )
    else:
        action = "regenerated" if regenerate else "qualified"
        totals = inventory["expected_totals"]
        print(
            f"PASS: {action} {len(surfaces)} Thor VSS API surfaces offline — "
            f"{totals['declared_rest_operations']} declared REST operations "
            f"({totals['normalized_unique_rest_operations']} normalized unique) and "
            f"{totals['mcp_tools']} MCP tools plus "
            f"{totals['mcp_prompts']} MCP prompts"
        )
        print(
            "NOTE: the REST implementation total includes "
            f"{totals['thor_local_extension_operations']} explicit Thor-local extensions; "
            "the official core denominator is "
            f"{totals['official_declared_rest_operations']} declared "
            f"({totals['official_normalized_unique_rest_operations']} normalized unique)."
        )
        if inventory.get("known_contract_differences"):
            print(
                "NOTE: reviewed contract differences remain recorded in api_inventory.json."
            )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("contract",), default="contract")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--expected-dir", type=Path, default=DEFAULT_EXPECTED_DIR)
    parser.add_argument(
        "--live-openapi",
        action="append",
        default=[],
        metavar="SURFACE=LOCAL_JSON_FILE",
        help="compare a locally captured live OpenAPI document; URLs are intentionally unsupported",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable result"
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="developer-only: rewrite expected manifests from the reviewed checkout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_contract(
        args.inventory,
        args.expected_dir,
        regenerate=args.regenerate,
        live_openapi=args.live_openapi,
        json_output=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
