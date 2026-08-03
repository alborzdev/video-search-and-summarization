#!/usr/bin/env python3

"""Fail-closed validation for the versioned official VSS capability ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

import capability_oracles as oracle_contract


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
LEDGER = SCRIPT_DIR / "official-capabilities.json"
SCHEMA = SCRIPT_DIR / "official-capabilities.schema.json"
MANIFEST = SCRIPT_DIR / "manifest.json"
ACCEPTANCE = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
ORACLES = SCRIPT_DIR / "capability-oracles.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
CPU_MULTIMEDIA_CAPABILITY_ID = (
    "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"
)
CPU_MULTIMEDIA_SOURCE_CONTROLS = {
    "services/vios/src/framework/media/media_utils/gst_utils.cpp": "08400fd8679288b2ccb4e2d89d7edbaee6e118ea14345626544339718b3e84a9",
    "services/vios/src/framework/media/media_pipelines/transcode_writer_consumer.cpp": "044efd0c133c17277119e065f035d63fc300c9965fea8c2058c5e606c5b2d787",
    "services/vios/src/framework/utilities/config.cpp": "b455d17eade9eea5c4502ed5a99f961849467d10e1b3b733737c55eca1640c92",
    "services/vios/src/framework/platform_specific/nvhwdetection.h": "49c65717f6afa4da93e9b0206cde0664eb2ae51d2ed4a46d15156886c687e7e0",
    "deploy/docker/thor-local/vios/vst_config.json": "0c8e101229e37abb5369386a1185116e8be59a3915bcdb4b7d42a2af2c472399",
    "deploy/docker/thor-local/audio/codec-bundle.lock.json": "97701cf9abc00fdb3fec331abd13228b0d45ce347951a96456b9946882557c78",
    "deploy/docker/thor-local/Dockerfile.vios-streamprocessing": "e71de2ba4a3c74b405e93d17f18f624944e8c8741a430ce5a286096762730285",
    "deploy/docker/thor-local/Dockerfile.vios-nvstreamer": "78117c6a700c7217e9bdcfdf082bbb4eb4f9fead811cdb97072993ec1e9b23d0",
    "deploy/docker/thor-local/vios-codecs/vios_media.py": "8f850b69fe85b87be9ba7fcd52fbf8802dc73e42f665ec12d5fc7afd8a0c543b",
}


class CapabilityContractError(ValueError):
    """The checked-in capability contract is inconsistent."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CapabilityContractError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
    )
    if not isinstance(value, dict):
        raise CapabilityContractError(f"{path.name}: root must be an object")
    return value


def _resolve_repo_file(
    repo_root: Path,
    relative_path: Any,
    *,
    label: str,
    required_prefix: str,
) -> Path:
    if not isinstance(relative_path, str):
        raise CapabilityContractError(f"{label}: repository path must be a string")
    path = Path(relative_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not relative_path.startswith(required_prefix)
    ):
        raise CapabilityContractError(f"{label}: unsafe repository path")
    try:
        resolved_root = repo_root.resolve(strict=True)
        candidate = resolved_root
        for part in path.parts:
            candidate /= part
            if candidate.is_symlink():
                raise CapabilityContractError(
                    f"{label}: repository path contains a symlink"
                )
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except CapabilityContractError:
        raise
    except (OSError, ValueError) as exc:
        raise CapabilityContractError(f"{label}: repository path is missing") from exc
    if not resolved.is_file():
        raise CapabilityContractError(
            f"{label}: repository path must be a regular file"
        )
    return resolved


def _ids(values: Any, label: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise CapabilityContractError(f"{label}: expected a non-empty list")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or PLAIN_ID.fullmatch(value) is None:
            raise CapabilityContractError(f"{label}: invalid id {value!r}")
        result.append(value)
    if len(result) != len(set(result)):
        raise CapabilityContractError(f"{label}: duplicate ids")
    return result


def _aggregate_family_status(capabilities: list[dict[str, Any]]) -> dict[str, str]:
    """Derive manifest family status while preserving external boundaries."""
    if not capabilities:
        raise CapabilityContractError("cannot aggregate an empty capability family")
    classes = {item["acceptance_class"] for item in capabilities}
    acceptance_class = (
        "required_local"
        if "required_local" in classes
        else (
            "external_optional"
            if classes == {"external_optional"}
            else "alternate_local_lane"
        )
    )
    thor_states = {item["thor_state"] for item in capabilities}
    thor_state = (
        "external_optional"
        if acceptance_class == "external_optional"
        else next(iter(thor_states))
        if len(thor_states) == 1
        else "partial"
    )
    runtime_states = {item["runtime_state"] for item in capabilities}
    runtime_state = (
        next(iter(runtime_states)) if len(runtime_states) == 1 else "not_qualified"
    )
    return {
        "acceptance_class": acceptance_class,
        "thor_state": thor_state,
        "runtime_state": runtime_state,
    }


def _validate_cpu_multimedia_contract(
    capability: dict[str, Any], repo_root: Path
) -> None:
    capability_id = capability["id"]
    expected_identity = {
        "feature_id": "vios-codecs-audio",
        "kind": "runtime_behavior",
        "title": "CPU multimedia support",
        "acceptance_class": "required_local",
        "thor_state": "wired",
        "runtime_state": "not_qualified",
        "scenario_ids": ["analytics-vios-workflows"],
    }
    if any(capability.get(key) != value for key, value in expected_identity.items()):
        raise CapabilityContractError(f"{capability_id}: canonical identity drift")
    if "runtime_evidence" in capability:
        raise CapabilityContractError(
            f"{capability_id}: unqualified capability cannot contain runtime evidence"
        )

    contract = capability["contract"]
    selectors = contract.get("selectors")
    branch_selection = contract.get("branch_selection")
    software = contract.get("software_elements")
    hardware_default = contract.get("hardware_default_elements")
    bundle = contract.get("offline_bundle")
    derivatives = contract.get("immutable_derivatives")
    expected_selectors = {
        "use_software_path": {
            "json_pointer": "/data/use_software_path",
            "checked_in_value": False,
            "default": False,
        },
        "USE_SOFTWARE_PATH": {
            "environment_override_for": "/data/use_software_path",
            "accepted_values": ["true", "false"],
        },
        "use_software_encoder": {
            "json_pointer": "/data/use_software_encoder",
            "checked_in_key_present": False,
            "default": False,
        },
    }
    expected_branch_selection = {
        "decoder_gate": "m_useNvV4l2Dec",
        "encoder_gate": "m_useNvV4l2Enc",
        "use_software_path_directly_selects_elements": False,
        "use_software_path_true": {
            "m_useNvV4l2Dec": False,
            "m_useNvV4l2Enc": False,
        },
        "use_software_encoder_true": {
            "m_useNvV4l2Dec": "hardware_availability",
            "m_useNvV4l2Enc": False,
        },
    }
    expected_software = {
        "video_decoders": {"h264": "avdec_h264", "h265": "avdec_h265"},
        "video_encoders": {"h264": "x264enc", "h265": "x265enc"},
        "audio_encoder": "avenc_aac",
        "parsers": ["h264parse", "h265parse"],
    }
    expected_hardware_default = {
        "video_decoder": "nvv4l2decoder",
        "video_encoders": {
            "h264": "nvv4l2h264enc",
            "h265": "nvv4l2h265enc",
        },
    }
    expected_bundle = {
        "lock_path": "deploy/docker/thor-local/audio/codec-bundle.lock.json",
        "architecture": "arm64",
        "package_count": 59,
        "package_set_sha256": "c34db3c88287c8c049190bafdc0096d91f70bdf14a3b0ffdcc30c01fbc11f44f",
    }
    expected_derivatives = {
        "runtime_network_install": "disabled",
        "entrypoint": "/usr/local/bin/vios-offline-entrypoint",
        "dockerfiles": [
            "deploy/docker/thor-local/Dockerfile.vios-streamprocessing",
            "deploy/docker/thor-local/Dockerfile.vios-nvstreamer",
        ],
    }
    if (
        selectors != expected_selectors
        or branch_selection != expected_branch_selection
        or software != expected_software
        or hardware_default != expected_hardware_default
        or bundle != expected_bundle
        or derivatives != expected_derivatives
    ):
        raise CapabilityContractError(f"{capability_id}: exact CPU path contract drift")

    source_controls = contract.get("source_controls")
    if not isinstance(source_controls, list):
        raise CapabilityContractError(f"{capability_id}: source controls are missing")
    observed_controls = {
        item.get("path"): item.get("sha256")
        for item in source_controls
        if isinstance(item, dict)
    }
    if (
        len(observed_controls) != len(source_controls)
        or observed_controls != CPU_MULTIMEDIA_SOURCE_CONTROLS
    ):
        raise CapabilityContractError(f"{capability_id}: source control set drift")
    resolved_controls: dict[str, Path] = {}
    for relative, expected_digest in observed_controls.items():
        required_prefix = (
            "services/vios/"
            if relative.startswith("services/vios/")
            else "deploy/docker/thor-local/"
        )
        resolved = _resolve_repo_file(
            repo_root,
            relative,
            label=f"{capability_id}.source_controls",
            required_prefix=required_prefix,
        )
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected_digest:
            raise CapabilityContractError(
                f"{capability_id}: source control digest drift"
            )
        resolved_controls[relative] = resolved

    config_path = "deploy/docker/thor-local/vios/vst_config.json"
    config = _load(resolved_controls[config_path])
    config_data = config.get("data", {})
    if (
        config_data.get("use_software_path") is not False
        or "use_software_encoder" in config_data
    ):
        raise CapabilityContractError(f"{capability_id}: default CPU selector drift")
    lock = _load(resolved_controls[bundle["lock_path"]])
    if any(
        lock.get(key) != bundle[key]
        for key in ("architecture", "package_count", "package_set_sha256")
    ):
        raise CapabilityContractError(f"{capability_id}: offline bundle identity drift")

    required_fragments = {
        "services/vios/src/framework/media/media_utils/gst_utils.cpp": [
            "x264enc",
            "x265enc",
            "h264parse",
            "h265parse",
        ],
        "services/vios/src/framework/media/media_pipelines/transcode_writer_consumer.cpp": [
            "m_useNvV4l2Dec",
            "m_useNvV4l2Enc",
            "nvv4l2decoder",
            "nvv4l2h264enc",
            "nvv4l2h265enc",
            "avdec_h264",
            "avdec_h265",
            "x264enc",
            "x265enc",
            "avenc_aac",
        ],
        "services/vios/src/framework/utilities/config.cpp": [
            "use_software_path",
            "use_software_encoder",
            "USE_SOFTWARE_PATH",
        ],
        "services/vios/src/framework/platform_specific/nvhwdetection.h": [
            "use_software_path",
            "use_software_encoder",
            "m_useNvV4l2Dec",
            "m_useNvV4l2Enc",
        ],
    }
    for relative, fragments in required_fragments.items():
        text = resolved_controls[relative].read_text(encoding="utf-8")
        if any(fragment not in text for fragment in fragments):
            raise CapabilityContractError(f"{capability_id}: CPU element control drift")
    for relative in derivatives["dockerfiles"]:
        text = resolved_controls[relative].read_text(encoding="utf-8")
        if (
            'com.nvidia.vss.thor.vios-runtime-network-install="disabled"' not in text
            or 'ENTRYPOINT ["/usr/local/bin/vios-offline-entrypoint"]' not in text
        ):
            raise CapabilityContractError(
                f"{capability_id}: immutable derivative control drift"
            )


def _validate_bound_runtime_evidence(
    capability: dict[str, Any],
    oracle: dict[str, Any],
    evidence: dict[str, Any],
    target: dict[str, Any],
) -> None:
    capability_id = capability["id"]
    if oracle.get("capability_id") != capability_id:
        raise CapabilityContractError(
            f"{capability_id}: capability oracle is not bound"
        )
    if oracle.get("acceptance_readiness", {}).get("classification") != "executor_ready":
        raise CapabilityContractError(
            f"{capability_id}: planning_index_only oracle cannot advance runtime state"
        )
    binding = oracle.get("ledger_binding")
    expected_binding = {
        key: capability[key]
        for key in (
            "feature_id",
            "kind",
            "title",
            "source_claims",
            "acceptance_class",
            "thor_state",
            "runtime_state",
            "contract",
            "gap",
        )
    }
    if binding != expected_binding:
        raise CapabilityContractError(f"{capability_id}: oracle ledger binding differs")
    materialization = oracle.get("fixture", {}).get("materialization", {})
    if (
        not all(
            isinstance(materialization.get(key), str) and materialization[key]
            for key in ("path", "generator", "sha256")
        )
        or re.fullmatch(r"[0-9a-f]{64}", materialization["sha256"]) is None
    ):
        raise CapabilityContractError(
            f"{capability_id}: executor-ready fixture is incomplete"
        )
    if (
        not oracle.get("execution_bounds", {}).get("executor")
        or not oracle.get("execution_bounds", {}).get("collectors")
        or not oracle.get("cleanup", {}).get("executor")
        or not oracle.get("cleanup", {}).get("postcondition_collectors")
    ):
        raise CapabilityContractError(
            f"{capability_id}: executor-ready oracle lacks executors or collectors"
        )
    expected_keys = {
        "schema_version",
        "capability_id",
        "oracle_id",
        "oracle_sha256",
        "result",
        "target",
        "scenario_ids",
        "fixture",
        "observations",
        "assertions",
        "cleanup",
    }
    protocol_binding = oracle.get("protocol_case_binding")
    if protocol_binding is not None:
        expected_keys.add("protocol_case")
    if set(evidence) != expected_keys:
        raise CapabilityContractError(
            f"{capability_id}: runtime evidence fields are not exact"
        )
    expected_target = {
        "product_version": target["product_version"],
        "ga_commit": target["ga_commit"],
        "main_commit": target["main_commit"],
        "captured_on": target["captured_on"],
    }
    if (
        type(evidence.get("schema_version")) is not int
        or evidence.get("schema_version") != 1
        or evidence.get("capability_id") != capability_id
        or evidence.get("oracle_id") != oracle["oracle_id"]
        or evidence.get("oracle_sha256")
        != oracle_contract.canonical_oracle_sha256(oracle)
        or evidence.get("result") != "passed_current"
        or evidence.get("target") != expected_target
        or evidence.get("scenario_ids") != oracle["reviewed_scenario_ids"]
    ):
        raise CapabilityContractError(
            f"{capability_id}: runtime evidence metadata is not bound to the exact oracle"
        )
    permitted_scenarios = set(capability["scenario_ids"]) | {oracle["oracle_id"]}
    if (
        set(evidence["scenario_ids"]) != permitted_scenarios
        or oracle["oracle_id"] not in evidence["scenario_ids"]
    ):
        raise CapabilityContractError(
            f"{capability_id}: runtime evidence scenario set is not oracle-bound"
        )
    expected_fixture = {
        "id": oracle["fixture"]["id"],
        "path": materialization["path"],
        "sha256": materialization["sha256"],
    }
    if evidence.get("fixture") != expected_fixture:
        raise CapabilityContractError(f"{capability_id}: fixture evidence is not bound")
    if protocol_binding is not None:
        expected_protocol = {
            "path": protocol_binding["path"],
            "file_sha256": protocol_binding["file_sha256"],
            "contract_set_sha256": protocol_binding["contract_set_sha256"],
            "target_commit": protocol_binding["target_commit"],
            "case_id": protocol_binding["case_id"],
            "case_sha256": protocol_binding["case_sha256"],
            "positive_vector_id": protocol_binding["positive_vector_id"],
            "negative_vector_ids": protocol_binding["negative_vector_ids"],
            "source_hashes": protocol_binding["source_hashes"],
            "cleanup_result": "pass",
        }
        if evidence.get("protocol_case") != expected_protocol:
            raise CapabilityContractError(
                f"{capability_id}: protocol case evidence is not bound to exact hashes and vectors"
            )
    observations = evidence.get("observations")
    expected_observation_ids = [item["id"] for item in oracle["expected_observations"]]
    if (
        not isinstance(observations, list)
        or [item.get("id") for item in observations if isinstance(item, dict)]
        != expected_observation_ids
        or any(
            set(item) != {"id", "result", "value"} or item.get("result") != "pass"
            for item in observations
            if isinstance(item, dict)
        )
        or any(not isinstance(item, dict) for item in observations)
    ):
        raise CapabilityContractError(
            f"{capability_id}: every required observation must pass in oracle order"
        )
    assertions = evidence.get("assertions")
    if not isinstance(assertions, list) or len(assertions) != len(oracle["assertions"]):
        raise CapabilityContractError(
            f"{capability_id}: every required assertion must be evidenced"
        )
    for required, observed in zip(oracle["assertions"], assertions, strict=True):
        if not isinstance(observed, dict) or set(observed) != {
            "id",
            "observation",
            "operator",
            "expected",
            "observed",
            "result",
        }:
            raise CapabilityContractError(
                f"{capability_id}: malformed assertion evidence"
            )
        if (
            observed["id"] != required["id"]
            or observed["observation"] != required["observation"]
            or observed["operator"] != required["operator"]
            or observed["expected"] != required["expected"]
            or observed["result"] != "pass"
        ):
            raise CapabilityContractError(
                f"{capability_id}: assertion evidence is not bound to expected semantics"
            )
        if (
            required["operator"] == "equals"
            and observed["observed"] != required["expected"]
        ) or (
            required["operator"] == "recorded_pass" and observed["observed"] is not True
        ):
            raise CapabilityContractError(
                f"{capability_id}: assertion observed value does not satisfy the oracle"
            )
    cleanup = evidence.get("cleanup")
    expected_cleanup = oracle["cleanup"]
    if not isinstance(cleanup, dict) or set(cleanup) != {
        "result",
        "mutation",
        "targets",
        "allowlist",
        "pre_state_captured",
        "postconditions",
    }:
        raise CapabilityContractError(f"{capability_id}: cleanup evidence is malformed")
    expected_postconditions = [
        {"description": description, "result": "pass"}
        for description in expected_cleanup["postconditions"]
    ]
    if (
        cleanup["result"] != "pass"
        or cleanup["mutation"] != expected_cleanup["mutation"]
        or cleanup["targets"] != expected_cleanup["targets"]
        or cleanup["allowlist"] != expected_cleanup["allowlist"]
        or cleanup["pre_state_captured"] is not True
        or cleanup["postconditions"] != expected_postconditions
    ):
        raise CapabilityContractError(
            f"{capability_id}: cleanup did not satisfy exact oracle postconditions"
        )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise CapabilityContractError(
            f"aggregate captured-checkout provenance failed: {' '.join(args)}"
        )
    return result.stdout


def _git_blob(repo_root: Path, commit: str, path: str) -> bytes:
    if not isinstance(path, str) or not path:
        raise CapabilityContractError("aggregate provenance contains an unsafe path")
    normalized = Path(path)
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or path != str(normalized)
        or normalized.parts[0] == ".git"
        or any(character in path for character in ("\x00", "\n", "\r"))
    ):
        raise CapabilityContractError("aggregate provenance contains an unsafe path")
    return _git_bytes(repo_root, "show", f"{commit}:{path}")


def _git_json_blob(repo_root: Path, commit: str, path: str) -> dict[str, Any]:
    raw = _git_blob(repo_root, commit, path)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    if not isinstance(value, dict):
        raise CapabilityContractError("aggregate provenance JSON root is not an object")
    return value


def _select_aggregate_capability(
    aggregate: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    pointer = reference.get("json_pointer")
    if (
        not isinstance(pointer, str)
        or re.fullmatch(r"/capability_results/(0|[1-9][0-9]*)", pointer) is None
    ):
        raise CapabilityContractError(
            "aggregate runtime evidence selector must be an exact capability-results JSON pointer"
        )
    index = int(pointer.rsplit("/", 1)[1])
    rows = aggregate.get("capability_results")
    if not isinstance(rows, list) or index >= len(rows):
        raise CapabilityContractError(
            "aggregate runtime evidence selector is out of range"
        )
    selected = rows[index]
    if not isinstance(selected, dict) or selected.get("capability_id") != reference.get(
        "capability_id"
    ):
        raise CapabilityContractError(
            "aggregate runtime evidence selector does not match capability_id"
        )
    return selected


def _validate_aggregate_runtime_evidence(
    aggregate: dict[str, Any],
    reference: dict[str, Any],
    capability: dict[str, Any],
    capabilities_by_id: dict[str, dict[str, Any]],
    oracles_by_id: dict[str, dict[str, Any]],
    target: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    capability_id = capability["id"]
    if set(reference) != {"path", "sha256", "capability_id", "json_pointer"}:
        raise CapabilityContractError(
            f"{capability_id}: aggregate runtime evidence reference fields are not exact"
        )
    if reference["capability_id"] != capability_id:
        raise CapabilityContractError(
            f"{capability_id}: aggregate runtime evidence capability selector differs"
        )
    top_keys = {
        "schema_version",
        "package_id",
        "mode",
        "status",
        "captured_at_utc",
        "bindings",
        "environment",
        "capability_results",
        "cleanup",
        "confinement",
        "promotion",
    }
    if set(aggregate) != top_keys:
        raise CapabilityContractError("aggregate runtime evidence fields are not exact")
    captured_at = aggregate.get("captured_at_utc")
    if (
        type(aggregate.get("schema_version")) is not int
        or aggregate["schema_version"] != 1
        or aggregate.get("mode") != "target_bound_offline_runtime_evidence"
        or aggregate.get("status") != "pass"
        or not isinstance(captured_at, str)
        or not captured_at.endswith("Z")
    ):
        raise CapabilityContractError(
            "aggregate runtime evidence is not a passed execution"
        )

    bindings = aggregate.get("bindings")
    binding_keys = {
        "checkout_head",
        "checkout_tree",
        "checkout_clean",
        "checkout_status_porcelain_sha256",
        "upstream_commit",
        "product_version",
        "current_oracle_document_path",
        "current_oracle_row_sha256",
        "current_ledger_row_sha256",
        "execution_oracle_document_path",
        "execution_oracle_document_sha256",
        "execution_oracle_row_sha256",
        "execution_oracles_executor_ready",
        "fixture_manifest_sha256",
        "contract_sha256",
        "executor_sha256",
    }
    empty_sha = hashlib.sha256(b"").hexdigest()
    if (
        not isinstance(bindings, dict)
        or set(bindings) != binding_keys
        or bindings.get("checkout_clean") is not True
        or bindings.get("checkout_status_porcelain_sha256") != empty_sha
        or bindings.get("execution_oracles_executor_ready") is not True
        or HEX40.fullmatch(str(bindings.get("checkout_head"))) is None
        or HEX40.fullmatch(str(bindings.get("checkout_tree"))) is None
        or bindings.get("upstream_commit") != target["main_commit"]
        or bindings.get("product_version") != target["product_version"]
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(bindings.get(key))) is None
            for key in (
                "execution_oracle_document_sha256",
                "contract_sha256",
                "executor_sha256",
            )
        )
    ):
        raise CapabilityContractError(
            "aggregate runtime evidence is not clean/executor/contract bound"
        )
    captured_commit = bindings["checkout_head"]
    _git_bytes(repo_root, "cat-file", "-e", f"{captured_commit}^{{commit}}")
    captured_tree = (
        _git_bytes(repo_root, "rev-parse", f"{captured_commit}^{{tree}}")
        .decode("ascii")
        .strip()
    )
    if captured_tree != bindings["checkout_tree"]:
        raise CapabilityContractError(
            "aggregate captured checkout tree differs from its commit"
        )
    _git_bytes(
        repo_root,
        "merge-base",
        "--is-ancestor",
        target["main_commit"],
        captured_commit,
    )
    execution_oracle_path = bindings["execution_oracle_document_path"]
    execution_oracle_raw = _git_blob(repo_root, captured_commit, execution_oracle_path)
    if (
        hashlib.sha256(execution_oracle_raw).hexdigest()
        != bindings["execution_oracle_document_sha256"]
    ):
        raise CapabilityContractError(
            "aggregate execution-oracle blob differs at captured commit"
        )
    execution_oracle_document = json.loads(
        execution_oracle_raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
    )
    if not isinstance(execution_oracle_document, dict):
        raise CapabilityContractError(
            "aggregate execution-oracle root is not an object"
        )
    historical_oracles = {
        row.get("capability_id"): row
        for row in execution_oracle_document.get("oracles", [])
        if isinstance(row, dict)
    }

    promotion = aggregate.get("promotion")
    promotion_keys = {
        "receipt_is_runtime_evidence",
        "aggregate_is_promotable",
        "eligible_capability_ids",
        "family_id",
        "ledger_mutation_performed",
        "requires_separate_reviewed_metadata_integration",
        "development_smoke_only",
        "dependency_pin_parity_claimed",
    }
    if (
        not isinstance(promotion, dict)
        or set(promotion) != promotion_keys
        or promotion.get("receipt_is_runtime_evidence") is not True
        or promotion.get("aggregate_is_promotable") is not True
        or promotion.get("development_smoke_only") is not False
        or promotion.get("ledger_mutation_performed") is not False
        or promotion.get("requires_separate_reviewed_metadata_integration") is not True
        or promotion.get("dependency_pin_parity_claimed") is not False
    ):
        raise CapabilityContractError(
            "aggregate runtime evidence is development or non-promotable"
        )

    environment = aggregate.get("environment")
    if not isinstance(environment, dict) or set(environment) != {
        "platform",
        "python",
        "declared_requirements",
        "observed_distributions",
        "observed_modules",
        "declared_versions_match_observed",
        "dependency_caveat",
        "normative_scope",
    }:
        raise CapabilityContractError(
            "aggregate runtime evidence environment is not exact"
        )
    if (
        promotion.get("dependency_pin_parity_claimed")
        is not environment.get("declared_versions_match_observed")
        or environment.get("normative_scope") != "observed_current_thor_behavior_only"
    ):
        raise CapabilityContractError(
            "aggregate dependency parity claim differs from observed environment"
        )

    rows = aggregate.get("capability_results")
    eligible_ids = promotion.get("eligible_capability_ids")
    if (
        not isinstance(rows, list)
        or not rows
        or not isinstance(eligible_ids, list)
        or [row.get("capability_id") for row in rows if isinstance(row, dict)]
        != eligible_ids
        or len(set(eligible_ids)) != len(eligible_ids)
    ):
        raise CapabilityContractError(
            "aggregate runtime evidence capability denominator differs"
        )
    for map_key in (
        "current_oracle_row_sha256",
        "current_ledger_row_sha256",
        "execution_oracle_row_sha256",
        "fixture_manifest_sha256",
    ):
        value = bindings.get(map_key)
        if not isinstance(value, dict) or list(value) != eligible_ids:
            raise CapabilityContractError(
                f"aggregate runtime evidence {map_key} denominator differs"
            )
    selected_capabilities = [capabilities_by_id.get(row_id) for row_id in eligible_ids]
    if any(not isinstance(item, dict) for item in selected_capabilities):
        raise CapabilityContractError(
            "aggregate eligible capability lacks canonical ledger authority"
        )
    selected_feature_ids = {item["feature_id"] for item in selected_capabilities}
    if len(selected_feature_ids) != 1 or promotion.get("family_id") != next(
        iter(selected_feature_ids)
    ):
        raise CapabilityContractError(
            "aggregate promotion family differs from canonical capability family"
        )
    executor_paths = {
        oracles_by_id[row_id].get("execution_bounds", {}).get("executor")
        for row_id in eligible_ids
    }
    if len(executor_paths) != 1 or not all(
        isinstance(item, str) for item in executor_paths
    ):
        raise CapabilityContractError(
            "aggregate eligible capabilities do not share one exact executor"
        )
    executor_path = next(iter(executor_paths))
    executor_raw = _git_blob(repo_root, captured_commit, executor_path)
    if hashlib.sha256(executor_raw).hexdigest() != bindings["executor_sha256"]:
        raise CapabilityContractError(
            "aggregate executor blob differs at captured commit"
        )
    contract_path = str(Path(executor_path).with_name("contract.json"))
    contract_raw = _git_blob(repo_root, captured_commit, contract_path)
    if hashlib.sha256(contract_raw).hexdigest() != bindings["contract_sha256"]:
        raise CapabilityContractError(
            "aggregate contract blob differs at captured commit"
        )
    contract_document = json.loads(
        contract_raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
    )
    if (
        not isinstance(contract_document, dict)
        or contract_document.get("package_id") != aggregate.get("package_id")
        or contract_document.get("mode") != aggregate.get("mode")
        or contract_document.get("target", {}).get("upstream_commit")
        != target["main_commit"]
        or contract_document.get("target", {}).get("product_version")
        != target["product_version"]
        or contract_document.get("target", {}).get("current_oracle_document")
        != bindings["current_oracle_document_path"]
    ):
        raise CapabilityContractError(
            "aggregate contract identity/target differs from receipt bindings"
        )
    contract_capabilities = contract_document.get("capabilities")
    if (
        not isinstance(contract_capabilities, list)
        or [item.get("capability_id") for item in contract_capabilities] != eligible_ids
    ):
        raise CapabilityContractError(
            "aggregate contract capability denominator differs"
        )
    contract_by_id = {item["capability_id"]: item for item in contract_capabilities}
    seen_source_controls: dict[str, str] = {}
    for contract_capability in contract_capabilities:
        source_controls = contract_capability.get("source_controls")
        if not isinstance(source_controls, list) or not source_controls:
            raise CapabilityContractError(
                "aggregate contract capability has no exact source controls"
            )
        for control in source_controls:
            if (
                not isinstance(control, dict)
                or set(control) != {"path", "sha256"}
                or not isinstance(control.get("path"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(control.get("sha256"))) is None
            ):
                raise CapabilityContractError(
                    "aggregate contract source control is malformed"
                )
            previous = seen_source_controls.setdefault(
                control["path"], control["sha256"]
            )
            if previous != control["sha256"]:
                raise CapabilityContractError(
                    "aggregate contract source control digest conflicts"
                )
            source_raw = _git_blob(repo_root, captured_commit, control["path"])
            if hashlib.sha256(source_raw).hexdigest() != control["sha256"]:
                raise CapabilityContractError(
                    "aggregate source-control blob differs at captured commit"
                )
    historical_current_oracles = _git_json_blob(
        repo_root,
        captured_commit,
        bindings["current_oracle_document_path"],
    )
    current_oracles_by_id = {
        row.get("capability_id"): row
        for row in historical_current_oracles.get("oracles", [])
        if isinstance(row, dict)
    }
    historical_ledger = _git_json_blob(
        repo_root,
        captured_commit,
        "deploy/docker/thor-local/parity/official-capabilities.json",
    )
    historical_ledger_by_id = {
        row.get("id"): row
        for row in historical_ledger.get("capabilities", [])
        if isinstance(row, dict)
    }
    for row_id in eligible_ids:
        if (
            _json_sha256(current_oracles_by_id.get(row_id))
            != bindings["current_oracle_row_sha256"][row_id]
            or _json_sha256(historical_ledger_by_id.get(row_id))
            != bindings["current_ledger_row_sha256"][row_id]
        ):
            raise CapabilityContractError(
                f"{row_id}: aggregate current oracle/ledger provenance differs"
            )

    capability_keys = {
        "capability_id",
        "oracle_id",
        "status",
        "independent_runs",
        "bounded_capability_actions",
        "target_case_actions",
        "supporting_cam_generation_actions",
        "requests",
        "imported_helper_invocations",
        "total_imported_source_function_invocations",
        "imported_source_function_counts",
        "deterministic_output",
        "fixture_sha256",
        "payload_sha256",
        "run_output_sha256",
        "positive_observations",
        "adjacent_negatives",
        "oracle_observations",
        "oracle_assertions",
        "runtime_evidence_binding",
        "official_receipt",
        "cleanup",
    }
    aggregate_counts = {
        "bounded_capability_actions": 0,
        "target_case_actions": 0,
        "supporting_cam_generation_actions": 0,
        "requests": 0,
        "imported_helper_invocations": 0,
        "total_imported_source_function_invocations": 0,
    }
    aggregate_function_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != capability_keys:
            raise CapabilityContractError(
                "aggregate capability result fields are not exact"
            )
        row_id = row["capability_id"]
        row_capability = capabilities_by_id.get(row_id)
        oracle = oracles_by_id.get(row_id)
        if row_capability is None or oracle is None:
            raise CapabilityContractError(
                f"{row_id}: aggregate row lacks canonical capability/oracle authority"
            )
        independent_runs = row.get("independent_runs")
        target_actions = row.get("target_case_actions")
        supporting_actions = row.get("supporting_cam_generation_actions")
        bounded_actions = row.get("bounded_capability_actions")
        requests = row.get("requests")
        helper_invocations = row.get("imported_helper_invocations")
        total_invocations = row.get("total_imported_source_function_invocations")
        run_hashes = row.get("run_output_sha256")
        negatives = row.get("adjacent_negatives")
        function_counts = row.get("imported_source_function_counts")
        if (
            row.get("oracle_id") != oracle["oracle_id"]
            or row.get("status") != "pass"
            or type(independent_runs) is not int
            or independent_runs < 2
            or type(target_actions) is not int
            or type(supporting_actions) is not int
            or type(bounded_actions) is not int
            or type(requests) is not int
            or type(helper_invocations) is not int
            or type(total_invocations) is not int
            or target_actions != requests
            or bounded_actions != target_actions + supporting_actions
            or total_invocations != bounded_actions + helper_invocations
            or row.get("deterministic_output") is not True
            or not isinstance(run_hashes, list)
            or len(run_hashes) != independent_runs
            or len(set(run_hashes)) != 1
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(item)) is None for item in run_hashes
            )
            or not isinstance(negatives, list)
            or len(negatives) != target_actions - independent_runs
            or any(
                not isinstance(item, dict)
                or set(item) != {"case_id", "rejected", "exception"}
                or item["rejected"] is not True
                for item in negatives
            )
            or not isinstance(function_counts, dict)
            or not function_counts
            or any(
                type(value) is not int or value < 0
                for value in function_counts.values()
            )
            or sum(function_counts.values()) != total_invocations
        ):
            raise CapabilityContractError(
                f"{row_id}: aggregate capability execution semantics differ"
            )
        positive = row.get("positive_observations")
        if (
            not isinstance(positive, dict)
            or set(positive)
            != {
                "payload_sha256",
                "output_sha256",
                "file_sha256",
                "semantic",
                "input_unchanged",
            }
            or positive.get("input_unchanged") is not True
            or positive.get("payload_sha256") != row.get("payload_sha256")
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
                for value in (
                    row.get("fixture_sha256"),
                    row.get("payload_sha256"),
                    positive.get("output_sha256"),
                )
            )
        ):
            raise CapabilityContractError(
                f"{row_id}: aggregate positive observations are not exact"
            )
        row_cleanup = row.get("cleanup")
        if (
            not isinstance(row_cleanup, dict)
            or set(row_cleanup)
            != {
                "namespace",
                "pre_state_captured",
                "temporary_files_only",
                "removed",
                "siblings_unchanged",
            }
            or row_cleanup.get("pre_state_captured") != "absent"
            or any(
                row_cleanup.get(key) is not True
                for key in ("temporary_files_only", "removed", "siblings_unchanged")
            )
        ):
            raise CapabilityContractError(f"{row_id}: aggregate cleanup differs")

        official = row["official_receipt"]
        if not isinstance(official, dict):
            raise CapabilityContractError(
                f"{row_id}: aggregate official receipt must be an object"
            )
        contract_capability = contract_by_id[row_id]
        fixture_lock = contract_capability.get("fixture_manifest")
        if (
            contract_capability.get("oracle_id") != oracle["oracle_id"]
            or not isinstance(fixture_lock, dict)
            or set(fixture_lock) != {"path", "sha256"}
            or fixture_lock.get("path") != official.get("fixture", {}).get("path")
            or fixture_lock.get("sha256") != row["fixture_sha256"]
            or contract_document.get("policy", {})
            .get("supporting_cam_generation_actions", {})
            .get(row_id)
            != supporting_actions
            or contract_document.get("policy", {}).get(
                "target_case_actions_per_capability"
            )
            != target_actions
            or contract_document.get("policy", {}).get("independent_positive_runs")
            != independent_runs
            or contract_document.get("policy", {}).get(
                "adjacent_negative_count_per_capability"
            )
            != len(negatives)
        ):
            raise CapabilityContractError(
                f"{row_id}: aggregate contract capability/fixture mapping differs"
            )
        if historical_oracles.get(row_id) != oracle:
            raise CapabilityContractError(
                f"{row_id}: aggregate oracle differs from captured oracle document"
            )
        official_fixture = official.get("fixture")
        if not isinstance(official_fixture, dict) or not isinstance(
            official_fixture.get("path"), str
        ):
            raise CapabilityContractError(
                f"{row_id}: aggregate official fixture reference is absent"
            )
        fixture_raw = _git_blob(repo_root, captured_commit, official_fixture["path"])
        if hashlib.sha256(fixture_raw).hexdigest() != row["fixture_sha256"]:
            raise CapabilityContractError(
                f"{row_id}: aggregate fixture blob differs at captured commit"
            )
        if official.get("observations") != row.get(
            "oracle_observations"
        ) or official.get("assertions") != row.get("oracle_assertions"):
            raise CapabilityContractError(
                f"{row_id}: aggregate outer observations differ from official receipt"
            )
        _validate_bound_runtime_evidence(row_capability, oracle, official, target)

        evidence_payload = {
            key: value
            for key, value in row.items()
            if key not in {"official_receipt", "runtime_evidence_binding"}
        }
        expected_outer = {
            "schema_version": 1,
            "captured_at_utc": captured_at,
            "executor_sha256": bindings["executor_sha256"],
            "contract_sha256": bindings["contract_sha256"],
            "oracle_sha256": oracle_contract.canonical_oracle_sha256(oracle),
            "oracle_document_sha256": bindings["execution_oracle_document_sha256"],
            "official_receipt_sha256": _json_sha256(official),
            "product_execution_deadline_seconds": oracle["execution_bounds"][
                "max_duration_seconds"
            ],
            "bounded_capability_actions": bounded_actions,
            "target_case_actions": target_actions,
            "supporting_cam_generation_actions": supporting_actions,
            "requests": requests,
            "imported_helper_invocations": helper_invocations,
            "total_imported_source_function_invocations": total_invocations,
            "run_output_sha256": run_hashes,
            "positive_output_sha256": positive["output_sha256"],
            "adjacent_negatives_sha256": _json_sha256(negatives),
            "capability_evidence_sha256": _json_sha256(evidence_payload),
        }
        if row.get("runtime_evidence_binding") != expected_outer:
            raise CapabilityContractError(
                f"{row_id}: aggregate outer runtime evidence binding differs"
            )
        if (
            bindings["execution_oracle_row_sha256"].get(row_id)
            != expected_outer["oracle_sha256"]
            or bindings["fixture_manifest_sha256"].get(row_id) != row["fixture_sha256"]
        ):
            raise CapabilityContractError(
                f"{row_id}: aggregate binding maps differ from selected evidence"
            )
        for key in aggregate_counts:
            aggregate_counts[key] += row[key]
        for key, value in function_counts.items():
            aggregate_function_counts[key] = (
                aggregate_function_counts.get(key, 0) + value
            )

    if aggregate.get("cleanup") != {
        "root_removed": True,
        "exact_namespace_count": len(rows),
        "sibling_names_unchanged": True,
        "repository_mutations": 0,
    }:
        raise CapabilityContractError("aggregate root cleanup differs")
    policy = contract_document.get("policy", {})
    if (
        policy.get("aggregate_bounded_capability_actions")
        != aggregate_counts["bounded_capability_actions"]
        or policy.get("aggregate_requests") != aggregate_counts["requests"]
        or policy.get("aggregate_imported_helper_invocations")
        != aggregate_counts["imported_helper_invocations"]
        or policy.get("aggregate_total_imported_source_function_invocations")
        != aggregate_counts["total_imported_source_function_invocations"]
        or policy.get("aggregate_imported_source_function_counts")
        != aggregate_function_counts
    ):
        raise CapabilityContractError(
            "aggregate contract policy differs from observed execution accounting"
        )
    confinement = aggregate.get("confinement")
    confinement_keys = {
        "network_calls",
        "docker_calls",
        "service_lifecycle_calls",
        "model_accesses",
        "downloads",
        "warehouse_sample_accesses",
        *aggregate_counts.keys(),
        "imported_source_function_counts",
        "product_subprocess_calls",
        "provenance_git_command_count",
        "network_boundary",
        "product_execution_deadline_seconds",
    }
    if not isinstance(confinement, dict) or set(confinement) != confinement_keys:
        raise CapabilityContractError("aggregate confinement fields are not exact")
    if any(
        confinement.get(key) != 0
        for key in (
            "network_calls",
            "docker_calls",
            "service_lifecycle_calls",
            "model_accesses",
            "downloads",
            "warehouse_sample_accesses",
            "product_subprocess_calls",
        )
    ) or any(confinement.get(key) != value for key, value in aggregate_counts.items()):
        raise CapabilityContractError("aggregate confinement action counts differ")
    if (
        confinement.get("imported_source_function_counts") != aggregate_function_counts
        or confinement.get("product_execution_deadline_seconds")
        != max(
            oracles_by_id[row["capability_id"]]["execution_bounds"][
                "max_duration_seconds"
            ]
            for row in rows
        )
        or type(confinement.get("provenance_git_command_count")) is not int
        or confinement["provenance_git_command_count"] < 1
        or not isinstance(confinement.get("network_boundary"), str)
        or not confinement["network_boundary"]
    ):
        raise CapabilityContractError("aggregate confinement provenance differs")

    selected = _select_aggregate_capability(aggregate, reference)
    if selected.get("capability_id") != capability_id:
        raise CapabilityContractError(
            f"{capability_id}: selected aggregate capability row differs"
        )
    return selected


def validate(
    ledger: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    acceptance: dict[str, Any] | None = None,
    oracle_plan: dict[str, Any] | None = None,
    oracle_schema: dict[str, Any] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    ledger = _load(LEDGER) if ledger is None else ledger
    manifest = _load(MANIFEST) if manifest is None else manifest
    acceptance = _load(ACCEPTANCE) if acceptance is None else acceptance
    injected_oracle_plan = oracle_plan is not None
    if oracle_plan is None:
        oracle_plan = _load(ORACLES)
        try:
            # Validate the checked oracle artifact against the checked ledger.
            # Tests may inject a prospective ledger transition, but cannot
            # bypass the integrity of the repository's current oracle plan.
            oracle_contract.validate(oracle_plan, oracle_contract._load(LEDGER))
        except oracle_contract.OracleContractError as exc:
            raise CapabilityContractError(
                f"capability oracle contract invalid: {exc}"
            ) from exc
    else:
        if oracle_schema is None:
            raise CapabilityContractError(
                "an injected capability oracle plan requires its exact schema"
            )
        try:
            Draft202012Validator.check_schema(oracle_schema)
        except SchemaError as exc:
            raise CapabilityContractError(
                f"invalid injected capability oracle schema: {exc.message}"
            ) from exc
        oracle_errors = sorted(
            Draft202012Validator(oracle_schema).iter_errors(oracle_plan),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if oracle_errors:
            error = oracle_errors[0]
            path = ".".join(str(item) for item in error.absolute_path) or "<root>"
            raise CapabilityContractError(
                f"injected capability oracle schema violation at {path}: "
                f"{error.message}"
            )
    oracle_by_capability = {
        item.get("capability_id"): item
        for item in oracle_plan.get("oracles", [])
        if isinstance(item, dict)
    }
    schema = _load(SCHEMA)
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise CapabilityContractError("schema must declare JSON Schema draft 2020-12")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CapabilityContractError(
            f"invalid official capability schema: {exc.message}"
        ) from exc
    schema_errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            ledger
        ),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if schema_errors:
        error = schema_errors[0]
        path = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise CapabilityContractError(
            f"ledger schema violation at {path}: {error.message}"
        )
    if ledger.get("schema_version") != 1:
        raise CapabilityContractError("ledger schema_version must be 1")

    target = ledger.get("target")
    if not isinstance(target, dict) or target.get("product_version") != "3.2.1":
        raise CapabilityContractError("target must be VSS 3.2.1")
    if not all(
        HEX40.fullmatch(str(target.get(key, "")))
        for key in ("ga_commit", "main_commit")
    ):
        raise CapabilityContractError(
            "target commits must be lowercase 40-character SHAs"
        )
    upstream = manifest.get("upstream", {})
    if target["ga_commit"] != upstream.get("latest_ga_commit") or target[
        "main_commit"
    ] != upstream.get("target_commit"):
        raise CapabilityContractError("ledger target differs from parity manifest")

    sources = ledger.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CapabilityContractError("sources must be a non-empty list")
    source_ids = _ids(
        [item.get("id") for item in sources if isinstance(item, dict)], "sources"
    )
    if len(source_ids) != len(sources):
        raise CapabilityContractError("every source must be an object with an id")
    for source in sources:
        if source.get("kind") not in {
            "versioned_official_docs",
            "release_notes",
            "tagged_repository",
            "main_repository",
        }:
            raise CapabilityContractError(f"{source['id']}: invalid source kind")
        if not all(
            isinstance(source.get(key), str) and source[key]
            for key in ("uri", "version", "locator_policy")
        ):
            raise CapabilityContractError(f"{source['id']}: incomplete source record")
        if (
            re.fullmatch(r"[0-9a-f]{64}", str(source.get("claim_set_sha256", "")))
            is None
        ):
            raise CapabilityContractError(f"{source['id']}: invalid claim-set hash")

    features = manifest.get("features")
    if not isinstance(features, list):
        raise CapabilityContractError("manifest features must be a list")
    feature_by_id = {
        item.get("id"): item for item in features if isinstance(item, dict)
    }
    scenario_values = acceptance.get("scenarios")
    if not isinstance(scenario_values, list):
        raise CapabilityContractError("acceptance scenarios must be a list")
    scenario_ids = {
        item.get("id") for item in scenario_values if isinstance(item, dict)
    }

    capabilities = ledger.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise CapabilityContractError("capabilities must be a non-empty list")
    capability_ids = _ids(
        [item.get("id") for item in capabilities if isinstance(item, dict)],
        "capabilities",
    )
    if len(capability_ids) != len(capabilities):
        raise CapabilityContractError("every capability must be an object with an id")
    capability_by_id = {item["id"]: item for item in capabilities}
    if injected_oracle_plan:
        oracle_rows = oracle_plan.get("oracles")
        if not isinstance(oracle_rows, list) or not all(
            isinstance(item, dict) for item in oracle_rows
        ):
            raise CapabilityContractError(
                "injected capability oracle plan has no exact oracle collection"
            )
        if [item.get("capability_id") for item in oracle_rows] != capability_ids:
            raise CapabilityContractError(
                "injected capability oracle order differs from the ledger"
            )
        oracle_target = oracle_plan.get("target")
        if not isinstance(oracle_target, dict) or any(
            oracle_target.get(key) != target[key]
            for key in ("product_version", "main_commit", "captured_on")
        ):
            raise CapabilityContractError(
                "injected capability oracle target differs from the ledger"
            )
        for capability, oracle in zip(capabilities, oracle_rows, strict=True):
            expected_binding = {
                key: capability[key]
                for key in (
                    "feature_id",
                    "kind",
                    "title",
                    "source_claims",
                    "acceptance_class",
                    "thor_state",
                    "runtime_state",
                    "contract",
                    "gap",
                )
            }
            if oracle.get("ledger_binding") != expected_binding:
                raise CapabilityContractError(
                    f"{capability['id']}: injected capability oracle binding differs"
                )
    allowed_classes = set(manifest["status_contract"]["acceptance_class"])
    allowed_thor = set(manifest["status_contract"]["thor_state"])
    allowed_runtime = set(manifest["status_contract"]["runtime_state"])
    by_feature: dict[str, set[str]] = {}
    for capability in capabilities:
        capability_id = capability["id"]
        feature_id = capability.get("feature_id")
        feature = feature_by_id.get(feature_id)
        if feature is None:
            raise CapabilityContractError(
                f"{capability_id}: unknown feature_id {feature_id!r}"
            )
        if (
            capability.get("acceptance_class") not in allowed_classes
            or capability.get("thor_state") not in allowed_thor
            or capability.get("runtime_state") not in allowed_runtime
        ):
            raise CapabilityContractError(f"{capability_id}: invalid status")
        if not isinstance(capability.get("title"), str) or not capability["title"]:
            raise CapabilityContractError(f"{capability_id}: title is required")
        if capability["title"] not in feature.get("advertised", []):
            raise CapabilityContractError(
                f"{capability_id}: title is not an exact manifest capability"
            )
        claims = capability.get("source_claims")
        if not isinstance(claims, list) or not claims:
            raise CapabilityContractError(
                f"{capability_id}: source_claims are required"
            )
        for claim in claims:
            if (
                not isinstance(claim, dict)
                or claim.get("source_id") not in source_ids
                or not isinstance(claim.get("locator"), str)
                or not claim["locator"]
            ):
                raise CapabilityContractError(f"{capability_id}: invalid source claim")
        linked_scenarios = _ids(
            capability.get("scenario_ids"), f"{capability_id}.scenario_ids"
        )
        if not set(linked_scenarios) <= scenario_ids:
            raise CapabilityContractError(
                f"{capability_id}: unknown acceptance scenario"
            )
        if (
            not isinstance(capability.get("contract"), dict)
            or not capability["contract"]
        ):
            raise CapabilityContractError(
                f"{capability_id}: exact contract is required"
            )
        contract = capability["contract"]
        if capability_id == CPU_MULTIMEDIA_CAPABILITY_ID:
            _validate_cpu_multimedia_contract(capability, repo_root)
        if "expected_manifest" in contract:
            expected_manifest = _resolve_repo_file(
                repo_root,
                contract["expected_manifest"],
                label=f"{capability_id}.expected_manifest",
                required_prefix="deploy/docker/thor-local/qualification/expected/",
            )
            expected_digest = contract.get("expected_manifest_sha256")
            if (
                not isinstance(expected_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
                or hashlib.sha256(expected_manifest.read_bytes()).hexdigest()
                != expected_digest
            ):
                raise CapabilityContractError(
                    f"{capability_id}: expected operation manifest digest differs"
                )
            operation_manifest = _load(expected_manifest)
            implementation_count = contract.get(
                "implementation_operation_count", contract.get("operation_count")
            )
            if (
                implementation_count is not None
                and operation_manifest.get("normalized_unique_operation_count")
                != implementation_count
            ):
                raise CapabilityContractError(
                    f"{capability_id}: expected operation count differs"
                )
            extensions = contract.get("thor_local_extensions", [])
            if extensions:
                if not isinstance(extensions, list) or any(
                    not isinstance(item, dict)
                    or set(item) != {"method", "path"}
                    or not isinstance(item["method"], str)
                    or not isinstance(item["path"], str)
                    for item in extensions
                ):
                    raise CapabilityContractError(
                        f"{capability_id}: malformed Thor-local extension set"
                    )
                extension_routes = {
                    (item["method"], item["path"]) for item in extensions
                }
                manifest_routes = {
                    (item["method"], item["path"])
                    for item in operation_manifest.get("operations", [])
                }
                if (
                    len(extension_routes) != len(extensions)
                    or not extension_routes <= manifest_routes
                    or type(contract.get("operation_count")) is not int
                    or implementation_count
                    != contract["operation_count"] + len(extensions)
                ):
                    raise CapabilityContractError(
                        f"{capability_id}: official and Thor-local operation split differs"
                    )
            if (
                "tool_count" in contract
                and operation_manifest.get("tool_count") != contract["tool_count"]
            ):
                raise CapabilityContractError(
                    f"{capability_id}: expected MCP tool count differs"
                )
            if (
                "repository_tool_count" in contract
                and operation_manifest.get("tool_count")
                != contract["repository_tool_count"]
            ):
                raise CapabilityContractError(
                    f"{capability_id}: repository MCP tool count differs"
                )
        if not isinstance(capability.get("gap"), str) or not capability["gap"]:
            raise CapabilityContractError(f"{capability_id}: explicit gap is required")
        if capability["runtime_state"] == "passed_current":
            runtime_evidence = capability.get("runtime_evidence")
            if not isinstance(runtime_evidence, list) or not runtime_evidence:
                raise CapabilityContractError(
                    f"{capability_id}: passed_current requires capability-specific runtime_evidence"
                )
            for reference in runtime_evidence:
                if not isinstance(reference, dict):
                    raise CapabilityContractError(
                        f"{capability_id}: invalid runtime evidence reference"
                    )
                evidence_path = reference.get("path")
                expected_digest = reference.get("sha256")
                path = (
                    Path(evidence_path)
                    if isinstance(evidence_path, str)
                    else Path("..")
                )
                if (
                    not isinstance(evidence_path, str)
                    or path.is_absolute()
                    or ".." in path.parts
                    or not evidence_path.startswith("deploy/docker/thor-local/")
                ):
                    raise CapabilityContractError(
                        f"{capability_id}: unsafe runtime evidence path"
                    )
                try:
                    resolved_root = repo_root.resolve(strict=True)
                    full_path = resolved_root
                    for part in path.parts:
                        full_path /= part
                        if full_path.is_symlink():
                            raise CapabilityContractError(
                                f"{capability_id}: runtime evidence path contains a symlink"
                            )
                    resolved = full_path.resolve(strict=True)
                    resolved.relative_to(resolved_root)
                except CapabilityContractError:
                    raise
                except (OSError, ValueError) as exc:
                    raise CapabilityContractError(
                        f"{capability_id}: missing runtime evidence path"
                    ) from exc
                if not resolved.is_file():
                    raise CapabilityContractError(
                        f"{capability_id}: runtime evidence must be a regular non-symlink file"
                    )
                if (
                    not isinstance(expected_digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
                    or hashlib.sha256(resolved.read_bytes()).hexdigest()
                    != expected_digest
                ):
                    raise CapabilityContractError(
                        f"{capability_id}: runtime evidence digest differs"
                    )
                oracle = oracle_by_capability.get(capability_id)
                if oracle is None:
                    raise CapabilityContractError(
                        f"{capability_id}: passed_current has no capability oracle"
                    )
                evidence = _load(resolved)
                if set(reference) == {"path", "sha256"}:
                    _validate_bound_runtime_evidence(
                        capability,
                        oracle,
                        evidence,
                        ledger["target"],
                    )
                else:
                    _validate_aggregate_runtime_evidence(
                        evidence,
                        reference,
                        capability,
                        capability_by_id,
                        oracle_by_capability,
                        ledger["target"],
                        repo_root,
                    )
        by_feature.setdefault(feature_id, set()).add(capability_id)

    for source in sources:
        claims = []
        for capability in capabilities:
            for claim in capability["source_claims"]:
                if claim["source_id"] == source["id"]:
                    claims.append(
                        {
                            "capability_id": capability["id"],
                            "locator": claim["locator"],
                            "contract": capability["contract"],
                        }
                    )
        canonical = sorted(
            json.dumps(item, sort_keys=True, separators=(",", ":")) for item in claims
        )
        if not claims:
            raise CapabilityContractError(
                f"{source['id']}: official source has no precise capability claim"
            )
        digest = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":")).encode()
        ).hexdigest()
        if source["claim_set_sha256"] != digest:
            raise CapabilityContractError(f"{source['id']}: extracted claim set drift")

    manifest_linked: set[str] = set()
    for feature_id, expected in by_feature.items():
        feature = feature_by_id[feature_id]
        declared = feature.get("official_capability_ids")
        declared_ids = set(_ids(declared, f"{feature_id}.official_capability_ids"))
        if declared_ids != expected:
            raise CapabilityContractError(
                f"{feature_id}: official capability cross-link drift"
            )
        group = [item for item in capabilities if item["feature_id"] == feature_id]
        expected_status = _aggregate_family_status(group)
        expected_class = expected_status["acceptance_class"]
        if feature.get("acceptance_class") != expected_class:
            raise CapabilityContractError(
                f"{feature_id}: family acceptance_class does not aggregate capability classes"
            )
        expected_thor = expected_status["thor_state"]
        if feature.get("thor_state") != expected_thor:
            raise CapabilityContractError(
                f"{feature_id}: family thor_state does not aggregate capability states"
            )
        expected_runtime = expected_status["runtime_state"]
        if feature.get("runtime_state") != expected_runtime:
            raise CapabilityContractError(
                f"{feature_id}: family runtime_state does not aggregate capability states"
            )
        manifest_linked.update(declared_ids)
    if manifest_linked != set(capability_ids):
        raise CapabilityContractError(
            "not every official capability is linked from the manifest"
        )

    coverage = acceptance.get("coverage", {}).get("features")
    if not isinstance(coverage, list):
        raise CapabilityContractError("acceptance feature coverage must be a list")
    covered = {
        item.get("feature_id"): item for item in coverage if isinstance(item, dict)
    }
    for feature_id in by_feature:
        record = covered.get(feature_id)
        if record is None or not set(record.get("scenario_ids", [])) >= set().union(
            *(
                set(capability["scenario_ids"])
                for capability in capabilities
                if capability["feature_id"] == feature_id
            )
        ):
            raise CapabilityContractError(
                f"{feature_id}: acceptance cross-link is incomplete"
            )

    discrepancies = ledger.get("source_discrepancies")
    if not isinstance(discrepancies, list) or not discrepancies:
        raise CapabilityContractError(
            "at least one source discrepancy must remain explicit"
        )
    discrepancy_ids = _ids(
        [item.get("id") for item in discrepancies if isinstance(item, dict)],
        "source_discrepancies",
    )
    if len(discrepancy_ids) != len(discrepancies):
        raise CapabilityContractError("invalid source discrepancy record")
    for discrepancy in discrepancies:
        discrepancy_source_ids = discrepancy.get("source_ids", [])
        observations = discrepancy.get("observations", [])
        semantics = discrepancy.get("record_semantics")
        category = discrepancy.get("category")
        observation_sides = {
            (
                item.get("source_id"),
                item.get("locator"),
                item.get("claim"),
            )
            for item in observations
            if isinstance(item, dict)
        }
        invalid_semantics = (
            (semantics is None and len(observations) < 2)
            or (
                semantics == "single_source_record"
                and (len(observations) != 1 or len(discrepancy_source_ids) != 1)
            )
            or (semantics == "cross_source_discrepancy" and len(observations) < 2)
            or semantics
            not in {None, "single_source_record", "cross_source_discrepancy"}
            or (
                semantics is not None
                and category
                not in {"boundary", "discrepancy", "scoped_default", "known_limitation"}
            )
        )
        generic_values = {
            "official source boundary",
            "official documentation boundary",
            "source-backed observation",
            "reviewed official source claim",
        }
        fabricated_generic = any(
            value.strip().lower().rstrip(".") in generic_values
            for item in observation_sides
            for value in item[1:]
        )
        candidate_observations = discrepancy.get("candidate_observations")
        invalid_candidate_observations = candidate_observations is not None and (
            not isinstance(candidate_observations, list)
            or not candidate_observations
            or any(
                not isinstance(value, str) or not value
                for value in candidate_observations
            )
        )
        if (
            not discrepancy_source_ids
            or len(discrepancy_source_ids) != len(set(discrepancy_source_ids))
            or not set(discrepancy_source_ids) <= set(source_ids)
            or not isinstance(observations, list)
            or invalid_semantics
            or fabricated_generic
            or invalid_candidate_observations
            or len(observation_sides) != len(observations)
            or {item[0] for item in observation_sides} != set(discrepancy_source_ids)
            or any(
                not all(isinstance(value, str) and value for value in item)
                for item in observation_sides
            )
            or not discrepancy.get("resolution")
            or not discrepancy.get("must_not_claim")
        ):
            raise CapabilityContractError(f"{discrepancy['id']}: invalid discrepancy")

    return {
        "sources": len(sources),
        "capabilities": len(capabilities),
        "feature_families": len(by_feature),
        "discrepancies": len(discrepancies),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        counts = validate()
    except (OSError, json.JSONDecodeError, KeyError, CapabilityContractError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: reviewed VSS capability gap ledger is cross-linked and fail-closed")
    if args.report:
        print(", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
