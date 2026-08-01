#!/usr/bin/env python3
"""Inert-by-default, read-only readiness inventory for Thor official-edge VSS."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
DEFAULT_PLAN = HERE / "staging-plan.json"
DEFAULT_HF_HUB = Path.home() / ".cache/huggingface/hub"
DEFAULT_MEMINFO = Path("/proc/meminfo")
DEFAULT_DISK_PATH = REPO_ROOT
OFFICIAL_VERIFIER = (
    REPO_ROOT / "deploy/docker/thor-local/official-edge/official_edge.py"
)
ACKNOWLEDGEMENT = "I_ACCEPT_READ_ONLY_HOST_INSPECTION"
DOCKER_HOST = "unix:///var/run/docker.sock"


class ReadinessError(RuntimeError):
    """A source-lock, input, or inspection-policy violation."""


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReadinessError(f"JSON root must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReadinessError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _expect(mapping: dict[str, Any], key: str, expected: Any, context: str) -> None:
    if mapping.get(key) != expected:
        raise ReadinessError(
            f"{context}.{key} is {mapping.get(key)!r}; expected {expected!r}"
        )


def validate_plan(plan: dict[str, Any]) -> None:
    _expect(plan, "schema_version", 1, "plan")
    _expect(plan, "plan_id", "vss-3.2.1-thor-official-edge-readiness", "plan")
    _expect(plan, "scope", "read_only_prelaunch_inspection", "plan")
    policy = plan.get("inspection_policy")
    if not isinstance(policy, dict):
        raise ReadinessError("inspection_policy must be an object")
    for key in (
        "network",
        "docker_mutation",
        "filesystem_mutation",
        "credential_reads",
    ):
        _expect(policy, key, False, "inspection_policy")
    _expect(
        policy,
        "allowed_docker_operations",
        ["image inspect", "container inspect", "volume inspect"],
        "inspection_policy",
    )
    identities = plan.get("identities")
    images = plan.get("images")
    if not isinstance(identities, dict) or not isinstance(images, dict):
        raise ReadinessError("plan identities and images must be objects")
    _expect(
        identities["llm"],
        "repository",
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8",
        "identities.llm",
    )
    _expect(
        identities["vlm"],
        "artifact_id",
        "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final",
        "identities.vlm",
    )
    _expect(identities["vlm"], "selector", "cosmos-reason3", "identities.vlm")
    for key in ("edge_vllm", "rt_vlm"):
        entry = images.get(key)
        if not isinstance(entry, dict):
            raise ReadinessError(f"images.{key} must be an object")
        reference = entry.get("exact_reference")
        digest = entry.get("required_manifest_digest")
        if not isinstance(reference, str) or not reference.endswith(f"@{digest}"):
            raise ReadinessError(f"images.{key} reference is not digest-bound")
        _expect(entry, "required_architecture", "arm64", f"images.{key}")
    if plan.get("forbidden_substitutions") != [
        "nvidia/NVIDIA-Nemotron-Edge-4B-v2.1-EA-020126_FP8",
        "datasheet-chat",
        "datasheet-vision",
        "Qwen/Qwen3-VL-8B-Instruct-FP8",
    ]:
        raise ReadinessError("forbidden substitutions drifted")
    remote = plan.get("reviewed_remote_staging_metadata")
    if not isinstance(remote, dict):
        raise ReadinessError("reviewed_remote_staging_metadata must be an object")
    _expect(remote, "local_readiness_evidence", False, "remote_staging")
    _expect(
        remote["edge_llm"],
        "revision",
        "3fe6dab75665a93884214ad4b1b95cf02717d081",
        "remote_staging.edge_llm",
    )
    _expect(remote["edge_llm"], "total_bytes", 5284569483, "remote_staging.edge_llm")
    _expect(
        remote["edge_vllm_image"],
        "manifest_payload_bytes",
        14586467388,
        "remote_staging.edge_vllm_image",
    )
    _expect(
        remote["edge_vllm_image"],
        "installed_or_unpacked_size",
        None,
        "remote_staging.edge_vllm_image",
    )
    _expect(
        remote["cosmos3_nano_bf16"],
        "access_state",
        "blocked_invalid_apikey",
        "remote_staging.cosmos3_nano_bf16",
    )
    _expect(
        plan["admission"],
        "known_minimum_remote_payload_bytes_excluding_cosmos3",
        19871036871,
        "admission",
    )


def verify_source_locks(plan: dict[str, Any]) -> dict[str, Any]:
    locks = plan.get("source_locks")
    if not isinstance(locks, list) or not locks:
        raise ReadinessError("source_locks must be a non-empty list")
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    repository = REPO_ROOT.resolve(strict=True)
    for index, entry in enumerate(locks):
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ReadinessError(f"source_locks[{index}] has invalid shape")
        path_text = entry["path"]
        expected = entry["sha256"]
        if (
            not isinstance(path_text, str)
            or path_text in seen
            or path_text.startswith("/")
        ):
            raise ReadinessError(f"source_locks[{index}] has unsafe or duplicate path")
        if ".." in Path(path_text).parts:
            raise ReadinessError(f"source_locks[{index}] escapes the repository")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ReadinessError(f"source_locks[{index}] has invalid SHA-256")
        seen.add(path_text)
        source_path = REPO_ROOT / path_text
        try:
            resolved_source = source_path.resolve(strict=True)
        except OSError as exc:
            raise ReadinessError(
                f"source_locks[{index}] cannot resolve inside the repository: {exc}"
            ) from exc
        if not _within(resolved_source, repository):
            raise ReadinessError(
                f"source_locks[{index}] resolves outside the repository: {path_text}"
            )
        actual = _sha256(resolved_source)
        results.append(
            {
                "path": path_text,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "state": "match" if actual == expected else "drift",
            }
        )
    return {
        "state": "match"
        if all(item["state"] == "match" for item in results)
        else "drift",
        "files": results,
    }


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _tree_summary(path: Path, allowed_root: Path | None = None) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink():
        return {"state": "not_a_real_directory", "entry_count": 0, "bytes": 0}
    try:
        allowed = (allowed_root or path).resolve(strict=True)
        resolved_root = path.resolve(strict=True)
    except OSError as exc:
        return {
            "state": "unreadable",
            "entry_count": 0,
            "bytes": 0,
            "detail": str(exc),
        }
    if not _within(resolved_root, allowed):
        return {
            "state": "path_escape",
            "entry_count": 0,
            "bytes": 0,
        }
    entries = 0
    byte_count = 0
    try:
        for current, directory_names, file_names in os.walk(path, followlinks=False):
            current_path = Path(current)
            for name in directory_names:
                candidate = current_path / name
                if candidate.is_symlink():
                    resolved = candidate.resolve(strict=True)
                    if not _within(resolved, allowed):
                        return {
                            "state": "unsafe_symlink_escape",
                            "entry_count": entries,
                            "bytes": byte_count,
                            "detail": str(candidate.relative_to(path)),
                        }
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not (current_path / name).is_symlink()
            )
            entries += len(directory_names)
            for name in sorted(file_names):
                candidate = current_path / name
                entries += 1
                if candidate.is_symlink():
                    resolved = candidate.resolve(strict=True)
                    if not _within(resolved, allowed):
                        return {
                            "state": "unsafe_symlink_escape",
                            "entry_count": entries,
                            "bytes": byte_count,
                            "detail": str(candidate.relative_to(path)),
                        }
                if candidate.is_file():
                    byte_count += candidate.stat().st_size
    except OSError as exc:
        return {
            "state": "unreadable",
            "entry_count": entries,
            "bytes": byte_count,
            "detail": str(exc),
        }
    return {"state": "readable", "entry_count": entries, "bytes": byte_count}


def inspect_edge_artifact(plan: dict[str, Any], hf_hub: Path) -> dict[str, Any]:
    cache_name = plan["identities"]["llm"]["standard_hf_cache_directory"]
    repository = hf_hub / cache_name
    snapshots = repository / "snapshots"
    candidates: list[dict[str, Any]] = []
    if snapshots.is_dir() and not snapshots.is_symlink():
        try:
            children = sorted(snapshots.iterdir(), key=lambda item: item.name)
        except OSError:
            children = []
        for child in children:
            revision = child.name
            if (
                child.is_dir()
                and not child.is_symlink()
                and len(revision) == 40
                and all(character in "0123456789abcdef" for character in revision)
            ):
                candidates.append(
                    {
                        "revision": revision,
                        "path": str(child),
                        "tree_summary": _tree_summary(child, repository),
                        "matches_reviewed_remote_revision": revision
                        == plan["reviewed_remote_staging_metadata"]["edge_llm"][
                            "revision"
                        ],
                        "identity_state": "candidate_only_not_lock_evidence",
                    }
                )
    matching = any(item["matches_reviewed_remote_revision"] for item in candidates)
    selected = next(
        (
            item["path"]
            for item in candidates
            if item["matches_reviewed_remote_revision"]
        ),
        None,
    )
    return {
        "repository": plan["identities"]["llm"]["repository"],
        "cache_repository_path": str(repository),
        "cache_repository_state": "present" if repository.is_dir() else "missing",
        "snapshot_candidates": candidates,
        "selected_candidate_path": selected,
        "reviewed_remote_staging_metadata": plan["reviewed_remote_staging_metadata"][
            "edge_llm"
        ],
        "reviewed_remote_metadata_is_local_readiness_evidence": False,
        "state": (
            "candidate_present_unlocked"
            if matching
            else "wrong_revision_candidates_only"
            if candidates
            else "missing_exact_artifact"
        ),
    }


def inspect_cosmos_artifact(
    plan: dict[str, Any], cosmos_cache: Path | None
) -> dict[str, Any]:
    if cosmos_cache is None:
        return {
            "artifact_id": plan["identities"]["vlm"]["artifact_id"],
            "path": null_value(),
            "tree_summary": null_value(),
            "reviewed_remote_staging_metadata": plan[
                "reviewed_remote_staging_metadata"
            ]["cosmos3_nano_bf16"],
            "reviewed_remote_metadata_is_local_readiness_evidence": False,
            "state": "exact_cache_path_not_supplied",
        }
    absolute = cosmos_cache.expanduser().absolute()
    summary = _tree_summary(absolute)
    present_nonempty = summary["state"] == "readable" and summary["entry_count"] > 0
    return {
        "artifact_id": plan["identities"]["vlm"]["artifact_id"],
        "path": str(absolute),
        "tree_summary": summary,
        "reviewed_remote_staging_metadata": plan["reviewed_remote_staging_metadata"][
            "cosmos3_nano_bf16"
        ],
        "reviewed_remote_metadata_is_local_readiness_evidence": False,
        "state": (
            "candidate_present_unlocked"
            if present_nonempty
            else "empty_candidate_directory"
            if summary["state"] == "readable"
            else "missing_or_unreadable_exact_cache"
        ),
    }


def null_value() -> None:
    """Keep JSON null construction obvious without accepting magic strings."""

    return None


def _docker(args: list[str]) -> tuple[str, str]:
    allowed = {
        ("image", "inspect"),
        ("container", "inspect"),
        ("volume", "inspect"),
    }
    if len(args) < 2 or tuple(args[:2]) not in allowed:
        raise ReadinessError(f"forbidden Docker operation: {args}")
    command = ["docker", "--host", DOCKER_HOST, *args]
    environment = {
        "PATH": os.environ.get(
            "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
        ),
        "LANG": "C.UTF-8",
    }
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReadinessError(f"Docker inspection failed to execute: {exc}") from exc
    return result.stdout.strip(), result.stderr.strip() if result.returncode else ""


def _parse_pipe_json(output: str, fields: int, context: str) -> list[Any]:
    parts = output.split("|", fields - 1)
    if len(parts) != fields:
        raise ReadinessError(f"unexpected {context} inspection output")
    try:
        return [json.loads(part) for part in parts]
    except json.JSONDecodeError as exc:
        raise ReadinessError(f"invalid JSON in {context} inspection output") from exc


def inspect_image(entry: dict[str, Any]) -> dict[str, Any]:
    reference = entry["exact_reference"]
    output, error = _docker(
        [
            "image",
            "inspect",
            reference,
            "--format",
            "{{json .Id}}|{{json .RepoDigests}}|{{json .RepoTags}}|{{json .Size}}|{{json .Architecture}}|{{json .Os}}",
        ]
    )
    if error:
        state = "missing" if "No such image" in error else "inspection_unavailable"
        return {"reference": reference, "state": state, "detail": error}
    image_id, digests, tags, size, architecture, operating_system = _parse_pipe_json(
        output, 6, reference
    )
    exact = (
        isinstance(digests, list)
        and reference in digests
        and architecture == entry["required_architecture"]
        and operating_system == "linux"
    )
    return {
        "reference": reference,
        "state": "present_exact" if exact else "present_but_not_exact",
        "image_id": image_id,
        "repository_digests": digests,
        "repository_tags": tags,
        "inspect_size_bytes": size,
        "architecture": architecture,
        "os": operating_system,
    }


def inspect_mutable_tag(
    reference: str, required_exact_reference: str
) -> dict[str, Any]:
    output, error = _docker(
        [
            "image",
            "inspect",
            reference,
            "--format",
            "{{json .Id}}|{{json .RepoDigests}}|{{json .Size}}|{{json .Architecture}}|{{json .Os}}",
        ]
    )
    if error:
        state = "missing" if "No such image" in error else "inspection_unavailable"
        return {"reference": reference, "state": state, "detail": error}
    image_id, digests, size, architecture, operating_system = _parse_pipe_json(
        output, 5, reference
    )
    matches = isinstance(digests, list) and required_exact_reference in digests
    return {
        "reference": reference,
        "state": (
            "present_same_digest_discovery_only"
            if matches
            else "present_wrong_digest_for_official_contract"
        ),
        "required_exact_reference_matches": matches,
        "image_id": image_id,
        "repository_digests": digests,
        "inspect_size_bytes": size,
        "architecture": architecture,
        "os": operating_system,
    }


def inspect_volume(name: str) -> dict[str, Any]:
    output, error = _docker(
        ["volume", "inspect", name, "--format", "{{json .Name}}|{{json .Mountpoint}}"]
    )
    if error:
        state = "missing" if "No such volume" in error else "inspection_unavailable"
        return {"name": name, "state": state, "detail": error}
    observed_name, mountpoint = _parse_pipe_json(output, 2, name)
    return {
        "name": observed_name,
        "state": "present_metadata_only_not_identity_evidence",
        "mountpoint": mountpoint,
    }


def inspect_container(
    name: str, required_image_reference: str | None
) -> dict[str, Any]:
    output, error = _docker(
        [
            "container",
            "inspect",
            name,
            "--format",
            "{{json .State.Running}}|{{json .State.Status}}|{{json .Image}}|{{json .Config.Image}}|{{json .Config.Cmd}}",
        ]
    )
    if error:
        state = (
            "absent"
            if "No such object" in error or "No such container" in error
            else "inspection_unavailable"
        )
        return {"name": name, "state": state, "detail": error}
    running, status, image_id, configured_image, command = _parse_pipe_json(
        output, 5, name
    )
    image_matches = (
        required_image_reference is None or configured_image == required_image_reference
    )
    return {
        "name": name,
        "state": "running" if running else "not_running",
        "docker_status": status,
        "image_id": image_id,
        "configured_image": configured_image,
        "required_image_reference": required_image_reference,
        "required_image_reference_matches": image_matches,
        "command": command,
    }


def inspect_memory(path: Path, required_fraction: str) -> dict[str, Any]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in {"MemTotal:", "MemAvailable:"}:
                values[parts[0]] = int(parts[1])
    except (OSError, ValueError) as exc:
        return {"state": "inspection_unavailable", "detail": str(exc)}
    if values.keys() != {"MemTotal:", "MemAvailable:"} or values["MemTotal:"] <= 0:
        return {"state": "inspection_unavailable", "detail": "incomplete meminfo"}
    actual = Decimal(values["MemAvailable:"]) / Decimal(values["MemTotal:"])
    required = Decimal(required_fraction)
    return {
        "state": "pass" if actual >= required else "blocked_below_admission_threshold",
        "total_kib": values["MemTotal:"],
        "available_kib": values["MemAvailable:"],
        "available_fraction": format(actual, ".6f"),
        "required_fraction": required_fraction,
    }


def inspect_disk(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    absolute = path.expanduser().absolute()
    try:
        values = os.statvfs(absolute)
    except OSError as exc:
        return {
            "path": str(absolute),
            "state": "inspection_unavailable",
            "detail": str(exc),
        }
    return {
        "path": str(absolute),
        "state": "required_staging_bytes_unknown",
        "capacity_bytes": values.f_blocks * values.f_frsize,
        "available_bytes": values.f_bavail * values.f_frsize,
        "known_minimum_remote_payload_bytes_excluding_cosmos3": plan["admission"][
            "known_minimum_remote_payload_bytes_excluding_cosmos3"
        ],
        "required_additional_bytes": None,
        "capacity_qualified": False,
    }


def inspect_artifact_lock(plan: dict[str, Any]) -> dict[str, Any]:
    lock_path = REPO_ROOT / "deploy/docker/thor-local/official-edge/artifacts.lock.json"
    lock = _load_json(lock_path)
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ReadinessError("official artifact lock has no artifacts object")
    results: dict[str, Any] = {
        "path": str(lock_path.relative_to(REPO_ROOT)),
        "lock_state": lock.get("lock_state"),
        "entries": {},
    }
    for gate_name, gate in plan["artifact_gates"].items():
        key = gate["lock_key"]
        entry = artifacts.get(key)
        if not isinstance(entry, dict):
            raise ReadinessError(f"official artifact lock lacks {key}")
        tree = entry.get("tree")
        identity = entry.get("identity")
        results["entries"][gate_name] = {
            "lock_key": key,
            "state": entry.get("state"),
            "identity": identity,
            "tree_present": isinstance(tree, dict),
            "tree_entry_count": tree.get("entry_count")
            if isinstance(tree, dict)
            else None,
        }
    return results


def _load_official_verifier() -> Any:
    """Load the source-locked verifier without changing import search paths."""

    spec = importlib.util.spec_from_file_location(
        "thor_official_edge_source_locked_verifier", OFFICIAL_VERIFIER
    )
    if spec is None or spec.loader is None:
        raise ReadinessError("cannot load the source-locked official-edge verifier")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (Exception, SystemExit) as exc:  # pragma: no cover - host-specific
        raise ReadinessError(
            f"cannot import the official-edge verifier: {exc}"
        ) from exc
    return module


def verify_candidate_trees(
    lock_path: Path, edge_snapshot: Path, cosmos_cache: Path
) -> dict[str, Any]:
    """Delegate byte-exact tree verification to the source-locked verifier."""

    verifier = _load_official_verifier()
    try:
        verifier.verify_artifacts(lock_path, edge_snapshot, cosmos_cache)
    except verifier.ContractError as exc:
        return {
            "state": "mismatch_or_unqualified",
            "verifier": str(OFFICIAL_VERIFIER.relative_to(REPO_ROOT)),
            "detail": str(exc),
        }
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
        return {
            "state": "verifier_error",
            "verifier": str(OFFICIAL_VERIFIER.relative_to(REPO_ROOT)),
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "state": "exact_match",
        "verifier": str(OFFICIAL_VERIFIER.relative_to(REPO_ROOT)),
        "edge_snapshot": str(edge_snapshot),
        "cosmos_cache": str(cosmos_cache),
    }


def _blocker(identifier: str, state: str, detail: str) -> dict[str, str]:
    return {"id": identifier, "state": state, "detail": detail}


def build_plan_result(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plan_id": plan["plan_id"],
        "inspection_mode": "plan",
        "qualification_state": "plan_only",
        "runtime_qualification_performed": False,
        "source_locks": {"state": "not_inspected", "expected": plan["source_locks"]},
        "artifact_lock": {
            "state": "not_inspected",
            "requirements": plan["artifact_gates"],
        },
        "artifacts": {"state": "not_inspected", "identities": plan["identities"]},
        "images": {"state": "not_inspected", "requirements": plan["images"]},
        "memory": {"state": "not_inspected", "requirements": plan["admission"]},
        "disk": {"state": "not_inspected", "rule": plan["admission"]["disk_rule"]},
        "containers": {"state": "not_inspected", "requirements": plan["containers"]},
        "blockers": [
            _blocker(
                "inspection.not_executed",
                "unverified",
                "Plan mode performs no host or Docker inspection.",
            )
        ],
    }


def build_host_result(
    plan: dict[str, Any],
    *,
    hf_hub: Path,
    cosmos_cache: Path | None,
    meminfo: Path,
    disk_path: Path,
) -> dict[str, Any]:
    sources = verify_source_locks(plan)
    artifact_lock = inspect_artifact_lock(plan)
    edge = inspect_edge_artifact(plan, hf_hub.expanduser().absolute())
    cosmos = inspect_cosmos_artifact(plan, cosmos_cache)
    lock_path = REPO_ROOT / "deploy/docker/thor-local/official-edge/artifacts.lock.json"
    selected_edge = edge.get("selected_candidate_path")
    if (
        sources["state"] == "match"
        and artifact_lock["lock_state"] == "complete_exact"
        and isinstance(selected_edge, str)
        and cosmos_cache is not None
        and cosmos["state"] == "candidate_present_unlocked"
    ):
        tree_verification = verify_candidate_trees(
            lock_path,
            Path(selected_edge),
            cosmos_cache.expanduser().absolute(),
        )
    else:
        tree_verification = {
            "state": (
                "not_evaluated_source_lock_drift"
                if sources["state"] != "match"
                else "not_evaluated_prerequisites_missing"
            ),
            "verifier": str(OFFICIAL_VERIFIER.relative_to(REPO_ROOT)),
        }
    volume = inspect_volume(plan["artifact_gates"]["cosmos_cache"]["discovery_volume"])
    edge_image = inspect_image(plan["images"]["edge_vllm"])
    edge_image["reviewed_remote_staging_metadata"] = plan[
        "reviewed_remote_staging_metadata"
    ]["edge_vllm_image"]
    edge_image["reviewed_remote_metadata_is_local_readiness_evidence"] = False
    mutable_image = inspect_mutable_tag(
        plan["images"]["edge_vllm"]["documented_mutable_tag"],
        plan["images"]["edge_vllm"]["exact_reference"],
    )
    rtvlm_image = inspect_image(plan["images"]["rt_vlm"])
    images = {
        "edge_vllm": edge_image,
        "edge_vllm_documented_mutable_tag": mutable_image,
        "rt_vlm": rtvlm_image,
    }
    memory = inspect_memory(
        meminfo, plan["admission"]["minimum_available_memory_fraction"]
    )
    disk = inspect_disk(disk_path, plan)
    containers: dict[str, Any] = {}
    for name, requirement in plan["containers"].items():
        image_key = requirement["required_image_key"]
        required_reference = (
            plan["images"][image_key]["exact_reference"] if image_key else None
        )
        containers[name] = inspect_container(name, required_reference)

    blockers: list[dict[str, str]] = []
    if sources["state"] != "match":
        blockers.append(
            _blocker("sources.drift", "blocked", "Official-edge source locks drifted.")
        )
    if artifact_lock["lock_state"] != "complete_exact":
        blockers.append(
            _blocker(
                "artifacts.lock_incomplete",
                "blocked",
                f"Artifact lock state is {artifact_lock['lock_state']!r}, not 'complete_exact'.",
            )
        )
    if tree_verification["state"] != "exact_match":
        blockers.append(
            _blocker(
                "artifacts.exact_tree_verification",
                "blocked",
                f"Source-locked exact artifact verification state is {tree_verification['state']}.",
            )
        )
    for key, observation in (("edge_snapshot", edge), ("cosmos_cache", cosmos)):
        if observation["state"] != "candidate_present_unlocked":
            blockers.append(
                _blocker(
                    f"artifacts.{key}",
                    "blocked",
                    f"Exact artifact candidate is unavailable: {observation['state']}.",
                )
            )
    for key, observation in (("edge_vllm", edge_image), ("rt_vlm", rtvlm_image)):
        if observation["state"] != "present_exact":
            blockers.append(
                _blocker(
                    f"images.{key}",
                    "blocked",
                    f"Exact digest-bound image is unavailable: {observation['state']}.",
                )
            )
    if mutable_image.get("state") == "present_wrong_digest_for_official_contract":
        blockers.append(
            _blocker(
                "images.edge_vllm_mutable_tag_mismatch",
                "unverified",
                "The locally tagged documented vLLM image has a different repository digest and cannot substitute for the exact image.",
            )
        )
    if memory.get("state") != "pass":
        blockers.append(
            _blocker(
                "admission.memory",
                "blocked",
                f"Unified-memory admission state is {memory.get('state')}.",
            )
        )
    blockers.append(
        _blocker(
            "admission.disk_bytes_unknown",
            "unverified",
            "Exact missing model/image byte requirements are not published in the reviewed lock; free bytes alone cannot qualify staging capacity.",
        )
    )
    if volume["state"] == "present_metadata_only_not_identity_evidence":
        blockers.append(
            _blocker(
                "artifacts.cosmos_volume_identity",
                "unverified",
                "The existing Docker volume is discovery metadata only; it does not prove the Cosmos3 artifact identity or tree.",
            )
        )
    for name, observation in containers.items():
        if observation["state"] != "running":
            blockers.append(
                _blocker(
                    f"runtime.{name}",
                    "unverified",
                    f"Runtime container is {observation['state']}; no lifecycle action or runtime qualification was performed.",
                )
            )
        elif observation.get("required_image_reference_matches") is False:
            blockers.append(
                _blocker(
                    f"runtime.{name}.image",
                    "unverified",
                    "Running container does not use the official exact image reference.",
                )
            )
    blocked = any(item["state"] == "blocked" for item in blockers)
    return {
        "schema_version": 1,
        "plan_id": plan["plan_id"],
        "inspection_mode": "read_only_host",
        "qualification_state": (
            "blocked_not_runtime_qualified"
            if blocked
            else "prelaunch_ready_not_runtime_qualified"
        ),
        "runtime_qualification_performed": False,
        "source_locks": sources,
        "artifact_lock": artifact_lock,
        "artifacts": {
            "edge_snapshot": edge,
            "cosmos_cache": cosmos,
            "cosmos_discovery_volume": volume,
            "exact_tree_verification": tree_verification,
        },
        "images": images,
        "memory": memory,
        "disk": disk,
        "containers": containers,
        "blockers": blockers,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="print the inert inspection plan")
    inspect = subparsers.add_parser("inspect", help="perform allowlisted local reads")
    inspect.add_argument("--acknowledgement", required=True)
    inspect.add_argument("--hf-hub", type=Path, default=DEFAULT_HF_HUB)
    inspect.add_argument("--cosmos3-cache", type=Path)
    inspect.add_argument("--meminfo", type=Path, default=DEFAULT_MEMINFO)
    inspect.add_argument("--disk-path", type=Path, default=DEFAULT_DISK_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = _load_json(args.plan)
        validate_plan(plan)
        if args.command == "plan":
            result = build_plan_result(plan)
        else:
            if args.acknowledgement != ACKNOWLEDGEMENT:
                raise ReadinessError(
                    f"inspect requires --acknowledgement {ACKNOWLEDGEMENT}"
                )
            result = build_host_result(
                plan,
                hf_hub=args.hf_hub,
                cosmos_cache=args.cosmos3_cache,
                meminfo=args.meminfo,
                disk_path=args.disk_path,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ReadinessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
