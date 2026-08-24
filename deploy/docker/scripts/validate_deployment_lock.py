#!/usr/bin/env python3
"""Static validation for deploy/docker/image-compatibility.lock.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

IMAGE_LINE = re.compile(r"^\s*image:\s*(?P<reference>[^#\n]+?)\s*$")
PIN_STATUSES = {"digest-pinned", "local-build-mutable", "unresolved-tag", "unresolved-variable", "untagged"}


def image_references(compose_file: Path) -> set[str]:
    """Return literal scalar `image:` declarations without parsing Compose."""
    references: set[str] = set()
    for line in compose_file.read_text(encoding="utf-8").splitlines():
        match = IMAGE_LINE.match(line)
        if not match:
            continue
        reference = match.group("reference").strip()
        if len(reference) >= 2 and reference[0] == reference[-1] and reference[0] in "\"'":
            reference = reference[1:-1]
        references.add(reference)
    return references


def resolve_path(value: str, repository_root: Path) -> Path:
    for token, replacement in {
        "${VSS_REPO_ROOT}": str(repository_root),
        "${VSS_APPS_DIR}": str(repository_root / "deploy/docker"),
    }.items():
        value = value.replace(token, replacement)
    path = Path(value)
    return path if path.is_absolute() else repository_root / path


def explicit_tag_or_digest(reference: str) -> bool:
    """Variable-only Compose values need a runtime lock, so are unresolved."""
    if "@sha256:" in reference:
        return True
    if "${" in reference:
        return ":" in reference.split("${", 1)[0]
    return ":" in reference.rsplit("/", 1)[-1]


def validate(manifest_path: Path, repository_root: Path, strict: bool = False) -> tuple[int, list[str]]:
    """Validate manifest structure, Compose coverage, and local build inputs."""
    messages: list[str] = []
    errors = warnings = 0

    def error(message: str) -> None:
        nonlocal errors
        errors += 1
        messages.append(f"ERROR: {message}")

    def warn(message: str) -> None:
        nonlocal warnings
        warnings += 1
        messages.append(f"WARN: {message}")

    if not manifest_path.is_file():
        return 1, [f"ERROR: manifest does not exist: {manifest_path}"]
    try:
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 1, [f"ERROR: invalid JSON in {manifest_path}: {exc}"]
    if manifest.get("schema_version") != 1:
        error("schema_version must be 1")
    scope = manifest.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("compose_files"), list):
        error("scope.compose_files must be a list")
        scope = {"compose_files": []}
    images = manifest.get("images")
    if not isinstance(images, list) or not images:
        error("images must be a non-empty list")
        images = []

    declared_by_file: dict[str, set[str]] = {}
    image_ids: set[str] = set()
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            error(f"images[{index}] must be an object")
            continue
        required = ("id", "source_file", "source_reference", "pin_status")
        missing = [key for key in required if not isinstance(image.get(key), str) or not image[key]]
        if missing:
            error(f"images[{index}] missing required string field(s): {', '.join(missing)}")
            continue
        if image["id"] in image_ids:
            error(f"duplicate image id: {image['id']}")
        image_ids.add(image["id"])
        if image["pin_status"] not in PIN_STATUSES:
            error(f"image {image['id']} has unsupported pin_status {image['pin_status']!r}")
        declared_by_file.setdefault(image["source_file"], set()).add(image["source_reference"])
        source_path = repository_root / image["source_file"]
        if not source_path.is_file():
            error(f"image {image['id']} source file is missing: {image['source_file']}")
        elif image["source_reference"] not in image_references(source_path):
            error(f"image {image['id']} reference is absent from {image['source_file']}: {image['source_reference']}")
        status = image["pin_status"]
        if status in {"unresolved-tag", "unresolved-variable", "untagged"}:
            warn(f"image {image['id']} remains {status}: {image['source_reference']}")
        elif status == "local-build-mutable":
            messages.append(f"INFO: image {image['id']} is an intentionally mutable local-build tag")

    for relative_path in scope["compose_files"]:
        if not isinstance(relative_path, str):
            error("scope.compose_files entries must be strings")
            continue
        compose_file = repository_root / relative_path
        if not compose_file.is_file():
            error(f"supported Compose file is missing: {relative_path}")
            continue
        source_references = image_references(compose_file)
        recorded = declared_by_file.get(relative_path, set())
        for reference in sorted(source_references - recorded):
            error(f"supported Compose image is missing from manifest: {relative_path}: {reference}")
        for reference in sorted(source_references):
            if not explicit_tag_or_digest(reference):
                warn(f"supported Compose image is untagged or unresolved: {relative_path}: {reference}")

    builds = manifest.get("local_builds", [])
    if not isinstance(builds, list):
        error("local_builds must be a list")
        builds = []
    for index, build in enumerate(builds):
        if not isinstance(build, dict) or not all(isinstance(build.get(key), str) and build[key] for key in ("compose_file", "context", "dockerfile")):
            error(f"local_builds[{index}] must contain compose_file, context, and dockerfile strings")
            continue
        compose_file = repository_root / build["compose_file"]
        context = resolve_path(build["context"], repository_root)
        dockerfile = context / build["dockerfile"]
        if not compose_file.is_file():
            error(f"local build Compose file is missing: {build['compose_file']}")
        if not context.is_dir():
            error(f"local build context is missing: {build['context']}")
        elif not dockerfile.is_file():
            error(f"local build Dockerfile is missing: {build['context']}/{build['dockerfile']}")

    messages.append(f"SUMMARY: {errors} error(s), {warnings} warning(s); Docker and network were not invoked.")
    return (1 if errors or (strict and warnings) else 0), messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the static Thor/full image compatibility manifest.")
    parser.add_argument("--manifest", type=Path, help="Manifest path (defaults to deploy/docker/image-compatibility.lock.json).")
    parser.add_argument("--repo-root", type=Path, help="Repository root (defaults to this script's ancestor).")
    parser.add_argument("--strict", action="store_true", help="Treat unresolved or untagged image warnings as failures.")
    args = parser.parse_args(argv)
    repository_root = (args.repo_root or Path(__file__).resolve().parents[3]).resolve()
    manifest_path = (args.manifest or repository_root / "deploy/docker/image-compatibility.lock.json").resolve()
    status, messages = validate(manifest_path, repository_root, args.strict)
    print("\n".join(messages))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
