#!/usr/bin/env python3
"""Validate an inert Thor runtime campaign and its sanitized receipt set.

The CLI never imports or invokes a runtime collector.  ``plan`` validates the
checked-in contract and source locks.  ``check`` additionally reads caller-
supplied JSON evidence and validates it without writing or promoting anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SET_SCHEMA_PATH = HERE / "receipt-set.schema.json"
MAX_BYTES = 128 * 1024 * 1024
ZERO_SHA = "0" * 64

OVERLAY_PATH = (
    "deploy/docker/thor-local/qualification/"
    "advertised-candidate-bindings-current-semantic-closure-successor/"
    "binding-overlay.json"
)
OVERLAY_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/"
    "advertised-candidate-bindings-current-semantic-closure-successor/"
    "binding-overlay.schema.json"
)
OVERLAY_CONTRACT_PATH = (
    "deploy/docker/thor-local/qualification/"
    "advertised-candidate-bindings-current-semantic-closure-successor/"
    "contract.json"
)
LVS_MULTI_FIXTURE_PATH = (
    "deploy/docker/thor-local/qualification/"
    "lvs-multi-video-artifact-oracle-successor/fixture.json"
)
OFFICIAL_EDGE_CONTRACT_PATH = "deploy/docker/thor-local/official-edge/contract.json"
OFFICIAL_EDGE_ARTIFACT_LOCK_PATH = (
    "deploy/docker/thor-local/official-edge/artifacts.lock.json"
)
MODEL_SEMANTIC_ROOT = (
    "deploy/docker/thor-local/qualification/"
    "official-edge-semantic-runtime-evidence-successor/"
)
MODEL_SEMANTIC_CONTRACT_PATH = MODEL_SEMANTIC_ROOT + "contract.json"
MODEL_SEMANTIC_CONTRACT_SCHEMA_PATH = MODEL_SEMANTIC_ROOT + "contract.schema.json"
MODEL_SEMANTIC_EXECUTOR_PATH = MODEL_SEMANTIC_ROOT + "executor.py"
MODEL_SEMANTIC_MANIFEST_SCHEMA_PATH = MODEL_SEMANTIC_ROOT + "manifest.schema.json"
MODEL_SEMANTIC_RECEIPT_SCHEMA_PATH = MODEL_SEMANTIC_ROOT + "receipt.schema.json"
THOR_REQUIREMENTS_PATH = "deploy/docker/thor-local/agent-models/thor-requirements.json"
THOR_REQUIREMENTS_VERIFIER_PATH = (
    "deploy/docker/thor-local/agent-models/verify_thor_requirements.py"
)
RUNTIME_RECEIPT_APPROVAL_PATH = (
    "deploy/docker/thor-local/agent-models/approved-runtime-receipt.json"
)
MODEL_RECEIPT_ID = "official-model-semantic-admission"
EXPECTED_PHASES = (
    ("host-prerequisites", "none", False),
    (MODEL_RECEIPT_ID, "base", True),
    ("base-tiny-agent-media", "base", True),
    ("base-hitl-state", "base", True),
    ("search-file-semantics", "search", True),
    ("search-rtsp-archive", "search", True),
    ("ui-video-management", "search", True),
    ("lvs-closure", "lvs", True),
    ("lvs-agent-session", "lvs", True),
    ("lvs-multi-static-oracle", "none", False),
    ("lvs-focus-matrix", "lvs", True),
    ("alerts-terminal", "alerts", True),
)
EXPECTED_TRANSITIONS = (
    (1, "none", "base"),
    (2, "base", "search"),
    (3, "search", "lvs"),
    (4, "lvs", "alerts"),
)
HOST_CAPABILITY_IDS = (
    "prereq.platform.validated-gpus",
    "prereq.platform.agx-thor-software",
    "prereq.platform.toolchain-versions",
    "prereq.platform.capacity-and-access",
)
ALERT_CAPABILITY_ID = "runtime.workflow.alert-verification"


class CampaignError(RuntimeError):
    """A source, schema, identity, provenance, or receipt invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise CampaignError(f"{label}: exceeds size bound")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CampaignError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                CampaignError(f"{label}: non-finite JSON number {token}")
            ),
        )
    except CampaignError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"{label}: JSON root must be an object")
    return value


def _read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise CampaignError(f"{label}: unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise CampaignError(f"{label}: must be a regular non-symlink")
    if before.st_size > MAX_BYTES:
        raise CampaignError(f"{label}: exceeds size bound")
    try:
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise CampaignError(f"{label}: read failed") from exc
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(payload) != before.st_size
    ):
        raise CampaignError(f"{label}: changed while reading")
    return payload


def _safe_repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CampaignError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CampaignError(f"repository source unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CampaignError(f"repository source contains symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise CampaignError(f"repository source is not regular: {relative}")
    return path


def _safe_evidence_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CampaignError(f"unsafe receipt path: {relative}")
    root = root.resolve(strict=True)
    path = root
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CampaignError(f"receipt unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CampaignError(f"receipt path contains symlink: {relative}")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CampaignError(f"receipt escapes evidence root: {relative}") from exc
    if not stat.S_ISREG(path.lstat().st_mode):
        raise CampaignError(f"receipt is not regular: {relative}")
    return path


def _validate_schema(value: Any, schema: Mapping[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CampaignError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.absolute_path)
        raise CampaignError(f"{label}: schema violation at {location}: {first.message}")


def _one(rows: Sequence[Mapping[str, Any]], key: str, value: Any) -> Mapping[str, Any]:
    matches = [row for row in rows if row.get(key) == value]
    if len(matches) != 1:
        raise CampaignError(f"expected one {key}={value!r}, found {len(matches)}")
    return matches[0]


def _verify_transitive_locks(
    owner_path: str,
    source_payloads: dict[str, bytes],
    source_objects: dict[str, dict[str, Any]],
) -> None:
    owner = source_objects[owner_path]
    rows = owner.get("source_locks")
    if not isinstance(rows, list):
        raise CampaignError(f"{owner_path}: transitive source locks are absent")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise CampaignError(f"{owner_path}: malformed transitive source lock")
        relative = row["path"]
        expected = row["sha256"]
        if not isinstance(relative, str) or relative in seen:
            raise CampaignError(f"{owner_path}: duplicate transitive source lock")
        seen.add(relative)
        payload = _read_regular(_safe_repo_path(relative), relative)
        if sha256(payload) != expected:
            raise CampaignError(f"transitive source drift for {relative}")
        if relative in source_payloads and source_payloads[relative] != payload:
            raise CampaignError(f"conflicting direct/transitive source: {relative}")
        source_payloads[relative] = payload
        if relative.endswith(".json"):
            source_objects[relative] = _strict_json(payload, relative)


def _parse_locked_env(payload: bytes) -> dict[str, str]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CampaignError("official model environment is not UTF-8") from exc
    result: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CampaignError("official model environment is malformed")
        key, value = line.split("=", 1)
        if key in result:
            raise CampaignError("official model environment has a duplicate key")
        result[key] = value
    return result


def _no_cloud_projection(
    model_contract: Mapping[str, Any], source_payloads: Mapping[str, bytes]
) -> str:
    env_path = "deploy/docker/thor-local/official-edge/official-edge.env"
    compose_path = "deploy/docker/thor-local/official-edge/compose.yml"
    config_path = "deploy/docker/thor-local/official-edge/config_edge.yml"
    env = _parse_locked_env(source_payloads[env_path])
    llm = model_contract["canonical_models"]["llm"]
    vlm = model_contract["canonical_models"]["vlm"]
    required = {
        "LLM_MODE": "remote",
        "VLM_MODE": "local_shared",
        "LLM_BASE_URL": llm["origin"],
        "LLM_NAME": llm["served_model_id"],
        "VLM_BASE_URL": vlm["origin"],
        "VLM_NAME": vlm["served_model_id"],
        "RTVI_VLM_BASE_URL": vlm["origin"],
        "RTVI_VLM_MODEL_TO_USE": vlm["selector"],
        "RTVI_VLM_MODEL_PATH": vlm["artifact_id"],
        "RTVI_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": vlm["served_model_id"],
    }
    if any(env.get(key) != value for key, value in required.items()):
        raise CampaignError("official model no-cloud wiring identity drift")
    blank_keys = model_contract["canonical_models"]["agent"]["api_keys_must_be_blank"]
    compose = source_payloads[compose_path]
    blank_projection = {
        key: env[key] == "" if key in env else f'{key}: ""'.encode() in compose
        for key in blank_keys
    }
    if not all(blank_projection.values()):
        raise CampaignError("official model no-cloud key boundary drift")
    selected = source_payloads[env_path] + compose + source_payloads[config_path]
    if any(
        item.encode() in selected for item in model_contract["forbidden_substitutions"]
    ):
        raise CampaignError("official model forbidden substitution is configured")
    projection = {
        "required": required,
        "blank_keys": sorted(blank_projection),
        "compose_sha256": sha256(compose),
        "config_sha256": sha256(source_payloads[config_path]),
    }
    return sha256(canonical_bytes(projection))


def _load_contract_and_sources() -> tuple[
    dict[str, Any], dict[str, bytes], dict[str, dict[str, Any]]
]:
    contract_payload = _read_regular(CONTRACT_PATH, "campaign contract")
    contract = _strict_json(contract_payload, "campaign contract")
    contract_schema = _strict_json(
        _read_regular(CONTRACT_SCHEMA_PATH, "campaign contract schema"),
        "campaign contract schema",
    )
    manifest_schema = _strict_json(
        _read_regular(MANIFEST_SCHEMA_PATH, "campaign manifest schema"),
        "campaign manifest schema",
    )
    receipt_set_schema = _strict_json(
        _read_regular(RECEIPT_SET_SCHEMA_PATH, "campaign receipt-set schema"),
        "campaign receipt-set schema",
    )
    _validate_schema(contract, contract_schema, "campaign contract")
    for label, schema in (
        ("campaign manifest schema", manifest_schema),
        ("campaign receipt-set schema", receipt_set_schema),
    ):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise CampaignError(f"{label}: invalid JSON Schema") from exc

    source_payloads: dict[str, bytes] = {}
    source_objects: dict[str, dict[str, Any]] = {}
    seen_paths: set[str] = set()
    for lock in contract["source_locks"]:
        relative = lock["path"]
        if relative in seen_paths:
            raise CampaignError(f"duplicate source lock: {relative}")
        seen_paths.add(relative)
        payload = _read_regular(_safe_repo_path(relative), relative)
        actual = sha256(payload)
        if actual != lock["sha256"]:
            raise CampaignError(
                f"source drift for {relative}: expected {lock['sha256']}, got {actual}"
            )
        source_payloads[relative] = payload
        if relative.endswith(".json"):
            source_objects[relative] = _strict_json(payload, relative)

    _verify_transitive_locks(
        MODEL_SEMANTIC_CONTRACT_PATH, source_payloads, source_objects
    )
    _verify_transitive_locks(THOR_REQUIREMENTS_PATH, source_payloads, source_objects)
    if len(source_payloads) != 43:
        raise CampaignError("expanded direct/transitive source closure drift")

    overlay = source_objects[OVERLAY_PATH]
    overlay_schema = source_objects[OVERLAY_SCHEMA_PATH]
    _validate_schema(overlay, overlay_schema, "selected binding overlay")
    selected = [row["capability_id"] for row in overlay["rows"]]
    expected_selected = [
        row["capability_id"]
        for row in contract["capability_mappings"]
        if row["capability_id"].startswith("manifest-entry.")
    ]
    if (
        selected != expected_selected
        or len(set(selected)) != 10
        or overlay["summary"]["concrete_implementation_count"] != 10
        or overlay["summary"]["partial_implementation_count"] != 0
        or overlay["summary"]["runtime_receipt_count"] != 0
        or overlay["warehouse_sample_bundle"] != "excluded"
    ):
        raise CampaignError("selected binding overlay identity or state drift")

    receipt_ids = [row["receipt_id"] for row in contract["receipt_types"]]
    phase_receipts = [row["receipt_id"] for row in contract["phases"]]
    expected_receipt_ids = [row[0] for row in EXPECTED_PHASES]
    if (
        receipt_ids != expected_receipt_ids
        or phase_receipts != expected_receipt_ids
        or len(set(receipt_ids)) != 12
    ):
        raise CampaignError("contract receipt/phase partition drift")
    phase_shape = [
        (
            row["order"],
            row["phase_id"],
            row["profile_id"],
            row["run_namespace_required"],
        )
        for row in contract["phases"]
    ]
    if phase_shape != [
        (order, phase_id, profile_id, runtime)
        for order, (phase_id, profile_id, runtime) in enumerate(EXPECTED_PHASES, 1)
    ]:
        raise CampaignError("contract phase order drift")
    transitions = [
        (row["order"], row["from"], row["to"])
        for row in contract["profile_transitions"]
    ]
    if transitions != list(EXPECTED_TRANSITIONS):
        raise CampaignError("contract profile transition drift")
    capability_ids = [row["capability_id"] for row in contract["capability_mappings"]]
    if capability_ids != [*HOST_CAPABILITY_IDS, *selected, ALERT_CAPABILITY_ID]:
        raise CampaignError("contract capability mapping is not one-to-one")

    required_source_paths = {
        OVERLAY_PATH,
        OVERLAY_SCHEMA_PATH,
        OVERLAY_CONTRACT_PATH,
        LVS_MULTI_FIXTURE_PATH,
        OFFICIAL_EDGE_CONTRACT_PATH,
        OFFICIAL_EDGE_ARTIFACT_LOCK_PATH,
        MODEL_SEMANTIC_CONTRACT_SCHEMA_PATH,
        MODEL_SEMANTIC_EXECUTOR_PATH,
        MODEL_SEMANTIC_MANIFEST_SCHEMA_PATH,
        THOR_REQUIREMENTS_PATH,
        THOR_REQUIREMENTS_VERIFIER_PATH,
        RUNTIME_RECEIPT_APPROVAL_PATH,
        *(
            path
            for row in contract["receipt_types"]
            for path in (row["contract_path"], row["schema_path"])
        ),
    }
    if seen_paths != required_source_paths:
        raise CampaignError("campaign source-lock closure drift")

    official = source_objects[OFFICIAL_EDGE_CONTRACT_PATH]
    model_semantic = source_objects[MODEL_SEMANTIC_CONTRACT_PATH]
    requirements = source_objects[THOR_REQUIREMENTS_PATH]
    artifact_lock = source_objects[OFFICIAL_EDGE_ARTIFACT_LOCK_PATH]
    models = contract["official_thor_models"]
    if (
        models["release_commit"] != model_semantic["reviewed_release"]["tag_commit"]
        or models["main_commit"] != model_semantic["reviewed_release"]["main_commit"]
        or models["artifact_lock_sha256"]
        != _one(
            model_semantic["source_locks"],
            "path",
            OFFICIAL_EDGE_ARTIFACT_LOCK_PATH,
        )["sha256"]
        or models["llm_artifact"]
        != f"{official['llm']['repository']}@{official['llm']['revision']}"
        or models["llm_served_model"] != official["llm"]["served_model_id"]
        or models["llm_image_reference"]
        != model_semantic["canonical_models"]["llm"]["image_reference"]
        or models["llm_image_id"]
        != model_semantic["canonical_models"]["llm"]["image_id"]
        or models["vlm_artifact"] != official["vlm"]["artifact_id"]
        or models["vlm_served_model"] != official["vlm"]["served_model_id"]
        or models["vlm_image_reference"]
        != model_semantic["canonical_models"]["vlm"]["image_reference"]
        or models["vlm_image_id"]
        != model_semantic["canonical_models"]["vlm"]["image_id"]
        or models["no_cloud_projection_sha256"]
        != _no_cloud_projection(model_semantic, source_payloads)
    ):
        raise CampaignError("official Thor model identity drift")
    runtime_contract = requirements["denominators"]["canonical_official_edge_pair"][
        "runtime_evidence"
    ]
    if (
        runtime_contract["state"] != "collector_contract_ready_no_live_receipt"
        or runtime_contract["readiness_only_is_sufficient"] is not False
        or runtime_contract["accepted_evidence_contract"]
        != {
            "package_id": model_semantic["package_id"],
            "collector_id": model_semantic["collector_id"],
            "receipt_schema_version": 1,
            "required_status": "passed_candidate_non_promoting",
        }
        or requirements["current_state"]["canonical_official_edge_pair"]
        != "incomplete_fail_closed"
        or requirements["current_state"]["runtime_evidence_promoted"] is not False
        or requirements["current_state"]["warehouse_sample_required"] is not False
        or artifact_lock["lock_state"] != "incomplete_fail_closed"
    ):
        raise CampaignError("official model readiness/live-receipt boundary drift")
    return (
        contract,
        source_payloads,
        {
            "manifest": manifest_schema,
            "receipt_set": receipt_set_schema,
            **source_objects,
        },
    )


def _profile_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256(canonical_bytes(list(rows)))


def _validate_manifest(
    manifest: dict[str, Any], contract: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Mapping[str, Any]]:
    _validate_schema(manifest, schema, "campaign manifest")
    if (
        manifest["repository_commit"] != contract["repository"]["commit"]
        or manifest["selected_binding_overlay_sha256"]
        != _one(contract["source_locks"], "path", OVERLAY_PATH)["sha256"]
    ):
        raise CampaignError("campaign repository or selected-overlay identity drift")

    expected_profiles = contract["profiles"]
    if [row["profile_id"] for row in manifest["profiles"]] != [
        row["profile_id"] for row in expected_profiles
    ]:
        raise CampaignError("campaign profile order drift")
    for actual, expected in zip(manifest["profiles"], expected_profiles, strict=True):
        image_roles = [row["role"] for row in actual["images"]]
        if image_roles != expected["required_image_roles"]:
            raise CampaignError(
                f"{actual['profile_id']}: incomplete image identity set"
            )
        for image in actual["images"]:
            suffix = f"@sha256:{image['digest']}"
            if not image["reference"].endswith(suffix):
                raise CampaignError(
                    f"{actual['profile_id']}: image reference/digest drift for {image['role']}"
                )
        if actual["image_set_sha256"] != _profile_digest(actual["images"]):
            raise CampaignError(f"{actual['profile_id']}: image-set digest drift")
        expected_models = expected["required_models"]
        if [row["role"] for row in actual["models"]] != [
            row["role"] for row in expected_models
        ]:
            raise CampaignError(f"{actual['profile_id']}: model role set drift")
        for model, required in zip(actual["models"], expected_models, strict=True):
            if (
                model["identity"] != required["identity"]
                or model["served_model_id"] != required["served_model_id"]
                or model["artifact_sha256"] == ZERO_SHA
            ):
                raise CampaignError(
                    f"{actual['profile_id']}: model identity drift for {model['role']}"
                )
        if actual["model_set_sha256"] != _profile_digest(actual["models"]):
            raise CampaignError(f"{actual['profile_id']}: model-set digest drift")

    fixture_rows = manifest["fixtures"]
    fixture_ids = [row["fixture_id"] for row in fixture_rows]
    expected_fixture_ids = list(
        dict.fromkeys(
            fixture_id
            for phase in contract["phases"]
            for fixture_id in phase["fixture_ids"]
        )
    )
    if fixture_ids != expected_fixture_ids or len(set(fixture_ids)) != 16:
        raise CampaignError("campaign fixture inventory drift")

    if [row["phase_id"] for row in manifest["phases"]] != [
        row["phase_id"] for row in contract["phases"]
    ]:
        raise CampaignError("campaign phase order drift")
    namespaces: list[str] = []
    input_hashes: list[str] = []
    campaign_prefix = f"{manifest['campaign_id']}-"
    for actual, expected in zip(manifest["phases"], contract["phases"], strict=True):
        if (
            actual["order"] != expected["order"]
            or actual["profile_id"] != expected["profile_id"]
            or actual["receipt_id"] != expected["receipt_id"]
            or actual["fixture_ids"] != expected["fixture_ids"]
        ):
            raise CampaignError(f"campaign phase drift: {expected['phase_id']}")
        namespace = actual["run_namespace"]
        input_sha = actual["executor_input_sha256"]
        model_receipt_sha = actual["model_semantic_receipt_sha256"]
        if expected["receipt_id"] in {"host-prerequisites", MODEL_RECEIPT_ID}:
            if model_receipt_sha is not None:
                raise CampaignError(
                    f"{expected['phase_id']}: model admission cannot depend on itself"
                )
        elif model_receipt_sha != manifest["model_semantic_receipt_sha256"]:
            raise CampaignError(
                f"{expected['phase_id']}: mandatory semantic model receipt is absent"
            )
        if expected["run_namespace_required"]:
            if not isinstance(namespace, str) or not namespace.startswith(
                campaign_prefix
            ):
                raise CampaignError(
                    f"{expected['phase_id']}: run namespace is not campaign-bound"
                )
            if not isinstance(input_sha, str):
                raise CampaignError(
                    f"{expected['phase_id']}: executor input digest is required"
                )
            namespaces.append(namespace)
            input_hashes.append(input_sha)
        elif namespace is not None or input_sha is not None:
            raise CampaignError(
                f"{expected['phase_id']}: static phase cannot carry runtime identity"
            )
    if len(namespaces) != len(set(namespaces)):
        raise CampaignError("campaign run namespaces are not disjoint")
    if len(input_hashes) != len(set(input_hashes)):
        raise CampaignError("campaign executor input identities are not disjoint")
    return {row["fixture_id"]: row for row in fixture_rows}


def _receipt_package(receipt: Mapping[str, Any]) -> str | None:
    for key in ("package_id", "collector_id", "package"):
        value = receipt.get(key)
        if isinstance(value, str):
            return value
    return None


def _require_contract_hash(receipt: Mapping[str, Any], expected: str) -> None:
    if "contract_sha256" in receipt and receipt["contract_sha256"] != expected:
        raise CampaignError("receipt contract hash drift")


def _require_manifest_hash(receipt: Mapping[str, Any], expected: str) -> None:
    if receipt.get("manifest_sha256") != expected:
        raise CampaignError("receipt executor-manifest hash drift")


def _require_run_hash(receipt_hash: Any, namespace: str) -> None:
    if receipt_hash != sha256(namespace.encode("utf-8")):
        raise CampaignError("receipt run namespace hash drift")


def _phase_fixtures(
    manifest: Mapping[str, Any],
    fixtures: Mapping[str, Mapping[str, Any]],
    phase_id: str,
) -> list[Mapping[str, Any]]:
    phase = _one(manifest["phases"], "phase_id", phase_id)
    return [fixtures[fixture_id] for fixture_id in phase["fixture_ids"]]


def _validate_host(receipt: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    expected = [
        row["capability_id"]
        for row in contract["capability_mappings"]
        if row["capability_id"].startswith("prereq.platform.")
    ]
    if (
        receipt.get("mode") != "inspect"
        or receipt.get("result") != "pass"
        or receipt.get("summary", {}).get("contract_result") != "pass"
        or receipt.get("summary", {}).get("contracts_passed") != 4
        or [row.get("capability_id") for row in receipt.get("capabilities", [])]
        != expected
        or any(
            row.get("contract_status") != "pass"
            or row.get("contract_satisfied") is not True
            for row in receipt.get("capabilities", [])
        )
    ):
        raise CampaignError(
            "host prerequisite receipt is not an exact four-pass record"
        )
    unsigned = dict(receipt)
    claimed = unsigned.pop("evidence_sha256", None)
    if claimed != sha256(canonical_bytes(unsigned)):
        raise CampaignError("host prerequisite evidence digest drift")


def _validate_model_semantic_receipt(
    receipt: Mapping[str, Any],
    namespace: str,
    fixture: Mapping[str, Any],
    contract: Mapping[str, Any],
    source_payloads: Mapping[str, bytes],
) -> None:
    model_semantic_contract = _strict_json(
        source_payloads[MODEL_SEMANTIC_CONTRACT_PATH],
        "official semantic model contract",
    )
    expected_locks = {
        "contract_sha256": sha256(source_payloads[MODEL_SEMANTIC_CONTRACT_PATH]),
        "contract_schema_sha256": sha256(
            source_payloads[MODEL_SEMANTIC_CONTRACT_SCHEMA_PATH]
        ),
        "executor_sha256": sha256(source_payloads[MODEL_SEMANTIC_EXECUTOR_PATH]),
        "manifest_schema_sha256": sha256(
            source_payloads[MODEL_SEMANTIC_MANIFEST_SCHEMA_PATH]
        ),
        "receipt_schema_sha256": sha256(
            source_payloads[MODEL_SEMANTIC_RECEIPT_SCHEMA_PATH]
        ),
    }
    models = contract["official_thor_models"]
    expected_model_contract = {
        "release_commit": models["release_commit"],
        "main_commit": models["main_commit"],
        "artifact_lock_sha256": models["artifact_lock_sha256"],
        "llm": {
            "served_model_id": models["llm_served_model"],
            "endpoint": "http://127.0.0.1:30081",
            "image_reference": models["llm_image_reference"],
            "image_id": models["llm_image_id"],
        },
        "vlm": {
            "served_model_id": models["vlm_served_model"],
            "endpoint": "http://127.0.0.1:8018",
            "image_reference": models["vlm_image_reference"],
            "image_id": models["vlm_image_id"],
        },
    }
    expected_observations = [
        ("llm-model-identity", "llm", ["exact-llm-served-id"]),
        (
            "llm-tool-positive",
            "llm",
            ["exact-tool-name", "exact-tool-arguments"],
        ),
        (
            "llm-tool-negative",
            "llm",
            ["negative-no-tool-call", "negative-exact-content"],
        ),
        ("vlm-model-identity", "vlm", ["exact-vlm-served-id"]),
        (
            "vlm-visual-positive",
            "vlm",
            [
                "digest-pinned-media",
                "positive-visual-literal",
                "absent-literal-excluded",
            ],
        ),
        (
            "vlm-visual-absent-negative",
            "vlm",
            ["digest-pinned-media", "absent-negative-exact"],
        ),
        (
            "agent-both-models-workflow",
            "agent",
            [
                "agent-consumed-vlm",
                "agent-consumed-llm",
                "agent-workflow-sentinel",
            ],
        ),
    ]
    observations = receipt.get("observations", [])
    expected_challenge_sha256 = sha256(
        (
            model_semantic_contract["semantic_contract"]["llm_challenge_prefix"]
            + namespace
        ).encode("utf-8")
    )
    if (
        receipt.get("collector_locks") != expected_locks
        or receipt.get("identity", {}).get("run_id") != namespace
        or receipt.get("identity", {}).get("llm_tool_challenge_sha256")
        != expected_challenge_sha256
        or receipt.get("model_contract") != expected_model_contract
        or receipt.get("no_cloud_agent_wiring")
        != {
            "status": "pass",
            "projection_sha256": models["no_cloud_projection_sha256"],
            "blank_api_key_count": 5,
            "forbidden_substitution_count": 0,
        }
        or receipt.get("prerequisite", {}).get("qualification_state")
        != "prelaunch_ready_not_runtime_qualified"
        or receipt.get("media", {}).get("sha256") != fixture["sha256"]
        or receipt.get("media", {}).get("byte_count") != fixture["bytes"]
        or receipt.get("media", {}).get("media_type") != fixture["media_type"]
        or [row.get("sequence") for row in observations] != list(range(1, 8))
        or [
            (row.get("observation_id"), row.get("role"), row.get("assertion_ids"))
            for row in observations
        ]
        != expected_observations
    ):
        raise CampaignError(
            "official semantic model receipt identity, collector, or semantics drift"
        )


def _validate_receipt_semantics(
    *,
    receipt_id: str,
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
    fixtures: Mapping[str, Mapping[str, Any]],
    contract_sha: str,
    campaign_contract: Mapping[str, Any],
    source_payloads: Mapping[str, bytes],
) -> None:
    _require_contract_hash(receipt, contract_sha)
    phase = _one(manifest["phases"], "receipt_id", receipt_id)
    namespace = phase["run_namespace"]
    input_sha = phase["executor_input_sha256"]
    phase_fixtures = _phase_fixtures(manifest, fixtures, phase["phase_id"])

    if receipt_id == "host-prerequisites":
        return
    if receipt_id == MODEL_RECEIPT_ID:
        _validate_model_semantic_receipt(
            receipt,
            namespace,
            phase_fixtures[0],
            campaign_contract,
            source_payloads,
        )
        return
    if receipt_id in {"base-tiny-agent-media", "base-hitl-state"}:
        expected_case = (
            "tiny-agent-media"
            if receipt_id == "base-tiny-agent-media"
            else "hitl-state-transcript"
        )
        _require_manifest_hash(receipt, input_sha)
        if receipt.get("case_id") != expected_case:
            raise CampaignError(f"{receipt_id}: wrong Base case")
        fixture = receipt.get("fixture", {})
        if (
            fixture.get("primary_sha256") != phase_fixtures[0]["sha256"]
            or fixture.get("primary_bytes") != phase_fixtures[0]["bytes"]
            or fixture.get("secondary_sha256") != phase_fixtures[1]["sha256"]
            or fixture.get("secondary_bytes") != phase_fixtures[1]["bytes"]
        ):
            raise CampaignError(f"{receipt_id}: Base fixture identity drift")
        return
    if receipt_id == "search-file-semantics":
        if receipt.get("identity", {}).get("run_id") != namespace:
            raise CampaignError("Search lifecycle cross-run receipt")
        if (
            receipt.get("identity", {}).get("media_sha256")
            != phase_fixtures[0]["sha256"]
        ):
            raise CampaignError("Search media identity drift")
        fixture = receipt.get("fixture", {})
        if (
            fixture.get("consumer_invoked") is not True
            or fixture.get("consumer_transport_accounting")
            != "shared-lifecycle-budget-and-deadline"
            or not isinstance(fixture.get("consumer_receipt_sha256"), str)
        ):
            raise CampaignError("Search integrated semantic consumer is absent")
        return
    if receipt_id == "search-rtsp-archive":
        if receipt.get("identity", {}).get("run_id") != namespace:
            raise CampaignError("Search RTSP cross-run receipt")
        if (
            receipt.get("identity", {}).get("rtsp_url_sha256")
            != phase_fixtures[0]["sha256"]
            or receipt.get("control", {}).get("reviewed_projection_sha256")
            != phase_fixtures[1]["sha256"]
        ):
            raise CampaignError("Search RTSP/control fixture identity drift")
        return
    if receipt_id == "ui-video-management":
        _require_manifest_hash(receipt, input_sha)
        _require_run_hash(receipt.get("run_id_sha256"), namespace)
        if receipt.get("fixture_sha256") != [
            phase_fixtures[0]["sha256"],
            phase_fixtures[1]["sha256"],
        ]:
            raise CampaignError("UI uploaded fixture identity drift")
        return
    if receipt_id == "lvs-closure":
        _require_manifest_hash(receipt, input_sha)
        _require_run_hash(receipt.get("identity", {}).get("run_id_sha256"), namespace)
        expected_media = [row["sha256"] for row in phase_fixtures[:2]]
        if [
            row.get("stored_media_sha256")
            for row in receipt.get("fixture_readback", [])
        ] != expected_media:
            raise CampaignError("LVS closure fixture readback drift")
        return
    if receipt_id == "lvs-agent-session":
        _require_manifest_hash(receipt, input_sha)
        _require_run_hash(receipt.get("identity", {}).get("run_id_sha256"), namespace)
        if (
            receipt.get("semantic_observations", {}).get("multi_video_report")
            is not True
        ):
            raise CampaignError("LVS Agent multi-video observation missing")
        return
    if receipt_id == "lvs-multi-static-oracle":
        if (
            receipt.get("fixture_sha256") != phase_fixtures[0]["sha256"]
            or receipt.get("fixture", {}).get("materialized_video_count") != 0
            or receipt.get("runtime_evidence") != []
        ):
            raise CampaignError("LVS static oracle identity or confinement drift")
        return
    if receipt_id == "lvs-focus-matrix":
        _require_run_hash(receipt.get("run_id_sha256"), namespace)
        if receipt.get("fixture_sha256") != phase_fixtures[0]["sha256"]:
            raise CampaignError("LVS focus fixture identity drift")
        return
    if receipt_id == "alerts-terminal":
        if receipt.get("fixture_sha256") != phase_fixtures[0]["sha256"]:
            raise CampaignError("Alerts semantic descriptor identity drift")
        # The current receipt intentionally exposes neither the authorized run
        # namespace nor served media bytes.  The campaign must retain that
        # blocker and cannot manufacture a cross-run binding here.
        return
    raise CampaignError(f"unknown receipt id: {receipt_id}")


def check_campaign(manifest_path: Path, receipt_set_path: Path) -> dict[str, Any]:
    contract, payloads, objects = _load_contract_and_sources()
    manifest_payload = _read_regular(manifest_path, "campaign manifest")
    manifest = _strict_json(manifest_payload, "campaign manifest")
    fixtures = _validate_manifest(manifest, contract, objects["manifest"])

    receipt_set_payload = _read_regular(receipt_set_path, "campaign receipt set")
    receipt_set = _strict_json(receipt_set_payload, "campaign receipt set")
    _validate_schema(receipt_set, objects["receipt_set"], "campaign receipt set")
    if (
        receipt_set["campaign_id"] != manifest["campaign_id"]
        or receipt_set["repository_commit"] != manifest["repository_commit"]
        or receipt_set["manifest_sha256"] != sha256(manifest_payload)
        or receipt_set["model_semantic_receipt_sha256"]
        != manifest["model_semantic_receipt_sha256"]
        or receipt_set["unresolved_blockers"] != contract["required_blockers"]
        or receipt_set["capability_evidence"] != contract["capability_mappings"]
    ):
        raise CampaignError(
            "receipt-set campaign, blocker, or capability mapping drift"
        )

    expected_receipts = contract["receipt_types"]
    if [row["receipt_id"] for row in receipt_set["receipts"]] != [
        row["receipt_id"] for row in expected_receipts
    ]:
        raise CampaignError("receipt set is missing, duplicated, or out of order")
    if len({row["path"] for row in receipt_set["receipts"]}) != 12:
        raise CampaignError("receipt paths are not disjoint")
    if len({row["sha256"] for row in receipt_set["receipts"]}) != 12:
        raise CampaignError("duplicate or stale receipt payload reused across phases")

    evidence_root = receipt_set_path.resolve(strict=True).parent
    loaded: dict[str, dict[str, Any]] = {}
    raw_hashes: dict[str, str] = {}
    for descriptor, receipt_type, phase in zip(
        receipt_set["receipts"], expected_receipts, contract["phases"], strict=True
    ):
        if (
            descriptor["receipt_id"] != receipt_type["receipt_id"]
            or descriptor["phase_id"] != phase["phase_id"]
        ):
            raise CampaignError("receipt descriptor phase/type drift")
        contract_payload = payloads[receipt_type["contract_path"]]
        schema_payload = payloads[receipt_type["schema_path"]]
        if descriptor["contract_sha256"] != sha256(contract_payload) or descriptor[
            "schema_sha256"
        ] != sha256(schema_payload):
            raise CampaignError("receipt descriptor source identity drift")
        manifest_phase = _one(manifest["phases"], "phase_id", phase["phase_id"])
        namespace = manifest_phase["run_namespace"]
        expected_run_sha = (
            sha256(namespace.encode("utf-8")) if isinstance(namespace, str) else None
        )
        if (
            descriptor["run_namespace_sha256"] != expected_run_sha
            or descriptor["executor_input_sha256"]
            != manifest_phase["executor_input_sha256"]
            or descriptor["model_semantic_receipt_sha256"]
            != manifest_phase["model_semantic_receipt_sha256"]
        ):
            raise CampaignError("receipt descriptor cross-run/input identity drift")

        path = _safe_evidence_path(evidence_root, descriptor["path"])
        receipt_payload = _read_regular(path, f"receipt {descriptor['receipt_id']}")
        actual_sha = sha256(receipt_payload)
        if actual_sha != descriptor["sha256"]:
            raise CampaignError(
                f"stale or replaced receipt: {descriptor['receipt_id']}"
            )
        receipt = _strict_json(receipt_payload, f"receipt {descriptor['receipt_id']}")
        schema = _strict_json(schema_payload, f"schema {descriptor['receipt_id']}")
        _validate_schema(receipt, schema, f"receipt {descriptor['receipt_id']}")
        package = _receipt_package(receipt)
        if package in contract["forbidden_receipt_package_ids"]:
            raise CampaignError(f"conflicting predecessor receipt supplied: {package}")
        if package != receipt_type["package_id"]:
            raise CampaignError(
                f"receipt package drift for {descriptor['receipt_id']}: {package}"
            )
        _validate_receipt_semantics(
            receipt_id=descriptor["receipt_id"],
            receipt=receipt,
            manifest=manifest,
            fixtures=fixtures,
            contract_sha=descriptor["contract_sha256"],
            campaign_contract=contract,
            source_payloads=payloads,
        )
        loaded[descriptor["receipt_id"]] = receipt
        raw_hashes[descriptor["receipt_id"]] = actual_sha

    model_receipt_sha = raw_hashes[MODEL_RECEIPT_ID]
    if (
        manifest["model_semantic_receipt_sha256"] != model_receipt_sha
        or receipt_set["model_semantic_receipt_sha256"] != model_receipt_sha
        or any(
            phase["model_semantic_receipt_sha256"] != model_receipt_sha
            for phase in manifest["phases"][2:]
        )
    ):
        raise CampaignError(
            "downstream campaign is not bound to the semantic model receipt"
        )

    _validate_host(loaded["host-prerequisites"], contract)
    lvs = receipt_set["lvs_multi_provenance"]
    if (
        lvs["agent_receipt_sha256"] != raw_hashes["lvs-agent-session"]
        or lvs["static_result_sha256"] != raw_hashes["lvs-multi-static-oracle"]
        or lvs["live_artifact_set_sha256"]
        != loaded["lvs-agent-session"]["cleanup"]["artifact_set_sha256"]
        or lvs["static_fixture_sha256"]
        != loaded["lvs-multi-static-oracle"]["fixture_sha256"]
        or lvs["connected"] is not False
    ):
        raise CampaignError("LVS live/static provenance linkage drift or overclaim")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "campaign-receipt-set-valid-incomplete-nonpromoting",
        "campaign_id_sha256": sha256(manifest["campaign_id"].encode("utf-8")),
        "manifest_sha256": sha256(manifest_payload),
        "receipt_set_sha256": sha256(receipt_set_payload),
        "model_semantic_receipt_sha256": model_receipt_sha,
        "receipt_count": 12,
        "selected_capability_count": 10,
        "mapped_capability_count": 15,
        "unresolved_blocker_count": 6,
        "runtime_activity_performed": False,
        "authorization_granted": False,
        "evidence_complete": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


def compile_plan() -> dict[str, Any]:
    contract, payloads, _objects = _load_contract_and_sources()
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert-campaign-plan-valid",
        "repository_commit": contract["repository"]["commit"],
        "phase_ids": [row["phase_id"] for row in contract["phases"]],
        "profile_transitions": contract["profile_transitions"],
        "receipt_count": 12,
        "selected_capability_count": 10,
        "mapped_capability_count": 15,
        "source_lock_count": len(contract["source_locks"]),
        "verified_source_file_count": len(payloads),
        "required_blockers": contract["required_blockers"],
        "model_semantic_receipt_required": True,
        "runtime_activity_performed": False,
        "authorization_granted": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("plan")
    check = commands.add_parser("check")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--receipt-set", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = (
            check_campaign(args.manifest, args.receipt_set)
            if args.command == "check"
            else compile_plan()
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except CampaignError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
