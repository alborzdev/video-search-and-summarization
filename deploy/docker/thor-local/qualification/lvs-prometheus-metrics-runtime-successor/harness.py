#!/usr/bin/env python3
"""Qualify LVS Prometheus metrics around one bounded successful file request."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import re
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from prometheus_client.parser import text_string_to_metric_families


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
LVS = "http://127.0.0.1:38111"
NEO4J_HOST = "127.0.0.1"
NEO4J_PORT = 7474
FILE_ID = "30430430-aaaa-4bbb-8ccc-304304304304"
FILENAME = "thor-row304-prometheus-metrics.mp4"
SENSOR_NAME = "thor-row304-prometheus-metrics"
FIXTURE = REPO / "services/alert/warmup/test.mp4"
MINIMUM_FREE_BYTES = 10 * 1024**3
MODEL = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
PROMPT = "Describe visible activity concisely."
COUNT_SERIES = [
    "vlm_latency_seconds_count",
    "vlm_input_tokens_per_chunk_count",
    "vlm_output_tokens_per_chunk_count",
    "vlm_queue_time_seconds_count",
    "vlm_chunk_total_latency_seconds_count",
    "vlm_frames_per_chunk_count",
]
FORBIDDEN_LABELS = {
    "asset_id", "candidate_id", "camera_id", "file_id", "id", "request_id",
    "resource_id", "sensor_id", "stream_id", "video_id",
}
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class QualificationError(RuntimeError):
    """The bounded metrics proof failed."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], check=False, capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise QualificationError(f"docker command failed: {result.stderr.strip()}")
    return result.stdout


def request(
    method: str,
    path: str,
    body: Any | bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 240,
) -> tuple[int, Any, bytes, dict[str, str]]:
    if isinstance(body, bytes) or body is None:
        payload = body
    else:
        payload = canonical(body)
    req = urllib.request.Request(
        LVS + path,
        data=payload,
        method=method,
        headers={"Content-Type": content_type, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(8 * 1024**2 + 1)
            status = response.status
            headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raw = exc.read(8 * 1024**2 + 1)
        status = exc.code
        headers = {key.lower(): value for key, value in exc.headers.items()}
    if len(raw) > 8 * 1024**2:
        raise QualificationError("HTTP response exceeded bound")
    if path == "/metrics":
        parsed: Any = raw.decode("utf-8")
    elif raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QualificationError(f"non-JSON response from {method} {path}") from exc
    else:
        parsed = None
    return status, parsed, raw, headers


def files() -> dict[str, Any]:
    status, value, _, _ = request("GET", "/files?purpose=vision")
    if status != 200 or value.get("object") != "list" or not isinstance(value.get("data"), list):
        raise QualificationError("LVS file catalog is unavailable")
    return value


def multipart(media: bytes) -> tuple[bytes, str]:
    boundary = "thor-row304-prometheus-boundary"
    pieces: list[bytes] = []
    for key, value in {
        "purpose": "vision",
        "media_type": "video",
        "id": FILE_ID,
        "sensor_name": SENSOR_NAME,
    }.items():
        pieces.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            value.encode(), b"\r\n",
        ])
    pieces.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{FILENAME}"\r\n'.encode(),
        b"Content-Type: video/mp4\r\n\r\n", media, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(pieces), f"multipart/form-data; boundary={boundary}"


def metric_snapshot(text: str) -> dict[str, Any]:
    families = list(text_string_to_metric_families(text))
    if not families:
        raise QualificationError("Prometheus parser returned no metric families")
    samples: dict[str, float] = {}
    label_names: set[str] = set()
    for family in families:
        for sample in family.samples:
            label_names.update(sample.labels)
            if not sample.labels:
                samples[sample.name] = float(sample.value)
    required = ["video_file_queries_processed", "video_file_queries_pending", *COUNT_SERIES]
    if any(name not in samples for name in required):
        raise QualificationError("required LVS metric sample is absent")
    return {
        "family_count": len(families),
        "sample_count": sum(len(family.samples) for family in families),
        "label_names": sorted(label_names),
        "values": {name: samples[name] for name in required},
        "latest": {
            name: samples.get(name)
            for name in (
                "e2e_latency_seconds_latest",
                "vlm_pipeline_latency_seconds_latest",
                "vlm_latency_seconds_latest",
            )
        },
    }


def graph_password() -> str:
    path = REPO / "deploy/docker/thor-local/generated.env"
    if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise QualificationError("protected graph environment is invalid")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key in values:
                raise QualificationError("duplicate graph environment key")
            values[key] = value
    value = values.get("GRAPH_DB_PASSWORD", "")
    if len(value) < 16:
        raise QualificationError("graph password is unavailable")
    return value


def graph_query(password: str, statement: str, parameters: dict[str, Any]) -> list[list[Any]]:
    auth = base64.b64encode(f"neo4j:{password}".encode()).decode()
    payload = canonical({"statements": [{"statement": statement, "parameters": parameters}]})
    connection = http.client.HTTPConnection(NEO4J_HOST, NEO4J_PORT, timeout=30)
    try:
        connection.request(
            "POST", "/db/neo4j/tx/commit", body=payload,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read(2 * 1024**2)
    finally:
        connection.close()
    value = json.loads(raw)
    if response.status != 200 or value.get("errors"):
        raise QualificationError("graph query failed")
    return [item["row"] for item in value["results"][0]["data"]]


def graph_snapshot(password: str) -> dict[str, int]:
    rows = graph_query(
        password,
        "MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[r]->() RETURN nodes, count(r)",
        {},
    )
    if len(rows) != 1 or len(rows[0]) != 2:
        raise QualificationError("invalid graph snapshot")
    return {"nodes": rows[0][0], "relationships": rows[0][1]}


def graph_owned_count(password: str) -> int:
    rows = graph_query(
        password,
        "MATCH (n) WHERE n.uuid = $asset_id RETURN count(n)",
        {"asset_id": FILE_ID},
    )
    return rows[0][0]


def runtime_snapshot() -> dict[str, Any]:
    value = json.loads(docker("inspect", "vss-lvs"))[0]
    state = value["State"]
    return {
        "container": "vss-lvs",
        "image_id": value["Image"],
        "image_name": value["Config"]["Image"],
        "healthy": state["Health"]["Status"] == "healthy",
        "restart_count": value["RestartCount"],
        "oom_killed": state["OOMKilled"],
        "started_at_sha256": sha_bytes(state["StartedAt"].encode()),
    }


def running_containers() -> list[str]:
    return sorted(docker("ps", "--format", "{{.Names}}").splitlines())


def live_sha(path: str) -> str:
    code = "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())"
    return docker("exec", "vss-lvs", "python3", "-c", code, path).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", required=True)
    parser.add_argument("--output", type=Path, default=RECEIPT_PATH)
    args = parser.parse_args()
    expected_ack = "I_ACK_ONE_OWNED_LVS_FILE_AND_ONE_LOCAL_VLM_CAPTION_REQUEST"
    if args.ack != expected_ack:
        raise QualificationError(f"acknowledgement must equal {expected_ack}")
    started = time.monotonic()
    free_before = shutil.disk_usage(REPO).free
    if free_before < MINIMUM_FREE_BYTES:
        raise QualificationError("free-space safety floor is not met")
    before_files = files()
    if any(
        item.get("id") == FILE_ID or item.get("filename") == FILENAME
        for item in before_files["data"]
    ):
        raise QualificationError("owned LVS fixture already exists")
    password = graph_password()
    before_graph = graph_snapshot(password)
    if graph_owned_count(password):
        raise QualificationError("owned graph identity already exists")
    before_runtime = runtime_snapshot()
    before_running = running_containers()
    if not before_runtime["healthy"] or before_runtime["oom_killed"]:
        raise QualificationError("LVS runtime is not healthy")

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for lock in contract["source_locks"]:
        if sha_file(REPO / lock["path"]) != lock["sha256"]:
            raise QualificationError(f"host source lock drifted: {lock['path']}")
        if lock.get("container_path") and live_sha(lock["container_path"]) != lock["sha256"]:
            raise QualificationError(f"live source lock drifted: {lock['container_path']}")

    ready_status, _, _, _ = request("GET", "/v1/ready")
    models_status, models, _, _ = request("GET", "/models")
    if ready_status != 200 or models_status != 200:
        raise QualificationError("LVS is not ready")
    if [item.get("id") for item in models.get("data", [])] != [MODEL]:
        raise QualificationError("unexpected LVS model identity")

    metrics_status, before_text, before_raw, before_headers = request("GET", "/metrics")
    before_metrics = metric_snapshot(before_text)
    if metrics_status != 200 or not before_headers.get("content-type", "").startswith("text/plain"):
        raise QualificationError("LVS metrics route contract failed")
    if FORBIDDEN_LABELS.intersection(before_metrics["label_names"]):
        raise QualificationError("high-cardinality resource label found before request")

    file_added = False
    delete_status = 0
    cleanup_failures: list[str] = []
    caption_status = 0
    response_hash = ""
    chunk_count = 0
    try:
        upload_body, upload_type = multipart(FIXTURE.read_bytes())
        upload_status, uploaded, _, _ = request(
            "POST", "/files", upload_body, upload_type, timeout=60
        )
        if (
            upload_status != 200
            or uploaded.get("id") != FILE_ID
            or uploaded.get("filename") != FILENAME
            or uploaded.get("sensor_name") != SENSOR_NAME
        ):
            raise QualificationError("owned file upload failed")
        file_added = True
        caption_request = {
            "id": FILE_ID,
            "model": MODEL,
            "prompt": PROMPT,
            "chunk_duration": 0,
            "max_tokens": 96,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 1,
        }
        caption_status, caption, caption_raw, _ = request(
            "POST", "/generate_vlm_captions", caption_request, timeout=240
        )
        chunks = caption.get("chunk_responses", []) if isinstance(caption, dict) else []
        if (
            caption_status != 200
            or caption.get("model") != MODEL
            or len(chunks) != 1
            or not isinstance(chunks[0].get("content"), str)
            or not chunks[0]["content"].strip()
        ):
            raise QualificationError("bounded successful LVS request failed")
        response_hash = sha_bytes(caption_raw)
        chunk_count = len(chunks)
    finally:
        if file_added:
            try:
                delete_status, deleted, _, _ = request(
                    "DELETE", f"/files/{urllib.parse.quote(FILE_ID, safe='')}", timeout=120
                )
                if delete_status != 200 or deleted.get("deleted") is not True:
                    cleanup_failures.append("owned file deletion failed")
                else:
                    file_added = False
            except Exception as exc:
                cleanup_failures.append(f"owned file deletion: {type(exc).__name__}")

    metrics_status_after, after_text, after_raw, after_headers = request("GET", "/metrics")
    after_metrics = metric_snapshot(after_text)
    if metrics_status_after != 200 or not after_headers.get("content-type", "").startswith("text/plain"):
        raise QualificationError("post-request LVS metrics route contract failed")
    forbidden_after = sorted(FORBIDDEN_LABELS.intersection(after_metrics["label_names"]))
    if forbidden_after:
        raise QualificationError("high-cardinality resource label found after request")
    deltas = {
        name: after_metrics["values"][name] - before_metrics["values"][name]
        for name in ["video_file_queries_processed", *COUNT_SERIES]
    }
    if any(value != 1.0 for value in deltas.values()):
        raise QualificationError(f"intended metrics did not advance exactly once: {deltas}")
    if (
        before_metrics["values"]["video_file_queries_pending"] != 0.0
        or after_metrics["values"]["video_file_queries_pending"] != 0.0
    ):
        raise QualificationError("LVS pending-query gauge did not return to zero")
    if not all(
        isinstance(value, float) and value > 0
        for value in after_metrics["latest"].values()
    ):
        raise QualificationError("latest latency gauges are not positive")

    after_files = files()
    after_graph = graph_snapshot(password)
    after_runtime = runtime_snapshot()
    after_running = running_containers()
    free_after = shutil.disk_usage(REPO).free
    if cleanup_failures:
        raise QualificationError("; ".join(cleanup_failures))
    if after_files != before_files or graph_owned_count(password) != 0:
        raise QualificationError("LVS/graph owned state was not cleaned")
    if after_graph != before_graph:
        raise QualificationError("graph baseline was not restored exactly")
    if after_runtime != before_runtime or after_running != before_running:
        raise QualificationError("runtime/container baseline changed")
    if free_after < MINIMUM_FREE_BYTES:
        raise QualificationError("free-space safety floor was crossed")

    run_id = f"thor-lvs-metrics-{time.time_ns()}"
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "passed",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "contract_sha256": sha_file(CONTRACT_PATH),
        "run": {
            "id_sha256": sha_bytes(run_id.encode()),
            "duration_seconds": round(time.monotonic() - started, 6),
            "free_bytes_before": free_before,
            "free_bytes_after": free_after,
        },
        "runtime": {
            **after_runtime,
            "endpoint_loopback": True,
            "model": MODEL,
            "live_source_locks_exact": True,
        },
        "request": {
            "route": "/generate_vlm_captions",
            "http_status": caption_status,
            "model": MODEL,
            "chunk_duration": 0,
            "chunk_count": chunk_count,
            "prompt_sha256": sha_bytes(PROMPT.encode()),
            "response_sha256": response_hash,
            "response_content_nonempty": True,
        },
        "prometheus": {
            "route": "/metrics",
            "http_status_before": metrics_status,
            "http_status_after": metrics_status_after,
            "content_type_text_plain": True,
            "parser": "prometheus_client.parser.text_string_to_metric_families",
            "parseable_before": True,
            "parseable_after": True,
            "family_count_before": before_metrics["family_count"],
            "family_count_after": after_metrics["family_count"],
            "sample_count_before": before_metrics["sample_count"],
            "sample_count_after": after_metrics["sample_count"],
            "before_sha256": sha_bytes(before_raw),
            "after_sha256": sha_bytes(after_raw),
            "processed_query_delta": deltas["video_file_queries_processed"],
            "histogram_count_deltas": {name: deltas[name] for name in COUNT_SERIES},
            "pending_before": before_metrics["values"]["video_file_queries_pending"],
            "pending_after": after_metrics["values"]["video_file_queries_pending"],
            "latest_latencies_positive": True,
            "observed_label_names": after_metrics["label_names"],
            "forbidden_resource_labels": forbidden_after,
            "resource_id_cardinality_absent": True,
        },
        "cleanup": {
            "delete_status": delete_status,
            "file_catalog_before_sha256": sha_bytes(canonical(before_files)),
            "file_catalog_after_sha256": sha_bytes(canonical(after_files)),
            "file_catalog_restored_exactly": after_files == before_files,
            "graph_before": before_graph,
            "graph_after": after_graph,
            "graph_restored_exactly": after_graph == before_graph,
            "owned_graph_nodes_absent": graph_owned_count(password) == 0,
            "running_container_set_preserved": after_running == before_running,
            "runtime_state_preserved": after_runtime == before_runtime,
            "failures": cleanup_failures,
        },
        "policy": {
            "external_requests": 0,
            "agent_generate_calls": 0,
            "model_inference_requests": 1,
            "vios_or_rt_cv_stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "warehouse_sample_bundle": "excluded",
            "raw_resource_ids_retained": False,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "credentials_retained": False,
        },
    }
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if UUID_PATTERN.search(rendered):
        raise QualificationError("receipt would retain a raw UUID")
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "official_indices": receipt["official_indices"],
        "receipt_sha256": sha_file(args.output),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
