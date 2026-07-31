#!/usr/bin/env python3
"""Validate the immutable VSS 3.2.1 Agent model contract and Thor snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
DEFAULT_MANIFEST = HERE / "official-vss-3.2.1.json"
DEFAULT_STATE = HERE / "thor-state.json"
RELEASE_COMMIT = "7640d917047cf7b0fd3085eefb8282754b56bc94"
TARGET_MAIN_COMMIT = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
CAPTURED_ON = "2026-07-31"
OFFICIAL_ORACLE_SHA256 = "d6d44086a1a5a26fe0c02f8a6623e48282c66d50019c7ab8aa31c97d44c8ed71"
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
IMMUTABLE_REVISION = re.compile(r"^(?:[0-9a-f]{40,64}|sha256:[0-9a-f]{64})$")

EXPECTED_LLM = [
    ("nvidia/nvidia-nemotron-nano-9b-v2", "nvidia-nemotron-nano-9b-v2", "default", "verified"),
    (
        "nvidia/NVIDIA-Nemotron-Nano-9B-v2-FP8",
        "nvidia-nemotron-nano-9b-v2-fp8",
        "supported-alternate",
        "not-verified",
    ),
    ("nvidia/nemotron-3-nano", "nemotron-3-nano", "supported-alternate", "not-verified"),
    (
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "llama-3.3-nemotron-super-49b-v1.5",
        "supported-alternate",
        "not-verified",
    ),
    ("openai/gpt-oss-20b", "gpt-oss-20b", "supported-alternate", "not-verified"),
]

EXPECTED_VLM = [
    (
        "nvidia/cosmos3-nano-reasoner",
        "cosmos3-reasoner",
        "nano",
        "default",
        "verified",
    ),
    (
        "nvidia/cosmos-reason2-8b",
        "cosmos-reason2-8b",
        None,
        "supported-alternate",
        "not-verified",
    ),
    (
        "Qwen/Qwen3-VL-8B-Instruct",
        "qwen3-vl-8b-instruct",
        None,
        "supported-alternate",
        "not-verified",
    ),
]

EXPECTED_AMBIGUOUS_VLM = [
    (
        "nvidia/cosmos3-super-reasoner",
        "cosmos3-reasoner",
        "super",
        "repository-declared-local-option-not-in-docs-supported-list",
        False,
    ),
    (
        "nvidia/cosmos-reason1-7b",
        "cosmos-reason1-7b",
        None,
        "tag-env-option-omitted-from-3.2.1-docs-supported-list",
        False,
    ),
]

EXPECTED_REMOTE = {
    "llm": {
        "hosted_nim": [
            "nvidia/nemotron-3-nano-30b-a3b",
            "openai/gpt-oss-120b",
            "z-ai/glm5",
        ],
        "frontier_openai": ["gpt-5.2", "gpt-4.1"],
        "downloadable_nim_images": [
            "nvcr.io/nim/nvidia/nemotron-3-nano:latest",
            "nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:latest",
            "nvcr.io/nim/openai/gpt-oss-20b:latest",
        ],
        "self_hosted_vllm": ["OpenAI/gpt-oss-20b", "Qwen/Qwen3-8B"],
    },
    "vlm": {
        "frontier_openai": ["gpt-5.2", "gpt-4.1"],
        "reka": ["reka-flash"],
        "downloadable_nim_images": [
            "nvcr.io/nim/nvidia/cosmos3-reasoner:1.7",
            "nvcr.io/nim/nvidia/cosmos-reason2-8b:latest",
            "nvcr.io/nim/nvidia/cosmos-reason2-2b:latest",
        ],
        "self_hosted_vllm": ["Qwen/Qwen3-VL-8B-Instruct"],
        "audio_enabled_omni_checkpoint": [
            "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4"
        ],
    },
}

EXPECTED_OMNI_SETTINGS = {
    "max_model_len": 131072,
    "tensor_parallel_size": 1,
    "trust_remote_code": True,
    "video_pruning_rate": 0.5,
    "max_num_seqs": 384,
    "video_fps": 2,
    "video_num_frames": 256,
    "reasoning_parser": "nemotron_v3",
    "enable_auto_tool_choice": True,
    "tool_call_parser": "qwen3_coder",
    "kv_cache_dtype": "fp8",
    "enable_flashinfer_autotune": False,
}

EXPECTED_SOURCE_IDS = {
    "llm-docs",
    "vlm-docs",
    "release-notes",
    "prerequisites",
    "tag-base-env",
    "tag-agent-config",
}

EXPECTED_SOURCES = {
    "llm-docs": (
        "https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-llm.html",
        None,
    ),
    "vlm-docs": (
        "https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-vlm.html",
        None,
    ),
    "release-notes": ("https://docs.nvidia.com/vss/3.2.1/release-notes.html", None),
    "prerequisites": ("https://docs.nvidia.com/vss/3.2.1/prerequisites.html", None),
    "tag-base-env": (
        "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/blob/"
        f"{RELEASE_COMMIT}/deploy/docker/developer-profiles/dev-profile-base/.env",
        "508e04f8d35afd6deefe2fa8c1c37e0ba5b408168b8d81763eb630d3b47f2b6b",
    ),
    "tag-agent-config": (
        "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/blob/"
        f"{RELEASE_COMMIT}/deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml",
        "e89664e421bac7b8869b9dfa1e4149930e11b935bf6dc01351392a6557bb4c79",
    ),
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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _expect(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _tuple_rows(rows: Any, keys: tuple[str, ...]) -> list[tuple[Any, ...]]:
    if not isinstance(rows, list):
        return []
    return [tuple(row.get(key) for key in keys) if isinstance(row, dict) else () for row in rows]


def _reviewed_file_reference(
    row: dict[str, Any], path_key: str, digest_key: str, model_id: str
) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    path_text = row.get(path_key)
    digest = row.get(digest_key)
    if (
        not isinstance(path_text, str)
        or not path_text.startswith("deploy/docker/thor-local/")
        or Path(path_text).is_absolute()
        or ".." in Path(path_text).parts
    ):
        return None, [f"{model_id}: {path_key} must be a safe reviewed repository path"]
    if not isinstance(digest, str) or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        errors.append(f"{model_id}: {digest_key} must be an exact SHA-256")
    path = REPO_ROOT
    try:
        resolved_root = REPO_ROOT.resolve(strict=True)
        for part in Path(path_text).parts:
            path /= part
            if path.is_symlink():
                errors.append(
                    f"{model_id}: reviewed path contains a symlink: {path_text}"
                )
                return None, errors
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        errors.append(f"{model_id}: reviewed file does not exist inside the repository: {path_text}")
        return None, errors
    if not resolved.is_file():
        errors.append(f"{model_id}: reviewed path must be a regular non-symlink file: {path_text}")
        return None, errors
    if isinstance(digest, str) and sha256(resolved) != digest:
        errors.append(f"{model_id}: reviewed file digest differs: {path_text}")
    return resolved, errors


def _validated_checks(
    value: Any, model_id: str, context: str, required_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list) or not value:
        return [f"{model_id}: {context}.checks must be a non-empty list"]
    identifiers: list[str] = []
    for check in value:
        if not isinstance(check, dict):
            errors.append(f"{model_id}: {context}.checks must contain objects")
            continue
        identifier = check.get("id")
        if not isinstance(identifier, str) or PLAIN_ID.fullmatch(identifier) is None:
            errors.append(f"{model_id}: {context} check has an invalid id")
        else:
            identifiers.append(identifier)
        if check.get("result") != "pass":
            errors.append(f"{model_id}: {context} check {identifier!r} did not pass")
    if len(identifiers) != len(set(identifiers)):
        errors.append(f"{model_id}: {context} check ids must be unique")
    missing = required_ids - set(identifiers)
    if missing:
        errors.append(
            f"{model_id}: {context} is missing required checks: {sorted(missing)}"
        )
    return errors


def _safe_artifact_path(path_text: Any, model_id: str) -> str:
    if (
        not isinstance(path_text, str)
        or not path_text
        or Path(path_text).is_absolute()
        or ".." in Path(path_text).parts
        or Path(path_text).as_posix() != path_text
    ):
        raise ValueError(f"{model_id}: unsafe artifact path {path_text!r}")
    return path_text


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _artifact_tree(root: Path, allowed_root: Path, model_id: str) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"{model_id}: artifact root must be a real directory")
    resolved_root = root.resolve(strict=True)
    resolved_allowed = allowed_root.resolve(strict=True)
    if not _within(resolved_root, resolved_allowed):
        raise ValueError(f"{model_id}: artifact root escapes its allowed repository")
    entries: list[dict[str, Any]] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in list(directories):
            path = current_path / directory
            if path.is_symlink():
                raise ValueError(f"{model_id}: artifact directory symlinks are forbidden")
        for name in files:
            path = current_path / name
            relative = _safe_artifact_path(path.relative_to(root).as_posix(), model_id)
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = os.readlink(path)
                if Path(target).is_absolute():
                    raise ValueError(f"{model_id}: absolute artifact symlink is forbidden")
                resolved = path.resolve(strict=True)
                if not _within(resolved, resolved_allowed) or not resolved.is_file():
                    raise ValueError(f"{model_id}: artifact symlink escapes its repository")
                entries.append(
                    {
                        "path": relative,
                        "type": "symlink",
                        "target": target,
                        "size": resolved.stat().st_size,
                        "sha256": sha256(resolved),
                    }
                )
            elif stat.S_ISREG(mode):
                entries.append(
                    {
                        "path": relative,
                        "type": "file",
                        "size": path.stat().st_size,
                        "sha256": sha256(path),
                    }
                )
            else:
                raise ValueError(f"{model_id}: unsupported artifact entry type")
    entries.sort(key=lambda item: item["path"])
    return entries


def _validate_artifact_lock(
    lock: dict[str, Any], row: dict[str, Any], model_id: str
) -> list[str]:
    errors: list[str] = []
    source = lock.get("source")
    entries = lock.get("files")
    if not isinstance(source, dict):
        errors.append(f"{model_id}: artifact lock source must be an object")
    else:
        _expect(
            errors,
            source.get("model_id") == model_id,
            f"{model_id}: artifact source model_id differs",
        )
        _expect(
            errors,
            source.get("kind") in {"huggingface_snapshot", "ngc_model_cache"},
            f"{model_id}: artifact source kind is not recognized",
        )
        _expect(
            errors,
            isinstance(source.get("uri"), str)
            and (
                (
                    source.get("kind") == "huggingface_snapshot"
                    and source["uri"].startswith("https://huggingface.co/")
                )
                or (
                    source.get("kind") == "ngc_model_cache"
                    and source["uri"].startswith("ngc:")
                )
            ),
            f"{model_id}: artifact source URI does not match its recognized source kind",
        )
        _expect(
            errors,
            isinstance(source.get("revision"), str)
            and IMMUTABLE_REVISION.fullmatch(source["revision"]) is not None,
            f"{model_id}: artifact source revision must be immutable",
        )
    if not isinstance(entries, list) or not entries:
        errors.append(f"{model_id}: artifact lock files must be non-empty")
        return errors
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{model_id}: artifact lock files must contain objects")
            continue
        try:
            path_text = _safe_artifact_path(entry.get("path"), model_id)
        except ValueError as error:
            errors.append(str(error))
            continue
        if path_text in seen:
            errors.append(f"{model_id}: artifact lock paths must be unique")
        seen.add(path_text)
        expected_keys = (
            {"path", "type", "target", "size", "sha256"}
            if entry.get("type") == "symlink"
            else {"path", "type", "size", "sha256"}
        )
        _expect(
            errors,
            set(entry) == expected_keys and entry.get("type") in {"file", "symlink"},
            f"{model_id}: invalid artifact file entry for {path_text}",
        )
        _expect(
            errors,
            type(entry.get("size")) is int and entry["size"] >= 0,
            f"{model_id}: invalid artifact size for {path_text}",
        )
        _expect(
            errors,
            isinstance(entry.get("sha256"), str)
            and SHA256.fullmatch(entry["sha256"]) is not None,
            f"{model_id}: invalid artifact digest for {path_text}",
        )
    _expect(
        errors,
        [entry.get("path") for entry in entries if isinstance(entry, dict)]
        == sorted(seen),
        f"{model_id}: artifact lock files must be sorted",
    )
    _expect(
        errors,
        lock.get("tree_sha256") == _canonical_sha256(entries),
        f"{model_id}: artifact aggregate tree digest differs",
    )
    root_text = row.get("artifact_root_path")
    allowed_text = row.get("artifact_allowed_root_path")
    if not all(isinstance(value, str) and Path(value).is_absolute() for value in (root_text, allowed_text)):
        errors.append(f"{model_id}: staged artifact requires absolute root and allowed-root paths")
        return errors
    try:
        actual = _artifact_tree(Path(root_text), Path(allowed_text), model_id)
    except (OSError, ValueError) as error:
        errors.append(str(error))
    else:
        _expect(
            errors,
            actual == entries,
            f"{model_id}: staged artifact tree differs from exact lock",
        )
    return errors


def _validate_backend_lock(lock: dict[str, Any], model_id: str) -> list[str]:
    errors: list[str] = []
    image = lock.get("image")
    command = lock.get("command")
    environment = lock.get("environment")
    if not isinstance(image, dict):
        errors.append(f"{model_id}: backend image lock must be an object")
    else:
        reference = image.get("reference")
        _expect(
            errors,
            isinstance(reference, str) and IMAGE_DIGEST.fullmatch(reference) is not None,
            f"{model_id}: backend image reference must use an immutable repo digest",
        )
        _expect(
            errors,
            image.get("repo_digest") == reference,
            f"{model_id}: backend repo digest differs from image reference",
        )
        _expect(
            errors,
            isinstance(image.get("image_id"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", image["image_id"]) is not None,
            f"{model_id}: backend image ID must be exact",
        )
    _expect(
        errors,
        isinstance(command, list)
        and bool(command)
        and all(isinstance(item, str) and item for item in command)
        and model_id in command,
        f"{model_id}: backend command contract must be a non-empty string list",
    )
    _expect(
        errors,
        isinstance(environment, dict)
        and bool(environment)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in environment.items())
        and environment.get("SERVED_MODEL_ID") == model_id,
        f"{model_id}: backend environment must bind SERVED_MODEL_ID",
    )
    contract = {"image": image, "command": command, "environment": environment}
    _expect(
        errors,
        lock.get("contract_sha256") == _canonical_sha256(contract),
        f"{model_id}: backend image/command/environment contract digest differs",
    )
    return errors


def _validate_model_lock(
    path: Path, model_id: str, expected_lock_type: str, row: dict[str, Any]
) -> list[str]:
    try:
        lock = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"{model_id}: invalid {expected_lock_type} JSON: {error}"]
    errors: list[str] = []
    expected = {
        "schema_version": 1,
        "lock_type": expected_lock_type,
        "model_id": model_id,
        "release_commit": RELEASE_COMMIT,
        "target_commit": TARGET_MAIN_COMMIT,
        "state": "locked_exact",
    }
    for key, value in expected.items():
        _expect(
            errors,
            type(lock.get(key)) is type(value) and lock.get(key) == value,
            f"{model_id}: {expected_lock_type}.{key} must be {value!r}",
        )
    required_checks = (
        {"source-identity", "artifact-tree"}
        if expected_lock_type == "exact-agent-model-artifact"
        else {"image-identity", "command-contract", "environment-contract"}
    )
    errors.extend(
        _validated_checks(
            lock.get("checks"), model_id, expected_lock_type, required_checks
        )
    )
    if expected_lock_type == "exact-agent-model-artifact":
        errors.extend(_validate_artifact_lock(lock, row, model_id))
    else:
        errors.extend(_validate_backend_lock(lock, model_id))
    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    release = manifest.get("release", {})
    _expect(errors, manifest.get("schema_version") == 1, "manifest schema_version must be 1")
    _expect(errors, release.get("version") == "3.2.1", "release version must be 3.2.1")
    _expect(
        errors,
        release.get("upstream_tag_commit") == RELEASE_COMMIT,
        "release commit must be the peeled official v3.2.1 tag",
    )

    sources = manifest.get("sources", [])
    source_ids = {source.get("id") for source in sources if isinstance(source, dict)}
    _expect(errors, source_ids == EXPECTED_SOURCE_IDS, "source inventory is incomplete or has extras")
    _expect(errors, len(sources) == len(EXPECTED_SOURCE_IDS), "source inventory contains duplicates")
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            errors.append("every source must be an object")
            continue
        url = source.get("url", "")
        expected_url, expected_sha256 = EXPECTED_SOURCES.get(source.get("id"), (None, None))
        _expect(errors, url == expected_url, f"source URL changed for {source.get('id')}")
        _expect(errors, isinstance(url, str) and url.startswith("https://"), f"invalid source URL: {url!r}")
        if source.get("id", "").startswith("tag-"):
            _expect(errors, RELEASE_COMMIT in url, f"repository source is not commit-pinned: {url}")
            sha256 = source.get("sha256", "")
            _expect(errors, sha256 == expected_sha256, f"repository source SHA-256 changed: {url}")
        else:
            _expect(errors, "/3.2.1/" in url, f"documentation source is not versioned: {url}")

    llm = manifest.get("llm", {})
    _expect(errors, llm.get("selector") == "--llm", "LLM selector changed")
    _expect(
        errors,
        llm.get("default_model_id") == EXPECTED_LLM[0][0],
        "LLM default differs from official 3.2.1",
    )
    actual_llm = _tuple_rows(
        llm.get("local_models"),
        ("model_id", "profile_slug", "official_role", "official_local_verification"),
    )
    _expect(errors, actual_llm == EXPECTED_LLM, "exact local LLM inventory or semantics changed")

    vlm = manifest.get("vlm", {})
    _expect(errors, vlm.get("selector") == "--vlm", "VLM selector changed")
    _expect(
        errors,
        vlm.get("default_model_id") == EXPECTED_VLM[0][0],
        "VLM default differs from official 3.2.1",
    )
    actual_vlm = _tuple_rows(
        vlm.get("explicit_local_models"),
        ("model_id", "profile_slug", "nim_model_size", "official_role", "official_local_verification"),
    )
    _expect(errors, actual_vlm == EXPECTED_VLM, "exact local VLM inventory or semantics changed")
    actual_ambiguous = _tuple_rows(
        vlm.get("repository_only_or_ambiguous_local_references"),
        ("model_id", "profile_slug", "nim_model_size", "classification", "resolved"),
    )
    _expect(
        errors,
        actual_ambiguous == EXPECTED_AMBIGUOUS_VLM,
        "repository/docs VLM ambiguity inventory changed or was marked resolved without review",
    )

    for kind in ("llm", "vlm"):
        remote = manifest.get(kind, {}).get("remote_contract", {})
        _expect(errors, remote.get("model_set") == "open-ended", f"{kind.upper()} remote set must stay open-ended")
        _expect(
            errors,
            remote.get("named_examples") == EXPECTED_REMOTE[kind],
            f"exact advertised remote {kind.upper()} examples changed",
        )
    _expect(
        errors,
        vlm.get("remote_contract", {}).get("omni_vllm_settings") == EXPECTED_OMNI_SETTINGS,
        "Nemotron Omni vLLM settings changed",
    )

    custom = vlm.get("custom_weights", {})
    _expect(errors, custom.get("supported") is True, "custom VLM weights capability was dropped")
    _expect(errors, custom.get("setting") == "VLM_CUSTOM_WEIGHTS", "custom weights setting changed")
    _expect(errors, custom.get("deploy_flag") == "--vlm-custom-weights", "custom weights flag changed")

    boundary = manifest.get("thor_platform_boundary", {})
    _expect(
        errors,
        boundary.get("platforms") == ["AGX-THOR", "IGX-THOR"],
        "Thor platform inventory changed",
    )
    _expect(
        errors,
        boundary.get("official_3_2_1_configuration") == "remote-LLM",
        "official Thor configuration must remain remote-LLM",
    )
    _expect(
        errors,
        boundary.get("fully_local_all_agent_workflows_supported") is False,
        "official 3.2.1 does not support fully local all-workflow Thor Agent deployment",
    )

    ambiguities = manifest.get("ambiguities", [])
    ambiguity_ids = [item.get("id") for item in ambiguities if isinstance(item, dict)]
    _expect(
        errors,
        ambiguity_ids
        == [
            "cosmos3-super-local-list-skew",
            "cosmos-reason1-tag-doc-skew",
            "remote-model-set-open-ended",
            "mutable-latest-container-tags",
        ],
        "ambiguity inventory changed",
    )
    _expect(
        errors,
        all(item.get("resolution") != "resolved" for item in ambiguities if isinstance(item, dict)),
        "an ambiguity was silently marked resolved",
    )
    return errors


def expected_state_models() -> set[tuple[str, str]]:
    expected = {("llm", row[0]) for row in EXPECTED_LLM}
    expected.update({("vlm", row[0]) for row in EXPECTED_VLM})
    expected.update({("vlm-ambiguous", row[0]) for row in EXPECTED_AMBIGUOUS_VLM})
    return expected


def validate_state(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    blockers: list[str] = []
    _expect(errors, state.get("schema_version") == 1, "state schema_version must be 1")
    _expect(errors, state.get("observed_on") == CAPTURED_ON, "state observation date changed")
    _expect(
        errors,
        state.get("target_commit") == TARGET_MAIN_COMMIT,
        "state target commit must be the reviewed upstream main commit",
    )
    _expect(
        errors,
        state.get("runtime_qualification") in {"not-run", "qualified"},
        "invalid aggregate runtime qualification",
    )

    rows = state.get("official_model_state", [])
    actual_models = {
        (row.get("kind"), row.get("model_id")) for row in rows if isinstance(row, dict)
    }
    _expect(errors, actual_models == expected_state_models(), "Thor state does not cover every official/ambiguous model")
    _expect(
        errors,
        isinstance(rows, list) and len(rows) == len(expected_state_models()),
        "Thor state rows must be unique and contain exactly one row per model",
    )
    allowed_artifact = {
        "absent",
        "staged-hf-snapshot-only",
        "staged-and-locked",
    }
    allowed_backend = {"absent", "staged-and-locked"}
    allowed_runtime = {"not-run", "qualified"}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            errors.append("every Thor model state row must be an object")
            continue
        model_id = row.get("model_id", "<missing>")
        _expect(
            errors,
            row.get("exact_artifact_state") in allowed_artifact,
            f"{model_id}: invalid exact artifact state",
        )
        _expect(
            errors,
            row.get("agent_backend_state") in allowed_backend,
            f"{model_id}: invalid Agent backend state",
        )
        _expect(
            errors,
            row.get("runtime_qualification") in allowed_runtime,
            f"{model_id}: invalid runtime qualification",
        )
        if row.get("exact_artifact_state") == "staged-and-locked":
            artifact_path, reference_errors = _reviewed_file_reference(
                row, "artifact_lock_path", "artifact_lock_sha256", str(model_id)
            )
            errors.extend(reference_errors)
            if artifact_path is not None and not reference_errors:
                errors.extend(
                    _validate_model_lock(
                        artifact_path,
                        str(model_id),
                        "exact-agent-model-artifact",
                        row,
                    )
                )
        if row.get("agent_backend_state") == "staged-and-locked":
            backend_path, reference_errors = _reviewed_file_reference(
                row, "backend_lock_path", "backend_lock_sha256", str(model_id)
            )
            errors.extend(reference_errors)
            if backend_path is not None and not reference_errors:
                errors.extend(
                    _validate_model_lock(
                        backend_path,
                        str(model_id),
                        "exact-agent-model-backend",
                        row,
                    )
                )
        if row.get("runtime_qualification") == "qualified":
            _expect(
                errors,
                row.get("exact_artifact_state") == "staged-and-locked"
                and row.get("agent_backend_state") == "staged-and-locked",
                f"{model_id}: runtime qualification requires the exact artifact and backend",
            )
            evidence_path, reference_errors = _reviewed_file_reference(
                row, "evidence_path", "evidence_sha256", str(model_id)
            )
            errors.extend(reference_errors)
            if evidence_path is not None and not reference_errors:
                try:
                    evidence = load_json(evidence_path)
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    errors.append(f"{model_id}: invalid runtime evidence JSON: {error}")
                else:
                    evidence_errors = _validated_checks(
                        evidence.get("checks"),
                        str(model_id),
                        "runtime evidence",
                        {"models-endpoint", "semantic-request", "agent-workflow"},
                    )
                    errors.extend(evidence_errors)
                    _expect(
                        errors,
                        type(evidence.get("schema_version")) is int
                        and evidence.get("schema_version") == 1
                        and evidence.get("model_id") == model_id
                        and evidence.get("result") == "passed_current"
                        and evidence.get("release_commit") == RELEASE_COMMIT
                        and evidence.get("target_commit") == TARGET_MAIN_COMMIT
                        and evidence.get("captured_on") == state.get("observed_on")
                        and evidence.get("artifact_lock_path")
                        == row.get("artifact_lock_path")
                        and evidence.get("artifact_lock_sha256")
                        == row.get("artifact_lock_sha256")
                        and evidence.get("backend_lock_path")
                        == row.get("backend_lock_path")
                        and evidence.get("backend_lock_sha256")
                        == row.get("backend_lock_sha256")
                        and not evidence_errors,
                        f"{model_id}: runtime evidence is not bound to this exact model and locks",
                    )
        # Repository/docs ambiguities stay visible but are not exact official
        # models and therefore do not inflate the completeness denominator.
        if row.get("kind") in {"llm", "vlm"}:
            if row.get("exact_artifact_state") != "staged-and-locked":
                blockers.append(f"{model_id}: exact Agent artifact is not staged and locked")
            if row.get("agent_backend_state") != "staged-and-locked":
                blockers.append(f"{model_id}: Agent backend is not staged and locked")
            if row.get("runtime_qualification") != "qualified":
                blockers.append(f"{model_id}: runtime qualification is absent")

    if state.get("runtime_qualification") == "qualified" and blockers:
        errors.append("aggregate runtime qualification requires every exact official model")
    if not blockers and state.get("runtime_qualification") != "qualified":
        errors.append("every exact official model is qualified but aggregate state is not qualified")

    expected_alternates = {
        ("llm", "Qwen/Qwen3.6-35B-A3B-FP8", "95a723d08a9490559dae23d0cff1d9466213d989"),
        ("vlm", "Qwen/Qwen3-VL-8B-Instruct-FP8", "9cdc6310a8cb770ce18efaf4e9935334512aee45"),
        ("vlm", "nvidia/Cosmos-Reason2-8B", "a9fae2cf89dc64db96b12860417f0eb403013bb9"),
    }
    actual_alternates = {
        (row.get("kind"), row.get("model_id"), row.get("revision"))
        for row in state.get("non_official_local_alternates", [])
        if isinstance(row, dict)
    }
    _expect(errors, actual_alternates == expected_alternates, "reviewed local alternate inventory changed")
    _expect(
        errors,
        all(
            row.get("runtime_qualification") == "not-claimed-by-this-lane"
            for row in state.get("non_official_local_alternates", [])
            if isinstance(row, dict)
        ),
        "static lane must not qualify local alternates",
    )
    return errors, blockers


def validate_files(manifest_path: Path, state_path: Path) -> tuple[list[str], list[str]]:
    try:
        if sha256(manifest_path) != OFFICIAL_ORACLE_SHA256:
            return ["official VSS 3.2.1 Agent-model oracle digest differs"], []
        manifest = load_json(manifest_path)
        state = load_json(state_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [str(error)], []
    errors = validate_manifest(manifest)
    state_errors, blockers = validate_state(state)
    errors.extend(state_errors)
    return errors, blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--require-thor-complete",
        action="store_true",
        help="also fail unless every exact official model has staged backend and runtime evidence",
    )
    args = parser.parse_args(argv)
    errors, blockers = validate_files(args.manifest, args.state)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print("[OK] Exact NVIDIA VSS 3.2.1 Agent model contract is internally consistent.")
    state = load_json(args.state)
    if state.get("runtime_qualification") == "qualified" and not blockers:
        print("[OK] Every exact model has current Thor runtime qualification evidence.")
    else:
        print("[OK] Thor state covers every exact model and makes no runtime qualification claim.")
    print(f"[INFO] Thor-completeness blockers: {len(blockers)}")
    if args.require_thor_complete and blockers:
        for blocker in blockers:
            print(f"[BLOCKED] {blocker}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
