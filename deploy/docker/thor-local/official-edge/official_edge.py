#!/usr/bin/env python3
"""Fail-closed verifier and command renderer for the Thor official-edge lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only on incomplete hosts
    raise SystemExit(
        "PyYAML is required to validate the official-edge contract"
    ) from exc


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
DEPLOY_DOCKER = REPO_ROOT / "deploy/docker"
DEFAULT_CONTRACT = HERE / "contract.json"
DEFAULT_ARTIFACT_LOCK = HERE / "artifacts.lock.json"
DEFAULT_RUNTIME_ENV = DEPLOY_DOCKER / "thor-local/generated.env"
OFFICIAL_ENV = HERE / "official-edge.env"
OFFICIAL_COMPOSE = HERE / "compose.yml"
OFFICIAL_AGENT_CONFIG = HERE / "config_edge.yml"
THOR_OPERATOR_GUIDANCE = (
    REPO_ROOT / "skills/vss-deploy-profile/references/thor-official-edge.md"
)
DEPLOY_PROFILE_SKILL = REPO_ROOT / "skills/vss-deploy-profile/SKILL.md"
EDITABLE_THOR_GUIDANCE = (
    REPO_ROOT / "skills/vss-deploy-profile/references/credentials.md",
    REPO_ROOT / "skills/vss-deploy-profile/references/lvs-profile.md",
    REPO_ROOT / "skills/vss-deploy-profile/references/troubleshooting.md",
    REPO_ROOT / "skills/vss-deploy-profile/scripts/check_credentials.sh",
)

EDGE_REPOSITORY = "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"
EDGE_MODEL_ID = EDGE_REPOSITORY
EDGE_REVISION = "3fe6dab75665a93884214ad4b1b95cf02717d081"
EDGE_CACHE_DIRECTORY = "models--nvidia--NVIDIA-Nemotron-3-Nano-4B-FP8"
EDGE_BASE_URL = "http://127.0.0.1:30081"
COSMOS_ARTIFACT = "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final"
COSMOS_MODEL_ID = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
COSMOS_BASE_URL = "http://127.0.0.1:8018"
COSMOS_CACHE_DIRECTORY = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
EDGE_IMAGE = (
    "ghcr.io/nvidia-ai-iot/vllm@"
    "sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8"
)
EDGE_IMAGE_MANIFEST_DIGEST = (
    "sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8"
)
EDGE_IMAGE_CONFIG_DIGEST = (
    "sha256:11544a7267571a837e2abc4a14be638257d7f402b0fc45d2223eec0f5f3e8c09"
)
RTVLM_IMAGE = (
    "nvcr.io/nvidia/vss-core/vss-rt-vlm@"
    "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
)
RTVLM_IMAGE_ID = (
    "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
)
RTVLM_SERVER_OVERLAY = (
    REPO_ROOT / "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py"
)
RTVLM_SERVER_OVERLAY_SHA256 = (
    "24f6f968cbfac481dd1d310f4fe278b9db2311ec16f3f613c0525e8b77834a0d"
)
RTVLM_SERVER_CONTAINER = "/opt/nvidia/rtvi/rtvi/server/rtvi_vlm_server.py"
RTVLM_STREAM_HANDLER_OVERLAY = (
    REPO_ROOT / "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py"
)
RTVLM_STREAM_HANDLER_OVERLAY_SHA256 = (
    "0a76e5e574d9466662d3424f45fc62ca26313577e87379e25fc4940d1c9bc52d"
)
RTVLM_STREAM_HANDLER_CONTAINER = (
    "/opt/nvidia/rtvi/rtvi/server/rtvi_stream_handler.py"
)
RTVLM_PIPELINE_OVERLAY = (
    REPO_ROOT / "services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py"
)
RTVLM_PIPELINE_OVERLAY_SHA256 = (
    "76e8f53931f600cc6c8f05cf7d1f752688f6ed1e574fecf911e8b8dfee84df44"
)
RTVLM_PIPELINE_CONTAINER = "/opt/nvidia/rtvi/rtvi/vlm_pipeline/vlm_pipeline.py"
RTVLM_PROCESS_BASE_OVERLAY = (
    REPO_ROOT / "services/rtvi/rt-vlm/src/vlm_pipeline/process_base.py"
)
RTVLM_PROCESS_BASE_OVERLAY_SHA256 = (
    "a56ecdb52ef125b1f0b33b57c8b55a9f4e547a6e53a26bfb6a9d68590b1dea91"
)
RTVLM_PROCESS_BASE_CONTAINER = "/opt/nvidia/rtvi/rtvi/vlm_pipeline/process_base.py"
RTVLM_REQUEST_CANCELLATION_OVERLAYS = {
    RTVLM_SERVER_CONTAINER: (
        RTVLM_SERVER_OVERLAY,
        RTVLM_SERVER_OVERLAY_SHA256,
    ),
    RTVLM_STREAM_HANDLER_CONTAINER: (
        RTVLM_STREAM_HANDLER_OVERLAY,
        RTVLM_STREAM_HANDLER_OVERLAY_SHA256,
    ),
    RTVLM_PIPELINE_CONTAINER: (
        RTVLM_PIPELINE_OVERLAY,
        RTVLM_PIPELINE_OVERLAY_SHA256,
    ),
    RTVLM_PROCESS_BASE_CONTAINER: (
        RTVLM_PROCESS_BASE_OVERLAY,
        RTVLM_PROCESS_BASE_OVERLAY_SHA256,
    ),
}
AGENT_CONFIG_CONTAINER = (
    "/vss-agent/deploy/docker/thor-local/official-edge/config_edge.yml"
)
EDGE_COMMAND = [
    "python3",
    "-m",
    "vllm.entrypoints.openai.api_server",
    "--model",
    "/models/edge4b",
    "--tokenizer",
    "/models/edge4b",
    "--served-model-name",
    EDGE_MODEL_ID,
    "--trust-remote-code",
    "--host",
    "127.0.0.1",
    "--port",
    "30081",
    "--gpu-memory-utilization",
    "0.25",
    "--enable-auto-tool-choice",
    "--tool-call-parser",
    "qwen3_coder",
]


class ContractError(RuntimeError):
    """A fail-closed contract violation."""


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate object key: {key!r}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"YAML root must be an object: {path}")
    return value


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            f"command failed to execute: {shlex.join(command)}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise ContractError(
            f"command returned {result.returncode}: {shlex.join(command)}: {detail}"
        )
    return result.stdout


def _expect(mapping: dict[str, Any], key: str, expected: Any, context: str) -> None:
    actual = mapping.get(key)
    if actual != expected:
        raise ContractError(f"{context}.{key} is {actual!r}; expected {expected!r}")


def _decimal(value: Any, context: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"{context} is not a decimal fraction: {value!r}") from exc
    if not Decimal("0") <= result <= Decimal("1"):
        raise ContractError(f"{context} must be within [0,1], found {result}")
    return result


def verify_contract_identity(contract: dict[str, Any]) -> None:
    _expect(contract, "schema_version", 1, "contract")
    _expect(contract, "contract_id", "vss-3.2.1-thor-official-edge", "contract")

    upstream = contract.get("reviewed_upstream")
    if not isinstance(upstream, dict):
        raise ContractError("contract.reviewed_upstream must be an object")
    _expect(
        upstream,
        "main_commit",
        "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
        "reviewed_upstream",
    )
    documentation = contract.get("versioned_documentation")
    discrepancy = contract.get("documentation_discrepancy")
    if not isinstance(documentation, dict) or not isinstance(discrepancy, dict):
        raise ContractError(
            "contract must record the versioned-docs/check-out-skill discrepancy"
        )
    _expect(
        documentation,
        "url",
        "https://docs.nvidia.com/vss/3.2.1/edge-deployment.html",
        "versioned_documentation",
    )
    _expect(documentation, "last_updated", "2026-07-16", "versioned_documentation")
    _expect(documentation, "verified_on", "2026-07-31", "versioned_documentation")
    _expect(documentation, "llm_repository", EDGE_REPOSITORY, "versioned_documentation")
    _expect(
        documentation,
        "documented_image_tag",
        "ghcr.io/nvidia-ai-iot/vllm:latest-jetson-thor",
        "versioned_documentation",
    )
    _expect(
        documentation,
        "registry_manifest_digest_verified_on_2026_07_31",
        EDGE_IMAGE_MANIFEST_DIGEST,
        "versioned_documentation",
    )
    _expect(
        discrepancy,
        "checkout_skill_model",
        "nvidia/NVIDIA-Nemotron-Edge-4B-v2.1-EA-020126_FP8",
        "documentation_discrepancy",
    )
    _expect(
        discrepancy,
        "checkout_skill_state",
        "older_fallback_unqualified",
        "documentation_discrepancy",
    )
    _expect(
        discrepancy, "official_lane_model", EDGE_REPOSITORY, "documentation_discrepancy"
    )
    _expect(discrepancy, "resolved", False, "documentation_discrepancy")
    _expect(
        upstream,
        "tag_commit",
        "7640d917047cf7b0fd3085eefb8282754b56bc94",
        "reviewed_upstream",
    )

    llm = contract.get("llm")
    vlm = contract.get("vlm")
    memory = contract.get("unified_memory")
    images = contract.get("images")
    alternate = contract.get("alternate_lane")
    for name, value in (
        ("llm", llm),
        ("vlm", vlm),
        ("unified_memory", memory),
        ("images", images),
        ("alternate_lane", alternate),
    ):
        if not isinstance(value, dict):
            raise ContractError(f"contract.{name} must be an object")

    _expect(llm, "repository", EDGE_REPOSITORY, "llm")
    _expect(llm, "revision", EDGE_REVISION, "llm")
    _expect(llm, "served_model_id", EDGE_MODEL_ID, "llm")
    _expect(llm, "adapter_mode", "remote", "llm")
    _expect(llm, "provider_type", "vllm", "llm")
    _expect(llm, "base_url", EDGE_BASE_URL, "llm")
    _expect(llm, "gpu_memory_utilization", "0.25", "llm")
    _expect(llm, "tool_call_parser", "qwen3_coder", "llm")
    _expect(llm, "agent_config", AGENT_CONFIG_CONTAINER, "llm")

    _expect(vlm, "artifact_id", COSMOS_ARTIFACT, "vlm")
    _expect(vlm, "served_model_id", COSMOS_MODEL_ID, "vlm")
    _expect(vlm, "selector", "cosmos-reason3", "vlm")
    _expect(vlm, "adapter_mode", "local_shared", "vlm")
    _expect(vlm, "provider_type", "rtvi", "vlm")
    _expect(vlm, "base_url", COSMOS_BASE_URL, "vlm")
    _expect(vlm, "gpu_memory_utilization", "0.35", "vlm")

    llm_fraction = _decimal(memory.get("llm_fraction"), "memory.llm_fraction")
    vlm_fraction = _decimal(memory.get("vlm_fraction"), "memory.vlm_fraction")
    reserve = _decimal(
        memory.get("minimum_reserve_fraction"), "memory.minimum_reserve_fraction"
    )
    required = _decimal(
        memory.get("minimum_available_fraction_before_launch"),
        "memory.minimum_available_fraction_before_launch",
    )
    if llm_fraction != Decimal("0.25") or vlm_fraction != Decimal("0.35"):
        raise ContractError("official Edge4B/Cosmos3 fractions must remain 0.25/0.35")
    if reserve != Decimal("0.20"):
        raise ContractError("official-edge unified-memory reserve must remain 0.20")
    if required != llm_fraction + vlm_fraction + reserve:
        raise ContractError("minimum available fraction must equal LLM + VLM + reserve")

    edge_image = images.get("edge4b_vllm")
    rtvlm_image = images.get("rt_vlm")
    if not isinstance(edge_image, dict) or not isinstance(rtvlm_image, dict):
        raise ContractError("both official-edge image locks are required")
    _expect(edge_image, "reference", EDGE_IMAGE, "images.edge4b_vllm")
    _expect(
        edge_image,
        "documented_tag",
        "ghcr.io/nvidia-ai-iot/vllm:latest-jetson-thor",
        "images.edge4b_vllm",
    )
    _expect(
        edge_image,
        "manifest_digest",
        EDGE_IMAGE_MANIFEST_DIGEST,
        "images.edge4b_vllm",
    )
    _expect(
        edge_image,
        "manifest_config_digest",
        EDGE_IMAGE_CONFIG_DIGEST,
        "images.edge4b_vllm",
    )
    edge_state = edge_image.get("state")
    edge_image_id = edge_image.get("image_id")
    if edge_state == "missing_exact_image_unqualified":
        if edge_image_id is not None:
            raise ContractError(
                "an unstaged Edge vLLM image cannot claim a local image ID"
            )
    elif edge_state == "locked_exact":
        if edge_image_id not in {
            EDGE_IMAGE_CONFIG_DIGEST,
            EDGE_IMAGE_MANIFEST_DIGEST,
        }:
            raise ContractError(
                "a locked Edge vLLM image ID must equal the exact manifest or "
                "manifest config digest"
            )
    else:
        raise ContractError(f"unsupported Edge vLLM image state: {edge_state!r}")
    _expect(rtvlm_image, "reference", RTVLM_IMAGE, "images.rt_vlm")
    _expect(rtvlm_image, "image_id", RTVLM_IMAGE_ID, "images.rt_vlm")
    _expect(rtvlm_image, "state", "locked_exact", "images.rt_vlm")
    _expect(alternate, "id", "qwen-openai-compat", "alternate_lane")
    _expect(alternate, "preserved", True, "alternate_lane")


def verify_source_anchors(contract: dict[str, Any]) -> None:
    anchors = contract.get("source_anchors")
    if not isinstance(anchors, list) or not anchors:
        raise ContractError("contract.source_anchors must be a non-empty list")
    seen: set[str] = set()
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            raise ContractError(f"source_anchors[{index}] must be an object")
        path_text = anchor.get("path")
        commit = anchor.get("commit")
        blob = anchor.get("git_blob")
        expected_sha = anchor.get("sha256")
        if not all(
            isinstance(item, str) and item
            for item in (path_text, commit, blob, expected_sha)
        ):
            raise ContractError(f"source_anchors[{index}] has incomplete identity")
        if path_text in seen:
            raise ContractError(f"duplicate source anchor: {path_text}")
        seen.add(path_text)
        object_name = f"{commit}:{path_text}"
        actual_blob = _run(["git", "rev-parse", object_name]).strip()
        if actual_blob != blob:
            raise ContractError(
                f"source anchor blob drift for {object_name}: {actual_blob} != {blob}"
            )
        content = subprocess.run(
            ["git", "show", object_name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=120,
        )
        if content.returncode != 0:
            raise ContractError(f"cannot read source anchor {object_name}")
        actual_sha = _sha256_bytes(content.stdout)
        if actual_sha != expected_sha:
            raise ContractError(
                f"source anchor content drift for {object_name}: {actual_sha} != {expected_sha}"
            )
        if anchor.get("worktree_must_match") is True:
            worktree_path = REPO_ROOT / path_text
            if _sha256_file(worktree_path) != expected_sha:
                raise ContractError(
                    f"required worktree source differs from anchor: {path_text}"
                )


def _parse_env(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read env file {path}: {exc}") from exc
    values: dict[str, str] = {}
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ContractError(f"invalid env line {path}:{number}")
        key, value = line.split("=", 1)
        if not key or not key.replace("_", "A").isalnum() or not key[0].isalpha():
            raise ContractError(f"invalid env key {path}:{number}: {key!r}")
        if key in values:
            raise ContractError(f"duplicate env key {key} in {path}")
        values[key] = value
    return values


def verify_env_contract() -> None:
    values = _parse_env(OFFICIAL_ENV)
    expected = {
        "LLM_MODE": "remote",
        "LLM_NAME": EDGE_MODEL_ID,
        "LLM_NAME_SLUG": "none",
        "LLM_BASE_URL": EDGE_BASE_URL,
        "LLM_MODEL_TYPE": "vllm",
        "LLM_PORT": "30081",
        "LVS_LLM_MODEL_NAME": EDGE_MODEL_ID,
        "LVS_LLM_MODEL_TYPE": "vllm",
        "EVAL_LLM_JUDGE_NAME": EDGE_MODEL_ID,
        "EVAL_LLM_JUDGE_BASE_URL": EDGE_BASE_URL,
        "VLM_MODE": "local_shared",
        "VLM_NAME": COSMOS_MODEL_ID,
        "VLM_NAME_SLUG": "none",
        "VLM_BASE_URL": COSMOS_BASE_URL,
        "VLM_MODEL_TYPE": "rtvi",
        "VLM_PORT": "8018",
        "RTVI_VLM_BASE_URL": COSMOS_BASE_URL,
        "RTVI_VLM_ENDPOINT": "",
        "RTVI_VLM_API_KEY": "",
        "RTVI_VLM_MODEL_TO_USE": "cosmos-reason3",
        "RTVI_VLM_MODEL_PATH": COSMOS_ARTIFACT,
        "RTVI_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": COSMOS_MODEL_ID,
        "RTVI_VLLM_GPU_MEMORY_UTILIZATION": "0.35",
        "RTVI_VLM_BATCH_SIZE": "1",
        "RTVI_VLM_NUM_VLM_PROCS": "1",
        "VSS_AGENT_CONFIG_FILE": AGENT_CONFIG_CONTAINER,
    }
    if values != expected:
        missing = sorted(set(expected) - set(values))
        extra = sorted(set(values) - set(expected))
        wrong = sorted(
            key
            for key in expected.keys() & values.keys()
            if expected[key] != values[key]
        )
        raise ContractError(
            f"official-edge.env drift (missing={missing}, extra={extra}, wrong={wrong})"
        )


def _command_contains(command: Any, required: list[str], context: str) -> None:
    if not isinstance(command, list) or not all(
        isinstance(item, str) for item in command
    ):
        raise ContractError(f"{context} command must be a string list")
    for token in required:
        if token not in command:
            raise ContractError(f"{context} command is missing {token!r}")


def verify_compose_contract() -> None:
    for destination, (source, expected_sha256) in (
        RTVLM_REQUEST_CANCELLATION_OVERLAYS.items()
    ):
        if _sha256_file(source) != expected_sha256:
            raise ContractError(
                "RT-VLM request-cancellation overlay source drifted: "
                f"{destination}"
            )
    compose = _load_yaml(OFFICIAL_COMPOSE)
    services = compose.get("services")
    if not isinstance(services, dict):
        raise ContractError("official-edge compose must define services")
    if set(services) != {
        "perception-2d-fusion",
        "nemotron-edge",
        "rtvi-vlm",
        "vss-agent",
        "lvs-server",
        "vss-va-mcp",
        "alert-bridge",
    }:
        raise ContractError("official-edge compose service set drifted")

    perception = services["perception-2d-fusion"]
    edge = services["nemotron-edge"]
    rtvlm = services["rtvi-vlm"]
    agent = services["vss-agent"]
    lvs = services["lvs-server"]
    va_mcp = services["vss-va-mcp"]
    alert_bridge = services["alert-bridge"]
    for name, value in (
        ("perception-2d-fusion", perception),
        ("nemotron-edge", edge),
        ("rtvi-vlm", rtvlm),
        ("vss-agent", agent),
        ("lvs-server", lvs),
        ("vss-va-mcp", va_mcp),
        ("alert-bridge", alert_bridge),
    ):
        if not isinstance(value, dict):
            raise ContractError(f"compose service {name} must be an object")

    if perception != {"restart": "unless-stopped"}:
        raise ContractError(
            "compose perception-2d-fusion override must only preserve reboot restart"
        )

    _expect(edge, "image", EDGE_IMAGE, "compose.nemotron-edge")
    _expect(edge, "network_mode", "host", "compose.nemotron-edge")
    _expect(edge, "runtime", "nvidia", "compose.nemotron-edge")
    _expect(edge, "read_only", True, "compose.nemotron-edge")
    _expect(edge, "command", EDGE_COMMAND, "compose.nemotron-edge")
    expected_edge_environment = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HOME": "/runtime/huggingface",
        "XDG_CACHE_HOME": "/runtime/cache",
        "XDG_CONFIG_HOME": "/runtime/config",
        "FLASHINFER_WORKSPACE_BASE": "/runtime/cache",
        "TRITON_CACHE_DIR": "/runtime/cache/triton",
        "TORCHINDUCTOR_CACHE_DIR": "/runtime/cache/torchinductor",
        "VLLM_CACHE_ROOT": "/runtime/cache/vllm",
        "CUDA_CACHE_PATH": "/runtime/cache/cuda",
        "NVIDIA_VISIBLE_DEVICES": "0",
        "NVIDIA_DRIVER_CAPABILITIES": "all",
    }
    if edge.get("environment") != expected_edge_environment:
        raise ContractError(
            "compose Edge vLLM environment differs from exact offline lane"
        )
    expected_edge_volumes = [
        "${THOR_OFFICIAL_EDGE4B_SNAPSHOT:?Set the exact verified Edge4B snapshot path}:/models/edge4b:ro",
        "${THOR_OFFICIAL_EDGE4B_BLOBS_DIR:?Set the exact verified Edge4B blobs path}:/blobs:ro",
    ]
    if edge.get("volumes") != expected_edge_volumes:
        raise ContractError(
            "compose Edge vLLM artifact mounts differ from exact contract"
        )

    _expect(rtvlm, "image", RTVLM_IMAGE, "compose.rtvi-vlm")
    rtvlm_env = rtvlm.get("environment")
    if not isinstance(rtvlm_env, dict):
        raise ContractError("compose.rtvi-vlm.environment must be an object")
    expected_rtvlm = {
        "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": COSMOS_MODEL_ID,
        "VIA_VLM_ENDPOINT": "",
        "VIA_VLM_API_KEY": "",
        "NGC_API_KEY": "",
        "NVIDIA_API_KEY": "",
        "HF_TOKEN": "",
        "OPENAI_API_KEY": "",
        "VLM_MODEL_TO_USE": "cosmos-reason3",
        "MODEL_PATH": COSMOS_ARTIFACT,
        "VLLM_GPU_MEMORY_UTILIZATION": "0.35",
        "VLM_BATCH_SIZE": "1",
        "NUM_VLM_PROCS": "1",
    }
    if rtvlm_env != expected_rtvlm:
        raise ContractError(
            "compose RT-VLM environment differs from exact Cosmos3 lane"
        )
    if lvs.get("environment") != {
        "NVIDIA_API_KEY": "",
        "OPENAI_API_KEY": "",
        "LVS_LLM_API_KEY": "",
        "LVS_LLM_MODEL_NAME": EDGE_MODEL_ID,
        "LVS_LLM_BASE_URL": f"{EDGE_BASE_URL}/v1",
        "LVS_LLM_MODEL_TYPE": "vllm",
        "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": COSMOS_MODEL_ID,
        "RTVI_VLM_URL": COSMOS_BASE_URL,
        "VIA_VLM_ENDPOINT": f"{COSMOS_BASE_URL}/v1/",
    }:
        raise ContractError("compose LVS credential environment differs")
    if va_mcp.get("environment") != {
        "NVIDIA_API_KEY": "",
        "OPENAI_API_KEY": "",
        "HF_TOKEN": "",
        "LLM_MODEL_TYPE": "vllm",
        "LLM_NAME": EDGE_MODEL_ID,
        "LLM_BASE_URL": EDGE_BASE_URL,
    }:
        raise ContractError("compose VA-MCP credential environment differs")
    if alert_bridge.get("environment") != {
        "NVIDIA_API_KEY": "",
        "OPENAI_API_KEY": "",
        "HF_TOKEN": "",
        "VLM_MODE": "local_shared",
        "VLM_NAME": COSMOS_MODEL_ID,
        "VLM_BASE_URL": COSMOS_BASE_URL,
        "RTVI_VLM_BASE_URL": COSMOS_BASE_URL,
    }:
        raise ContractError("compose Alert Bridge model environment differs")
    if rtvlm.get("volumes") != [
        "${THOR_OFFICIAL_COSMOS3_CACHE_ROOT:?Set the parent of the exact verified Cosmos3 NGC cache path}:/opt/nvidia/rtvi/.rtvi/ngc_model_cache",
        "${VSS_REPO_ROOT:?Set the VSS repository root}/services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py:/opt/nvidia/rtvi/rtvi/server/rtvi_vlm_server.py:ro",
        "${VSS_REPO_ROOT:?Set the VSS repository root}/services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py:/opt/nvidia/rtvi/rtvi/server/rtvi_stream_handler.py:ro",
        "${VSS_REPO_ROOT:?Set the VSS repository root}/services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py:/opt/nvidia/rtvi/rtvi/vlm_pipeline/vlm_pipeline.py:ro",
        "${VSS_REPO_ROOT:?Set the VSS repository root}/services/rtvi/rt-vlm/src/vlm_pipeline/process_base.py:/opt/nvidia/rtvi/rtvi/vlm_pipeline/process_base.py:ro",
    ]:
        raise ContractError(
            "compose RT-VLM cache-root or request-cancellation overlay mount differs from exact Cosmos3 lane"
        )

    agent_env = agent.get("environment")
    if not isinstance(agent_env, dict):
        raise ContractError("compose.vss-agent.environment must be an object")
    expected_agent = {
        "NVIDIA_API_KEY": "",
        "OPENAI_API_KEY": "",
        "HF_TOKEN": "",
        "RAG_API_KEY": "",
        "LLM_MODE": "remote",
        "LLM_MODEL_TYPE": "vllm",
        "LLM_NAME": EDGE_MODEL_ID,
        "LLM_BASE_URL": EDGE_BASE_URL,
        "VLM_MODE": "local_shared",
        "VLM_MODEL_TYPE": "rtvi",
        "VLM_NAME": COSMOS_MODEL_ID,
        "VLM_BASE_URL": COSMOS_BASE_URL,
        "VSS_AGENT_CONFIG_FILE": AGENT_CONFIG_CONTAINER,
    }
    if agent_env != expected_agent:
        raise ContractError(
            "compose Agent environment differs from exact edge contract"
        )
    _command_contains(agent.get("command"), [AGENT_CONFIG_CONTAINER], "vss-agent")


def verify_agent_prompt_overlay() -> None:
    source = _load_yaml(
        DEPLOY_DOCKER
        / "developer-profiles/dev-profile-base/vss-agent/configs/config_edge.yml"
    )
    overlay = _load_yaml(OFFICIAL_AGENT_CONFIG)
    _expect(
        overlay,
        "base",
        "../../developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml",
        "official-edge.config_edge",
    )
    source_workflow = source.get("workflow")
    overlay_workflow = overlay.get("workflow")
    if not isinstance(source_workflow, dict) or not isinstance(overlay_workflow, dict):
        raise ContractError("both Edge agent configs must contain workflow objects")
    if set(overlay_workflow) != {"plan_prompt", "response_format_prompt"}:
        raise ContractError(
            "official Edge prompt overlay may override only two prompt fields"
        )
    for field in ("plan_prompt", "response_format_prompt"):
        if overlay_workflow.get(field) != source_workflow.get(field):
            raise ContractError(
                f"official Edge prompt overlay drifted from source field {field}"
            )


def verify_operator_guidance(contract: dict[str, Any]) -> None:
    """Keep editable Thor instructions on the versioned-doc model contract.

    The older upstream references are intentional byte anchors, so this gate
    verifies the repository-local precedence route instead of rewriting them.
    """

    guidance = THOR_OPERATOR_GUIDANCE.read_text(encoding="utf-8")
    skill = DEPLOY_PROFILE_SKILL.read_text(encoding="utf-8")
    older = contract["documentation_discrepancy"]["checkout_skill_model"]
    current = contract["llm"]["served_model_id"]
    cosmos_artifact = contract["vlm"]["artifact_id"]
    cosmos_model = contract["vlm"]["served_model_id"]
    required_guidance = (
        current,
        cosmos_artifact,
        cosmos_model,
        older,
        "MUST NOT run its AGX/IGX Thor model command",
        "MUST NOT",
        "deploy/docker/thor-local/official-edge/contract.json",
        "deploy/docker/thor-local/official-edge/README.md",
    )
    missing = [token for token in required_guidance if token not in guidance]
    if missing:
        raise ContractError(
            f"Thor operator precedence guidance is incomplete: {missing}"
        )

    route = "references/thor-official-edge.md"
    if skill.count(route) < 3 or "Thor precedence gate" not in skill:
        raise ContractError(
            "deploy-profile skill does not mandate the Thor precedence route"
        )

    editable_text = {
        path: path.read_text(encoding="utf-8") for path in EDITABLE_THOR_GUIDANCE
    }
    stale = [
        str(path.relative_to(REPO_ROOT))
        for path, text in editable_text.items()
        if older in text
    ]
    if stale:
        raise ContractError(
            f"editable Thor guidance still selects the older model: {stale}"
        )

    for path in EDITABLE_THOR_GUIDANCE[:3]:
        if "thor-official-edge.md" not in editable_text[path]:
            raise ContractError(
                f"editable Thor guidance bypasses precedence route: {path.relative_to(REPO_ROOT)}"
            )
    credential_probe = editable_text[EDITABLE_THOR_GUIDANCE[3]]
    if current not in credential_probe:
        raise ContractError(
            "credential helper does not probe the current Thor model identity"
        )


def verify_static(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _load_json(contract_path)
    verify_contract_identity(contract)
    verify_source_anchors(contract)
    verify_env_contract()
    verify_compose_contract()
    verify_agent_prompt_overlay()
    verify_operator_guidance(contract)
    return contract


def _safe_relative(path_text: str) -> PurePosixPath:
    path = PurePosixPath(path_text)
    if not path_text or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ContractError(f"unsafe artifact-tree path: {path_text!r}")
    if str(path) != path_text:
        raise ContractError(f"non-canonical artifact-tree path: {path_text!r}")
    return path


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _actual_tree_entries(
    root: Path,
    allowed_root: Path,
    ignored_top_level: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise ContractError(f"artifact root must be a real directory: {root}")
    allowed = allowed_root.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if not _within(resolved_root, allowed):
        raise ContractError(f"artifact root escapes allowed root: {root}")

    ignored = ignored_top_level or set()
    if any(len(_safe_relative(name).parts) != 1 for name in ignored):
        raise ContractError("ignored artifact runtime paths must be top-level")

    entries: list[dict[str, Any]] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path == root:
            directory_names[:] = [
                name for name in directory_names if name not in ignored
            ]
            file_names = [name for name in file_names if name not in ignored]
        for name in sorted(directory_names):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                entries.append(_symlink_entry(path, relative, allowed))
            elif stat.S_ISDIR(mode):
                entries.append({"path": relative, "type": "directory"})
            else:
                raise ContractError(f"unsupported artifact entry type: {path}")
        directory_names[:] = [
            name for name in directory_names if not (current_path / name).is_symlink()
        ]
        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                entries.append(_symlink_entry(path, relative, allowed))
            elif stat.S_ISREG(mode):
                entries.append(
                    {
                        "path": relative,
                        "type": "file",
                        "size": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
            else:
                raise ContractError(f"unsupported artifact entry type: {path}")
    entries.sort(key=lambda item: item["path"])
    return entries


def _symlink_entry(path: Path, relative: str, allowed_root: Path) -> dict[str, Any]:
    target = os.readlink(path)
    if Path(target).is_absolute():
        raise ContractError(
            f"absolute artifact symlink is forbidden: {path} -> {target}"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"broken artifact symlink: {path}: {exc}") from exc
    if not _within(resolved, allowed_root):
        raise ContractError(
            f"artifact symlink escapes repository/cache: {path} -> {target}"
        )
    if not resolved.is_file():
        raise ContractError(f"artifact symlink must resolve to a file: {path}")
    return {
        "path": relative,
        "type": "symlink",
        "target": target,
        "resolved_size": resolved.stat().st_size,
        "resolved_sha256": _sha256_file(resolved),
    }


def _validate_expected_tree(tree: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        raise ContractError(f"{context}.tree must be a populated object")
    entries = tree.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContractError(f"{context}.tree.entries must be non-empty")
    if tree.get("entry_count") != len(entries):
        raise ContractError(f"{context}.tree.entry_count does not match entries")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError(f"{context}.tree.entries[{index}] must be an object")
        path_text = entry.get("path")
        if not isinstance(path_text, str):
            raise ContractError(f"{context}.tree.entries[{index}] has no path")
        _safe_relative(path_text)
        if path_text in seen:
            raise ContractError(f"{context}.tree has duplicate path {path_text}")
        seen.add(path_text)
        kind = entry.get("type")
        keys = set(entry)
        allowed_keys = {
            "directory": {"path", "type"},
            "file": {"path", "type", "size", "sha256"},
            "symlink": {
                "path",
                "type",
                "target",
                "resolved_size",
                "resolved_sha256",
            },
        }
        if kind not in allowed_keys or keys != allowed_keys[kind]:
            raise ContractError(
                f"{context}.tree entry schema is invalid for {path_text}"
            )
    if [item["path"] for item in entries] != sorted(item["path"] for item in entries):
        raise ContractError(f"{context}.tree entries must be sorted by path")
    return entries


def _verify_locked_artifact(
    entry: Any,
    *,
    root: Path,
    allowed_root: Path,
    expected_kind: str,
    expected_identity: dict[str, str],
    context: str,
    provenance_root: Path,
    allowed_runtime_state: dict[str, str] | None = None,
) -> None:
    if not isinstance(entry, dict):
        raise ContractError(f"{context} lock entry must be an object")
    if entry.get("state") != "locked_exact":
        raise ContractError(
            f"{context} is not locked_exact; current state={entry.get('state')!r}"
        )
    _expect(entry, "kind", expected_kind, context)
    identity = entry.get("identity")
    if not isinstance(identity, dict):
        raise ContractError(f"{context}.identity must be an object")
    for key, value in expected_identity.items():
        _expect(identity, key, value, f"{context}.identity")
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {
        "state",
        "identity",
        "evidence_path",
        "evidence_sha256",
        "reviewed_by",
    }:
        raise ContractError(f"{context}.provenance is absent or has invalid shape")
    _expect(
        provenance,
        "state",
        "independently_reviewed_upstream_provenance",
        f"{context}.provenance",
    )
    _expect(provenance, "identity", expected_identity, f"{context}.provenance")
    evidence_sha256 = provenance.get("evidence_sha256")
    if (
        not isinstance(evidence_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
        or evidence_sha256 == "0" * 64
    ):
        raise ContractError(f"{context}.provenance evidence SHA-256 is invalid")
    if (
        not isinstance(provenance.get("reviewed_by"), str)
        or not provenance["reviewed_by"].strip()
    ):
        raise ContractError(f"{context}.provenance reviewer is absent")
    evidence_path_text = provenance.get("evidence_path")
    if not isinstance(evidence_path_text, str):
        raise ContractError(f"{context}.provenance evidence path is absent")
    _safe_relative(evidence_path_text)
    if not evidence_path_text.startswith(
        "deploy/docker/thor-local/official-edge/provenance/"
    ):
        raise ContractError(f"{context}.provenance evidence path is outside trust root")
    source_path = provenance_root / evidence_path_text
    current = provenance_root
    for component in Path(evidence_path_text).parts:
        current /= component
        if current.is_symlink():
            raise ContractError(
                f"{context}.provenance evidence path contains a symlink"
            )
    try:
        resolved_source = source_path.resolve(strict=True)
        resolved_source.relative_to(provenance_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ContractError(
            f"{context}.provenance evidence cannot resolve inside repository"
        ) from exc
    if source_path.is_symlink() or not resolved_source.is_file():
        raise ContractError(f"{context}.provenance evidence must be a regular file")
    if _sha256_file(resolved_source) != evidence_sha256:
        raise ContractError(f"{context}.provenance evidence hash differs")
    evidence = _load_json(resolved_source)
    if set(evidence) != {
        "schema_version",
        "state",
        "identity",
        "reviewed_by",
        "sources",
        "upstream_sha256",
    }:
        raise ContractError(f"{context}.provenance evidence schema is invalid")
    _expect(evidence, "schema_version", 1, f"{context}.provenance evidence")
    _expect(
        evidence,
        "state",
        "independently_reviewed_upstream_provenance",
        f"{context}.provenance evidence",
    )
    _expect(evidence, "identity", expected_identity, f"{context}.provenance evidence")
    _expect(
        evidence,
        "reviewed_by",
        provenance["reviewed_by"],
        f"{context}.provenance evidence",
    )
    sources = evidence.get("sources")
    upstream_hashes = evidence.get("upstream_sha256")
    if (
        not isinstance(sources, list)
        or not sources
        or any(
            not isinstance(item, str) or not item.startswith("https://")
            for item in sources
        )
    ):
        raise ContractError(f"{context}.provenance evidence sources are invalid")
    if (
        not isinstance(upstream_hashes, list)
        or not upstream_hashes
        or any(
            not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
            for item in upstream_hashes
        )
    ):
        raise ContractError(f"{context}.provenance upstream SHA-256 list is invalid")
    if expected_kind == "huggingface_snapshot":
        revision = identity.get("revision")
        if not isinstance(revision, str) or len(revision) != 40:
            raise ContractError(f"{context} requires an immutable 40-hex revision")
        if any(character not in "0123456789abcdef" for character in revision):
            raise ContractError(f"{context} revision is not lowercase hexadecimal")
        if root.name != revision:
            raise ContractError(
                f"Edge4B snapshot directory {root.name!r} != locked revision {revision!r}"
            )
    expected_entries = _validate_expected_tree(entry.get("tree"), context)
    ignored_runtime_state: set[str] = set()
    for name, expected_type in (allowed_runtime_state or {}).items():
        relative = _safe_relative(name)
        if len(relative.parts) != 1 or expected_type not in {"file", "directory"}:
            raise ContractError(f"{context} runtime-state contract is invalid")
        path = root / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        actual_type = (
            "file"
            if stat.S_ISREG(mode)
            else "directory" if stat.S_ISDIR(mode) else "unsupported"
        )
        if actual_type != expected_type:
            raise ContractError(
                f"{context} runtime state {name} is {actual_type}, "
                f"expected {expected_type}"
            )
        ignored_runtime_state.add(name)
    actual_entries = _actual_tree_entries(
        root, allowed_root, ignored_top_level=ignored_runtime_state
    )
    if expected_kind == "huggingface_snapshot":
        repository = _verify_edge_snapshot_layout(root, actual_entries)
        expected_blob_entries = _validate_expected_tree(
            entry.get("blob_tree"), f"{context}.blob_tree"
        )
        actual_blob_entries = _actual_tree_entries(
            repository / "blobs", repository / "blobs"
        )
        if actual_blob_entries != expected_blob_entries:
            expected_blob_paths = {item["path"] for item in expected_blob_entries}
            actual_blob_paths = {item["path"] for item in actual_blob_entries}
            raise ContractError(
                f"{context} mounted blob tree differs from lock "
                f"(missing={sorted(expected_blob_paths - actual_blob_paths)}, "
                f"extra={sorted(actual_blob_paths - expected_blob_paths)})"
            )
    if actual_entries != expected_entries:
        expected_paths = {item["path"] for item in expected_entries}
        actual_paths = {item["path"] for item in actual_entries}
        raise ContractError(
            f"{context} tree differs from lock "
            f"(missing={sorted(expected_paths - actual_paths)}, "
            f"extra={sorted(actual_paths - expected_paths)})"
        )


def _edge_repository(edge_snapshot: Path) -> Path:
    if edge_snapshot.parent.name != "snapshots":
        raise ContractError("Edge4B snapshot must be inside a snapshots directory")
    repository = edge_snapshot.parent.parent
    if repository.name != EDGE_CACHE_DIRECTORY:
        raise ContractError(
            f"Edge4B Hugging Face cache directory is {repository.name!r}; "
            f"expected {EDGE_CACHE_DIRECTORY!r}"
        )
    blobs = repository / "blobs"
    if not blobs.is_dir() or blobs.is_symlink():
        raise ContractError(f"Edge4B Hugging Face blob store is unavailable: {blobs}")
    return repository


def _verify_edge_snapshot_layout(
    edge_snapshot: Path, entries: list[dict[str, Any]]
) -> Path:
    repository = _edge_repository(edge_snapshot)
    blobs = (repository / "blobs").resolve(strict=True)
    for entry in entries:
        if entry.get("type") != "symlink":
            continue
        target = entry.get("target")
        parts = PurePosixPath(str(target)).parts
        if (
            len(parts) != 4
            or parts[:3] != ("..", "..", "blobs")
            or len(parts[3]) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in parts[3])
        ):
            raise ContractError(
                f"Edge4B snapshot symlink is not a canonical HF blob target: "
                f"{entry.get('path')} -> {target}"
            )
        resolved = (edge_snapshot / str(entry["path"])).resolve(strict=True)
        if not _within(resolved, blobs):
            raise ContractError(
                f"Edge4B snapshot symlink does not resolve inside the mounted blob store: "
                f"{entry.get('path')}"
            )
    return repository


def verify_artifacts(
    lock_path: Path,
    edge_snapshot: Path,
    cosmos_cache: Path,
    *,
    provenance_root: Path | None = None,
) -> None:
    lock = _load_json(lock_path)
    _expect(lock, "schema_version", 1, "artifact_lock")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "edge4b",
        "cosmos3_nano_bf16",
    }:
        raise ContractError(
            "artifact lock must contain exactly Edge4B and Cosmos3 Nano BF16"
        )
    if lock.get("lock_state") != "complete_exact":
        states = {
            key: value.get("state") if isinstance(value, dict) else None
            for key, value in artifacts.items()
        }
        raise ContractError(f"artifact lock is intentionally incomplete: {states}")

    reviewed_root = REPO_ROOT if provenance_root is None else provenance_root

    edge_repository_root = _edge_repository(edge_snapshot)
    _verify_locked_artifact(
        artifacts["edge4b"],
        root=edge_snapshot,
        allowed_root=edge_repository_root,
        expected_kind="huggingface_snapshot",
        expected_identity={"repository": EDGE_REPOSITORY, "revision": EDGE_REVISION},
        context="artifacts.edge4b",
        provenance_root=reviewed_root,
    )
    _verify_locked_artifact(
        artifacts["cosmos3_nano_bf16"],
        root=cosmos_cache,
        allowed_root=cosmos_cache,
        expected_kind="ngc_model_cache",
        expected_identity={"artifact_id": COSMOS_ARTIFACT},
        context="artifacts.cosmos3_nano_bf16",
        provenance_root=reviewed_root,
        allowed_runtime_state={".lock": "file", ".vllm": "directory"},
    )


def verify_images(contract: dict[str, Any]) -> None:
    images = contract["images"]
    for key in ("edge4b_vllm", "rt_vlm"):
        expected = images[key]
        if expected.get("state") != "locked_exact":
            raise ContractError(
                f"image {key} is not locked_exact; current state={expected.get('state')!r}"
            )
        reference = expected["reference"]
        expected_image_id = expected.get("image_id")
        if not isinstance(expected_image_id, str) or not expected_image_id.startswith(
            "sha256:"
        ):
            raise ContractError(f"image {key} lacks a reviewed local image ID")
        output = _run(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}|{{json .RepoDigests}}",
                reference,
            ]
        ).strip()
        if "|" not in output:
            raise ContractError(
                f"unexpected docker image inspection output for {reference}"
            )
        image_id, digest_json = output.split("|", 1)
        try:
            repo_digests = json.loads(digest_json)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid RepoDigests JSON for {reference}") from exc
        if image_id != expected_image_id:
            raise ContractError(f"image ID mismatch for {reference}: {image_id}")
        if not isinstance(repo_digests, list) or reference not in repo_digests:
            raise ContractError(
                f"repository digest is not locally proven for {reference}"
            )


def _read_meminfo(path: Path) -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read memory information {path}: {exc}") from exc
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[0] in {"MemTotal:", "MemAvailable:"}:
            try:
                values[fields[0]] = int(fields[1])
            except ValueError as exc:
                raise ContractError(f"invalid memory value in {path}: {line}") from exc
    if values.keys() != {"MemTotal:", "MemAvailable:"}:
        raise ContractError(f"{path} lacks MemTotal or MemAvailable")
    if values["MemTotal:"] <= 0 or values["MemAvailable:"] < 0:
        raise ContractError(f"invalid memory totals in {path}")
    return values["MemTotal:"], values["MemAvailable:"]


def verify_memory(contract: dict[str, Any], meminfo_path: Path) -> None:
    total, available = _read_meminfo(meminfo_path)
    required = _decimal(
        contract["unified_memory"]["minimum_available_fraction_before_launch"],
        "memory.minimum_available_fraction_before_launch",
    )
    actual = Decimal(available) / Decimal(total)
    if actual < required:
        raise ContractError(
            "unified-memory admission failed: "
            f"MemAvailable/MemTotal={actual:.4f}, required>={required} "
            "(0.25 Edge4B + 0.35 Cosmos3 + 0.20 reserve)"
        )


def _compose_prefix(runtime_env: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(DEPLOY_DOCKER),
        "--env-file",
        str(runtime_env),
        "--env-file",
        str(OFFICIAL_ENV),
        "-f",
        str(DEPLOY_DOCKER / "compose.yml"),
        "-f",
        str(DEPLOY_DOCKER / "thor-local/compose.yml"),
        "-f",
        str(OFFICIAL_COMPOSE),
    ]


def _cosmos_cache_root(cosmos_cache: Path) -> Path:
    if cosmos_cache.name != COSMOS_CACHE_DIRECTORY:
        raise ContractError(
            f"Cosmos3 cache directory is {cosmos_cache.name!r}; "
            f"expected {COSMOS_CACHE_DIRECTORY!r}"
        )
    return cosmos_cache.parent


def _environment_list_to_map(value: Any, context: str) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            str(key): "" if item is None else str(item) for key, item in value.items()
        }
    if isinstance(value, list):
        result: dict[str, str] = {}
        for item in value:
            if not isinstance(item, str) or "=" not in item:
                raise ContractError(f"invalid environment item in {context}: {item!r}")
            key, content = item.split("=", 1)
            result[key] = content
        return result
    raise ContractError(f"{context} environment must be a list or object")


CREDENTIAL_ENV_KEYS = {
    "NGC_API_KEY",
    "NVIDIA_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "OPENAI_API_KEY",
    "VIA_VLM_API_KEY",
    "LVS_LLM_API_KEY",
    "RAG_API_KEY",
}


def _reject_credential_leaks(environment: dict[str, str], context: str) -> None:
    leaked = sorted(
        key for key in CREDENTIAL_ENV_KEYS if environment.get(key) not in {None, ""}
    )
    if leaked:
        raise ContractError(
            f"{context} exposes non-empty credential environment: {leaked}"
        )


def _reject_mount_overlays(
    mounts: Any,
    protected_destinations: set[str],
    context: str,
    *,
    allowed_overlaps: set[str] | None = None,
) -> None:
    if not isinstance(mounts, list):
        raise ContractError(f"{context} has no inspectable mounts")
    destinations: list[str] = []
    for mount in mounts:
        if not isinstance(mount, dict) or not isinstance(mount.get("target"), str):
            raise ContractError(f"{context} has an invalid mount record")
        destinations.append(mount["target"])
    if len(destinations) != len(set(destinations)):
        raise ContractError(f"{context} has duplicate mount destinations")
    allowed = protected_destinations | (allowed_overlaps or set())
    unexpected = sorted(
        destination
        for destination in destinations
        if destination not in allowed
        and any(
            destination.startswith(f"{root.rstrip('/')}/")
            or root.startswith(f"{destination.rstrip('/')}/")
            for root in protected_destinations
        )
    )
    if unexpected:
        raise ContractError(f"{context} has protected-path shadow mounts: {unexpected}")


def verify_resolved_compose(
    runtime_env: Path, edge_snapshot: Path, cosmos_cache: Path
) -> dict[str, Any]:
    if not runtime_env.is_file():
        raise ContractError(f"protected Thor runtime env is missing: {runtime_env}")
    process_env = os.environ.copy()
    process_env["VSS_REPO_ROOT"] = str(REPO_ROOT)
    process_env["THOR_OFFICIAL_EDGE4B_SNAPSHOT"] = str(edge_snapshot)
    process_env["THOR_OFFICIAL_EDGE4B_BLOBS_DIR"] = str(
        _edge_repository(edge_snapshot) / "blobs"
    )
    process_env["THOR_OFFICIAL_COSMOS3_CACHE_DIR"] = str(cosmos_cache)
    process_env["THOR_OFFICIAL_COSMOS3_CACHE_ROOT"] = str(
        _cosmos_cache_root(cosmos_cache)
    )
    for key in CREDENTIAL_ENV_KEYS:
        process_env[key] = ""
    output = _run(
        _compose_prefix(runtime_env) + ["config", "--format", "json"], env=process_env
    )
    try:
        resolved = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ContractError("docker compose config did not return JSON") from exc
    services = resolved.get("services")
    if not isinstance(services, dict):
        raise ContractError("resolved Compose has no services")
    for name in ("nemotron-edge", "rtvi-vlm", "vss-agent"):
        if name not in services:
            raise ContractError(f"resolved Compose omitted required service {name}")
    if services["nemotron-edge"].get("image") != EDGE_IMAGE:
        raise ContractError("resolved Edge4B image differs from digest lock")
    if services["rtvi-vlm"].get("image") != RTVLM_IMAGE:
        raise ContractError("resolved RT-VLM image differs from digest lock")
    _expect(
        services["nemotron-edge"], "command", EDGE_COMMAND, "resolved nemotron-edge"
    )
    rtvlm_env = _environment_list_to_map(
        services["rtvi-vlm"].get("environment"), "resolved rtvi-vlm"
    )
    edge_env = _environment_list_to_map(
        services["nemotron-edge"].get("environment"), "resolved nemotron-edge"
    )
    _reject_credential_leaks(edge_env, "resolved nemotron-edge")
    _reject_credential_leaks(rtvlm_env, "resolved rtvi-vlm")
    agent_env = _environment_list_to_map(
        services["vss-agent"].get("environment"), "resolved vss-agent"
    )
    expected_rtvlm = {
        "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": COSMOS_MODEL_ID,
        "VIA_VLM_ENDPOINT": "",
        "VIA_VLM_API_KEY": "",
        "NGC_API_KEY": "",
        "NVIDIA_API_KEY": "",
        "HF_TOKEN": "",
        "OPENAI_API_KEY": "",
        "VLM_MODEL_TO_USE": "cosmos-reason3",
        "MODEL_PATH": COSMOS_ARTIFACT,
        "VLLM_GPU_MEMORY_UTILIZATION": "0.35",
    }
    for key, expected in expected_rtvlm.items():
        if rtvlm_env.get(key) != expected:
            raise ContractError(f"resolved RT-VLM {key} differs from {expected!r}")
    expected_agent = {
        "LLM_MODE": "remote",
        "LLM_MODEL_TYPE": "vllm",
        "LLM_NAME": EDGE_MODEL_ID,
        "LLM_BASE_URL": EDGE_BASE_URL,
        "VLM_MODE": "local_shared",
        "VLM_MODEL_TYPE": "rtvi",
        "VLM_NAME": COSMOS_MODEL_ID,
        "VLM_BASE_URL": COSMOS_BASE_URL,
        "VSS_AGENT_CONFIG_FILE": AGENT_CONFIG_CONTAINER,
    }
    for key, expected in expected_agent.items():
        if agent_env.get(key) != expected:
            raise ContractError(f"resolved Agent {key} differs from {expected!r}")
    if agent_env.get("EVAL_LLM_JUDGE_NAME") != EDGE_MODEL_ID:
        raise ContractError("resolved Agent evaluator retained a non-Edge4B model ID")
    if agent_env.get("EVAL_LLM_JUDGE_BASE_URL") != EDGE_BASE_URL:
        raise ContractError("resolved Agent evaluator retained a non-Edge4B endpoint")
    lvs_env = _environment_list_to_map(
        services["lvs-server"].get("environment"), "resolved lvs-server"
    )
    if lvs_env.get("LVS_LLM_MODEL_NAME") != EDGE_MODEL_ID:
        raise ContractError("resolved LVS retained a non-Edge4B model ID")
    if lvs_env.get("LVS_LLM_BASE_URL") != f"{EDGE_BASE_URL}/v1":
        raise ContractError("resolved LVS retained a non-Edge4B endpoint")
    va_mcp_env = _environment_list_to_map(
        services["vss-va-mcp"].get("environment"), "resolved vss-va-mcp"
    )
    expected_va_mcp = {
        "LLM_MODEL_TYPE": "vllm",
        "LLM_NAME": EDGE_MODEL_ID,
        "LLM_BASE_URL": EDGE_BASE_URL,
    }
    for key, expected in expected_va_mcp.items():
        if va_mcp_env.get(key) != expected:
            raise ContractError(f"resolved VA-MCP {key} differs from {expected!r}")
    alert_env = _environment_list_to_map(
        services["alert-bridge"].get("environment"), "resolved alert-bridge"
    )
    expected_alert = {
        "VLM_MODE": "local_shared",
        "VLM_NAME": COSMOS_MODEL_ID,
        "VLM_BASE_URL": COSMOS_BASE_URL,
        "RTVI_VLM_BASE_URL": COSMOS_BASE_URL,
    }
    for key, expected in expected_alert.items():
        if alert_env.get(key) != expected:
            raise ContractError(
                f"resolved Alert Bridge {key} differs from {expected!r}"
            )
    edge_mounts = services["nemotron-edge"].get("volumes")
    rtvlm_mounts = services["rtvi-vlm"].get("volumes")
    rtvlm_ports = services["rtvi-vlm"].get("ports")
    expected_edge_source = str(edge_snapshot.resolve())
    expected_edge_blobs_source = str(
        (_edge_repository(edge_snapshot) / "blobs").resolve()
    )
    expected_cosmos_source = str(_cosmos_cache_root(cosmos_cache).resolve())
    if rtvlm_ports != [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 8000,
            "published": "8018",
            "protocol": "tcp",
        }
    ]:
        raise ContractError(
            "resolved RT-VLM port publication is not exact loopback-only 8018"
        )
    _reject_mount_overlays(
        edge_mounts, {"/models/edge4b", "/blobs"}, "resolved nemotron-edge"
    )
    _reject_mount_overlays(
        rtvlm_mounts,
        {"/opt/nvidia/rtvi/.rtvi/ngc_model_cache"}
        | set(RTVLM_REQUEST_CANCELLATION_OVERLAYS),
        "resolved rtvi-vlm",
    )
    if not isinstance(edge_mounts, list) or not any(
        isinstance(mount, dict)
        and mount.get("type") == "bind"
        and mount.get("source") == expected_edge_source
        and mount.get("target") == "/models/edge4b"
        and mount.get("read_only") is True
        for mount in edge_mounts
    ):
        raise ContractError("resolved Edge4B snapshot is not the exact read-only bind")
    if not any(
        isinstance(mount, dict)
        and mount.get("type") == "bind"
        and mount.get("source") == expected_edge_blobs_source
        and mount.get("target") == "/blobs"
        and mount.get("read_only") is True
        for mount in edge_mounts
    ):
        raise ContractError("resolved Edge4B blobs are not the exact read-only bind")
    if not isinstance(rtvlm_mounts, list) or not any(
        isinstance(mount, dict)
        and mount.get("type") == "bind"
        and mount.get("source") == expected_cosmos_source
        and mount.get("target") == "/opt/nvidia/rtvi/.rtvi/ngc_model_cache"
        and mount.get("read_only", False) is False
        for mount in rtvlm_mounts
    ):
        raise ContractError(
            "resolved Cosmos3 cache is not the exact dedicated writable bind"
        )
    for destination, (source, _expected_sha256) in (
        RTVLM_REQUEST_CANCELLATION_OVERLAYS.items()
    ):
        if not any(
            isinstance(mount, dict)
            and mount.get("type") == "bind"
            and mount.get("source") == str(source.resolve())
            and mount.get("target") == destination
            and mount.get("read_only") is True
            for mount in rtvlm_mounts
        ):
            raise ContractError(
                "resolved RT-VLM lacks exact read-only request-cancellation "
                f"overlay: {destination}"
            )
    for forbidden in ("qwen3-vl-8b-instruct", "qwen3-vl-8b-instruct-shared-gpu"):
        if forbidden in services:
            raise ContractError(
                f"official-edge resolution unexpectedly selected {forbidden}"
            )
    for service_name, service in services.items():
        environment = service.get("environment") if isinstance(service, dict) else None
        if environment is not None:
            values = _environment_list_to_map(environment, f"resolved {service_name}")
            if service_name in {
                "nemotron-edge",
                "rtvi-vlm",
                "vss-agent",
                "vss-va-mcp",
                "lvs-server",
                "vss-alert-bridge",
            }:
                _reject_credential_leaks(values, f"resolved {service_name}")
            if any(
                value in {"datasheet-chat", "datasheet-vision"}
                for value in values.values()
            ):
                raise ContractError(
                    f"resolved service {service_name} retained a Qwen-lane served model alias"
                )
    agent_mounts = services["vss-agent"].get("volumes")
    agent_deploy_target = "/vss-agent/deploy/docker"
    if isinstance(agent_mounts, list) and any(
        isinstance(mount, dict) and mount.get("target") == AGENT_CONFIG_CONTAINER
        for mount in agent_mounts
    ):
        raise ContractError("resolved vss-agent has a direct config shadow mount")
    _reject_mount_overlays(
        agent_mounts,
        {AGENT_CONFIG_CONTAINER},
        "resolved vss-agent",
        allowed_overlaps={agent_deploy_target},
    )
    expected_agent_source = str(DEPLOY_DOCKER.resolve(strict=True))
    if not any(
        isinstance(mount, dict)
        and mount.get("type") == "bind"
        and mount.get("source") == expected_agent_source
        and mount.get("target") == agent_deploy_target
        and mount.get("read_only") is True
        for mount in agent_mounts
    ):
        raise ContractError(
            "resolved vss-agent config does not come from the exact read-only deploy bind"
        )
    return resolved


def render_pull_free_command(
    runtime_env: Path, edge_snapshot: Path, cosmos_cache: Path
) -> str:
    return shlex.join(
        [
            "env",
            f"VSS_REPO_ROOT={REPO_ROOT}",
            f"THOR_OFFICIAL_EDGE4B_SNAPSHOT={edge_snapshot}",
            f"THOR_OFFICIAL_EDGE4B_BLOBS_DIR={_edge_repository(edge_snapshot) / 'blobs'}",
            f"THOR_OFFICIAL_COSMOS3_CACHE_DIR={cosmos_cache}",
            f"THOR_OFFICIAL_COSMOS3_CACHE_ROOT={_cosmos_cache_root(cosmos_cache)}",
            "NVIDIA_API_KEY=",
            "OPENAI_API_KEY=",
            "HF_TOKEN=",
            "HUGGING_FACE_HUB_TOKEN=",
            "NGC_API_KEY=",
            "VIA_VLM_API_KEY=",
            "LVS_LLM_API_KEY=",
            "RAG_API_KEY=",
        ]
        + _compose_prefix(runtime_env)
        + ["up", "-d", "--no-build", "--pull", "never"]
    )


def _docker_container(name: str) -> dict[str, Any]:
    output = _run(["docker", "inspect", name])
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ContractError(f"docker inspect returned invalid JSON for {name}") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ContractError(f"unexpected docker inspect shape for {name}")
    return value[0]


def _verify_running_container(
    name: str,
    expected_image: str,
    expected_image_id: str,
    required_command: list[str],
    expected_env: dict[str, str],
    expected_mounts: dict[str, Path] | None = None,
    writable_mount_destinations: set[str] | None = None,
    expected_port_bindings: dict[str, list[dict[str, str]]] | None = None,
) -> None:
    container = _docker_container(name)
    state = container.get("State")
    config = container.get("Config")
    if not isinstance(state, dict) or not isinstance(config, dict):
        raise ContractError(f"container {name} has incomplete inspection data")
    if state.get("Running") is not True:
        raise ContractError(f"container {name} is not running")
    if (
        config.get("Image") != expected_image
        or container.get("Image") != expected_image_id
    ):
        raise ContractError(f"container {name} image differs from exact lock")
    if name == "vss-nemotron-edge-4b":
        if config.get("Cmd") != required_command:
            raise ContractError(f"container {name} command differs from exact contract")
    elif required_command:
        _command_contains(config.get("Cmd"), required_command, f"container {name}")
    environment = _environment_list_to_map(config.get("Env"), f"container {name}")
    for key, expected in expected_env.items():
        if environment.get(key) != expected:
            raise ContractError(f"container {name} environment {key} differs")
    credential_keys = {
        "NGC_API_KEY",
        "NVIDIA_API_KEY",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "OPENAI_API_KEY",
        "VIA_VLM_API_KEY",
    }
    leaked = sorted(
        key for key in credential_keys if environment.get(key) not in {None, ""}
    )
    if leaked:
        raise ContractError(
            f"container {name} exposes non-empty credential environment: {leaked}"
        )
    if expected_port_bindings is not None:
        host_config = container.get("HostConfig")
        if not isinstance(host_config, dict):
            raise ContractError(f"container {name} has no inspectable host config")
        if host_config.get("PortBindings") != expected_port_bindings:
            raise ContractError(
                f"container {name} port publication differs from exact contract"
            )
    if expected_mounts:
        writable = writable_mount_destinations or set()
        if not writable.issubset(expected_mounts):
            raise ContractError(
                f"container {name} has an invalid writable-mount contract"
            )
        mounts = container.get("Mounts")
        if not isinstance(mounts, list):
            raise ContractError(f"container {name} has no inspectable mounts")
        destinations: list[str] = []
        for mount in mounts:
            if not isinstance(mount, dict) or not isinstance(
                mount.get("Destination"), str
            ):
                raise ContractError(f"container {name} has an invalid mount record")
            destinations.append(mount["Destination"])
        if len(destinations) != len(set(destinations)):
            raise ContractError(f"container {name} has duplicate mount destinations")
        protected = tuple(expected_mounts)
        unexpected_overlays = sorted(
            destination
            for destination in destinations
            if destination not in expected_mounts
            and any(
                destination.startswith(f"{root.rstrip('/')}/")
                or root.startswith(f"{destination.rstrip('/')}/")
                for root in protected
            )
        )
        if unexpected_overlays:
            raise ContractError(
                f"container {name} has mounts overlapping protected model paths: "
                f"{unexpected_overlays}"
            )
        for destination, source in expected_mounts.items():
            expected_source = str(source.resolve(strict=True))
            expected_rw = destination in writable
            if not any(
                isinstance(mount, dict)
                and mount.get("Type") == "bind"
                and mount.get("Source") == expected_source
                and mount.get("Destination") == destination
                and mount.get("RW") is expected_rw
                for mount in mounts
            ):
                mode = "writable" if expected_rw else "read-only"
                raise ContractError(
                    f"container {name} does not use exact {mode} bind "
                    f"{expected_source} -> {destination}"
                )


def _verify_running_environment(
    name: str, required_command: list[str], expected_env: dict[str, str]
) -> None:
    container = _docker_container(name)
    state = container.get("State")
    config = container.get("Config")
    if not isinstance(state, dict) or not isinstance(config, dict):
        raise ContractError(f"container {name} has incomplete inspection data")
    if state.get("Running") is not True:
        raise ContractError(f"container {name} is not running")
    if required_command:
        _command_contains(config.get("Cmd"), required_command, f"container {name}")
    environment = _environment_list_to_map(config.get("Env"), f"container {name}")
    for key, expected in expected_env.items():
        if environment.get(key) != expected:
            raise ContractError(f"container {name} environment {key} differs")
    credential_keys = {
        "NGC_API_KEY",
        "NVIDIA_API_KEY",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "OPENAI_API_KEY",
        "VIA_VLM_API_KEY",
    }
    leaked = sorted(
        key for key in credential_keys if environment.get(key) not in {None, ""}
    )
    if leaked:
        raise ContractError(
            f"container {name} exposes non-empty credential environment: {leaked}"
        )


def _get_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ContractError(f"GET {url} returned HTTP {response.status}")
            return json.loads(response.read())
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"GET {url} failed: {exc}") from exc


def _verify_model_endpoint(base_url: str, model_id: str, timeout: float) -> None:
    payload = _get_json(f"{base_url}/v1/models", timeout)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ContractError(f"{base_url}/v1/models returned an invalid model list")
    identifiers = {item.get("id") for item in payload["data"] if isinstance(item, dict)}
    if identifiers != {model_id}:
        raise ContractError(
            f"{base_url}/v1/models advertises {sorted(str(item) for item in identifiers)}; "
            f"expected only {model_id}"
        )


def verify_readiness(
    contract: dict[str, Any],
    timeout: float,
    edge_snapshot: Path,
    cosmos_cache: Path,
) -> None:
    edge_image_id = contract["images"]["edge4b_vllm"].get("image_id")
    if not isinstance(edge_image_id, str):
        raise ContractError("Edge4B image lacks a reviewed local image ID")
    _verify_running_container(
        "vss-nemotron-edge-4b",
        EDGE_IMAGE,
        edge_image_id,
        EDGE_COMMAND,
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "XDG_CONFIG_HOME": "/runtime/config",
            "FLASHINFER_WORKSPACE_BASE": "/runtime/cache",
            "TRITON_CACHE_DIR": "/runtime/cache/triton",
            "TORCHINDUCTOR_CACHE_DIR": "/runtime/cache/torchinductor",
            "VLLM_CACHE_ROOT": "/runtime/cache/vllm",
            "CUDA_CACHE_PATH": "/runtime/cache/cuda",
        },
        {
            "/models/edge4b": edge_snapshot,
            "/blobs": _edge_repository(edge_snapshot) / "blobs",
        },
    )
    _verify_running_container(
        "vss-rtvi-vlm",
        RTVLM_IMAGE,
        RTVLM_IMAGE_ID,
        [],
        {
            "VLM_MODEL_TO_USE": "cosmos-reason3",
            "MODEL_PATH": COSMOS_ARTIFACT,
            "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": COSMOS_MODEL_ID,
            "VLLM_GPU_MEMORY_UTILIZATION": "0.35",
            "NGC_API_KEY": "",
            "NVIDIA_API_KEY": "",
            "HF_TOKEN": "",
            "OPENAI_API_KEY": "",
        },
        {
            "/opt/nvidia/rtvi/.rtvi/ngc_model_cache": _cosmos_cache_root(cosmos_cache),
            **{
                destination: source
                for destination, (source, _expected_sha256) in (
                    RTVLM_REQUEST_CANCELLATION_OVERLAYS.items()
                )
            },
        },
        {"/opt/nvidia/rtvi/.rtvi/ngc_model_cache"},
        {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8018"}]},
    )
    _verify_running_environment(
        "vss-agent",
        [AGENT_CONFIG_CONTAINER],
        {
            "LLM_MODE": "remote",
            "LLM_MODEL_TYPE": "vllm",
            "LLM_NAME": EDGE_MODEL_ID,
            "LLM_BASE_URL": EDGE_BASE_URL,
            "VLM_MODE": "local_shared",
            "VLM_MODEL_TYPE": "rtvi",
            "VLM_NAME": COSMOS_MODEL_ID,
            "VLM_BASE_URL": COSMOS_BASE_URL,
            "VSS_AGENT_CONFIG_FILE": AGENT_CONFIG_CONTAINER,
            "EVAL_LLM_JUDGE_NAME": EDGE_MODEL_ID,
            "EVAL_LLM_JUDGE_BASE_URL": EDGE_BASE_URL,
        },
    )
    _verify_running_environment(
        "vss-lvs",
        [],
        {
            "LVS_LLM_MODEL_NAME": EDGE_MODEL_ID,
            "LVS_LLM_BASE_URL": f"{EDGE_BASE_URL}/v1",
            "LVS_LLM_MODEL_TYPE": "vllm",
            "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": COSMOS_MODEL_ID,
        },
    )
    _verify_running_environment(
        "vss-va-mcp",
        [],
        {
            "LLM_MODEL_TYPE": "vllm",
            "LLM_NAME": EDGE_MODEL_ID,
            "LLM_BASE_URL": EDGE_BASE_URL,
        },
    )
    _verify_running_environment(
        "vss-alert-bridge",
        [],
        {
            "VLM_NAME": COSMOS_MODEL_ID,
            "VLM_BASE_URL": COSMOS_BASE_URL,
            "VLM_MODE": "local_shared",
        },
    )
    _verify_model_endpoint(EDGE_BASE_URL, EDGE_MODEL_ID, timeout)
    _verify_model_endpoint(COSMOS_BASE_URL, COSMOS_MODEL_ID, timeout)
    _get_json(f"{COSMOS_BASE_URL}/v1/health/ready", timeout)
    _get_json("http://127.0.0.1:8100/health", timeout)


def _require_path(value: str | None, label: str) -> Path:
    if not value:
        raise ContractError(f"{label} is required")
    return Path(value).expanduser().absolute()


def _common_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    edge = _require_path(args.edge4b_snapshot, "--edge4b-snapshot")
    cosmos = _require_path(args.cosmos3_cache, "--cosmos3-cache")
    return edge, cosmos


def _audit(args: argparse.Namespace) -> int:
    failures: list[str] = []
    contract: dict[str, Any] | None = None
    try:
        contract = verify_static(args.contract)
        print("PASS static source/compose/prompt contract")
    except ContractError as exc:
        failures.append(f"static: {exc}")
        print(f"FAIL static: {exc}")
    edge: Path | None = None
    cosmos: Path | None = None
    try:
        edge, cosmos = _common_paths(args)
        verify_artifacts(args.artifact_lock, edge, cosmos)
        print("PASS exact Edge4B and Cosmos3 artifact trees")
    except ContractError as exc:
        failures.append(f"artifacts: {exc}")
        print(f"FAIL artifacts: {exc}")
    if contract is not None:
        try:
            verify_images(contract)
            print("PASS pinned local image identities")
        except ContractError as exc:
            failures.append(f"images: {exc}")
            print(f"FAIL images: {exc}")
        try:
            verify_memory(contract, args.meminfo)
            print("PASS 0.25 + 0.35 + 0.20 unified-memory admission")
        except ContractError as exc:
            failures.append(f"memory: {exc}")
            print(f"FAIL memory: {exc}")
    if (
        contract is not None
        and edge is not None
        and cosmos is not None
        and not failures
    ):
        try:
            verify_resolved_compose(args.runtime_env, edge, cosmos)
            print("PASS resolved pull-free Compose contract")
        except ContractError as exc:
            failures.append(f"compose: {exc}")
            print(f"FAIL compose: {exc}")
    if failures:
        print(f"BLOCKED official-edge launch: {len(failures)} gate(s) failed")
        return 1
    print(
        "READY official-edge artifacts and admission are qualified for pull-free launch"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--artifact-lock", type=Path, default=DEFAULT_ARTIFACT_LOCK)
    parser.add_argument("--runtime-env", type=Path, default=DEFAULT_RUNTIME_ENV)
    parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument(
        "--edge4b-snapshot", default=os.environ.get("THOR_OFFICIAL_EDGE4B_SNAPSHOT")
    )
    parser.add_argument(
        "--cosmos3-cache", default=os.environ.get("THOR_OFFICIAL_COSMOS3_CACHE_DIR")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("static", help="verify source anchors and inert lane files")
    subparsers.add_parser(
        "audit", help="run every pre-launch gate; expected to fail until staged"
    )
    subparsers.add_parser(
        "render-command",
        help="print a pull-free launch command only after every gate passes",
    )
    ready = subparsers.add_parser(
        "readiness", help="verify an already-running official lane"
    )
    ready.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "static":
            verify_static(args.contract)
            print("PASS official-edge static contract")
            return 0
        if args.command == "audit":
            return _audit(args)

        edge, cosmos = _common_paths(args)
        contract = verify_static(args.contract)
        verify_artifacts(args.artifact_lock, edge, cosmos)
        verify_images(contract)
        if args.command == "render-command":
            verify_memory(contract, args.meminfo)
            verify_resolved_compose(args.runtime_env, edge, cosmos)
            print(render_pull_free_command(args.runtime_env, edge, cosmos))
            return 0
        if args.command == "readiness":
            verify_resolved_compose(args.runtime_env, edge, cosmos)
            verify_readiness(contract, args.timeout, edge, cosmos)
            print("PASS official-edge runtime identity/readiness contract")
            return 0
        raise ContractError(f"unsupported command: {args.command}")
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
