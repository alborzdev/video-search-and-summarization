#!/usr/bin/env python3
"""Fail-closed connected staging for the exact Thor official-edge artifacts.

With no arguments this program only renders a constant plan.  The ``execute``
subcommand is deliberately difficult to invoke accidentally: it requires an
exact acknowledgement, every immutable artifact identity, absolute executable
paths, symbolic credential sources, an absolute staging root, and explicit disk
headroom.  Execution produces review candidates; it never edits a lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.dont_write_bytecode = True


SCHEMA_VERSION = 1
ACKNOWLEDGEMENT = "I_ACCEPT_CONNECTED_STAGING_EXACT_THOR_OFFICIAL_EDGE_ARTIFACTS_ONLY"

EDGE_REPOSITORY = "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"
EDGE_REVISION = "3fe6dab75665a93884214ad4b1b95cf02717d081"
EDGE_CACHE_DIRECTORY = "models--nvidia--NVIDIA-Nemotron-3-Nano-4B-FP8"
COSMOS_ARTIFACT = "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final"
COSMOS_NGC_TARGET = "nim/nvidia/cosmos3-nano-reasoner:bf16-final"
COSMOS_NGC_DOWNLOAD_DIRECTORY = "cosmos3-nano-reasoner_vbf16-final"
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

# Reviewed metadata from qualification/official-edge-readiness/staging-plan.json.
# These are planning floors, not claims about exact installed/unpacked sizes.
EDGE_REMOTE_PAYLOAD_BYTES = 5_284_569_483
COSMOS_DOCUMENTED_DISK_BYTES = 30_000_000_000
EDGE_IMAGE_COMPRESSED_BYTES = 14_586_467_388
KNOWN_PLANNING_FLOOR_BYTES = 49_871_036_871

HF_CREDENTIAL_SOURCES = ("env:HF_TOKEN",)
NGC_CREDENTIAL_SOURCES = ("env:NGC_CLI_API_KEY", "env:NGC_API_KEY")
STATE_FILENAME = ".official-edge-staging-state-v1.json"
CANDIDATE_FILENAME = "official-edge-review-candidate-v1.json"
HERE = Path(__file__).absolute().parent
CONTRACT_PATH = HERE / "contract.json"
LOCK_PATH = HERE / "artifacts.lock.json"


class StagingError(RuntimeError):
    """A staging request or postcondition failed closed."""


@dataclass(frozen=True)
class ExecutionRequest:
    staging_root_text: str
    hf_executable_text: str
    ngc_executable_text: str
    docker_executable_text: str
    hf_credential_source: str
    ngc_credential_source: str
    additional_headroom_bytes: int
    minimum_free_after_bytes: int


@dataclass(frozen=True)
class ToolIdentity:
    role: str
    requested_path: str
    resolved_path: str
    sha256: str
    size_bytes: int
    version: str


def _artifact_identities() -> dict[str, Any]:
    return {
        "nemotron": {
            "repository": EDGE_REPOSITORY,
            "revision": EDGE_REVISION,
        },
        "cosmos3": {"artifact_id": COSMOS_ARTIFACT},
        "vllm_image": {
            "reference": EDGE_IMAGE,
            "manifest_digest": EDGE_IMAGE_MANIFEST_DIGEST,
            "config_digest": EDGE_IMAGE_CONFIG_DIGEST,
        },
    }


def build_plan() -> dict[str, Any]:
    """Return a literal plan without inspecting the filesystem, env, or host."""
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "plan",
        "state": "inert_no_action",
        "reads_performed": False,
        "network_performed": False,
        "filesystem_writes_performed": False,
        "docker_mutation_performed": False,
        "credential_reads_performed": False,
        "subprocesses_performed": False,
        "required_acknowledgement": ACKNOWLEDGEMENT,
        "required_explicit_inputs": [
            "absolute_staging_root",
            "absolute_hf_executable",
            "absolute_ngc_executable",
            "absolute_docker_executable",
            "exact_nemotron_repository_and_revision",
            "exact_cosmos3_artifact_id",
            "exact_digest_bound_vllm_image",
            "hf_credential_source",
            "ngc_credential_source",
            "additional_unknown_image_headroom_bytes",
            "minimum_free_after_staging_bytes",
        ],
        "allowed_credential_sources": {
            "huggingface": list(HF_CREDENTIAL_SOURCES),
            "ngc": list(NGC_CREDENTIAL_SOURCES),
        },
        "identities": _artifact_identities(),
        "disk_admission": {
            "known_planning_floor_bytes": KNOWN_PLANNING_FLOOR_BYTES,
            "nemotron_remote_payload_bytes": EDGE_REMOTE_PAYLOAD_BYTES,
            "cosmos_documented_disk_bytes": COSMOS_DOCUMENTED_DISK_BYTES,
            "vllm_compressed_bytes": EDGE_IMAGE_COMPRESSED_BYTES,
            "unpacked_vllm_size_state": "unknown_requires_explicit_additional_headroom",
        },
        "resumability": {
            "huggingface": (
                "skip_only_with_matching_prior_review_candidate_tree;"
                "unreviewed_preexisting_snapshot_fails_closed_and_requires_"
                "operator_recovery_or_new_staging_root"
            ),
            "ngc": "retained_partial_download_retried_until_exact_tool_success",
            "docker": "exact_digest_and_config_verified_before_pull",
            "journal_is_identity_evidence": False,
        },
        "output_policy": {
            "candidate_state": "review_candidate_only_not_promoted",
            "artifact_lock_mutation": False,
            "automatic_promotion": False,
            "credential_values_recorded": False,
        },
        "forbidden": [
            "mutable_image_tags",
            "alternate_model_repositories",
            "fallback_models",
            "automatic_artifacts.lock.json_mutation",
        ],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StagingError(f"cannot hash selected tool {path}: {exc}") from exc
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha256_bytes(content)


def _safe_version(output: str) -> str:
    line = output.strip().splitlines()[0] if output.strip() else "unreported"
    if len(line) > 256:
        line = line[:256]
    return line


def _subprocess(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StagingError(
            f"selected tool failed to execute: {command[0]}: {exc}"
        ) from exc


def _run_checked(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout: int,
    role: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    result = _subprocess(command, env=env, cwd=cwd, timeout=timeout)
    receipt = {
        "role": role,
        "command": list(command),
        "returncode": result.returncode,
        "stdout_sha256": _sha256_bytes(result.stdout.encode("utf-8")),
        "stderr_sha256": _sha256_bytes(result.stderr.encode("utf-8")),
        "output_recorded": False,
    }
    if result.returncode != 0:
        raise StagingError(
            f"{role} returned {result.returncode}; output was withheld to avoid "
            "credential disclosure"
        )
    return result, receipt


def _require_absolute_text(value: str, label: str) -> None:
    if not value or "\x00" in value or not Path(value).is_absolute():
        raise StagingError(f"{label} must be an explicit absolute path")


def _request_from_args(args: argparse.Namespace) -> ExecutionRequest:
    # Validate all literal authorization/identity fields before any host read.
    if args.acknowledgement != ACKNOWLEDGEMENT:
        raise StagingError(f"execute requires --acknowledgement {ACKNOWLEDGEMENT}")
    exact = {
        "--edge-repository": (args.edge_repository, EDGE_REPOSITORY),
        "--edge-revision": (args.edge_revision, EDGE_REVISION),
        "--cosmos-artifact": (args.cosmos_artifact, COSMOS_ARTIFACT),
        "--vllm-image": (args.vllm_image, EDGE_IMAGE),
    }
    for label, (actual, expected) in exact.items():
        if actual != expected:
            raise StagingError(f"{label} must equal the exact identity {expected!r}")
    _require_absolute_text(args.staging_root, "--staging-root")
    _require_absolute_text(args.hf_executable, "--hf-executable")
    _require_absolute_text(args.ngc_executable, "--ngc-executable")
    _require_absolute_text(args.docker_executable, "--docker-executable")
    if args.hf_credential_source not in HF_CREDENTIAL_SOURCES:
        raise StagingError("unsupported Hugging Face credential source")
    if args.ngc_credential_source not in NGC_CREDENTIAL_SOURCES:
        raise StagingError("unsupported NGC credential source")
    if args.additional_headroom_bytes <= 0:
        raise StagingError("--additional-headroom-bytes must be positive")
    if args.minimum_free_after_bytes <= 0:
        raise StagingError("--minimum-free-after-bytes must be positive")
    return ExecutionRequest(
        staging_root_text=args.staging_root,
        hf_executable_text=args.hf_executable,
        ngc_executable_text=args.ngc_executable,
        docker_executable_text=args.docker_executable,
        hf_credential_source=args.hf_credential_source,
        ngc_credential_source=args.ngc_credential_source,
        additional_headroom_bytes=args.additional_headroom_bytes,
        minimum_free_after_bytes=args.minimum_free_after_bytes,
    )


def _resolve_staging_root(text: str) -> Path:
    requested = Path(text)
    if requested.name in {"", ".", ".."}:
        raise StagingError("staging root must name a dedicated directory")
    parent = requested.parent
    try:
        canonical_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise StagingError(
            f"staging-root parent must already exist: {parent}: {exc}"
        ) from exc
    root = canonical_parent / requested.name
    if root == root.anchor or len(root.parts) < 3:
        raise StagingError("staging root is too broad")
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return root
    except OSError as exc:
        raise StagingError(f"cannot inspect staging root {root}: {exc}") from exc
    _assert_private_root(root, metadata)
    return root


def _assert_private_root(root: Path, metadata: os.stat_result | None = None) -> None:
    try:
        current = metadata if metadata is not None else root.lstat()
    except OSError as exc:
        raise StagingError(f"cannot inspect staging root {root}: {exc}") from exc
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
        raise StagingError("existing staging root must be a real directory, not a link")
    if current.st_uid != os.geteuid():
        raise StagingError("existing staging root must be owned by the effective user")
    if stat.S_IMODE(current.st_mode) != 0o700:
        raise StagingError("existing staging root must have exact mode 0700")


def _guard_directory_chain(root: Path, path: Path, *, create: bool) -> None:
    """Reject directory redirects while allowing symlinks inside HF snapshots."""
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise StagingError(f"child path escapes staging root: {path}") from exc
    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise StagingError(f"unsafe staging child path: {path}")
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if not create:
                return
            try:
                current.mkdir(mode=0o700)
                metadata = current.lstat()
            except OSError as exc:
                raise StagingError(
                    f"cannot create private staging directory {current}: {exc}"
                ) from exc
        except OSError as exc:
            raise StagingError(
                f"cannot inspect staging directory {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise StagingError(
                f"staging directory chain contains a redirect: {current}"
            )


def _inspect_tool(
    role: str,
    requested_text: str,
    version_args: Sequence[str],
    *,
    cwd: Path,
) -> tuple[ToolIdentity, Path]:
    requested = Path(requested_text)
    try:
        resolved = requested.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise StagingError(
            f"cannot resolve selected {role} tool {requested}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise StagingError(f"selected {role} tool is not an executable regular file")
    env = {"PATH": str(resolved.parent), "LC_ALL": "C", "LANG": "C"}
    result = _subprocess([str(resolved), *version_args], env=env, cwd=cwd, timeout=30)
    if result.returncode != 0:
        raise StagingError(
            f"selected {role} tool does not support its exact version probe"
        )
    version = _safe_version(result.stdout or result.stderr)
    return (
        ToolIdentity(
            role=role,
            requested_path=str(requested),
            resolved_path=str(resolved),
            sha256=_sha256_file(resolved),
            size_bytes=metadata.st_size,
            version=version,
        ),
        resolved,
    )


def _load_contract_and_verify_constants() -> None:
    try:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingError(f"cannot read official-edge contract: {exc}") from exc
    expected = {
        "llm.repository": (contract.get("llm") or {}).get("repository"),
        "llm.revision": (contract.get("llm") or {}).get("revision"),
        "vlm.artifact_id": (contract.get("vlm") or {}).get("artifact_id"),
        "images.edge4b_vllm.reference": (
            ((contract.get("images") or {}).get("edge4b_vllm") or {}).get("reference")
        ),
        "images.edge4b_vllm.manifest_config_digest": (
            ((contract.get("images") or {}).get("edge4b_vllm") or {}).get(
                "manifest_config_digest"
            )
        ),
    }
    required = {
        "llm.repository": EDGE_REPOSITORY,
        "llm.revision": EDGE_REVISION,
        "vlm.artifact_id": COSMOS_ARTIFACT,
        "images.edge4b_vllm.reference": EDGE_IMAGE,
        "images.edge4b_vllm.manifest_config_digest": EDGE_IMAGE_CONFIG_DIGEST,
    }
    for field, value in expected.items():
        if value != required[field]:
            raise StagingError(
                f"embedded staging identity disagrees with contract field {field}"
            )


def _credential_value(source: str, environ: Mapping[str, str]) -> tuple[str, str]:
    prefix, variable = source.split(":", 1)
    if prefix != "env":  # guarded earlier; keep this helper independently closed.
        raise StagingError("credential source must be an approved environment symbol")
    value = environ.get(variable, "")
    if not value:
        raise StagingError(f"selected credential source {source} is unset or empty")
    return variable, value


def _disk_free(path: Path) -> tuple[int, int]:
    try:
        metadata = path.stat()
        free = shutil.disk_usage(path).free
    except OSError as exc:
        raise StagingError(f"cannot inspect disk capacity for {path}: {exc}") from exc
    return metadata.st_dev, free


def _disk_admission(
    staging_parent: Path,
    docker_root: Path,
    request: ExecutionRequest,
) -> dict[str, Any]:
    stage_device, stage_free = _disk_free(staging_parent)
    docker_device, docker_free = _disk_free(docker_root)
    reserve = request.minimum_free_after_bytes
    unknown = request.additional_headroom_bytes
    same_device = stage_device == docker_device
    if same_device:
        required = KNOWN_PLANNING_FLOOR_BYTES + unknown + reserve
        if stage_free < required:
            raise StagingError(
                f"insufficient shared disk headroom: {stage_free} available; "
                f"{required} required"
            )
    else:
        stage_required = (
            EDGE_REMOTE_PAYLOAD_BYTES + COSMOS_DOCUMENTED_DISK_BYTES + reserve
        )
        docker_required = EDGE_IMAGE_COMPRESSED_BYTES + unknown + reserve
        if stage_free < stage_required:
            raise StagingError(
                f"insufficient model-staging disk headroom: {stage_free} available; "
                f"{stage_required} required"
            )
        if docker_free < docker_required:
            raise StagingError(
                f"insufficient Docker disk headroom: {docker_free} available; "
                f"{docker_required} required"
            )
    return {
        "same_filesystem": same_device,
        "staging_free_before_bytes": stage_free,
        "docker_free_before_bytes": docker_free,
        "known_planning_floor_bytes": KNOWN_PLANNING_FLOOR_BYTES,
        "additional_unknown_image_headroom_bytes": unknown,
        "minimum_free_after_bytes": reserve,
        "capacity_state": "operator_headroom_admitted_planning_floor_not_exact_size",
    }


def _base_child_env(tool_home: Path, tool_path: Path) -> dict[str, str]:
    return {
        "PATH": str(tool_path.parent),
        "HOME": str(tool_home),
        # Keep HOME isolated from operator credentials and caches while allowing
        # an explicitly selected ``pip --user`` CLI to import its own packages.
        # Python ignores this variable for non-Python tools.
        "PYTHONUSERBASE": str(tool_path.parent.parent),
        "XDG_CACHE_HOME": str(tool_home / ".cache"),
        "XDG_CONFIG_HOME": str(tool_home / ".config"),
        "LC_ALL": "C",
        "LANG": "C",
    }


def _state_template(request: ExecutionRequest, root: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "staging_incomplete",
        "staging_root": str(root),
        "identities": _artifact_identities(),
        "credential_sources": {
            "huggingface": request.hf_credential_source,
            "ngc": request.ngc_credential_source,
            "credential_values_recorded": False,
        },
        "steps": {
            "nemotron": "pending",
            "cosmos3": "pending",
            "vllm_image": "pending",
        },
        "journal_is_identity_evidence": False,
        "automatic_promotion": False,
    }


def _write_json_atomic(path: Path, value: Any) -> None:
    if path.exists() and path.is_symlink():
        raise StagingError(f"refusing to replace symlink: {path}")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists() and temporary.is_symlink():
        raise StagingError(f"refusing to replace symlink: {temporary}")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    except OSError as exc:
        raise StagingError(f"cannot write staging receipt {path}: {exc}") from exc


def _load_or_create_state(
    state_path: Path, request: ExecutionRequest, root: Path
) -> dict[str, Any]:
    expected = _state_template(request, root)
    if not state_path.exists():
        _write_json_atomic(state_path, expected)
        return expected
    if state_path.is_symlink() or not state_path.is_file():
        raise StagingError("staging state must be a regular non-symlinked file")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingError(f"cannot resume invalid staging state: {exc}") from exc
    for key in ("schema_version", "staging_root", "identities", "credential_sources"):
        if state.get(key) != expected[key]:
            raise StagingError(
                f"staging state does not match this exact request: {key}"
            )
    if state.get("automatic_promotion") is not False:
        raise StagingError("staging state violates no-promotion policy")
    return state


def _nonempty_directory(path: Path) -> bool:
    try:
        metadata = path.lstat()
        return (
            not stat.S_ISLNK(metadata.st_mode)
            and stat.S_ISDIR(metadata.st_mode)
            and any(path.iterdir())
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StagingError(f"cannot inspect staged directory {path}: {exc}") from exc


def _path_lexists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StagingError(f"cannot inspect staging path {path}: {exc}") from exc


def _load_prior_candidate(
    root: Path, tools: Sequence[ToolIdentity]
) -> dict[str, Any] | None:
    path = root / CANDIDATE_FILENAME
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StagingError(f"cannot inspect prior review candidate: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise StagingError(
            "prior review candidate must be a regular non-symlinked file"
        )
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingError(f"cannot read prior review candidate: {exc}") from exc
    if not isinstance(candidate, dict):
        raise StagingError("prior review candidate root must be an object")
    if candidate.get("candidate_state") != "review_candidate_only_not_promoted":
        raise StagingError("prior review candidate has an inadmissible state")
    if candidate.get("staging_root") != str(root):
        raise StagingError("prior review candidate belongs to another staging root")
    if candidate.get("identities") != _artifact_identities():
        raise StagingError("prior review candidate has different artifact identities")
    if candidate.get("artifact_lock_mutated") is not False:
        raise StagingError("prior review candidate asserts artifact-lock mutation")
    if candidate.get("promotion_performed") is not False:
        raise StagingError("prior review candidate asserts promotion")
    expected_tools = [tool.__dict__ for tool in tools]
    if candidate.get("tool_identities") != expected_tools:
        raise StagingError(
            "prior review candidate was produced by different tool bytes"
        )
    recorded_digest = candidate.get("candidate_canonical_sha256")
    without_digest = dict(candidate)
    without_digest.pop("candidate_canonical_sha256", None)
    if recorded_digest != _canonical_json_sha256(without_digest):
        raise StagingError("prior review candidate canonical digest does not match")
    source = candidate.get("source_evidence")
    if not isinstance(source, dict) or source.get("stager_sha256") != _sha256_file(
        Path(__file__).absolute()
    ):
        raise StagingError(
            "prior review candidate was produced by different stager bytes"
        )
    return candidate


def _prior_artifact_tree_matches(
    candidate: Mapping[str, Any], artifact_key: str, path: Path
) -> bool:
    wrapper = candidate.get("artifact_candidate")
    if not isinstance(wrapper, dict):
        return False
    proposed = wrapper.get("proposed_artifact_lock")
    artifacts = proposed.get("artifacts") if isinstance(proposed, dict) else None
    recorded = artifacts.get(artifact_key) if isinstance(artifacts, dict) else None
    if not isinstance(recorded, dict):
        return False
    sys.path.insert(0, str(HERE))
    try:
        import official_edge as verifier  # type: ignore

        if artifact_key == "edge4b":
            repository = verifier._edge_repository(path)
            entries = verifier._actual_tree_entries(path, repository)
            verifier._verify_edge_snapshot_layout(path, entries)
            blob_entries = verifier._actual_tree_entries(
                repository / "blobs", repository / "blobs"
            )
            return recorded.get("tree") == {
                "entry_count": len(entries),
                "entries": entries,
            } and recorded.get("blob_tree") == {
                "entry_count": len(blob_entries),
                "entries": blob_entries,
            }
        entries = verifier._actual_tree_entries(path, path)
        return recorded.get("tree") == {
            "entry_count": len(entries),
            "entries": entries,
        }
    except Exception:
        return False


def _docker_inspect(
    docker: Path, env: Mapping[str, str], cwd: Path
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    command = [str(docker), "image", "inspect", EDGE_IMAGE]
    result = _subprocess(command, env=env, cwd=cwd, timeout=120)
    receipt = {
        "role": "docker_image_inspect",
        "command": command,
        "returncode": result.returncode,
        "stdout_sha256": _sha256_bytes(result.stdout.encode("utf-8")),
        "stderr_sha256": _sha256_bytes(result.stderr.encode("utf-8")),
        "output_recorded": False,
    }
    if result.returncode != 0:
        return None, receipt
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise StagingError("Docker image inspect returned invalid JSON") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], dict)
    ):
        raise StagingError("Docker image inspect did not return exactly one image")
    image = payload[0]
    if image.get("Id") not in {EDGE_IMAGE_CONFIG_DIGEST, EDGE_IMAGE_MANIFEST_DIGEST}:
        raise StagingError(
            "vLLM local image ID is neither the exact manifest nor config digest"
        )
    if image.get("Architecture") != "arm64" or image.get("Os") != "linux":
        raise StagingError("vLLM image platform must be linux/arm64")
    repo_digests = image.get("RepoDigests")
    if not isinstance(repo_digests, list) or EDGE_IMAGE not in repo_digests:
        raise StagingError("vLLM image does not expose the exact repository digest")
    return image, receipt


def _stage_nemotron(
    root: Path,
    hf: Path,
    credential: str,
    base_env: Mapping[str, str],
    prior_candidate: Mapping[str, Any] | None,
) -> tuple[Path, dict[str, Any]]:
    cache = root / "huggingface" / "hub"
    snapshot = cache / EDGE_CACHE_DIRECTORY / "snapshots" / EDGE_REVISION
    if _path_lexists(snapshot):
        _guard_directory_chain(root, snapshot, create=False)
        if (
            _nonempty_directory(snapshot)
            and prior_candidate is not None
            and _prior_artifact_tree_matches(prior_candidate, "edge4b", snapshot)
        ):
            return snapshot, {
                "role": "huggingface_download",
                "action": "prior_review_candidate_tree_verified_skip",
            }
        raise StagingError(
            "pre-existing Nemotron snapshot lacks a matching review-candidate tree; "
            "refusing name-only resume; use operator recovery or a new staging root"
        )
    _guard_directory_chain(root, cache, create=True)
    env = dict(base_env)
    env.update(
        {
            "HF_TOKEN": credential,
            "HF_HOME": str(root / "huggingface"),
            "HF_HUB_CACHE": str(cache),
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    command = [
        str(hf),
        "download",
        EDGE_REPOSITORY,
        "--repo-type",
        "model",
        "--revision",
        EDGE_REVISION,
        "--cache-dir",
        str(cache),
        "--quiet",
    ]
    _, receipt = _run_checked(
        command, env=env, cwd=root, timeout=86_400, role="huggingface_download"
    )
    if not _nonempty_directory(snapshot):
        raise StagingError(
            "Hugging Face tool did not create the exact revision snapshot"
        )
    _guard_directory_chain(root, snapshot, create=False)
    return snapshot, receipt


def _stage_cosmos(
    root: Path,
    ngc: Path,
    credential: str,
    base_env: Mapping[str, str],
    prior_candidate: Mapping[str, Any] | None,
) -> tuple[Path, dict[str, Any]]:
    cache_root = root / "ngc" / "model-cache"
    canonical = cache_root / COSMOS_CACHE_DIRECTORY
    if _path_lexists(canonical):
        _guard_directory_chain(root, canonical, create=False)
        if (
            _nonempty_directory(canonical)
            and prior_candidate is not None
            and _prior_artifact_tree_matches(
                prior_candidate, "cosmos3_nano_bf16", canonical
            )
        ):
            return canonical, {
                "role": "ngc_download",
                "action": "prior_review_candidate_tree_verified_skip",
            }
        raise StagingError(
            "pre-existing Cosmos cache lacks a matching review-candidate tree; "
            "refusing name-only resume; use operator recovery or a new staging root"
        )
    partial = root / "ngc" / "partial"
    downloaded = partial / COSMOS_NGC_DOWNLOAD_DIRECTORY
    _guard_directory_chain(root, cache_root, create=True)
    _guard_directory_chain(root, partial, create=True)
    env = dict(base_env)
    env.update(
        {
            "NGC_CLI_API_KEY": credential,
            "NGC_CLI_ORG": "nim",
            "NGC_CLI_TEAM": "nvidia",
            "NGC_CLI_FORMAT_TYPE": "json",
        }
    )
    # A non-empty partial directory is not completion evidence.  Retain it for
    # the exact NGC tool to resume/reconcile, but require a successful exact
    # download-version invocation before atomically admitting the cache path.
    command = [
        str(ngc),
        "registry",
        "model",
        "download-version",
        COSMOS_NGC_TARGET,
        "--org",
        "nim",
        "--team",
        "nvidia",
        "--ace",
        "no-ace",
        "--dest",
        str(partial),
    ]
    _, receipt = _run_checked(
        command, env=env, cwd=root, timeout=86_400, role="ngc_download"
    )
    if not _nonempty_directory(downloaded):
        raise StagingError(
            "NGC tool did not create the exact bf16-final version directory"
        )
    _guard_directory_chain(root, downloaded, create=False)
    if _path_lexists(canonical):
        raise StagingError("canonical Cosmos cache appeared concurrently")
    os.replace(downloaded, canonical)
    return canonical, receipt


def _stage_vllm_image(
    root: Path,
    docker: Path,
    base_env: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipts: list[dict[str, Any]] = []
    image, inspect_receipt = _docker_inspect(docker, base_env, root)
    receipts.append(inspect_receipt)
    if image is not None:
        receipts.append({"role": "docker_pull", "action": "resumed_verified_skip"})
        return image, receipts
    _, pull_receipt = _run_checked(
        [str(docker), "pull", EDGE_IMAGE],
        env=base_env,
        cwd=root,
        timeout=86_400,
        role="docker_pull_exact_digest",
    )
    receipts.append(pull_receipt)
    image, inspect_receipt = _docker_inspect(docker, base_env, root)
    receipts.append(inspect_receipt)
    if image is None:
        raise StagingError("exact vLLM image is still absent after digest-bound pull")
    return image, receipts


def _review_candidate(
    root: Path,
    snapshot: Path,
    cosmos: Path,
    image: Mapping[str, Any],
    request: ExecutionRequest,
    tools: Sequence[ToolIdentity],
    disk: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    # Import only in acknowledged execution, never in the default plan path.
    sys.path.insert(0, str(HERE))
    try:
        import lock_candidate  # type: ignore

        artifact_candidate = lock_candidate.build_candidate(snapshot, cosmos)
    except Exception as exc:
        raise StagingError(
            f"cannot create read-only artifact review candidate: {exc}"
        ) from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "connected_staging_review_candidate",
        "candidate_state": "review_candidate_only_not_promoted",
        "staging_root": str(root),
        "identities": _artifact_identities(),
        "credential_sources": {
            "huggingface": request.hf_credential_source,
            "ngc": request.ngc_credential_source,
            "values_recorded": False,
        },
        "tool_identities": [tool.__dict__ for tool in tools],
        "disk_admission": dict(disk),
        "command_receipts": list(receipts),
        "artifact_candidate": artifact_candidate,
        "image_candidate": {
            "state": "local_exact_bytes_candidate_only_unqualified",
            "reference": EDGE_IMAGE,
            "id": image.get("Id"),
            "repo_digests": image.get("RepoDigests"),
            "architecture": image.get("Architecture"),
            "os": image.get("Os"),
            "size_bytes": image.get("Size"),
        },
        "source_evidence": {
            "contract_path": str(CONTRACT_PATH),
            "contract_sha256": _sha256_file(CONTRACT_PATH),
            "stager_sha256": _sha256_file(Path(__file__).absolute()),
        },
        "artifact_lock_path": str(LOCK_PATH),
        "artifact_lock_mutated": False,
        "promotion_performed": False,
        "runtime_qualification_performed": False,
    }


def execute(request: ExecutionRequest, environ: Mapping[str, str]) -> dict[str, Any]:
    _load_contract_and_verify_constants()
    root = _resolve_staging_root(request.staging_root_text)
    hf_var, hf_credential = _credential_value(request.hf_credential_source, environ)
    ngc_var, ngc_credential = _credential_value(request.ngc_credential_source, environ)
    # The variable names are intentionally retained only as symbolic provenance.
    assert hf_var == "HF_TOKEN"
    assert ngc_var in {"NGC_CLI_API_KEY", "NGC_API_KEY"}

    cwd = root.parent
    hf_tool, hf = _inspect_tool(
        "huggingface", request.hf_executable_text, ["version"], cwd=cwd
    )
    ngc_tool, ngc = _inspect_tool(
        "ngc", request.ngc_executable_text, ["--version"], cwd=cwd
    )
    docker_tool, docker = _inspect_tool(
        "docker", request.docker_executable_text, ["--version"], cwd=cwd
    )
    tools = [hf_tool, ngc_tool, docker_tool]

    tool_home = root / "tool-home"
    docker_env = {
        "PATH": str(docker.parent),
        "HOME": str(tool_home),
        "DOCKER_CONFIG": str(tool_home / ".docker-empty"),
        "LC_ALL": "C",
        "LANG": "C",
    }
    docker_info, _ = _run_checked(
        [str(docker), "info", "--format", "{{.DockerRootDir}}"],
        env=docker_env,
        cwd=cwd,
        timeout=120,
        role="docker_root_inspection",
    )
    docker_root_text = docker_info.stdout.strip()
    if not Path(docker_root_text).is_absolute():
        raise StagingError("Docker reported a non-absolute data root")
    try:
        docker_root = Path(docker_root_text).resolve(strict=True)
    except OSError as exc:
        raise StagingError(f"cannot inspect Docker data root: {exc}") from exc
    disk = _disk_admission(root.parent, docker_root, request)

    # All preflight gates above are read-only.  The first mutation occurs here.
    root.mkdir(mode=0o700, parents=False, exist_ok=True)
    _assert_private_root(root)
    _guard_directory_chain(root, tool_home, create=True)
    _guard_directory_chain(root, tool_home / ".docker-empty", create=True)
    prior_candidate = _load_prior_candidate(root, tools)
    state_path = root / STATE_FILENAME
    state = _load_or_create_state(state_path, request, root)
    receipts: list[dict[str, Any]] = []

    hf_env = _base_child_env(tool_home, hf)
    snapshot, receipt = _stage_nemotron(
        root, hf, hf_credential, hf_env, prior_candidate
    )
    receipts.append(receipt)
    state["steps"]["nemotron"] = "verified_exact_identity_candidate"
    _write_json_atomic(state_path, state)

    ngc_env = _base_child_env(tool_home, ngc)
    cosmos, receipt = _stage_cosmos(root, ngc, ngc_credential, ngc_env, prior_candidate)
    receipts.append(receipt)
    state["steps"]["cosmos3"] = "verified_exact_identity_candidate"
    _write_json_atomic(state_path, state)

    docker_env = _base_child_env(tool_home, docker)
    docker_env["DOCKER_CONFIG"] = str(tool_home / ".docker-empty")
    image, image_receipts = _stage_vllm_image(root, docker, docker_env)
    receipts.extend(image_receipts)
    state["steps"]["vllm_image"] = "verified_exact_identity_candidate"
    _write_json_atomic(state_path, state)

    _, staging_free_after = _disk_free(root)
    _, docker_free_after = _disk_free(docker_root)
    if min(staging_free_after, docker_free_after) < request.minimum_free_after_bytes:
        raise StagingError(
            "staging completed but the explicitly required free-space reserve was not retained"
        )
    disk = dict(disk)
    disk["staging_free_after_bytes"] = staging_free_after
    disk["docker_free_after_bytes"] = docker_free_after

    candidate = _review_candidate(
        root, snapshot, cosmos, image, request, tools, disk, receipts
    )
    candidate["candidate_canonical_sha256"] = _canonical_json_sha256(candidate)
    _write_json_atomic(root / CANDIDATE_FILENAME, candidate)
    state["state"] = "staged_review_candidate_only_not_promoted"
    state["review_candidate"] = CANDIDATE_FILENAME
    state["promotion_performed"] = False
    _write_json_atomic(state_path, state)
    return candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan", help="render the inert constant plan (default)")
    run = subparsers.add_parser(
        "execute", help="perform explicitly acknowledged staging"
    )
    run.add_argument("--acknowledgement", required=True)
    run.add_argument("--staging-root", required=True)
    run.add_argument("--hf-executable", required=True)
    run.add_argument("--ngc-executable", required=True)
    run.add_argument("--docker-executable", required=True)
    run.add_argument("--hf-credential-source", required=True)
    run.add_argument("--ngc-credential-source", required=True)
    run.add_argument("--edge-repository", required=True)
    run.add_argument("--edge-revision", required=True)
    run.add_argument("--cosmos-artifact", required=True)
    run.add_argument("--vllm-image", required=True)
    run.add_argument("--additional-headroom-bytes", type=int, required=True)
    run.add_argument("--minimum-free-after-bytes", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in (None, "plan"):
            result = build_plan()
        else:
            request = _request_from_args(args)
            result = execute(request, os.environ)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except StagingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
