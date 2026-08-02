#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the provider-free LVS two-video artifact-correlation oracle."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any
from typing import Callable
from typing import Sequence

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
FIXTURE = HERE / "fixture.json"
FIXTURE_SCHEMA = HERE / "fixture.schema.json"
RESULT_SCHEMA = HERE / "result.schema.json"
MAX_BYTES = 32 * 1024 * 1024
CAPABILITY_ID = "manifest-entry.video-summarization-file.02-multi-video-report"
EXPECTED_LOCK_PATHS = {
    "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
    "deploy/docker/thor-local/qualification/lvs-multi-video-artifact-oracle-successor/fixture.json",
    "services/agent/src/vss_agents/tools/video_report_gen.py",
    "services/agent/src/vss_agents/agents/report_agent.py",
    "services/agent/tests/unit_test/tools/test_video_report_gen.py",
    "services/agent/tests/unit_test/agents/test_report_agent.py",
}


class OracleError(RuntimeError):
    """A locked static contract or semantic observation failed closed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OracleError("cannot open bounded regular source") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
            raise OracleError("source is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 131072))
            if not chunk:
                raise OracleError("short source read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, key) != getattr(after, key) for key in stable):
            raise OracleError("source changed during bounded read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OracleError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            _read(path).decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                OracleError(f"non-finite JSON value: {token}")
            ),
        )
    except OracleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OracleError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise OracleError("JSON root must be an object")
    return value


def _repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise OracleError("unsafe repository path")
    current = ROOT
    for part in candidate.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise OracleError("symlink source rejected")
        except OSError as exc:
            raise OracleError("missing source lock") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise OracleError("source lock escapes repository") from exc
    return current


def _schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.path),
    )
    if errors:
        raise OracleError(f"{label} schema failure: {errors[0].message}")


def _load_contract() -> dict[str, Any]:
    contract = _json(CONTRACT)
    _schema(contract, CONTRACT_SCHEMA, "contract")
    paths = [item["path"] for item in contract["source_locks"]]
    if len(paths) != len(set(paths)) or set(paths) != EXPECTED_LOCK_PATHS:
        raise OracleError("source-lock inventory drift")
    for lock in contract["source_locks"]:
        if _sha256(_read(_repo_path(lock["path"]))) != lock["sha256"]:
            raise OracleError(f"source lock mismatch: {lock['path']}")
    return contract


def _find_capability_row() -> dict[str, Any]:
    source = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json"
        )
    )
    rows = source.get("entries")
    if not isinstance(rows, list):
        raise OracleError("candidate row collection missing")
    found = [
        row["proposed_capability"]
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("proposed_capability"), dict)
        and row["proposed_capability"].get("id") == CAPABILITY_ID
    ]
    if len(found) != 1:
        raise OracleError("candidate row identity is not unique")
    row = found[0]
    contract = row.get("contract", {})
    if (
        row.get("runtime_state") != "not_qualified"
        or row.get("thor_state") != "wired"
        or contract.get("warehouse_sample_bundle") != "excluded"
        or contract.get("required_semantics")
        != [
            "Accept multiple selected videos in one report call and retain per-video provenance.",
            "Attribute each disjoint planted event to the correct source file in the report.",
        ]
    ):
        raise OracleError("candidate row boundary drift")
    return row


def _load_fixture() -> dict[str, Any]:
    fixture = _json(FIXTURE)
    _schema(fixture, FIXTURE_SCHEMA, "fixture")
    videos = fixture["videos"]
    if [item["source_index"] for item in videos] != [0, 1]:
        raise OracleError("video source order drift")
    if len({item["sensor_id"] for item in videos}) != 2:
        raise OracleError("video identities are not distinct")
    if len({item["required_event_token"] for item in videos}) != 2:
        raise OracleError("planted events are not disjoint")
    for video in videos:
        if _sha256(_canonical(video["recipe"])) != video["recipe_canonical_sha256"]:
            raise OracleError("video recipe digest drift")
        if video["materialized_video_sha256"] is not None:
            raise OracleError("static fixture must not claim materialized media")
    return fixture


def _extract_function(relative: str, function_name: str) -> Callable[..., Any]:
    source = _read(_repo_path(relative)).decode("utf-8")
    tree = ast.parse(source, filename=relative)
    found = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(found) != 1 or isinstance(found[0], ast.AsyncFunctionDef):
        raise OracleError(f"production helper missing or ambiguous: {function_name}")
    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            found[0],
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(isolated, relative, "exec"), namespace)
    function = namespace.get(function_name)
    if not callable(function):
        raise OracleError(f"production helper did not compile: {function_name}")
    return function


def _report_rows(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for video in fixture["videos"]:
        artifacts = [
            item
            for item in fixture["artifacts"]
            if item["sensor_id"] == video["sensor_id"]
        ]
        by_extension = {item["extension"]: item for item in artifacts}
        rows.append(
            {
                "sensor_id": video["sensor_id"],
                "http_url": f"http://127.0.0.1:8100/static/{by_extension['md']['object_store_key']}",
                "pdf_url": f"http://127.0.0.1:8100/static/{by_extension['pdf']['object_store_key']}",
                "object_store_key": by_extension["md"]["object_store_key"],
                "pdf_object_store_key": by_extension["pdf"]["object_store_key"],
                "file_size": len(by_extension["md"]["semantic_text"].encode()),
                "pdf_file_size": len(by_extension["pdf"]["semantic_text"].encode()),
            }
        )
    return rows


def _production_observability(fixture: dict[str, Any]) -> dict[str, Any]:
    correlate = _extract_function(
        "services/agent/src/vss_agents/tools/video_report_gen.py",
        "_correlate_video_reports",
    )
    observe = _extract_function(
        "services/agent/src/vss_agents/agents/report_agent.py",
        "_video_report_observability",
    )
    sensor_ids = [item["sensor_id"] for item in fixture["videos"]]
    # Reverse provider completion order deliberately. Production must restore
    # the caller's ordered source identity before exposing artifact metadata.
    correlated = correlate(
        list(reversed(_report_rows(fixture))),
        sensor_ids,
        [],
        fixture["report_correlation_id"],
    )
    output = SimpleNamespace(
        report_correlation_id=fixture["report_correlation_id"],
        requested_sensor_ids=sensor_ids,
        failed_sensor_ids=[],
        all_reports=correlated,
        http_url=correlated[0]["http_url"],
    )
    observed = observe(output, sensor_ids)
    if not observed["complete"] or observed["successful_sensor_ids"] != sensor_ids:
        raise OracleError(
            "production observability did not preserve exact source order"
        )
    return observed


def _semantic_oracle(
    fixture: dict[str, Any], artifacts: Sequence[dict[str, Any]] | None = None
) -> dict[str, bool]:
    observed = [
        copy.deepcopy(item)
        for item in (artifacts if artifacts is not None else fixture["artifacts"])
    ]
    videos = {item["sensor_id"]: item for item in fixture["videos"]}
    if len(observed) != 4:
        raise OracleError("semantic oracle requires exactly four artifacts")
    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for artifact in observed:
        sensor_id = artifact.get("sensor_id")
        video = videos.get(sensor_id)
        extension = artifact.get("extension")
        if video is None or extension not in {"md", "pdf"}:
            raise OracleError("artifact has an unknown source or extension")
        if (
            artifact.get("source_index") != video["source_index"]
            or artifact.get("source_count") != 2
            or artifact.get("report_correlation_id") != fixture["report_correlation_id"]
            or not str(artifact.get("object_store_key", "")).endswith(f".{extension}")
        ):
            raise OracleError("artifact correlation metadata mismatch")
        text = artifact.get("semantic_text")
        if not isinstance(text, str) or _sha256(text.encode()) != artifact.get(
            "semantic_text_sha256"
        ):
            raise OracleError("artifact semantic digest mismatch")
        if sensor_id not in text or video["required_event_token"] not in text:
            raise OracleError(
                "artifact does not attribute its planted event to its source"
            )
        if any(token in text for token in video["forbidden_event_tokens"]):
            raise OracleError("artifact contains a cross-source planted event")
        bucket = pairs.setdefault(sensor_id, {})
        if extension in bucket:
            raise OracleError("duplicate artifact extension for source")
        bucket[extension] = artifact

    if set(pairs) != set(videos) or any(
        set(pair) != {"md", "pdf"} for pair in pairs.values()
    ):
        raise OracleError("each source requires one Markdown/PDF pair")
    for pair in pairs.values():
        if (
            pair["md"]["object_store_key"].rsplit(".", 1)[0]
            != pair["pdf"]["object_store_key"].rsplit(".", 1)[0]
        ):
            raise OracleError("Markdown/PDF artifact stems are not paired")
    return {
        "per_source_attribution": True,
        "reciprocal_negative_exclusion": True,
        "markdown_pdf_pairing": True,
        "semantic_digest_match": True,
        "one_missing_source_cannot_pass": True,
    }


def run() -> dict[str, Any]:
    contract = _load_contract()
    _find_capability_row()
    fixture = _load_fixture()
    observed = _production_observability(fixture)
    semantic = _semantic_oracle(fixture)
    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "static_semantic_oracle_complete_non_promoting",
        "candidate_implementation_state": "concrete_static_candidate",
        "runtime_evidence": [],
        "canonical_state_advanced": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
        "contract_sha256": _sha256(_read(CONTRACT)),
        "fixture_sha256": _sha256(_read(FIXTURE)),
        "source_lock_count": len(contract["source_locks"]),
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "video_count": len(fixture["videos"]),
            "artifact_count": len(fixture["artifacts"]),
            "disjoint_event_count": len(
                {item["required_event_token"] for item in fixture["videos"]}
            ),
            "materialized_video_count": sum(
                item["materialized_video_sha256"] is not None
                for item in fixture["videos"]
            ),
        },
        "production_observability": {
            "ordered_source_ids": observed["requested_sensor_ids"],
            "source_indexes": [item["source_index"] for item in observed["artifacts"]],
            "source_count": len(observed["requested_sensor_ids"]),
            "report_count": observed["report_count"],
            "shared_correlation_id": observed["report_correlation_id"],
            "complete": observed["complete"],
        },
        "semantic_oracle": semantic,
        "retained_gaps": contract["retained_gaps"],
        "confinement": {
            "network_calls": 0,
            "docker_calls": 0,
            "subprocess_calls": 0,
            "downloads": 0,
            "service_lifecycle_calls": 0,
            "model_calls": 0,
            "filesystem_writes": 0,
            "warehouse_sample_bundle": "excluded",
        },
    }
    _schema(result, RESULT_SCHEMA, "result")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the static non-promoting result as JSON",
    )
    options = parser.parse_args(argv)
    result = run()
    if options.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
