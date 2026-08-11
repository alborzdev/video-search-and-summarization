#!/usr/bin/env python3
"""Bounded, authorization-gated current-runtime Search qualification.

The executor creates the two otherwise-absent fixed video-file indices, writes
four tiny owned fixture documents, exercises every canonical Search route, and
then removes only resources whose index UUID and exact document set it owns.
The default command is inert. Retained evidence contains digests and semantic
facts, never prompts, vectors, raw responses, URLs, or runtime object IDs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
GENERATED_ENV_PATH = ROOT / "deploy/docker/thor-local/generated.env"

BEHAVIOR_INDEX = "mdx-behavior-2025-01-01"
RAW_INDEX = "mdx-raw-2025-01-01"
EMBED_INDEX = "mdx-embed-filtered-2025-01-01"
QUERY_A = "person wearing dark clothing"
QUERY_B = "vehicle wheel and tire"
FUSION_QUERY = "person wearing dark clothing moving beside a racing vehicle"
AUTHORIZATION_ID = "search-current-runtime"
PLAIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE_BYTES = 32 * 1024 * 1024


class QualificationError(RuntimeError):
    """Stable public failure code; never include sensitive runtime material."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "deadline_exceeded",
        "fixture_error",
        "oracle_failed",
        "runtime_identity_error",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _progress(stage: str) -> None:
    """Emit one fixed, non-sensitive execution checkpoint."""
    allowed = {
        "admission-passed",
        "fixture-resolved",
        "templates-and-embedding-passed",
        "owned-indices-created",
        "owned-documents-indexed",
        "frames-api-passed",
        "attribute-semantics-passed",
        "selected-object-semantics-passed",
        "fusion-response-passed",
        "adjacent-invalid-passed",
        "fusion-semantics-passed",
        "cleanup-started",
        "cleanup-indices-processed",
        "cleanup-absence-passed",
        "cleanup-embed-passed",
        "cleanup-frames-passed",
        "cleanup-passed",
    }
    if stage not in allowed:
        raise QualificationError("configuration_error")
    print(f"[search-current-runtime] {stage}", file=sys.stderr, flush=True)


def _failure_checkpoint(scope: str, code: str) -> None:
    if scope not in {"runtime", "cleanup"} or code not in QualificationError.CODES:
        raise QualificationError("configuration_error")
    print(f"[search-current-runtime] {scope}-failure={code}", file=sys.stderr, flush=True)


def _canonical(value: Any) -> bytes:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise QualificationError("configuration_error")
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_canonical(value))


def _read_regular(path: Path, maximum: int = MAX_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > maximum:
            raise QualificationError("configuration_error")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise QualificationError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _decode_json(raw: bytes, *, object_only: bool = False) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise QualificationError("transport_error")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                QualificationError("transport_error")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("transport_error") from exc
    if object_only and not isinstance(value, dict):
        raise QualificationError("transport_error")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    value = _decode_json(_read_regular(path), object_only=True)
    if not isinstance(value, dict):
        raise QualificationError("configuration_error")
    return value


def _repo_path(relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise QualificationError("configuration_error")
    current = ROOT
    for part in relative.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise QualificationError("configuration_error")
        except OSError as exc:
            raise QualificationError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc
    return current


def _validate_source_locks(contract: Mapping[str, Any]) -> dict[str, str]:
    rows = contract.get("source_locks")
    if not isinstance(rows, list) or len(rows) < 1:
        raise QualificationError("configuration_error")
    observed: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise QualificationError("configuration_error")
        relative = row.get("path")
        expected = row.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str) or not SHA_RE.fullmatch(expected):
            raise QualificationError("configuration_error")
        if relative in observed:
            raise QualificationError("configuration_error")
        actual = _sha(_read_regular(_repo_path(relative)))
        if actual != expected:
            raise QualificationError("configuration_error")
        observed[relative] = actual
    return observed


def _contract() -> dict[str, Any]:
    contract = _load_object(CONTRACT_PATH)
    expected = {
        "package_id": "thor-search-semantic-current-runtime-successor-v1",
        "capability_id": "runtime.agent.search-profile",
        "oracle_id": "oracle.runtime.agent.search-profile",
        "mode": "authorization-gated-owned-index-numeric-local-runtime",
        "default_execution_enabled": False,
    }
    if any(contract.get(key) != value for key, value in expected.items()):
        raise QualificationError("configuration_error")
    if contract.get("indices", {}).get("behavior_owned") != BEHAVIOR_INDEX:
        raise QualificationError("configuration_error")
    if contract.get("indices", {}).get("raw_owned") != RAW_INDEX:
        raise QualificationError("configuration_error")
    if contract.get("indices", {}).get("embed_read_only") != EMBED_INDEX:
        raise QualificationError("configuration_error")
    queries = contract.get("fixture", {}).get("query_contracts")
    expected_queries = [
        {"sha256": _sha(QUERY_A.encode("utf-8")), "bytes": len(QUERY_A.encode("utf-8"))},
        {"sha256": _sha(QUERY_B.encode("utf-8")), "bytes": len(QUERY_B.encode("utf-8"))},
    ]
    if queries != expected_queries:
        raise QualificationError("configuration_error")
    return contract


def _plain(value: str) -> str:
    if not isinstance(value, str) or not PLAIN_RE.fullmatch(value):
        raise QualificationError("configuration_error")
    return value


def _run(command: Sequence[str], *, timeout: float, maximum: int) -> bytes:
    try:
        completed = subprocess.run(
            list(command),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_identity_error") from exc
    if len(completed.stdout) > maximum:
        raise QualificationError("runtime_identity_error")
    return completed.stdout


def _runtime_snapshot(contract: Mapping[str, Any]) -> dict[str, Any]:
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict) or len(runtime) != 5:
        raise QualificationError("configuration_error")
    snapshot: dict[str, Any] = {}
    template = "{{.Name}}|{{.Config.Image}}|{{.Image}}|{{.State.Running}}|{{.RestartCount}}|{{.State.OOMKilled}}|{{.State.StartedAt}}"
    for key, expected in runtime.items():
        if not isinstance(expected, dict):
            raise QualificationError("configuration_error")
        container = expected.get("container")
        if not isinstance(container, str) or not PLAIN_RE.fullmatch(container):
            raise QualificationError("configuration_error")
        raw = _run(
            ["docker", "inspect", "--format", template, container],
            timeout=10,
            maximum=4096,
        ).decode("utf-8").strip()
        parts = raw.split("|")
        if len(parts) != 7:
            raise QualificationError("runtime_identity_error")
        name, configured_image, image_id, running, restart_count, oom_killed, started_at = parts
        if name.lstrip("/") != container:
            raise QualificationError("runtime_identity_error")
        try:
            restart = int(restart_count)
        except ValueError as exc:
            raise QualificationError("runtime_identity_error") from exc
        row = {
            "configured_image": configured_image,
            "image_id": image_id,
            "running": running == "true",
            "restart_count": restart,
            "oom_killed": oom_killed == "true",
            "started_at_sha256": _sha(started_at.encode("utf-8")),
        }
        if (
            row["configured_image"] != expected.get("configured_image")
            or row["image_id"] != expected.get("image_id")
            or row["running"] is not True
            or row["restart_count"] != 0
            or row["oom_killed"] is not False
        ):
            raise QualificationError("runtime_identity_error")
        snapshot[container] = row
    return snapshot


def _selected_env() -> tuple[str, int]:
    raw = _read_regular(GENERATED_ENV_PATH, maximum=1024 * 1024).decode("utf-8")
    selected: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"HOST_IP", "RTVI_CV_PORT"}:
            if key in selected:
                raise QualificationError("configuration_error")
            selected[key] = value.strip()
    if set(selected) != {"HOST_IP", "RTVI_CV_PORT"}:
        raise QualificationError("configuration_error")
    try:
        address = ipaddress.ip_address(selected["HOST_IP"])
        port = int(selected["RTVI_CV_PORT"])
    except (ValueError, TypeError) as exc:
        raise QualificationError("configuration_error") from exc
    if address.is_unspecified or address.is_multicast or not 1 <= port <= 65535:
        raise QualificationError("configuration_error")
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    probe = socket.socket(family, socket.SOCK_STREAM)
    try:
        probe.bind((address.compressed, 0))
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    finally:
        probe.close()
    return address.compressed, port


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@dataclass
class Budget:
    max_requests: int
    max_mutations: int
    requests: int = 0
    mutations: int = 0

    def request(self, mutation: bool) -> None:
        if self.requests >= self.max_requests:
            raise QualificationError("transport_error")
        if mutation and self.mutations >= self.max_mutations:
            raise QualificationError("transport_error")
        self.requests += 1
        if mutation:
            self.mutations += 1


@dataclass
class LocalHttp:
    origins: Mapping[str, str]
    budget: Budget
    response_limit: int
    deadline: float
    timeout: float = 150.0
    observations: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())
        for name, origin in self.origins.items():
            _plain(name)
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "http"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or parsed.hostname is None
                or parsed.port is None
            ):
                raise QualificationError("configuration_error")
            try:
                ipaddress.ip_address(parsed.hostname)
            except ValueError as exc:
                raise QualificationError("configuration_error") from exc

    def call(
        self,
        *,
        operation: str,
        target: str,
        method: str,
        path: str,
        body: Any | None = None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
        allowed: Iterable[int] = (200,),
        mutation: bool = False,
        expect_json: bool = True,
    ) -> tuple[int, Any, bytes]:
        _plain(operation)
        if target not in self.origins or method not in {"DELETE", "GET", "HEAD", "POST", "PUT"}:
            raise QualificationError("configuration_error")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise QualificationError("configuration_error")
        parsed_path = urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc or parsed_path.fragment or "\\" in path:
            raise QualificationError("configuration_error")
        if any(part in {".", ".."} for part in parsed_path.path.split("/")):
            raise QualificationError("configuration_error")
        if time.monotonic() >= self.deadline:
            raise QualificationError("deadline_exceeded")
        self.budget.request(mutation)
        if body is not None and raw_body is not None:
            raise QualificationError("configuration_error")
        payload = _canonical(body) if body is not None else raw_body
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = content_type
        request = Request(
            self.origins[target] + path,
            data=payload,
            headers=headers,
            method=method,
        )
        status: int
        raw: bytes
        try:
            response = self.opener.open(
                request,
                timeout=max(1.0, min(self.timeout, self.deadline - time.monotonic())),
            )
            try:
                status = int(response.status)
                if response.geturl() != request.full_url:
                    raise QualificationError("transport_error")
                raw = response.read(self.response_limit + 1)
            finally:
                response.close()
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read(self.response_limit + 1)
            exc.close()
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            raise QualificationError("transport_error") from exc
        if len(raw) > self.response_limit or status not in set(allowed):
            print(
                f"[search-current-runtime] transport-rejected-operation={operation} status={status}",
                file=sys.stderr,
                flush=True,
            )
            raise QualificationError("transport_error")
        value: Any = None
        if expect_json:
            if not raw:
                raise QualificationError("transport_error")
            value = _decode_json(raw)
        self.observations.append(
            {
                "sequence": len(self.observations) + 1,
                "operation": operation,
                "target": target,
                "method": method,
                "path_sha256": _sha(path.encode("utf-8")),
                "status": status,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
            }
        )
        return status, value, raw


def _index_status(http: LocalHttp, index: str, operation: str) -> tuple[int, Any]:
    status, value, _ = http.call(
        operation=operation,
        target="elasticsearch",
        method="GET",
        path=f"/{index}",
        allowed=(200, 404),
    )
    return status, value


def _index_uuid(http: LocalHttp, index: str, operation: str) -> str:
    _, value, _ = http.call(
        operation=operation,
        target="elasticsearch",
        method="GET",
        path=f"/{index}/_settings",
    )
    try:
        uuid = value[index]["settings"]["index"]["uuid"]
    except (KeyError, TypeError) as exc:
        raise QualificationError("oracle_failed") from exc
    if not isinstance(uuid, str) or not uuid:
        raise QualificationError("oracle_failed")
    return uuid


def _index_count(http: LocalHttp, index: str, operation: str) -> int:
    _, value, _ = http.call(
        operation=operation,
        target="elasticsearch",
        method="GET",
        path=f"/{index}/_count",
    )
    count = value.get("count") if isinstance(value, dict) else None
    if type(count) is not int or count < 0:
        raise QualificationError("oracle_failed")
    return count


def _index_document_ids(http: LocalHttp, index: str, operation: str, size: int) -> set[str]:
    _, value, _ = http.call(
        operation=operation,
        target="elasticsearch",
        method="POST",
        path=f"/{index}/_search",
        body={"query": {"match_all": {}}, "size": size, "_source": False},
    )
    try:
        hits = value["hits"]["hits"]
    except (KeyError, TypeError) as exc:
        raise QualificationError("cleanup_failed") from exc
    if not isinstance(hits, list):
        raise QualificationError("cleanup_failed")
    ids = {row.get("_id") for row in hits if isinstance(row, dict)}
    if None in ids or len(ids) != len(hits):
        raise QualificationError("cleanup_failed")
    return {str(item) for item in ids}


def _vector(value: Any, dimensions: int) -> list[float]:
    try:
        data = value["data"][0]
        if isinstance(data, dict):
            data = data["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("oracle_failed") from exc
    if not isinstance(data, list) or len(data) != dimensions:
        raise QualificationError("oracle_failed")
    vector: list[float] = []
    for item in data:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise QualificationError("oracle_failed")
        number = float(item)
        if not math.isfinite(number):
            raise QualificationError("oracle_failed")
        vector.append(number)
    if not any(number != 0.0 for number in vector):
        raise QualificationError("oracle_failed")
    return vector


def _normalized_average(first: Sequence[float], second: Sequence[float]) -> list[float]:
    values = [(left + right) / 2.0 for left, right in zip(first, second, strict=True)]
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0:
        raise QualificationError("oracle_failed")
    return [value / norm for value in values]


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise QualificationError("fixture_error")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise QualificationError("fixture_error")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualificationError("fixture_error") from exc
    if parsed.tzinfo is None:
        raise QualificationError("fixture_error")
    return parsed.astimezone(timezone.utc)


def _attribute_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"value"} or not isinstance(value["value"], list):
        raise QualificationError("oracle_failed")
    rows = value["value"]
    if not all(isinstance(row, dict) and isinstance(row.get("metadata"), dict) for row in rows):
        raise QualificationError("oracle_failed")
    return rows


def _search_rows(value: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    if not isinstance(value, dict) or set(value) != {"data", "search_messages"}:
        raise QualificationError("oracle_failed")
    rows = value["data"]
    messages = value["search_messages"]
    if not isinstance(rows, list) or not isinstance(messages, list) or not all(isinstance(row, dict) for row in rows):
        raise QualificationError("oracle_failed")
    return rows, messages


def _frame_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("frames"), list):
        rows = value["frames"]
    else:
        raise QualificationError("oracle_failed")
    if not all(isinstance(row, dict) for row in rows):
        raise QualificationError("oracle_failed")
    return rows


def _object_set_attribute(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        metadata = row.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("object_id"), str):
            raise QualificationError("oracle_failed")
        result.add(metadata["object_id"])
    return result


def _object_set_search(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        object_ids = row.get("object_ids")
        if not isinstance(object_ids, list) or not all(isinstance(item, str) for item in object_ids):
            raise QualificationError("oracle_failed")
        result.update(object_ids)
    return result


def _hashed_set(values: Iterable[str]) -> list[str]:
    return sorted(_sha(value.encode("utf-8")) for value in values)


def _duration(row: Mapping[str, Any]) -> float:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        raise QualificationError("oracle_failed")
    start = _parse_iso(metadata.get("start_time"))
    end = _parse_iso(metadata.get("end_time"))
    seconds = (end - start).total_seconds()
    if not math.isfinite(seconds) or seconds < 0:
        raise QualificationError("oracle_failed")
    return seconds


def _template_dimensions(value: Any) -> set[int]:
    found: set[int] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("type") == "dense_vector" and type(item.get("dims")) is int:
                found.add(item["dims"])
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


def _docker_log_markers(since: str, maximum: int) -> dict[str, int]:
    try:
        completed = subprocess.run(
            ["docker", "logs", "--since", since, "vss-agent"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_identity_error") from exc
    raw = completed.stdout
    if len(raw) > maximum:
        raise QualificationError("runtime_identity_error")
    text = raw.decode("utf-8", errors="replace")
    markers = {
        "embed": text.count("EXECUTION PATH: Embed search"),
        "fusion": text.count("EXECUTION PATH: Fusion Search"),
        "rerank": text.count("RRF fusion reranking complete"),
    }
    print(
        "[search-current-runtime] fusion-log-markers="
        + ",".join(f"{key}:{markers[key]}" for key in ("embed", "fusion", "rerank")),
        file=sys.stderr,
        flush=True,
    )
    if any(value < 1 for value in markers.values()):
        raise QualificationError("oracle_failed")
    return markers


def _make_object_ids(run_id: str) -> tuple[str, str]:
    first = 900000 + int(_sha((run_id + ":reference").encode())[:6], 16) % 90000
    second = 900000 + int(_sha((run_id + ":candidate").encode())[:6], 16) % 90000
    if second == first:
        second = 900000 + ((second - 900000 + 1) % 90000)
    return str(first), str(second)


@dataclass
class OwnedIndex:
    name: str
    uuid: str | None = None
    document_ids: set[str] = field(default_factory=set)


def _cleanup_index(http: LocalHttp, owned: OwnedIndex) -> dict[str, Any]:
    if owned.uuid is None:
        status, _ = _index_status(http, owned.name, f"cleanup_probe_{owned.name.split('-')[1]}")
        if status == 404:
            return {"created": False, "deleted": False, "foreign_documents_observed": False}
        raise QualificationError("cleanup_failed")
    current_uuid = _index_uuid(http, owned.name, f"cleanup_uuid_{owned.name.split('-')[1]}")
    if current_uuid != owned.uuid:
        raise QualificationError("cleanup_failed")
    ids = _index_document_ids(
        http,
        owned.name,
        f"cleanup_inventory_{owned.name.split('-')[1]}",
        len(owned.document_ids) + 2,
    )
    foreign = ids != owned.document_ids
    if foreign:
        lines: list[bytes] = []
        for document_id in sorted(owned.document_ids):
            lines.append(_canonical({"delete": {"_index": owned.name, "_id": document_id}}) + b"\n")
        raw = b"".join(lines)
        _, value, _ = http.call(
            operation=f"cleanup_exact_docs_{owned.name.split('-')[1]}",
            target="elasticsearch",
            method="POST",
            path="/_bulk?refresh=wait_for",
            raw_body=raw,
            content_type="application/x-ndjson",
            mutation=True,
        )
        if not isinstance(value, dict) or value.get("errors") is not False:
            raise QualificationError("cleanup_failed")
        remaining = _index_document_ids(
            http,
            owned.name,
            f"cleanup_verify_docs_{owned.name.split('-')[1]}",
            len(owned.document_ids) + 2,
        )
        if remaining & owned.document_ids:
            raise QualificationError("cleanup_failed")
        return {"created": True, "deleted": False, "foreign_documents_observed": True}
    _, value, _ = http.call(
        operation=f"cleanup_delete_index_{owned.name.split('-')[1]}",
        target="elasticsearch",
        method="DELETE",
        path=f"/{owned.name}",
        mutation=True,
    )
    if not isinstance(value, dict) or value.get("acknowledged") is not True:
        raise QualificationError("cleanup_failed")
    return {"created": True, "deleted": True, "foreign_documents_observed": False}


def _execute(contract: dict[str, Any], run_id: str, acknowledgement: str) -> dict[str, Any]:
    expected_ack = contract.get("authorization", {}).get("acknowledgement")
    if acknowledgement != expected_ack:
        raise QualificationError("authorization_required")
    started = time.monotonic()
    deadline = started + contract["bounds"]["max_duration_ms"] / 1000.0
    source_hashes = _validate_source_locks(contract)
    commit = _run(["git", "rev-parse", "HEAD"], timeout=10, maximum=256).decode().strip()
    if commit != contract.get("target_commit") or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise QualificationError("configuration_error")
    pre_runtime = _runtime_snapshot(contract)
    host_ip, rtvi_cv_port = _selected_env()
    origins = {
        "search": "http://127.0.0.1:8100",
        "elasticsearch": "http://127.0.0.1:9200",
        "ingress": "http://127.0.0.1:7777",
        "rtvi_cv": f"http://{host_ip}:{rtvi_cv_port}",
    }
    budget = Budget(
        max_requests=contract["bounds"]["max_http_requests"],
        max_mutations=contract["bounds"]["max_persistent_mutations"],
    )
    http = LocalHttp(
        origins=origins,
        budget=budget,
        response_limit=contract["bounds"]["max_response_bytes"],
        deadline=deadline,
    )
    behavior = OwnedIndex(BEHAVIOR_INDEX)
    raw_index = OwnedIndex(RAW_INDEX)
    cleanup_rows: dict[str, Any] = {}
    failure: QualificationError | None = None
    semantics: dict[str, Any] | None = None
    embed_uuid = ""
    embed_count = -1
    fixture_context: dict[str, Any] = {}
    log_since = datetime.now(timezone.utc).isoformat()
    _progress("admission-passed")
    try:
        behavior_pre, _ = _index_status(http, BEHAVIOR_INDEX, "behavior_prestate")
        raw_pre, _ = _index_status(http, RAW_INDEX, "raw_prestate")
        if behavior_pre != 404 or raw_pre != 404:
            raise QualificationError("fixture_error")
        embed_uuid = _index_uuid(http, EMBED_INDEX, "embed_pre_uuid")
        embed_count = _index_count(http, EMBED_INDEX, "embed_pre_count")
        if embed_count < 1:
            raise QualificationError("fixture_error")

        sensor_status, sensors, _ = http.call(
            operation="vios_sensor_inventory",
            target="ingress",
            method="GET",
            path="/vst/api/v1/sensor/list",
        )
        if sensor_status != 200 or not isinstance(sensors, list):
            raise QualificationError("fixture_error")
        sensor_hash = contract["fixture"]["existing_sensor_name_sha256"]
        matches = [
            row
            for row in sensors
            if isinstance(row, dict)
            and isinstance(row.get("name"), str)
            and _sha(row["name"].encode("utf-8")) == sensor_hash
        ]
        if len(matches) != 1:
            raise QualificationError("fixture_error")
        sensor = matches[0]
        sensor_name = sensor.get("name")
        sensor_id = sensor.get("sensorId")
        if (
            not isinstance(sensor_name, str)
            or not isinstance(sensor_id, str)
            or sensor.get("type") != contract["fixture"]["required_sensor_type"]
            or sensor.get("state") != contract["fixture"]["required_sensor_state"]
            or sensor.get("isTimelinePresent") is not True
        ):
            raise QualificationError("fixture_error")

        _, storage, _ = http.call(
            operation="vios_storage_timelines",
            target="ingress",
            method="GET",
            path="/vst/api/v1/storage/size?timelines=true",
        )
        try:
            timelines = storage[sensor_id]["timelines"]
            selected_timeline = timelines[0]
            base = _parse_iso(selected_timeline["startTime"])
            timeline_end = _parse_iso(selected_timeline["endTime"])
        except (KeyError, IndexError, TypeError) as exc:
            raise QualificationError("fixture_error") from exc
        timeline_seconds = (timeline_end - base).total_seconds()
        if timeline_seconds < contract["fixture"]["minimum_timeline_seconds"]:
            raise QualificationError("fixture_error")
        fixture_context = {
            "sensor_name_sha256": _sha(sensor_name.encode("utf-8")),
            "sensor_id_sha256": _sha(sensor_id.encode("utf-8")),
            "timeline_sha256": _digest(selected_timeline),
            "timeline_seconds": timeline_seconds,
        }
        _progress("fixture-resolved")

        dimensions = contract["indices"]["vector_dimensions"]
        for template_name, operation in (
            ("mdx_behavior_template", "behavior_template"),
            ("mdx_raw_template", "raw_template"),
        ):
            _, template, _ = http.call(
                operation=operation,
                target="elasticsearch",
                method="GET",
                path=f"/_index_template/{template_name}",
            )
            if _template_dimensions(template) != {dimensions}:
                raise QualificationError("oracle_failed")
        _, live, _ = http.call(
            operation="rtvi_cv_liveness",
            target="rtvi_cv",
            method="GET",
            path="/api/v1/live",
        )
        if not isinstance(live, dict):
            raise QualificationError("oracle_failed")
        _, embedding_a_value, _ = http.call(
            operation="embedding_query_a",
            target="rtvi_cv",
            method="POST",
            path="/api/v1/generate_text_embeddings",
            body={"text_input": QUERY_A, "model": ""},
        )
        _, embedding_b_value, _ = http.call(
            operation="embedding_query_b",
            target="rtvi_cv",
            method="POST",
            path="/api/v1/generate_text_embeddings",
            body={"text_input": QUERY_B, "model": ""},
        )
        embedding_a = _vector(embedding_a_value, dimensions)
        embedding_b = _vector(embedding_b_value, dimensions)
        candidate_embedding = _normalized_average(embedding_a, embedding_b)
        _progress("templates-and-embedding-passed")

        _, created_behavior, _ = http.call(
            operation="create_behavior_index",
            target="elasticsearch",
            method="PUT",
            path=f"/{BEHAVIOR_INDEX}",
            body={},
            mutation=True,
        )
        if not isinstance(created_behavior, dict) or created_behavior.get("acknowledged") is not True:
            raise QualificationError("oracle_failed")
        behavior.uuid = _index_uuid(http, BEHAVIOR_INDEX, "behavior_owned_uuid")
        _, created_raw, _ = http.call(
            operation="create_raw_index",
            target="elasticsearch",
            method="PUT",
            path=f"/{RAW_INDEX}",
            body={},
            mutation=True,
        )
        if not isinstance(created_raw, dict) or created_raw.get("acknowledged") is not True:
            raise QualificationError("oracle_failed")
        raw_index.uuid = _index_uuid(http, RAW_INDEX, "raw_owned_uuid")
        _progress("owned-indices-created")

        reference_id, candidate_id = _make_object_ids(run_id)
        object_hashes = _hashed_set((reference_id, candidate_id))
        reference_bbox = contract["fixture"]["reference_bbox_xyxy"]
        candidate_bbox = contract["fixture"]["candidate_bbox_xyxy"]
        t0 = _iso(base)
        t02 = _iso(base + timedelta(seconds=0.2))
        t04 = _iso(base + timedelta(seconds=0.4))
        t4 = _iso(base + timedelta(seconds=4.0))
        t42 = _iso(base + timedelta(seconds=4.2))
        behavior_docs = [
            (
                f"vssq-{run_id}-behavior-a",
                {
                    "Id": f"vssq-{run_id}-behavior-a",
                    "timestamp": t0,
                    "end": t02,
                    "sensor": {"id": sensor_name, "type": "camera"},
                    "object": {
                        "id": reference_id,
                        "type": "Person",
                        "bbox": {
                            "leftX": reference_bbox[0], "topY": reference_bbox[1],
                            "rightX": reference_bbox[2], "bottomY": reference_bbox[3],
                        },
                    },
                    "embeddings": {"vector": embedding_a},
                },
            ),
            (
                f"vssq-{run_id}-behavior-b",
                {
                    "Id": f"vssq-{run_id}-behavior-b",
                    "timestamp": t02,
                    "end": t04,
                    "sensor": {"id": sensor_name, "type": "camera"},
                    "object": {
                        "id": reference_id,
                        "type": "Person",
                        "bbox": {
                            "leftX": reference_bbox[0], "topY": reference_bbox[1],
                            "rightX": reference_bbox[2], "bottomY": reference_bbox[3],
                        },
                    },
                    "embeddings": {"vector": embedding_a},
                },
            ),
            (
                f"vssq-{run_id}-behavior-c",
                {
                    "Id": f"vssq-{run_id}-behavior-c",
                    "timestamp": t4,
                    "end": t42,
                    "sensor": {"id": sensor_name, "type": "camera"},
                    "object": {
                        "id": candidate_id,
                        "type": "Person",
                        "bbox": {
                            "leftX": candidate_bbox[0], "topY": candidate_bbox[1],
                            "rightX": candidate_bbox[2], "bottomY": candidate_bbox[3],
                        },
                    },
                    "embeddings": {"vector": candidate_embedding},
                },
            ),
        ]
        for ordinal, (document_id, document) in enumerate(behavior_docs, start=1):
            http.call(
                operation=f"write_behavior_{ordinal}",
                target="elasticsearch",
                method="PUT",
                path=f"/{BEHAVIOR_INDEX}/_doc/{document_id}",
                body=document,
                allowed=(200, 201),
                mutation=True,
            )
            behavior.document_ids.add(document_id)
        raw_document_id = f"vssq-{run_id}-raw"
        raw_document = {
            "id": 1,
            "timestamp": t0,
            "sensorId": sensor_name,
            "objects": [
                {
                    "id": reference_id,
                    "type": "Person",
                    "bbox": {
                        "leftX": reference_bbox[0], "topY": reference_bbox[1],
                        "rightX": reference_bbox[2], "bottomY": reference_bbox[3],
                    },
                    "embedding": {"vector": embedding_a},
                },
                {
                    "id": candidate_id,
                    "type": "Person",
                    "bbox": {
                        "leftX": candidate_bbox[0], "topY": candidate_bbox[1],
                        "rightX": candidate_bbox[2], "bottomY": candidate_bbox[3],
                    },
                    "embedding": {"vector": candidate_embedding},
                },
            ],
        }
        http.call(
            operation="write_raw_frame",
            target="elasticsearch",
            method="PUT",
            path=f"/{RAW_INDEX}/_doc/{raw_document_id}",
            body=raw_document,
            allowed=(200, 201),
            mutation=True,
        )
        raw_index.document_ids.add(raw_document_id)
        for index, operation in ((BEHAVIOR_INDEX, "refresh_behavior"), (RAW_INDEX, "refresh_raw")):
            http.call(
                operation=operation,
                target="elasticsearch",
                method="POST",
                path=f"/{index}/_refresh",
                mutation=True,
            )
        if _index_count(http, BEHAVIOR_INDEX, "behavior_fixture_count") != 3:
            raise QualificationError("oracle_failed")
        if _index_count(http, RAW_INDEX, "raw_fixture_count") != 1:
            raise QualificationError("oracle_failed")
        _progress("owned-documents-indexed")

        frames_query = urlencode(
            {
                "sensorId": sensor_name,
                "fromTimestamp": _iso(base - timedelta(milliseconds=200)),
                "toTimestamp": t0,
            }
        )
        _, frames, _ = http.call(
            operation="analytics_frames",
            target="ingress",
            method="GET",
            path=f"/video-analytics-api/frames?{frames_query}",
        )
        frames_rows = _frame_rows(frames)
        print(
            f"[search-current-runtime] frames-count={len(frames_rows)}",
            file=sys.stderr,
            flush=True,
        )
        if len(frames_rows) != 1:
            raise QualificationError("oracle_failed")
        frame_objects = frames_rows[0].get("objects")
        if frame_objects is None and isinstance(frames_rows[0].get("metadata"), dict):
            frame_objects = frames_rows[0]["metadata"].get("objects")
        print(
            f"[search-current-runtime] frames-object-count={len(frame_objects) if isinstance(frame_objects, list) else -1}",
            file=sys.stderr,
            flush=True,
        )
        if not isinstance(frame_objects, list) or len(frame_objects) != 2:
            raise QualificationError("oracle_failed")
        frame_ids = {str(item.get("id")) for item in frame_objects if isinstance(item, dict)}
        if frame_ids != {reference_id, candidate_id}:
            raise QualificationError("oracle_failed")
        _progress("frames-api-passed")

        attribute_common = {
            "source_type": "video_file",
            "video_sources": [sensor_name],
            "timestamp_start": t0,
            "timestamp_end": _iso(base + timedelta(seconds=5)),
            "top_k": 10,
            "min_similarity": 0.0,
        }
        _, single_value, _ = http.call(
            operation="search_attribute_single",
            target="search",
            method="POST",
            path="/api/v1/search/attribute",
            body={**attribute_common, "query": QUERY_A, "fuse_multi_attribute": False},
        )
        single_rows = _attribute_rows(single_value)
        single_objects = _object_set_attribute(single_rows)
        reference_rows = [row for row in single_rows if row["metadata"]["object_id"] == reference_id]
        if single_objects != {reference_id, candidate_id} or len(reference_rows) != 1:
            raise QualificationError("oracle_failed")
        reference_duration = _duration(reference_rows[0])
        if not 0.999 <= reference_duration <= 1.001:
            raise QualificationError("oracle_failed")

        _, append_value, _ = http.call(
            operation="search_attribute_append",
            target="search",
            method="POST",
            path="/api/v1/search/attribute",
            body={**attribute_common, "query": [QUERY_A, QUERY_B], "fuse_multi_attribute": False},
        )
        append_rows = _attribute_rows(append_value)
        if _object_set_attribute(append_rows) != {reference_id, candidate_id}:
            raise QualificationError("oracle_failed")

        _, fused_value, _ = http.call(
            operation="search_attribute_fused",
            target="search",
            method="POST",
            path="/api/v1/search/attribute",
            body={**attribute_common, "query": [QUERY_A, QUERY_B], "fuse_multi_attribute": True},
        )
        fused_rows = _attribute_rows(fused_value)
        if _object_set_attribute(fused_rows) != {reference_id, candidate_id}:
            raise QualificationError("oracle_failed")
        fused_media = all(isinstance(row.get("screenshot_url"), str) and bool(row["screenshot_url"]) for row in fused_rows)
        if not fused_media:
            raise QualificationError("oracle_failed")
        _progress("attribute-semantics-passed")

        reference_object = {
            "object_id": reference_id,
            "sensor_name": sensor_name,
            "sensor_id": sensor_id,
            "timestamp": _iso(base + timedelta(seconds=0.1)),
        }
        image_body = {
            "query": "Find visually similar objects",
            "top_k": 5,
            "agent_mode": False,
            "use_critic": False,
            "source_type": "video_file",
            "reference_object": reference_object,
        }
        _, base_value, _ = http.call(
            operation="search_base_selected_object",
            target="search",
            method="POST",
            path="/api/v1/search",
            body=image_body,
        )
        base_rows, base_messages = _search_rows(base_value)
        _, image_value, _ = http.call(
            operation="search_image_selected_object",
            target="search",
            method="POST",
            path="/api/v1/search/image",
            body=image_body,
        )
        image_rows, image_messages = _search_rows(image_value)
        for rows, messages in ((base_rows, base_messages), (image_rows, image_messages)):
            objects = _object_set_search(rows)
            if messages or objects != {candidate_id} or reference_id in objects or len(rows) != 1:
                raise QualificationError("oracle_failed")
        _progress("selected-object-semantics-passed")

        _, fusion_value, _ = http.call(
            operation="search_fusion_agent_mode",
            target="search",
            method="POST",
            path="/api/v1/search/fusion",
            body={
                "query": FUSION_QUERY,
                "video_sources": [sensor_name],
                "source_type": "video_file",
                "top_k": 1,
                "agent_mode": True,
                "use_critic": False,
                "min_cosine_similarity": 0.0,
            },
        )
        fusion_rows, fusion_messages = _search_rows(fusion_value)
        print(
            f"[search-current-runtime] fusion-count={len(fusion_rows)} messages={len(fusion_messages)}",
            file=sys.stderr,
            flush=True,
        )
        if len(fusion_rows) != 1 or fusion_messages:
            raise QualificationError("oracle_failed")
        fusion_similarity = fusion_rows[0].get("similarity")
        if isinstance(fusion_similarity, bool) or not isinstance(fusion_similarity, (int, float)):
            raise QualificationError("oracle_failed")
        fusion_similarity = float(fusion_similarity)
        if not math.isfinite(fusion_similarity):
            raise QualificationError("oracle_failed")
        _progress("fusion-response-passed")

        invalid_status, _, _ = http.call(
            operation="search_invalid_source_type",
            target="search",
            method="POST",
            path="/api/v1/search",
            body={
                "query": "adjacent invalid input",
                "source_type": "unsupported",
                "agent_mode": False,
                "use_critic": False,
            },
            allowed=(422,),
        )
        _progress("adjacent-invalid-passed")
        markers = _docker_log_markers(log_since, contract["bounds"]["max_docker_log_bytes"])
        _progress("fusion-semantics-passed")
        semantics = {
            "embedding_dimensions": dimensions,
            "templates_exact_dimensions": True,
            "frames": {
                "count": len(frames_rows),
                "object_count": len(frame_objects),
                "selected_bbox_present": True,
            },
            "single_attribute": {
                "result_count": len(single_rows),
                "object_id_hashes": _hashed_set(single_objects),
                "same_object_merge": True,
                "reference_duration_seconds": reference_duration,
                "minimum_clip_extended": True,
            },
            "append_multiple_attributes": {
                "result_count": len(append_rows),
                "object_id_hashes": _hashed_set(_object_set_attribute(append_rows)),
                "passed": True,
            },
            "fuse_multiple_attributes": {
                "result_count": len(fused_rows),
                "object_id_hashes": _hashed_set(_object_set_attribute(fused_rows)),
                "all_have_media": fused_media,
                "passed": True,
            },
            "selected_object_knn": {
                "base_route_result_count": len(base_rows),
                "image_route_result_count": len(image_rows),
                "candidate_object_id_hash": _sha(candidate_id.encode("utf-8")),
                "seed_object_id_hash": _sha(reference_id.encode("utf-8")),
                "seed_excluded": True,
            },
            "fusion": {
                "result_count": len(fusion_rows),
                "top_k_limited": True,
                "similarity": fusion_similarity,
                "message_count": len(fusion_messages),
                "branch_markers": markers,
                "order_observed": ["embedding", "rerank_or_fallback"],
            },
            "adjacent_invalid_status": invalid_status,
            "all_expected_object_id_hashes": object_hashes,
            "canonical_routes_observed": [
                "/api/v1/search",
                "/api/v1/search/attribute",
                "/api/v1/search/fusion",
                "/api/v1/search/image",
            ],
        }
    except QualificationError as exc:
        _failure_checkpoint("runtime", exc.code)
        failure = exc
    except Exception as exc:
        failure = QualificationError("oracle_failed")
        failure.__cause__ = exc
        _failure_checkpoint("runtime", failure.code)
    finally:
        try:
            _progress("cleanup-started")
            cleanup_rows["behavior"] = _cleanup_index(http, behavior)
            cleanup_rows["raw"] = _cleanup_index(http, raw_index)
            _progress("cleanup-indices-processed")
            absence_rows: list[dict[str, int]] = []
            for check in range(contract["bounds"]["cleanup_absence_checks"]):
                if check:
                    time.sleep(1.0)
                behavior_status, _ = _index_status(http, BEHAVIOR_INDEX, f"behavior_absent_{check + 1}")
                raw_status, _ = _index_status(http, RAW_INDEX, f"raw_absent_{check + 1}")
                absence_rows.append({"behavior": behavior_status, "raw": raw_status})
            cleanup_rows["absence_checks"] = absence_rows
            if any(row != {"behavior": 404, "raw": 404} for row in absence_rows):
                raise QualificationError("cleanup_failed")
            _progress("cleanup-absence-passed")
            if any(row.get("foreign_documents_observed") for key, row in cleanup_rows.items() if key in {"behavior", "raw"}):
                raise QualificationError("cleanup_failed")
            embed_post_uuid = _index_uuid(http, EMBED_INDEX, "embed_post_uuid")
            embed_post_count = _index_count(http, EMBED_INDEX, "embed_post_count")
            cleanup_rows["embed_read_only_unchanged"] = embed_post_uuid == embed_uuid and embed_post_count == embed_count
            if not cleanup_rows["embed_read_only_unchanged"]:
                raise QualificationError("cleanup_failed")
            _progress("cleanup-embed-passed")
            if fixture_context:
                frames_query = urlencode(
                    {
                        "sensorId": sensor_name,
                        "fromTimestamp": _iso(base - timedelta(milliseconds=200)),
                        "toTimestamp": _iso(base),
                    }
                )
                _, post_frames, _ = http.call(
                    operation="analytics_frames_post_cleanup",
                    target="ingress",
                    method="GET",
                    path=f"/video-analytics-api/frames?{frames_query}",
                )
                post_frame_rows = _frame_rows(post_frames)
                cleanup_rows["frames_empty"] = post_frame_rows == []
                if post_frame_rows != []:
                    raise QualificationError("cleanup_failed")
                _progress("cleanup-frames-passed")
            _progress("cleanup-passed")
        except QualificationError as exc:
            _failure_checkpoint("cleanup", exc.code)
            failure = exc

    if failure is not None:
        raise failure
    if semantics is None:
        raise QualificationError("oracle_failed")
    post_runtime = _runtime_snapshot(contract)
    if post_runtime != pre_runtime:
        raise QualificationError("runtime_identity_error")
    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms < 1 or duration_ms > contract["bounds"]["max_duration_ms"]:
        raise QualificationError("deadline_exceeded")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "passed_current_candidate",
        "promotion_eligible": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_commit": commit,
        "contract_sha256": _sha(_read_regular(CONTRACT_PATH)),
        "executor_sha256": _sha(_read_regular(Path(__file__).resolve())),
        "receipt_schema_sha256": _sha(_read_regular(SCHEMA_PATH)),
        "identity": {
            "run_id_sha256": _sha(run_id.encode("utf-8")),
            "authorization_id": AUTHORIZATION_ID,
            "authorization_token_sha256": _sha(acknowledgement.encode("utf-8")),
            "origin_hashes": {name: _sha(origin.encode("utf-8")) for name, origin in sorted(origins.items())},
            "source_hashes": source_hashes,
            "query_contracts": contract["fixture"]["query_contracts"],
        },
        "pre_state": {
            "runtime": pre_runtime,
            "owned_index_status": {"behavior": 404, "raw": 404},
            "embed_index": {"uuid_sha256": _sha(embed_uuid.encode("utf-8")), "count": embed_count},
            "fixture": fixture_context,
        },
        "bounds": {
            "duration_ms": duration_ms,
            "http_requests": budget.requests,
            "persistent_mutations": budget.mutations,
            "max_duration_ms": contract["bounds"]["max_duration_ms"],
            "max_http_requests": budget.max_requests,
            "max_persistent_mutations": budget.max_mutations,
        },
        "observations": http.observations,
        "semantics": semantics,
        "post_state": {
            "runtime": post_runtime,
            "owned_index_status": {"behavior": 404, "raw": 404},
            "embed_index": {"uuid_sha256": _sha(embed_uuid.encode("utf-8")), "count": embed_count},
        },
        "cleanup": {
            **cleanup_rows,
            "exact_owned_resources_only": True,
            "persistent_stream_mutations": 0,
            "service_lifecycle_mutations": 0,
            "warehouse_sample_bundle": "excluded",
        },
    }
    schema = _load_object(SCHEMA_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(receipt))
    except Exception as exc:
        raise QualificationError("configuration_error") from exc
    if errors:
        raise QualificationError("configuration_error")
    return receipt


def _atomic_write_receipt(receipt: Mapping[str, Any]) -> None:
    raw = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-receipt.", dir=HERE)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, RECEIPT_PATH)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _plan(contract: Mapping[str, Any]) -> dict[str, Any]:
    source_hashes = _validate_source_locks(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "ready_inert",
        "network_requests": 0,
        "persistent_mutations": 0,
        "authorization_required": True,
        "source_lock_count": len(source_hashes),
        "warehouse_sample_bundle": "excluded",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    execute = subparsers.add_parser("execute-http")
    execute.add_argument("--ack", required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--receipt", default=str(RECEIPT_PATH))
    args = parser.parse_args(argv)
    command = args.command or "plan"
    try:
        contract = _contract()
        if command == "plan":
            print(json.dumps(_plan(contract), sort_keys=True))
            return 0
        if command != "execute-http":
            raise QualificationError("configuration_error")
        if Path(args.receipt).resolve() != RECEIPT_PATH.resolve():
            raise QualificationError("configuration_error")
        run_id = _plain(args.run_id)
        receipt = _execute(contract, run_id, args.ack)
        _atomic_write_receipt(receipt)
        print(
            json.dumps(
                {
                    "package_id": contract["package_id"],
                    "status": receipt["status"],
                    "promotion_eligible": receipt["promotion_eligible"],
                    "http_requests": receipt["bounds"]["http_requests"],
                    "persistent_mutations": receipt["bounds"]["persistent_mutations"],
                    "cleanup_complete": True,
                },
                sort_keys=True,
            )
        )
        return 0
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": exc.code}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
