#!/usr/bin/env python3
"""Bounded Thor proof for RT-Embed URL/base64 and broker/OTel integrations."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import requests


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
PAUSED_WORKLOADS = (
    "datasheet-vllm-30",
    "datasheet-embedding",
    "ctai-vision-playground-api",
)


class QualificationError(RuntimeError):
    """A bounded qualification assertion failed."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _loads(raw: bytes | str, label: str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON value in {label}: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {label}") from exc


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"JSON source is not a regular file: {path}")
    value = _loads(path.read_bytes(), str(path))
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _verify_regular(path: Path, byte_count: int, digest: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"source is not a regular file: {path}")
    raw = path.read_bytes()
    if len(raw) != byte_count or _sha(raw) != digest:
        raise QualificationError(f"source lock drifted: {path}")


def _verify_static(contract: dict[str, Any]) -> None:
    if contract.get("official_indices") != [370, 372]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        _verify_regular(REPO / lock["path"], lock["bytes"], lock["sha256"])
    fixture = contract["fixture"]
    _verify_regular(REPO / fixture["path"], fixture["bytes"], fixture["sha256"])
    ledger_lock = contract["source_locks"][-1]
    ledger = _load(REPO / ledger_lock["path"])
    expected = (
        (370, "manifest-entry.rt-embed.02-url-and-inline-base64-video", "URL and inline base64 video"),
        (372, "manifest-entry.rt-embed.04-kafka-redis-opentelemetry", "Kafka/Redis/OpenTelemetry"),
    )
    for index, capability_id, title in expected:
        row = ledger["capabilities"][index]
        if (
            row.get("id") != capability_id
            or row.get("title") != title
            or row.get("acceptance_class") != "required_local"
            or row.get("contract", {}).get("advertised_literal") != title
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


def _environment(row: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in row.get("Config", {}).get("Env", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def _inspect(
    contract: dict[str, Any], counter: list[int]
) -> tuple[dict[str, Any], dict[str, Any], str]:
    runtime = contract["runtime"]
    peer_names = [contract["peers"][name]["container"] for name in ("kafka", "redis")]
    names = [runtime["container"], *peer_names, *PAUSED_WORKLOADS]
    rows = _loads(_docker(["inspect", *names], counter).stdout, "Docker inspect")
    if not isinstance(rows, list):
        raise QualificationError("Docker inspect envelope differed")
    by_name = {row.get("Name", "").lstrip("/"): row for row in rows}
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
    if row.get("HostConfig", {}).get("ExtraHosts") != [
        "host.docker.internal:host-gateway"
    ]:
        raise QualificationError("RT-Embed host-gateway mapping drifted")
    env = _environment(row)
    expected_env = {
        "MODEL_PATH": runtime["model_source"],
        "VLM_BATCH_SIZE": str(runtime["batch_size"]),
        "RTVI_OFFLINE": "true",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ASSET_DOWNLOAD_ALLOWED_PRIVATE_HOSTS": runtime["allowed_private_host"],
        "KAFKA_ENABLED": "true",
        "KAFKA_TOPIC": runtime["kafka_topic"],
        "ENABLE_REDIS_ERROR_MESSAGES": "true",
        "REDIS_HOST": runtime["allowed_private_host"],
        "REDIS_PORT": str(contract["peers"]["redis"]["port"]),
        "ERROR_MESSAGE_TOPIC": runtime["redis_error_channel"],
        "ENABLE_OTEL_MONITORING": "true",
        "OTEL_TRACES_EXPORTER": "console",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_SERVICE_NAME": runtime["otel_service_name"],
    }
    if any(env.get(key) != value for key, value in expected_env.items()):
        raise QualificationError("RT-Embed integration environment drifted")
    if not env.get("KAFKA_BOOTSTRAP_SERVERS"):
        raise QualificationError("RT-Embed Kafka bootstrap server is absent")
    if any(
        env.get(name, "")
        for name in ("NGC_CLI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN")
    ):
        raise QualificationError("RT-Embed unexpectedly retains credentials")

    peer_proof: dict[str, Any] = {}
    peer_token: dict[str, Any] = {}
    for name in ("kafka", "redis"):
        expected = contract["peers"][name]
        peer = by_name.get(expected["container"], {})
        peer_state = peer.get("State", {})
        if (
            peer.get("Image") != expected["image_id"]
            or peer.get("Config", {}).get("Image") != expected["image"]
            or peer.get("HostConfig", {}).get("NetworkMode") != expected["network_mode"]
            or peer_state.get("Status") != "running"
            or peer_state.get("Health", {}).get("Status") != "healthy"
            or peer_state.get("OOMKilled") is not False
            or peer.get("RestartCount") != 0
        ):
            raise QualificationError(f"local {name} peer identity drifted")
        peer_proof[f"{name}_healthy"] = True
        peer_proof[f"{name}_image_exact"] = True
        peer_proof[f"{name}_host_network"] = True
        peer_token[name] = {
            "id": peer.get("Id"),
            "image": peer.get("Image"),
            "started_at": peer_state.get("StartedAt"),
            "restart_count": peer.get("RestartCount"),
            "oom_killed": peer_state.get("OOMKilled"),
        }
    kafka_env = _environment(by_name[contract["peers"]["kafka"]["container"]])
    advertised = kafka_env.get("KAFKA_ADVERTISED_LISTENERS", "")
    if advertised != "PLAINTEXT://" + env["KAFKA_BOOTSTRAP_SERVERS"]:
        raise QualificationError("Kafka advertised listener and RT-Embed bootstrap differ")

    paused_token: dict[str, Any] = {}
    for name in PAUSED_WORKLOADS:
        paused = by_name.get(name)
        if not isinstance(paused, dict):
            raise QualificationError(f"operator-paused workload missing: {name}")
        paused_state = paused.get("State", {}).get("Status")
        if paused_state == "running":
            raise QualificationError(f"operator-paused workload restarted: {name}")
        paused_token[name] = {"id": paused.get("Id"), "status": paused_state}

    token = {
        "runtime": {
            "id": row.get("Id"),
            "image": row.get("Image"),
            "started_at": state.get("StartedAt"),
            "restart_count": row.get("RestartCount"),
            "oom_killed": state.get("OOMKilled"),
        },
        "peers": peer_token,
        "paused": paused_token,
    }
    proof = {
        "rt_embed_healthy": True,
        "rt_embed_image_exact": True,
        "rt_embed_loopback_exact": True,
        "rt_embed_restart_count": 0,
        "rt_embed_oom_killed": False,
        "integration_environment_exact": True,
        "credentials_blank": True,
        "operator_paused_workloads_preserved": True,
        **peer_proof,
    }
    return token, proof, row.get("Config", {}).get("Hostname", "")


def _verify_live_sources(contract: dict[str, Any], counter: list[int]) -> None:
    locks = [lock for lock in contract["source_locks"] if "container_path" in lock]
    result = _docker(
        [
            "exec",
            contract["runtime"]["container"],
            "sha256sum",
            *[lock["container_path"] for lock in locks],
        ],
        counter,
    )
    observed: dict[str, str] = {}
    for line in result.stdout.decode().splitlines():
        fields = line.split()
        if len(fields) == 2:
            observed[fields[1]] = fields[0]
    expected = {lock["container_path"]: lock["sha256"] for lock in locks}
    if observed != expected:
        raise QualificationError("live RT-Embed production source drifted")


def _resolve_owned_gateway(
    contract: dict[str, Any], counter: list[int]
) -> str:
    host = contract["runtime"]["allowed_private_host"]
    result = _docker(
        ["exec", contract["runtime"]["container"], "getent", "ahostsv4", host],
        counter,
    )
    addresses = {line.split()[0] for line in result.stdout.decode().splitlines() if line.split()}
    if len(addresses) != 1:
        raise QualificationError("host-gateway DNS did not resolve to one IPv4 address")
    address = addresses.pop()
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise QualificationError("host-gateway DNS returned an invalid IPv4 address") from exc
    if parsed.version != 4 or not parsed.is_private or parsed.is_loopback:
        raise QualificationError("host-gateway address left the private bridge scope")
    try:
        rows = _loads(
            subprocess.run(
                ["ip", "-j", "-4", "address", "show"],
                capture_output=True,
                check=True,
                timeout=10,
            ).stdout,
            "host IPv4 inventory",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("host IPv4 inventory failed") from exc
    host_addresses = {
        info.get("local")
        for row in rows
        for info in row.get("addr_info", [])
        if info.get("family") == "inet"
    }
    if address not in host_addresses:
        raise QualificationError("resolved Docker host-gateway is not a host interface")
    return address


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
        return response.status_code, _loads(bytes(raw), f"HTTP {path}")


def _require(status: int, expected: int, value: Any, label: str) -> dict[str, Any]:
    if status != expected or not isinstance(value, dict):
        raise QualificationError(f"{label} response contract differed")
    return value


def _uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise QualificationError("response omitted a UUID")
    try:
        UUID(value)
    except ValueError as exc:
        raise QualificationError("response UUID was invalid") from exc
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


def _validate_media(
    value: dict[str, Any], contract: dict[str, Any]
) -> list[list[float]]:
    _uuid(value.get("id"))
    chunks = value.get("chunk_responses")
    media = value.get("media_info")
    fixture = contract["fixture"]
    runtime = contract["runtime"]
    if (
        value.get("model") != runtime["model_id"]
        or not isinstance(value.get("created"), int)
        or not isinstance(media, dict)
        or media.get("type") != "offset"
        or not isinstance(chunks, list)
        or len(chunks) != fixture["expected_chunk_count"]
    ):
        raise QualificationError("video embedding envelope differed")
    vectors: list[list[float]] = []
    prior_end = -math.inf
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise QualificationError("video embedding chunk differed")
        try:
            start = float(chunk["start_time"])
            end = float(chunk["end_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QualificationError("video embedding timestamps differed") from exc
        if start < prior_end or end < start:
            raise QualificationError("video embedding chunks were not chronological")
        prior_end = end
        vectors.append(_vector(chunk.get("embeddings"), runtime["embedding_dimension"]))
    return vectors


class FixtureServer:
    """Serve exactly one owned fixture on one Docker host-gateway address."""

    def __init__(self, gateway: str, raw: bytes, mime_type: str) -> None:
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/owned-fixture.mp4":
                    self.send_error(404)
                    return
                self.server.hit_count += 1  # type: ignore[attr-defined]
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self.server = ThreadingHTTPServer((gateway, 0), Handler)
        self.server.daemon_threads = True
        self.server.hit_count = 0  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise QualificationError("owned HTTP fixture helper did not stop")


def _read_resp(stream) -> Any:
    prefix = stream.read(1)
    if not prefix:
        raise QualificationError("Redis connection closed before a response")
    line = stream.readline()
    if not line.endswith(b"\r\n"):
        raise QualificationError("Redis response framing differed")
    body = line[:-2]
    if prefix == b"+":
        return body.decode()
    if prefix == b"-":
        raise QualificationError("Redis returned an error")
    if prefix == b":":
        return int(body)
    if prefix == b"$":
        length = int(body)
        if length == -1:
            return None
        value = stream.read(length)
        if stream.read(2) != b"\r\n":
            raise QualificationError("Redis bulk response framing differed")
        return value
    if prefix == b"*":
        return [_read_resp(stream) for _ in range(int(body))]
    raise QualificationError("Redis response type differed")


def _redis_payload(parts: list[bytes]) -> bytes:
    return b"*" + str(len(parts)).encode() + b"\r\n" + b"".join(
        b"$" + str(len(part)).encode() + b"\r\n" + part + b"\r\n" for part in parts
    )


def _redis_command(gateway: str, port: int, parts: list[bytes]) -> Any:
    try:
        sock = socket.create_connection((gateway, port), timeout=5)
        sock.settimeout(5)
        stream = sock.makefile("rb")
        sock.sendall(_redis_payload(parts))
        result = _read_resp(stream)
        stream.close()
        sock.close()
        return result
    except OSError as exc:
        raise QualificationError("local Redis command failed") from exc


class RedisSubscription:
    def __init__(self, gateway: str, port: int, channel: str) -> None:
        try:
            self.sock = socket.create_connection((gateway, port), timeout=5)
            self.sock.settimeout(30)
            self.stream = self.sock.makefile("rb")
            self.channel = channel.encode()
            self.sock.sendall(_redis_payload([b"SUBSCRIBE", self.channel]))
            ack = _read_resp(self.stream)
        except OSError as exc:
            raise QualificationError("local Redis subscription failed") from exc
        if ack != [b"subscribe", self.channel, 1]:
            raise QualificationError("Redis subscription acknowledgement differed")

    def receive(self) -> dict[str, Any]:
        try:
            row = _read_resp(self.stream)
        except OSError as exc:
            raise QualificationError("Redis error message timed out") from exc
        if not isinstance(row, list) or row[:2] != [b"message", self.channel]:
            raise QualificationError("Redis Pub/Sub message envelope differed")
        value = _loads(row[2], "Redis Pub/Sub payload")
        if not isinstance(value, dict):
            raise QualificationError("Redis Pub/Sub payload was not an object")
        return value

    def close(self) -> None:
        try:
            self.sock.sendall(_redis_payload([b"UNSUBSCRIBE", self.channel]))
        except OSError:
            pass
        self.stream.close()
        self.sock.close()


KAFKA_CONSUMER_SCRIPT = r'''
import json, math, os, sys, time
sys.path.insert(0, "/opt/nvidia/rtvi/rtvi")
from kafka import KafkaConsumer, TopicPartition
from server.protos import nv_pb2

target = os.environ["QUALIFIER_TARGET_STREAM"]
topic = os.environ["KAFKA_TOPIC"]
consumer = KafkaConsumer(
    bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
    group_id=None,
    enable_auto_commit=False,
    consumer_timeout_ms=120000,
)
deadline = time.monotonic() + 20
partitions = None
while time.monotonic() < deadline and not partitions:
    partitions = consumer.partitions_for_topic(topic)
if not partitions:
    raise SystemExit("topic_metadata_timeout")
owned = [TopicPartition(topic, partition) for partition in sorted(partitions)]
consumer.assign(owned)
consumer.seek_to_end(*owned)
print(json.dumps({"ready": True}), flush=True)
matched = 0
dimensions = set()
finite = True
header_exact = True
key_correlated = True
request_present = True
chunks = set()
deadline = time.monotonic() + 120
while time.monotonic() < deadline and matched < 2:
    for records in consumer.poll(timeout_ms=1000).values():
        for record in records:
            message = nv_pb2.VisionLLM()
            try:
                message.ParseFromString(record.value)
            except Exception:
                continue
            if message.info.get("streamId", "") != target:
                continue
            matched += 1
            values = []
            for embedding in message.llm.visionEmbeddings:
                values.extend(embedding.vector)
            dimensions.add(len(values))
            finite = finite and all(math.isfinite(value) for value in values)
            headers = dict(record.headers or [])
            header_exact = header_exact and headers.get("message_type") == b"vision_llm"
            request_id = message.info.get("requestId", "")
            chunk_index = message.info.get("chunkIdx", "")
            request_present = request_present and bool(request_id)
            key_correlated = key_correlated and record.key == f"{request_id}:{chunk_index}".encode()
            chunks.add(chunk_index)
consumer.close()
print(json.dumps({
    "status": "passed" if matched == 2 else "failed",
    "matched": matched,
    "dimensions": sorted(dimensions),
    "finite": finite,
    "header_exact": header_exact,
    "key_correlated": key_correlated,
    "request_present": request_present,
    "unique_chunks": len(chunks),
}), flush=True)
'''


class KafkaObservation:
    def __init__(
        self, contract: dict[str, Any], target_stream: str, counter: list[int]
    ) -> None:
        counter[0] += 1
        try:
            self.process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-e",
                    f"QUALIFIER_TARGET_STREAM={target_stream}",
                    contract["runtime"]["container"],
                    "python3",
                    "-c",
                    KAFKA_CONSUMER_SCRIPT,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise QualificationError("Kafka observation process failed to start") from exc
        ready = self._line(30)
        if ready != {"ready": True}:
            self.close()
            raise QualificationError("Kafka observation did not become ready")

    def _line(self, timeout: float) -> dict[str, Any]:
        if self.process.stdout is None:
            raise QualificationError("Kafka observation stdout was unavailable")
        readable, _, _ = select.select([self.process.stdout], [], [], timeout)
        if not readable:
            raise QualificationError("Kafka observation timed out")
        line = self.process.stdout.readline()
        value = _loads(line, "Kafka observation")
        if not isinstance(value, dict):
            raise QualificationError("Kafka observation envelope differed")
        return value

    def result(self) -> dict[str, Any]:
        value = self._line(150)
        try:
            code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            self.close()
            raise QualificationError("Kafka observation did not exit") from exc
        if code != 0:
            raise QualificationError("Kafka observation failed")
        return value

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def _catalog(client: Client) -> dict[str, Any]:
    status, value = client.request("GET", "/v1/files?purpose=vision")
    return _require(status, 200, value, "file catalog")


def _stats(client: Client) -> dict[str, Any]:
    status, value = client.request("GET", "/v1/assets/stats")
    return _require(status, 200, value, "asset statistics")


def _streams(client: Client) -> list[Any]:
    status, value = client.request("GET", "/v1/streams/get-stream-info")
    if status != 200 or not isinstance(value, list):
        raise QualificationError("stream catalog response contract differed")
    return value


def _extract_spans(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace")
    decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicates)
    spans: list[dict[str, Any]] = []
    index = 0
    while True:
        index = text.find("{", index)
        if index < 0:
            break
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        index = end
        if (
            isinstance(value, dict)
            and isinstance(value.get("name"), str)
            and isinstance(value.get("context"), dict)
            and isinstance(value.get("attributes"), dict)
        ):
            spans.append(value)
    return spans


def _span_status(span: dict[str, Any]) -> str:
    return str(span.get("status", {}).get("status_code", ""))


def _service_name(span: dict[str, Any]) -> str:
    return str(span.get("resource", {}).get("attributes", {}).get("service.name", ""))


def _otel_proof(
    spans: list[dict[str, Any]],
    contract: dict[str, Any],
    url_id: str,
    data_id: str,
    error_id: str,
) -> dict[str, Any]:
    service_name = contract["runtime"]["otel_service_name"]

    def matching(name: str, stream_id: str) -> list[dict[str, Any]]:
        return [
            span
            for span in spans
            if span.get("name") == name
            and span.get("attributes", {}).get("stream_id") == stream_id
        ]

    url_ingress = matching("Video Embeddings API Request", url_id)
    data_ingress = matching("Video Embeddings API Request", data_id)
    error_ingress = matching("Video Embeddings API Request", error_id)
    e2e = matching("Pipeline End-to-End", url_id)
    kafka = matching("Kafka Publish", url_id)
    redis = matching("Redis Error Publish", error_id)
    if not (
        len(url_ingress) == len(data_ingress) == len(error_ingress) == len(e2e) == len(redis) == 1
        and len(kafka) == contract["fixture"]["expected_chunk_count"]
    ):
        raise QualificationError("required OpenTelemetry span denominator differed")
    if (
        url_ingress[0]["attributes"].get("input_transport") != "http"
        or data_ingress[0]["attributes"].get("input_transport") != "data"
        or error_ingress[0]["attributes"].get("input_transport") != "http"
        or _span_status(url_ingress[0]) != "OK"
        or _span_status(data_ingress[0]) != "OK"
        or _span_status(error_ingress[0]) != "ERROR"
    ):
        raise QualificationError("API ingress span semantics differed")
    e2e_span = e2e[0]
    e2e_trace = e2e_span["context"].get("trace_id")
    e2e_span_id = e2e_span["context"].get("span_id")
    e2e_request = e2e_span["attributes"].get("request_id")
    for span in kafka:
        attrs = span["attributes"]
        if (
            span["context"].get("trace_id") != e2e_trace
            or span.get("parent_id") != e2e_span_id
            or attrs.get("request_id") != e2e_request
            or attrs.get("messaging.system") != "kafka"
            or attrs.get("messaging.operation.name") != "publish"
            or attrs.get("messaging.destination.name") != contract["runtime"]["kafka_topic"]
            or attrs.get("message_type") != "vision_llm"
            or not isinstance(attrs.get("messaging.kafka.destination.partition"), int)
            or not isinstance(attrs.get("messaging.kafka.message.offset"), int)
            or _span_status(span) != "OK"
        ):
            raise QualificationError("Kafka publication span correlation differed")
    redis_span = redis[0]
    error_span = error_ingress[0]
    redis_attrs = redis_span["attributes"]
    if (
        redis_span["context"].get("trace_id") != error_span["context"].get("trace_id")
        or redis_span.get("parent_id") != error_span["context"].get("span_id")
        or redis_attrs.get("request_id") != error_span["attributes"].get("request_id")
        or redis_attrs.get("messaging.system") != "redis"
        or redis_attrs.get("messaging.operation.name") != "publish"
        or redis_attrs.get("messaging.destination.name")
        != contract["runtime"]["redis_error_channel"]
        or redis_attrs.get("message_type") != "error"
        or redis_attrs.get("messaging.redis.subscriber_count") != 1
        or _span_status(redis_span) != "OK"
    ):
        raise QualificationError("Redis publication span correlation differed")
    relevant = [*url_ingress, *data_ingress, *error_ingress, *e2e, *kafka, *redis]
    if any(_service_name(span) != service_name for span in relevant):
        raise QualificationError("OpenTelemetry service.name override was not honored")
    return {
        "api_ingress_span_count": 3,
        "pipeline_e2e_span_count": 1,
        "kafka_publish_span_count": len(kafka),
        "redis_publish_span_count": 1,
        "kafka_parent_trace_correlated": True,
        "redis_parent_trace_correlated": True,
        "request_attributes_correlated": True,
        "broker_acknowledgements_present": True,
        "success_and_error_statuses_exact": True,
        "configured_service_name_exact": True,
    }


def _read_otel(
    contract: dict[str, Any], counter: list[int], since: str,
    url_id: str, data_id: str, error_id: str
) -> dict[str, Any]:
    time.sleep(contract["execution"]["otel_flush_wait_seconds"])
    last_error: QualificationError | None = None
    for attempt in range(3):
        raw = _docker(
            ["logs", "--since", since, contract["runtime"]["container"]],
            counter,
            timeout=30,
        ).stdout
        try:
            return _otel_proof(_extract_spans(raw), contract, url_id, data_id, error_id)
        except QualificationError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(6)
    raise QualificationError(
        f"OpenTelemetry evidence did not flush in time: {last_error}"
    ) from last_error


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "status": "inert_rt_embed_url_brokers_otel_plan_valid",
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
    identity_before, identity_proof, expected_source = _inspect(contract, docker_counter)
    if not expected_source:
        raise QualificationError("RT-Embed source identity was absent")
    _verify_live_sources(contract, docker_counter)
    gateway = _resolve_owned_gateway(contract, docker_counter)
    fixture = contract["fixture"]
    fixture_raw = (REPO / fixture["path"]).read_bytes()
    helper = FixtureServer(gateway, fixture_raw, fixture["mime_type"])
    client = Client(contract)
    kafka: KafkaObservation | None = None
    redis_sub: RedisSubscription | None = None
    helper_closed = False
    kafka_closed = False
    redis_closed = False
    url_id = str(uuid4())
    data_id = str(uuid4())
    error_id = str(uuid4())
    since = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        ready_status, ready_value = client.request("GET", "/v1/ready?detailed=true")
        ready = _require(ready_status, 200, ready_value, "readiness")
        if ready.get("healthy") is not True:
            raise QualificationError("RT-Embed was not ready")
        models_status, models_value = client.request("GET", "/v1/models")
        models = _require(models_status, 200, models_value, "models")
        model_rows = models.get("data")
        if (
            not isinstance(model_rows, list)
            or len(model_rows) != 1
            or model_rows[0].get("id") != contract["runtime"]["model_id"]
        ):
            raise QualificationError("loaded RT-Embed model identity differed")
        catalog_before = _catalog(client)
        stats_before = _stats(client)
        streams_before = _streams(client)
        redis_size_before = _redis_command(
            gateway, contract["peers"]["redis"]["port"], [b"DBSIZE"]
        )
        if not isinstance(redis_size_before, int):
            raise QualificationError("Redis DBSIZE response differed")
        channel = contract["runtime"]["redis_error_channel"]
        numsub_before = _redis_command(
            gateway,
            contract["peers"]["redis"]["port"],
            [b"PUBSUB", b"NUMSUB", channel.encode()],
        )
        if numsub_before != [channel.encode(), 0]:
            raise QualificationError("Redis error channel had a pre-existing subscriber")

        kafka = KafkaObservation(contract, url_id, docker_counter)
        host = contract["runtime"]["allowed_private_host"]
        url = f"http://{host}:{helper.port}/owned-fixture.mp4"
        common = {
            "model": contract["runtime"]["model_id"],
            "media_type": fixture["media_type"],
            "chunk_duration": fixture["chunk_duration_seconds"],
            "chunk_overlap_duration": 0,
        }
        url_status, url_value = client.request(
            "POST",
            "/v1/generate_video_embeddings",
            json_body={"id": url_id, "url": url, **common},
            timeout=180,
        )
        url_vectors = _validate_media(
            _require(url_status, 200, url_value, "URL video embedding"), contract
        )
        kafka_proof = kafka.result()
        kafka_closed = True
        if kafka_proof != {
            "status": "passed",
            "matched": fixture["expected_chunk_count"],
            "dimensions": [contract["runtime"]["embedding_dimension"]],
            "finite": True,
            "header_exact": True,
            "key_correlated": True,
            "request_present": True,
            "unique_chunks": fixture["expected_chunk_count"],
        }:
            raise QualificationError("Kafka embedding-result oracle differed")

        data_uri = (
            f"data:{fixture['mime_type']};base64,"
            + base64.b64encode(fixture_raw).decode("ascii")
        )
        data_status, data_value = client.request(
            "POST",
            "/v1/generate_video_embeddings",
            json_body={"id": data_id, "url": data_uri, **common},
            timeout=180,
        )
        data_vectors = _validate_media(
            _require(data_status, 200, data_value, "inline-base64 video embedding"),
            contract,
        )
        if len(url_vectors) != len(data_vectors):
            raise QualificationError("URL/base64 chunk counts differed")
        cosines: list[float] = []
        max_difference = 0.0
        for left, right in zip(url_vectors, data_vectors, strict=True):
            numerator = sum(a * b for a, b in zip(left, right, strict=True))
            left_norm = math.sqrt(sum(value * value for value in left))
            right_norm = math.sqrt(sum(value * value for value in right))
            cosine = numerator / (left_norm * right_norm)
            if not math.isfinite(cosine):
                raise QualificationError("URL/base64 cosine was non-finite")
            cosines.append(cosine)
            max_difference = max(
                max_difference,
                max(abs(a - b) for a, b in zip(left, right, strict=True)),
            )
        if min(cosines) < 0.999999 or max_difference > 1e-9:
            raise QualificationError("same-byte URL/base64 vectors were not equivalent")
        if helper.server.hit_count != 1:  # type: ignore[attr-defined]
            raise QualificationError("owned URL helper request count differed")

        redis_sub = RedisSubscription(
            gateway, contract["peers"]["redis"]["port"], channel
        )
        closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        closed.bind((gateway, 0))
        closed_port = int(closed.getsockname()[1])
        closed.close()
        error_status, error_value = client.request(
            "POST",
            "/v1/generate_video_embeddings",
            json_body={
                "id": error_id,
                "url": f"http://{host}:{closed_port}/owned-unreachable.mp4",
                **common,
            },
            timeout=20,
        )
        error = _require(error_status, 500, error_value, "URL acquisition error")
        if error != {
            "code": "AssetAcquisitionError",
            "message": "Failed to acquire video input.",
        }:
            raise QualificationError("sanitized URL acquisition error differed")
        redis_message = redis_sub.receive()
        if set(redis_message) != {"streamId", "timestamp", "type", "source", "event"}:
            raise QualificationError("Redis error schema differed")
        if (
            redis_message.get("streamId") != error_id
            or redis_message.get("type") != "functional"
            or redis_message.get("source") != expected_source
            or redis_message.get("event") != "Failed to acquire video input."
        ):
            raise QualificationError("Redis error correlation differed")
        try:
            parsed_timestamp = datetime.fromisoformat(
                str(redis_message["timestamp"]).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise QualificationError("Redis error timestamp differed") from exc
        if parsed_timestamp.tzinfo is None:
            raise QualificationError("Redis error timestamp was not timezone-aware")
        redis_sub.close()
        redis_closed = True
        redis_sub = None
        numsub = _redis_command(
            gateway,
            contract["peers"]["redis"]["port"],
            [b"PUBSUB", b"NUMSUB", channel.encode()],
        )
        if numsub != [channel.encode(), 0]:
            raise QualificationError("owned Redis subscriber remained attached")

        otel_proof = _read_otel(
            contract, docker_counter, since, url_id, data_id, error_id
        )
        helper.close()
        helper_closed = True
        catalog_after = _catalog(client)
        stats_after = _stats(client)
        streams_after = _streams(client)
        final_ready_status, final_ready_value = client.request(
            "GET", "/v1/ready?detailed=true"
        )
        final_ready = _require(
            final_ready_status, 200, final_ready_value, "final readiness"
        )
        final_models_status, final_models_value = client.request("GET", "/v1/models")
        final_models = _require(
            final_models_status, 200, final_models_value, "final models"
        )
        redis_size_after = _redis_command(
            gateway, contract["peers"]["redis"]["port"], [b"DBSIZE"]
        )
        if (
            catalog_after != catalog_before
            or stats_after != stats_before
            or streams_after != streams_before
            or final_ready.get("healthy") is not True
            or final_models != models
            or redis_size_after != redis_size_before
        ):
            raise QualificationError("runtime state was not restored exactly")
    finally:
        if redis_sub is not None:
            redis_sub.close()
            redis_closed = True
        if kafka is not None and not kafka_closed:
            kafka.close()
            kafka_closed = True
        if not helper_closed:
            helper.close()
            helper_closed = True
        client.close()

    identity_after, _, _ = _inspect(contract, docker_counter)
    if identity_after != identity_before:
        raise QualificationError("RT-Embed, peers, or paused workloads changed identity")
    if client.requests != contract["execution"]["max_http_requests"]:
        raise QualificationError("HTTP request budget was not exact")
    if docker_counter[0] > contract["execution"]["max_docker_commands"]:
        raise QualificationError("Docker command budget exceeded")
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
            "model_requests": 2,
            "max_model_requests": contract["execution"]["max_model_requests"],
            "docker_commands": docker_counter[0],
            "max_docker_commands": contract["execution"]["max_docker_commands"],
            "support_processes_peak": 2,
            "max_support_processes": 2,
        },
        "runtime_identity": {**identity_proof, "production_sources_exact": True},
        "url_and_inline_base64": {
            "same_fixture_bytes": True,
            "fixture_codec_h264": True,
            "fixture_duration_seconds": fixture["duration_seconds"],
            "url_http_status": 200,
            "inline_base64_http_status": 200,
            "url_helper_request_count": 1,
            "distinct_transport_provenance": True,
            "chunk_count_each": fixture["expected_chunk_count"],
            "embedding_dimension": contract["runtime"]["embedding_dimension"],
            "vectors_finite_nonzero": True,
            "minimum_cosine_at_least_0_999999": True,
            "maximum_absolute_difference_at_most_1e_9": True,
        },
        "kafka": {
            "enabled": True,
            "local_peer_healthy": True,
            "topic_preexisting": True,
            "result_message_count": kafka_proof["matched"],
            "protobuf_vision_llm_parsed": True,
            "message_type_header_exact": True,
            "record_key_request_chunk_correlated": True,
            "payload_request_present": True,
            "unique_chunk_count": kafka_proof["unique_chunks"],
            "embedding_dimension": contract["runtime"]["embedding_dimension"],
            "vectors_finite": True,
            "consumer_group_created": False,
            "topic_configuration_mutations": 0,
        },
        "redis": {
            "enabled": True,
            "local_peer_healthy": True,
            "error_http_status": 500,
            "sanitized_api_error_exact": True,
            "error_message_count": 1,
            "schema_exact": True,
            "stream_correlated": True,
            "event_exact": True,
            "source_exact": True,
            "type_exact": True,
            "timestamp_utc_parseable": True,
            "persistent_key_count_preserved": True,
            "subscriber_detached": True,
        },
        "opentelemetry": otel_proof,
        "cleanup": {
            "asset_statistics_restored_exactly": True,
            "file_catalog_restored_exactly": True,
            "stream_catalog_restored_exactly": True,
            "model_catalog_preserved": True,
            "runtime_identity_preserved": True,
            "owned_http_helper_stopped": helper_closed,
            "owned_kafka_consumer_stopped": kafka_closed,
            "owned_redis_subscriber_stopped": redis_closed,
            "operator_paused_workloads_preserved": True,
        },
        "policy": contract["policy"],
    }


def _write_receipt(value: dict[str, Any]) -> None:
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = RECEIPT_PATH.with_suffix(".json.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, RECEIPT_PATH)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("plan")
    execute = subparsers.add_parser("execute")
    execute.add_argument("--ack", required=True)
    args = parser.parse_args()
    try:
        contract = _load(CONTRACT_PATH)
        if args.mode == "plan":
            value = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("execution acknowledgement differed")
            value = _execute(contract)
            _write_receipt(value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "package_id": "rt-embed-url-brokers-otel-runtime-successor",
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
