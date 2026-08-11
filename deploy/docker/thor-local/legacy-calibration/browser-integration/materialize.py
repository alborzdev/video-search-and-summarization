#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Materialize the Thor VIOS calibration UI overlay without changing upstream."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
OVERLAY_PATH = HERE / "overlay.json"
ACKNOWLEDGEMENT = "I_ACCEPT_MATERIALIZE_THOR_CALIBRATION_UI_SOURCE"
MAX_SOURCE_FILE_BYTES = 5_000_000
MAX_TREE_FILES = 5_000
MAX_TREE_BYTES = 50_000_000
EXCLUDED_SOURCE_DIRECTORIES = frozenset({"node_modules"})
EXPECTED_SOURCE_ROOT = "services/vios/ui/vios-ui"
EXPECTED_OVERLAY_ID = "thor-local-vios-calibration-browser-v1"
TOP_LEVEL_KEYS = {"schema_version", "overlay_id", "source_root", "policy", "files"}
FILE_KEYS = {"path", "source_sha256", "replacements", "output_sha256"}
REPLACEMENT_REQUIRED_KEYS = {"old", "new"}
REPLACEMENT_ALLOWED_KEYS = {*REPLACEMENT_REQUIRED_KEYS, "occurrence"}
EXPECTED_REPLACEMENT_COUNTS = {
    "src/config.tsx": 2,
    "src/layout/routes/Routes.tsx": 2,
    "src/layout/nav/ListItems.tsx": 2,
    "src/pages/vst/calibration-steps/CalibrationJsonManager.tsx": 2,
    "src/pages/vst/calibration-steps/MmsURLConfiguration.tsx": 1,
}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_POLICY = {
    "same_origin_endpoint": "/vst/calibration-api",
    "private_backend": "127.0.0.1:8013",
    "public_backend_port": False,
    "warehouse_required": False,
    "runtime_evidence": [],
}


class OverlayError(RuntimeError):
    """An overlay identity, confinement, or deterministic replacement failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        unknown = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise OverlayError(
            f"{label} keys are not exact; unknown={unknown}, missing={missing}"
        )


def _validate_file_contract(file_contract: Any) -> None:
    if not isinstance(file_contract, dict):
        raise OverlayError("overlay file entries must be objects")
    _exact_keys(file_contract, FILE_KEYS, "overlay file")
    path = file_contract["path"]
    if path not in EXPECTED_REPLACEMENT_COUNTS:
        raise OverlayError(f"unexpected overlay file path: {path!r}")
    for field in ("source_sha256", "output_sha256"):
        value = file_contract[field]
        if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
            raise OverlayError(f"overlay {field} must be a lowercase SHA-256")
    replacements = file_contract["replacements"]
    if (
        not isinstance(replacements, list)
        or len(replacements) != EXPECTED_REPLACEMENT_COUNTS[path]
    ):
        raise OverlayError(f"overlay replacements are not exact for {path}")
    for replacement in replacements:
        if not isinstance(replacement, dict):
            raise OverlayError("overlay replacements must be objects")
        actual_keys = set(replacement)
        if not REPLACEMENT_REQUIRED_KEYS.issubset(
            actual_keys
        ) or not actual_keys.issubset(REPLACEMENT_ALLOWED_KEYS):
            raise OverlayError("overlay replacement keys are not exact")
        old = replacement["old"]
        new = replacement["new"]
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise OverlayError("overlay replacement strings are invalid")
        occurrence = replacement.get("occurrence", 1)
        if (
            isinstance(occurrence, bool)
            or not isinstance(occurrence, int)
            or occurrence < 1
        ):
            raise OverlayError("overlay replacement occurrence is invalid")


def _validate_overlay(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OverlayError("overlay root must be an object")
    _exact_keys(value, TOP_LEVEL_KEYS, "overlay top-level")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise OverlayError("unsupported overlay schema")
    if value["overlay_id"] != EXPECTED_OVERLAY_ID:
        raise OverlayError("unexpected overlay identity")
    if value["source_root"] != EXPECTED_SOURCE_ROOT:
        raise OverlayError("unexpected overlay source root")
    if value["policy"] != EXPECTED_POLICY:
        raise OverlayError("unexpected overlay policy")
    files = value["files"]
    if not isinstance(files, list) or len(files) != len(EXPECTED_REPLACEMENT_COUNTS):
        raise OverlayError("overlay must bind exactly five files")
    for file_contract in files:
        _validate_file_contract(file_contract)
    paths = [file_contract["path"] for file_contract in files]
    if set(paths) != set(EXPECTED_REPLACEMENT_COUNTS) or len(paths) != len(set(paths)):
        raise OverlayError("overlay must bind each allowed path exactly once")
    return value


def _load_overlay() -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise OverlayError(f"duplicate JSON key in overlay.json: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            OVERLAY_PATH.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                OverlayError(f"non-finite JSON value in overlay.json: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise OverlayError("cannot load overlay.json") from exc
    return _validate_overlay(value)


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise OverlayError(f"unsafe relative path: {value!r}")
    return Path(*pure.parts)


def _read_regular(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OverlayError(f"cannot read {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OverlayError(f"{label} must be a regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_SOURCE_FILE_BYTES:
        raise OverlayError(f"{label} violates the file-size bound")
    data = path.read_bytes()
    if len(data) != metadata.st_size:
        raise OverlayError(f"{label} changed while being read")
    return data


def transform(source: bytes, file_contract: dict[str, Any]) -> bytes:
    _validate_file_contract(file_contract)
    expected = file_contract["source_sha256"]
    if _sha256(source) != expected:
        raise OverlayError(f"source digest mismatch: {file_contract.get('path')}")
    try:
        value = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OverlayError("overlay source must be UTF-8") from exc
    for replacement in file_contract["replacements"]:
        old = replacement["old"]
        new = replacement["new"]
        occurrence = replacement.get("occurrence", 1)
        locations = []
        start = 0
        while True:
            index = value.find(old, start)
            if index < 0:
                break
            locations.append(index)
            start = index + len(old)
        if len(locations) < occurrence:
            raise OverlayError(
                f"replacement occurrence missing: {file_contract.get('path')}"
            )
        index = locations[occurrence - 1]
        value = value[:index] + new + value[index + len(old) :]
    output = value.encode("utf-8")
    expected_output = file_contract["output_sha256"]
    if _sha256(output) != expected_output:
        raise OverlayError(f"output digest mismatch: {file_contract.get('path')}")
    return output


def verify_source_tree(
    source_root: Path, overlay: dict[str, Any]
) -> list[dict[str, str]]:
    source_root = source_root.resolve(strict=True)
    results = []
    for contract in overlay.get("files", []):
        relative = _safe_relative(contract.get("path", ""))
        source = _read_regular(source_root / relative, f"source {relative}")
        output = transform(source, contract)
        results.append(
            {
                "path": relative.as_posix(),
                "source_sha256": _sha256(source),
                "output_sha256": _sha256(output),
            }
        )
    return results


def _reject_symlinks(root: Path) -> None:
    file_count = 0
    total_bytes = 0
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if name not in EXCLUDED_SOURCE_DIRECTORIES
        ]
        files[:] = [name for name in files if name not in EXCLUDED_SOURCE_DIRECTORIES]
        current_path = Path(current)
        for name in [*directories, *files]:
            candidate = current_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise OverlayError(f"source tree contains a symlink: {candidate}")
            if name in files:
                if not stat.S_ISREG(metadata.st_mode):
                    raise OverlayError(
                        f"source tree contains a special file: {candidate}"
                    )
                file_count += 1
                total_bytes += metadata.st_size
                if file_count > MAX_TREE_FILES or total_bytes > MAX_TREE_BYTES:
                    raise OverlayError("source tree violates the aggregate bound")


def materialize(
    source_ui_root: Path, output_root: Path, overlay: dict[str, Any]
) -> list[dict[str, str]]:
    source_ui_root = source_ui_root.resolve(strict=True)
    # Resolve lexical ``..`` and every existing symlinked parent before the
    # confinement check. The final leaf is required not to exist, so
    # ``strict=False`` is intentional.
    output_root = output_root.resolve(strict=False)
    if output_root.exists():
        raise OverlayError("output root must not already exist")
    if source_ui_root == output_root or source_ui_root in output_root.parents:
        raise OverlayError("output root must not be within the source tree")
    _reject_symlinks(source_ui_root)
    shutil.copytree(
        source_ui_root,
        output_root,
        ignore=shutil.ignore_patterns(*EXCLUDED_SOURCE_DIRECTORIES),
    )
    ui_root = output_root / "vios-ui"
    results = []
    for contract in overlay.get("files", []):
        relative = _safe_relative(contract.get("path", ""))
        target = ui_root / relative
        source = _read_regular(target, f"copied source {relative}")
        output = transform(source, contract)
        target.write_bytes(output)
        results.append(
            {
                "path": relative.as_posix(),
                "source_sha256": _sha256(source),
                "output_sha256": _sha256(output),
            }
        )
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("inspect", help="verify source locks without writing")
    apply_parser = subparsers.add_parser(
        "materialize", help="copy and patch a UI source tree"
    )
    apply_parser.add_argument(
        "--source-ui-root", type=Path, default=REPO_ROOT / "services/vios/ui"
    )
    apply_parser.add_argument("--output-root", type=Path, required=True)
    apply_parser.add_argument("--acknowledgement", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    overlay = _load_overlay()
    if args.command in (None, "inspect"):
        results = verify_source_tree(REPO_ROOT / overlay["source_root"], overlay)
        print(
            json.dumps(
                {"mode": "inspect", "writes": [], "files": results}, sort_keys=True
            )
        )
        return 0
    if args.acknowledgement != ACKNOWLEDGEMENT:
        raise OverlayError("exact materialization acknowledgement is required")
    results = materialize(args.source_ui_root, args.output_root, overlay)
    print(
        json.dumps(
            {
                "mode": "materialize",
                "output_root": str(args.output_root),
                "files": results,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OverlayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
