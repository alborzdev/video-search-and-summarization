#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare a geometry-identical stage migration. Never apply or call services.

Only stage and calibrationRevision may differ between the two full exports.
All output goes into a new review directory; runtime files remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

CAMERAS = ("cam_SW", "cam_NE")
PREFIX = "native/mv3dt-demo/"
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same(actual: object, expected: object, label: str) -> None:
    # JSON API model serialization can turn 0 into 0.0. Their numeric value
    # must be exactly equal; this is deliberately not a tolerance check.
    if isinstance(expected, dict):
        require(
            isinstance(actual, dict) and actual.keys() == expected.keys(),
            label + " fields differ",
        )
        for key in expected:
            same(actual[key], expected[key], label + "." + key)
    elif isinstance(expected, list):
        require(
            isinstance(actual, list) and len(actual) == len(expected),
            label + " shape differs",
        )
        for index, value in enumerate(expected):
            same(actual[index], value, f"{label}[{index}]")
    elif type(expected) in (float, int):
        require(
            type(actual) in (float, int) and actual == expected,
            label + " numeric geometry differs",
        )
        canonical(actual)
        canonical(expected)
    else:
        require(
            type(actual) is type(expected) and actual == expected, label + " differs"
        )


def read(path: Path) -> dict:
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024 * 1024,
        "Invalid or oversized input: " + str(path),
    )
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), "Expected a JSON object: " + str(path))
    canonical(value)
    return value


def prepare(
    before: dict,
    candidate: dict,
    site: dict,
    rules: dict,
    mobility: dict,
    registration: dict,
    archives: dict,
    directory: Path,
    image_id: str,
    snapshot: str,
    *,
    expected_rule_count: int = 14,
) -> dict:
    """Build candidate objects and cloned bytes without changing any input."""
    require(type(expected_rule_count) is int and 1 <= expected_rule_count <= 256,
            "Expected rule count must be explicit and bounded")
    before, candidate, site, rules, mobility, registration, archives = map(
        deepcopy, (before, candidate, site, rules, mobility, registration, archives)
    )
    require(IMAGE.fullmatch(image_id), "An immutable local image SHA256 is required")
    require(NAME.fullmatch(snapshot), "Snapshot must be a plain unique directory name")
    require(
        before.get("schemaVersion")
        == candidate.get("schemaVersion")
        == "city.isaac-camera-export.v1"
        and before.get("cameraOrder") == list(CAMERAS),
        "Expected the exact ordered camera export schema",
    )
    old_revision, revision = (
        before.get("calibrationRevision"),
        candidate.get("calibrationRevision"),
    )
    require(
        isinstance(old_revision, str)
        and old_revision
        and isinstance(revision, str)
        and revision
        and old_revision != revision,
        "A different explicit calibration revision is required",
    )
    require(
        isinstance(before.get("stage"), str)
        and isinstance(candidate.get("stage"), str)
        and Path(before["stage"]).is_absolute()
        and Path(candidate["stage"]).is_absolute()
        and before["stage"] != candidate["stage"],
        "A different absolute stage path is required",
    )
    same(
        {
            k: v
            for k, v in candidate.items()
            if k not in {"stage", "calibrationRevision"}
        },
        {k: v for k, v in before.items() if k not in {"stage", "calibrationRevision"}},
        "Whole camera export",
    )
    require(set(registration) == set(CAMERAS), "Unexpected camera registration set")
    order = [registration[name]["id"] for name in CAMERAS]
    require(
        len(set(order)) == 2
        and site.get("id") == "isaac-intersection-a"
        and site.get("mode") == "live"
        and [source["id"] for source in site.get("sources", [])] == order,
        "Full ordered live site required",
    )
    same(site["map"], before["map"], "Site map")
    same(site["groundWorldZM"], before["groundWorldZM"], "Road plane")
    config = deepcopy(mobility.get("config", mobility))
    profile = read(directory / "active.json")
    require(
        profile.get("schemaVersion") == "city.mv3dt-demo.v1"
        and profile.get("enabled") is True
        and profile.get("siteId") == site["id"]
        and profile.get("cameraOrder") == order,
        "Enabled source MV3DT profile identity differs",
    )
    require(
        profile.get("cameraCalibrations") == dict.fromkeys(order, old_revision)
        and IMAGE.fullmatch(profile.get("imageId", "")),
        "Source MV3DT calibration/image identity differs",
    )
    hashes, tracker_path = profile.get("fileHashes"), profile.get("trackerConfig")
    require(
        isinstance(hashes, dict)
        and isinstance(tracker_path, str)
        and tracker_path in hashes
        and tracker_path.startswith(PREFIX),
        "Pinned source tracker profile is required",
    )
    old_prefix = tracker_path.rsplit("/", 1)[0] + "/"
    local_tracker_path = profile.get("localTrackerConfig")
    staged = profile.get("trackingArchitecture") == "nvdcf-local-then-mv3dt-v1"
    if "trackingArchitecture" in profile or local_tracker_path is not None:
        require(staged and isinstance(local_tracker_path, str)
                and local_tracker_path != tracker_path
                and local_tracker_path in hashes
                and local_tracker_path.startswith(old_prefix),
                "Staged migration requires its distinct pinned local tracker")
    require(
        not any(part in (".", "..") for part in Path(old_prefix).parts),
        "Invalid source snapshot path",
    )
    source_directory = directory / old_prefix[len(PREFIX) :]
    require(
        source_directory.resolve().is_relative_to(directory.resolve()),
        "Source snapshot escaped its profile",
    )
    files = {}
    for relative, expected in hashes.items():
        require(
            isinstance(relative, str)
            and relative.startswith(old_prefix)
            and ".." not in Path(relative).parts,
            "Pinned file escaped its profile",
        )
        name = relative[len(old_prefix) :]
        require(name and "/" not in name, "Only flat pinned MV3DT files are supported")
        path = source_directory / name
        require(
            path.is_file()
            and not path.is_symlink()
            and path.resolve().is_relative_to(source_directory.resolve())
            and path.stat().st_size <= 1024 * 1024,
            "Invalid pinned file: " + name,
        )
        data = path.read_bytes()
        require(sha(data) == expected, "Pinned file changed: " + name)
        files[name] = data
    required_files = {
        "package.json",
        "camera-0.yml",
        "camera-1.yml",
        "pub-sub.yml",
        "mqtt.ini",
        tracker_path[len(old_prefix) :],
    }
    if staged:
        required_files.add(local_tracker_path[len(old_prefix) :])
    require(
        set(files) in (required_files, required_files | {"manifest.json"}),
        "Pinned source files must exactly match the tracker architecture and optional manifest",
    )
    package = json.loads(files["package.json"])
    require(
        package.get("siteId") == site["id"]
        and package.get("calibrationRevision") == old_revision
        and [camera["sourceId"] for camera in package.get("cameras", [])] == order,
        "Native package identity differs",
    )
    same(
        package.get("nativeProjectionPlaneWorldZM"),
        before["groundWorldZM"],
        "Native road plane",
    )
    same(
        package.get("navigationWorldZM"),
        before["navigationWorldZM"],
        "Native person plane",
    )
    manifest = read(source_directory / "manifest.json")
    require(
        manifest.get("inputSha256") == sha(files["package.json"])
        and manifest.get("trackerInputResolution") == [640, 384],
        "Native manifest/package pins differ",
    )
    require(
        set(archives) == {"calibrations", "rules", "sources"},
        "All controller archives are required",
    )
    present_sources = set(order) & archives["sources"].keys()
    require(
        not present_sources or present_sources == set(order),
        "Pause or retain both camera sources together",
    )
    for index, (name, source_id) in enumerate(zip(CAMERAS, order)):
        camera, source, native = (
            before["cameras"][name],
            site["sources"][index],
            package["cameras"][index],
        )
        require(
            source.get("calibrationRevision")
            == native.get("calibrationRevision")
            == old_revision,
            "Source calibration revision differs",
        )
        for key, value in camera.items():
            same(source.get(key), value, "Site camera " + name + "." + key)
            same(native.get(key), value, "Native camera " + name + "." + key)
            same(
                archives["calibrations"].get(source_id, {}).get(key),
                value,
                "Archived camera " + name + "." + key,
            )
        require(
            archives["calibrations"][source_id].get("calibrationRevision")
            == old_revision,
            "Archived calibration revision differs",
        )
        if source_id in present_sources:
            for key in (
                "id",
                "name",
                "width",
                "height",
                "vssSensorId",
                "inputUri",
                "kind",
            ):
                same(
                    archives["sources"][source_id].get(key),
                    source.get(key),
                    "Archived source " + key,
                )
        source["calibrationRevision"] = revision
        source.pop(
            "processedPreview", None
        )  # Never carry a stale dynamic frame receipt into a PUT.
        native["calibrationRevision"] = revision
        archives["calibrations"][source_id]["calibrationRevision"] = revision
    identifiers = [rule["id"] for rule in rules.get("rules", [])]
    require(
        len(identifiers) == expected_rule_count
        and len(set(identifiers)) == len(identifiers),
        "Expected the complete distinct operator rule set",
    )
    for source_id in order:
        selected = [
            rule for rule in rules["rules"] if rule.get("sourceId") == source_id
        ]
        saved = archives["rules"].get(source_id, [])
        same(
            [{k: v for k, v in row.items() if k != "revision"} for row in saved],
            [{k: v for k, v in row.items() if k != "revision"} for row in selected],
            "Archived rules",
        )
    for rule in rules["rules"]:
        require(
            rule.get("sourceId") in order
            and rule.get("calibrationRevision") in (None, old_revision),
            "Rule has an unknown source or stale calibration",
        )
        rule["calibrationRevision"] = revision
    for source_id in order:
        archives["rules"][source_id] = [
            deepcopy(row) for row in rules["rules"] if row["sourceId"] == source_id
        ]
    for category, references in (
        ("movements", ("entryRuleId", "exitRuleId")),
        ("crossings", ("waitingRuleId", "crossingRuleId")),
        ("queues", ("zoneRuleId",)),
        ("curbs", ("zoneRuleId",)),
    ):
        for row in config.get(category, []):
            require(
                all(row.get(key) in identifiers for key in references),
                "Mobility references a missing rule",
            )
    new_prefix = PREFIX + snapshot + "/"
    package["calibrationRevision"] = revision
    files["package.json"] = encoded(package)
    # Clone configuration paths only. Camera matrices, tracker tuning, MQTT
    # settings and peer topics remain unchanged; no YAML reserialization.
    tracker_name = tracker_path[len(old_prefix) :]
    old_tracker = files[tracker_name]
    require(
        ("/state/" + old_prefix).encode() in old_tracker,
        "Tracker has no pinned local config references",
    )
    files[tracker_name] = old_tracker.replace(
        ("/state/" + old_prefix).encode(), ("/state/" + new_prefix).encode()
    )
    profile["trackerConfig"] = new_prefix + tracker_name
    if staged:
        local_name = local_tracker_path[len(old_prefix) :]
        files[local_name] = files[local_name].replace(
            ("/state/" + old_prefix).encode(), ("/state/" + new_prefix).encode()
        )
        profile["localTrackerConfig"] = new_prefix + local_name
    profile["cameraCalibrations"] = dict.fromkeys(order, revision)
    previous_image_id = profile["imageId"]
    profile["imageId"] = image_id
    summary = {
        "schemaVersion": "city.isaac-identical-calibration.v1",
        "candidateOnly": True,
        "runtimeChanged": False,
        "geometryExactlyEqual": True,
        "allowedExportChanges": ["stage", "calibrationRevision"],
        "previousStage": before["stage"],
        "newStage": candidate["stage"],
        "previousCalibrationRevision": old_revision,
        "newCalibrationRevision": revision,
        "cameraOrder": order,
        "rulesPreserved": len(identifiers),
        "mobilityPreserved": True,
        "mobilityCounts": {
            key: len(config.get(key, []))
            for key in ("movements", "crossings", "queues", "curbs")
        },
        "previousImageId": previous_image_id,
        "imageId": image_id,
        "snapshotPrefix": new_prefix,
        "trackerTuningAndTopicsPreserved": True,
        "sourceArchiveState": "active" if present_sources else "paused",
        "runtimeQualified": False,
        "transportClockQualified": False,
        "productionQualified": False,
    }
    manifest["parentInputSha256"] = manifest["inputSha256"]
    manifest["inputSha256"] = sha(files["package.json"])
    manifest["calibrationRevision"] = revision
    manifest.update(
        enabled=False,
        runtimeQualified=False,
        transportClockQualified=False,
        diagnosticOnly=True,
    )
    manifest["identicalCalibrationMigration"] = deepcopy(summary)
    files["manifest.json"] = encoded(manifest)
    require(
        len(files) == (8 if staged else 7),
        "Migration configuration count differs from the explicit tracker architecture",
    )
    profile["fileHashes"] = {
        new_prefix + name: sha(data) for name, data in files.items()
    }
    site.pop("expectedRevision", None)
    rules.pop("expectedRevision", None)
    summary["pinnedFileCount"] = len(files)
    return {
        "site": site,
        "rules": rules,
        "mobility": config,
        "export": candidate,
        "profile": profile,
        "archives": archives,
        "files": files,
        "summary": summary,
    }


def write_review(output: Path, result: dict, inputs: dict[str, Path]) -> None:
    require(not output.exists(), "Output must be a new review directory")
    preconditions = {
        name: {"path": str(path.resolve()), "sha256": sha(path.read_bytes())}
        for name, path in inputs.items()
    }
    output.mkdir(parents=True, exist_ok=False)
    for name in ("site", "rules", "mobility", "summary"):
        (output / (name + ".json")).write_bytes(encoded(result[name]))
    (output / "active.json").write_bytes(encoded(result["profile"]))
    (output / "camera-map-export.json").write_bytes(encoded(result["export"]))
    for name, value in result["archives"].items():
        filename = {
            "calibrations": "controller-calibrations.json",
            "rules": "controller-source-rules.json",
            "sources": "controller-sources.json",
        }[name]
        (output / filename).write_bytes(encoded(value))
    clone = output / result["summary"]["snapshotPrefix"]
    clone.mkdir(parents=True)
    for name, data in result["files"].items():
        (clone / name).write_bytes(data)
    (clone / "current-static-export.json").write_bytes(encoded(result["export"]))
    hashes = {
        str(path.relative_to(output)): sha(path.read_bytes())
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    (output / "review-receipt.json").write_bytes(
        encoded(
            {
                "schemaVersion": "city.calibration-review.v1",
                "applied": False,
                "inputPreconditions": preconditions,
                "outputSha256": hashes,
                "note": "No APIs or runtime files changed. Pause sources and stop controller before manual install. Re-read current API revisions immediately before each PUT. Retain mobility unchanged. New runtime/clock/accuracy evidence is still required.",
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "before-export",
        "candidate-export",
        "site",
        "rules",
        "mobility",
        "registration",
        "calibrations-archive",
        "rules-archive",
        "sources-archive",
        "demo-directory",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--expected-rule-count", type=int, default=14,
                        help="Reviewed complete rule count; defaults to the original fourteen-rule profile")
    args = parser.parse_args()
    inputs = {
        key.replace("_", "-"): value
        for key, value in vars(args).items()
        if isinstance(value, Path) and key not in ("output", "demo_directory")
    }
    inputs["active-profile"] = args.demo_directory / "active.json"
    profile = read(inputs["active-profile"])
    for relative in profile.get("fileHashes", {}):
        require(
            isinstance(relative, str)
            and relative.startswith(PREFIX)
            and ".." not in Path(relative).parts,
            "Invalid pinned input path",
        )
        inputs["pinned:" + relative] = args.demo_directory / relative[len(PREFIX) :]
    manifest_directory = (
        args.demo_directory / profile["trackerConfig"].rsplit("/", 1)[0][len(PREFIX) :]
    )
    inputs["source-manifest"] = manifest_directory / "manifest.json"
    initial = {name: sha(path.read_bytes()) for name, path in inputs.items()}
    archives = {
        name: read(getattr(args, key))
        for name, key in (
            ("calibrations", "calibrations_archive"),
            ("rules", "rules_archive"),
            ("sources", "sources_archive"),
        )
    }
    result = prepare(
        *(
            read(getattr(args, key))
            for key in (
                "before_export",
                "candidate_export",
                "site",
                "rules",
                "mobility",
                "registration",
            )
        ),
        archives,
        args.demo_directory,
        args.image_id,
        args.snapshot,
        expected_rule_count=args.expected_rule_count,
    )
    require(
        all(sha(path.read_bytes()) == initial[name] for name, path in inputs.items()),
        "An input changed during preparation",
    )
    require(
        not args.output.resolve().is_relative_to(args.demo_directory.resolve()),
        "Output cannot be inside the source profile",
    )
    write_review(args.output, result, inputs)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
