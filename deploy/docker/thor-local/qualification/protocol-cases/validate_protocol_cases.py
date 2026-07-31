#!/usr/bin/env python3
"""Fail-closed static validator for the Thor non-REST protocol case ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


EXPECTED_CAPABILITIES = {
    "protocol.agent.websocket",
    "protocol.alert.websocket",
    "protocol.rt-vlm.sse",
    "protocol.kafka.nvschema",
    "protocol.redis.events",
    "protocol.vios.webrtc-live",
    "protocol.vios.webrtc-replay",
}
SAFE_PREFIXES = ("vss-protocol-case-", "vss:protocol-case:")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when the static protocol contract is incomplete or has drifted."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path}: {exc}") from exc


def canonical_contract_hash(document: dict[str, Any]) -> str:
    payload = {
        "schema_version": document.get("schema_version"),
        "target_commit": document.get("target_commit"),
        "cases": document.get("cases"),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _resolve_source(repo_root: Path, relative: str) -> Path:
    _require(
        relative and not relative.startswith("/"), f"unsafe source path: {relative!r}"
    )
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ContractError(f"source escapes repository: {relative}") from exc
    _require(candidate.exists(), f"source is missing: {relative}")
    _require(
        candidate.is_file() and not candidate.is_symlink(),
        f"source is not a regular non-symlink: {relative}",
    )
    return candidate


def _git_blob_oid(repo_root: Path, path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _validate_source(repo_root: Path, source: dict[str, Any], label: str) -> None:
    required = {"path", "git_blob_oid", "content_sha256", "locator"}
    _require(
        set(source) == required,
        f"{label}: source keys must be exactly {sorted(required)}",
    )
    path = _resolve_source(repo_root, source["path"])
    content = path.read_bytes()
    actual_sha = hashlib.sha256(content).hexdigest()
    _require(
        HEX64.fullmatch(source["content_sha256"]) is not None,
        f"{label}: invalid source SHA-256",
    )
    _require(
        actual_sha == source["content_sha256"],
        f"{label}: source SHA-256 drift: {source['path']}",
    )
    _require(
        HEX40.fullmatch(source["git_blob_oid"]) is not None,
        f"{label}: invalid Git blob OID",
    )
    _require(
        _git_blob_oid(repo_root, path) == source["git_blob_oid"],
        f"{label}: Git blob drift: {source['path']}",
    )
    _require(
        isinstance(source["locator"], str) and source["locator"].strip(),
        f"{label}: empty source locator",
    )


def _validate_wire_schema(schema: dict[str, Any], label: str) -> None:
    _require(
        set(schema) == {"encoding", "fields", "additional_fields"},
        f"{label}: incomplete wire schema",
    )
    _require(
        schema["additional_fields"] in {"allowed", "ignored", "rejected", "opaque"},
        f"{label}: invalid additional_fields",
    )
    seen: set[str] = set()
    for field in schema["fields"]:
        _require(
            set(field) == {"path", "type", "required", "contract"},
            f"{label}: malformed field",
        )
        _require(
            field["path"] not in seen, f"{label}: duplicate field path {field['path']}"
        )
        seen.add(field["path"])
        _require(
            isinstance(field["required"], bool), f"{label}: required is not boolean"
        )
        _require(
            all(
                isinstance(field[k], str) and field[k].strip()
                for k in ("path", "type", "contract")
            ),
            f"{label}: empty field metadata",
        )


def _validate_vector(vector: dict[str, Any], label: str, *, negative: bool) -> None:
    common = {
        "id",
        "network_scope",
        "deadline_seconds",
        "max_events",
        "fixture",
        "expected",
    }
    required = common | (
        {"adjacent_mutation", "expected_rejection"} if negative else set()
    )
    _require(
        set(vector) == required,
        f"{label}: vector keys must be exactly {sorted(required)}",
    )
    _require(
        vector["network_scope"] == "loopback_only",
        f"{label}: network scope is not loopback-only",
    )
    _require(
        type(vector["deadline_seconds"]) is int
        and 1 <= vector["deadline_seconds"] <= 60,
        f"{label}: unsafe deadline",
    )
    _require(
        type(vector["max_events"]) is int and 1 <= vector["max_events"] <= 32,
        f"{label}: unsafe event bound",
    )
    _require(
        isinstance(vector["expected"], str) and vector["expected"].strip(),
        f"{label}: empty expectation",
    )
    if negative:
        mutation = vector["adjacent_mutation"]
        _require(
            set(mutation) in ({"operation", "path"}, {"operation", "path", "value"}),
            f"{label}: malformed adjacent mutation",
        )
        _require(
            mutation["operation"] in {"remove", "replace", "truncate"},
            f"{label}: invalid adjacent mutation",
        )
        _require(
            isinstance(mutation["path"], str) and mutation["path"].startswith("/"),
            f"{label}: mutation path is not JSON Pointer-like",
        )
        _require(
            isinstance(vector["expected_rejection"], str)
            and vector["expected_rejection"].strip(),
            f"{label}: empty rejection",
        )


def validate(document: dict[str, Any], repo_root: Path) -> None:
    _require(
        set(document)
        == {"schema_version", "target_commit", "contract_set_sha256", "cases"},
        "unexpected top-level keys",
    )
    _require(document["schema_version"] == 1, "unsupported schema version")
    _require(
        HEX40.fullmatch(document["target_commit"]) is not None, "invalid target commit"
    )
    expected_hash = canonical_contract_hash(document)
    _require(
        document["contract_set_sha256"] == expected_hash, "contract_set_sha256 mismatch"
    )
    cases = document["cases"]
    _require(
        isinstance(cases, list) and len(cases) == 7,
        "exactly seven protocol cases are required",
    )
    by_capability = {case.get("capability_id"): case for case in cases}
    _require(
        len(by_capability) == 7 and set(by_capability) == EXPECTED_CAPABILITIES,
        "protocol capability denominator drift",
    )

    for capability_id, case in by_capability.items():
        label = capability_id
        required_keys = {
            "capability_id",
            "case_id",
            "protocol",
            "runtime_state",
            "runtime_evidence",
            "endpoint_or_topic",
            "method_or_handshake",
            "auth",
            "headers",
            "request_schema",
            "response_schema",
            "sequence",
            "terminal_and_error_semantics",
            "ordering_and_timing",
            "positive_vector",
            "adjacent_negative_vectors",
            "mutation",
            "sources",
            "source_limitations",
        }
        _require(set(case) == required_keys, f"{label}: case keys drift")
        _require(
            case["case_id"]
            == f"protocol-case.{capability_id.removeprefix('protocol.')}",
            f"{label}: case ID mismatch",
        )
        _require(
            case["protocol"]
            in {"websocket", "sse", "kafka", "redis-streams", "webrtc"},
            f"{label}: unknown protocol",
        )
        _require(
            case["runtime_state"] == "unexecuted" and case["runtime_evidence"] == [],
            f"{label}: static ledger cannot claim runtime execution",
        )
        for key in (
            "endpoint_or_topic",
            "method_or_handshake",
            "auth",
            "terminal_and_error_semantics",
            "ordering_and_timing",
        ):
            _require(
                isinstance(case[key], list)
                and case[key]
                and all(isinstance(v, str) and v.strip() for v in case[key]),
                f"{label}: empty {key}",
            )
        _require(
            isinstance(case["headers"], list)
            and all(isinstance(v, str) and v.strip() for v in case["headers"]),
            f"{label}: invalid headers",
        )
        _validate_wire_schema(case["request_schema"], f"{label}.request_schema")
        _validate_wire_schema(case["response_schema"], f"{label}.response_schema")
        sequence = case["sequence"]
        _require(
            isinstance(sequence, list) and len(sequence) >= 2,
            f"{label}: sequence is incomplete",
        )
        _require(
            [step.get("order") for step in sequence]
            == list(range(1, len(sequence) + 1)),
            f"{label}: sequence order is not contiguous",
        )
        _require(
            any(step.get("terminal") is True for step in sequence),
            f"{label}: no terminal sequence step",
        )
        _validate_vector(case["positive_vector"], f"{label}.positive", negative=False)
        negatives = case["adjacent_negative_vectors"]
        _require(
            isinstance(negatives, list) and negatives,
            f"{label}: no adjacent-negative vector",
        )
        for index, negative in enumerate(negatives):
            _validate_vector(negative, f"{label}.negative[{index}]", negative=True)
        mutation = case["mutation"]
        _require(
            set(mutation) == {"class", "ownership", "cleanup"},
            f"{label}: mutation contract is incomplete",
        )
        _require(
            mutation["class"] in {"connection_only", "transient_namespaced"},
            f"{label}: invalid mutation class",
        )
        _require(
            any(prefix in mutation["ownership"] for prefix in SAFE_PREFIXES),
            f"{label}: ownership lacks protocol-case namespace",
        )
        _require(
            isinstance(mutation["cleanup"], list) and mutation["cleanup"],
            f"{label}: cleanup is empty",
        )
        sources = case["sources"]
        _require(isinstance(sources, list) and sources, f"{label}: no exact sources")
        for index, source in enumerate(sources):
            _validate_source(repo_root, source, f"{label}.sources[{index}]")
        _require(
            isinstance(case["source_limitations"], list),
            f"{label}: source_limitations must be a list",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract", type=Path, default=Path(__file__).with_name("protocol-cases.json")
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[5]
    )
    parser.add_argument("--print-hash", action="store_true")
    args = parser.parse_args()
    try:
        document = load_json(args.contract)
        if args.print_hash:
            print(canonical_contract_hash(document))
            return 0
        validate(document, args.repo_root.resolve())
    except (ContractError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS: seven exact non-REST protocol cases are statically pinned; runtime remains unexecuted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
