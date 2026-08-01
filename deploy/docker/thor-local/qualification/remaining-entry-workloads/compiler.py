#!/usr/bin/env python3
"""Compile locked, candidate-only API and deployment workload plans."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[4]
OUTPUT = PACKAGE / "workloads.json"
SCHEMA = PACKAGE / "workload.schema.json"
SOURCES = {
    "candidates": (
        "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
        "a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd",
    ),
    "api_inventory": (
        "deploy/docker/thor-local/qualification/remaining-entry-workloads/api-inventory.json",
        "07087f97a00721e8a47d399a3a14275fa28bd47439d4ba955563f59ef7bc4b77",
    ),
    "deployment_inventory": (
        "deploy/docker/thor-local/qualification/remaining-entry-workloads/deployment-inventory.json",
        "14b8087d963341343bd1b4977f196406b0b26d7e267e3d944632c3adcac2ccd8",
    ),
    "manifest": (
        "deploy/docker/thor-local/parity/manifest.json",
        "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    ),
    "official_capabilities": (
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    ),
}
SCHEMA_RAW_SHA256 = "736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14"
EXPECTED_OUTPUT_RAW_SHA256 = (
    "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312"
)
EXPECTED_PAYLOAD_SHA256 = (
    "0e8512e64399af7d8acc0c7136efbd52da4ebf9119ad0826859e6fce6906d847"
)
FORBIDDEN = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
    "passed_current",
    "<todo",
    "tbd",
    "placeholder",
    "generic default",
)


class WorkloadError(RuntimeError):
    pass


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical(v: Any) -> bytes:
    return json.dumps(
        v, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def encoded(v: Any) -> bytes:
    return (json.dumps(v, indent=2, sort_keys=True) + "\n").encode()


def load(path: Path, digest: str | None = None) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        raise WorkloadError(f"not a regular file: {path}")
    raw = path.read_bytes()
    observed = sha(raw)
    if digest not in (None, "TO_BE_PINNED") and observed != digest:
        raise WorkloadError(f"raw lock drift: {path}")

    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise WorkloadError(f"duplicate key {k!r}: {path}")
            out[k] = v
        return out

    return json.loads(raw, object_pairs_hook=pairs), observed


def regular_surface(surface: str) -> None:
    base = surface.split("#", 1)[0]
    relative = Path(base)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise WorkloadError(f"surface is not a safe repo-relative path: {surface}")

    current = ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise WorkloadError(f"surface traverses a symlink: {surface}")

    path = current.resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise WorkloadError(f"surface escapes repo: {surface}") from exc
    if path.is_symlink() or not path.is_file():
        raise WorkloadError(f"surface is not a regular repo file: {surface}")


def atomic_write(path: Path, payload: bytes) -> None:
    """Atomically replace a regular output without following symlinks."""
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise WorkloadError(f"output parent is not a regular directory: {parent}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise WorkloadError(f"refusing unsafe output target: {path}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise WorkloadError(f"output target changed during write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_api(row: dict, candidate: dict) -> None:
    units = row["operation_units"]
    ids = [u["unit_id"] for u in units]
    if len(ids) != len(set(ids)) or set(ids) != set(row["literal_facets"]):
        raise WorkloadError(f"{row['manifest_pointer']}: API unit/facet partition")
    if row["unit_count"] != len(units) or row["phases"] != [
        "fixture_setup",
        "operation_exercise",
        "semantic_observation",
        "owned_cleanup",
    ]:
        raise WorkloadError(f"{row['manifest_pointer']}: API units/phases")
    request_map = {x["unit_id"]: x["max_requests"] for x in row["requests_per_unit"]}
    if len(request_map) != len(units) or request_map != {
        u["unit_id"]: u["max_requests"] for u in units
    }:
        raise WorkloadError(f"{row['manifest_pointer']}: API requests_per_unit")
    external = row["acceptance_class"] == "external_optional"
    expected = sum(request_map.values()) + row["overhead_requests"]
    if (
        expected != row["calculated_max_requests"]
        or row["total_request_budget"] != expected
    ):
        raise WorkloadError(f"{row['manifest_pointer']}: API request arithmetic")
    if external:
        if (
            row["activation"] != "external_non_activating"
            or expected
            or row["max_actions"]
        ):
            raise WorkloadError(f"{row['manifest_pointer']}: external API activates")
    elif (
        row["activation"] != "candidate_owned_local"
        or expected <= 0
        or row["max_actions"] != len(units) + 2
    ):
        raise WorkloadError(f"{row['manifest_pointer']}: local API bounds")
    for u in units:
        if (
            u["covers"] != [u["unit_id"]]
            or u["phase"] != "operation_exercise"
            or len(u["required_observations"]) < 2
        ):
            raise WorkloadError(f"{row['manifest_pointer']}: API unit semantics")


def validate_deployment(row: dict, candidate: dict) -> None:
    actions = row["actions"]
    ids = [a["action_id"] for a in actions]
    if len(ids) != len(set(ids)) or [a["sequence"] for a in actions] != list(
        range(1, len(actions) + 1)
    ):
        raise WorkloadError(f"{row['manifest_pointer']}: deployment action order")
    request_map = {
        x["action_id"]: x["max_requests"] for x in row["requests_per_action"]
    }
    if request_map != {a["action_id"]: a["max_requests"] for a in actions}:
        raise WorkloadError(f"{row['manifest_pointer']}: deployment request map")
    expected = sum(request_map.values()) + row["overhead_requests"]
    external = row["acceptance_class"] == "external_optional"
    if (
        row["calculated_max_requests"] != expected
        or len(row["preconditions"]) < 1
        or len(row["readiness_observations"]) < 2
    ):
        raise WorkloadError(f"{row['manifest_pointer']}: deployment graph")
    if external:
        if (
            row["activation"] != "external_non_activating"
            or expected
            or row["max_actions"]
            or any(
                a["mode"] != "static_non_activating" or a["max_attempts"]
                for a in actions
            )
        ):
            raise WorkloadError(
                f"{row['manifest_pointer']}: external deployment activates"
            )
    elif row["activation"] != "planning_only_local" or row["max_actions"] != len(
        actions
    ):
        raise WorkloadError(f"{row['manifest_pointer']}: local deployment bounds")


def validate_candidate_binding(row: dict, candidate: dict) -> None:
    proposed = candidate["proposed_capability"]
    if (
        row["manifest_pointer"] != candidate["manifest_pointer"]
        or row["advertised"] != candidate["advertised"]
        or row["acceptance_class"] != proposed["acceptance_class"]
        or row["source_surfaces"] != proposed["contract"]["implementation_surfaces"]
        or row["workload_type"] != proposed["kind"]
    ):
        raise WorkloadError(f"{row['candidate_id']}: candidate identity/type drift")


def compile_workloads() -> dict:
    docs = {}
    locks = {}
    for key, (rel, digest) in SOURCES.items():
        docs[key], observed = load(ROOT / rel, digest)
        locks[key] = {"path": rel, "raw_sha256": observed}
    candidate_rows = {
        e["proposed_capability"]["id"]: e
        for e in docs["candidates"]["entries"]
        if e["proposed_capability"]["kind"] in {"api", "deployment"}
    }
    if len(candidate_rows) != 60:
        raise WorkloadError("candidate API/deployment denominator drift")
    api = docs["api_inventory"]["entries"]
    dep = docs["deployment_inventory"]["entries"]
    if len(api) != 41 or len(dep) != 19:
        raise WorkloadError("inventory denominator drift")
    rows = api + dep
    if {r["candidate_id"] for r in rows} != set(candidate_rows):
        raise WorkloadError("candidate workload ID partition drift")
    for row in rows:
        c = candidate_rows[row["candidate_id"]]
        validate_candidate_binding(row, c)
        for surface in row["source_surfaces"]:
            regular_surface(surface)
        (validate_api if row["workload_type"] == "api" else validate_deployment)(row, c)
        text = json.dumps(row, sort_keys=True).lower()
        if (
            any(marker in text for marker in FORBIDDEN)
            or '"runtime_evidence"' in text
            or '"evidence"' in text
        ):
            raise WorkloadError(
                f"{row['manifest_pointer']}: evidence/promotion/sample marker"
            )
    rows.sort(
        key=lambda r: (
            int(r["manifest_pointer"].split("/")[2]),
            int(r["manifest_pointer"].split("/")[4]),
        )
    )
    out = {
        "schema_version": 1,
        "package_id": "remaining-entry-api-deployment-workloads",
        "policy": {
            "candidate_only": True,
            "can_promote_runtime_state": False,
            "runtime_evidence": [],
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
            "external_activation": "forbidden",
        },
        "locks": locks,
        "summary": {
            "api_candidates": 41,
            "deployment_candidates": 19,
            "workloads": 60,
            "api_units": sum(len(r["operation_units"]) for r in api),
            "deployment_actions": sum(len(r["actions"]) for r in dep),
            "candidate_runtime_evidence_records": 0,
            "external_activations": 0,
            "warehouse_sample_bundle_entries": 0,
        },
        "workloads": rows,
    }
    out["payload_sha256"] = sha(canonical(out))
    return out


def validate(out: dict) -> None:
    schema, _ = load(SCHEMA, SCHEMA_RAW_SHA256)
    errs = sorted(
        Draft202012Validator(schema).iter_errors(out),
        key=lambda e: list(e.absolute_path),
    )
    if errs:
        raise WorkloadError(f"schema: {errs[0].message}")
    payload = dict(out)
    shown = payload.pop("payload_sha256")
    if shown != sha(canonical(payload)):
        raise WorkloadError("payload digest")
    if EXPECTED_PAYLOAD_SHA256 not in ("TO_BE_PINNED", shown):
        raise WorkloadError("payload lock")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    a = p.parse_args(argv)
    try:
        out = compile_workloads()
        validate(out)
        raw = encoded(out)
        if a.write:
            atomic_write(OUTPUT, raw)
            print(f"WROTE: {OUTPUT.relative_to(ROOT)}")
            return 0
        old, d = load(OUTPUT, EXPECTED_OUTPUT_RAW_SHA256)
        if old != out or OUTPUT.read_bytes() != raw:
            raise WorkloadError("checked output drift")
        print(
            f"PASS: 41 API / 19 deployment candidate workloads; api_units={out['summary']['api_units']}, deployment_actions={out['summary']['deployment_actions']}, evidence=0"
        )
        return 0
    except (
        WorkloadError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
