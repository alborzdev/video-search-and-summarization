#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate the exact prerelease commit/path denominator from local Git metadata."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RULES_PATH = HERE / "classification-rules.json"
DENOMINATOR_PATH = HERE / "denominator.json"
PATH_STATUS_PATH = HERE / "path-status.jsonl.gz"

MERGE_BASE_SHA = "7640d917047cf7b0fd3085eefb8282754b56bc94"
STABLE_MAIN_SHA = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
PRERELEASE_SHA = "a34c6b0406bcadd380e4c4dac6ff7e830deb27e5"
LAST_NIGHTLY_TAG = "nightly-20260801"
LAST_NIGHTLY_SHA = "708dac2ff071c76971d5cc8cab24f3879e6aac63"
EXPECTED_DEVELOP_COMMITS = 499
EXPECTED_MAIN_EXCEPTIONS = 2


class GenerationError(RuntimeError):
    """The source metadata or generated denominator is invalid."""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(git_dir: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env["GIT_NO_LAZY_FETCH"] = "1"
    try:
        return subprocess.run(
            ["git", f"--git-dir={git_dir}", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise GenerationError(f"git {' '.join(args)} failed: {detail}") from exc


def _text(git_dir: Path, *args: str) -> str:
    return _git(git_dir, *args).decode("utf-8").strip()


def _commit_sequence(git_dir: Path, end_sha: str) -> list[str]:
    raw = _text(
        git_dir,
        "rev-list",
        "--reverse",
        "--topo-order",
        f"{MERGE_BASE_SHA}..{end_sha}",
    )
    return raw.splitlines() if raw else []


def _changes(git_dir: Path, sha: str) -> list[dict[str, str]]:
    raw = _git(
        git_dir,
        "diff-tree",
        "--no-commit-id",
        "--first-parent",
        "--root",
        "-r",
        "--no-renames",
        "--name-status",
        "-z",
        sha,
    )
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise GenerationError(f"odd name-status field count for {sha}")
    rows: list[dict[str, str]] = []
    for index in range(0, len(fields), 2):
        status = fields[index].decode("ascii")
        path = fields[index + 1].decode("utf-8", errors="surrogateescape")
        if status not in {"A", "D", "M", "T"}:
            raise GenerationError(f"unexpected no-renames status {status!r} in {sha}")
        rows.append({"path": path, "status": status})
    return rows


def _metadata(git_dir: Path, sha: str) -> tuple[str, list[str], str, str]:
    # Parse the commit object directly. ``git show`` may consult a blob-backed
    # mailmap even when no author field is requested, which would violate this
    # generator's metadata-only/no-lazy-fetch contract.
    raw = _git(git_dir, "cat-file", "commit", sha).decode("utf-8", errors="strict")
    headers, separator, message = raw.partition("\n\n")
    if not separator:
        raise GenerationError(f"commit {sha} has no message separator")
    tree = ""
    parents: list[str] = []
    committed_at = ""
    for line in headers.splitlines():
        if line.startswith("tree "):
            tree = line.removeprefix("tree ")
        elif line.startswith("parent "):
            parents.append(line.removeprefix("parent "))
        elif line.startswith("committer "):
            match = re.search(r" (\d+) ([+-])(\d{2})(\d{2})$", line)
            if not match:
                raise GenerationError(f"cannot parse committer time for {sha}")
            epoch, sign, hours, minutes = match.groups()
            offset_minutes = int(hours) * 60 + int(minutes)
            if sign == "-":
                offset_minutes = -offset_minutes
            committed_at = datetime.fromtimestamp(
                int(epoch), timezone(timedelta(minutes=offset_minutes))
            ).isoformat(timespec="seconds")
    subject = message.splitlines()[0] if message.splitlines() else ""
    if not tree or not committed_at or not subject:
        raise GenerationError(f"incomplete commit metadata for {sha}")
    return tree, parents, committed_at, subject


def _compile_rules(rules: dict[str, Any]) -> list[dict[str, Any]]:
    compiled = []
    for rule in rules["rules"]:
        compiled.append(
            {
                **rule,
                "path_patterns": [
                    re.compile(pattern, re.IGNORECASE)
                    for pattern in rule["path_regexes"]
                ],
                "subject_patterns": [
                    re.compile(pattern, re.IGNORECASE)
                    for pattern in rule["subject_regexes"]
                ],
                "deleted_path_patterns": [
                    re.compile(pattern, re.IGNORECASE)
                    for pattern in rule["deleted_path_regexes"]
                ],
            }
        )
    return compiled


def classify(
    subject: str,
    changes: list[dict[str, str]],
    compiled_rules: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    classifications: list[str] = []
    matched_rules: list[str] = []
    for rule in compiled_rules:
        matches = any(
            pattern.search(change["path"])
            for pattern in rule["path_patterns"]
            for change in changes
        ) or any(pattern.search(subject) for pattern in rule["subject_patterns"])
        matches = matches or any(
            change["status"] == "D" and pattern.search(change["path"])
            for pattern in rule["deleted_path_patterns"]
            for change in changes
        )
        if matches:
            matched_rules.append(rule["rule_id"])
            if rule["classification_id"] not in classifications:
                classifications.append(rule["classification_id"])
    if not classifications:
        raise GenerationError(f"unclassified commit subject: {subject}")
    return classifications, matched_rules


def _build_range(
    git_dir: Path,
    range_id: str,
    commits: list[str],
    compiled_rules: list[dict[str, Any]],
    path_records: list[bytes],
    status_counts: Counter[str],
    classification_counts: Counter[str],
    unique_paths: set[str],
) -> list[dict[str, Any]]:
    result = []
    for ordinal, sha in enumerate(commits, start=1):
        tree, parents, committed_at, subject = _metadata(git_dir, sha)
        changes = _changes(git_dir, sha)
        classifications, matched_rules = classify(subject, changes, compiled_rules)
        commit_hasher = hashlib.sha256()
        for change in changes:
            record = {"commit": sha, "range": range_id, **change}
            line = _canonical_bytes(record) + b"\n"
            commit_hasher.update(line)
            path_records.append(line)
            status_counts[change["status"]] += 1
            unique_paths.add(change["path"])
        classification_counts.update(classifications)
        result.append(
            {
                "ordinal": ordinal,
                "sha": sha,
                "tree": tree,
                "parents": parents,
                "committed_at": committed_at,
                "subject": subject,
                "classifications": classifications,
                "classification_rule_ids": matched_rules,
                "change_count": len(changes),
                "path_status_sha256": commit_hasher.hexdigest(),
            }
        )
    return result


def generate(git_dir: Path) -> dict[str, Any]:
    rules = _load_json(RULES_PATH)
    compiled_rules = _compile_rules(rules)

    for sha in (MERGE_BASE_SHA, STABLE_MAIN_SHA, PRERELEASE_SHA):
        if _text(git_dir, "cat-file", "-t", sha) != "commit":
            raise GenerationError(f"required commit object is unavailable: {sha}")
    actual_merge_base = _text(git_dir, "merge-base", STABLE_MAIN_SHA, PRERELEASE_SHA)
    if actual_merge_base != MERGE_BASE_SHA:
        raise GenerationError(
            f"merge base drifted: expected {MERGE_BASE_SHA}, got {actual_merge_base}"
        )

    develop_shas = _commit_sequence(git_dir, PRERELEASE_SHA)
    main_shas = _commit_sequence(git_dir, STABLE_MAIN_SHA)
    if len(develop_shas) != EXPECTED_DEVELOP_COMMITS:
        raise GenerationError(
            f"expected {EXPECTED_DEVELOP_COMMITS} develop commits, got {len(develop_shas)}"
        )
    if len(main_shas) != EXPECTED_MAIN_EXCEPTIONS:
        raise GenerationError(
            f"expected {EXPECTED_MAIN_EXCEPTIONS} main exceptions, got {len(main_shas)}"
        )

    path_records: list[bytes] = []
    status_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    unique_paths: set[str] = set()
    develop_commits = _build_range(
        git_dir,
        "develop_side",
        develop_shas,
        compiled_rules,
        path_records,
        status_counts,
        classification_counts,
        unique_paths,
    )
    develop_change_count = len(path_records)
    main_exceptions = _build_range(
        git_dir,
        "main_only_exception",
        main_shas,
        compiled_rules,
        path_records,
        status_counts,
        classification_counts,
        unique_paths,
    )

    raw_path_status = b"".join(path_records)
    with PATH_STATUS_PATH.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="", fileobj=raw_output, mode="wb", compresslevel=9, mtime=0
        ) as compressed:
            compressed.write(raw_path_status)
    compressed_path_status = PATH_STATUS_PATH.read_bytes()

    all_classifications = (
        rules["candidate_family_ids"] + rules["watchlist_category_ids"]
    )
    denominator = {
        "schema_version": 1,
        "scope": "static_prerelease_diff_denominator_only",
        "evidence_ceiling": "commit_tree_and_path_status_metadata_only",
        "runtime_parity_claimed": False,
        "official_capability_promotions": 0,
        "upstream_locks": {
            "repository": "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization",
            "merge_base_sha": MERGE_BASE_SHA,
            "stable_main_sha": STABLE_MAIN_SHA,
            "prerelease_branch": "develop",
            "prerelease_sha": PRERELEASE_SHA,
            "nightly_tag": LAST_NIGHTLY_TAG,
            "nightly_sha": LAST_NIGHTLY_SHA,
        },
        "generation_contract": {
            "commit_traversal": "git rev-list --reverse --topo-order <merge-base>..<tip>",
            "path_status_mode": "git diff-tree --no-commit-id --first-parent --root -r --no-renames --name-status -z <commit>",
            "rename_representation": "deterministic_delete_and_add_pairs",
            "blob_materialization_required": False,
            "network_required_by_offline_validator": False,
        },
        "classification_contract": {
            "candidate_family_ids": rules["candidate_family_ids"],
            "watchlist_category_ids": rules["watchlist_category_ids"],
            "rules_canonical_sha256": _sha256(_canonical_bytes(rules)),
            "every_commit_classified": True,
            "classification_is_runtime_evidence": False,
        },
        "counts": {
            "develop_side_commits": len(develop_commits),
            "main_only_exceptions": len(main_exceptions),
            "develop_side_path_status_records": develop_change_count,
            "main_only_path_status_records": len(path_records) - develop_change_count,
            "all_path_status_records": len(path_records),
            "unique_paths": len(unique_paths),
            "status_counts": dict(sorted(status_counts.items())),
            "classification_counts": {
                key: classification_counts.get(key, 0) for key in all_classifications
            },
        },
        "digests": {
            "develop_commit_sequence_sha256": _sha256(
                ("\n".join(develop_shas) + "\n").encode("ascii")
            ),
            "main_exception_sequence_sha256": _sha256(
                ("\n".join(main_shas) + "\n").encode("ascii")
            ),
            "path_status_jsonl_sha256": _sha256(raw_path_status),
            "path_status_gzip_sha256": _sha256(compressed_path_status),
        },
        "path_status_sidecar": {
            "path": "path-status.jsonl.gz",
            "format": "gzip_json_lines",
            "gzip_mtime": 0,
            "compressed_bytes": len(compressed_path_status),
            "uncompressed_bytes": len(raw_path_status),
        },
        "develop_side_commits": develop_commits,
        "main_only_exceptions": main_exceptions,
    }
    DENOMINATOR_PATH.write_text(
        json.dumps(denominator, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return denominator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--git-dir",
        type=Path,
        required=True,
        help="bare or non-bare Git metadata directory containing all locked commits/trees",
    )
    args = parser.parse_args()
    denominator = generate(args.git_dir.resolve())
    print(
        "generated prerelease denominator: "
        f"{denominator['counts']['develop_side_commits']} develop commits, "
        f"{denominator['counts']['all_path_status_records']} path/status records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
