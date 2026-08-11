#!/usr/bin/env python3
"""Bounded current-Thor proof for RT-VLM asset limits and TTL expiry."""

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
    if contract["official_indices"] != [364]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _file_sha(path) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    compose = (REPO / contract["source_locks"][1]["path"]).read_text()
    expected_mount = (
        "services/rtvi/rt-vlm/src/utils/asset_manager.py:"
        "/opt/nvidia/rtvi/rtvi/utils/asset_manager.py:ro"
    )
    if expected_mount not in compose:
        raise QualificationError("official-edge asset-manager source overlay is absent")
    ledger = _load(REPO / contract["source_locks"][2]["path"])
    row = ledger["capabilities"][364]
    if (
        row.get("id") != contract["capability_ids"][0]
        or row.get("title") != "asset limits and expiry"
        or row.get("contract", {}).get("advertised_literal") != "asset limits and expiry"
    ):
        raise QualificationError("advertised capability row drifted")


def _validate_endpoint(endpoint: str, contract: dict[str, Any]) -> str:
    endpoint = endpoint.rstrip("/")
    parsed = urllib.parse.urlparse(endpoint)
    if (
        endpoint != contract["execution"]["endpoint"]
        or parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 8018
    ):
        raise QualificationError("endpoint must be the frozen loopback RT-VLM endpoint")
    return endpoint


def _http_json(endpoint: str, path: str, counter: list[int]) -> tuple[bytes, Any]:
    counter[0] += 1
    try:
        with urllib.request.urlopen(endpoint + path, timeout=15) as response:
            if response.status != 200:
                raise QualificationError(f"RT-VLM {path} was not HTTP 200")
            raw = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError(f"local RT-VLM request failed: {path}") from exc
    try:
        return raw, json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"RT-VLM returned non-JSON: {path}") from exc


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
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("bounded Docker command failed") from exc


def _inspect(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    raw = _docker(["inspect", contract["execution"]["container"]], counter).stdout
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError("Docker inspect JSON was invalid") from exc
    if not isinstance(rows, list) or len(rows) != 1:
        raise QualificationError("Docker inspect envelope was invalid")
    row = rows[0]
    state = row.get("State", {})
    destination = contract["source_locks"][0]["container_path"]
    mounts = [mount for mount in row.get("Mounts", []) if mount.get("Destination") == destination]
    expected_source = str(REPO / contract["source_locks"][0]["path"])
    if (
        state.get("Status") != "running"
        or state.get("Health", {}).get("Status") != "healthy"
        or state.get("OOMKilled") is not False
        or row.get("RestartCount") != 0
        or row.get("Image") != contract["model"]["image_id"]
        or len(mounts) != 1
        or mounts[0].get("Source") != expected_source
        or mounts[0].get("RW") is not False
    ):
        raise QualificationError("RT-VLM runtime or source-overlay identity drifted")
    return {
        "healthy": True,
        "image_exact": True,
        "restart_count": 0,
        "oom_killed": False,
        "asset_manager_overlay_exact": True,
        "asset_manager_overlay_read_only": True,
    }


def _verify_live_source(contract: dict[str, Any], counter: list[int]) -> None:
    lock = contract["source_locks"][0]
    output = _docker(
        ["exec", contract["execution"]["container"], "sha256sum", lock["container_path"]],
        counter,
    ).stdout.decode()
    fields = output.split()
    if len(fields) != 2 or fields[0] != lock["sha256"] or fields[1] != lock["container_path"]:
        raise QualificationError("live AssetManager source does not match the lock")


def _stats(value: Any) -> dict[str, Any]:
    expected = {
        "asset_count": 0,
        "asset_count_with_storage": 0,
        "aged_out_count": 0,
        "oldest_asset_age_hours": 0.0,
        "max_storage_usage_gb": None,
        "max_asset_age_hours": None,
    }
    if value != expected:
        raise QualificationError("main RT-VLM asset statistics were not pristine")
    return expected


def _models(value: Any, expected_id: str) -> str:
    rows = value.get("data") if isinstance(value, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or rows[0].get("id") != expected_id
        or value.get("audio_support") is not False
    ):
        raise QualificationError("RT-VLM model inventory drifted")
    return _sha(_canonical(value))


STORAGE_PROBE = r'''
import asyncio
import json
import os
import shutil
import tempfile
import time
from common.service_exception import ServiceException
from utils.asset_manager import AssetManager

class Reader:
    def __init__(self, size, byte):
        self.remaining = size
        self.byte = byte
    async def read(self, _requested):
        if self.remaining <= 0:
            return b""
        count = min(self.remaining, 131072)
        self.remaining -= count
        return self.byte * count

async def main():
    callbacks = []
    root = tempfile.mkdtemp(prefix="vss-asset-limit-qual-")
    result = {}
    try:
        manager = AssetManager(
            root,
            max_storage_usage_gb=1.0 / 1024.0,
            asset_removal_callback=lambda asset: callbacks.append(asset.filename) or True,
        )
        time.sleep(0.2)
        old_id = await manager.save_file(
            Reader(600 * 1024, b"o"), "old.bin", "vision", "video", None, "storage-old"
        )
        old_time = time.time() - 120
        os.utime(manager.get_asset(old_id).asset_dir, (old_time, old_time))
        kept_id = await manager.save_file(
            Reader(512 * 1024, b"k"), "kept.bin", "vision", "video", None, "storage-kept"
        )
        stats = manager.get_stats()
        result["pressure_eviction"] = {
            "oldest_evicted": not manager.check_asset_exists(old_id),
            "newest_preserved": manager.check_asset_exists(kept_id),
            "aged_out_count": stats["aged_out_count"],
            "callback_count": len(callbacks),
            "configured_max_storage_gb": stats["max_storage_usage_gb"],
        }
        kept = manager.get_asset(kept_id)
        kept.lock()
        error = None
        try:
            await manager.save_file(
                Reader(2 * 1024 * 1024, b"b"),
                "blocked.bin", "vision", "video", None, "storage-blocked",
            )
        except ServiceException as exc:
            error = {"code": exc.code, "status_code": exc.status_code}
        result["hard_limit"] = {
            "busy_asset_preserved": manager.check_asset_exists(kept_id),
            "blocked_asset_absent": not manager.check_asset_exists("storage-blocked"),
            "error": error,
        }
        kept.unlock()
        manager.cleanup_asset(kept_id)
        result["cleanup"] = {
            "asset_count": manager.get_stats()["asset_count"],
            "root_entry_count": len(os.listdir(root)),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
    result["temporary_root_absent"] = not os.path.exists(root)
    print("VSS_ASSET_LIMIT_RECEIPT=" + json.dumps(result, sort_keys=True))

asyncio.run(main())
'''


TTL_PROBE = r'''
import asyncio
import json
import os
import shutil
import tempfile
import time
from utils.asset_manager import AssetManager

class Reader:
    def __init__(self, byte):
        self.remaining = 2048
        self.byte = byte
    async def read(self, _requested):
        if self.remaining <= 0:
            return b""
        count = min(self.remaining, 1024)
        self.remaining -= count
        return self.byte * count

async def main():
    callbacks = []
    root = tempfile.mkdtemp(prefix="vss-asset-ttl-qual-")
    result = {}
    try:
        manager = AssetManager(
            root, asset_removal_callback=lambda asset: callbacks.append(asset.filename) or True
        )
        time.sleep(0.2)
        old_id = await manager.save_file(Reader(b"o"), "old.bin", "vision", "video", None, "ttl-old")
        busy_id = await manager.save_file(Reader(b"b"), "busy.bin", "vision", "video", None, "ttl-busy")
        fresh_id = await manager.save_file(Reader(b"f"), "fresh.bin", "vision", "video", None, "ttl-fresh")
        old_time = time.time() - 10
        os.utime(manager.get_asset(old_id).asset_dir, (old_time, old_time))
        os.utime(manager.get_asset(busy_id).asset_dir, (old_time, old_time))
        manager.get_asset(busy_id).lock()
        before = manager.get_stats()
        await manager._ttl_expire_assets()
        after = manager.get_stats()
        result["ttl"] = {
            "configured_max_age_hours": before["max_asset_age_hours"],
            "old_expired": not manager.check_asset_exists(old_id),
            "busy_expired_asset_preserved": manager.check_asset_exists(busy_id),
            "fresh_asset_preserved": manager.check_asset_exists(fresh_id),
            "aged_out_count": after["aged_out_count"],
            "callback_count": len(callbacks),
        }
        manager.get_asset(busy_id).unlock()
        manager.cleanup_asset(busy_id)
        manager.cleanup_asset(fresh_id)
        result["cleanup"] = {
            "asset_count": manager.get_stats()["asset_count"],
            "root_entry_count": len(os.listdir(root)),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
    result["temporary_root_absent"] = not os.path.exists(root)
    print("VSS_ASSET_TTL_RECEIPT=" + json.dumps(result, sort_keys=True))

asyncio.run(main())
'''


def _probe(
    contract: dict[str, Any],
    script: str,
    marker: str,
    counter: list[int],
    *,
    environment: str | None = None,
) -> dict[str, Any]:
    args = ["exec", "-i"]
    if environment:
        args.extend(["-e", environment])
    args.extend(
        [
            "-w",
            "/opt/nvidia/rtvi/rtvi",
            contract["execution"]["container"],
            "python3",
            "-",
        ]
    )
    output = _docker(args, counter, input_bytes=script.encode()).stdout.decode(errors="replace")
    prefix = marker + "="
    matches = [line[len(prefix) :] for line in output.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise QualificationError("isolated production AssetManager probe omitted its receipt")
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise QualificationError("isolated AssetManager receipt was invalid JSON") from exc
    if not isinstance(value, dict):
        raise QualificationError("isolated AssetManager receipt was not an object")
    return value


def _validate_storage(value: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    fixture = contract["storage_fixture"]
    expected = {
        "pressure_eviction": {
            "oldest_evicted": True,
            "newest_preserved": True,
            "aged_out_count": 1,
            "callback_count": 1,
            "configured_max_storage_gb": fixture["max_storage_gb"],
        },
        "hard_limit": {
            "busy_asset_preserved": True,
            "blocked_asset_absent": True,
            "error": {
                "code": fixture["expected_error_code"],
                "status_code": fixture["expected_http_status"],
            },
        },
        "cleanup": {"asset_count": 0, "root_entry_count": 0},
        "temporary_root_absent": True,
    }
    if value != expected:
        raise QualificationError("production storage-limit semantics differed")
    return value


def _validate_ttl(value: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "ttl": {
            "configured_max_age_hours": contract["ttl_fixture"]["max_age_hours"],
            "old_expired": True,
            "busy_expired_asset_preserved": True,
            "fresh_asset_preserved": True,
            "aged_out_count": 1,
            "callback_count": 1,
        },
        "cleanup": {"asset_count": 0, "root_entry_count": 0},
        "temporary_root_absent": True,
    }
    if value != expected:
        raise QualificationError("production TTL-expiry semantics differed")
    return value


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "status": "inert_asset_limits_expiry_plan_valid",
        "contract_sha256": _file_sha(CONTRACT_PATH),
        "http_requests": 0,
        "docker_commands": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    endpoint = _validate_endpoint(endpoint, contract)
    http_counter = [0]
    docker_counter = [0]

    identity_before = _inspect(contract, docker_counter)
    _verify_live_source(contract, docker_counter)
    stats_before_raw, stats_before_value = _http_json(endpoint, "/v1/assets/stats", http_counter)
    stats_before = _stats(stats_before_value)
    models_before_raw, models_before_value = _http_json(endpoint, "/v1/models", http_counter)
    models_before_sha = _models(models_before_value, contract["model"]["id"])

    storage = _validate_storage(
        _probe(contract, STORAGE_PROBE, "VSS_ASSET_LIMIT_RECEIPT", docker_counter), contract
    )
    ttl = _validate_ttl(
        _probe(
            contract,
            TTL_PROBE,
            "VSS_ASSET_TTL_RECEIPT",
            docker_counter,
            environment="ASSET_MAX_AGE_HOURS=0.001",
        ),
        contract,
    )

    stats_after_raw, stats_after_value = _http_json(endpoint, "/v1/assets/stats", http_counter)
    stats_after = _stats(stats_after_value)
    models_after_raw, models_after_value = _http_json(endpoint, "/v1/models", http_counter)
    models_after_sha = _models(models_after_value, contract["model"]["id"])
    identity_after = _inspect(contract, docker_counter)

    execution = contract["execution"]
    if http_counter[0] != execution["max_http_requests"]:
        raise QualificationError("HTTP request budget was not exact")
    if docker_counter[0] != execution["max_docker_commands"]:
        raise QualificationError("Docker command budget was not exact")
    if stats_before != stats_after or stats_before_raw != stats_after_raw:
        raise QualificationError("main RT-VLM asset state changed")
    if models_before_sha != models_after_sha or models_before_raw != models_after_raw:
        raise QualificationError("RT-VLM model inventory changed")
    if identity_before != identity_after:
        raise QualificationError("RT-VLM runtime identity changed")
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
            "max_model_requests": execution["max_model_requests"],
            "docker_commands": docker_counter[0],
            "max_docker_commands": execution["max_docker_commands"],
            "support_processes_peak": 1,
            "max_support_processes": execution["max_support_processes"],
        },
        "runtime_identity": identity_after,
        "main_runtime": {
            "asset_stats_sha256": _sha(stats_after_raw),
            "asset_catalog_pristine": True,
            "asset_limits_disabled_in_main_runtime": True,
            "model_inventory_sha256": models_after_sha,
            "model_inventory_unchanged": True,
        },
        "storage_limit": storage,
        "ttl_expiry": ttl,
        "cleanup": {
            "isolated_storage_catalog_empty": True,
            "isolated_ttl_catalog_empty": True,
            "isolated_temporary_roots_absent": True,
            "main_asset_statistics_restored_exactly": True,
            "main_model_inventory_restored_exactly": True,
            "runtime_identity_restored_exactly": True,
        },
        "policy": {
            "agent_generate_calls": 0,
            "main_asset_catalog_mutations": 0,
            "stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "raw_resource_ids_retained": False,
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
    execute_parser.add_argument("--endpoint", default="http://127.0.0.1:8018")
    args = parser.parse_args()
    contract = _load(CONTRACT_PATH)
    try:
        if (args.mode or "plan") == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract, args.endpoint)
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
