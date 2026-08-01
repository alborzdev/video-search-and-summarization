#!/usr/bin/env python3
"""Bounded, inert-by-default qualification of Thor's local Qwen alternate lane.

The only execute-mode side effect is at most four direct HTTP requests to two
code-owned IPv4 endpoints. There is deliberately no subprocess, Docker,
credential, download, redirect, proxy, lifecycle, or file-write path.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"

ACKNOWLEDGEMENT = (
    "I_ACKNOWLEDGE_THIS_IS_A_NON_OFFICIAL_ALTERNATE_MODEL_TEST_"
    "WITH_NO_OFFICIAL_VSS_CAPABILITY_PROMOTION"
)
ARTIFACT_LOCK_PATH = REPO_ROOT / "deploy/docker/thor-local/models/artifacts.lock.json"
ARTIFACT_LOCK_SHA256 = (
    "5b0030ba13fb1ccee5950e3c4b78d334d8dd0c30a2a45ce90e6166a57fe31d09"
)
RELEASE_COMMIT = "7640d917047cf7b0fd3085eefb8282754b56bc94"
MAIN_COMMIT = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
LOCAL_BASE_COMMIT = "ee82896c01e66e03502d24bdafe6b46e20679785"
VLLM_IMAGE = (
    "ghcr.io/nvidia-ai-iot/vllm@"
    "sha256:6402d5ac90223b9ba4434228f98aec798c5a8b942e770ee47528b4148e923105"
)
MAX_REQUESTS = 4
TIMEOUT_SECONDS = 10
MAX_REQUEST_BODY = 262_144
MAX_RESPONSE_BODY = 1_048_576
PING_MESSAGE = "thor-local-qwen-alternate-qualification"
COLOR_ANSWER = "red, green, blue, yellow"

ENDPOINTS = {
    "llm": ("172.17.0.1", 8000, "datasheet-chat"),
    "vlm": ("172.17.0.1", 8003, "datasheet-vision"),
}
ARTIFACTS = {
    "qwen_llm": {
        "repository": "Qwen/Qwen3.6-35B-A3B-FP8",
        "revision": "95a723d08a9490559dae23d0cff1d9466213d989",
        "canonical_sha256": (
            "3daac37579503b0ad6f3346c484194b82842889cdcccbb8b6b459190322fa483"
        ),
    },
    "qwen_vlm": {
        "repository": "Qwen/Qwen3-VL-8B-Instruct-FP8",
        "revision": "9cdc6310a8cb770ce18efaf4e9935334512aee45",
        "canonical_sha256": (
            "f39e7f8a690e9d4fec01c0ceab74effdb495682f67b08ba659e6f436c1020a6b"
        ),
    },
}
COLORS = (
    (
        "red",
        (255, 0, 0),
        "c7688e580506236f18d65e36ae194d5ee94ff232a4f43fe4996f47e12df2ef37",
    ),
    (
        "green",
        (0, 255, 0),
        "75a9d4734f1002189a3c477eb52c21fd695afc10dd3ee6f865a985e390439692",
    ),
    (
        "blue",
        (0, 0, 255),
        "9fcd98102a7190ec20857cf9925c53b888cba30c5aab65d6e39cbd84ee044e8c",
    ),
    (
        "yellow",
        (255, 255, 0),
        "5c78c2c759ce3cacc482f8696e65846a7e5c4aadaea245b45d51de42470da600",
    ),
)
PROBE_IDS = (
    "llm-model-identity",
    "vlm-model-identity",
    "llm-ping-tool-call",
    "vlm-four-image-color-order",
)


class QualificationError(RuntimeError):
    """A fail-closed contract, transport, or response validation error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError("duplicate_json_key")
        result[key] = value
    return result


def _decode_json(raw: bytes, error_code: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicate_pairs)
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(error_code) from exc


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_contract() -> tuple[dict[str, Any], str]:
    raw = CONTRACT_PATH.read_bytes()
    value = _decode_json(raw, "contract_invalid_json")
    if not isinstance(value, dict):
        raise QualificationError("contract_invalid_type")
    return value, hashlib.sha256(raw).hexdigest()


def _expected_probe_contract() -> list[dict[str, Any]]:
    return [
        {
            "id": "llm-model-identity",
            "request_number": 1,
            "endpoint": "llm",
            "method": "GET",
            "path": "/v1/models",
            "expected": "the only returned model id is datasheet-chat",
        },
        {
            "id": "vlm-model-identity",
            "request_number": 2,
            "endpoint": "vlm",
            "method": "GET",
            "path": "/v1/models",
            "expected": "the only returned model id is datasheet-vision",
        },
        {
            "id": "llm-ping-tool-call",
            "request_number": 3,
            "endpoint": "llm",
            "method": "POST",
            "path": "/v1/chat/completions",
            "expected": (
                "exactly one ping tool call with the locked message and "
                "enable_thinking=false"
            ),
        },
        {
            "id": "vlm-four-image-color-order",
            "request_number": 4,
            "endpoint": "vlm",
            "method": "POST",
            "path": "/v1/chat/completions",
            "expected": COLOR_ANSWER,
            "images": [
                {"color": name, "rgb": list(rgb), "sha256": digest}
                for name, rgb, digest in COLORS
            ],
        },
    ]


def validate_contract(contract: Mapping[str, Any]) -> None:
    """Validate every security- and identity-relevant contract field exactly."""
    expected = {
        "schema_version": 1,
        "contract_id": "vss-3.2.1-thor-local-qwen-alternate-runtime",
        "classification": {
            "lane": "non-official-local-alternate",
            "official_vss_model_equivalence": False,
            "official_capability_promotion_allowed": False,
            "acceptance_oracle_mutation_allowed": False,
            "statement": (
                "A pass qualifies only the locked Thor-local Qwen alternate "
                "endpoints; it is not evidence that an official NVIDIA VSS "
                "model or capability passed."
            ),
        },
        "source_binding": {
            "product_version": "3.2.1",
            "release_commit": RELEASE_COMMIT,
            "reviewed_main_commit": MAIN_COMMIT,
            "reviewed_local_base_commit": LOCAL_BASE_COMMIT,
            "current_commit_source": (
                ".git/HEAD (resolved read-only without subprocess)"
            ),
        },
        "artifact_lock": {
            "path": "deploy/docker/thor-local/models/artifacts.lock.json",
            "sha256": ARTIFACT_LOCK_SHA256,
            "artifacts": ARTIFACTS,
        },
        "runtime": {
            "vllm_image": VLLM_IMAGE,
            "endpoints": {
                "llm": {
                    "base_url": "http://172.17.0.1:8000",
                    "served_model_id": "datasheet-chat",
                },
                "vlm": {
                    "base_url": "http://172.17.0.1:8003",
                    "served_model_id": "datasheet-vision",
                },
            },
        },
        "execution_policy": {
            "default_mode": "plan",
            "exact_acknowledgement": ACKNOWLEDGEMENT,
            "maximum_http_requests": MAX_REQUESTS,
            "request_timeout_seconds": TIMEOUT_SECONDS,
            "maximum_request_body_bytes": MAX_REQUEST_BODY,
            "maximum_response_body_bytes": MAX_RESPONSE_BODY,
            "proxies_allowed": False,
            "redirects_allowed": False,
            "credentials_allowed": False,
            "docker_or_subprocess_allowed": False,
            "lifecycle_or_download_allowed": False,
            "file_writes_allowed": False,
            "evidence_destination": "stdout",
        },
        "probes": _expected_probe_contract(),
    }
    if contract != expected:
        raise QualificationError("contract_not_exact")


def validate_artifact_lock() -> None:
    if _file_sha256(ARTIFACT_LOCK_PATH) != ARTIFACT_LOCK_SHA256:
        raise QualificationError("artifact_lock_digest_mismatch")
    lock = _decode_json(ARTIFACT_LOCK_PATH.read_bytes(), "artifact_lock_invalid_json")
    if not isinstance(lock, dict) or not isinstance(lock.get("artifacts"), dict):
        raise QualificationError("artifact_lock_invalid_shape")
    for key, expected in ARTIFACTS.items():
        artifact = lock["artifacts"].get(key)
        if not isinstance(artifact, dict):
            raise QualificationError(f"artifact_{key}_missing")
        if _canonical_sha256(artifact) != expected["canonical_sha256"]:
            raise QualificationError(f"artifact_{key}_digest_mismatch")
        provenance = artifact.get("provenance")
        if not isinstance(provenance, dict):
            raise QualificationError(f"artifact_{key}_provenance_missing")
        if (
            provenance.get("repository") != expected["repository"]
            or provenance.get("revision") != expected["revision"]
        ):
            raise QualificationError(f"artifact_{key}_identity_mismatch")


@dataclass(frozen=True)
class HttpResult:
    status: int
    content_type: str
    body: bytes


class Transport(Protocol):
    requests_attempted: int

    def request(
        self, endpoint: str, method: str, path: str, body: bytes
    ) -> HttpResult: ...


class DirectLocalTransport:
    """No-proxy transport with a closed endpoint/method/path set."""

    def __init__(self) -> None:
        self.requests_attempted = 0

    def request(self, endpoint: str, method: str, path: str, body: bytes) -> HttpResult:
        allowed = {
            ("llm", "GET", "/v1/models"),
            ("vlm", "GET", "/v1/models"),
            ("llm", "POST", "/v1/chat/completions"),
            ("vlm", "POST", "/v1/chat/completions"),
        }
        if (endpoint, method, path) not in allowed:
            raise QualificationError("request_not_allowlisted")
        if self.requests_attempted >= MAX_REQUESTS:
            raise QualificationError("request_limit_exceeded")
        if len(body) > MAX_REQUEST_BODY:
            raise QualificationError("request_body_too_large")

        host, port, _model = ENDPOINTS[endpoint]
        self.requests_attempted += 1
        connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT_SECONDS)
        headers = {
            "Accept": "application/json",
            "Connection": "close",
            "Content-Type": "application/json",
        }
        try:
            connection.request(method, path, body=body or None, headers=headers)
            response = connection.getresponse()
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > MAX_RESPONSE_BODY:
                        raise QualificationError("response_body_too_large")
                except ValueError as exc:
                    raise QualificationError("invalid_content_length") from exc
            response_body = response.read(MAX_RESPONSE_BODY + 1)
            if len(response_body) > MAX_RESPONSE_BODY:
                raise QualificationError("response_body_too_large")
            return HttpResult(
                status=response.status,
                content_type=response.getheader("Content-Type", ""),
                body=response_body,
            )
        except QualificationError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise QualificationError("local_http_transport_error") from exc
        finally:
            connection.close()


def _json_body(value: Any) -> bytes:
    body = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()
    if len(body) > MAX_REQUEST_BODY:
        raise QualificationError("request_body_too_large")
    return body


def _response_json(result: HttpResult) -> dict[str, Any]:
    if result.status != 200:
        # This rejects redirects without following or exposing their Location.
        raise QualificationError("unexpected_http_status")
    if result.content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise QualificationError("unexpected_content_type")
    value = _decode_json(result.body, "response_invalid_json")
    if not isinstance(value, dict):
        raise QualificationError("response_invalid_shape")
    return value


def _validate_model_identity(value: Mapping[str, Any], expected: str) -> None:
    data = value.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise QualificationError("model_identity_not_exact")
    item = data[0]
    if not isinstance(item, dict) or item.get("id") != expected:
        raise QualificationError("model_identity_not_exact")


def _png(rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    scanlines = b"".join(b"\x00" + bytes(rgb) * 56 for _ in range(56))
    header = struct.pack(">IIBBBBB", 56, 56, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def _llm_payload() -> dict[str, Any]:
    return {
        "model": ENDPOINTS["llm"][2],
        "messages": [
            {
                "role": "user",
                "content": (
                    "Call the ping tool exactly once with message "
                    f"{PING_MESSAGE}. Do not answer with text."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "Return a bounded local qualification ping.",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["message"],
                        "properties": {"message": {"type": "string"}},
                    },
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "ping"}},
        "temperature": 0,
        "max_tokens": 64,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def _validate_llm_payload(payload: Mapping[str, Any]) -> None:
    if payload != _llm_payload():
        raise QualificationError("llm_request_contract_not_exact")


def _validate_llm_tool_call(value: Mapping[str, Any]) -> None:
    try:
        calls = value["choices"][0]["message"]["tool_calls"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("llm_tool_call_missing") from exc
    if not isinstance(calls, list) or len(calls) != 1:
        raise QualificationError("llm_tool_call_not_exact")
    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    if not isinstance(function, dict) or function.get("name") != "ping":
        raise QualificationError("llm_tool_call_not_exact")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise QualificationError("llm_tool_arguments_invalid")
    parsed = _decode_json(arguments.encode(), "llm_tool_arguments_invalid")
    if parsed != {"message": PING_MESSAGE}:
        raise QualificationError("llm_tool_arguments_not_exact")


def _vlm_payload() -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "These four images are ordered first through fourth. Identify each "
                "solid color. Respond with exactly: red, green, blue, yellow"
            ),
        }
    ]
    for _name, rgb, expected_digest in COLORS:
        raw = _png(rgb)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise QualificationError("generated_image_digest_mismatch")
        encoded = base64.b64encode(raw).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    return {
        "model": ENDPOINTS["vlm"][2],
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 32,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def _validate_vlm_payload(payload: Mapping[str, Any]) -> None:
    if payload != _vlm_payload():
        raise QualificationError("vlm_request_contract_not_exact")


def _validate_vlm_answer(value: Mapping[str, Any]) -> None:
    try:
        answer = value["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("vlm_answer_missing") from exc
    if not isinstance(answer, str):
        raise QualificationError("vlm_answer_invalid")
    normalized = " ".join(answer.strip().lower().split()).removesuffix(".")
    if normalized != COLOR_ANSWER:
        raise QualificationError("vlm_color_order_not_exact")


def _binding(contract_sha256: str, current_commit: str | None = None) -> dict[str, Any]:
    return {
        "release_commit": RELEASE_COMMIT,
        "reviewed_main_commit": MAIN_COMMIT,
        "reviewed_local_base_commit": LOCAL_BASE_COMMIT,
        "current_commit": current_commit or _read_current_commit(),
        "artifact_lock_sha256": ARTIFACT_LOCK_SHA256,
        "contract_sha256": contract_sha256,
        "vllm_image": VLLM_IMAGE,
    }


def _read_current_commit() -> str:
    git_dir = REPO_ROOT / ".git"
    if not git_dir.is_dir():
        raise QualificationError("git_directory_unavailable")
    head_raw = git_dir.joinpath("HEAD").read_bytes()
    if len(head_raw) > 512:
        raise QualificationError("git_head_invalid")
    try:
        head = head_raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise QualificationError("git_head_invalid") from exc

    if head.startswith("ref: "):
        reference = head.removeprefix("ref: ")
        if (
            not reference.startswith("refs/heads/")
            or ".." in reference
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-"
                for character in reference
            )
        ):
            raise QualificationError("git_head_reference_invalid")
        reference_path = (git_dir / reference).resolve()
        if git_dir.resolve() not in reference_path.parents:
            raise QualificationError("git_head_reference_invalid")
        if reference_path.is_file():
            commit_raw = reference_path.read_bytes()
            if len(commit_raw) > 128:
                raise QualificationError("git_head_commit_invalid")
            try:
                commit = commit_raw.decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise QualificationError("git_head_commit_invalid") from exc
        else:
            packed_path = git_dir / "packed-refs"
            if not packed_path.is_file():
                raise QualificationError("git_head_reference_unresolved")
            packed_raw = packed_path.read_bytes()
            if len(packed_raw) > 5_242_880:
                raise QualificationError("git_packed_refs_too_large")
            try:
                lines = packed_raw.decode("ascii").splitlines()
            except UnicodeDecodeError as exc:
                raise QualificationError("git_packed_refs_invalid") from exc
            matches = [
                line.split(" ", 1)[0]
                for line in lines
                if line.endswith(f" {reference}") and not line.startswith(("#", "^"))
            ]
            if len(matches) != 1:
                raise QualificationError("git_head_reference_unresolved")
            commit = matches[0]
    else:
        commit = head

    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise QualificationError("git_head_commit_invalid")
    return commit


def _evidence(
    status: str,
    contract_sha256: str,
    requests_attempted: int,
    checks: list[dict[str, str]],
    current_commit: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": "vss-3.2.1-thor-local-qwen-alternate-runtime",
        "classification": "non-official-local-alternate",
        "status": status,
        "binding": _binding(contract_sha256, current_commit),
        "policy": {
            "official_capability_promotion_allowed": False,
            "writes_or_lifecycle_actions": False,
            "network_scope": "exact-no-proxy-local-http-endpoints-only",
            "raw_model_output_recorded": False,
        },
        "requests_attempted": requests_attempted,
        "checks": checks,
    }


def build_plan() -> dict[str, Any]:
    contract, contract_sha256 = _load_contract()
    validate_contract(contract)
    validate_artifact_lock()
    return _evidence(
        "planned",
        contract_sha256,
        0,
        [{"id": probe_id, "status": "planned"} for probe_id in PROBE_IDS],
    )


def _run_llm_probe(transport: Transport) -> None:
    payload = _llm_payload()
    _validate_llm_payload(payload)
    _validate_llm_tool_call(
        _response_json(
            transport.request(
                "llm",
                "POST",
                "/v1/chat/completions",
                _json_body(payload),
            )
        )
    )


def _run_vlm_probe(transport: Transport) -> None:
    payload = _vlm_payload()
    _validate_vlm_payload(payload)
    _validate_vlm_answer(
        _response_json(
            transport.request(
                "vlm",
                "POST",
                "/v1/chat/completions",
                _json_body(payload),
            )
        )
    )


def execute(transport: Transport) -> dict[str, Any]:
    contract, contract_sha256 = _load_contract()
    validate_contract(contract)
    validate_artifact_lock()
    checks = [{"id": probe_id, "status": "not-run"} for probe_id in PROBE_IDS]

    operations = (
        (
            "llm-model-identity",
            lambda: _validate_model_identity(
                _response_json(transport.request("llm", "GET", "/v1/models", b"")),
                ENDPOINTS["llm"][2],
            ),
        ),
        (
            "vlm-model-identity",
            lambda: _validate_model_identity(
                _response_json(transport.request("vlm", "GET", "/v1/models", b"")),
                ENDPOINTS["vlm"][2],
            ),
        ),
        (
            "llm-ping-tool-call",
            lambda: _run_llm_probe(transport),
        ),
        (
            "vlm-four-image-color-order",
            lambda: _run_vlm_probe(transport),
        ),
    )

    for index, (probe_id, operation) in enumerate(operations):
        try:
            operation()
            checks[index] = {"id": probe_id, "status": "passed"}
        except QualificationError as exc:
            checks[index] = {
                "id": probe_id,
                "status": "failed",
                "diagnostic": exc.code,
            }
            return _evidence(
                "failed", contract_sha256, transport.requests_attempted, checks
            )
    return _evidence("passed", contract_sha256, transport.requests_attempted, checks)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or execute bounded Thor-local Qwen alternate qualification."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform exactly four allowlisted local HTTP probes",
    )
    parser.add_argument(
        "--ack",
        default=None,
        help="exact non-official-lane acknowledgement required with --execute",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.execute:
            if args.ack is not None:
                raise QualificationError("acknowledgement_without_execute")
            output = build_plan()
        else:
            if args.ack != ACKNOWLEDGEMENT:
                raise QualificationError("exact_acknowledgement_required")
            output = execute(DirectLocalTransport())
    except (QualificationError, OSError) as exc:
        code = (
            exc.code if isinstance(exc, QualificationError) else "contract_read_error"
        )
        # A pre-request failure still emits controlled, redacted stdout evidence.
        output = _evidence(
            "failed",
            "0" * 64,
            0,
            [{"id": "preflight", "status": "failed", "diagnostic": code}],
            current_commit="0" * 40,
        )
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0 if output["status"] in {"planned", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
