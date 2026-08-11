#!/usr/bin/env python3
"""Bounded current-Thor proof for RT-VLM Prometheus and OpenTelemetry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"


class QualificationError(RuntimeError):
    """A bounded qualification assertion failed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _verify_static(contract: dict[str, Any]) -> None:
    if contract["official_indices"] != [366]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _file_sha(path) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    prometheus = (REPO / contract["source_locks"][2]["path"]).read_text()
    if "job_name: 'rtvi-vlm'" not in prometheus or "metrics_path: /v1/metrics" not in prometheus:
        raise QualificationError("RT-VLM Prometheus scrape contract drifted")
    ledger = _load(REPO / contract["source_locks"][3]["path"])
    row = ledger["capabilities"][366]
    if (
        row.get("id") != contract["capability_ids"][0]
        or row.get("title") != "Prometheus and OpenTelemetry"
        or row.get("contract", {}).get("advertised_literal")
        != "Prometheus and OpenTelemetry"
    ):
        raise QualificationError("advertised capability row drifted")


def _endpoint(value: str, expected: str) -> str:
    value = value.rstrip("/")
    parsed = urllib.parse.urlparse(value)
    expected_parsed = urllib.parse.urlparse(expected)
    if (
        value != expected
        or parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != expected_parsed.port
    ):
        raise QualificationError("observability endpoint is not the frozen loopback endpoint")
    return value


def _http(endpoint: str, path: str, counter: list[int]) -> tuple[bytes, Any | None]:
    counter[0] += 1
    try:
        with urllib.request.urlopen(endpoint + path, timeout=15) as response:
            if response.status != 200:
                raise QualificationError(f"observability request was not HTTP 200: {path}")
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError(f"local observability request failed: {path}") from exc
    if "json" not in content_type.casefold():
        return raw, None
    try:
        return raw, json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"observability response was invalid JSON: {path}") from exc


def _docker(
    args: list[str],
    counter: list[int],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[bytes]:
    counter[0] += 1
    try:
        return subprocess.run(
            ["docker", *args],
            input=input_bytes,
            capture_output=True,
            check=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("bounded Docker command failed") from exc


def _inspect(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    runtime = contract["runtime"]
    raw = _docker(
        ["inspect", runtime["rt_vlm_container"], runtime["prometheus_container"]], counter
    ).stdout
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError("Docker inspect JSON was invalid") from exc
    by_name = {row.get("Name", "").lstrip("/"): row for row in rows}
    expected = {
        runtime["rt_vlm_container"]: runtime["rt_vlm_image_id"],
        runtime["prometheus_container"]: runtime["prometheus_image_id"],
    }
    for name, image in expected.items():
        row = by_name.get(name, {})
        state = row.get("State", {})
        if (
            row.get("Image") != image
            or state.get("Status") != "running"
            or state.get("Health", {}).get("Status") != "healthy"
            or state.get("OOMKilled") is not False
            or row.get("RestartCount") != 0
        ):
            raise QualificationError(f"runtime identity drifted: {name}")
    return {
        "rt_vlm_healthy": True,
        "rt_vlm_image_exact": True,
        "rt_vlm_restart_count": 0,
        "rt_vlm_oom_killed": False,
        "prometheus_healthy": True,
        "prometheus_image_exact": True,
        "prometheus_restart_count": 0,
        "prometheus_oom_killed": False,
    }


def _verify_live_sources(contract: dict[str, Any], counter: list[int]) -> None:
    locks = contract["source_locks"][:2]
    output = _docker(
        [
            "exec",
            contract["runtime"]["rt_vlm_container"],
            "sha256sum",
            *[lock["container_path"] for lock in locks],
        ],
        counter,
    ).stdout.decode()
    live = {line.split()[1]: line.split()[0] for line in output.splitlines() if line}
    for lock in locks:
        if live.get(lock["container_path"]) != lock["sha256"]:
            raise QualificationError(f"live source lock drifted: {lock['container_path']}")


REQUIRED_METRICS = {
    "target_info",
    "video_file_queries_processed",
    "video_file_queries_pending",
    "active_live_streams",
    "system_uptime_seconds",
    "e2e_latency_seconds_latest_seconds",
    "decode_latency_seconds_latest_seconds",
    "vlm_latency_seconds_latest_seconds",
}


def _metrics(raw: bytes) -> dict[str, Any]:
    text = raw.decode(errors="strict")
    if "not initialized" in text.casefold() or "# error" in text.casefold():
        raise QualificationError("RT-VLM Prometheus exporter reported an error")
    metric_names = {
        line.split()[2]
        for line in text.splitlines()
        if line.startswith("# TYPE ") and len(line.split()) >= 4
    }
    if not REQUIRED_METRICS.issubset(metric_names):
        raise QualificationError("RT-VLM Prometheus metric families were incomplete")
    if (
        'service_name="rtvi-vlm"' not in text
        or 'service_version="3.2.1"' not in text
        or 'telemetry_sdk_name="opentelemetry"' not in text
    ):
        raise QualificationError("RT-VLM OpenTelemetry resource labels were incomplete")
    return {
        "required_metric_families_present": True,
        "metric_family_count": len(metric_names),
        "service_name_exact": True,
        "service_version_exact": True,
        "otel_sdk_label_present": True,
    }


def _prometheus_target(value: Any) -> dict[str, Any]:
    targets = value.get("data", {}).get("activeTargets") if isinstance(value, dict) else None
    if not isinstance(targets, list):
        raise QualificationError("Prometheus target envelope was invalid")
    rows = [row for row in targets if row.get("labels", {}).get("job") == "rtvi-vlm"]
    if (
        len(rows) != 1
        or rows[0].get("health") != "up"
        or rows[0].get("lastError") not in ("", None)
        or rows[0].get("scrapeUrl") != "http://rtvi-vlm:8000/v1/metrics"
    ):
        raise QualificationError("Prometheus RT-VLM target was not healthy and exact")
    return {"target_count": 1, "target_up": True, "last_error_empty": True, "scrape_url_exact": True}


def _prometheus_query(value: Any) -> dict[str, Any]:
    results = value.get("data", {}).get("result") if isinstance(value, dict) else None
    if not isinstance(results, list) or len(results) != 1:
        raise QualificationError("Prometheus up query result was not singular")
    row = results[0]
    if (
        row.get("metric", {}).get("job") != "rtvi-vlm"
        or row.get("metric", {}).get("instance") != "rtvi-vlm:8000"
        or not isinstance(row.get("value"), list)
        or len(row["value"]) != 2
        or row["value"][1] != "1"
    ):
        raise QualificationError("Prometheus RT-VLM up query was not one")
    return {"series_count": 1, "job_exact": True, "instance_exact": True, "up_value": 1}


OTEL_PROBE = r'''
import json
from opentelemetry import metrics, trace
from utils import otel_helper

initialized = otel_helper.init_otel(
    service_name="rt-vlm-qualification",
    service_version="3.2.1",
)
tracer = trace.get_tracer("rt-vlm-qualification")
with tracer.start_as_current_span("rt-vlm-qualification-span") as span:
    span.set_attribute("qualification.marker", "local-console-export")
    span_recording = span.is_recording()
meter = metrics.get_meter("rt-vlm-qualification")
counter = meter.create_counter("rt-vlm-qualification-counter")
counter.add(1, {"qualification": "local"})
trace_flushed = trace.get_tracer_provider().force_flush(timeout_millis=5000)
metrics_flushed = metrics.get_meter_provider().force_flush(timeout_millis=5000)
print("VSS_OTEL_QUAL_RECEIPT=" + json.dumps({
    "initialized": initialized,
    "otel_enabled": otel_helper._otel_enabled,
    "tracer_present": otel_helper._tracer is not None,
    "meter_provider_present": otel_helper._meter_provider is not None,
    "prometheus_reader_present": otel_helper._prometheus_reader is not None,
    "span_recording": span_recording,
    "trace_flushed": trace_flushed,
    "metrics_flushed": metrics_flushed,
}, sort_keys=True))
trace.get_tracer_provider().shutdown()
metrics.get_meter_provider().shutdown()
'''


def _otel(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    fixture = contract["otel_fixture"]
    args = ["exec", "-i"]
    for value in (
        "ENABLE_OTEL_MONITORING=true",
        f"OTEL_TRACES_EXPORTER={fixture['trace_exporter']}",
        f"OTEL_METRICS_EXPORTER={fixture['metrics_exporter']}",
        f"OTEL_METRIC_EXPORT_INTERVAL={fixture['metric_export_interval_ms']}",
    ):
        args.extend(["-e", value])
    args.extend(
        [
            "-w",
            "/opt/nvidia/rtvi/rtvi",
            contract["runtime"]["rt_vlm_container"],
            "python3",
            "-",
        ]
    )
    raw = _docker(args, counter, input_bytes=OTEL_PROBE.encode()).stdout
    text = raw.decode(errors="replace")
    prefix = "VSS_OTEL_QUAL_RECEIPT="
    matches = [line[len(prefix) :] for line in text.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise QualificationError("OpenTelemetry production probe omitted its receipt")
    try:
        receipt = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise QualificationError("OpenTelemetry production receipt was invalid JSON") from exc
    expected = {
        "initialized": True,
        "otel_enabled": True,
        "tracer_present": True,
        "meter_provider_present": True,
        "prometheus_reader_present": True,
        "span_recording": True,
        "trace_flushed": True,
        "metrics_flushed": True,
    }
    if receipt != expected:
        raise QualificationError("OpenTelemetry production probe assertions differed")
    required_signals = (
        fixture["span_name"],
        fixture["counter_name"],
        fixture["service_name"],
        '"qualification.marker": "local-console-export"',
        '"value": 1',
    )
    if not all(signal in text for signal in required_signals):
        raise QualificationError("OpenTelemetry console exports omitted required signals")
    return {
        **expected,
        "console_span_export_present": True,
        "console_metric_export_present": True,
        "service_resource_exact": True,
        "export_output_sha256": _sha(raw),
    }


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "status": "inert_prometheus_otel_plan_valid",
        "contract_sha256": _file_sha(CONTRACT_PATH),
        "http_requests": 0,
        "docker_commands": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    runtime = contract["runtime"]
    rt_endpoint = _endpoint(runtime["rt_vlm_endpoint"], "http://127.0.0.1:8018")
    prometheus_endpoint = _endpoint(
        runtime["prometheus_endpoint"], "http://127.0.0.1:9090"
    )
    http_counter = [0]
    docker_counter = [0]

    identity_before = _inspect(contract, docker_counter)
    _verify_live_sources(contract, docker_counter)
    pre_metrics_raw, _ = _http(rt_endpoint, "/v1/metrics", http_counter)
    pre_metrics = _metrics(pre_metrics_raw)
    _, targets_value = _http(prometheus_endpoint, "/api/v1/targets", http_counter)
    target = _prometheus_target(targets_value)
    _, query_value = _http(
        prometheus_endpoint,
        "/api/v1/query?query=up%7Bjob%3D%22rtvi-vlm%22%7D",
        http_counter,
    )
    query = _prometheus_query(query_value)
    otel = _otel(contract, docker_counter)
    post_metrics_raw, _ = _http(rt_endpoint, "/v1/metrics", http_counter)
    post_metrics = _metrics(post_metrics_raw)
    identity_after = _inspect(contract, docker_counter)

    execution = contract["execution"]
    if http_counter[0] != execution["max_http_requests"]:
        raise QualificationError("HTTP request budget was not exact")
    if docker_counter[0] != execution["max_docker_commands"]:
        raise QualificationError("Docker command budget was not exact")
    if pre_metrics != post_metrics:
        raise QualificationError("RT-VLM Prometheus metric contract changed")
    if identity_before != identity_after:
        raise QualificationError("runtime identity changed")
    duration = round(time.monotonic() - started, 6)
    if duration > execution["max_duration_seconds"]:
        raise QualificationError("qualification exceeded its duration budget")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _file_sha(CONTRACT_PATH),
        "duration_seconds": duration,
        "budget": {
            "http_requests": http_counter[0],
            "max_http_requests": execution["max_http_requests"],
            "model_requests": 0,
            "max_model_requests": 0,
            "docker_commands": docker_counter[0],
            "max_docker_commands": execution["max_docker_commands"],
            "support_processes_peak": 1,
            "max_support_processes": execution["max_support_processes"],
        },
        "runtime_identity": identity_after,
        "prometheus_endpoint": {
            **post_metrics,
            "content_sha256": _sha(post_metrics_raw),
            "http_status": 200,
        },
        "prometheus_scrape": target,
        "prometheus_query": query,
        "opentelemetry": otel,
        "cleanup": {
            "isolated_otel_process_exited": True,
            "main_metrics_contract_preserved": True,
            "rt_vlm_identity_preserved": True,
            "prometheus_identity_preserved": True,
        },
        "policy": {
            "agent_generate_calls": 0,
            "asset_mutations": 0,
            "stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "raw_trace_ids_retained": False,
            "raw_span_ids_retained": False,
            "credentials_retained": False,
            "warehouse_sample_bundle": "excluded",
        },
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
