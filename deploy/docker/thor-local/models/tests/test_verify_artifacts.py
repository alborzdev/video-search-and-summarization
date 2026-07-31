# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest


MODULE_PATH = Path(__file__).parents[1] / "verify_artifacts.py"
SPEC = importlib.util.spec_from_file_location("thor_model_artifacts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifacts)


def safetensor(tensors: dict[str, bytes]) -> bytes:
    offset = 0
    header: dict[str, Any] = {}
    payload = bytearray()
    for name, data in tensors.items():
        header[name] = {
            "dtype": "U8",
            "shape": [len(data)],
            "data_offsets": [offset, offset + len(data)],
        }
        payload.extend(data)
        offset += len(data)
    encoded = json.dumps(header, separators=(",", ":")).encode()
    padding = (-len(encoded)) % 8
    encoded += b" " * padding
    return len(encoded).to_bytes(8, "little") + encoded + payload


def hf_fixture(tmp_path: Path) -> tuple[dict[str, Any], Path, Path]:
    repository = "Acme/Test-FP8"
    revision = "a" * 40
    repo_root = tmp_path / "models--Acme--Test-FP8"
    snapshot = repo_root / "snapshots" / revision
    blobs = repo_root / "blobs"
    snapshot.mkdir(parents=True)
    blobs.mkdir()
    contents = {
        "config.json": json.dumps(
            {
                "architectures": ["TestForGeneration"],
                "model_type": "test",
                "quantization_config": {"quant_method": "fp8"},
            },
            sort_keys=True,
        ).encode(),
        "model.safetensors.index.json": json.dumps(
            {"metadata": {"total_size": 4}, "weight_map": {"weight": "model.safetensors"}},
            sort_keys=True,
        ).encode(),
        "model.safetensors": safetensor({"weight": b"data"}),
    }
    entries = []
    for name, data in contents.items():
        digest = hashlib.sha256(data).hexdigest()
        (blobs / digest).write_bytes(data)
        (blobs / digest).chmod(0o644)
        target = f"../../blobs/{digest}"
        (snapshot / name).symlink_to(target)
        entries.append(
            {
                "path": name,
                "type": "symlink",
                "target": target,
                "blob": digest,
                "size": len(data),
                "sha256": digest,
                "mode": 0o644,
            }
        )
    lock = {
        "schema_version": 1,
        "artifacts": {
            "fixture": {
                "kind": "huggingface_snapshot",
                "provenance": {
                    "repository": repository,
                    "revision": revision,
                    "source_url": f"https://huggingface.co/{repository}",
                    "cache_layout": "huggingface_hub_v1",
                },
                "tree": {"directories": [], "files": entries},
                "semantics": {
                    "type": "indexed_safetensors_model",
                    "config_path": "config.json",
                    "index_path": "model.safetensors.index.json",
                    "expected_config": {
                        "architectures": ["TestForGeneration"],
                        "model_type": "test",
                        "quantization_config.quant_method": "fp8",
                    },
                    "metadata_total_size": 4,
                    "weight_count": 1,
                    "shard_count": 1,
                },
            }
        },
    }
    return lock, snapshot, repo_root


def verify_hf(lock: dict[str, Any], snapshot: Path, repo_root: Path) -> None:
    artifacts.verify_hf_snapshot(
        lock,
        "fixture",
        snapshot,
        repo_root,
        "Acme/Test-FP8",
        "a" * 40,
    )


def replace_locked_symlink(
    lock: dict[str, Any], snapshot: Path, repo_root: Path, name: str, data: bytes
) -> None:
    digest = hashlib.sha256(data).hexdigest()
    (repo_root / "blobs" / digest).write_bytes(data)
    (repo_root / "blobs" / digest).chmod(0o644)
    path = snapshot / name
    path.unlink()
    path.symlink_to(f"../../blobs/{digest}")
    entry = next(item for item in lock["artifacts"]["fixture"]["tree"]["files"] if item["path"] == name)
    entry.update(
        {
            "target": f"../../blobs/{digest}",
            "blob": digest,
            "size": len(data),
            "sha256": digest,
        }
    )


def test_hf_snapshot_accepts_exact_tree_and_index(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    verify_hf(lock, snapshot, repo_root)


@pytest.mark.parametrize("operation", ["extra", "missing", "tamper"])
def test_hf_snapshot_rejects_membership_and_digest_changes(tmp_path: Path, operation: str) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    if operation == "extra":
        (snapshot / "extra.json").symlink_to("../../blobs/" + "0" * 64)
    elif operation == "missing":
        (snapshot / "config.json").unlink()
    else:
        entry = next(
            item
            for item in lock["artifacts"]["fixture"]["tree"]["files"]
            if item["path"] == "model.safetensors"
        )
        (repo_root / "blobs" / entry["blob"]).write_bytes(b"changed")
    with pytest.raises(artifacts.VerificationError):
        verify_hf(lock, snapshot, repo_root)


def test_hf_snapshot_rejects_escape_even_when_lock_names_it(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    outside_name = "b" * 64
    outside = tmp_path / outside_name
    outside.write_bytes(b"outside")
    path = snapshot / "config.json"
    path.unlink()
    path.symlink_to(f"../../../{outside_name}")
    entry = next(
        item
        for item in lock["artifacts"]["fixture"]["tree"]["files"]
        if item["path"] == "config.json"
    )
    entry.update(
        {
            "target": f"../../../{outside_name}",
            "blob": outside_name,
            "size": 7,
            "sha256": hashlib.sha256(b"outside").hexdigest(),
        }
    )
    with pytest.raises(artifacts.VerificationError, match="canonical|escapes"):
        verify_hf(lock, snapshot, repo_root)


def test_hf_snapshot_rejects_regular_file_substitution(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    path = snapshot / "config.json"
    data = path.read_bytes()
    path.unlink()
    path.write_bytes(data)
    with pytest.raises(artifacts.VerificationError, match="locked symlink"):
        verify_hf(lock, snapshot, repo_root)


def test_config_semantics_survive_an_attacker_updating_the_digest(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    replacement = json.dumps(
        {
            "architectures": ["WrongArchitecture"],
            "model_type": "test",
            "quantization_config": {"quant_method": "fp8"},
        },
        sort_keys=True,
    ).encode()
    replace_locked_symlink(lock, snapshot, repo_root, "config.json", replacement)
    with pytest.raises(artifacts.VerificationError, match="config semantic"):
        verify_hf(lock, snapshot, repo_root)


def test_duplicate_config_keys_are_rejected_after_relocking(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    replacement = b'{"architectures":["TestForGeneration"],"model_type":"test","model_type":"test","quantization_config":{"quant_method":"fp8"}}'
    replace_locked_symlink(lock, snapshot, repo_root, "config.json", replacement)
    with pytest.raises(artifacts.VerificationError, match="duplicate JSON key"):
        verify_hf(lock, snapshot, repo_root)


def test_index_cannot_name_an_unstaged_shard_after_relocking(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    replacement = json.dumps(
        {"metadata": {"total_size": 4}, "weight_map": {"weight": "ghost.safetensors"}},
        sort_keys=True,
    ).encode()
    replace_locked_symlink(lock, snapshot, repo_root, "model.safetensors.index.json", replacement)
    with pytest.raises(artifacts.VerificationError, match="shard membership"):
        verify_hf(lock, snapshot, repo_root)


def test_safetensors_header_must_agree_with_index_after_relocking(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    replace_locked_symlink(
        lock,
        snapshot,
        repo_root,
        "model.safetensors",
        safetensor({"different_weight": b"data"}),
    )
    with pytest.raises(artifacts.VerificationError, match="maps tensor|membership differs"):
        verify_hf(lock, snapshot, repo_root)


def test_non_authoritative_zero_index_total_keeps_all_other_checks(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    replacement = json.dumps(
        {"metadata": {"total_size": 0}, "weight_map": {"weight": "model.safetensors"}},
        sort_keys=True,
    ).encode()
    replace_locked_symlink(lock, snapshot, repo_root, "model.safetensors.index.json", replacement)
    semantics = lock["artifacts"]["fixture"]["semantics"]
    semantics["metadata_total_size"] = 0
    semantics["metadata_total_size_authoritative"] = False
    verify_hf(lock, snapshot, repo_root)

    semantics["metadata_total_size_authoritative"] = True
    with pytest.raises(artifacts.VerificationError, match="tensor bytes"):
        verify_hf(lock, snapshot, repo_root)


def test_single_safetensors_semantics_are_content_and_shape_locked(tmp_path: Path) -> None:
    lock, snapshot, repo_root = hf_fixture(tmp_path)
    (snapshot / "model.safetensors.index.json").unlink()
    lock["artifacts"]["fixture"]["tree"]["files"] = [
        entry
        for entry in lock["artifacts"]["fixture"]["tree"]["files"]
        if entry["path"] != "model.safetensors.index.json"
    ]
    lock["artifacts"]["fixture"]["semantics"] = {
        "type": "single_safetensors_model",
        "config_path": "config.json",
        "weight_path": "model.safetensors",
        "expected_config": {
            "architectures": ["TestForGeneration"],
            "model_type": "test",
            "quantization_config.quant_method": "fp8",
        },
        "weight_count": 1,
        "tensor_bytes": 4,
    }
    verify_hf(lock, snapshot, repo_root)
    lock["artifacts"]["fixture"]["semantics"]["weight_count"] = 2
    with pytest.raises(artifacts.VerificationError, match="tensor count"):
        verify_hf(lock, snapshot, repo_root)


def triton_config(batch_size: int = 8) -> bytes:
    return f'''name: "text_embeddings"
platform: "tensorrt_plan"
max_batch_size: {batch_size}
default_model_filename: "cosmos_embed1_text_NVIDIA_Thor_{batch_size}_fp16.engine"
input [{{ name: "input_ids" data_type: TYPE_INT64 dims: [ -1 ] }}]
output [{{ name: "text_embeddings" data_type: TYPE_FP32 dims: [768] }}]
instance_group [{{ kind: KIND_GPU count: 1 }}]
'''.encode()


def tar_bytes(
    root: str,
    files: dict[str, tuple[bytes, int]],
    directories: list[str],
    *,
    extra_members: list[tarfile.TarInfo] | None = None,
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        root_info = tarfile.TarInfo(root)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        archive.addfile(root_info)
        for directory in directories:
            info = tarfile.TarInfo(f"{root}/{directory}")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            info.mode = mode
            archive.addfile(info, io.BytesIO(data))
        for info in extra_members or []:
            archive.addfile(info, io.BytesIO(b"x") if info.isfile() else None)
    return output.getvalue()


def triton_fixture() -> tuple[dict[str, Any], bytes, str, dict[str, tuple[bytes, int]], list[str]]:
    root = "cosmos-embed1-448p-anomaly-detection"
    engine_name = "cosmos_embed1_text_NVIDIA_Thor_8_fp16.engine"
    files = {
        "text_embeddings/config.pbtxt": (triton_config(), 0o755),
        f"text_embeddings/1/{engine_name}": (b"locked-engine", 0o644),
    }
    directories = ["text_embeddings", "text_embeddings/1"]
    tree_files = [
        {
            "path": name,
            "type": "file",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "mode": mode,
        }
        for name, (data, mode) in files.items()
    ]
    lock = {
        "schema_version": 1,
        "artifacts": {
            "source": {"kind": "unused", "provenance": {"revision": "c" * 40}},
            "triton": {
                "kind": "docker_volume_tree",
                "archive_root": root,
                "provenance": {
                    "source_spec": "git:https://example.test/model",
                    "service_image": "example.test/embed:1",
                    "container_path": "/cache/model",
                    "derived_from_artifact": "source",
                    "derived_from_revision": "c" * 40,
                },
                "tree": {"directories": directories, "files": tree_files},
                "semantics": {
                    "type": "triton_tensorrt_repository",
                    "models": [
                        {
                            "name": "text_embeddings",
                            "config_path": "text_embeddings/config.pbtxt",
                            "default_model_filename": engine_name,
                            "required_tokens": [
                                'name: "input_ids"',
                                "TYPE_INT64",
                                'name: "text_embeddings"',
                                "TYPE_FP32",
                                "dims: [768]",
                                "KIND_GPU",
                            ],
                        }
                    ],
                },
            },
        },
    }
    return lock, tar_bytes(root, files, directories), root, files, directories


def verify_triton(lock: dict[str, Any], archive: bytes, batch_size: int = 8) -> None:
    artifacts.verify_tar_tree(
        lock,
        "triton",
        io.BytesIO(archive),
        source_spec="git:https://example.test/model",
        image="example.test/embed:1",
        container_path="/cache/model",
        batch_size=batch_size,
    )


def test_tar_tree_accepts_exact_membership_and_thor_semantics() -> None:
    lock, archive, _, _, _ = triton_fixture()
    verify_triton(lock, archive)


@pytest.mark.parametrize("operation", ["missing", "extra", "tamper", "mode"])
def test_tar_tree_rejects_membership_hash_and_mode_changes(operation: str) -> None:
    lock, _, root, original, directories = triton_fixture()
    files = copy.deepcopy(original)
    if operation == "missing":
        files.pop("text_embeddings/config.pbtxt")
    elif operation == "extra":
        files["unexpected"] = (b"unexpected", 0o644)
    elif operation == "tamper":
        files["text_embeddings/1/cosmos_embed1_text_NVIDIA_Thor_8_fp16.engine"] = (
            b"tampered",
            0o644,
        )
    else:
        data, _ = files["text_embeddings/config.pbtxt"]
        files["text_embeddings/config.pbtxt"] = (data, 0o644)
    with pytest.raises(artifacts.VerificationError):
        verify_triton(lock, tar_bytes(root, files, directories))


@pytest.mark.parametrize("kind", ["symlink", "traversal", "duplicate"])
def test_tar_tree_rejects_unsafe_or_duplicate_members(kind: str) -> None:
    lock, _, root, files, directories = triton_fixture()
    info = tarfile.TarInfo()
    if kind == "symlink":
        info.name = f"{root}/link"
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
    elif kind == "traversal":
        info.name = f"{root}/../escape"
        info.size = 1
    else:
        info.name = f"{root}/text_embeddings/config.pbtxt"
        info.size = 1
    with pytest.raises(artifacts.VerificationError):
        verify_triton(lock, tar_bytes(root, files, directories, extra_members=[info]))


def test_triton_batch_semantics_reject_relocked_wrong_config() -> None:
    lock, _, root, files, directories = triton_fixture()
    wrong = triton_config(64)
    files["text_embeddings/config.pbtxt"] = (wrong, 0o755)
    entry = next(
        item
        for item in lock["artifacts"]["triton"]["tree"]["files"]
        if item["path"] == "text_embeddings/config.pbtxt"
    )
    entry.update({"size": len(wrong), "sha256": hashlib.sha256(wrong).hexdigest()})
    with pytest.raises(artifacts.VerificationError, match="max_batch_size"):
        verify_triton(lock, tar_bytes(root, files, directories), batch_size=8)


def test_triton_derived_revision_must_match_source_lock() -> None:
    lock, archive, _, _, _ = triton_fixture()
    lock["artifacts"]["triton"]["provenance"]["derived_from_revision"] = "d" * 40
    with pytest.raises(artifacts.VerificationError, match="provenance"):
        verify_triton(lock, archive)


def test_provenance_arguments_are_fail_closed() -> None:
    lock, archive, _, _, _ = triton_fixture()
    with pytest.raises(artifacts.VerificationError, match="service_image"):
        artifacts.verify_tar_tree(
            lock,
            "triton",
            io.BytesIO(archive),
            source_spec="git:https://example.test/model",
            image="example.test/embed:latest",
            container_path="/cache/model",
            batch_size=8,
        )
