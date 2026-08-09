#!/usr/bin/env python3
"""Verify and render the exact-model Thor demo memory lane."""

from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any

import official_edge as oe

HERE = Path(__file__).resolve().parent
DEMO_COMPOSE = HERE / "compose.thor-demo-memory.yml"
LLM_FRACTION = Decimal("0.12")
VLM_FRACTION = Decimal("0.35")
RESERVE_FRACTION = Decimal("0.23")
REQUIRED_AVAILABLE_FRACTION = Decimal("0.70")
DEMO_EDGE_COMMAND = [
    "python3",
    "-m",
    "vllm.entrypoints.openai.api_server",
    "--model",
    "/models/edge4b",
    "--tokenizer",
    "/models/edge4b",
    "--served-model-name",
    oe.EDGE_MODEL_ID,
    "--trust-remote-code",
    "--host",
    "127.0.0.1",
    "--port",
    "30081",
    "--gpu-memory-utilization",
    str(LLM_FRACTION),
    "--enable-auto-tool-choice",
    "--tool-call-parser",
    "qwen3_coder",
]


def verify_overlay_contract() -> None:
    overlay = oe._load_yaml(DEMO_COMPOSE)
    if set(overlay) != {"services"}:
        raise oe.ContractError("Thor demo overlay may define only services")
    services = overlay.get("services")
    if not isinstance(services, dict) or set(services) != {"nemotron-edge"}:
        raise oe.ContractError("Thor demo overlay service set drifted")
    edge = services["nemotron-edge"]
    if not isinstance(edge, dict) or set(edge) != {"command"}:
        raise oe.ContractError("Thor demo Edge override may change only command")
    if edge.get("command") != DEMO_EDGE_COMMAND:
        raise oe.ContractError("Thor demo Edge command differs from exact 0.12 lane")
    if REQUIRED_AVAILABLE_FRACTION != (LLM_FRACTION + VLM_FRACTION + RESERVE_FRACTION):
        raise oe.ContractError("Thor demo memory admission arithmetic drifted")


def verify_static(contract_path: Path = oe.DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = oe.verify_static(contract_path)
    verify_overlay_contract()
    return contract


def verify_memory(meminfo_path: Path) -> None:
    total, available = oe._read_meminfo(meminfo_path)
    actual = Decimal(available) / Decimal(total)
    if actual < REQUIRED_AVAILABLE_FRACTION:
        raise oe.ContractError(
            "Thor demo unified-memory admission failed: "
            f"MemAvailable/MemTotal={actual:.4f}, "
            f"required>={REQUIRED_AVAILABLE_FRACTION} "
            "(0.12 Edge4B + 0.35 Cosmos3 + 0.23 reserve)"
        )


def _compose_prefix(runtime_env: Path) -> list[str]:
    return oe._compose_prefix(runtime_env) + ["-f", str(DEMO_COMPOSE)]


def _compose_environment(edge_snapshot: Path, cosmos_cache: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["VSS_REPO_ROOT"] = str(oe.REPO_ROOT)
    environment["THOR_OFFICIAL_EDGE4B_SNAPSHOT"] = str(edge_snapshot)
    environment["THOR_OFFICIAL_EDGE4B_BLOBS_DIR"] = str(
        oe._edge_repository(edge_snapshot) / "blobs"
    )
    environment["THOR_OFFICIAL_COSMOS3_CACHE_DIR"] = str(cosmos_cache)
    environment["THOR_OFFICIAL_COSMOS3_CACHE_ROOT"] = str(
        oe._cosmos_cache_root(cosmos_cache)
    )
    for key in oe.CREDENTIAL_ENV_KEYS:
        environment[key] = ""
    return environment


def verify_resolved_compose(
    runtime_env: Path, edge_snapshot: Path, cosmos_cache: Path
) -> dict[str, Any]:
    """Prove the demo graph differs from the official graph in one value only."""

    official = oe.verify_resolved_compose(runtime_env, edge_snapshot, cosmos_cache)
    output = oe._run(
        _compose_prefix(runtime_env) + ["config", "--format", "json"],
        env=_compose_environment(edge_snapshot, cosmos_cache),
    )
    try:
        demo = json.loads(output)
    except json.JSONDecodeError as exc:
        raise oe.ContractError("Thor demo Compose config did not return JSON") from exc
    services = demo.get("services")
    official_services = official.get("services")
    if not isinstance(services, dict) or not isinstance(official_services, dict):
        raise oe.ContractError("Thor demo Compose graph has no services")
    edge = services.get("nemotron-edge")
    rtvlm = services.get("rtvi-vlm")
    if not isinstance(edge, dict) or not isinstance(rtvlm, dict):
        raise oe.ContractError("Thor demo Compose omitted a model service")
    if edge.get("command") != DEMO_EDGE_COMMAND:
        raise oe.ContractError("resolved Thor demo Edge command is not exact")
    rtvlm_environment = oe._environment_list_to_map(
        rtvlm.get("environment"), "resolved Thor demo rtvi-vlm"
    )
    if rtvlm_environment.get("VLLM_GPU_MEMORY_UTILIZATION") != str(VLM_FRACTION):
        raise oe.ContractError("resolved Thor demo RT-VLM utilization is not exact")
    oe._reject_credential_leaks(
        oe._environment_list_to_map(
            edge.get("environment"), "resolved Thor demo nemotron-edge"
        ),
        "resolved Thor demo nemotron-edge",
    )
    oe._reject_credential_leaks(rtvlm_environment, "resolved Thor demo rtvi-vlm")

    normalized = deepcopy(demo)
    normalized_services = normalized["services"]
    normalized_services["nemotron-edge"]["command"] = official_services[
        "nemotron-edge"
    ]["command"]
    if normalized != official:
        raise oe.ContractError("Thor demo resolved graph differs outside Edge memory")
    return demo


def render_pull_free_command(
    runtime_env: Path, edge_snapshot: Path, cosmos_cache: Path
) -> str:
    return shlex.join(
        [
            "env",
            f"VSS_REPO_ROOT={oe.REPO_ROOT}",
            f"THOR_OFFICIAL_EDGE4B_SNAPSHOT={edge_snapshot}",
            f"THOR_OFFICIAL_EDGE4B_BLOBS_DIR={oe._edge_repository(edge_snapshot) / 'blobs'}",
            f"THOR_OFFICIAL_COSMOS3_CACHE_DIR={cosmos_cache}",
            f"THOR_OFFICIAL_COSMOS3_CACHE_ROOT={oe._cosmos_cache_root(cosmos_cache)}",
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


def verify_readiness(
    contract: dict[str, Any],
    timeout: float,
    edge_snapshot: Path,
    cosmos_cache: Path,
) -> None:
    edge_image_id = contract["images"]["edge4b_vllm"].get("image_id")
    if not isinstance(edge_image_id, str):
        raise oe.ContractError("Edge4B image lacks a reviewed local image ID")
    oe._verify_running_container(
        "vss-nemotron-edge-4b",
        oe.EDGE_IMAGE,
        edge_image_id,
        DEMO_EDGE_COMMAND,
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
            "/blobs": oe._edge_repository(edge_snapshot) / "blobs",
        },
    )
    oe._verify_running_container(
        "vss-rtvi-vlm",
        oe.RTVLM_IMAGE,
        oe.RTVLM_IMAGE_ID,
        [],
        {
            "VLM_MODEL_TO_USE": "cosmos-reason3",
            "MODEL_PATH": oe.COSMOS_ARTIFACT,
            "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": oe.COSMOS_MODEL_ID,
            "VLLM_GPU_MEMORY_UTILIZATION": str(VLM_FRACTION),
            "NGC_API_KEY": "",
            "NVIDIA_API_KEY": "",
            "HF_TOKEN": "",
            "OPENAI_API_KEY": "",
        },
        {"/opt/nvidia/rtvi/.rtvi/ngc_model_cache": oe._cosmos_cache_root(cosmos_cache)},
        {"/opt/nvidia/rtvi/.rtvi/ngc_model_cache"},
    )
    oe._verify_running_environment(
        "vss-agent",
        [oe.AGENT_CONFIG_CONTAINER],
        {
            "LLM_MODE": "remote",
            "LLM_MODEL_TYPE": "vllm",
            "LLM_NAME": oe.EDGE_MODEL_ID,
            "LLM_BASE_URL": oe.EDGE_BASE_URL,
            "VLM_MODE": "local_shared",
            "VLM_MODEL_TYPE": "rtvi",
            "VLM_NAME": oe.COSMOS_MODEL_ID,
            "VLM_BASE_URL": oe.COSMOS_BASE_URL,
            "VSS_AGENT_CONFIG_FILE": oe.AGENT_CONFIG_CONTAINER,
            "EVAL_LLM_JUDGE_NAME": oe.EDGE_MODEL_ID,
            "EVAL_LLM_JUDGE_BASE_URL": oe.EDGE_BASE_URL,
        },
    )
    oe._verify_running_environment(
        "vss-lvs",
        [],
        {
            "LVS_LLM_MODEL_NAME": oe.EDGE_MODEL_ID,
            "LVS_LLM_BASE_URL": f"{oe.EDGE_BASE_URL}/v1",
            "LVS_LLM_MODEL_TYPE": "vllm",
            "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": oe.COSMOS_MODEL_ID,
        },
    )
    oe._verify_running_environment(
        "vss-va-mcp",
        [],
        {
            "LLM_MODEL_TYPE": "vllm",
            "LLM_NAME": oe.EDGE_MODEL_ID,
            "LLM_BASE_URL": oe.EDGE_BASE_URL,
        },
    )
    oe._verify_running_environment(
        "vss-alert-bridge",
        [],
        {
            "VLM_NAME": oe.COSMOS_MODEL_ID,
            "VLM_BASE_URL": oe.COSMOS_BASE_URL,
            "VLM_MODE": "local_shared",
        },
    )
    oe._verify_model_endpoint(oe.EDGE_BASE_URL, oe.EDGE_MODEL_ID, timeout)
    oe._verify_model_endpoint(oe.COSMOS_BASE_URL, oe.COSMOS_MODEL_ID, timeout)
    oe._get_json(f"{oe.COSMOS_BASE_URL}/v1/health/ready", timeout)
    oe._get_json("http://127.0.0.1:8100/health", timeout)


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    return (
        oe._require_path(args.edge4b_snapshot, "--edge4b-snapshot"),
        oe._require_path(args.cosmos3_cache, "--cosmos3-cache"),
    )


def _prerequisites(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    edge, cosmos = _paths(args)
    contract = verify_static(args.contract)
    oe.verify_artifacts(args.artifact_lock, edge, cosmos)
    oe.verify_images(contract)
    return contract, edge, cosmos


def _audit(args: argparse.Namespace) -> int:
    failures: list[str] = []
    contract: dict[str, Any] | None = None
    edge: Path | None = None
    cosmos: Path | None = None
    try:
        contract = verify_static(args.contract)
        print("PASS official source contract and exact Thor demo overlay")
    except oe.ContractError as exc:
        failures.append(f"static: {exc}")
        print(f"FAIL static: {exc}")
    try:
        edge, cosmos = _paths(args)
        oe.verify_artifacts(args.artifact_lock, edge, cosmos)
        print("PASS exact Edge4B and Cosmos3 artifact trees")
    except oe.ContractError as exc:
        failures.append(f"artifacts: {exc}")
        print(f"FAIL artifacts: {exc}")
    if contract is not None:
        try:
            oe.verify_images(contract)
            print("PASS pinned local image identities")
        except oe.ContractError as exc:
            failures.append(f"images: {exc}")
            print(f"FAIL images: {exc}")
        try:
            verify_memory(args.meminfo)
            print("PASS 0.12 + 0.35 + 0.23 Thor demo memory admission")
        except oe.ContractError as exc:
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
            print("PASS exact-model Thor demo Compose delta")
        except oe.ContractError as exc:
            failures.append(f"compose: {exc}")
            print(f"FAIL compose: {exc}")
    if failures:
        print(f"BLOCKED Thor demo launch: {len(failures)} gate(s) failed")
        return 1
    print("READY exact-model Thor demo lane for pull-free launch")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=oe.DEFAULT_CONTRACT)
    parser.add_argument("--artifact-lock", type=Path, default=oe.DEFAULT_ARTIFACT_LOCK)
    parser.add_argument("--runtime-env", type=Path, default=oe.DEFAULT_RUNTIME_ENV)
    parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument(
        "--edge4b-snapshot", default=os.environ.get("THOR_OFFICIAL_EDGE4B_SNAPSHOT")
    )
    parser.add_argument(
        "--cosmos3-cache", default=os.environ.get("THOR_OFFICIAL_COSMOS3_CACHE_DIR")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("static", help="verify the official lane and demo overlay")
    subparsers.add_parser("audit", help="run every pull-free prelaunch gate")
    subparsers.add_parser("render-command", help="print the gated launch command")
    ready = subparsers.add_parser("readiness", help="verify the running demo lane")
    ready.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "static":
            verify_static(args.contract)
            print("PASS exact-model Thor demo static contract")
            return 0
        if args.command == "audit":
            return _audit(args)
        contract, edge, cosmos = _prerequisites(args)
        if args.command == "render-command":
            verify_memory(args.meminfo)
            verify_resolved_compose(args.runtime_env, edge, cosmos)
            print(render_pull_free_command(args.runtime_env, edge, cosmos))
            return 0
        if args.command == "readiness":
            verify_resolved_compose(args.runtime_env, edge, cosmos)
            verify_readiness(contract, args.timeout, edge, cosmos)
            print("PASS exact-model Thor demo runtime identity/readiness contract")
            return 0
        raise oe.ContractError(f"unsupported command: {args.command}")
    except oe.ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
