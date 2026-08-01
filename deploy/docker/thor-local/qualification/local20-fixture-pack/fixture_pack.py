#!/usr/bin/env python3
"""Validate or explicitly materialize bounded local20 candidate fixtures.

The default action is an inert plan. Validation is read-only. Media generation
is a separately acknowledgement-gated, local-only operation and is never run
by the package's default tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4].resolve(strict=True)
MANIFEST = LANE / "manifest.json"
MANIFEST_SCHEMA = LANE / "manifest.schema.json"
FIXTURE_SCHEMA = LANE / "fixture.schema.json"
RECEIPT_SCHEMA = LANE / "generation-receipt.schema.json"
ACKNOWLEDGEMENT = (
    "I_ACKNOWLEDGE_GENERATING_BOUNDED_LOCAL20_MEDIA_OUTSIDE_THE_REPOSITORY"
)
MAX_JSON_BYTES = 65_536
MAX_TOOL_BYTES = 100_000_000
MAX_TOTAL_MEDIA_BYTES = 8_000_000
RECEIPT_NAME = "local20-generation-receipt.json"
PINNED_SOURCE_SHA256 = {
    "manifest.json": "f6f994992620fe34da36695be82b9092fc04b64a3f065a2472f614a71f77935b",
    "manifest.schema.json": "90c6c747aa5f921186660d6da9a72e51ac245f35c6f62d3b2e34f951c7904ea2",
    "fixture.schema.json": "5b98998e21ce43838ff19ca8f59761e43fdbe0ae541319829e236eb9d27ec887",
    "generation-receipt.schema.json": "b0b0d09c7ea38d5662f14ec961a4fc683f1a06e81996b4cf47f830393f07766d",
}
EXPECTED_REQUIREMENTS = [
    "tiny-agent-media",
    "hitl-state-transcript",
    "lvs-multi-file",
    "search-documents-and-bboxes",
    "candidate-alerts",
    "tiny-alert-stream",
    "smartcity-ui-incidents",
    "smartcity-synthetic-tracks",
    "systems-vios-playback-remediation",
]
EXPECTED_RECIPE_IDS = [
    "tiny-identity-mp4-v1",
    "tiny-identity-mkv-v1",
    "tiny-bframe-failing-mp4-v1",
    "tiny-bframe-reference-mp4-v1",
]
SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}
TOOL_CANDIDATES = (Path("/usr/local/bin/ffmpeg"), Path("/usr/bin/ffmpeg"))


class FixturePackError(RuntimeError):
    """A strict fixture-pack or generation invariant was violated."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise FixturePackError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixturePackError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise FixturePackError(f"JSON root must be an object in {label}")
    return value


def _read_regular(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if not hasattr(os, "O_NOFOLLOW"):
        raise FixturePackError("O_NOFOLLOW is required")
    try:
        descriptor = os.open(path, flags | os.O_NOFOLLOW)
    except OSError as exc:
        raise FixturePackError(f"cannot open pinned regular file: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise FixturePackError(f"file is not a bounded regular file: {path}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                raise FixturePackError(f"short read from {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_identity != after_identity:
            raise FixturePackError(f"file changed during bounded read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _load(path: Path, maximum: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path, maximum)
    return _strict_json(raw, str(path)), raw


def _load_pinned(path: Path) -> tuple[dict[str, Any], bytes]:
    value, raw = _load(path)
    expected = PINNED_SOURCE_SHA256[path.name]
    if _sha256(raw) != expected:
        raise FixturePackError(f"pinned source SHA-256 mismatch for {path.name}")
    return value, raw


def _validate_schema(
    instance: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.path)
        raise FixturePackError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _validate_bbox(bbox: list[float], label: str) -> None:
    if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise FixturePackError(f"{label} must have x1 < x2 and y1 < y2")


def _semantic_fixture(
    fixture: dict[str, Any], recipes: dict[str, dict[str, Any]]
) -> None:
    fixture_id = fixture["fixture_id"]
    if fixture_id == "local20-search-documents-bboxes-v1":
        documents = {item["document_id"]: item for item in fixture["documents"]}
        frames = {item["frame_id"] for item in fixture["documents"]}
        if len(documents) != len(fixture["documents"]):
            raise FixturePackError("search document IDs must be unique")
        routes = [item["route"] for item in fixture["route_cases"]]
        if routes != ["text", "image", "object", "selected_bbox"]:
            raise FixturePackError(
                "search routes must be the exact ordered four-route set"
            )
        for document in documents.values():
            _validate_bbox(document["bbox_xyxy_normalized"], document["document_id"])
        for case in fixture["route_cases"]:
            if case["expected_document_id"] not in documents:
                raise FixturePackError("search case references an unknown document")
            if "query_fixture" in case and case["query_fixture"] not in frames:
                raise FixturePackError("search case references an unknown frame")
            if case["route"] == "selected_bbox":
                _validate_bbox(case["bbox_xyxy_normalized"], "selected bbox")
    elif fixture_id == "local20-alerts-incidents-tracks-v1":
        for alert in fixture["alerts"]:
            if alert["expected_publish"] != (alert["vlm_verdict"] == "verified"):
                raise FixturePackError(
                    "alert publish decision must match the deterministic verdict"
                )
        events = [item["event"] for item in fixture["tracks"]]
        if events != ["speed", "flow", "collision", "stall", "wrong_way"]:
            raise FixturePackError("tracks must cover the exact ordered event set")
        incident_ids = {item["incident_id"] for item in fixture["incidents"]}
        if set(fixture["dashboard"]["incident_ids"]) != incident_ids:
            raise FixturePackError(
                "dashboard incidents must exactly reference the fixture incidents"
            )
    elif fixture_id == "local20-hitl-state-transcript-v1":
        expected = [
            (1, "generate", "idle", "awaiting_review"),
            (2, "refine", "awaiting_review", "awaiting_review"),
            (3, "cancel", "awaiting_review", "cancelled"),
            (4, "restart", "cancelled", "awaiting_review"),
            (5, "persist", "awaiting_review", "completed"),
        ]
        observed = [
            (
                item["sequence"],
                item["action"],
                item["state_before"],
                item["state_after"],
            )
            for item in fixture["steps"]
        ]
        if observed != expected:
            raise FixturePackError(
                "HITL transcript must preserve all exact state transitions"
            )
        requests = [item["request_id"] for item in fixture["steps"]]
        if fixture["persistence"]["retained_request_ids"] != requests:
            raise FixturePackError(
                "HITL persistence must retain the ordered request identities"
            )
    elif fixture_id == "local20-vios-remediation-v1":
        failing = recipes[fixture["failing_media_recipe_id"]]
        reference = recipes[fixture["reference_media_recipe_id"]]
        if failing["b_frames"] != 2 or reference["b_frames"] != 0:
            raise FixturePackError(
                "VIOS remediation must bind the B-frame failing/reference pair"
            )
        if failing["filename"] == reference["filename"]:
            raise FixturePackError(
                "VIOS source and derived identities must be distinct"
            )
    else:
        raise FixturePackError(f"unknown fixture identity: {fixture_id}")


def validate_pack() -> dict[str, Any]:
    manifest, _ = _load_pinned(MANIFEST)
    manifest_schema, _ = _load_pinned(MANIFEST_SCHEMA)
    fixture_schema, _ = _load_pinned(FIXTURE_SCHEMA)
    _validate_schema(manifest, manifest_schema, "manifest")
    if manifest["requirement_ids"] != EXPECTED_REQUIREMENTS:
        raise FixturePackError(
            "requirement IDs must remain in their exact locked order"
        )
    recipes = {item["recipe_id"]: item for item in manifest["media_recipes"]}
    if list(recipes) != EXPECTED_RECIPE_IDS or len(recipes) != 4:
        raise FixturePackError("media recipe identities or order drifted")
    for recipe in recipes.values():
        if recipe["filename"].endswith(".mp4") != (recipe["container"] == "mp4"):
            raise FixturePackError("media filename/container identity mismatch")
    fixture_ids: list[str] = []
    covered: set[str] = set()
    for recipe in recipes.values():
        covered.update(recipe["covers"])
    for entry in manifest["json_fixtures"]:
        candidate = (LANE / entry["path"]).resolve(strict=False)
        try:
            candidate.relative_to(LANE)
        except ValueError as exc:
            raise FixturePackError("fixture path escaped the lane") from exc
        fixture, raw = _load(candidate, entry["max_bytes"])
        if _sha256(raw) != entry["raw_sha256"]:
            raise FixturePackError(f"raw SHA-256 mismatch for {entry['path']}")
        _validate_schema(fixture, fixture_schema, entry["fixture_id"])
        if fixture["fixture_id"] != entry["fixture_id"]:
            raise FixturePackError("manifest and payload fixture IDs differ")
        fixture_ids.append(entry["fixture_id"])
        covered.update(entry["covers"])
        _semantic_fixture(fixture, recipes)
    if len(fixture_ids) != len(set(fixture_ids)):
        raise FixturePackError("JSON fixture identities must be unique")
    if covered != set(EXPECTED_REQUIREMENTS):
        raise FixturePackError(
            "fixture coverage must exactly span the nine target rows"
        )
    return {
        "status": "valid_candidate_fixture_pack",
        "pack_id": manifest["pack_id"],
        "requirements": len(EXPECTED_REQUIREMENTS),
        "media_recipes": len(recipes),
        "json_fixtures": len(fixture_ids),
        "runtime_evidence": False,
        "capabilities_promoted": False,
    }


def _outside_repo_output(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise FixturePackError("--output-dir must be absolute")
    if (
        not path.name.isascii()
        or not path.name
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in path.name
        )
    ):
        raise FixturePackError(
            "output directory basename must use safe ASCII characters"
        )
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise FixturePackError("output parent must already exist") from exc
    output = parent / path.name
    try:
        output.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise FixturePackError("generation output must be outside the repository")
    try:
        output.lstat()
    except FileNotFoundError:
        return output
    raise FixturePackError("refusing to reuse or overwrite the output directory")


def _resolve_ffmpeg() -> Path:
    for candidate in TOOL_CANDIDATES:
        try:
            resolved = candidate.resolve(strict=True)
            observed = resolved.stat()
        except OSError:
            continue
        if resolved not in {Path("/usr/local/bin/ffmpeg"), Path("/usr/bin/ffmpeg")}:
            continue
        if (
            stat.S_ISREG(observed.st_mode)
            and observed.st_uid == 0
            and observed.st_mode & 0o022 == 0
            and os.access(resolved, os.X_OK)
        ):
            return resolved
    raise FixturePackError("no trusted allowlisted local ffmpeg was found")


def _command(recipe: dict[str, Any], ffmpeg: Path, directory_fd: int) -> list[str]:
    output = f"/proc/self/fd/{directory_fd}/{recipe['filename']}"
    return [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-n",
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=160x120:r=5:d=2",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "10",
        "-bf",
        str(recipe["b_frames"]),
        output,
    ]


def _run_ffmpeg(argv: Sequence[str], directory_fd: int) -> None:
    try:
        result = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=SAFE_ENV,
            shell=False,
            check=False,
            timeout=30,
            pass_fds=(directory_fd,),
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise FixturePackError("bounded ffmpeg generation timed out") from exc
    if result.returncode != 0:
        raise FixturePackError(
            f"bounded ffmpeg generation failed with {result.returncode}"
        )


def _hash_at(directory_fd: int, name: str, maximum: int) -> tuple[str, int]:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory_fd
    )
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_size <= 0
            or observed.st_size > maximum
        ):
            raise FixturePackError(f"generated artifact is outside its bound: {name}")
        digest = hashlib.sha256()
        remaining = observed.st_size
        while remaining:
            block = os.read(descriptor, min(remaining, 65_536))
            if not block:
                raise FixturePackError(f"short read from generated artifact: {name}")
            digest.update(block)
            remaining -= len(block)
        return digest.hexdigest(), observed.st_size
    finally:
        os.close(descriptor)


def _write_exclusive_at(directory_fd: int, name: str, data: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def generate_media(raw_output: str, acknowledgement: str) -> dict[str, Any]:
    if acknowledgement != ACKNOWLEDGEMENT:
        raise FixturePackError("exact media-generation acknowledgement is required")
    summary = validate_pack()
    output = _outside_repo_output(raw_output)
    ffmpeg = _resolve_ffmpeg()
    manifest, _ = _load_pinned(MANIFEST)
    output.mkdir(mode=0o700)
    directory_fd = os.open(
        output, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    expected_names = [item["filename"] for item in manifest["media_recipes"]] + [
        RECEIPT_NAME
    ]
    try:
        artifacts: list[dict[str, Any]] = []
        total = 0
        for recipe in manifest["media_recipes"]:
            _run_ffmpeg(_command(recipe, ffmpeg, directory_fd), directory_fd)
            digest, size = _hash_at(
                directory_fd, recipe["filename"], recipe["max_bytes"]
            )
            total += size
            if total > MAX_TOTAL_MEDIA_BYTES:
                raise FixturePackError(
                    "generated media exceeded the total byte ceiling"
                )
            artifacts.append(
                {
                    "recipe_id": recipe["recipe_id"],
                    "filename": recipe["filename"],
                    "raw_sha256": digest,
                    "size_bytes": size,
                    "max_bytes": recipe["max_bytes"],
                }
            )
        receipt = {
            "schema_version": 1,
            "pack_id": summary["pack_id"],
            "purpose": "candidate_inputs_only_non_promoting",
            "output_directory": str(output),
            "tool": {
                "name": "ffmpeg",
                "path": str(ffmpeg),
                "raw_sha256": _sha256(_read_regular(ffmpeg, MAX_TOOL_BYTES)),
            },
            "artifacts": artifacts,
            "safety": {
                "warehouse_data_used": False,
                "network_used": False,
                "docker_used": False,
                "downloads_used": False,
                "service_lifecycle_used": False,
                "acknowledgement": acknowledgement,
            },
        }
        receipt_schema, _ = _load_pinned(RECEIPT_SCHEMA)
        _validate_schema(receipt, receipt_schema, "generation receipt")
        encoded = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(encoded) > MAX_JSON_BYTES:
            raise FixturePackError("generation receipt exceeded its byte ceiling")
        _write_exclusive_at(directory_fd, RECEIPT_NAME, encoded)
        if sorted(os.listdir(directory_fd)) != sorted(expected_names):
            raise FixturePackError(
                "unexpected output appeared in the confined generation directory"
            )
        return receipt
    except BaseException:
        for name in expected_names:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(directory_fd)
        try:
            output.rmdir()
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("validate", help="read-only strict validation")
    generate = subparsers.add_parser(
        "generate-media", help="explicit bounded local generation"
    )
    generate.add_argument("--output-dir", required=True)
    generate.add_argument("--acknowledgement", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command is None:
            result = {
                "mode": "inert_plan",
                "writes": False,
                "subprocesses": False,
                "runtime_evidence": False,
                "acknowledgement_required": ACKNOWLEDGEMENT,
            }
        elif arguments.command == "validate":
            result = validate_pack()
        else:
            result = generate_media(arguments.output_dir, arguments.acknowledgement)
    except FixturePackError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
