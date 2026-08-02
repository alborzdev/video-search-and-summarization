#!/usr/bin/env python3
"""Validate the conservative 71-row current-source lock rebase."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
MAX_BYTES = 32_000_000

EXPECTED_REBASED_IDS = {
    "manifest-gap.agent-and-mcp-apis.00-nat-generate-chat",
    "manifest-gap.agent-and-mcp-apis.01-health",
    "manifest-gap.agent-and-mcp-apis.02-upload-handshake-and-completion",
    "manifest-gap.agent-and-mcp-apis.03-video-delete",
    "manifest-gap.agent-and-mcp-apis.04-rtsp-add-delete",
    "manifest-gap.agent-and-mcp-apis.06-lvs-mcp",
    "manifest-gap.audio-understanding.00-audio-aware-base-workflow",
    "manifest-gap.audio-understanding.01-audio-transcript-per-rt-vlm-chunk",
    "manifest-gap.audio-understanding.02-audio-aware-summarization-and-alerts",
    "manifest-gap.rt-vlm-api.00-openai-compatible-chat-completions",
    "manifest-gap.rt-vlm-api.01-text-only-chat",
    "manifest-gap.rt-vlm-api.02-multimodal-multi-turn-chat",
    "manifest-gap.rt-vlm-api.03-token-sse",
    "manifest-gap.rt-vlm-api.04-original-stream-api",
    "manifest-gap.rt-vlm-api.05-cv-compatible-stream-api",
    "manifest-gap.rt-vlm-api.06-file-api",
    "manifest-gap.rt-vlm-api.07-health-metadata-models-metrics",
    "manifest-gap.rt-vlm-media.03-allowlisted-file-uri",
    "manifest-gap.rt-vlm-media.07-incidents",
    "manifest-gap.rt-vlm-media.08-categories",
    "manifest-gap.rt-vlm-media.09-reasoning",
    "manifest-gap.rt-vlm-media.10-audio-transcript",
    "manifest-gap.rt-vlm-performance-observability.05-kafka-redis-error-publication",
    "manifest-gap.rt-vlm-performance-observability.06-prometheus-and-opentelemetry",
    "manifest-gap.rt-vlm-performance-observability.07-absolute-timestamp-metadata",
    "manifest-gap.search-scale.00-configuration-up-to-100-streams",
    "manifest-gap.video-summarization-live.00-live-captions",
    "manifest-gap.video-summarization-live.01-live-stream-summaries",
    "manifest-gap.video-summarization-live.02-stream-reports",
    "manifest-gap.video-summarization-live.03-caption-backed-q-a",
    "manifest-gap.video-summarization-live.04-elasticsearch-caption-storage",
    "manifest-gap.video-summarization-live.05-sse-mcp-server",
}

EXPECTED_OVERLAY = {
    "services/agent/src/vss_agents/api/custom_fastapi_worker.py": "b9b5354f32dd32c89e798559c7080b045d55cee8df41ca4822bdabab48f88075",
    "services/agent/src/vss_agents/api/video_delete.py": "67d2146665f7750c4bdd65513a3061e5b3955c95595f9ae3e4c7a23f7c13851c",
    "services/agent/src/vss_agents/api/video_ingest.py": "0074a4165684e207d629d2e56ed47d7abf0cc26b3a39f42bf197bc7bf4566534",
    "services/agent/src/vss_agents/api/rtsp_ingest.py": "b246293be1a0919a3620a35fb9e0fc423955186e31b91b900c2ae45a1302a38e",
    "services/agent/src/vss_agents/api/rtsp_delete.py": "d90e887b26f518a15a628224a33577e3469c4f3f29b66d84dae0470fe75285cb",
    "services/agent/src/vss_agents/tools/video_report_gen.py": "00fcea30078a11c188d094d082b0a0ecc7c1d991b1721ed1469a68ec963982ab",
    "deploy/docker/services/video-summarization/compose.yml": "6bf986735bb6971c03df50ec1cfa15fe2024ba213574f08ed767517e85b18e74",
    "deploy/docker/thor-local/qualification/expected/agent.json": "a20d7d3e2fcd8c8f9861477e9097e8071abdf493a4b3355793e4ef758d647540",
    "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py": "0a76e5e574d9466662d3424f45fc62ca26313577e87379e25fc4940d1c9bc52d",
    "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py": "24f6f968cbfac481dd1d310f4fe278b9db2311ec16f3f613c0525e8b77834a0d",
    "services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py": "76e8f53931f600cc6c8f05cf7d1f752688f6ed1e574fecf911e8b8dfee84df44",
    "services/video-summarization/src/lvs_mcp.py": "c31da08ff5847051732f08ab62344fbc898f40598bc69375910892bd35cdab2a",
    "services/video-summarization/src/rtvi_vlm_client.py": "bb10ff75f6cb13453b8c558a3060ee64b78d24b3c03469f7ae55d534c739bc6c",
    "services/video-summarization/src/via_server.py": "d4bd721cc0030f49875ef56f7c07a24aea3dd895d23fd405399a9c2ebf25856c",
    "services/video-summarization/src/via_stream_handler.py": "d6b8593af72f240b513f9b800c37bad1a3eb65115111ee9092d7d5d3a80ad9e7",
}

EXPECTED_NAT_ROUTES = {
    "POST /chat",
    "POST /chat/stream",
    "POST /generate",
    "POST /generate/full",
    "POST /generate/stream",
    "POST /v1/chat",
    "POST /v1/chat/completions",
    "POST /v1/chat/stream",
}

EXPECTED_SEARCH_ADDITIONS = {
    "POST /api/v1/search/attribute",
    "POST /api/v1/search/attribute/atif",
    "POST /api/v1/search/attribute/full",
    "POST /api/v1/search/attribute/stream",
    "POST /api/v1/search/fusion",
    "POST /api/v1/search/fusion/atif",
    "POST /api/v1/search/fusion/full",
    "POST /api/v1/search/fusion/stream",
    "POST /api/v1/search/image",
    "POST /api/v1/search/image/atif",
    "POST /api/v1/search/image/full",
    "POST /api/v1/search/image/stream",
}


class RebaseError(RuntimeError):
    """A rebase identity, topology, denominator, or safety invariant failed."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise RebaseError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise RebaseError(f"non-finite JSON constant in {label}: {value}")

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebaseError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise RebaseError(f"JSON root is not an object: {label}")
    return value


def _repo_file(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise RebaseError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for index, part in enumerate(pure.parts):
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RebaseError(f"repository input unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RebaseError(f"repository path contains a symlink: {relative}")
        if index < len(pure.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise RebaseError(f"repository parent is not a directory: {relative}")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
        raise RebaseError(f"repository input is not a bounded regular file: {relative}")
    return path


def _read(relative: str) -> bytes:
    path = _repo_file(relative)
    before = path.stat(follow_symlinks=False)
    payload = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    identity = lambda value: (  # noqa: E731 - compact immutable identity tuple
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise RebaseError(f"repository input changed while reading: {relative}")
    return payload


def _contract() -> dict[str, Any]:
    relative = CONTRACT_PATH.relative_to(REPO_ROOT).as_posix()
    contract = _strict_json(_read(relative), relative)
    if (
        contract.get("schema_version") != 1
        or contract.get("mode")
        != "advertised_entry_executors_71_current_source_rebase_successor"
    ):
        raise RebaseError("contract schema or mode drift")
    return contract


def _call_names(node: ast.AST) -> list[str]:
    result: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Attribute):
            result.append(child.func.attr)
        elif isinstance(child.func, ast.Name):
            result.append(child.func.id)
    return result


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise RebaseError(f"expected exactly one function definition: {name}")
    return matches[0]


def _is_terminal_guard(node: ast.If) -> bool:
    if not isinstance(node.test, ast.BoolOp) or not isinstance(node.test.op, ast.Or):
        return False
    attrs = {
        child.attr
        for child in ast.walk(node.test)
        if isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id == "req_info"
    }
    return attrs == {"abort_requested", "finalized"} and any(
        isinstance(child, ast.Return)
        for child in ast.walk(ast.Module(body=node.body, type_ignores=[]))
    )


def _validate_kafka_topology(contract: dict[str, Any]) -> dict[str, Any]:
    topology = contract.get("kafka_topology")
    if not isinstance(topology, dict):
        raise RebaseError("Kafka topology contract missing")
    if topology.get("call_chain") != [
        "_on_vlm_chunk_response",
        "_publish_chunk_messages_if_active",
        "_send_protobuf_to_kafka",
    ] or {
        "terminal_state_flags": topology.get("terminal_state_flags"),
        "publisher_send_call_count": topology.get("publisher_send_call_count"),
        "on_response_direct_send_call_count": topology.get(
            "on_response_direct_send_call_count"
        ),
        "on_response_pre_publish_terminal_rechecks": topology.get(
            "on_response_pre_publish_terminal_rechecks"
        ),
    } != {
        "terminal_state_flags": ["abort_requested", "finalized"],
        "publisher_send_call_count": 2,
        "on_response_direct_send_call_count": 0,
        "on_response_pre_publish_terminal_rechecks": 2,
    }:
        raise RebaseError("Kafka call-chain contract drift")
    source_path = topology.get("source_path")
    if not isinstance(source_path, str):
        raise RebaseError("Kafka source path missing")
    try:
        tree = ast.parse(_read(source_path), filename=source_path)
    except (SyntaxError, ValueError) as exc:
        raise RebaseError("Kafka source is not valid Python") from exc

    on_response = _function(tree, "_on_vlm_chunk_response")
    publisher = _function(tree, "_publish_chunk_messages_if_active")
    _function(tree, "_send_protobuf_to_kafka")
    on_calls = _call_names(on_response)
    publisher_calls = _call_names(publisher)
    if on_calls.count("_publish_chunk_messages_if_active") != 1:
        raise RebaseError("chunk response does not call guarded publisher exactly once")
    if on_calls.count("_send_protobuf_to_kafka") != 0:
        raise RebaseError("chunk response bypasses guarded Kafka publisher")
    if publisher_calls.count("_send_protobuf_to_kafka") != 2:
        raise RebaseError("guarded publisher Kafka send denominator drift")

    publisher_with = next(
        (
            statement
            for statement in publisher.body
            if isinstance(statement, ast.With)
            and any(
                isinstance(item.context_expr, ast.Attribute)
                and item.context_expr.attr == "_lock"
                for item in statement.items
            )
        ),
        None,
    )
    if not publisher_with or not publisher_with.body:
        raise RebaseError("guarded publisher lock scope missing")
    if not isinstance(publisher_with.body[0], ast.If) or not _is_terminal_guard(
        publisher_with.body[0]
    ):
        raise RebaseError(
            "guarded publisher terminal-state guard is not first under lock"
        )
    if _call_names(publisher_with).count("_send_protobuf_to_kafka") != 2:
        raise RebaseError("Kafka sends escaped guarded publisher lock scope")

    publish_call = next(
        child
        for child in ast.walk(on_response)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "_publish_chunk_messages_if_active"
    )
    pre_publish_guards = [
        child
        for child in ast.walk(on_response)
        if isinstance(child, ast.If)
        and child.lineno < publish_call.lineno
        and _is_terminal_guard(child)
    ]
    if len(pre_publish_guards) != 2:
        raise RebaseError(
            "chunk response pre-publish terminal recheck denominator drift"
        )
    return {
        "call_chain": topology["call_chain"],
        "publisher_send_call_count": 2,
        "on_response_direct_send_call_count": 0,
        "on_response_pre_publish_terminal_rechecks": 2,
        "publication_suppressed_after_abort_or_finalized": True,
    }


def _literal_string_set(node: ast.AST, variable: str) -> set[str]:
    assignments = [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == variable
            for target in child.targets
        )
    ]
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Set):
        raise RebaseError(f"historical literal set missing: {variable}")
    result: set[str] = set()
    for element in assignments[0].value.elts:
        if not isinstance(element, ast.Tuple) or len(element.elts) != 2:
            raise RebaseError(f"historical literal tuple malformed: {variable}")
        values = [ast.literal_eval(item) for item in element.elts]
        if not all(isinstance(item, str) for item in values):
            raise RebaseError(f"historical route is not textual: {variable}")
        result.add(f"{values[0]} {values[1]}")
    return result


def _validate_nat_inventory(
    contract: dict[str, Any], historical_waves: list[dict[str, Any]]
) -> dict[str, Any]:
    nat = contract.get("nat_inventory")
    if not isinstance(nat, dict):
        raise RebaseError("NAT inventory contract missing")
    if nat.get("historical_denominator") != 44 or nat.get("current_denominator") != 56:
        raise RebaseError("NAT denominator contract drift")
    if set(nat.get("required_nat_generate_chat_routes", [])) != EXPECTED_NAT_ROUTES:
        raise RebaseError("required NAT route contract drift")
    if set(nat.get("search_additions", [])) != EXPECTED_SEARCH_ADDITIONS:
        raise RebaseError("Search addition contract drift")

    document = _strict_json(_read(nat["source_path"]), nat["source_path"])
    operations = document.get("operations")
    if not isinstance(operations, list):
        raise RebaseError("current agent operation inventory missing")
    current: set[str] = set()
    for row in operations:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("method"), str)
            or not isinstance(row.get("path"), str)
        ):
            raise RebaseError("malformed current agent operation")
        current.add(f"{row['method']} {row['path']}")
    if (
        document.get("surface") != "agent"
        or document.get("declared_operation_count") != 56
        or document.get("normalized_unique_operation_count") != 56
        or len(operations) != 56
        or len(current) != 56
    ):
        raise RebaseError("current NAT operation denominator is not exact 56")
    methods = Counter(row["method"] for row in operations)
    if document.get("method_counts") != dict(methods):
        raise RebaseError("current NAT method counts drift")
    if not EXPECTED_NAT_ROUTES.issubset(current):
        raise RebaseError("one or more required NAT generate/chat routes are absent")
    if not EXPECTED_SEARCH_ADDITIONS.issubset(current):
        raise RebaseError("one or more exact Search additions are absent")
    if len(current - EXPECTED_SEARCH_ADDITIONS) != 44:
        raise RebaseError("56-operation inventory does not partition as 44 + 12")

    wave6 = next(row for row in historical_waves if row.get("wave") == 6)
    executor_source = _read(wave6["executor_path"])
    if _sha(executor_source) != wave6["executor_sha256"]:
        raise RebaseError("immutable Wave 6 executor identity drift")
    historical_tree = ast.parse(executor_source, filename=wave6["executor_path"])
    historical_nat = _function(historical_tree, "_nat_generate_chat")
    if _literal_string_set(historical_nat, "required") != EXPECTED_NAT_ROUTES:
        raise RebaseError("historical executor eight-route NAT contract drift")
    historical_constants = {
        child.value
        for child in ast.walk(historical_nat)
        if isinstance(child, ast.Constant) and isinstance(child.value, int)
    }
    if 44 not in historical_constants:
        raise RebaseError("historical executor 44-operation denominator missing")
    return {
        "historical_denominator": 44,
        "current_denominator": 56,
        "search_additions": sorted(EXPECTED_SEARCH_ADDITIONS),
        "search_addition_count": 12,
        "required_nat_generate_chat_routes": sorted(EXPECTED_NAT_ROUTES),
        "required_nat_generate_chat_route_count": 8,
    }


def validate() -> dict[str, Any]:
    contract = _contract()
    predecessor = contract.get("immutable_predecessor")
    if not isinstance(predecessor, dict):
        raise RebaseError("immutable predecessor contract missing")
    inventory_raw = _read(predecessor["inventory_path"])
    receipt_raw = _read(predecessor["receipt_path"])
    if _sha(inventory_raw) != predecessor.get("inventory_raw_sha256"):
        raise RebaseError("immutable predecessor inventory identity drift")
    if _sha(receipt_raw) != predecessor.get("receipt_raw_sha256"):
        raise RebaseError("immutable predecessor receipt identity drift")
    inventory = _strict_json(inventory_raw, predecessor["inventory_path"])
    receipt = _strict_json(receipt_raw, predecessor["receipt_path"])
    if (
        receipt.get("candidate_only") is not True
        or receipt.get("can_mark_passed_current") is not False
        or receipt.get("runtime_evidence") != []
        or receipt.get("official_capability_effect") != "none_candidate_only"
    ):
        raise RebaseError("immutable predecessor receipt non-promotion boundary drift")

    overlay_rows = contract.get("current_source_overlay")
    if not isinstance(overlay_rows, list):
        raise RebaseError("current-source overlay missing")
    overlay = {
        row.get("path"): row.get("sha256")
        for row in overlay_rows
        if isinstance(row, dict)
    }
    if overlay != EXPECTED_OVERLAY or len(overlay_rows) != len(overlay):
        raise RebaseError("exact fifteen-path overlay drift")
    for path, digest in overlay.items():
        if _sha(_read(path)) != digest:
            raise RebaseError(f"current overlay source drift: {path}")

    candidate_rows = [
        row
        for row in inventory.get("rows", [])
        if row.get("disposition") == "candidate"
    ]
    if (
        len(candidate_rows) != 71
        or len({row.get("entry_id") for row in candidate_rows}) != 71
    ):
        raise RebaseError("retained candidate denominator is not exact 71")
    waves = inventory.get("historical_waves")
    if not isinstance(waves, list) or [row.get("wave") for row in waves] != list(
        range(1, 8)
    ):
        raise RebaseError("immutable historical Wave 1-7 denominator drift")

    historical_cases: dict[str, dict[str, Any]] = {}
    for wave in waves:
        raw = _read(wave["inventory_path"])
        if _sha(raw) != wave["inventory_sha256"]:
            raise RebaseError(f"immutable Wave {wave['wave']} inventory identity drift")
        value = _strict_json(raw, wave["inventory_path"])
        for case in value.get("cases", []):
            entry_id = case.get("entry_id")
            if not isinstance(entry_id, str) or entry_id in historical_cases:
                raise RebaseError("duplicate or malformed historical case identity")
            historical_cases[entry_id] = case

    rebased: set[str] = set()
    unchanged: set[str] = set()
    overlay_usage: Counter[str] = Counter()
    current_lock_references = 0
    for row in candidate_rows:
        entry_id = row["entry_id"]
        case = historical_cases.get(entry_id)
        if not isinstance(case, dict):
            raise RebaseError(f"retained historical case missing: {entry_id}")
        locks = case.get("source_locks")
        if not isinstance(locks, list) or len(locks) != row.get("source_lock_count"):
            raise RebaseError(f"retained source-lock count drift: {entry_id}")
        affected_paths = {lock.get("path") for lock in locks} & set(overlay)
        (rebased if affected_paths else unchanged).add(entry_id)
        for lock in locks:
            path, historical_digest = lock.get("path"), lock.get("sha256")
            if not isinstance(path, str) or not isinstance(historical_digest, str):
                raise RebaseError(f"malformed retained source lock: {entry_id}")
            expected = overlay.get(path, historical_digest)
            if _sha(_read(path)) != expected:
                raise RebaseError(
                    f"current retained source lock drift: {entry_id}: {path}"
                )
            if path in overlay:
                if historical_digest == expected:
                    raise RebaseError(f"overlay path did not actually change: {path}")
                overlay_usage[path] += 1
            current_lock_references += 1

    partition = contract.get("partition")
    if not isinstance(partition, dict):
        raise RebaseError("partition contract missing")
    if (
        partition.get("retained_candidate_rows") != 71
        or partition.get("unchanged_rows") != 39
        or partition.get("rebased_rows") != 32
        or rebased != EXPECTED_REBASED_IDS
        or set(partition.get("rebased_entry_ids", [])) != EXPECTED_REBASED_IDS
        or len(partition.get("rebased_entry_ids", [])) != len(EXPECTED_REBASED_IDS)
        or len(unchanged) != 39
        or len(rebased) != 32
        or unchanged & rebased
        or unchanged | rebased != {row["entry_id"] for row in candidate_rows}
    ):
        raise RebaseError("exact 39 unchanged + 32 rebased partition drift")
    if set(overlay_usage) != set(EXPECTED_OVERLAY):
        raise RebaseError("one or more overlay paths are not used by retained rows")
    if current_lock_references != 182:
        raise RebaseError("retained current-source lock reference denominator drift")

    kafka = _validate_kafka_topology(contract)
    nat = _validate_nat_inventory(contract, waves)
    policy = contract.get("policy")
    if policy != {
        "candidate_only": True,
        "historical_inventory_rewritten": False,
        "historical_receipt_rewritten": False,
        "historical_dispatch_replayed": False,
        "runtime_evidence": [],
        "can_mark_passed_current": False,
        "official_capability_effect": "none_candidate_only",
        "warehouse_sample_bundle": "excluded",
    }:
        raise RebaseError("non-promotion policy drift")

    return {
        "schema_version": 1,
        "status": "pass_current_source_rebase_static_only",
        "retained_candidate_rows": 71,
        "unchanged_rows": 39,
        "rebased_rows": 32,
        "current_source_overlay_paths": 15,
        "current_source_lock_references": 182,
        "overlay_reference_counts": dict(sorted(overlay_usage.items())),
        "rebased_entry_ids": sorted(rebased),
        "kafka_topology": kafka,
        "nat_inventory": nat,
        "historical_inventory_rewritten": False,
        "historical_receipt_rewritten": False,
        "historical_dispatch_replayed": False,
        "runtime_evidence": [],
        "can_mark_passed_current": False,
        "official_capability_effect": "none_candidate_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate current sources")
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    try:
        result = validate()
    except (
        RebaseError,
        KeyError,
        TypeError,
        OSError,
        StopIteration,
        ValueError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "PASS: 71 retained rows = 39 unchanged + 32 current-source rebased; "
            "fifteen locks; Kafka abort gate; NAT 56 = 44 + 12; no promotion"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
