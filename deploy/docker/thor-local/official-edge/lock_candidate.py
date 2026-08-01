#!/usr/bin/env python3
"""Emit an inert plan or a read-only official-edge artifact-lock candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

import official_edge as verifier  # noqa: E402


ACKNOWLEDGEMENT = "I_ACCEPT_READ_ONLY_OFFICIAL_EDGE_ARTIFACT_HASHING"
HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1


class CandidateError(RuntimeError):
    """A candidate input or read-only policy violation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CandidateError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _tree(path: Path, allowed_root: Path) -> dict[str, Any]:
    try:
        entries = verifier._actual_tree_entries(path, allowed_root)
    except verifier.ContractError as exc:
        raise CandidateError(str(exc)) from exc
    return {"entry_count": len(entries), "entries": entries}


def build_plan() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "plan",
        "candidate_state": "inert_plan",
        "filesystem_reads_performed": False,
        "filesystem_mutation_performed": False,
        "network_performed": False,
        "credential_reads_performed": False,
        "docker_performed": False,
        "identities": {
            "edge4b": {
                "repository": verifier.EDGE_REPOSITORY,
                "revision": verifier.EDGE_REVISION,
            },
            "cosmos3_nano_bf16": {"artifact_id": verifier.COSMOS_ARTIFACT},
        },
        "required_acknowledgement": ACKNOWLEDGEMENT,
    }


def build_candidate(edge_snapshot: Path, cosmos_cache: Path) -> dict[str, Any]:
    edge = edge_snapshot.expanduser().absolute()
    cosmos = cosmos_cache.expanduser().absolute()
    if edge.name != verifier.EDGE_REVISION:
        raise CandidateError(
            f"Edge4B snapshot revision is {edge.name!r}; expected {verifier.EDGE_REVISION!r}"
        )
    try:
        edge_repository = verifier._edge_repository(edge)
        edge_entries = verifier._actual_tree_entries(edge, edge_repository)
        verifier._verify_edge_snapshot_layout(edge, edge_entries)
        edge_blob_tree = _tree(edge_repository / "blobs", edge_repository / "blobs")
        cosmos_tree = _tree(cosmos, cosmos)
    except verifier.ContractError as exc:
        raise CandidateError(str(exc)) from exc

    proposed_lock = {
        "schema_version": 1,
        "lock_state": "candidate_only_unqualified",
        "artifacts": {
            "edge4b": {
                "kind": "huggingface_snapshot",
                "identity": {
                    "repository": verifier.EDGE_REPOSITORY,
                    "revision": verifier.EDGE_REVISION,
                },
                "state": "local_bytes_only_unqualified",
                "provenance": {
                    "state": "local_bytes_only_not_independently_verified",
                    "promotion_requires": "reviewed_upstream_identity_and_hash_evidence",
                },
                "tree": {
                    "entry_count": len(edge_entries),
                    "entries": edge_entries,
                },
                "blob_tree": edge_blob_tree,
            },
            "cosmos3_nano_bf16": {
                "kind": "ngc_model_cache",
                "identity": {"artifact_id": verifier.COSMOS_ARTIFACT},
                "state": "local_bytes_only_unqualified",
                "provenance": {
                    "state": "local_bytes_only_not_independently_verified",
                    "promotion_requires": "reviewed_upstream_identity_and_hash_evidence",
                },
                "tree": cosmos_tree,
            },
        },
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "mode": "read_only_candidate",
        "candidate_state": "candidate_only_not_promoted",
        "filesystem_reads_performed": True,
        "filesystem_mutation_performed": False,
        "network_performed": False,
        "credential_reads_performed": False,
        "docker_performed": False,
        "source_evidence": {
            "contract_sha256": _sha256(verifier.DEFAULT_CONTRACT),
            "verifier_sha256": _sha256(Path(verifier.__file__).resolve()),
            "generator_sha256": _sha256(Path(__file__).resolve()),
        },
        "paths": {
            "edge_snapshot": str(edge),
            "edge_blobs": str((edge_repository / "blobs").resolve(strict=True)),
            "cosmos_cache": str(cosmos),
        },
        "proposed_artifact_lock": proposed_lock,
        "proposed_artifact_lock_canonical_sha256": _canonical_sha256(proposed_lock),
        "promotion_performed": False,
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="print an inert plan without inspecting paths")
    generate = subparsers.add_parser(
        "generate", help="hash two explicit local artifact trees and print a candidate"
    )
    generate.add_argument("--acknowledgement", required=True)
    generate.add_argument("--edge4b-snapshot", type=Path, required=True)
    generate.add_argument("--cosmos3-cache", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = build_plan()
        else:
            if args.acknowledgement != ACKNOWLEDGEMENT:
                raise CandidateError(
                    f"generate requires --acknowledgement {ACKNOWLEDGEMENT}"
                )
            result = build_candidate(args.edge4b_snapshot, args.cosmos3_cache)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except CandidateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
