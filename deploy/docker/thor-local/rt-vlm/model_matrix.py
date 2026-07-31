#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate the reviewed Thor RT-VLM matrix and verify locked local snapshots."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


EXPECTED_VARIANTS = {
    "cosmos_reason2_8b_0303_fp8_dynamic_kv8": (
        "cosmos-reason2",
        "ngc:nim/nvidia/cosmos-reason2-8b:0303-fp8-dynamic-kv8",
    ),
    "cosmos_reason2_8b_hf_0303": (
        "cosmos-reason2",
        "ngc:nim/nvidia/cosmos-reason2-8b:hf-0303",
    ),
    "cosmos_reason2_8b_0303_fp4_dynamic_kv8": (
        "cosmos-reason2",
        "ngc:nim/nvidia/cosmos-reason2-8b:0303-fp4-dynamic-kv8",
    ),
    "cosmos3_nano_modelopt_nvfp4": (
        "cosmos-reason3",
        "ngc:nim/nvidia/cosmos3-nano-reasoner:modelopt-nvfp4-full-quantize-final_format_fix",
    ),
    "cosmos3_nano_bf16": (
        "cosmos-reason3",
        "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final",
    ),
    "nemotron3_nano_omni_reasoning": (
        "vllm-compatible",
        "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning",
    ),
    "nemotron3_nano_omni_reasoning_fp8": (
        "vllm-compatible",
        "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8",
    ),
    "qwen3_vl_30b_a3b_instruct": (
        "vllm-compatible",
        "Qwen/Qwen3-VL-30B-A3B-Instruct",
    ),
    "qwen3_omni_30b_a3b_instruct": (
        "vllm-compatible",
        "Qwen/Qwen3-Omni-30B-A3B-Instruct",
    ),
    "qwen3_5_27b": ("vllm-compatible", "Qwen/Qwen3.5-27B"),
    "cosmos_reason1_7b_1_1_fp8_dynamic": (
        "cosmos-reason1",
        "ngc:nim/nvidia/cosmos-reason1-7b:1.1-fp8-dynamic",
    ),
}
EXPECTED_LOCAL = {
    "cosmos_reason2_8b_bf16_hf": (
        "nvidia/Cosmos-Reason2-8B",
        "a9fae2cf89dc64db96b12860417f0eb403013bb9",
    ),
    "cosmos_reason2_2b_bf16_hf": (
        "nvidia/Cosmos-Reason2-2B",
        "3dafcf35a57ce708a32241e06d6533c9c3ee0ab8",
    ),
}


class MatrixError(RuntimeError):
    """The reviewed matrix, its source anchors, or a local lock drifted."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MatrixError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MatrixError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_matrix(
    matrix_path: Path, artifact_lock_path: Path, repo_root: Path
) -> dict[str, Any]:
    matrix = _load(matrix_path)
    lock = _load(artifact_lock_path)
    if matrix.get("schema_version") != 1 or lock.get("schema_version") != 1:
        raise MatrixError("matrix and artifact lock schema_version must both be 1")
    revision = matrix.get("reviewed_upstream_revision")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise MatrixError("reviewed_upstream_revision must be an immutable Git commit")

    source_text: dict[str, str] = {}
    contracts = matrix.get("source_contracts")
    if not isinstance(contracts, dict) or set(contracts) != {
        "rt_vlm_readme",
        "cosmos3_nim_compose",
    }:
        raise MatrixError("source_contracts inventory differs")
    for name, contract in contracts.items():
        if not isinstance(contract, dict):
            raise MatrixError(f"invalid source contract: {name}")
        relative = contract.get("path")
        expected_hash = contract.get("sha256")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        ):
            raise MatrixError(f"unsafe source contract: {name}")
        source = repo_root / relative
        if _sha256(source) != expected_hash:
            raise MatrixError(f"reviewed source bytes differ: {relative}")
        source_text[name] = source.read_text(encoding="utf-8")

    variants = matrix.get("advertised_rt_vlm_variants")
    if not isinstance(variants, list):
        raise MatrixError("advertised_rt_vlm_variants must be an array")
    indexed = {item.get("key"): item for item in variants if isinstance(item, dict)}
    if len(indexed) != len(variants) or set(indexed) != set(EXPECTED_VARIANTS):
        raise MatrixError("advertised RT-VLM variant inventory differs")
    for key, (selector, artifact_id) in EXPECTED_VARIANTS.items():
        item = indexed[key]
        if item.get("selector") != selector or item.get("artifact_id") != artifact_id:
            raise MatrixError(f"advertised variant differs: {key}")
        if item.get("thor_status") != "missing_exact_artifact_unqualified":
            raise MatrixError(f"Thor status overclaims exact artifact coverage: {key}")
        if artifact_id not in source_text["rt_vlm_readme"]:
            raise MatrixError(
                f"advertised artifact is absent from reviewed README: {artifact_id}"
            )

    remote = matrix.get("remote_compatible")
    if not isinstance(remote, dict) or remote != {
        "artifact_id": None,
        "selector": "openai-compat",
        "thor_status": "adapter_present_endpoint_specific_unqualified",
    }:
        raise MatrixError("remote-compatible contract differs")
    if "VLM_MODEL_TO_USE=openai-compat" not in source_text["rt_vlm_readme"]:
        raise MatrixError("remote-compatible selector is absent from reviewed README")

    adjacent = matrix.get("adjacent_profile_variants")
    if not isinstance(adjacent, list) or len(adjacent) != 1:
        raise MatrixError("Cosmos3 Super distinction is missing")
    super_entry = adjacent[0]
    required_super = {
        "artifact_id": None,
        "friendly_model_id": "nvidia/cosmos3-super-reasoner",
        "nim_image": "nvcr.io/nim/nvidia/cosmos3-reasoner:1.7",
        "nim_model_size": "super",
        "route": "base-profile-compose-nim-not-rt-vlm-matrix",
        "thor_status": "artifact_revision_size_and_thor_recipe_unknown_unqualified",
    }
    if not isinstance(super_entry, dict) or any(
        super_entry.get(k) != v for k, v in required_super.items()
    ):
        raise MatrixError("Cosmos3 Super uncertainty contract differs")
    for token in (required_super["nim_image"], "NIM_MODEL_SIZE"):
        if token not in source_text["cosmos3_nim_compose"]:
            raise MatrixError(f"Cosmos3 Super source anchor is absent: {token}")

    omni = matrix.get("distinct_omni_examples")
    omni_ids = (
        {item.get("repository") for item in omni if isinstance(item, dict)}
        if isinstance(omni, list)
        else set()
    )
    if omni_ids != {
        "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8",
        "nvidia/Nemotron-Nano-V3-Omni-GA0420-FP8",
    }:
        raise MatrixError("distinct Omni identifiers were collapsed or omitted")

    locked_artifacts = lock.get("artifacts")
    if not isinstance(locked_artifacts, dict) or set(locked_artifacts) != set(
        EXPECTED_LOCAL
    ):
        raise MatrixError("local RT-VLM artifact lock inventory differs")
    local = matrix.get("local_artifacts")
    local_by_key = (
        {
            item.get("artifact_lock_key"): item
            for item in local
            if isinstance(item, dict)
        }
        if isinstance(local, list)
        else {}
    )
    if set(local_by_key) != set(EXPECTED_LOCAL):
        raise MatrixError("local matrix inventory differs from artifact lock")
    for key, (repository, artifact_revision) in EXPECTED_LOCAL.items():
        artifact = locked_artifacts[key]
        provenance = artifact.get("provenance") if isinstance(artifact, dict) else None
        entry = local_by_key[key]
        if (
            not isinstance(provenance, dict)
            or provenance.get("repository") != repository
            or provenance.get("revision") != artifact_revision
        ):
            raise MatrixError(f"local provenance differs: {key}")
        if (
            entry.get("repository") != repository
            or entry.get("revision") != artifact_revision
        ):
            raise MatrixError(f"matrix-to-lock provenance differs: {key}")
        files = artifact.get("tree", {}).get("files", [])
        if sum(
            item.get("size", -1) for item in files if isinstance(item, dict)
        ) != entry.get("logical_bytes"):
            raise MatrixError(f"logical byte count differs: {key}")
        if entry.get("runtime_qualified_on_thor") is not False:
            raise MatrixError(f"runtime qualification is not established: {key}")
    return matrix


def _artifact_verifier(repo_root: Path):
    path = repo_root / "deploy/docker/thor-local/models/verify_artifacts.py"
    spec = importlib.util.spec_from_file_location("thor_artifact_verifier", path)
    if spec is None or spec.loader is None:
        raise MatrixError(f"cannot load artifact verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_local(
    matrix_path: Path,
    artifact_lock_path: Path,
    repo_root: Path,
    artifact_key: str,
    repository_root: Path,
) -> None:
    matrix = validate_matrix(matrix_path, artifact_lock_path, repo_root)
    local = next(
        (
            item
            for item in matrix["local_artifacts"]
            if item["artifact_lock_key"] == artifact_key
        ),
        None,
    )
    if local is None:
        raise MatrixError(f"local artifact is absent from matrix: {artifact_key}")
    revision = local["revision"]
    snapshot = repository_root / "snapshots" / revision
    verifier = _artifact_verifier(repo_root)
    verifier.verify_hf_snapshot(
        verifier.load_lock(artifact_lock_path),
        artifact_key,
        snapshot,
        repository_root,
        local["repository"],
        revision,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--artifact-lock", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    verify = subparsers.add_parser("verify-local")
    verify.add_argument("--artifact", choices=sorted(EXPECTED_LOCAL), required=True)
    verify.add_argument("--repository-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            validate_matrix(args.matrix, args.artifact_lock, args.repo_root)
            print(
                "[OK] Reviewed RT-VLM model matrix is source-anchored and internally consistent"
            )
        else:
            verify_local(
                args.matrix,
                args.artifact_lock,
                args.repo_root,
                args.artifact,
                args.repository_root,
            )
            print(f"[OK] Exact locked local RT-VLM artifact verified: {args.artifact}")
    except (MatrixError, OSError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
