#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stage or verify the exact VSS 3.2.1 ARM64 multimedia codec bundle.

``source-audit`` and ``verify`` are offline/read-only.  ``stage`` is an
explicit connected preparation step: it resolves the exact VSS 3.2.1 package
set through signed Ubuntu Noble metadata over HTTPS, then writes a
content-addressed local bundle.  Image build and runtime consume that bundle
with networking disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path


SCHEMA_VERSION = 1
PACKAGE_COUNT = 59
SOURCE_INSTALLER_SHA256 = "20f1c024c11405ed88192ed9e26a2841348249b8c4238bccd5cce355f7051238"
PACKAGE_SET_SHA256 = "c34db3c88287c8c049190bafdc0096d91f70bdf14a3b0ffdcc30c01fbc11f44f"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]
SOURCE_INSTALLER = REPO_ROOT / "services/rtvi/rt-embed/src/scripts/install_codecs_nonroot.sh"
DEFAULT_BUNDLE = SCRIPT_PATH.parent / "rtvi-vlm-codecs" / "bundle"
DEFAULT_LOCK = SCRIPT_PATH.parent / "codec-bundle.lock.json"
ALLOWED_SOURCE = ("https", "ports.ubuntu.com", 443)
MANIFEST_KEYS = {
    "schema_version",
    "source",
    "source_installer_sha256",
    "package_set_sha256",
    "architecture",
    "package_count",
    "packages",
}
PACKAGE_KEYS = {
    "architecture",
    "filename",
    "package",
    "sha256",
    "size",
    "url",
    "version",
}


class BundleError(RuntimeError):
    """Raised when codec staging or verification fails closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_set_digest(packages: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(packages)) + "\n").encode()).hexdigest()


def source_packages() -> list[str]:
    if not SOURCE_INSTALLER.is_file():
        raise BundleError(f"VSS 3.2.1 codec source is missing: {SOURCE_INSTALLER}")
    digest = sha256_file(SOURCE_INSTALLER)
    if digest != SOURCE_INSTALLER_SHA256:
        raise BundleError(
            "VSS 3.2.1 codec source digest changed: "
            f"expected {SOURCE_INSTALLER_SHA256}, got {digest}"
        )
    text = SOURCE_INSTALLER.read_text(encoding="utf-8")
    match = re.search(r"DEB_URLS_arm64=\(\n(?P<body>.*?)\n\)", text, re.DOTALL)
    if not match:
        raise BundleError("cannot find DEB_URLS_arm64 in the pinned VSS codec source")
    urls = re.findall(r"'([^']+)'", match.group("body"))
    if len(urls) != PACKAGE_COUNT or len(set(urls)) != PACKAGE_COUNT:
        raise BundleError(f"expected {PACKAGE_COUNT} unique ARM64 packages, found {len(urls)}")
    packages: list[str] = []
    for url in urls:
        parsed = urllib.parse.urlsplit(url)
        name = Path(urllib.parse.unquote(parsed.path)).name
        if not name.endswith("_arm64.deb") or "/ubuntu-ports/pool/" not in parsed.path:
            raise BundleError(f"codec URL is not a pinned Ubuntu Noble ARM64 package: {url}")
        packages.append(name.split("_", 1)[0])
    if len(set(packages)) != PACKAGE_COUNT:
        raise BundleError("VSS 3.2.1 codec source contains duplicate package identities")
    if package_set_digest(packages) != PACKAGE_SET_SHA256:
        raise BundleError("VSS 3.2.1 codec package identity digest changed")
    return sorted(packages)


def deb_fields(path: Path) -> dict[str, str]:
    try:
        output = subprocess.check_output(
            ["dpkg-deb", "--field", str(path), "Package", "Version", "Architecture"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BundleError(f"cannot inspect Debian package {path.name}: {exc}") from exc
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip().lower()] = value.strip()
    if fields.get("architecture") != "arm64":
        raise BundleError(f"package {path.name} architecture is not arm64: {fields.get('architecture')!r}")
    if not fields.get("package") or not fields.get("version"):
        raise BundleError(f"package {path.name} has incomplete control metadata")
    return fields


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme, parsed.hostname, parsed.port or 443) != ALLOWED_SOURCE:
        raise BundleError(f"codec URL leaves the signed HTTPS Ubuntu allowlist: {url}")
    if not Path(urllib.parse.unquote(parsed.path)).name.endswith("_arm64.deb"):
        raise BundleError(f"codec URL is not ARM64: {url}")


def _apt_options(apt_dir: Path, retries: int, timeout: int) -> list[str]:
    sources_list = apt_dir / "sources.list"
    keyring = Path("/usr/share/keyrings/ubuntu-archive-keyring.gpg")
    certificates = Path("/etc/ssl/certs/ca-certificates.crt")
    if not keyring.is_file() or not os.access(keyring, os.R_OK):
        raise BundleError(f"Ubuntu archive keyring is unavailable: {keyring}")
    if not certificates.is_file() or not os.access(certificates, os.R_OK):
        raise BundleError(f"HTTPS CA bundle is unavailable: {certificates}")
    (apt_dir / "lists" / "partial").mkdir(parents=True)
    (apt_dir / "cache").mkdir()
    sources_list.write_text(
        "\n".join(
            [
                f"deb [arch=arm64 signed-by={keyring}] https://ports.ubuntu.com/ubuntu-ports noble main universe",
                f"deb [arch=arm64 signed-by={keyring}] https://ports.ubuntu.com/ubuntu-ports noble-updates main universe",
                f"deb [arch=arm64 signed-by={keyring}] https://ports.ubuntu.com/ubuntu-ports noble-security main universe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return [
        "-o",
        f"Dir::Etc::sourcelist={sources_list}",
        "-o",
        "Dir::Etc::sourceparts=-",
        "-o",
        f"Dir::State::lists={apt_dir / 'lists'}",
        "-o",
        f"Dir::Cache={apt_dir / 'cache'}",
        "-o",
        "APT::Architecture=arm64",
        "-o",
        "APT::Update::Error-Mode=any",
        "-o",
        f"Acquire::Retries={retries}",
        "-o",
        f"Acquire::https::Timeout={timeout}",
    ]


def resolve_and_download(staging: Path, packages: list[str], retries: int, timeout: int) -> list[str]:
    if shutil.which("apt-get") is None:
        raise BundleError("apt-get is required for signed Ubuntu metadata resolution")
    apt_dir = staging / "apt"
    options = _apt_options(apt_dir, retries, timeout)
    try:
        subprocess.run(["apt-get", *options, "update"], check=True)
        uri_output = subprocess.check_output(
            ["apt-get", *options, "--print-uris", "download", *packages],
            text=True,
            stderr=subprocess.STDOUT,
        )
        urls = re.findall(r"^'([^']+)'", uri_output, re.MULTILINE)
        if len(urls) != PACKAGE_COUNT or len(set(urls)) != PACKAGE_COUNT:
            raise BundleError(f"signed metadata resolved {len(urls)} artifacts, expected {PACKAGE_COUNT}")
        for url in urls:
            validate_url(url)
        subprocess.run(["apt-get", *options, "download", *packages], cwd=staging, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BundleError(f"signed Ubuntu codec resolution/download failed: {exc}") from exc
    finally:
        shutil.rmtree(apt_dir, ignore_errors=True)
    return urls


def build_manifest(bundle: Path, urls: list[str], expected_packages: list[str]) -> dict[str, object]:
    url_by_package = {}
    for url in urls:
        validate_url(url)
        package = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name.split("_", 1)[0]
        if package in url_by_package:
            raise BundleError(f"signed metadata returned duplicate package: {package}")
        url_by_package[package] = url
    if sorted(url_by_package) != sorted(expected_packages):
        raise BundleError("signed metadata package identities differ from the VSS 3.2.1 package set")

    entries = []
    package_paths = sorted(bundle.glob("*_arm64.deb"), key=lambda path: path.name)
    if len(package_paths) != PACKAGE_COUNT:
        raise BundleError(f"codec bundle has {len(package_paths)} Debian archives, expected {PACKAGE_COUNT}")
    seen: set[str] = set()
    for package_path in package_paths:
        if package_path.is_symlink():
            raise BundleError(f"unsafe codec package symlink: {package_path.name}")
        fields = deb_fields(package_path)
        package = fields["package"]
        if package not in url_by_package or package in seen:
            raise BundleError(f"unexpected or duplicate downloaded package: {package}")
        seen.add(package)
        entries.append(
            {
                "architecture": fields["architecture"],
                "filename": package_path.name,
                "package": package,
                "sha256": sha256_file(package_path),
                "size": package_path.stat().st_size,
                "url": url_by_package[package],
                "version": fields["version"],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "VSS v3.2.1 services/rtvi/rt-embed/src/scripts/install_codecs_nonroot.sh",
        "source_installer_sha256": SOURCE_INSTALLER_SHA256,
        "package_set_sha256": PACKAGE_SET_SHA256,
        "architecture": "arm64",
        "package_count": len(entries),
        "packages": entries,
    }


def validate_manifest(document: object) -> tuple[list[dict[str, object]], set[str]]:
    """Validate the frozen manifest schema and its exact, safe archive inventory."""
    if not isinstance(document, dict) or set(document) != MANIFEST_KEYS:
        raise BundleError("codec bundle manifest has an incomplete or unknown schema")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise BundleError("codec bundle manifest has an unsupported schema")
    if document.get("source") != "VSS v3.2.1 services/rtvi/rt-embed/src/scripts/install_codecs_nonroot.sh":
        raise BundleError("codec bundle manifest has an unexpected source identity")
    if document.get("source_installer_sha256") != SOURCE_INSTALLER_SHA256:
        raise BundleError("codec bundle manifest is not anchored to the VSS 3.2.1 source digest")
    if document.get("package_set_sha256") != PACKAGE_SET_SHA256:
        raise BundleError("codec bundle manifest has the wrong VSS 3.2.1 package identity digest")
    if document.get("architecture") != "arm64" or document.get("package_count") != PACKAGE_COUNT:
        raise BundleError(f"codec bundle manifest must describe {PACKAGE_COUNT} ARM64 packages")

    packages = document.get("packages")
    if not isinstance(packages, list) or len(packages) != PACKAGE_COUNT:
        raise BundleError(f"codec bundle manifest must contain {PACKAGE_COUNT} packages")
    filenames: set[str] = set()
    identities: list[str] = []
    records: list[dict[str, object]] = []
    for item in packages:
        if not isinstance(item, dict) or set(item) != PACKAGE_KEYS:
            raise BundleError("codec bundle manifest has an invalid package-entry schema")
        filename = item.get("filename")
        package = item.get("package")
        version = item.get("version")
        digest = item.get("sha256")
        size = item.get("size")
        url = item.get("url")
        if (
            not isinstance(filename, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:%~_-]*_arm64\.deb", filename)
            or Path(filename).name != filename
        ):
            raise BundleError(f"codec bundle manifest has an unsafe archive filename: {filename!r}")
        if not isinstance(package, str) or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", package):
            raise BundleError(f"codec bundle manifest has an invalid package identity: {package!r}")
        if not filename.startswith(f"{package}_"):
            raise BundleError(f"codec archive filename does not match package identity: {filename}")
        if item.get("architecture") != "arm64":
            raise BundleError(f"codec bundle manifest package is not ARM64: {filename}")
        if not isinstance(version, str) or not version or any(character.isspace() for character in version):
            raise BundleError(f"codec bundle manifest has an invalid version: {filename}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BundleError(f"codec bundle manifest has an invalid SHA-256: {filename}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise BundleError(f"codec bundle manifest has an invalid size: {filename}")
        if not isinstance(url, str):
            raise BundleError(f"codec bundle manifest has an invalid URL: {filename}")
        validate_url(url)
        if filename in filenames:
            raise BundleError(f"codec bundle manifest has a duplicate archive filename: {filename}")
        filenames.add(filename)
        identities.append(package)
        records.append(item)
    if len(set(identities)) != PACKAGE_COUNT:
        raise BundleError("codec bundle manifest has duplicate package identities")
    if package_set_digest(identities) != PACKAGE_SET_SHA256:
        raise BundleError("codec bundle manifest package identities differ from VSS 3.2.1")
    return records, filenames


def load_canonical_lock(path: Path = DEFAULT_LOCK) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise BundleError(f"canonical codec lock must be a regular non-symlink file: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read canonical codec lock {path}: {exc}") from exc
    validate_manifest(document)
    return document


def stage_bundle(
    destination: Path,
    retries: int,
    timeout: int,
    *,
    lock_path: Path = DEFAULT_LOCK,
) -> dict[str, object]:
    packages = source_packages()
    canonical = load_canonical_lock(lock_path)
    if destination.exists() or destination.is_symlink():
        raise BundleError(f"refusing to overwrite existing bundle: {destination}")
    if not destination.parent.is_dir():
        raise BundleError(f"bundle parent directory does not exist: {destination.parent}")

    staging = Path(tempfile.mkdtemp(prefix=".bundle-stage-", dir=destination.parent))
    try:
        urls = resolve_and_download(staging, packages, retries, timeout)
        document = build_manifest(staging, urls, packages)
        if document != canonical:
            raise BundleError(
                "signed Ubuntu resolution differs from the committed codec lock; "
                "refusing an automatic package/version/hash refresh"
            )
        (staging / "manifest.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, destination)
        return document
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_bundle(
    bundle: Path,
    *,
    frozen: bool = False,
    lock_path: Path = DEFAULT_LOCK,
) -> dict[str, object]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise BundleError(f"codec bundle must be a regular directory, not a link: {bundle}")
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BundleError(f"codec bundle manifest must be a regular non-symlink file: {manifest_path}")
    try:
        expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read codec manifest {manifest_path}: {exc}") from exc
    canonical = load_canonical_lock(lock_path)
    if expected != canonical or sha256_file(manifest_path) != sha256_file(lock_path):
        raise BundleError("codec bundle manifest does not match the committed canonical lock")
    packages, filenames = validate_manifest(expected)
    urls = [str(entry["url"]) for entry in packages]
    manifest_packages = [str(entry["package"]) for entry in packages]
    expected_entries = filenames | {"manifest.json"}
    actual_entries: set[str] = set()
    for path in bundle.iterdir():
        if path.is_symlink() or not path.is_file():
            raise BundleError(f"codec bundle contains a non-regular or linked entry: {path.name}")
        actual_entries.add(path.name)
    if actual_entries != expected_entries:
        raise BundleError(
            f"codec bundle inventory mismatch: missing={sorted(expected_entries - actual_entries)}, "
            f"extra={sorted(actual_entries - expected_entries)}"
        )
    expected_packages = sorted(manifest_packages)
    if not frozen and expected_packages != source_packages():
        raise BundleError("canonical codec lock package identities differ from VSS 3.2.1 source")
    actual = build_manifest(bundle, urls, expected_packages)
    if actual != expected:
        raise BundleError("codec bundle bytes or package metadata do not match manifest.json")
    return actual


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("source-audit", help="verify the exact offline source contract")
    stage = subparsers.add_parser("stage", help="connected, additive package staging")
    stage.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    stage.add_argument("--retries", type=int, default=5)
    stage.add_argument("--timeout", type=int, default=60)
    verify = subparsers.add_parser("verify", help="offline bundle verification")
    verify.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    verify.add_argument(
        "--frozen",
        action="store_true",
        help="verify only against the embedded source digest and manifest (for the networkless image build)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "source-audit":
            packages = source_packages()
            canonical = load_canonical_lock()
            print(
                f"verified VSS 3.2.1 source digest, {len(packages)} ARM64 codec package "
                f"identities, and {canonical['package_count']}-entry canonical lock"
            )
        elif args.command == "stage":
            if args.retries < 1 or args.timeout < 1:
                raise BundleError("retries and timeout must be positive integers")
            document = stage_bundle(args.bundle.resolve(), args.retries, args.timeout)
            print(f"staged {document['package_count']} packages at {args.bundle.resolve()}")
        else:
            document = verify_bundle(args.bundle.resolve(), frozen=args.frozen)
            print(f"verified {document['package_count']} offline ARM64 codec packages")
    except BundleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
