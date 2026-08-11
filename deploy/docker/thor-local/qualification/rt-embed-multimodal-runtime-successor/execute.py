#!/usr/bin/env python3
"""Bounded local video/image/text embedding proof for RT-Embed on Thor."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import requests


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
PAUSED_WORKLOADS = (
    "datasheet-vllm-30",
    "datasheet-embedding",
    "ctai-vision-playground-api",
)


class QualificationError(RuntimeError):
    """A bounded qualification assertion failed."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(),
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON source: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _verify_regular(path: Path, expected_bytes: int, expected_sha: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"source is not a regular file: {path}")
    raw = path.read_bytes()
    if len(raw) != expected_bytes or _sha(raw) != expected_sha:
        raise QualificationError(f"source lock drifted: {path}")


def _verify_static(contract: dict[str, Any]) -> None:
    if contract["official_indices"] != [368, 371]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        _verify_regular(REPO / lock["path"], lock["bytes"], lock["sha256"])
    for fixture in contract["fixtures"].values():
        if isinstance(fixture, dict) and "path" in fixture:
            _verify_regular(REPO / fixture["path"], fixture["bytes"], fixture["sha256"])
    ledger = _load(REPO / contract["source_locks"][-1]["path"])
    expected = (
        (368, "video/image/text embedding"),
        (371, "Cosmos-Embed1"),
    )
    for index, literal in expected:
        row = ledger["capabilities"][index]
        if (
            row.get("id") not in contract["capability_ids"]
            or row.get("title") != literal
            or row.get("acceptance_class") != "required_local"
            or row.get("contract", {}).get("advertised_literal") != literal
        ):
            raise QualificationError(f"advertised capability row drifted: {index}")
    origin = urlsplit(contract["runtime"]["origin"])
    if (
        origin.scheme != "http"
        or origin.hostname != "127.0.0.1"
        or origin.port != 8017
        or origin.path not in ("", "/")
    ):
        raise QualificationError("runtime origin is not exact numeric loopback")
    if shutil.disk_usage(REPO).free < contract["execution"]["min_free_bytes"]:
        raise QualificationError("free-space safety floor is not met")


def _docker(
    args: list[str], counter: list[int], *, timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    counter[0] += 1
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            check=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("bounded Docker command failed") from exc


def _inspect(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    names = [contract["runtime"]["container"], *PAUSED_WORKLOADS]
    try:
        rows = json.loads(_docker(["inspect", *names], counter).stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("Docker inspect output was invalid") from exc
    by_name = {row.get("Name", "").lstrip("/"): row for row in rows}
    runtime = contract["runtime"]
    row = by_name.get(runtime["container"], {})
    state = row.get("State", {})
    if (
        row.get("Image") != runtime["image_id"]
        or state.get("Status") != "running"
        or state.get("Health", {}).get("Status") != "healthy"
        or state.get("OOMKilled") is not False
        or row.get("RestartCount") != 0
    ):
        raise QualificationError("RT-Embed runtime identity drifted")
    bindings = row.get("HostConfig", {}).get("PortBindings", {}).get("8000/tcp")
    if bindings != [{"HostIp": "127.0.0.1", "HostPort": "8017"}]:
        raise QualificationError("RT-Embed is not published on exact loopback")
    env = {}
    for item in row.get("Config", {}).get("Env", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    if {
        "MODEL_PATH": env.get("MODEL_PATH"),
        "VLM_BATCH_SIZE": env.get("VLM_BATCH_SIZE"),
        "RTVI_OFFLINE": env.get("RTVI_OFFLINE"),
        "HF_HUB_OFFLINE": env.get("HF_HUB_OFFLINE"),
        "TRANSFORMERS_OFFLINE": env.get("TRANSFORMERS_OFFLINE"),
    } != {
        "MODEL_PATH": runtime["model_source"],
        "VLM_BATCH_SIZE": str(runtime["batch_size"]),
        "RTVI_OFFLINE": "true",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }:
        raise QualificationError("RT-Embed safe model environment drifted")
    if any(
        env.get(name, "")
        for name in ("NGC_CLI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN")
    ):
        raise QualificationError("RT-Embed container unexpectedly retains credentials")
    paused = {}
    for name in PAUSED_WORKLOADS:
        paused_row = by_name.get(name)
        if not isinstance(paused_row, dict):
            raise QualificationError(f"operator-paused workload missing: {name}")
        paused_state = paused_row.get("State", {}).get("Status")
        if paused_state == "running":
            raise QualificationError(f"operator-paused workload restarted: {name}")
        paused[name] = {
            "container_id": paused_row.get("Id"),
            "status": paused_state,
        }
    return {
        "container_id": row.get("Id"),
        "image_id": row.get("Image"),
        "started_at": state.get("StartedAt"),
        "health": state.get("Health", {}).get("Status"),
        "restart_count": row.get("RestartCount"),
        "oom_killed": state.get("OOMKilled"),
        "loopback_binding": bindings,
        "safe_model_environment_exact": True,
        "credentials_blank": True,
        "paused_workloads": paused,
    }


def _verify_live_sources(contract: dict[str, Any], counter: list[int]) -> None:
    locks = [lock for lock in contract["source_locks"] if "container_path" in lock]
    output = _docker(
        [
            "exec",
            contract["runtime"]["container"],
            "sha256sum",
            *[lock["container_path"] for lock in locks],
        ],
        counter,
    ).stdout.decode()
    observed = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 2:
            observed[fields[1]] = fields[0]
    if observed != {lock["container_path"]: lock["sha256"] for lock in locks}:
        raise QualificationError("live RT-Embed production source drifted")


class Client:
    def __init__(self, contract: dict[str, Any]) -> None:
        self.contract = contract
        self.origin = contract["runtime"]["origin"].rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        self.requests = 0

    def close(self) -> None:
        self.session.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float = 20,
    ) -> tuple[int, Any]:
        if not path.startswith("/v1/") or ".." in path:
            raise QualificationError("HTTP path left the frozen API scope")
        self.requests += 1
        if self.requests > self.contract["execution"]["max_http_requests"]:
            raise QualificationError("HTTP request budget exceeded")
        if json_body is not None:
            raw_request = json.dumps(json_body, allow_nan=False).encode()
            if len(raw_request) > self.contract["execution"]["max_request_bytes"]:
                raise QualificationError("JSON request budget exceeded")
        try:
            response = self.session.request(
                method,
                self.origin + path,
                json=json_body,
                data=data,
                files=files,
                timeout=(5, timeout),
                allow_redirects=False,
                stream=True,
            )
            raw = bytearray()
            maximum = self.contract["execution"]["max_response_bytes"]
            for block in response.iter_content(65536):
                raw.extend(block)
                if len(raw) > maximum:
                    raise QualificationError("HTTP response budget exceeded")
        except requests.RequestException as exc:
            raise QualificationError("loopback HTTP request failed") from exc
        if not raw:
            return response.status_code, None
        try:
            value = json.loads(
                bytes(raw),
                object_pairs_hook=_reject_duplicates,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    QualificationError(f"non-finite HTTP JSON value: {value}")
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QualificationError("RT-Embed response was not strict JSON") from exc
        return response.status_code, value


def _uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise QualificationError("RT-Embed response omitted a UUID")
    try:
        UUID(value)
    except ValueError as exc:
        raise QualificationError("RT-Embed response UUID was invalid") from exc
    return value


def _vector(value: Any, dimension: int) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != dimension
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise QualificationError("embedding vector shape differed")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise QualificationError("embedding vector was non-finite")
    if math.sqrt(sum(item * item for item in result)) <= 1e-6:
        raise QualificationError("embedding vector was zero")
    return result


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    result = numerator / (left_norm * right_norm)
    if not math.isfinite(result) or not -1.000001 <= result <= 1.000001:
        raise QualificationError("cross-modal cosine was invalid")
    return result


def _require(status: int, expected: int, value: Any, label: str) -> dict[str, Any]:
    if status != expected or not isinstance(value, dict):
        raise QualificationError(f"{label} response contract differed")
    return value


def _validate_text(
    value: dict[str, Any], contract: dict[str, Any]
) -> tuple[list[float], dict[str, Any]]:
    runtime = contract["runtime"]
    _uuid(value.get("id"))
    rows = value.get("data")
    if (
        value.get("model") != runtime["model_id"]
        or not isinstance(value.get("created"), int)
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("text_input") != contract["fixtures"]["text_marker"]
    ):
        raise QualificationError("text embedding envelope differed")
    vector = _vector(rows[0].get("embeddings"), runtime["embedding_dimension"])
    return vector, {
        "http_status": 200,
        "input_count": 1,
        "response_count": 1,
        "model_exact": True,
        "query_id_valid": True,
        "input_echo_exact": True,
        "vector_dimension": len(vector),
        "vector_finite": True,
        "vector_nonzero": True,
    }


def _validate_media(
    value: dict[str, Any], contract: dict[str, Any], expected_chunks: int
) -> tuple[list[list[float]], dict[str, Any]]:
    runtime = contract["runtime"]
    _uuid(value.get("id"))
    chunks = value.get("chunk_responses")
    media_info = value.get("media_info")
    if (
        value.get("model") != runtime["model_id"]
        or not isinstance(value.get("created"), int)
        or not isinstance(media_info, dict)
        or media_info.get("type") != "offset"
        or not isinstance(chunks, list)
        or len(chunks) != expected_chunks
    ):
        raise QualificationError("media embedding envelope differed")
    vectors = []
    chronological = True
    prior_end = -math.inf
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise QualificationError("media embedding chunk differed")
        try:
            start = float(chunk["start_time"])
            end = float(chunk["end_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QualificationError("media embedding timestamps differed") from exc
        chronological &= start >= prior_end and end >= start
        prior_end = end
        vectors.append(_vector(chunk.get("embeddings"), runtime["embedding_dimension"]))
    if not chronological:
        raise QualificationError("media embedding chunks were not chronological")
    return vectors, {
        "http_status": 200,
        "query_id_valid": True,
        "model_exact": True,
        "media_info_offset": True,
        "chunk_count": len(chunks),
        "vectors_dimension": runtime["embedding_dimension"],
        "vectors_finite": True,
        "vectors_nonzero": True,
        "chunks_chronological": True,
    }


def _catalog(client: Client) -> dict[str, Any]:
    status, value = client.request("GET", "/v1/files?purpose=vision")
    return _require(status, 200, value, "file catalog")


def _stats(client: Client) -> dict[str, Any]:
    status, value = client.request("GET", "/v1/assets/stats")
    return _require(status, 200, value, "asset statistics")


def _upload(
    client: Client, contract: dict[str, Any], fixture: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    path = REPO / fixture["path"]
    with path.open("rb") as handle:
        status, value = client.request(
            "POST",
            "/v1/files",
            data={"purpose": "vision", "media_type": fixture["media_type"]},
            files={"file": (path.name, handle, fixture["mime_type"])},
            timeout=30,
        )
    row = _require(status, 200, value, f"{fixture['media_type']} upload")
    file_id = _uuid(row.get("id"))
    if (
        row.get("bytes") != fixture["bytes"]
        or row.get("media_type") != fixture["media_type"]
        or row.get("purpose") != "vision"
    ):
        raise QualificationError(f"{fixture['media_type']} upload metadata differed")
    return file_id, {
        "http_status": 200,
        "stable_file_identity_returned": True,
        "bytes_exact": True,
        "media_type_exact": True,
        "purpose_exact": True,
    }


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "status": "inert_rt_embed_multimodal_plan_valid",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "http_requests": 0,
        "model_requests": 0,
        "docker_commands": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    docker_counter = [0]
    identity_before = _inspect(contract, docker_counter)
    _verify_live_sources(contract, docker_counter)
    client = Client(contract)
    owned_ids: list[str] = []
    cleanup_ok = False
    try:
        ready_status, ready_value = client.request("GET", "/v1/ready?detailed=true")
        ready = _require(ready_status, 200, ready_value, "readiness")
        if ready.get("healthy") is not True:
            raise QualificationError("RT-Embed was not ready")
        model_status, model_value = client.request("GET", "/v1/models")
        models = _require(model_status, 200, model_value, "models")
        model_rows = models.get("data")
        if (
            not isinstance(model_rows, list)
            or len(model_rows) != 1
            or model_rows[0].get("id") != contract["runtime"]["model_id"]
            or models.get("audio_support") is not False
        ):
            raise QualificationError("loaded Cosmos-Embed1 model identity differed")
        manifest_status, manifest_value = client.request("GET", "/v1/manifest")
        manifest = _require(manifest_status, 200, manifest_value, "manifest")
        if manifest != {
            "version": contract["runtime"]["release"],
            "model": contract["runtime"]["model_id"],
        }:
            raise QualificationError("RT-Embed manifest identity differed")
        catalog_before = _catalog(client)
        stats_before = _stats(client)

        text_status, text_value = client.request(
            "POST",
            "/v1/generate_text_embeddings",
            json_body={
                "text_input": contract["fixtures"]["text_marker"],
                "model": contract["runtime"]["model_id"],
            },
            timeout=180,
        )
        text_vector, text_proof = _validate_text(
            _require(text_status, 200, text_value, "text embedding"), contract
        )

        image_id, image_upload = _upload(client, contract, contract["fixtures"]["image"])
        owned_ids.append(image_id)
        image_status, image_value = client.request(
            "POST",
            "/v1/generate_video_embeddings",
            json_body={"id": image_id, "model": contract["runtime"]["model_id"]},
            timeout=180,
        )
        image_vectors, image_proof = _validate_media(
            _require(image_status, 200, image_value, "image embedding"), contract, 1
        )

        video_id, video_upload = _upload(client, contract, contract["fixtures"]["video"])
        owned_ids.append(video_id)
        video_status, video_value = client.request(
            "POST",
            "/v1/generate_video_embeddings",
            json_body={
                "id": video_id,
                "model": contract["runtime"]["model_id"],
                "chunk_duration": contract["fixtures"]["video"]["chunk_duration_seconds"],
                "chunk_overlap_duration": 0,
            },
            timeout=180,
        )
        video_vectors, video_proof = _validate_media(
            _require(video_status, 200, video_value, "video embedding"),
            contract,
            contract["fixtures"]["video"]["expected_chunk_count"],
        )

        for file_id in reversed(owned_ids):
            status, value = client.request("DELETE", f"/v1/files/{file_id}")
            _require(status, 200, value, "owned file delete")
        owned_ids.clear()
        catalog_after = _catalog(client)
        stats_after = _stats(client)
        final_ready_status, final_ready_value = client.request(
            "GET", "/v1/ready?detailed=true"
        )
        final_ready = _require(final_ready_status, 200, final_ready_value, "final readiness")
        final_models_status, final_models_value = client.request("GET", "/v1/models")
        final_models = _require(final_models_status, 200, final_models_value, "final models")
        if (
            catalog_after != catalog_before
            or stats_after != stats_before
            or final_ready.get("healthy") is not True
            or final_models != models
        ):
            raise QualificationError("RT-Embed state was not restored exactly")
        cleanup_ok = True
    finally:
        for file_id in reversed(owned_ids):
            try:
                client.request("DELETE", f"/v1/files/{file_id}")
            except QualificationError:
                pass
        client.close()
    if not cleanup_ok:
        raise QualificationError("owned file cleanup was incomplete")
    identity_after = _inspect(contract, docker_counter)
    if identity_after != identity_before:
        raise QualificationError("RT-Embed or paused-workload identity changed")
    if docker_counter[0] != contract["execution"]["max_docker_commands"]:
        raise QualificationError("Docker command budget was not exact")
    if client.requests != contract["execution"]["max_http_requests"]:
        raise QualificationError("HTTP request budget was not exact")
    if image_vectors[0] == text_vector or video_vectors[0] == text_vector:
        raise QualificationError("multimodal embedding vectors were unexpectedly identical")
    _cosine(text_vector, image_vectors[0])
    _cosine(text_vector, video_vectors[0])
    duration = round(time.monotonic() - started, 6)
    if duration > contract["execution"]["max_duration_seconds"]:
        raise QualificationError("qualification exceeded its duration budget")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": duration,
        "budget": {
            "http_requests": client.requests,
            "max_http_requests": contract["execution"]["max_http_requests"],
            "model_requests": 3,
            "max_model_requests": contract["execution"]["max_model_requests"],
            "docker_commands": docker_counter[0],
            "max_docker_commands": contract["execution"]["max_docker_commands"],
            "file_mutations": 4,
            "max_file_mutations": contract["execution"]["file_mutations"],
        },
        "runtime_identity": {
            "healthy": True,
            "image_exact": True,
            "restart_count": 0,
            "oom_killed": False,
            "loopback_binding_exact": True,
            "safe_model_environment_exact": True,
            "credentials_blank": True,
            "production_sources_exact": True,
            "operator_paused_workloads_preserved": True,
        },
        "model": {
            "release_exact": True,
            "manifest_model_exact": True,
            "models_endpoint_exact": True,
            "cosmos_embed1_source_exact": True,
            "embedding_dimension": contract["runtime"]["embedding_dimension"],
            "audio_support": False,
        },
        "text_embedding": text_proof,
        "image_embedding": {"upload": image_upload, "inference": image_proof},
        "video_embedding": {
            "upload": video_upload,
            "inference": video_proof,
            "fixture_codec_h264": True,
            "fixture_duration_seconds": contract["fixtures"]["video"]["duration_seconds"],
            "chunk_duration_seconds": contract["fixtures"]["video"][
                "chunk_duration_seconds"
            ],
        },
        "multimodal_space": {
            "same_embedding_dimension": True,
            "cross_modal_cosines_finite": True,
            "modal_vectors_distinct": True,
        },
        "cleanup": {
            "owned_image_deleted": True,
            "owned_video_deleted": True,
            "file_catalog_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "model_catalog_preserved": True,
            "runtime_identity_preserved": True,
        },
        "policy": contract["policy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode")
    subparsers.add_parser("plan")
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--ack", required=True)
    args = parser.parse_args()
    contract = _load(CONTRACT_PATH)
    try:
        if (args.mode or "plan") == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "package_id": contract.get("package_id"),
                    "status": "failed",
                    "failure": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
