#!/usr/bin/env python3
"""Validate the additive Aug. 2 prerelease delta without Git or network."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "contract.schema.json"
MAX_FILE_BYTES = 96_000_000
EXPECTED_PREDECESSORS = {
    "prerelease-watchlist-20260801": "deploy/docker/thor-local/qualification/prerelease-watchlist",
    "prerelease-denominator-through-a34c6b040": "deploy/docker/thor-local/qualification/prerelease-denominator",
}
EXPECTED_TRANSITION = {
    "repository": "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization",
    "stable_release_tag": "v3.2.1",
    "stable_release_sha": "7640d917047cf7b0fd3085eefb8282754b56bc94",
    "stable_main_sha": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
    "previous_develop_sha": "a34c6b0406bcadd380e4c4dac6ff7e830deb27e5",
    "latest_develop_sha": "8db763b4632864ec2875cef2004447d0f8bf1086",
    "latest_nightly_tag": "nightly-20260802",
    "latest_nightly_sha": "8db763b4632864ec2875cef2004447d0f8bf1086",
    "latest_tree_sha": "223a9c8850eb92ca04208a88598b222283c2ea25",
    "linear_commit_count": 1,
}
EXPECTED_CLASSIFICATIONS = [
    "profile-compose-inversion",
    "sdrc-configurator",
    "bugfix",
]
EXPECTED_RULE_IDS = [
    "family-profile-compose-inversion",
    "family-sdrc-configurator",
    "category-bugfix",
]


class QualificationError(RuntimeError):
    """A latest-upstream static invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label}: root must be an object")
    return value


def resolve_regular(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in pure.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise QualificationError(f"missing repository path: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationError(f"repository path traverses symlink: {relative}")
    if not stat.S_ISREG(current.stat().st_mode):
        raise QualificationError(f"repository path is not a regular file: {relative}")
    if current.stat().st_size > MAX_FILE_BYTES:
        raise QualificationError(f"repository file exceeds size bound: {relative}")
    return current


def load_contract() -> dict[str, Any]:
    contract = strict_json(CONTRACT_PATH.read_bytes(), CONTRACT_PATH.name)
    schema = strict_json(SCHEMA_PATH.read_bytes(), SCHEMA_PATH.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid contract schema: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(contract),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise QualificationError(f"contract schema violation: {errors[0].message}")
    return contract


def canonical_file_bytes(path: Path, payload: bytes) -> bytes:
    if path.suffix != ".json":
        return payload
    return canonical_bytes(strict_json(payload, path.as_posix()))


def package_identity(relative: str) -> dict[str, Any]:
    package = (REPO_ROOT / relative).resolve(strict=True)
    if not package.is_dir() or REPO_ROOT not in package.parents:
        raise QualificationError(f"unsafe predecessor package: {relative}")
    files: list[dict[str, Any]] = []
    raw_identity = hashlib.sha256()
    canonical_identity = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise QualificationError(f"predecessor contains symlink: {path}")
        payload = path.read_bytes()
        if len(payload) > MAX_FILE_BYTES:
            raise QualificationError(f"predecessor file exceeds size bound: {path}")
        relative_path = path.relative_to(package).as_posix()
        canonical = canonical_file_bytes(path, payload)
        prefix = relative_path.encode("utf-8") + b"\0"
        raw_identity.update(prefix + payload + b"\0")
        canonical_identity.update(prefix + canonical + b"\0")
        files.append(
            {
                "path": relative_path,
                "byte_count": len(payload),
                "raw_sha256": sha256(payload),
                "canonical_sha256": sha256(canonical),
            }
        )
    return {
        "file_count": len(files),
        "raw_identity_sha256": raw_identity.hexdigest(),
        "canonical_identity_sha256": canonical_identity.hexdigest(),
        "tree_sha256": sha256(canonical_bytes(files)),
    }


def verify_predecessors(contract: dict[str, Any]) -> None:
    rows = contract["predecessor_packages"]
    observed = {row["id"]: row["path"] for row in rows}
    if observed != EXPECTED_PREDECESSORS or len(rows) != 2:
        raise QualificationError("predecessor identity set drifted")
    for row in rows:
        expected = {
            key: row[key]
            for key in (
                "file_count",
                "raw_identity_sha256",
                "canonical_identity_sha256",
                "tree_sha256",
            )
        }
        if package_identity(row["path"]) != expected:
            raise QualificationError(f"predecessor package drift: {row['id']}")


def verify_transition(contract: dict[str, Any]) -> None:
    if contract["upstream_transition"] != EXPECTED_TRANSITION:
        raise QualificationError("latest upstream transition drifted")
    commit = contract["commit"]
    path_record = commit["path_record"]
    expected_record = {
        "commit": EXPECTED_TRANSITION["latest_develop_sha"],
        "path": "deploy/docker/industry-profiles/warehouse-operations/overrides.env",
        "range": "develop_side",
        "status": "M",
    }
    if path_record != expected_record:
        raise QualificationError("exact one-path delta drifted")
    if sha256(canonical_bytes(path_record) + b"\n") != commit["path_status_sha256"]:
        raise QualificationError("new path-status record digest drifted")
    expected_commit = {
        "ordinal": 500,
        "sha": EXPECTED_TRANSITION["latest_develop_sha"],
        "tree": EXPECTED_TRANSITION["latest_tree_sha"],
        "parent": EXPECTED_TRANSITION["previous_develop_sha"],
        "committed_at": "2026-08-02T01:38:33+05:30",
        "subject": "fix(deploy): Warehouse: start Phoenix so agent tracing has a collector",
        "classifications": EXPECTED_CLASSIFICATIONS,
        "classification_rule_ids": EXPECTED_RULE_IDS,
        "path_record": expected_record,
        "path_status_sha256": "9677dec33fd25efb3e5d1f2848aa949882967140baa1e3b6f9a95251f5f7af80",
        "old_blob_sha1": "e1b77dedc8329e22923a233e20751ee3c72d8b13",
        "new_blob_sha1": "5c96410077183a878db3d10df8006c81b934ba30",
        "unified_zero_context_diff_sha256": "ab4e29eea8c0bb4b5937fc1828f43370bf4941858795e8b9cd0f5a39d7f6f7ed",
        "semantic_change": "append phoenix between vss-ui and elasticsearch in COMPOSE_PROFILES_WH_2D",
    }
    if commit != expected_commit:
        raise QualificationError("latest upstream commit contract drifted")


def verify_projection(contract: dict[str, Any]) -> None:
    predecessor_path = resolve_regular(
        "deploy/docker/thor-local/qualification/prerelease-denominator/denominator.json"
    )
    predecessor = strict_json(predecessor_path.read_bytes(), predecessor_path.as_posix())
    counts = predecessor["counts"]
    if counts["develop_side_commits"] != 499 or predecessor["develop_side_commits"][-1]["sha"] != EXPECTED_TRANSITION["previous_develop_sha"]:
        raise QualificationError("predecessor denominator tip/count drifted")

    expected_counts = dict(counts)
    expected_counts["develop_side_commits"] += 1
    expected_counts["develop_side_path_status_records"] += 1
    expected_counts["all_path_status_records"] += 1
    expected_counts["status_counts"] = dict(counts["status_counts"])
    expected_counts["status_counts"]["M"] += 1
    expected_counts["classification_counts"] = dict(counts["classification_counts"])
    for classification in EXPECTED_CLASSIFICATIONS:
        expected_counts["classification_counts"][classification] += 1

    sequence = [row["sha"] for row in predecessor["develop_side_commits"]]
    sequence.append(EXPECTED_TRANSITION["latest_develop_sha"])
    sequence_digest = sha256(("\n".join(sequence) + "\n").encode("ascii"))

    sidecar = resolve_regular(
        "deploy/docker/thor-local/qualification/prerelease-denominator/path-status.jsonl.gz"
    )
    predecessor_raw = gzip.decompress(sidecar.read_bytes())
    appended_line = canonical_bytes(contract["commit"]["path_record"]) + b"\n"
    successor_raw = predecessor_raw + appended_line
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as output:
        output.write(successor_raw)
    successor_gzip = buffer.getvalue()

    projection = contract["latest_denominator_projection"]
    projected_counts = {
        key: projection[key]
        for key in (
            "develop_side_commits",
            "main_only_exceptions",
            "develop_side_path_status_records",
            "main_only_path_status_records",
            "all_path_status_records",
            "unique_paths",
            "status_counts",
        )
    }
    if projected_counts != {key: expected_counts[key] for key in projected_counts}:
        raise QualificationError("latest denominator arithmetic drifted")
    increments = projection["classification_increments"]
    if increments != {classification: 1 for classification in EXPECTED_CLASSIFICATIONS}:
        raise QualificationError("classification increments drifted")
    expected_projection = {
        "develop_commit_sequence_sha256": sequence_digest,
        "path_status_jsonl_sha256": sha256(successor_raw),
        "path_status_gzip_sha256": sha256(successor_gzip),
        "path_status_uncompressed_bytes": len(successor_raw),
        "path_status_compressed_bytes": len(successor_gzip),
    }
    if any(projection[key] != value for key, value in expected_projection.items()):
        raise QualificationError("latest denominator digest/size projection drifted")


def verify_local_equivalence(contract: dict[str, Any]) -> None:
    equivalence = contract["thor_local_equivalence"]
    expected = {
        "path": "deploy/docker/services/infra/compose.yml",
        "raw_sha256": "a1b38492963006e9cf0b55bb0a57a14de8e898abae5833babb9d20c1931b369c",
        "service": "phoenix",
        "required_profile": "bp_wh_2d",
        "upstream_path_is_absent_locally": True,
        "source_port_required": False,
    }
    if equivalence != expected:
        raise QualificationError("Thor-local equivalence contract drifted")
    path = resolve_regular(equivalence["path"])
    payload = path.read_bytes()
    if sha256(payload) != equivalence["raw_sha256"]:
        raise QualificationError("Thor-local compose source drifted")
    text = payload.decode("utf-8")
    match = re.search(r"(?ms)^  phoenix:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n)", text)
    if match is None or 'profiles: ["bp_wh_2d"' not in match.group("body"):
        raise QualificationError("Phoenix is not selected by the Thor Warehouse 2D profile")
    upstream_local = REPO_ROOT / contract["commit"]["path_record"]["path"]
    if upstream_local.exists():
        raise QualificationError("excluded upstream Warehouse override was unexpectedly ported")


def verify_scope(contract: dict[str, Any]) -> None:
    if contract["scope"] != {
        "stable_ga_affected": False,
        "rest_api_changed": False,
        "mcp_api_changed": False,
        "openapi_or_schema_changed": False,
        "model_or_inference_changed": False,
        "skill_changed": False,
        "curated_prerelease_family_count": 14,
        "warehouse_profile": "excluded_by_operator_scope",
        "warehouse_sample_bundle": "excluded",
        "runtime_evidence": [],
        "official_capability_promotions": 0,
    }:
        raise QualificationError("non-promoting Warehouse exclusion boundary drifted")


def check() -> dict[str, Any]:
    contract = load_contract()
    verify_predecessors(contract)
    verify_transition(contract)
    verify_projection(contract)
    verify_local_equivalence(contract)
    verify_scope(contract)
    return {
        "status": "static_latest_upstream_delta_valid",
        "latest_develop_sha": contract["upstream_transition"]["latest_develop_sha"],
        "latest_nightly_tag": contract["upstream_transition"]["latest_nightly_tag"],
        "develop_side_commits": contract["latest_denominator_projection"]["develop_side_commits"],
        "develop_side_path_status_records": contract["latest_denominator_projection"]["develop_side_path_status_records"],
        "stable_ga_affected": False,
        "source_port_required": False,
        "runtime_evidence": [],
        "official_capability_promotions": 0,
        "warehouse_sample_bundle": "excluded",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        parser.error("--check is required")
    try:
        result = check()
    except (OSError, QualificationError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
