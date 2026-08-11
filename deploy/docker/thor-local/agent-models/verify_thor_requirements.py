#!/usr/bin/env python3
"""Cross-validate the two VSS 3.2.1 model denominators for Thor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
DEFAULT_REQUIREMENTS = HERE / "thor-requirements.json"
RELEASE_COMMIT = "7640d917047cf7b0fd3085eefb8282754b56bc94"
MAIN_COMMIT = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
EDGE_REPOSITORY = "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"
EDGE_REVISION = "3fe6dab75665a93884214ad4b1b95cf02717d081"
EDGE_IMAGE_REFERENCE = (
    "ghcr.io/nvidia-ai-iot/vllm@sha256:"
    "b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8"
)
EDGE_IMAGE_ID = (
    "sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8"
)
VLM_AGENT_SELECTOR = "nvidia/cosmos3-nano-reasoner"
VLM_ARTIFACT = "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final"
VLM_SERVED_ID = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
VLM_SELECTOR = "cosmos-reason3"
RT_VLM_IMAGE_REFERENCE = (
    "nvcr.io/nvidia/vss-core/vss-rt-vlm@sha256:"
    "5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
)
RT_VLM_IMAGE_ID = (
    "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
)
EXPECTED_LLM_SELECTORS = [
    "nvidia/nvidia-nemotron-nano-9b-v2",
    "nvidia/NVIDIA-Nemotron-Nano-9B-v2-FP8",
    "nvidia/nemotron-3-nano",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "openai/gpt-oss-20b",
]
EXPECTED_VLM_SELECTORS = [
    VLM_AGENT_SELECTOR,
    "nvidia/cosmos-reason2-8b",
    "Qwen/Qwen3-VL-8B-Instruct",
]
EXPECTED_SOURCE_LOCKS = {
    "deploy/docker/thor-local/agent-models/official-vss-3.2.1.json": (
        "d6d44086a1a5a26fe0c02f8a6623e48282c66d50019c7ab8aa31c97d44c8ed71"
    ),
    "deploy/docker/thor-local/agent-models/thor-state.json": (
        "7ab2323ac155fdcfa551a664d6c854fe046871bf43e38979fa8010850bb8cf33"
    ),
    "deploy/docker/thor-local/official-edge/contract.json": (
        "ff7fbfd3296ff1d5af6cf688b58a0611dbcc811cc64ebe1d9272f13a0f29c63e"
    ),
    "deploy/docker/thor-local/official-edge/artifacts.lock.json": (
        "d5427164ccbd33529ddc2678c969601b09bb67776df332e230910702281766ae"
    ),
    "deploy/docker/thor-local/qualification/official-edge-readiness/staging-plan.json": (
        "e4c834c551d8b206fc7212de5905e937a8de54c0c53688d7efafe3d3d95efe33"
    ),
}
RUNTIME_COLLECTOR_DIR = (
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/official-edge-semantic-runtime-evidence-successor"
)
APPROVED_RUNTIME_COLLECTOR_LOCKS = {
    "contract.json": "6707db98f4a524a04cd9e86badaec1b0ad474d2fb79a11bfb08a303e03e236b0",
    "contract.schema.json": (
        "207aab65cb37cd18fa56a98539222604d8f32287d3beceb82201a6bc70b10dc9"
    ),
    "executor.py": "653546a1d3943c09f24b0c6e5e2fad6506696867e9bd10a531d6e9374075825c",
    "manifest.schema.json": "a80b0c799b61a159c8799c6eb3eaa27c9eb24586aa7a3d070bce3a316c2c217a",
    "receipt.schema.json": "6bfada0a7636dd3a9902d3f9b5827db35d9b2d514fa71762f543614a7052af34",
}
APPROVAL_AUTHORITY_RELATIVE_PATH = (
    "deploy/docker/thor-local/agent-models/approved-runtime-receipt.json"
)
APPROVAL_AUTHORITY_PATH = REPO_ROOT / APPROVAL_AUTHORITY_RELATIVE_PATH
APPROVAL_AUTHORITY_SHA256 = (
    "c2bbedd094a3c4e43fcce796519881018e65c2e6c505150b967f2773e02c8fd4"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
EXPECTED_RUNTIME_EVIDENCE_CONTRACT: dict[str, Any] = {
    "state": "collector_contract_ready_no_live_receipt",
    "accepted_evidence_contract": {
        "package_id": "thor-official-edge-semantic-runtime-evidence-successor-v1",
        "collector_id": "thor-official-edge-semantic-collector-v1",
        "receipt_schema_version": 1,
        "required_status": "passed_candidate_non_promoting",
    },
    "readiness_only_is_sufficient": False,
}


class DuplicateKeyError(ValueError):
    """Raised when JSON repeats an object member."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top level must be an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expect(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _safe_source_path(path_text: Any) -> Path:
    if (
        not isinstance(path_text, str)
        or not path_text.startswith("deploy/docker/thor-local/")
        or Path(path_text).is_absolute()
        or ".." in Path(path_text).parts
        or Path(path_text).as_posix() != path_text
    ):
        raise ValueError(f"unsafe source-lock path: {path_text!r}")
    root = REPO_ROOT.resolve(strict=True)
    path = REPO_ROOT
    for part in Path(path_text).parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"source-lock path contains a symlink: {path_text}")
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file():
        raise ValueError(f"source-lock path is not a regular file: {path_text}")
    return resolved


def _locked_inputs(
    requirements: dict[str, Any], errors: list[str]
) -> dict[str, dict[str, Any]]:
    rows = requirements.get("source_locks")
    if not isinstance(rows, list):
        errors.append("source_locks must be a list")
        return {}
    actual = {
        row.get("path"): row.get("sha256") for row in rows if isinstance(row, dict)
    }
    _expect(
        errors,
        len(rows) == len(actual) == len(EXPECTED_SOURCE_LOCKS),
        "source_locks must contain exactly one row per required input",
    )
    _expect(
        errors,
        actual == EXPECTED_SOURCE_LOCKS,
        "source-lock inventory or digest changed",
    )
    loaded: dict[str, dict[str, Any]] = {}
    for path_text, expected_digest in EXPECTED_SOURCE_LOCKS.items():
        try:
            path = _safe_source_path(path_text)
        except (OSError, ValueError) as error:
            errors.append(str(error))
            continue
        _expect(
            errors,
            sha256(path) == expected_digest,
            f"source-lock digest differs: {path_text}",
        )
        try:
            loaded[path_text] = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"cannot load source-locked JSON {path_text}: {error}")
    return loaded


def _selector_blockers(state: dict[str, Any]) -> list[str]:
    exact_ids = set(EXPECTED_LLM_SELECTORS + EXPECTED_VLM_SELECTORS)
    rows = {
        row.get("model_id"): row
        for row in state.get("official_model_state", [])
        if isinstance(row, dict) and row.get("kind") in {"llm", "vlm"}
    }
    blockers: list[str] = []
    for model_id in EXPECTED_LLM_SELECTORS + EXPECTED_VLM_SELECTORS:
        row = rows.get(model_id, {})
        if row.get("exact_artifact_state") != "staged-and-locked":
            blockers.append(
                f"{model_id}: exact Agent artifact is not staged and locked"
            )
        if row.get("agent_backend_state") != "staged-and-locked":
            blockers.append(f"{model_id}: Agent backend is not staged and locked")
        if row.get("runtime_qualification") != "qualified":
            blockers.append(f"{model_id}: runtime qualification is absent")
    if set(rows) != exact_ids:
        blockers.append("Agent selector state does not cover the exact denominator")
    return blockers


def _runtime_receipt_approval(errors: list[str]) -> dict[str, str] | None:
    """Load the verifier-pinned, source-reviewed receipt approval authority."""

    try:
        if sha256(APPROVAL_AUTHORITY_PATH) != APPROVAL_AUTHORITY_SHA256:
            errors.append("runtime receipt approval authority digest differs")
            return None
        authority = load_json(APPROVAL_AUTHORITY_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"runtime receipt approval authority is invalid: {error}")
        return None
    if (
        set(authority)
        != {
            "schema_version",
            "authority_id",
            "state",
            "package_id",
            "collector_id",
            "required_status",
            "approvals",
        }
        or authority.get("schema_version") != 1
        or authority.get("authority_id")
        != "thor-official-edge-runtime-receipt-approval-v1"
        or authority.get("package_id")
        != "thor-official-edge-semantic-runtime-evidence-successor-v1"
        or authority.get("collector_id") != "thor-official-edge-semantic-collector-v1"
        or authority.get("required_status") != "passed_candidate_non_promoting"
    ):
        errors.append("runtime receipt approval authority contract differs")
        return None
    approvals = authority.get("approvals")
    if authority.get("state") == "none_approved" and approvals == []:
        return None
    if (
        authority.get("state") != "one_source_reviewed"
        or not isinstance(approvals, list)
        or len(approvals) != 1
    ):
        errors.append("runtime receipt approval authority state is invalid")
        return None
    approval = approvals[0]
    if (
        not isinstance(approval, dict)
        or set(approval) != {"path", "sha256"}
        or not isinstance(approval.get("sha256"), str)
        or SHA256_PATTERN.fullmatch(approval["sha256"]) is None
    ):
        errors.append("source-reviewed runtime receipt approval is malformed")
        return None
    try:
        approved_path = _safe_source_path(approval.get("path"))
    except (OSError, ValueError) as error:
        errors.append(str(error))
        return None
    if sha256(approved_path) != approval["sha256"]:
        errors.append("source-reviewed runtime receipt digest differs")
        return None
    return {"path": str(approved_path), "sha256": approval["sha256"]}


def _validate_runtime_receipt(
    receipt_path: Path | None,
    receipt_sha256: str | None,
    approval: dict[str, str] | None,
    errors: list[str],
) -> bool:
    """Admit only a digest-bound receipt through the exact approved collector."""

    if receipt_path is None and receipt_sha256 is None:
        return False
    if receipt_path is None or receipt_sha256 is None:
        errors.append("runtime receipt path and SHA-256 must be supplied together")
        return False
    if not receipt_path.is_absolute():
        errors.append("runtime receipt path must be absolute")
        return False
    if (
        not isinstance(receipt_sha256, str)
        or SHA256_PATTERN.fullmatch(receipt_sha256) is None
    ):
        errors.append("runtime receipt SHA-256 is invalid")
        return False
    if approval is None:
        errors.append("runtime receipt is not source-approved")
        return False
    try:
        resolved_receipt = receipt_path.resolve(strict=True)
    except OSError:
        errors.append("source-approved runtime receipt is unavailable")
        return False
    if (
        str(resolved_receipt) != approval["path"]
        or receipt_sha256 != approval["sha256"]
    ):
        errors.append("runtime receipt does not match the source-reviewed approval")
        return False
    for filename, expected in APPROVED_RUNTIME_COLLECTOR_LOCKS.items():
        path = RUNTIME_COLLECTOR_DIR / filename
        try:
            actual = sha256(path)
        except OSError as error:
            errors.append(f"approved runtime collector is unavailable: {error}")
            return False
        if actual != expected:
            errors.append(f"approved runtime collector lock differs: {filename}")
            return False
    executor_path = RUNTIME_COLLECTOR_DIR / "executor.py"
    spec = importlib.util.spec_from_file_location(
        "thor_approved_semantic_receipt_validator", executor_path
    )
    if spec is None or spec.loader is None:
        errors.append("approved runtime receipt validator cannot be loaded")
        return False
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        receipt = module.validate_receipt_file(receipt_path, receipt_sha256)
    except Exception:
        errors.append("runtime receipt failed cryptographic collector validation")
        return False
    accepted = EXPECTED_RUNTIME_EVIDENCE_CONTRACT["accepted_evidence_contract"]
    if (
        receipt.get("package_id") != accepted["package_id"]
        or receipt.get("collector_id") != accepted["collector_id"]
        or receipt.get("schema_version") != accepted["receipt_schema_version"]
        or receipt.get("status") != accepted["required_status"]
        or receipt.get("canonical_effect")
        != {"admitted": False, "promoted": False, "binding_changed": False}
    ):
        errors.append("runtime receipt identity or non-promoting boundary differs")
        return False
    return True


def validate_requirements(
    requirements_path: Path = DEFAULT_REQUIREMENTS,
    *,
    runtime_receipt_path: Path | None = None,
    runtime_receipt_sha256: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return contract errors, canonical-pair blockers, and selector blockers."""

    errors: list[str] = []
    canonical_blockers: list[str] = []
    try:
        requirements = load_json(requirements_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [str(error)], [], []

    _expect(errors, requirements.get("schema_version") == 1, "schema_version must be 1")
    _expect(
        errors,
        requirements.get("requirements_id") == "vss-3.2.1-thor-model-denominators",
        "requirements_id changed",
    )
    _expect(
        errors,
        requirements.get("reviewed_release")
        == {
            "version": "3.2.1",
            "tag_commit": RELEASE_COMMIT,
            "main_commit": MAIN_COMMIT,
        },
        "reviewed release identity changed",
    )
    inputs = _locked_inputs(requirements, errors)
    if set(inputs) != set(EXPECTED_SOURCE_LOCKS):
        return errors, canonical_blockers, []

    agent = inputs["deploy/docker/thor-local/agent-models/official-vss-3.2.1.json"]
    state = inputs["deploy/docker/thor-local/agent-models/thor-state.json"]
    edge = inputs["deploy/docker/thor-local/official-edge/contract.json"]
    artifact_lock = inputs["deploy/docker/thor-local/official-edge/artifacts.lock.json"]
    readiness = inputs[
        "deploy/docker/thor-local/qualification/official-edge-readiness/staging-plan.json"
    ]
    denominators = requirements.get("denominators")
    if not isinstance(denominators, dict):
        errors.append("denominators must be an object")
        return errors, canonical_blockers, []
    _expect(
        errors,
        set(denominators)
        == {
            "canonical_official_edge_pair",
            "all_advertised_agent_selectors",
        },
        "denominator inventory changed",
    )
    canonical = denominators.get("canonical_official_edge_pair", {})
    selectors = denominators.get("all_advertised_agent_selectors", {})
    if not isinstance(canonical, dict) or not isinstance(selectors, dict):
        errors.append("both denominators must be objects")
        return errors, canonical_blockers, []

    _expect(
        errors,
        canonical.get("required_for_thor_feature_parity") is True,
        "canonical official-edge pair must remain required for Thor feature parity",
    )
    _expect(
        errors,
        selectors.get("required_for_thor_feature_parity") is False,
        "all-selector compatibility must remain distinct from Thor feature parity",
    )
    _expect(
        errors,
        selectors.get("llm_model_ids") == EXPECTED_LLM_SELECTORS,
        "all-selector LLM denominator changed",
    )
    _expect(
        errors,
        selectors.get("vlm_model_ids") == EXPECTED_VLM_SELECTORS,
        "all-selector VLM denominator changed",
    )
    _expect(
        errors,
        selectors.get("required_gates_per_model")
        == ["exact_agent_artifact", "exact_agent_backend", "runtime_qualification"],
        "all-selector gate dimensions changed",
    )

    manifest_llms = [
        row.get("model_id")
        for row in agent.get("llm", {}).get("local_models", [])
        if isinstance(row, dict)
    ]
    manifest_vlms = [
        row.get("model_id")
        for row in agent.get("vlm", {}).get("explicit_local_models", [])
        if isinstance(row, dict)
    ]
    _expect(
        errors,
        manifest_llms == EXPECTED_LLM_SELECTORS,
        "Agent LLM selector source drifted",
    )
    _expect(
        errors,
        manifest_vlms == EXPECTED_VLM_SELECTORS,
        "Agent VLM selector source drifted",
    )
    boundary = agent.get("thor_platform_boundary", {})
    _expect(
        errors,
        boundary.get("official_3_2_1_configuration") == "remote-LLM"
        and boundary.get("fully_local_all_agent_workflows_supported") is False,
        "Agent selector oracle's official Thor support boundary drifted",
    )

    llm = canonical.get("llm", {})
    vlm = canonical.get("vlm", {})
    expected_llm = {
        "repository": EDGE_REPOSITORY,
        "revision": EDGE_REVISION,
        "served_model_id": EDGE_REPOSITORY,
        "adapter_mode": "remote",
        "base_url": "http://127.0.0.1:30081",
        "artifact_lock_key": "edge4b",
        "backend_image_key": "edge4b_vllm",
        "backend_image_reference": EDGE_IMAGE_REFERENCE,
        "backend_image_id": EDGE_IMAGE_ID,
    }
    expected_vlm = {
        "agent_selector_model_id": VLM_AGENT_SELECTOR,
        "artifact_id": VLM_ARTIFACT,
        "served_model_id": VLM_SERVED_ID,
        "selector": VLM_SELECTOR,
        "adapter_mode": "local_shared",
        "base_url": "http://127.0.0.1:8018",
        "artifact_lock_key": "cosmos3_nano_bf16",
        "backend_image_key": "rt_vlm",
        "backend_image_reference": RT_VLM_IMAGE_REFERENCE,
        "backend_image_id": RT_VLM_IMAGE_ID,
    }
    _expect(errors, llm == expected_llm, "canonical Thor LLM denominator changed")
    _expect(errors, vlm == expected_vlm, "canonical Thor VLM denominator changed")
    _expect(
        errors,
        canonical.get("mapping_policy")
        == {
            "llm_relation_to_agent_selector_inventory": (
                "separate_later_versioned_thor_edge_identity"
            ),
            "vlm_relation_to_agent_selector_inventory": (
                "agent_selector_maps_to_exact_rt_vlm_artifact_and_served_identity"
            ),
            "all_selector_qualification_cannot_satisfy_this_denominator": True,
        },
        "canonical/all-selector mapping policy changed",
    )
    _expect(
        errors,
        EDGE_REPOSITORY not in EXPECTED_LLM_SELECTORS,
        "canonical Thor LLM must not be conflated with the general selector inventory",
    )

    _expect(
        errors,
        edge.get("contract_id") == "vss-3.2.1-thor-official-edge",
        "official-edge contract id drifted",
    )
    _expect(
        errors,
        edge.get("reviewed_upstream", {}).get("tag_commit") == RELEASE_COMMIT
        and edge.get("reviewed_upstream", {}).get("main_commit") == MAIN_COMMIT,
        "official-edge upstream anchors drifted",
    )
    _expect(
        errors,
        all(
            edge.get("llm", {}).get(key) == value
            for key, value in {
                "repository": EDGE_REPOSITORY,
                "revision": EDGE_REVISION,
                "served_model_id": EDGE_REPOSITORY,
                "adapter_mode": "remote",
                "base_url": "http://127.0.0.1:30081",
            }.items()
        ),
        "official-edge LLM identity differs from canonical denominator",
    )
    _expect(
        errors,
        all(
            edge.get("vlm", {}).get(key) == value
            for key, value in {
                "artifact_id": VLM_ARTIFACT,
                "served_model_id": VLM_SERVED_ID,
                "selector": VLM_SELECTOR,
                "adapter_mode": "local_shared",
                "base_url": "http://127.0.0.1:8018",
            }.items()
        ),
        "official-edge VLM identity differs from canonical denominator",
    )

    artifacts = artifact_lock.get("artifacts", {})
    edge_artifact = artifacts.get("edge4b", {}) if isinstance(artifacts, dict) else {}
    cosmos_artifact = (
        artifacts.get("cosmos3_nano_bf16", {}) if isinstance(artifacts, dict) else {}
    )
    _expect(
        errors,
        edge_artifact.get("identity")
        == {"repository": EDGE_REPOSITORY, "revision": EDGE_REVISION},
        "Edge LLM artifact-lock identity differs",
    )
    _expect(
        errors,
        cosmos_artifact.get("identity") == {"artifact_id": VLM_ARTIFACT},
        "Cosmos3 artifact-lock identity differs",
    )
    if artifact_lock.get("lock_state") != "complete_exact":
        canonical_blockers.append(
            "canonical.artifact_lock: official-edge artifact lock is not complete_exact"
        )
    for key, entry in (
        ("edge4b", edge_artifact),
        ("cosmos3_nano_bf16", cosmos_artifact),
    ):
        if entry.get("state") != "locked_exact" or not isinstance(
            entry.get("tree"), dict
        ):
            canonical_blockers.append(
                f"canonical.artifact.{key}: exact artifact tree is not staged and locked"
            )

    expected_images = {
        "edge4b_vllm": (EDGE_IMAGE_REFERENCE, EDGE_IMAGE_ID),
        "rt_vlm": (RT_VLM_IMAGE_REFERENCE, RT_VLM_IMAGE_ID),
    }
    edge_images = edge.get("images", {})
    for key, (reference, image_id) in expected_images.items():
        entry = edge_images.get(key, {}) if isinstance(edge_images, dict) else {}
        _expect(
            errors,
            entry.get("reference") == reference,
            f"official-edge {key} image reference differs",
        )
        if (
            entry.get("state") != "locked_exact"
            or entry.get("reference") != reference
            or entry.get("image_id") != image_id
        ):
            canonical_blockers.append(
                f"canonical.backend.{key}: exact backend image is not staged and locked"
            )

    _expect(
        errors,
        readiness.get("plan_id") == "vss-3.2.1-thor-official-edge-readiness",
        "official-edge readiness plan id drifted",
    )
    readiness_identities = readiness.get("identities", {})
    _expect(
        errors,
        readiness_identities.get("llm", {}).get("repository") == EDGE_REPOSITORY
        and readiness_identities.get("llm", {}).get("served_model_id")
        == EDGE_REPOSITORY,
        "readiness LLM identity differs from canonical denominator",
    )
    _expect(
        errors,
        readiness_identities.get("vlm", {}).get("artifact_id") == VLM_ARTIFACT
        and readiness_identities.get("vlm", {}).get("served_model_id") == VLM_SERVED_ID
        and readiness_identities.get("vlm", {}).get("selector") == VLM_SELECTOR,
        "readiness VLM identity differs from canonical denominator",
    )
    readiness_images = readiness.get("images", {})
    for plan_key, (_, reference, image_id) in {
        "edge_vllm": ("edge4b_vllm", EDGE_IMAGE_REFERENCE, EDGE_IMAGE_ID),
        "rt_vlm": ("rt_vlm", RT_VLM_IMAGE_REFERENCE, RT_VLM_IMAGE_ID),
    }.items():
        entry = (
            readiness_images.get(plan_key, {})
            if isinstance(readiness_images, dict)
            else {}
        )
        _expect(
            errors,
            entry.get("exact_reference") == reference
            and entry.get("required_image_id") == image_id,
            f"readiness {plan_key} image identity differs",
        )
    readiness_locks = {
        row.get("path"): row.get("sha256")
        for row in readiness.get("source_locks", [])
        if isinstance(row, dict)
    }
    for path_text in (
        "deploy/docker/thor-local/official-edge/contract.json",
        "deploy/docker/thor-local/official-edge/artifacts.lock.json",
    ):
        _expect(
            errors,
            readiness_locks.get(path_text) == EXPECTED_SOURCE_LOCKS[path_text],
            f"readiness source lock differs: {path_text}",
        )

    runtime = canonical.get("runtime_evidence", {})
    _expect(
        errors,
        runtime == EXPECTED_RUNTIME_EVIDENCE_CONTRACT,
        "canonical runtime-evidence boundary changed without a reviewed collector",
    )
    receipt_approval = _runtime_receipt_approval(errors)
    if not _validate_runtime_receipt(
        runtime_receipt_path, runtime_receipt_sha256, receipt_approval, errors
    ):
        canonical_blockers.append(
            "canonical.runtime_evidence: approved semantic runtime receipt is absent"
        )

    selector_blockers = _selector_blockers(state)
    _expect(
        errors,
        selectors.get("current_expected_blocker_count") == len(selector_blockers) == 24,
        "all-selector current blocker count differs",
    )
    current = requirements.get("current_state", {})
    _expect(
        errors,
        current
        == {
            "canonical_official_edge_pair": "incomplete_fail_closed",
            "all_advertised_agent_selectors": "not_runtime_qualified",
            "runtime_evidence_promoted": False,
            "warehouse_sample_required": False,
        },
        "declared current state changed",
    )
    _expect(
        errors,
        bool(canonical_blockers),
        "canonical pair unexpectedly has no blocker while current state is incomplete",
    )
    return errors, canonical_blockers, selector_blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("static",), default="static")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-thor-complete", action="store_true")
    parser.add_argument("--runtime-receipt", type=Path)
    parser.add_argument("--runtime-receipt-sha256")
    args = parser.parse_args(argv)
    errors, canonical_blockers, selector_blockers = validate_requirements(
        args.requirements,
        runtime_receipt_path=args.runtime_receipt,
        runtime_receipt_sha256=args.runtime_receipt_sha256,
    )
    result = {
        "schema_version": 1,
        "requirements_id": "vss-3.2.1-thor-model-denominators",
        "static_contract_valid": not errors,
        "canonical_official_edge_pair": {
            "complete": not errors and not canonical_blockers,
            "blockers": canonical_blockers,
        },
        "all_advertised_agent_selectors": {
            "complete": not errors and not selector_blockers,
            "blocker_count": len(selector_blockers),
        },
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    elif errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
    else:
        print("PASS Thor model denominator static coherence")
        print(f"INFO canonical official-edge blockers: {len(canonical_blockers)}")
        print(f"INFO all-advertised-selector blockers: {len(selector_blockers)}")
    if errors:
        return 1
    if args.require_thor_complete and canonical_blockers:
        if args.json:
            return 2
        for blocker in canonical_blockers:
            print(f"BLOCKED {blocker}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
