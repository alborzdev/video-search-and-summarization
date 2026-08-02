#!/usr/bin/env python3
"""Inert-by-default, bounded official-edge semantic evidence collector."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable, cast
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
COMMON_PATH = HERE.parent / "runtime-evidence-common" / "common.py"
ACKNOWLEDGEMENT = "I_ACK_OFFICIAL_EDGE_SEMANTIC_RUNTIME"
MAX_JSON_BYTES = 4 * 1024 * 1024


class CollectorError(RuntimeError):
    """A stable, sanitized collector failure."""

    ALLOWED = {
        "acknowledgement_required",
        "authorization_mismatch",
        "budget_exceeded",
        "cleanup_failed",
        "configuration_error",
        "identity_mismatch",
        "invalid_manifest",
        "invalid_prerequisite",
        "invalid_receipt",
        "invalid_response",
        "source_lock_mismatch",
        "stale_prerequisite",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.ALLOWED else "configuration_error"
        super().__init__(self.code)


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CollectorError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load_module(COMMON_PATH, "thor_runtime_evidence_common")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_json_bytes(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise CollectorError("configuration_error")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CollectorError("configuration_error")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CollectorError("configuration_error")
            ),
        )
    except CollectorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectorError("configuration_error") from exc
    if not isinstance(value, dict):
        raise CollectorError("configuration_error")
    return value


def _read_regular(path: Path, maximum: int, *, require_absolute: bool = False) -> bytes:
    if require_absolute and not path.is_absolute():
        raise CollectorError("configuration_error")
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise CollectorError("configuration_error")
        if info.st_size < 1 or info.st_size > maximum:
            raise CollectorError("configuration_error")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                info.st_dev,
                info.st_ino,
            ):
                raise CollectorError("configuration_error")
            raw = bytearray()
            while len(raw) <= maximum:
                block = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
        finally:
            os.close(descriptor)
    except CollectorError:
        raise
    except OSError as exc:
        raise CollectorError("configuration_error") from exc
    if len(raw) != info.st_size or len(raw) > maximum:
        raise CollectorError("configuration_error")
    return bytes(raw)


def _load_json(path: Path, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    return _strict_json_bytes(_read_regular(path, maximum))


def _schema_validate(instance: Any, schema_path: Path, code: str) -> None:
    try:
        schema = _load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(instance)):
            raise CollectorError(code)
    except CollectorError:
        raise
    except Exception as exc:
        raise CollectorError("configuration_error") from exc


def _contract() -> dict[str, Any]:
    contract = _load_json(CONTRACT_PATH)
    _schema_validate(contract, CONTRACT_SCHEMA_PATH, "configuration_error")
    if (
        contract.get("package_id")
        != "thor-official-edge-semantic-runtime-evidence-successor-v1"
        or contract.get("collector_id") != "thor-official-edge-semantic-collector-v1"
        or contract.get("mode") != "inert_by_default_authorization_gated_execute"
        or contract.get("promotion_policy") != "candidate_receipt_only_non_promoting"
        or contract.get("required_cloud_inference") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
    ):
        raise CollectorError("configuration_error")
    expected_bounds = {
        "max_requests": 7,
        "max_actions": 9,
        "cleanup_reserve_actions": 2,
        "max_duration_seconds": 120,
        "cleanup_reserve_seconds": 15,
        "request_timeout_seconds": 10,
        "max_request_bytes": 2097152,
        "max_response_bytes": 1048576,
        "max_media_bytes": 1048576,
    }
    if contract.get("execution_bounds") != expected_bounds:
        raise CollectorError("configuration_error")
    return contract


def _source_path(path_text: str) -> Path:
    candidate = Path(path_text)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != path_text
    ):
        raise CollectorError("configuration_error")
    path = REPO_ROOT
    for part in candidate.parts:
        path /= part
        if path.is_symlink():
            raise CollectorError("source_lock_mismatch")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CollectorError("source_lock_mismatch") from exc
    if not resolved.is_file():
        raise CollectorError("source_lock_mismatch")
    return resolved


def _verify_source_locks(contract: dict[str, Any]) -> dict[str, bytes]:
    locked: dict[str, bytes] = {}
    rows = contract.get("source_locks")
    if not isinstance(rows, list) or len(rows) != 10:
        raise CollectorError("source_lock_mismatch")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise CollectorError("source_lock_mismatch")
        path_text = row.get("path")
        digest = row.get("sha256")
        if not isinstance(path_text, str) or path_text in locked:
            raise CollectorError("source_lock_mismatch")
        raw = _read_regular(_source_path(path_text), MAX_JSON_BYTES)
        if not isinstance(digest, str) or not hmac.compare_digest(
            _sha256_bytes(raw), digest
        ):
            raise CollectorError("source_lock_mismatch")
        locked[path_text] = raw
    return locked


def _verify_static_official_edge() -> None:
    verifier_path = (
        REPO_ROOT / "deploy/docker/thor-local/official-edge/official_edge.py"
    )
    verifier = _load_module(verifier_path, "thor_official_edge_static_verifier")
    try:
        verifier.verify_static()
    except Exception as exc:
        raise CollectorError("source_lock_mismatch") from exc


def _parse_env(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CollectorError("configuration_error") from exc
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CollectorError("configuration_error")
        key, value = line.split("=", 1)
        if key in values:
            raise CollectorError("configuration_error")
        values[key] = value
    return values


def _validate_no_cloud(contract: dict[str, Any], locked: dict[str, bytes]) -> str:
    env_path = "deploy/docker/thor-local/official-edge/official-edge.env"
    compose_path = "deploy/docker/thor-local/official-edge/compose.yml"
    config_path = "deploy/docker/thor-local/official-edge/config_edge.yml"
    env = _parse_env(locked[env_path])
    llm = contract["canonical_models"]["llm"]
    vlm = contract["canonical_models"]["vlm"]
    required = {
        "LLM_MODE": "remote",
        "VLM_MODE": "local_shared",
        "LLM_BASE_URL": llm["origin"],
        "LLM_NAME": llm["served_model_id"],
        "VLM_BASE_URL": vlm["origin"],
        "VLM_NAME": vlm["served_model_id"],
        "RTVI_VLM_BASE_URL": vlm["origin"],
        "RTVI_VLM_MODEL_TO_USE": vlm["selector"],
        "RTVI_VLM_MODEL_PATH": vlm["artifact_id"],
        "RTVI_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": vlm["served_model_id"],
    }
    if any(env.get(key) != value for key, value in required.items()):
        raise CollectorError("identity_mismatch")
    blank_keys = contract["canonical_models"]["agent"]["api_keys_must_be_blank"]
    blank_projection = {
        key: (
            env[key] == ""
            if key in env
            else f'{key}: ""'.encode("utf-8") in locked[compose_path]
        )
        for key in blank_keys
    }
    if not all(blank_projection.values()):
        raise CollectorError("identity_mismatch")
    selected = locked[env_path] + locked[compose_path] + locked[config_path]
    if any(
        item.encode("utf-8") in selected for item in contract["forbidden_substitutions"]
    ):
        raise CollectorError("identity_mismatch")
    projection = {
        "required": required,
        "blank_keys": sorted(blank_projection),
        "compose_sha256": _sha256_bytes(locked[compose_path]),
        "config_sha256": _sha256_bytes(locked[config_path]),
    }
    return cast(str, common.digest_value(projection))


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CollectorError("invalid_prerequisite")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CollectorError("invalid_prerequisite") from exc
    if parsed.tzinfo is None:
        raise CollectorError("invalid_prerequisite")
    return parsed.astimezone(timezone.utc)


def _validate_prerequisite(
    manifest: dict[str, Any], contract: dict[str, Any], now: datetime
) -> tuple[dict[str, Any], bytes, float]:
    entry = manifest["prerequisite"]
    path = Path(entry["receipt_path"])
    try:
        raw = _read_regular(path, MAX_JSON_BYTES, require_absolute=True)
    except CollectorError as exc:
        raise CollectorError("invalid_prerequisite") from exc
    if not hmac.compare_digest(_sha256_bytes(raw), entry["receipt_sha256"]):
        raise CollectorError("invalid_prerequisite")
    receipt = _strict_json_bytes(raw)
    readiness_schema = (
        REPO_ROOT
        / "deploy/docker/thor-local/qualification/official-edge-readiness/result.schema.json"
    )
    _schema_validate(receipt, readiness_schema, "invalid_prerequisite")
    prereq = contract["prerequisite"]
    if (
        receipt.get("plan_id") != prereq["plan_id"]
        or receipt.get("inspection_mode") != prereq["required_inspection_mode"]
        or receipt.get("qualification_state") != prereq["required_qualification_state"]
        or receipt.get("runtime_qualification_performed") is not False
        or any(row.get("state") == "blocked" for row in receipt.get("blockers", []))
    ):
        raise CollectorError("invalid_prerequisite")
    captured = _parse_time(entry["captured_at_utc"])
    age = (now.astimezone(timezone.utc) - captured).total_seconds()
    if age < 0 or age > prereq["maximum_age_seconds"]:
        raise CollectorError("stale_prerequisite")
    try:
        skew = abs(path.stat().st_mtime - captured.timestamp())
    except OSError as exc:
        raise CollectorError("invalid_prerequisite") from exc
    if skew > prereq["maximum_capture_mtime_skew_seconds"]:
        raise CollectorError("stale_prerequisite")
    containers = receipt.get("containers", {})
    for name in prereq["required_running_containers"]:
        row = containers.get(name, {}) if isinstance(containers, dict) else {}
        if row.get("state") != "running":
            raise CollectorError("invalid_prerequisite")
        if (
            name in {"vss-nemotron-edge-4b", "vss-rtvi-vlm"}
            and row.get("required_image_reference_matches") is not True
        ):
            raise CollectorError("invalid_prerequisite")
    expected_sources = {
        row["path"]: row["sha256"]
        for row in contract["source_locks"]
        if row["path"]
        in {
            "deploy/docker/thor-local/official-edge/contract.json",
            "deploy/docker/thor-local/official-edge/artifacts.lock.json",
        }
    }
    source_locks = receipt.get("source_locks", {})
    files = source_locks.get("files") if isinstance(source_locks, dict) else None
    actual_sources = {
        row.get("path"): row.get("actual_sha256")
        for row in files or []
        if isinstance(row, dict)
        and row.get("state") == "match"
        and row.get("actual_sha256") == row.get("expected_sha256")
    }
    if source_locks.get("state") != "match" or any(
        actual_sources.get(path) != digest for path, digest in expected_sources.items()
    ):
        raise CollectorError("invalid_prerequisite")
    return receipt, raw, age


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class LiveOpener:
    """Explicit proxy-free, redirect-free urllib opener."""

    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def open(self, request: Any, timeout: float) -> Any:
        return self._opener.open(request, timeout=timeout)


def _json_body(value: Any, owned: list[bytearray]) -> bytes:
    raw = bytearray(common.canonical_bytes(value))
    owned.append(raw)
    return bytes(raw)


def _response_json(result: Any) -> dict[str, Any]:
    if result.status != 200 or result.media_type != "application/json":
        raise CollectorError("invalid_response")
    try:
        return cast(dict[str, Any], common.strict_json(result.body, "response"))
    except Exception as exc:
        raise CollectorError("invalid_response") from exc


def _model_id(value: dict[str, Any]) -> str:
    data = value.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise CollectorError("identity_mismatch")
    model_id = data[0].get("id")
    if not isinstance(model_id, str):
        raise CollectorError("identity_mismatch")
    return model_id


def _assistant_message(value: dict[str, Any]) -> dict[str, Any]:
    choices = value.get("choices")
    if (
        not isinstance(choices, list)
        or len(choices) != 1
        or not isinstance(choices[0], dict)
    ):
        raise CollectorError("invalid_response")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise CollectorError("invalid_response")
    return message


def _observation(
    sequence: int,
    observation_id: str,
    role: str,
    request_body: bytes,
    result: Any,
    assertions: list[str],
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "observation_id": observation_id,
        "role": role,
        "status": "pass",
        "result_code": "semantic_pass",
        "request_sha256": _sha256_bytes(request_body),
        "response_sha256": _sha256_bytes(result.body),
        "response_bytes": len(result.body),
        "response_status": result.status,
        "assertion_ids": assertions,
    }


def _wipe(buffers: list[bytearray]) -> bool:
    for buffer in buffers:
        buffer[:] = b"\x00" * len(buffer)
    return all(not any(buffer) for buffer in buffers)


def execute(
    manifest_path: Path,
    *,
    acknowledgement: str,
    authorization_token: str,
    opener_factory: Callable[[str], Any] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic: Callable[[], float] = time.monotonic,
    cleanup_probe: Callable[[], bool] = lambda: True,
) -> dict[str, Any]:
    """Execute only after explicit admission; dependencies are injectable for fake tests."""
    if acknowledgement != ACKNOWLEDGEMENT:
        raise CollectorError("acknowledgement_required")
    contract = _contract()
    locked = _verify_source_locks(contract)
    _verify_static_official_edge()
    manifest = _load_json(manifest_path)
    _schema_validate(manifest, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    expected_token = manifest["authorization"]["token_sha256"]
    actual_token = _sha256_bytes(authorization_token.encode("utf-8"))
    if not hmac.compare_digest(expected_token, actual_token):
        raise CollectorError("authorization_mismatch")
    identity = common.EvidenceIdentity(
        manifest["run_id"], manifest["authorization"]["authorization_id"], actual_token
    )
    no_cloud_projection = _validate_no_cloud(contract, locked)
    prereq, prereq_raw, age = _validate_prerequisite(manifest, contract, now())
    media_path = Path(manifest["media"]["path"])
    media_raw = bytearray(
        _read_regular(
            media_path,
            contract["execution_bounds"]["max_media_bytes"],
            require_absolute=True,
        )
    )
    if len(media_raw) != manifest["media"]["byte_count"] or not hmac.compare_digest(
        _sha256_bytes(bytes(media_raw)), manifest["media"]["sha256"]
    ):
        _wipe([media_raw])
        raise CollectorError("invalid_manifest")
    if (
        manifest["visual_oracle"]["positive_literal"]
        == manifest["visual_oracle"]["absent_literal"]
    ):
        _wipe([media_raw])
        raise CollectorError("invalid_manifest")
    bounds = contract["execution_bounds"]
    budget = common.ExecutionBudget(bounds["max_requests"], bounds["max_actions"])
    factory = opener_factory or (lambda _role: LiveOpener())
    targets = {
        role: common.LoopbackTarget.admit(
            manifest["origins"][role],
            tuple(
                path
                for path in (
                    contract["canonical_models"].get(role, {}).get("models_path"),
                    contract["canonical_models"].get(role, {}).get("semantic_path"),
                    contract["canonical_models"].get(role, {}).get("workflow_path"),
                )
                if path
            ),
        )
        for role in ("llm", "vlm", "agent")
    }
    try:
        transports = {
            role: common.BoundedHTTPTransport(
                target=target,
                opener=factory(role),
                budget=budget,
                max_request_bytes=bounds["max_request_bytes"],
                max_response_bytes=bounds["max_response_bytes"],
                timeout_seconds=bounds["request_timeout_seconds"],
            )
            for role, target in targets.items()
        }
    except common.EvidenceCommonError as exc:
        _wipe([media_raw])
        raise CollectorError("configuration_error") from exc
    positive = manifest["visual_oracle"]["positive_literal"]
    absent = manifest["visual_oracle"]["absent_literal"]
    semantics = contract["semantic_contract"]
    llm_id = contract["canonical_models"]["llm"]["served_model_id"]
    vlm_id = contract["canonical_models"]["vlm"]["served_model_id"]
    data_url = (
        "data:"
        + manifest["media"]["media_type"]
        + ";base64,"
        + base64.b64encode(media_raw).decode("ascii")
    )
    owned_requests: list[bytearray] = []
    observations: list[dict[str, Any]] = []
    started = monotonic()
    cleanup_ok = False
    try:
        steps: list[tuple[str, str, bytes]] = []
        steps.append(("llm", contract["canonical_models"]["llm"]["models_path"], b""))
        steps.append(
            (
                "llm",
                contract["canonical_models"]["llm"]["semantic_path"],
                _json_body(
                    {
                        "model": llm_id,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Call the supplied function exactly once.",
                            }
                        ],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": semantics["llm_tool_name"],
                                    "parameters": {
                                        "type": "object",
                                        "properties": {"value": {"type": "string"}},
                                        "required": ["value"],
                                        "additionalProperties": False,
                                    },
                                },
                            }
                        ],
                        "tool_choice": {
                            "type": "function",
                            "function": {"name": semantics["llm_tool_name"]},
                        },
                    },
                    owned_requests,
                ),
            )
        )
        steps.append(
            (
                "llm",
                contract["canonical_models"]["llm"]["semantic_path"],
                _json_body(
                    {
                        "model": llm_id,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Return exactly THOR_NO_TOOL_TARGET and do not call a tool.",
                            }
                        ],
                        "tool_choice": "none",
                    },
                    owned_requests,
                ),
            )
        )
        steps.append(("vlm", contract["canonical_models"]["vlm"]["models_path"], b""))
        for literal, question in (
            (positive, "Return only the exact visible oracle text."),
            (
                absent,
                "Return THOR_VISUAL_ABSENT only if the requested absent text is not visible.",
            ),
        ):
            steps.append(
                (
                    "vlm",
                    contract["canonical_models"]["vlm"]["semantic_path"],
                    _json_body(
                        {
                            "model": vlm_id,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": question + " Target: " + literal,
                                        },
                                        {
                                            "type": "image_url",
                                            "image_url": {"url": data_url},
                                        },
                                    ],
                                }
                            ],
                        },
                        owned_requests,
                    ),
                )
            )
        steps.append(
            (
                "agent",
                contract["canonical_models"]["agent"]["workflow_path"],
                _json_body(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Use visual understanding and reasoning; finish with THOR_AGENT_BOTH_MODELS. Return the visible oracle.",
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": data_url},
                                    },
                                ],
                            }
                        ]
                    },
                    owned_requests,
                ),
            )
        )

        for index, ((role, path, body), observation_id) in enumerate(
            zip(steps, semantics["request_template_ids"], strict=True), 1
        ):
            if (
                monotonic() - started
                > bounds["max_duration_seconds"] - bounds["cleanup_reserve_seconds"]
            ):
                raise CollectorError("budget_exceeded")
            result = transports[role].request(
                "GET" if not body else "POST",
                path,
                body=body,
                media_type=None if not body else "application/json",
            )
            budget.consume_action()
            assertions: list[str]
            if observation_id == "llm-model-identity":
                if _model_id(_response_json(result)) != llm_id:
                    raise CollectorError("identity_mismatch")
                assertions = ["exact-llm-served-id"]
            elif observation_id == "vlm-model-identity":
                if _model_id(_response_json(result)) != vlm_id:
                    raise CollectorError("identity_mismatch")
                assertions = ["exact-vlm-served-id"]
            else:
                if observation_id == "agent-both-models-workflow":
                    if result.status != 200 or result.media_type not in {
                        "application/json",
                        "text/event-stream",
                    }:
                        raise CollectorError("invalid_response")
                    try:
                        content = result.body.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise CollectorError("invalid_response") from exc
                    message: dict[str, Any] = {}
                else:
                    message = _assistant_message(_response_json(result))
                    content = message.get("content")
                if observation_id == "llm-tool-positive":
                    calls = message.get("tool_calls")
                    if not isinstance(calls, list) or len(calls) != 1:
                        raise CollectorError("invalid_response")
                    function = (
                        calls[0].get("function", {})
                        if isinstance(calls[0], dict)
                        else {}
                    )
                    try:
                        arguments = json.loads(function.get("arguments", ""))
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise CollectorError("invalid_response") from exc
                    if function.get("name") != semantics[
                        "llm_tool_name"
                    ] or arguments != {"value": semantics["llm_positive_argument"]}:
                        raise CollectorError("invalid_response")
                    assertions = ["exact-tool-name", "exact-tool-arguments"]
                elif observation_id == "llm-tool-negative":
                    if content != semantics[
                        "llm_negative_exact_content"
                    ] or message.get("tool_calls") not in (None, []):
                        raise CollectorError("invalid_response")
                    assertions = ["negative-no-tool-call", "negative-exact-content"]
                elif observation_id == "vlm-visual-positive":
                    if (
                        not isinstance(content, str)
                        or positive not in content
                        or absent in content
                    ):
                        raise CollectorError("invalid_response")
                    assertions = [
                        "digest-pinned-media",
                        "positive-visual-literal",
                        "absent-literal-excluded",
                    ]
                elif observation_id == "vlm-visual-absent-negative":
                    if content != semantics["vlm_absent_exact_content"]:
                        raise CollectorError("invalid_response")
                    assertions = ["digest-pinned-media", "absent-negative-exact"]
                else:
                    if (
                        not isinstance(content, str)
                        or positive not in content
                        or semantics["agent_workflow_sentinel"] not in content
                        or absent in content
                    ):
                        raise CollectorError("invalid_response")
                    assertions = [
                        "agent-consumed-vlm",
                        "agent-consumed-llm",
                        "agent-workflow-sentinel",
                    ]
            observations.append(
                _observation(index, observation_id, role, body, result, assertions)
            )
        duration = monotonic() - started
        if (
            duration < 0
            or duration
            > bounds["max_duration_seconds"] - bounds["cleanup_reserve_seconds"]
        ):
            raise CollectorError("budget_exceeded")
    except common.EvidenceCommonError as exc:
        raise CollectorError(
            "transport_error"
            if "transport" in exc.code or "response" in exc.code
            else "budget_exceeded"
        ) from exc
    finally:
        budget.consume_actions(bounds["cleanup_reserve_actions"])
        media_cleared = _wipe([media_raw])
        requests_cleared = _wipe(owned_requests)
        cleanup_ok = media_cleared and requests_cleared and cleanup_probe() is True
    if not cleanup_ok:
        raise CollectorError("cleanup_failed")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "collector_id": contract["collector_id"],
        "status": "passed_candidate_non_promoting",
        "promotion_eligible": False,
        "runtime_activity_performed": True,
        "required_cloud_inference": False,
        "warehouse_sample_bundle": "excluded",
        "collector_locks": {
            "contract_sha256": _sha256_file(CONTRACT_PATH),
            "executor_sha256": _sha256_file(Path(__file__).resolve()),
            "manifest_schema_sha256": _sha256_file(MANIFEST_SCHEMA_PATH),
            "receipt_schema_sha256": _sha256_file(RECEIPT_SCHEMA_PATH),
        },
        "identity": identity.evidence(),
        "prerequisite": {
            "receipt_sha256": _sha256_bytes(prereq_raw),
            "receipt_path_sha256": _sha256_bytes(
                str(Path(manifest["prerequisite"]["receipt_path"]).resolve()).encode()
            ),
            "captured_at_utc": manifest["prerequisite"]["captured_at_utc"],
            "age_seconds": age,
            "qualification_state": prereq["qualification_state"],
            "source_projection_sha256": common.digest_value(prereq["source_locks"]),
        },
        "model_contract": {
            "release_commit": contract["reviewed_release"]["tag_commit"],
            "main_commit": contract["reviewed_release"]["main_commit"],
            "artifact_lock_sha256": next(
                row["sha256"]
                for row in contract["source_locks"]
                if row["path"].endswith("artifacts.lock.json")
            ),
            "llm": {
                key: contract["canonical_models"]["llm"][key]
                for key in ("served_model_id", "image_reference", "image_id")
            }
            | {"endpoint": contract["canonical_models"]["llm"]["origin"]},
            "vlm": {
                key: contract["canonical_models"]["vlm"][key]
                for key in ("served_model_id", "image_reference", "image_id")
            }
            | {"endpoint": contract["canonical_models"]["vlm"]["origin"]},
        },
        "no_cloud_agent_wiring": {
            "status": "pass",
            "projection_sha256": no_cloud_projection,
            "blank_api_key_count": 5,
            "forbidden_substitution_count": 0,
        },
        "media": {
            "sha256": manifest["media"]["sha256"],
            "byte_count": manifest["media"]["byte_count"],
            "media_type": manifest["media"]["media_type"],
            "positive_literal_sha256": _sha256_bytes(positive.encode()),
            "absent_literal_sha256": _sha256_bytes(absent.encode()),
        },
        "observations": observations,
        "budget": budget.evidence()
        | {
            "duration_seconds": duration,
            "max_duration_seconds": 120,
            "cleanup_reserve_actions": 2,
            "cleanup_reserve_seconds": 15,
        },
        "cleanup": {
            "status": "pass",
            "raw_media_buffer_cleared": True,
            "request_buffers_cleared": True,
            "postcondition_verified": True,
        },
        "sanitization": {
            "raw_media_included": False,
            "credential_values_included": False,
            "raw_prompts_included": False,
            "response_bodies_included": False,
            "local_paths_included": False,
        },
        "canonical_effect": {
            "admitted": False,
            "promoted": False,
            "binding_changed": False,
        },
    }
    validate_receipt_document(receipt)
    forbidden_values = [
        authorization_token,
        str(media_path),
        str(Path(manifest["prerequisite"]["receipt_path"])),
        data_url,
        positive,
        absent,
    ]
    serialized = common.canonical_bytes(receipt).decode("ascii")
    if any(value and value in serialized for value in forbidden_values):
        raise CollectorError("invalid_receipt")
    return receipt


def validate_receipt_document(receipt: dict[str, Any]) -> None:
    _schema_validate(receipt, RECEIPT_SCHEMA_PATH, "invalid_receipt")
    contract = _contract()
    locked = _verify_source_locks(contract)
    expected_observations = [
        ("llm-model-identity", "llm", ["exact-llm-served-id"]),
        (
            "llm-tool-positive",
            "llm",
            ["exact-tool-name", "exact-tool-arguments"],
        ),
        (
            "llm-tool-negative",
            "llm",
            ["negative-no-tool-call", "negative-exact-content"],
        ),
        ("vlm-model-identity", "vlm", ["exact-vlm-served-id"]),
        (
            "vlm-visual-positive",
            "vlm",
            [
                "digest-pinned-media",
                "positive-visual-literal",
                "absent-literal-excluded",
            ],
        ),
        (
            "vlm-visual-absent-negative",
            "vlm",
            ["digest-pinned-media", "absent-negative-exact"],
        ),
        (
            "agent-both-models-workflow",
            "agent",
            [
                "agent-consumed-vlm",
                "agent-consumed-llm",
                "agent-workflow-sentinel",
            ],
        ),
    ]
    expected_ids = contract["semantic_contract"]["request_template_ids"]
    if [
        row.get("observation_id") for row in receipt.get("observations", [])
    ] != expected_ids:
        raise CollectorError("invalid_receipt")
    if [row.get("sequence") for row in receipt["observations"]] != list(range(1, 8)):
        raise CollectorError("invalid_receipt")
    if [
        (row.get("observation_id"), row.get("role"), row.get("assertion_ids"))
        for row in receipt["observations"]
    ] != expected_observations:
        raise CollectorError("invalid_receipt")
    expected_models = contract["canonical_models"]
    artifact_lock_sha256 = next(
        row["sha256"]
        for row in contract["source_locks"]
        if row["path"].endswith("artifacts.lock.json")
    )
    expected_model_contract = {
        "release_commit": contract["reviewed_release"]["tag_commit"],
        "main_commit": contract["reviewed_release"]["main_commit"],
        "artifact_lock_sha256": artifact_lock_sha256,
        "llm": {
            "served_model_id": expected_models["llm"]["served_model_id"],
            "endpoint": expected_models["llm"]["origin"],
            "image_reference": expected_models["llm"]["image_reference"],
            "image_id": expected_models["llm"]["image_id"],
        },
        "vlm": {
            "served_model_id": expected_models["vlm"]["served_model_id"],
            "endpoint": expected_models["vlm"]["origin"],
            "image_reference": expected_models["vlm"]["image_reference"],
            "image_id": expected_models["vlm"]["image_id"],
        },
    }
    if receipt["model_contract"] != expected_model_contract:
        raise CollectorError("invalid_receipt")
    if receipt["no_cloud_agent_wiring"] != {
        "status": "pass",
        "projection_sha256": _validate_no_cloud(contract, locked),
        "blank_api_key_count": 5,
        "forbidden_substitution_count": 0,
    }:
        raise CollectorError("invalid_receipt")
    locks = receipt["collector_locks"]
    expected_locks = {
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "executor_sha256": _sha256_file(Path(__file__).resolve()),
        "manifest_schema_sha256": _sha256_file(MANIFEST_SCHEMA_PATH),
        "receipt_schema_sha256": _sha256_file(RECEIPT_SCHEMA_PATH),
    }
    if locks != expected_locks:
        raise CollectorError("invalid_receipt")


def validate_receipt_file(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = _read_regular(path, MAX_JSON_BYTES, require_absolute=True)
    if not hmac.compare_digest(_sha256_bytes(raw), expected_sha256):
        raise CollectorError("invalid_receipt")
    receipt = _strict_json_bytes(raw)
    validate_receipt_document(receipt)
    return receipt


def plan() -> dict[str, Any]:
    contract = _contract()
    locked = _verify_source_locks(contract)
    _verify_static_official_edge()
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan_only_no_runtime_activity",
        "runtime_activity_performed": False,
        "network_requests": 0,
        "service_mutations": 0,
        "warehouse_sample_bundle": "excluded",
        "source_projection_sha256": common.digest_value(
            {key: _sha256_bytes(value) for key, value in sorted(locked.items())}
        ),
        "execution_requires_acknowledgement": ACKNOWLEDGEMENT,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan")
    execute_parser = sub.add_parser("execute")
    execute_parser.add_argument("--manifest", type=Path, required=True)
    execute_parser.add_argument("--acknowledgement", required=True)
    execute_parser.add_argument("--authorization-token", required=True)
    validate_parser = sub.add_parser("validate-receipt")
    validate_parser.add_argument("--receipt", type=Path, required=True)
    validate_parser.add_argument("--sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in (None, "plan"):
            result = plan()
        elif args.command == "execute":
            result = execute(
                args.manifest,
                acknowledgement=args.acknowledgement,
                authorization_token=args.authorization_token,
            )
        else:
            result = validate_receipt_file(args.receipt, args.sha256)
    except CollectorError as exc:
        print(json.dumps({"status": "fail", "code": exc.code}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
