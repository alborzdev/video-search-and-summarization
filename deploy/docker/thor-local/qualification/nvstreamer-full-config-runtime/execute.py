#!/usr/bin/env python3
"""Qualify the complete documented NvStreamer configuration contract on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
BASE = "http://127.0.0.1:31012/vst/api/v1"
CONTAINER = "vss-qual-nvstreamer-full-config"
IMAGE = "vss-vios-nvstreamer:3.2.1-thor-local"
BASE_CONFIG = (
    REPO
    / "services/vios/deployment/stream-processing/docker-compose/nvstreamer/configs/vst_config.json"
)
STORAGE_CONFIG = (
    REPO
    / "services/vios/deployment/stream-processing/docker-compose/nvstreamer/configs/vst_storage.json"
)
PARSER_SOURCE = REPO / "services/vios/src/framework/utilities/config.cpp"
PRINT_SOURCE = REPO / "services/vios/src/framework/apis/common/device_manager.cpp"
CONTRACT = HERE / "fixture-contract.json"
OVERRIDES = HERE / "config-overrides.json"
CAPABILITY_ID = "configuration.nvstreamer.full-contract"
TCP_PORTS = (31012, 31656)
UDP_PORTS = (31656,)
MAX_RESPONSE = 2 * 1024 * 1024
DOCUMENTED_SECTIONS = (
    "network",
    "onvif",
    "data",
    "notifications",
    "debug",
    "overlay",
    "security",
)
ADDED_KEYS = {
    "data.enable_aging_policy",
    "data.use_centralize_local_db",
    "debug.update_record_details_in_sec",
}


class QualificationError(RuntimeError):
    """The bounded complete-config transaction did not pass."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha(path.read_bytes())


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON in {label}: {value}")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {label}") from exc


def _run(
    command: list[str], *, timeout: int = 30, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        detail = stderr.decode(errors="replace")[-1200:]
        raise QualificationError(f"command failed: {command[0]}: {detail}") from exc


def _docker_ids(*, running: bool) -> list[str]:
    command = ["docker", "ps", "--no-trunc", "--format", "{{.ID}}"]
    if not running:
        command.insert(2, "-a")
    return sorted(line for line in _run(command).stdout.decode().splitlines() if line)


def _container_exists() -> bool:
    return (
        _run(["docker", "container", "inspect", CONTAINER], check=False).returncode == 0
    )


def _port_free(protocol: str, port: int) -> bool:
    kind = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    with socket.socket(socket.AF_INET, kind) as stream:
        stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            stream.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _documented_paths(contract: dict[str, Any]) -> set[str]:
    sections = contract.get("sections")
    if not isinstance(sections, dict) or tuple(sections) != DOCUMENTED_SECTIONS:
        raise QualificationError("documented section order or shape drifted")
    paths: list[str] = []
    expected_counts = contract.get("section_parameter_counts")
    if not isinstance(expected_counts, dict):
        raise QualificationError("section parameter counts are absent")
    for section, keys in sections.items():
        if not isinstance(keys, list) or any(
            not isinstance(key, str) or not key for key in keys
        ):
            raise QualificationError(f"invalid documented keys: {section}")
        if len(keys) != expected_counts.get(section) or len(keys) != len(set(keys)):
            raise QualificationError(f"documented key count drift: {section}")
        paths.extend(f"{section}.{key}" for key in keys)
    source = contract.get("official_source", {})
    if (
        len(paths) != source.get("parameter_count")
        or len(paths) != len(set(paths))
        or source.get("parameter_count") != 151
        or source.get("section_count") != 7
    ):
        raise QualificationError("official complete-table denominator drifted")
    if set(contract["runtime_fixture"]["missing_documented_keys_added"]) != ADDED_KEYS:
        raise QualificationError("explicit documented-key additions drifted")
    return set(paths)


def _deep_merge(
    base: dict[str, Any],
    overrides: dict[str, Any],
    documented: set[str],
    prefix: str = "",
) -> None:
    for key, value in overrides.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if key not in base or not isinstance(base[key], dict):
                raise QualificationError(f"config override changes object type: {path}")
            _deep_merge(base[key], value, documented, path)
        else:
            if key not in base and path not in ADDED_KEYS:
                raise QualificationError(
                    f"config override references unknown key: {path}"
                )
            if path in ADDED_KEYS and path not in documented:
                raise QualificationError(f"config addition is not documented: {path}")
            base[key] = value


def _derived_config(output: Path, contract: dict[str, Any]) -> dict[str, Any]:
    base = _strict_json(BASE_CONFIG.read_bytes(), "base NvStreamer config")
    overrides = _strict_json(OVERRIDES.read_bytes(), "complete-config overrides")
    if not isinstance(base, dict) or not isinstance(overrides, dict):
        raise QualificationError("NvStreamer config inputs must be JSON objects")
    documented = _documented_paths(contract)
    base_before = {
        f"{section}.{key}"
        for section in DOCUMENTED_SECTIONS
        for key in contract["sections"][section]
        if key in base.get(section, {})
    }
    if documented - base_before != ADDED_KEYS:
        raise QualificationError("shipped config/documented-table delta drifted")
    _deep_merge(base, overrides, documented)
    explicit = {
        f"{section}.{key}"
        for section in DOCUMENTED_SECTIONS
        for key in contract["sections"][section]
        if key in base.get(section, {})
    }
    if explicit != documented:
        raise QualificationError("derived fixture does not carry all documented keys")
    network = base["network"]
    data = base["data"]
    notifications = base["notifications"]
    security = base["security"]
    if (
        network.get("http_port") != "31012"
        or network.get("server_domain_name") != "127.0.0.1"
        or network.get("stunurl_list") != ["127.0.0.1:3478"]
        or network.get("rtsp_server_port") != 31656
        or network.get("rtsp_server_instances_count") != 1
        or data.get("enable_aging_policy") is not True
        or data.get("use_centralize_local_db") is not False
        or notifications.get("enable_notification") is not False
        or notifications.get("enable_notification_consumer") is not False
        or security.get("use_https") is not False
        or security.get("use_rtsp_authentication") is not False
        or security.get("use_http_digest_authentication") is not False
        or security.get("nv_org_id")
        or security.get("nv_ngc_key")
    ):
        raise QualificationError("derived fixture escaped its exact local-only policy")
    output.write_bytes(json.dumps(base, indent=2, sort_keys=True).encode() + b"\n")
    return base


def _source_parser_coverage(contract: dict[str, Any]) -> dict[str, Any]:
    source = PARSER_SOURCE.read_text()
    documented = _documented_paths(contract)
    observed: set[str] = set()
    for section in DOCUMENTED_SECTIONS:
        for key in contract["sections"][section]:
            pattern = rf'{re.escape(section)}\.get\("{re.escape(key)}"'
            if re.search(pattern, source):
                observed.add(f"{section}.{key}")
    missing = sorted(documented - observed)
    if missing:
        raise QualificationError(
            f"documented config keys absent from parser: {missing}"
        )
    print_source = PRINT_SOURCE.read_text()
    for marker in (
        "void DeviceConfig::printInfo()",
        "NV Streamer Sync File Count",
        "Update Record Details in sec",
        "Use HTTPS authentication",
        "Calibration Mode",
    ):
        if marker not in print_source:
            raise QualificationError(
                f"runtime config print source marker absent: {marker}"
            )
    return {
        "documented_parameter_count": len(documented),
        "parser_match_count": len(observed),
        "missing_parser_keys": missing,
        "parser_source_sha256": _sha_file(PARSER_SOURCE),
        "runtime_print_source_sha256": _sha_file(PRINT_SOURCE),
    }


class Client:
    def __init__(self, base: str = BASE) -> None:
        if base != BASE:
            raise QualificationError(
                "complete-config endpoint must remain loopback-bound"
            )
        self.base = base
        self.receipts: list[dict[str, Any]] = []

    def request(
        self, path: str, *, method: str = "GET", payload: Any = None, timeout: int = 5
    ) -> tuple[int, Any]:
        if not path.startswith("/") or "#" in path or method not in {"GET", "POST"}:
            raise QualificationError("unsafe HTTP request")
        body = None if payload is None else _canonical(payload)
        headers = {} if body is None else {"Content-Type": "application/json"}
        request = urllib.request.Request(
            self.base + path, data=body, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0]
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(MAX_RESPONSE + 1)
            content_type = (exc.headers.get("Content-Type") or "").split(";", 1)[0]
        except (OSError, urllib.error.URLError) as exc:
            raise QualificationError(
                f"NvStreamer request failed: {method} {path}"
            ) from exc
        if len(raw) > MAX_RESPONSE:
            raise QualificationError(f"oversized NvStreamer response: {method} {path}")
        value = _strict_json(raw, f"{method} {path}")
        self.receipts.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "request_sha256": None if body is None else _sha(body),
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "content_type": content_type,
            }
        )
        return status, value

    def json(self, path: str, *, timeout: int = 5) -> Any:
        status, value = self.request(path, timeout=timeout)
        if status != 200:
            raise QualificationError(f"unexpected HTTP {status}: GET {path}")
        return value


def _start_container(root: Path, config: Path) -> dict[str, Any]:
    media = root / "media"
    data = root / "data"
    media.mkdir()
    data.mkdir()
    media.chmod(0o777)
    data.chmod(0o777)
    image = _strict_json(
        _run(["docker", "image", "inspect", IMAGE]).stdout, "image inspect"
    )
    if (
        not isinstance(image, list)
        or len(image) != 1
        or image[0].get("Architecture") != "arm64"
    ):
        raise QualificationError(
            "the exact Thor-local NvStreamer arm64 image is absent"
        )
    labels = image[0].get("Config", {}).get("Labels", {})
    if labels.get("com.nvidia.vss.thor.vios-runtime-network-install") != "disabled":
        raise QualificationError(
            "NvStreamer image is not the offline Thor-local derivative"
        )
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        CONTAINER,
        "--label",
        "com.nvidia.vss.thor.qualifier=nvstreamer-full-config-runtime",
        "--runtime",
        "nvidia",
        "--memory",
        "4g",
        "--cpus",
        "4",
        "--pids-limit",
        "1024",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--network",
        "bridge",
        "--publish",
        "127.0.0.1:31012:31012/tcp",
        "--publish",
        "127.0.0.1:31656:31656/tcp",
        "--publish",
        "127.0.0.1:31656:31656/udp",
        "--env",
        "ADAPTOR=streamer",
        "--env",
        "HTTP_PORT=31012",
        "--env",
        "NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES=false",
        "--volume",
        f"{config}:/home/vst/vst_release/configs/vst_config.json:ro",
        "--volume",
        f"{STORAGE_CONFIG}:/home/vst/vst_release/configs/vst_storage.json:ro",
        "--volume",
        f"{media}:/home/vst/vst_release/streamer_videos",
        "--volume",
        f"{data}:/home/vst/vst_release/vst_data",
        IMAGE,
    ]
    container_id = _run(command, timeout=45).stdout.decode().strip()
    if len(container_id) != 64:
        raise QualificationError("Docker did not return a full container ID")
    return {
        "container_id": container_id,
        "image_id": image[0].get("Id"),
        "image_repo_digests": image[0].get("RepoDigests") or [],
        "image_size_bytes": image[0].get("Size"),
        "image_architecture": image[0].get("Architecture"),
        "offline_runtime_install": labels.get(
            "com.nvidia.vss.thor.vios-runtime-network-install"
        ),
        "codec_package_set": labels.get("com.nvidia.vss.thor.vios-codec-package-set"),
    }


def _wait_for_version(client: Client, timeout: int = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _container_exists():
            state = (
                _run(
                    ["docker", "inspect", CONTAINER, "--format", "{{.State.Status}}"],
                    check=False,
                )
                .stdout.decode()
                .strip()
            )
            if state == "exited":
                raise QualificationError("isolated NvStreamer exited before readiness")
        try:
            value = client.json("/sensor/version", timeout=2)
            if isinstance(value, dict) and value.get("type") == "streamer":
                return value
        except QualificationError:
            pass
        time.sleep(1)
    raise QualificationError("NvStreamer did not become ready")


def _path(config: dict[str, Any], dotted: str) -> Any:
    value: Any = config
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise QualificationError(f"config assertion path is absent: {dotted}")
        value = value[part]
    return value


def _readback(client: Client, config: dict[str, Any]) -> dict[str, Any]:
    responses: dict[str, dict[str, Any]] = {}
    for service in ("sensor", "storage", "live", "replay", "proxy"):
        value = client.json(f"/{service}/configuration")
        if not isinstance(value, dict) or not value:
            raise QualificationError(
                f"configuration readback is not an object: {service}"
            )
        responses[service] = value
    assertions = (
        ("network.http_port", "sensor", "httpPort", "stringified"),
        ("network.stunurl_list", "live", "stunUrlList", "exact"),
        ("network.rtsp_server_port", "proxy", "rtspServerPort", "exact"),
        (
            "network.rtsp_server_instances_count",
            "proxy",
            "rtsp_server_instances_count",
            "exact",
        ),
        (
            "onvif.device_discovery_timeout_secs",
            "sensor",
            "deviceDiscoveryTimeoutSeconds",
            "exact",
        ),
        ("onvif.default_resolution", "sensor", "defaultResolution", "exact"),
        ("data.enable_aging_policy", "storage", "enableAgingPolicy", "exact"),
        (
            "data.max_video_download_size_MB",
            "storage",
            "maxVideoDownloadSizeMB",
            "exact",
        ),
        (
            "data.enable_dec_low_latency_mode",
            "live",
            "enableDecLowLatencyMode",
            "exact",
        ),
        ("notifications.enable_notification", "sensor", "enableNotification", "exact"),
        ("notifications.use_message_broker", "sensor", "useMessageBroker", "exact"),
        ("notifications.message_broker_topic", "sensor", "messageBrokerTopic", "exact"),
        ("debug.enable_qos_monitoring", "proxy", "enableQosMonitoring", "exact"),
        ("debug.enable_prometheus", "proxy", "enablePrometheus", "exact"),
        ("overlay.video_metadata_server", "live", "videoMetadataServer", "exact"),
        ("overlay.calibration_mode", "live", "calibrationMode", "exact"),
        ("overlay.use_camera_groups", "live", "useCameraGroups", "exact"),
        ("security.use_https", "sensor", "useHttps", "exact"),
        ("security.use_rtsp_authentication", "proxy", "useRtspAuthentication", "exact"),
        (
            "security.use_http_digest_authentication",
            "sensor",
            "useHttpDigestAuthentication",
            "exact",
        ),
        ("security.session_max_age_sec", "proxy", "sessionMaxAgeSec", "exact"),
    )
    results: list[dict[str, Any]] = []
    for config_path, service, field, mode in assertions:
        expected = _path(config, config_path)
        observed = responses[service].get(field)
        passed = (
            str(observed) == str(expected)
            if mode == "stringified"
            else observed == expected
        )
        if not passed:
            raise QualificationError(
                f"configuration readback mismatch: {service}.{field}: {observed!r} != {expected!r}"
            )
        results.append(
            {
                "config_path": config_path,
                "service": service,
                "field": field,
                "expected": expected,
                "observed": observed,
                "status": "passed",
            }
        )
    return {
        "services": {
            service: {
                "status": 200,
                "field_count": len(value),
                "canonical_sha256": _sha(_canonical(value)),
            }
            for service, value in responses.items()
        },
        "assertions": results,
    }


def _round_trip(client: Client, original: list[str]) -> dict[str, Any]:
    alternate = ["127.0.0.2:3478"]
    status, _ = client.request(
        "/live/configuration", method="POST", payload={"stunUrlList": alternate}
    )
    changed = client.json("/live/configuration")
    if status != 200 or changed.get("stunUrlList") != alternate:
        raise QualificationError("live configuration did not apply/read back")
    restore_status, _ = client.request(
        "/live/configuration", method="POST", payload={"stunUrlList": original}
    )
    restored = client.json("/live/configuration")
    if restore_status != 200 or restored.get("stunUrlList") != original:
        raise QualificationError("live configuration did not restore/read back")
    return {
        "field": "stunUrlList",
        "initial": original,
        "alternate": alternate,
        "apply_status": status,
        "changed_readback": changed["stunUrlList"],
        "restore_status": restore_status,
        "restored_readback": restored["stunUrlList"],
        "status": "passed",
    }


def _runtime_logs() -> dict[str, Any]:
    process = _run(["docker", "logs", CONTAINER], check=False)
    raw = process.stdout + process.stderr
    text = raw.decode(errors="replace")
    markers = (
        "Host HTTP port: 31012",
        "Sensor Discovery Timeout(secs): 10",
        "enable aging policy: 1",
        "Message Broker used: redis",
        "Enable QoS Monitoring: 1",
        "Calibration Mode: synthetic",
        "Use HTTPS authentication: 0",
        "RTSP server port: 31656",
        "NV Streamer max upload file size: 10000",
        "NV Streamer Sync File Count: 0",
        "Enable MEGA Simulation: 0",
        "Update Record Details in sec: 10",
    )
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise QualificationError(f"runtime config log markers are absent: {missing}")
    return {
        "raw_sha256": _sha(raw),
        "bytes": len(raw),
        "marker_count": len(markers),
        "marker_sha256s": {marker: _sha(marker.encode()) for marker in markers},
        "missing_markers": missing,
    }


def _chmod_owned_mounts() -> None:
    _run(
        [
            "docker",
            "exec",
            CONTAINER,
            "/bin/sh",
            "-c",
            "find /home/vst/vst_release/vst_data /home/vst/vst_release/streamer_videos -exec chmod a+rwX {} +",
        ],
        check=False,
    )


def _stop_remove_container(cleanup: list[dict[str, Any]]) -> None:
    if not _container_exists():
        return
    _chmod_owned_mounts()
    stop = _run(
        ["docker", "stop", "--timeout", "20", CONTAINER], timeout=30, check=False
    )
    cleanup.append({"operation": "container-stop", "status": stop.returncode})
    remove = _run(["docker", "rm", CONTAINER], check=False)
    cleanup.append({"operation": "container-remove", "status": remove.returncode})


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise QualificationError("unsafe receipt output")
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def execute() -> dict[str, Any]:
    if _container_exists():
        raise QualificationError(
            f"reserved qualifier container already exists: {CONTAINER}"
        )
    occupied = [
        f"{protocol}/{port}"
        for protocol, ports in (("tcp", TCP_PORTS), ("udp", UDP_PORTS))
        for port in ports
        if not _port_free(protocol, port)
    ]
    if occupied:
        raise QualificationError(f"reserved qualifier ports are occupied: {occupied}")
    inputs = (
        BASE_CONFIG,
        STORAGE_CONFIG,
        PARSER_SOURCE,
        PRINT_SOURCE,
        CONTRACT,
        OVERRIDES,
    )
    if not all(path.is_file() and not path.is_symlink() for path in inputs):
        raise QualificationError("qualification inputs are missing or symlinked")
    contract = _strict_json(CONTRACT.read_bytes(), "fixture contract")
    if not isinstance(contract, dict) or contract.get("capability_id") != CAPABILITY_ID:
        raise QualificationError("fixture contract identity drifted")
    parser_coverage = _source_parser_coverage(contract)
    non_owned_all_before = _docker_ids(running=False)
    non_owned_running_before = _docker_ids(running=True)
    cleanup: list[dict[str, Any]] = []
    primary_error: Exception | None = None
    result: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="vss-nvstreamer-full-config-") as directory:
        root = Path(directory)
        config_path = root / "vst_config.json"
        derived_config = _derived_config(config_path, contract)
        client = Client()
        try:
            container = _start_container(root, config_path)
            version = _wait_for_version(client)
            mounted = _run(
                [
                    "docker",
                    "exec",
                    CONTAINER,
                    "cat",
                    "/home/vst/vst_release/configs/vst_config.json",
                ]
            ).stdout
            if _strict_json(mounted, "mounted config") != derived_config:
                raise QualificationError(
                    "mounted runtime config differs from derived fixture"
                )
            readback = _readback(client, derived_config)
            round_trip = _round_trip(client, derived_config["network"]["stunurl_list"])
            logs = _runtime_logs()
            result = {
                "schema_version": 1,
                "qualification_id": "thor-vss-3.2.1-nvstreamer-full-config-runtime",
                "captured_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "status": "passed",
                "runtime_evidence": True,
                "target": {
                    "product_version": "3.2.1",
                    "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                },
                "capability_results": {CAPABILITY_ID: "passed_current"},
                "bounds": {
                    "http_endpoint": BASE,
                    "http_loopback_only": True,
                    "rtsp_endpoint": "rtsp://127.0.0.1:31656",
                    "rtsp_loopback_only": True,
                    "external_downloads": False,
                    "runtime_package_installs": False,
                    "external_services_contacted": False,
                    "warehouse_sample_bundle_used": False,
                    "main_vios_sensor_added": False,
                    "rt_cv_stream_added": False,
                    "agent_generate_called": False,
                    "existing_container_count": len(non_owned_all_before),
                    "existing_running_container_count": len(non_owned_running_before),
                },
                "identity": {
                    "image": container,
                    "service_version": version,
                    "contract_sha256": _sha_file(CONTRACT),
                    "base_config_sha256": _sha_file(BASE_CONFIG),
                    "storage_config_sha256": _sha_file(STORAGE_CONFIG),
                    "overrides_sha256": _sha_file(OVERRIDES),
                    "derived_config_sha256": _sha_file(config_path),
                    "derived_config_canonical_sha256": _sha(_canonical(derived_config)),
                    "mounted_config_sha256": _sha(mounted),
                    "executor_sha256": _sha_file(Path(__file__).resolve()),
                },
                "official_contract": {
                    **contract["official_source"],
                    "sections": list(contract["sections"]),
                    "section_parameter_counts": contract["section_parameter_counts"],
                    "explicit_runtime_parameter_count": sum(
                        len(contract["sections"][section])
                        for section in DOCUMENTED_SECTIONS
                    ),
                    "missing_runtime_parameters": [],
                    "shipped_config_missing_keys_added": sorted(ADDED_KEYS),
                },
                "source_parser_coverage": parser_coverage,
                "observations": {
                    "configuration_readback": readback,
                    "reversible_round_trip": round_trip,
                    "startup_config_readback": logs,
                    "request_accounting": {
                        "http_response_count": len(client.receipts),
                        "http_failure_count": sum(
                            1 for item in client.receipts if item["status"] != 200
                        ),
                    },
                },
                "cleanup": {"result": "pending_container_cleanup", "attempts": cleanup},
                "requests": client.receipts,
            }
        except Exception as exc:
            primary_error = exc
        finally:
            _stop_remove_container(cleanup)

        non_owned_all_after = _docker_ids(running=False)
        non_owned_running_after = _docker_ids(running=True)
        restoration = {
            "exact_container_inventory_restored": non_owned_all_after
            == non_owned_all_before,
            "exact_running_set_restored": non_owned_running_after
            == non_owned_running_before,
            "all_reserved_ports_released": all(
                _port_free(protocol, port)
                for protocol, ports in (("tcp", TCP_PORTS), ("udp", UDP_PORTS))
                for port in ports
            ),
        }
        if not all(restoration.values()):
            raise QualificationError(
                f"non-owned Docker/port state was not restored: {restoration}"
            )
        if primary_error is not None:
            if isinstance(primary_error, QualificationError):
                raise primary_error
            raise QualificationError(
                "NvStreamer complete-config transaction failed"
            ) from primary_error
        if result is None:
            raise QualificationError(
                "NvStreamer complete-config transaction produced no result"
            )
        result["cleanup"].update(restoration)
        result["cleanup"]["result"] = "passed"
        result["cleanup"]["attempts"] = cleanup
        result["cleanup"]["temporary_tree_removed_by_context"] = True
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="run the bounded isolated mutation"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "failed", "error": "--execute is required"}))
        return 2
    try:
        receipt = execute()
        output = args.output.resolve()
        _write_receipt(output, receipt)
    except (OSError, QualificationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "output": str(output),
                "receipt_sha256": _sha(output.read_bytes()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
