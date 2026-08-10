#!/usr/bin/env python3
"""Qualify the LVS custom-model environment and custom-prompt contract on Thor."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Callable
from uuid import UUID


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
ACK = "I_ACK_LVS_CUSTOM_MODEL_PROMPT_AND_EXACT_CLEANUP"
MAX_STATIC_BYTES = 128 * 1024 * 1024
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
sys.dont_write_bytecode = True


class QualificationError(RuntimeError):
    """Stable fail-closed error code for the qualification boundary."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "evidence_already_retained",
        "invalid_response",
        "oracle_failed",
        "runtime_unavailable",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError("invalid_response")
        value[key] = item
    return value


def _decode(raw: bytes, *, object_only: bool = True) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                QualificationError("invalid_response")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("invalid_response") from exc
    if object_only and not isinstance(value, dict):
        raise QualificationError("invalid_response")
    return value


def _read_regular(path: Path, maximum: int = MAX_STATIC_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise QualificationError("configuration_error")
        pieces: list[bytes] = []
        total = 0
        while total <= maximum:
            piece = os.read(descriptor, min(131072, maximum + 1 - total))
            if not piece:
                break
            pieces.append(piece)
            total += len(piece)
        raw = b"".join(pieces)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise QualificationError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path)
    value = _decode(raw)
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationError("invalid_response") from exc


def _canonical_sha(value: Any) -> str:
    return _sha(_canonical(value))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _base_call(
    function: Callable[..., Any],
    *args: Any,
    fallback: str = "oracle_failed",
    **kwargs: Any,
) -> Any:
    try:
        return function(*args, **kwargs)
    except QualificationError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", fallback)
        if code not in QualificationError.CODES:
            code = fallback
        raise QualificationError(code) from exc


def _safe_repo_file(relative: str, expected_sha: str, expected_bytes: int) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise QualificationError("configuration_error")
    current = REPO
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise QualificationError("configuration_error")
        except QualificationError:
            raise
        except OSError as exc:
            raise QualificationError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(REPO.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc
    raw = _read_regular(current)
    if len(raw) != expected_bytes or _sha(raw) != expected_sha:
        raise QualificationError("configuration_error")
    return current


def _load_base(contract: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    dependency = contract["base_dependency"]
    executor = dependency["executor"]
    executor_path = _safe_repo_file(
        executor["path"], executor["sha256"], executor["bytes"]
    )
    contract_row = dependency["contract"]
    base_contract_path = _safe_repo_file(
        contract_row["path"], contract_row["sha256"], contract_row["bytes"]
    )
    module_name = "_thor_lvs_formats_runtime_for_custom_model_prompt"
    spec = importlib.util.spec_from_file_location(module_name, executor_path)
    if spec is None or spec.loader is None:
        raise QualificationError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise QualificationError("configuration_error") from exc
    base_contract, base_raw = _base_call(
        module._load, base_contract_path, fallback="configuration_error"
    )
    if _sha(base_raw) != contract_row["sha256"]:
        raise QualificationError("configuration_error")
    _base_call(module._verify_static, base_contract, fallback="configuration_error")
    return module, base_contract


def _custom_prompt() -> str:
    return (
        "You are an advanced intelligent video analysis system specialized in analyzing "
        "activity monitoring and generating captions.\n\n"
        "Focus on detecting these events: notable activity. Also watch for these objects "
        "of interest: . Describe all events and objects of interest throughout the video. "
        "Emphasize concise descriptions suitable for an edge-AI demonstration.\n\n\n\n"
        "Provide the result in json format with 'seconds' for time depiction for each event. "
        "Use keywords 'start_time', 'end_time', 'description', \"type\" in the json output. "
        '"type" should be the event type and chosen from [notable activity] only. You MUST '
        "include 'type', 'start_time', 'end_time', 'description' in json output. This is very "
        "important and you must follow this strictly.\n\n"
        '[\n{\n "start_time": t_start, #(MANDATORY)\n "end_time": t_end, #(MANDATORY)\n '
        '"type": Choose from [notable activity] #(MANDATORY)\n "description": EVENT1, '
        "#(MANDATORY)\n},\n]"
    )


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "acknowledgement",
        "adjacent_negative",
        "asset",
        "autonomous_hitl_defaults",
        "base_dependency",
        "capability_id",
        "cleanup",
        "containers",
        "default_execution_enabled",
        "endpoints",
        "execution_bounds",
        "live_model_configuration",
        "model_id",
        "official_contract",
        "prompt_contract",
        "render_probe",
        "schema_version",
        "service_contract",
        "source_anchors",
        "source_fixture",
        "summarization",
        "target",
        "tool_id",
        "transport",
    }
    if set(contract) != expected_keys:
        raise QualificationError("configuration_error")
    if (
        contract["schema_version"] != 1
        or contract["tool_id"] != "thor-lvs-custom-model-prompt-runtime"
        or contract["capability_id"] != "configuration.lvs.custom-model-prompt"
        or contract["acknowledgement"] != ACK
        or contract["default_execution_enabled"] is not False
        or contract["target"]
        != {
            "product_version": "3.2.1",
            "ga_commit": "7640d917047cf7b0fd3085eefb8282754b56bc94",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "captured_on": "2026-07-31",
        }
        or contract["official_contract"]
        != {
            "custom_model_environment": True,
            "prompt_override": True,
            "output_shape_must_match": True,
            "faq_sections": [
                "How do I use a custom VLM model in the Video Summarization microservice?",
                "How can I change the VLM prompt for summarization?",
            ],
            "faq_lines": "234-254",
            "verified_on": "2026-08-10",
        }
        or contract["endpoints"]
        != {
            "lvs_origin": "http://127.0.0.1:38111",
            "rt_vlm_origin": "http://127.0.0.1:8018",
        }
        or contract["model_id"]
        != "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
        or contract["service_contract"]
        != {
            "lvs_metadata_version": "3.0.0",
            "lvs_metadata_sub_version": "d16a216",
            "lvs_metadata_port": "38111",
            "lvs_model_count": 1,
        }
        or contract["autonomous_hitl_defaults"]
        != {"scenario": "activity monitoring", "events": ["notable activity"]}
    ):
        raise QualificationError("configuration_error")

    prompt_raw = _custom_prompt().encode("utf-8")
    if contract["prompt_contract"] != {
        "override_vlm_prompt": True,
        "custom_prompt_bytes": 905,
        "custom_prompt_sha256": "de33d71c5ee43453f8d1956dc3e3738d8901c6cab5ff5bc55515c6e64b7ddb84",
        "maximum_prompt_characters": 512000,
        "required_caption_event_keys": [
            "description",
            "end_time",
            "start_time",
            "type",
        ],
        "required_summary_keys": [
            "events",
            "total_events",
            "uuids",
            "video_summary",
        ],
    } or len(prompt_raw) != 905 or _sha(prompt_raw) != contract["prompt_contract"][
        "custom_prompt_sha256"
    ]:
        raise QualificationError("configuration_error")

    if contract["render_probe"] != {
        "profile": "bp_developer_lvs_2d",
        "model_root": "/tmp/vss-custom-model-root",
        "model_path": "/tmp/vss-custom-model-root/checkpoint",
        "model_selector": "vllm-compatible",
        "served_model_id": "custom-served-id",
        "lvs_model_root_mounted": True,
        "rt_vlm_model_root_mounted_read_only": True,
    } or contract["live_model_configuration"] != {
        "container": "vss-rtvi-vlm",
        "environment": {
            "MODEL_PATH": "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final",
            "MODEL_ROOT_DIR": str(REPO / "deploy/docker/data-dir/models"),
            "NUM_GPUS": "1",
            "VLM_BATCH_SIZE": "1",
            "VLM_MODEL_TO_USE": "cosmos-reason3",
        },
        "model_root_mount": {
            "source": str(REPO / "deploy/docker/data-dir/models"),
            "destination": str(REPO / "deploy/docker/data-dir/models"),
            "type": "bind",
            "read_only": True,
        },
        "ngc_cache_mount": {
            "destination": "/opt/nvidia/rtvi/.rtvi/ngc_model_cache",
            "type": "bind",
        },
        "served_model": {
            "id": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            "owned_by": "custom",
            "api_type": "internal",
            "audio_support": False,
        },
    }:
        raise QualificationError("configuration_error")

    source = contract["source_fixture"]
    source_path = _safe_repo_file(source["path"], source["sha256"], source["bytes"])
    if source["duration_seconds"] != 10.0 or source["warehouse_sample_bundle"] is not False:
        raise QualificationError("configuration_error")

    anchors = contract["source_anchors"]
    if not isinstance(anchors, list) or len(anchors) != 6:
        raise QualificationError("configuration_error")
    anchored: list[dict[str, Any]] = []
    for row in anchors:
        if set(row) != {"path", "bytes", "sha256", "required_literals"}:
            raise QualificationError("configuration_error")
        path = _safe_repo_file(row["path"], row["sha256"], row["bytes"])
        raw = _read_regular(path)
        literals = row["required_literals"]
        if (
            not isinstance(literals, list)
            or not literals
            or any(not isinstance(item, str) or not item for item in literals)
            or any(item.encode("utf-8") not in raw for item in literals)
        ):
            raise QualificationError("configuration_error")
        anchored.append(
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "required_literal_count": len(literals),
            }
        )

    asset = contract["asset"]
    try:
        identifier = UUID(str(asset["asset_id"]))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("configuration_error") from exc
    if identifier.version != 4 or asset != {
        "asset_id": "00000000-0000-4000-8000-000000000041",
        "filename": "vss-lvs-custom-prompt.mp4",
        "sensor_name": "vss-lvs-custom-model-prompt",
        "mime_type": "video/mp4",
    }:
        raise QualificationError("configuration_error")
    if contract["adjacent_negative"] != {
        "model_id": "vss-invalid-custom-model-probe",
        "expected_http_status": 400,
        "expected_error_code": "BadParameters",
    }:
        raise QualificationError("configuration_error")
    if contract["summarization"] != {
        "chunk_duration": 10,
        "fixed_frames_per_chunk": 8,
        "use_fps_for_chunking": False,
        "seed": 1,
        "max_tokens": 256,
        "expected_chunks_processed": 1,
    }:
        raise QualificationError("configuration_error")
    if contract["execution_bounds"] != {
        "max_duration_seconds": 420,
        "max_http_requests": 19,
        "max_semantic_actions": 2,
        "min_free_bytes": 10737418240,
        "network_scope": "numeric-loopback-only",
        "model_staging": "forbidden",
        "service_lifecycle": "forbidden",
        "warehouse_sample_bundle": "excluded",
    } or contract["transport"] != {
        "max_request_bytes": 4194304,
        "max_response_bytes": 16777216,
        "short_timeout_seconds": 15,
        "summarize_timeout_seconds": 240,
        "tool_timeout_seconds": 120,
    }:
        raise QualificationError("configuration_error")
    cleanup = contract["cleanup"]
    if (
        cleanup.get("logical_namespace")
        != "vss-oracle-configuration-lvs-custom-model-prompt"
        or cleanup.get("target_ids") != [asset["asset_id"]]
        or len(cleanup.get("postconditions", [])) != 4
    ):
        raise QualificationError("configuration_error")

    base, base_contract = _load_base(contract)
    if contract["containers"] != base_contract["containers"]:
        raise QualificationError("configuration_error")
    return {
        "base": base,
        "base_contract": base_contract,
        "source_path": source_path,
        "source_anchors": anchored,
    }


def plan() -> dict[str, Any]:
    contract, raw = _load(CONTRACT_PATH)
    static = _verify_static(contract)
    return {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "plan",
        "status": "passed",
        "contract_sha256": _sha(raw),
        "capability_id": contract["capability_id"],
        "source_anchor_count": len(static["source_anchors"]),
        "execution_bounds": contract["execution_bounds"],
        "acknowledgement_required": True,
        "writes_or_lifecycle_actions": False,
        "warehouse_sample_bundle": False,
    }


def _run(
    args: list[str],
    *,
    cwd: Path,
    deadline: float,
    timeout: float,
    env: dict[str, str] | None = None,
    maximum: int = 32 * 1024 * 1024,
) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QualificationError("oracle_failed")
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(timeout, max(0.1, remaining)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_unavailable") from exc
    if completed.returncode != 0 or len(completed.stdout) > maximum:
        raise QualificationError("runtime_unavailable")
    return completed.stdout


def _render_custom_model(contract: dict[str, Any], *, deadline: float) -> dict[str, Any]:
    probe = contract["render_probe"]
    docker_dir = REPO / "deploy/docker"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
        "VSS_REPO_ROOT": str(REPO),
        "SDR_CONTROLLER_CONFIG_PATH": str(
            docker_dir / "services/infra/sdrc"
        ),
        "MODEL_ROOT_DIR": probe["model_root"],
        "RTVI_VLM_MODEL_TO_USE": probe["model_selector"],
        "RTVI_VLM_MODEL_PATH": probe["model_path"],
        "VLM_NAME": probe["served_model_id"],
    }
    raw = _run(
        [
            "/usr/bin/docker",
            "compose",
            "--env-file",
            "thor-local/generated.env",
            "-f",
            "compose.yml",
            "-f",
            "thor-local/compose.yml",
            "--profile",
            probe["profile"],
            "config",
            "--format",
            "json",
        ],
        cwd=docker_dir,
        deadline=deadline,
        timeout=contract["transport"]["tool_timeout_seconds"],
        env=env,
    )
    rendered = _decode(raw)
    try:
        lvs = rendered["services"]["lvs-server"]
        rt_vlm = rendered["services"]["rtvi-vlm"]
        lvs_env = lvs["environment"]
        rt_env = rt_vlm["environment"]
        lvs_volumes = lvs["volumes"]
        rt_volumes = rt_vlm["volumes"]
    except (KeyError, TypeError) as exc:
        raise QualificationError("oracle_failed") from exc
    lvs_mounts = [
        row
        for row in lvs_volumes
        if isinstance(row, dict) and row.get("target") == probe["model_root"]
    ]
    rt_mounts = [
        row
        for row in rt_volumes
        if isinstance(row, dict) and row.get("target") == probe["model_root"]
    ]
    if (
        lvs_env.get("MODEL_ROOT_DIR") != probe["model_root"]
        or lvs_env.get("NGC_MODEL_CACHE") != probe["model_root"]
        or rt_env.get("MODEL_ROOT_DIR") != probe["model_root"]
        or rt_env.get("VLM_MODEL_TO_USE") != probe["model_selector"]
        or rt_env.get("MODEL_PATH") != probe["model_path"]
        or len(lvs_mounts) != 1
        or lvs_mounts[0].get("source") != probe["model_root"]
        or lvs_mounts[0].get("type") != "bind"
        or lvs_mounts[0].get("read_only", False) is not False
        or len(rt_mounts) != 1
        or rt_mounts[0].get("source") != probe["model_root"]
        or rt_mounts[0].get("type") != "bind"
        or rt_mounts[0].get("read_only") is not True
        or not probe["model_path"].startswith(probe["model_root"] + "/")
    ):
        raise QualificationError("oracle_failed")
    return {
        "model_selector_exact": True,
        "model_path_exact": True,
        "model_path_below_model_root": True,
        "lvs_model_root_environment_exact": True,
        "lvs_model_root_mount_exact": True,
        "rt_vlm_model_root_environment_exact": True,
        "rt_vlm_model_root_mount_exact": True,
        "rt_vlm_model_root_mount_read_only": True,
        "rendered_projection_sha256": _canonical_sha(
            {
                "lvs": {
                    "MODEL_ROOT_DIR": lvs_env["MODEL_ROOT_DIR"],
                    "NGC_MODEL_CACHE": lvs_env["NGC_MODEL_CACHE"],
                    "model_root_mount": lvs_mounts[0],
                },
                "rt_vlm": {
                    "MODEL_ROOT_DIR": rt_env["MODEL_ROOT_DIR"],
                    "VLM_MODEL_TO_USE": rt_env["VLM_MODEL_TO_USE"],
                    "MODEL_PATH": rt_env["MODEL_PATH"],
                    "model_root_mount": rt_mounts[0],
                },
            }
        ),
    }


def _live_model_configuration(
    contract: dict[str, Any], *, deadline: float
) -> dict[str, Any]:
    expected = contract["live_model_configuration"]
    raw = _run(
        ["/usr/bin/docker", "inspect", expected["container"]],
        cwd=REPO,
        deadline=deadline,
        timeout=30,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    value = _decode(raw, object_only=False)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise QualificationError("runtime_unavailable")
    item = value[0]
    env_rows = item.get("Config", {}).get("Env")
    mounts = item.get("Mounts")
    if not isinstance(env_rows, list) or not isinstance(mounts, list):
        raise QualificationError("runtime_unavailable")
    environment: dict[str, str] = {}
    for row in env_rows:
        if not isinstance(row, str) or "=" not in row:
            raise QualificationError("runtime_unavailable")
        key, val = row.split("=", 1)
        if key in environment:
            raise QualificationError("runtime_unavailable")
        environment[key] = val
    if any(environment.get(key) != val for key, val in expected["environment"].items()):
        raise QualificationError("runtime_unavailable")
    root = expected["model_root_mount"]
    root_rows = [row for row in mounts if row.get("Destination") == root["destination"]]
    cache = expected["ngc_cache_mount"]
    cache_rows = [row for row in mounts if row.get("Destination") == cache["destination"]]
    if (
        len(root_rows) != 1
        or root_rows[0].get("Source") != root["source"]
        or root_rows[0].get("Type") != root["type"]
        or root_rows[0].get("RW") is not False
        or len(cache_rows) != 1
        or cache_rows[0].get("Type") != cache["type"]
    ):
        raise QualificationError("runtime_unavailable")
    return {
        "container": expected["container"],
        "environment": dict(expected["environment"]),
        "model_root_mount_exact": True,
        "model_root_mount_read_only": True,
        "ngc_cache_mount_present": True,
    }


def _rt_vlm_models(client: Any, contract: dict[str, Any], phase: str) -> dict[str, Any]:
    response = client.request(
        "rt_vlm", f"{phase}-rt-vlm-models", "GET", "/v1/models"
    )
    value = _base_call(client_module(client)._json_response, response)
    expected = contract["live_model_configuration"]["served_model"]
    data = value.get("data")
    if (
        response.status != 200
        or value.get("object") != "list"
        or value.get("audio_support") is not expected["audio_support"]
        or not isinstance(data, list)
        or len(data) != 1
        or not isinstance(data[0], dict)
        or data[0].get("id") != expected["id"]
        or data[0].get("owned_by") != expected["owned_by"]
        or data[0].get("api_type") != expected["api_type"]
        or data[0].get("object") != "model"
        or type(data[0].get("created")) is not int
    ):
        raise QualificationError("runtime_unavailable")
    return {
        "http_status": response.status,
        "model_count": 1,
        "served_model_id": expected["id"],
        "owned_by": expected["owned_by"],
        "api_type": expected["api_type"],
        "audio_support": expected["audio_support"],
    }


def client_module(client: Any) -> Any:
    """Return the imported base module owning a LoopbackBudget instance."""

    return sys.modules[client.__class__.__module__]


def _openapi_contract(client: Any, contract: dict[str, Any]) -> dict[str, Any]:
    response = client.request("lvs", "lvs-openapi", "GET", "/openapi.json")
    value = _base_call(client_module(client)._json_response, response)
    try:
        schema = value["components"]["schemas"]["SummarizationQuery"]
        required = schema["required"]
        prompt_field = schema["properties"]["prompt"]
        override_field = schema["properties"]["override_vlm_prompt"]
    except (KeyError, TypeError) as exc:
        raise QualificationError("oracle_failed") from exc
    projection = {
        "required": required,
        "prompt": {
            key: prompt_field.get(key)
            for key in ("default", "description", "maxLength", "type")
        },
        "override_vlm_prompt": {
            key: override_field.get(key)
            for key in ("default", "description", "type")
        },
    }
    if (
        response.status != 200
        or not all(item in required for item in ("model", "scenario", "events"))
        or projection["prompt"]
        != {
            "default": "",
            "description": "Prompt for summary generation",
            "maxLength": contract["prompt_contract"]["maximum_prompt_characters"],
            "type": "string",
        }
        or projection["override_vlm_prompt"]
        != {
            "default": False,
            "description": "Override the VLM prompt with the user supplied prompt",
            "type": "boolean",
        }
    ):
        raise QualificationError("oracle_failed")
    return {
        "http_status": response.status,
        "required_fields_present": True,
        "custom_prompt_maximum_exact": True,
        "override_flag_default_false": True,
        "projection_sha256": _canonical_sha(projection),
    }


def _summary_request(
    contract: dict[str, Any], *, model: str
) -> dict[str, Any]:
    settings = contract["summarization"]
    defaults = contract["autonomous_hitl_defaults"]
    return {
        "id": contract["asset"]["asset_id"],
        "model": model,
        "scenario": defaults["scenario"],
        "events": defaults["events"],
        "override_vlm_prompt": True,
        "prompt": _custom_prompt(),
        "enable_vlm_structured_output": True,
        "chunk_duration": settings["chunk_duration"],
        "num_frames_per_second_or_fixed_frames_chunk": settings[
            "fixed_frames_per_chunk"
        ],
        "use_fps_for_chunking": settings["use_fps_for_chunking"],
        "seed": settings["seed"],
        "max_tokens": settings["max_tokens"],
    }


def _validate_custom_summary(
    base: Any, response: Any, contract: dict[str, Any]
) -> dict[str, Any]:
    summary = _base_call(
        base._validate_summary,
        response,
        identifier=contract["asset"]["asset_id"],
        model=contract["model_id"],
        expected_chunks=contract["summarization"]["expected_chunks_processed"],
    )
    value = _base_call(base._json_response, response)
    try:
        content = value["choices"][0]["message"]["content"]
        structured = _decode(content.encode("utf-8"))
        events = structured["events"]
        total_events = structured["total_events"]
        uuids = structured["uuids"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("invalid_response") from exc
    required_summary = set(contract["prompt_contract"]["required_summary_keys"])
    required_event = set(contract["prompt_contract"]["required_caption_event_keys"])
    if (
        set(structured) != required_summary
        or not isinstance(events, list)
        or not events
        or any(not isinstance(event, dict) or not required_event.issubset(event) for event in events)
        or type(total_events) is not int
        or total_events != len(events)
        or not isinstance(uuids, list)
        or len(uuids) != 1
    ):
        raise QualificationError("oracle_failed")
    summary.update(
        {
            "summary_shape_exact": True,
            "caption_event_shape_compatible": True,
            "event_count": len(events),
            "total_events_exact": True,
            "source_uuid_count": len(uuids),
        }
    )
    return summary


def _privacy_walk(value: Any) -> None:
    forbidden_keys = {
        "request_id",
        "video_id",
        "asset_id",
        "prompt",
        "system_prompt",
        "summary",
        "content",
        "authorization",
        "access_token",
        "refresh_token",
        "sdp",
        "ice",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise QualificationError("configuration_error")
            _privacy_walk(item)
    elif isinstance(value, list):
        for item in value:
            _privacy_walk(item)
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            UUID_RE.search(value)
            or "nvapi-" in lowered
            or "bearer " in lowered
            or "http://" in lowered
            or "https://" in lowered
        ):
            raise QualificationError("configuration_error")


def _retain_receipt(receipt: dict[str, Any]) -> None:
    raw = (
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    temporary = HERE / f".runtime-receipt.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, 0o644)
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(temporary, RECEIPT_PATH)
    except FileExistsError as exc:
        raise QualificationError("evidence_already_retained") from exc
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def execute(acknowledgement: str, *, retain: bool) -> dict[str, Any]:
    contract, contract_raw = _load(CONTRACT_PATH)
    static = _verify_static(contract)
    if acknowledgement != ACK:
        raise QualificationError("authorization_required")
    if RECEIPT_PATH.exists():
        raise QualificationError("evidence_already_retained")
    if shutil.disk_usage(REPO).free < contract["execution_bounds"]["min_free_bytes"]:
        raise QualificationError("runtime_unavailable")

    base = static["base"]
    base_contract = static["base_contract"]
    started_at = _utc_now()
    started = time.monotonic()
    deadline = started + contract["execution_bounds"]["max_duration_seconds"]
    client = base.LoopbackBudget(contract, started)
    pre_snapshot: dict[str, Any] | None = None
    post_snapshot: dict[str, Any] | None = None
    containers_after: dict[str, Any] | None = None
    positive: dict[str, Any] | None = None
    negative: dict[str, Any] | None = None
    active = False
    cleanup_failures: list[str] = []
    primary: QualificationError | None = None

    render_proof = _render_custom_model(contract, deadline=deadline)
    containers_before = _base_call(
        base._container_identity, base_contract, deadline=deadline
    )
    live_configuration = _live_model_configuration(contract, deadline=deadline)

    try:
        pre_snapshot = _base_call(
            base._service_snapshot, client, base_contract, phase="pre"
        )
        pre_files = pre_snapshot["files"]
        target = contract["asset"]["asset_id"]
        if target in {str(row["id"]) for row in pre_files}:
            raise QualificationError("oracle_failed")
        rt_models_before = _rt_vlm_models(client, contract, "pre")
        openapi = _openapi_contract(client, contract)

        media = _read_regular(
            static["source_path"], contract["transport"]["max_request_bytes"]
        )
        asset = contract["asset"]
        body, content_type = _base_call(
            base._multipart,
            identifier=asset["asset_id"],
            filename=asset["filename"],
            mime_type=asset["mime_type"],
            sensor_name=asset["sensor_name"],
            media=media,
            boundary_suffix="custom-model-prompt",
        )
        upload = client.request(
            "lvs",
            "upload-owned-file",
            "POST",
            "/files",
            body=body,
            content_type=content_type,
        )
        _base_call(
            base._validate_uploaded_file,
            upload,
            identifier=asset["asset_id"],
            filename=asset["filename"],
            sensor_name=asset["sensor_name"],
            size=len(media),
            require_media_type=True,
        )
        active = True
        readback = client.request(
            "lvs",
            "readback-owned-file",
            "GET",
            f"/files/{asset['asset_id']}",
            path_template="/files/{qualifier-owned-id}",
        )
        _base_call(
            base._validate_uploaded_file,
            readback,
            identifier=asset["asset_id"],
            filename=asset["filename"],
            sensor_name=asset["sensor_name"],
            size=len(media),
            require_media_type=False,
        )

        negative_request = _summary_request(
            contract, model=contract["adjacent_negative"]["model_id"]
        )
        rejected = client.request(
            "lvs",
            "reject-unknown-model",
            "POST",
            "/v1/summarize",
            body=_canonical(negative_request),
            content_type="application/json",
            timeout=contract["transport"]["short_timeout_seconds"],
        )
        rejection = _base_call(base._json_response, rejected)
        if (
            rejected.status
            != contract["adjacent_negative"]["expected_http_status"]
            or rejection.get("code")
            != contract["adjacent_negative"]["expected_error_code"]
        ):
            raise QualificationError("oracle_failed")
        negative = {
            "http_status": rejected.status,
            "error_code": rejection["code"],
            "response_bytes": len(rejected.body),
            "response_sha256": _sha(rejected.body),
            "model_identity_rejected_before_inference": True,
        }

        positive_request = _summary_request(contract, model=contract["model_id"])
        positive_started = time.monotonic()
        response = client.request(
            "lvs",
            "summarize-with-custom-prompt",
            "POST",
            "/v1/summarize",
            body=_canonical(positive_request),
            content_type="application/json",
            timeout=contract["transport"]["summarize_timeout_seconds"],
        )
        positive = _validate_custom_summary(base, response, contract)
        positive.update(
            {
                "duration_seconds": round(time.monotonic() - positive_started, 6),
                "override_flag_sent": True,
                "custom_prompt_bytes": contract["prompt_contract"][
                    "custom_prompt_bytes"
                ],
                "custom_prompt_sha256": contract["prompt_contract"][
                    "custom_prompt_sha256"
                ],
                "request_projection_sha256": _canonical_sha(
                    {
                        key: value
                        for key, value in positive_request.items()
                        if key not in {"id", "prompt"}
                    }
                    | {
                        "custom_prompt_sha256": contract["prompt_contract"][
                            "custom_prompt_sha256"
                        ]
                    }
                ),
            }
        )

        _base_call(base._delete_owned, client, asset["asset_id"], "custom-prompt")
        active = False
        after_delete = _base_call(
            base._read_file_list, client, "verify-exact-owned-cleanup"
        )
        if _canonical(after_delete) != _canonical(pre_files):
            raise QualificationError("cleanup_failed")

        post_snapshot = _base_call(
            base._service_snapshot,
            client,
            base_contract,
            phase="post",
            cleanup=True,
        )
        rt_models_after = _rt_vlm_models(client, contract, "post")
        containers_after = _base_call(
            base._container_identity, base_contract, deadline=deadline
        )
        if (
            not _base_call(base._snapshot_exact, pre_snapshot, post_snapshot)
            or rt_models_after != rt_models_before
            or containers_after != containers_before
            or target in {str(row["id"]) for row in post_snapshot["files"]}
        ):
            raise QualificationError("cleanup_failed")
    except QualificationError as exc:
        primary = exc
    except BaseException as exc:
        primary = QualificationError("oracle_failed")
        primary.__cause__ = exc
    finally:
        if active:
            try:
                current = _base_call(
                    base._read_file_list,
                    client,
                    "cleanup-discover-owned-file",
                    cleanup=True,
                )
                target = contract["asset"]["asset_id"]
                if target in {str(row["id"]) for row in current}:
                    _base_call(
                        base._delete_owned,
                        client,
                        target,
                        "recovery-custom-prompt",
                        cleanup=True,
                    )
                restored = _base_call(
                    base._read_file_list,
                    client,
                    "cleanup-verify-owned-file",
                    cleanup=True,
                )
                if (
                    target in {str(row["id"]) for row in restored}
                    or pre_snapshot is None
                    or _canonical(restored) != _canonical(pre_snapshot["files"])
                ):
                    cleanup_failures.append("owned_file_cleanup_failed")
            except BaseException:
                cleanup_failures.append("owned_file_cleanup_failed")

    if cleanup_failures:
        raise QualificationError("cleanup_failed")
    if primary is not None:
        raise primary
    if (
        pre_snapshot is None
        or post_snapshot is None
        or containers_after is None
        or positive is None
        or negative is None
    ):
        raise QualificationError("oracle_failed")

    duration = time.monotonic() - started
    if (
        client.request_count != contract["execution_bounds"]["max_http_requests"]
        or contract["execution_bounds"]["max_semantic_actions"] != 2
        or duration > contract["execution_bounds"]["max_duration_seconds"]
    ):
        raise QualificationError("oracle_failed")

    receipt = {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "capability_ids": [contract["capability_id"]],
        "mode": "execute",
        "status": "passed",
        "failure": None,
        "blockers": [],
        "contract_sha256": _sha(contract_raw),
        "target": contract["target"],
        "started_at": started_at,
        "completed_at": _utc_now(),
        "duration_seconds": round(duration, 6),
        "http_request_count": client.request_count,
        "semantic_action_count": 2,
        "network_scope": "numeric-loopback-only",
        "source_fixture": {
            "path": contract["source_fixture"]["path"],
            "bytes": contract["source_fixture"]["bytes"],
            "sha256": contract["source_fixture"]["sha256"],
        },
        "source_anchors": static["source_anchors"],
        "runtime_identity": containers_before,
        "pre_state": _base_call(base._snapshot_public, pre_snapshot, base_contract),
        "configuration_proof": {
            "official_contract": contract["official_contract"],
            "compose_render": render_proof,
            "live_model": live_configuration,
            "served_model": rt_models_before,
            "openapi": openapi,
        },
        "custom_prompt_proof": positive,
        "adjacent_negative": negative,
        "cleanup": {
            "failures": [],
            "files_created": 1,
            "files_deleted": 1,
            "all_qualifier_owned_ids_absent": True,
            "complete_file_list_exact": True,
            "rt_vlm_asset_statistics_exact": True,
            "lvs_ready_exact": True,
            "lvs_model_identity_exact": True,
            "lvs_metadata_exact": True,
            "container_identity_exact": True,
            "post_state": _base_call(base._snapshot_public, post_snapshot, base_contract),
        },
        "observations": client.observations,
        "forbidden_actions_observed": [],
        "writes_or_lifecycle_actions": True,
        "warehouse_sample_bundle": False,
    }
    _privacy_walk(receipt)
    if retain:
        _retain_receipt(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    live = subparsers.add_parser("execute")
    live.add_argument("--ack", required=True)
    live.add_argument("--retain", action="store_true")
    args = parser.parse_args()
    try:
        result = plan() if args.command == "plan" else execute(args.ack, retain=args.retain)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool_id": "thor-lvs-custom-model-prompt-runtime",
                    "status": "failed",
                    "failure": exc.code,
                },
                sort_keys=True,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool_id": "thor-lvs-custom-model-prompt-runtime",
                    "status": "failed",
                    "failure": "oracle_failed",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
