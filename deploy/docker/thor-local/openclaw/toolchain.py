#!/usr/bin/env python3
"""Stage, install, and inspect the pinned Thor NemoClaw/OpenClaw toolchain.

The stage commands are the only phases that use the network. The install phase
forces npm offline and writes only below an explicit user-local prefix. No
command creates a sandbox or starts/stops a container.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent
DEFAULT_LOCK = HERE / "toolchain.lock.json"
MANIFEST_NAME = "cache-manifest.json"
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_KEYS = {
    "schema_version",
    "lock_sha256",
    "npm_registry",
    "npm_cache_verified_offline",
    "sandbox_image_staged",
    "artifacts",
}
ARTIFACT_KEYS = {"path", "sha256", "size"}


class ToolchainError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolchainError(f"cannot read JSON {path}: {exc}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise ToolchainError(f"missing artifact: {path}")
    actual = sha256(path)
    if actual != expected:
        raise ToolchainError(
            f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}"
        )


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode != 0:
        detail = ""
        if capture:
            detail = f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        raise ToolchainError(f"command failed ({result.returncode}): {shlex.join(argv)}{detail}")
    return result


def command_output(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def normalized_machine() -> str:
    machine = platform.machine().lower()
    return {"aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)


def validated_registry(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ToolchainError(f"invalid npm registry URL: {value}") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ToolchainError(
            "npm staging registry must be an HTTPS URL without credentials, query, or fragment"
        )
    return value.rstrip("/") + "/"


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def ensure_platform(lock: dict) -> None:
    wanted_os, wanted_arch = lock["platform"].split("/", 1)
    actual_os = platform.system().lower()
    actual_arch = normalized_machine()
    if (actual_os, actual_arch) != (wanted_os, wanted_arch):
        raise ToolchainError(
            f"this lock is for {wanted_os}/{wanted_arch}, host is {actual_os}/{actual_arch}"
        )


def ensure_runtime(lock: dict) -> None:
    node = command_output(["node", "--version"])
    npm = command_output(["npm", "--version"])
    if node is None or version_tuple(node) < version_tuple(lock["runtime"]["node_minimum"]):
        raise ToolchainError(
            f"Node.js >= {lock['runtime']['node_minimum']} is required; found {node or 'missing'}"
        )
    npm_major = version_tuple(npm or "0.0.0")[0]
    if npm is None or npm_major < lock["runtime"]["npm_major_minimum"]:
        raise ToolchainError(
            f"npm >= {lock['runtime']['npm_major_minimum']} is required; found {npm or 'missing'}"
        )


def download(url: str, destination: Path, expected: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        require_hash(destination, expected)
        print(f"cached  {destination.name}")
        return
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "vss-thor-openclaw-stager/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
    except (OSError, urllib.error.URLError) as exc:
        partial.unlink(missing_ok=True)
        raise ToolchainError(f"download failed for {url}: {exc}") from exc
    try:
        require_hash(partial, expected)
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    print(f"fetched {destination.name}")


def extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as bundle:
        bundle.extractall(destination, filter="data")


def source_root(extract_dir: Path) -> Path:
    candidates = [item for item in extract_dir.iterdir() if item.is_dir()]
    if len(candidates) != 1 or not (candidates[0] / "package.json").is_file():
        raise ToolchainError("NemoClaw archive did not contain one package root")
    return candidates[0]


def npm_environment(
    cache_dir: Path, *, offline: bool, registry: str
) -> dict[str, str]:
    env = os.environ.copy()
    env["npm_config_cache"] = str(cache_dir)
    env["npm_config_audit"] = "false"
    env["npm_config_fund"] = "false"
    env["npm_config_update_notifier"] = "false"
    # Do not inherit a per-user mirror. Cache keys include the registry host,
    # so record an explicit staging registry and reuse that identity during
    # offline verification/install. Package integrity still comes from the
    # committed upstream lockfile.
    env["npm_config_registry"] = registry
    env["npm_config_replace_registry_host"] = "always"
    if offline:
        env["npm_config_offline"] = "true"
        env["npm_config_prefer_offline"] = "true"
    return env


def npm_offline_install(
    package: Path,
    package_lock: Path,
    npm_cache: Path,
    prefix: Path,
    registry: str,
) -> None:
    """Install the built CLI below prefix using only lockfile tarball URLs.

    Installing a standalone tgz makes npm query registry packuments even when
    every dependency tarball is already cached. Extracting the tgz, restoring
    the audited upstream package-lock, and running npm ci avoids that mutable
    registry-resolution step and is stricter as well as genuinely offline.
    """
    target = prefix / "lib" / "node_modules" / "nemoclaw"
    if target.exists():
        raise ToolchainError(
            f"refusing to replace existing install at {target}; select a new prefix"
        )
    with tempfile.TemporaryDirectory(prefix="vss-nemoclaw-package-") as tmp:
        unpacked = Path(tmp)
        extract_tar(package, unpacked)
        source = unpacked / "package"
        if not (source / "package.json").is_file():
            raise ToolchainError("packed NemoClaw artifact has no package/package.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=True)
    shutil.copy2(package_lock, target / "package-lock.json")
    run(
        ["npm", "ci", "--offline", "--ignore-scripts", "--omit=dev"],
        cwd=target,
        env=npm_environment(npm_cache, offline=True, registry=registry),
        capture=True,
    )
    bin_dir = prefix / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("nemoclaw", "nemohermes"):
        link = bin_dir / name
        link.symlink_to(Path("../lib/node_modules/nemoclaw/bin") / f"{name}.js")


def package_name_from_output(output: str) -> str:
    # npm 10 can emit a JSON audit/progress object immediately before the
    # requested `npm pack --json` array. Decode each top-level JSON value and
    # select the package result instead of assuming stdout has only one value.
    decoder = json.JSONDecoder()
    offset = 0
    filename = None
    try:
        while offset < len(output):
            while offset < len(output) and output[offset].isspace():
                offset += 1
            if offset >= len(output):
                break
            value, offset = decoder.raw_decode(output, offset)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                candidate = value[0].get("filename")
                if candidate:
                    filename = candidate
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise ToolchainError("could not parse npm pack JSON output") from exc
    if filename is None:
        raise ToolchainError("npm pack JSON output did not contain a filename")
    if not re.fullmatch(r"[A-Za-z0-9._+-]+\.tgz", filename):
        raise ToolchainError(f"unsafe npm package filename: {filename}")
    return filename


def manifest_entries(cache: Path, paths: list[Path]) -> list[dict]:
    entries = []
    for path in sorted(paths):
        entries.append(
            {
                "path": str(path.relative_to(cache)),
                "sha256": sha256(path),
                "size": path.stat().st_size,
            }
        )
    return entries


def _read_tar_member(bundle: tarfile.TarFile, member: tarfile.TarInfo, limit: int) -> bytes:
    if not member.isfile() or member.size > limit:
        raise ToolchainError(f"invalid or oversized Docker archive member: {member.name}")
    handle = bundle.extractfile(member)
    if handle is None:
        raise ToolchainError(f"cannot read Docker archive member: {member.name}")
    data = handle.read(limit + 1)
    if len(data) > limit:
        raise ToolchainError(f"oversized Docker archive member: {member.name}")
    return data


def _oci_blob_path(digest: object) -> str:
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ToolchainError("OCI archive contains an invalid digest")
    return f"blobs/sha256/{digest.removeprefix('sha256:')}"


def _read_tar_json(
    bundle: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    name: str,
) -> dict:
    member = members.get(name)
    if member is None:
        raise ToolchainError(f"Docker archive is missing {name}")
    try:
        value = json.loads(_read_tar_member(bundle, member, 2 * 1024 * 1024))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolchainError(f"Docker archive member is invalid JSON: {name}") from exc
    if not isinstance(value, dict):
        raise ToolchainError(f"Docker archive JSON member must be an object: {name}")
    return value


def _require_oci_blob(
    bundle: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    descriptor: dict,
) -> str:
    if not isinstance(descriptor, dict):
        raise ToolchainError("OCI archive contains an invalid descriptor")
    name = _oci_blob_path(descriptor.get("digest"))
    member = members.get(name)
    size = descriptor.get("size")
    if (
        member is None
        or not member.isfile()
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or member.size != size
    ):
        raise ToolchainError(f"OCI archive descriptor size mismatch: {name}")
    handle = bundle.extractfile(member)
    if handle is None:
        raise ToolchainError(f"cannot read Docker archive blob: {name}")
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
        digest.update(chunk)
    if digest.hexdigest() != name.rsplit("/", 1)[1]:
        raise ToolchainError(f"OCI archive blob digest mismatch: {name}")
    return name


def _verify_oci_sandbox_archive(
    lock: dict,
    bundle: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    entry: dict,
) -> None:
    layout = _read_tar_json(bundle, members, "oci-layout")
    if layout != {"imageLayoutVersion": "1.0.0"}:
        raise ToolchainError("Docker archive has an unsupported OCI layout")

    image_digest = lock["openclaw"]["sandbox_image"].rsplit("@", 1)[-1]
    index = _read_tar_json(bundle, members, "index.json")
    roots = index.get("manifests")
    if (
        index.get("schemaVersion") != 2
        or index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
        or not isinstance(roots, list)
        or len(roots) != 1
        or not isinstance(roots[0], dict)
        or roots[0].get("digest") != image_digest
    ):
        raise ToolchainError("Docker OCI archive root does not match the committed image")

    referenced = {_require_oci_blob(bundle, members, roots[0])}
    image_index = _read_tar_json(bundle, members, next(iter(referenced)))
    descriptors = image_index.get("manifests")
    if (
        image_index.get("schemaVersion") != 2
        or image_index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
        or not isinstance(descriptors, list)
        or not descriptors
    ):
        raise ToolchainError("committed Docker image is not a valid OCI index")

    target_manifest: dict | None = None
    target_count = 0
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            raise ToolchainError("Docker OCI index contains an invalid descriptor")
        descriptor_name = _oci_blob_path(descriptor.get("digest"))
        platform_value = descriptor.get("platform")
        is_target = (
            isinstance(platform_value, dict)
            and platform_value.get("os") == "linux"
            and platform_value.get("architecture") == "arm64"
        )
        if is_target:
            target_count += 1
            if descriptor.get("digest") != lock["openclaw"]["arm64_manifest_digest"]:
                raise ToolchainError("Docker OCI archive ARM64 manifest identity changed")
        if descriptor_name not in members:
            if is_target:
                raise ToolchainError("Docker OCI archive is missing the ARM64 manifest")
            continue

        referenced.add(_require_oci_blob(bundle, members, descriptor))
        manifest = _read_tar_json(bundle, members, descriptor_name)
        config_descriptor = manifest.get("config")
        layer_descriptors = manifest.get("layers")
        if (
            manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
            or not isinstance(config_descriptor, dict)
            or not isinstance(layer_descriptors, list)
            or not layer_descriptors
        ):
            raise ToolchainError("Docker OCI archive contains an invalid image manifest")
        referenced.add(_require_oci_blob(bundle, members, config_descriptor))
        for layer_descriptor in layer_descriptors:
            referenced.add(_require_oci_blob(bundle, members, layer_descriptor))
        if is_target:
            target_manifest = manifest

    if target_count != 1 or target_manifest is None:
        raise ToolchainError("Docker OCI archive must contain one Linux ARM64 manifest")

    config_descriptor = target_manifest["config"]
    if config_descriptor.get("digest") != lock["openclaw"]["arm64_config_digest"]:
        raise ToolchainError("Docker OCI archive config does not match committed ARM64 image")
    config_name = _oci_blob_path(config_descriptor["digest"])
    config = _read_tar_json(bundle, members, config_name)
    layer_descriptors = target_manifest["layers"]
    diff_ids = (
        config.get("rootfs", {}).get("diff_ids")
        if isinstance(config.get("rootfs"), dict)
        else None
    )
    if (
        config.get("architecture") != "arm64"
        or config.get("os") != "linux"
        or not isinstance(diff_ids, list)
        or len(diff_ids) != len(layer_descriptors)
        or any(
            not isinstance(item, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item)
            for item in diff_ids
        )
    ):
        raise ToolchainError("Docker OCI archive has an invalid ARM64 image config")

    expected_layers = [_oci_blob_path(item.get("digest")) for item in layer_descriptors]
    if entry.get("Config") != config_name or entry.get("Layers") != expected_layers:
        raise ToolchainError("Docker save manifest does not select the committed ARM64 image")

    discovered = {
        name
        for name, member in members.items()
        if name.startswith("blobs/sha256/") and member.isfile()
    }
    if discovered != referenced:
        raise ToolchainError("Docker OCI archive contains unreferenced or missing blobs")


def verify_sandbox_archive(lock: dict, archive: Path) -> None:
    """Verify a docker-save archive before it is ever passed to docker load.

    A docker-save tar does not retain the OCI platform-manifest digest. Its
    config filename/content does retain the image config digest. This verifier
    also hashes every saved layer against the config's rootfs diff IDs before
    Docker sees the archive. Those checks bind it to the committed ARM64 image
    identity instead of trusting a self-authored cache hash alone.
    """

    try:
        with tarfile.open(archive, "r:*") as bundle:
            members: dict[str, tarfile.TarInfo] = {}
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in member.name
                    or (member.isfile() and str(path) != member.name)
                    or member.name in members
                ):
                    raise ToolchainError("unsafe or duplicate Docker archive member")
                if not (member.isfile() or member.isdir()):
                    raise ToolchainError("Docker archive must contain only regular files and directories")
                members[member.name] = member
            manifest_member = members.get("manifest.json")
            if manifest_member is None:
                raise ToolchainError("Docker archive has no manifest.json")
            try:
                manifest = json.loads(_read_tar_member(bundle, manifest_member, 1024 * 1024))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ToolchainError("Docker archive manifest is invalid JSON") from exc
            if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
                raise ToolchainError("Docker archive must contain exactly one image")
            entry = manifest[0]
            config_name = entry.get("Config")
            layers = entry.get("Layers")
            if entry.get("RepoTags") not in (None, []):
                raise ToolchainError("Docker archive must not assign mutable repository tags")
            if isinstance(config_name, str) and re.fullmatch(
                r"blobs/sha256/[0-9a-f]{64}", config_name
            ):
                _verify_oci_sandbox_archive(lock, bundle, members, entry)
                return
            if not isinstance(config_name, str) or not re.fullmatch(r"[0-9a-f]{64}\.json", config_name):
                raise ToolchainError("Docker archive has an invalid config identity")
            expected_config = lock["openclaw"]["arm64_config_digest"]
            if config_name[:-5] != expected_config.removeprefix("sha256:"):
                raise ToolchainError("Docker archive config does not match the committed ARM64 image")
            config_member = members.get(config_name)
            if config_member is None:
                raise ToolchainError("Docker archive is missing its image config")
            config_bytes = _read_tar_member(bundle, config_member, 2 * 1024 * 1024)
            if hashlib.sha256(config_bytes).hexdigest() != config_name[:-5]:
                raise ToolchainError("Docker archive config digest mismatch")
            try:
                config = json.loads(config_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ToolchainError("Docker archive config is invalid JSON") from exc
            if config.get("architecture") != "arm64" or config.get("os") != "linux":
                raise ToolchainError("Docker archive is not a Linux ARM64 image")
            if not isinstance(layers, list) or not layers or len(set(layers)) != len(layers):
                raise ToolchainError("Docker archive has an invalid layer inventory")
            if any(not isinstance(name, str) or name not in members or not members[name].isfile() for name in layers):
                raise ToolchainError("Docker archive is missing a declared image layer")
            diff_ids = config.get("rootfs", {}).get("diff_ids") if isinstance(config.get("rootfs"), dict) else None
            if not isinstance(diff_ids, list) or len(diff_ids) != len(layers):
                raise ToolchainError("Docker archive layer/config inventory does not agree")
            for layer_name, expected_diff_id in zip(layers, diff_ids, strict=True):
                if not isinstance(expected_diff_id, str) or not re.fullmatch(
                    r"sha256:[0-9a-f]{64}", expected_diff_id
                ):
                    raise ToolchainError("Docker archive config has an invalid layer digest")
                layer_handle = bundle.extractfile(members[layer_name])
                if layer_handle is None:
                    raise ToolchainError(f"cannot read Docker archive layer: {layer_name}")
                digest = hashlib.sha256()
                for chunk in iter(lambda: layer_handle.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
                if digest.hexdigest() != expected_diff_id.removeprefix("sha256:"):
                    raise ToolchainError(
                        f"Docker archive layer does not match its config diff ID: {layer_name}"
                    )
    except (OSError, tarfile.TarError) as exc:
        raise ToolchainError(f"cannot inspect Docker archive {archive}: {exc}") from exc


def require_local_image_identity(lock: dict) -> None:
    image = lock["openclaw"]["sandbox_image"]
    result = run(["docker", "image", "inspect", image], capture=True)
    try:
        inspected = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise ToolchainError("docker returned invalid sandbox image metadata") from exc
    if inspected.get("Architecture") != "arm64" or inspected.get("Os") != "linux":
        raise ToolchainError("staged sandbox image is not Linux ARM64")
    image_digest = image.rsplit("@", 1)[-1]
    descriptor = inspected.get("Descriptor")
    if not isinstance(descriptor, dict) or descriptor.get("digest") != image_digest:
        raise ToolchainError("staged sandbox image descriptor does not match the committed identity")
    if inspected.get("Id") not in {image_digest, lock["openclaw"]["arm64_config_digest"]}:
        raise ToolchainError("staged sandbox image identity is unexpected")
    if image not in (inspected.get("RepoDigests") or []):
        raise ToolchainError("staged sandbox image does not retain the committed repository digest")


def expected_cache_entries(lock: dict, lock_path: Path, *, image_staged: bool) -> dict[str, str | None]:
    expected: dict[str, str | None] = {
        "toolchain.lock.json": sha256(lock_path),
        f"downloads/{lock['nemoclaw']['source']['filename']}": lock["nemoclaw"]["source"]["sha256"],
        f"artifacts/{lock['nemoclaw']['package_filename']}": lock["nemoclaw"]["package_sha256"],
        "artifacts/nemoclaw-package-lock.json": lock["nemoclaw"]["root_package_lock_sha256"],
    }
    for item in lock["openshell"]["artifacts"]:
        expected[f"downloads/{item['filename']}"] = item["sha256"]
    if image_staged:
        # docker-save tar serialization is cache-integrity checked by the
        # manifest; its embedded config is separately checked against the
        # committed ARM64 config digest before docker load.
        expected[f"artifacts/{lock['openclaw']['archive_filename']}"] = None
    return expected


def _validate_manifest_item(cache: Path, item: object) -> tuple[str, str, int, Path]:
    if not isinstance(item, dict) or set(item) != ARTIFACT_KEYS:
        raise ToolchainError("cache manifest has an invalid artifact entry schema")
    relative = item.get("path")
    expected_hash = item.get("sha256")
    size = item.get("size")
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ToolchainError("cache manifest has an invalid artifact path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative:
        raise ToolchainError(f"manifest path escapes cache: {relative}")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ToolchainError(f"cache manifest has an invalid hash for {relative}")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ToolchainError(f"cache manifest has an invalid size for {relative}")
    path = cache / relative
    resolved = path.resolve()
    try:
        resolved.relative_to(cache.resolve())
    except ValueError as exc:
        raise ToolchainError(f"manifest path escapes cache: {relative}") from exc
    if path.is_symlink():
        raise ToolchainError(f"cache artifact must not be a symlink: {relative}")
    return relative, expected_hash, size, path


def cmd_plan(lock: dict, _args: argparse.Namespace) -> int:
    data = {
        "platform": lock["platform"],
        "nemoclaw": {key: lock["nemoclaw"][key] for key in ("tag", "commit")},
        "openshell": lock["openshell"]["version"],
        "openclaw": {
            "version": lock["openclaw"]["version"],
            "sandbox_image": lock["openclaw"]["sandbox_image"],
            "arm64_manifest_digest": lock["openclaw"]["arm64_manifest_digest"],
        },
        "provider": lock["provider"],
    }
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def cmd_stage(lock: dict, args: argparse.Namespace) -> int:
    ensure_platform(lock)
    ensure_runtime(lock)
    args.npm_registry = validated_registry(args.npm_registry)
    cache = args.cache.resolve()
    downloads = cache / "downloads"
    artifacts = cache / "artifacts"
    npm_cache = cache / "npm-cache"
    artifacts.mkdir(parents=True, exist_ok=True)

    source = lock["nemoclaw"]["source"]
    source_path = downloads / source["filename"]
    download(source["url"], source_path, source["sha256"])
    tracked = [source_path]

    base_url = lock["openshell"]["release_base_url"].rstrip("/")
    for item in lock["openshell"]["artifacts"]:
        path = downloads / item["filename"]
        download(f"{base_url}/{item['filename']}", path, item["sha256"])
        tracked.append(path)

    with tempfile.TemporaryDirectory(prefix="vss-openclaw-stage-") as tmp:
        unpacked = Path(tmp) / "source"
        extract_tar(source_path, unpacked)
        root = source_root(unpacked)
        require_hash(root / "package-lock.json", lock["nemoclaw"]["root_package_lock_sha256"])
        require_hash(
            root / "nemoclaw" / "package-lock.json",
            lock["nemoclaw"]["plugin_package_lock_sha256"],
        )
        (root / ".version").write_text(lock["nemoclaw"]["tag"].removeprefix("v") + "\n")
        online_env = npm_environment(
            npm_cache, offline=False, registry=args.npm_registry
        )
        run(["npm", "ci", "--ignore-scripts"], cwd=root, env=online_env)
        run(["npm", "run", "build:cli"], cwd=root, env=online_env)
        run(["npm", "ci", "--ignore-scripts"], cwd=root / "nemoclaw", env=online_env)
        run(["npm", "run", "build"], cwd=root / "nemoclaw", env=online_env)
        packed = run(
            [
                "npm",
                "pack",
                "--ignore-scripts",
                "--json",
                "--pack-destination",
                str(artifacts),
            ],
            cwd=root,
            env=online_env,
            capture=True,
        )
        package = artifacts / package_name_from_output(packed.stdout)
        if package.name != lock["nemoclaw"]["package_filename"]:
            raise ToolchainError(
                f"built NemoClaw package name {package.name!r} does not match the committed lock"
            )
        require_hash(package, lock["nemoclaw"]["package_sha256"])
        runtime_lock = artifacts / "nemoclaw-package-lock.json"
        shutil.copy2(root / "package-lock.json", runtime_lock)
        tracked.extend((package, runtime_lock))

        smoke_prefix = Path(tmp) / "offline-smoke"
        npm_offline_install(
            package,
            runtime_lock,
            npm_cache,
            smoke_prefix,
            args.npm_registry,
        )
        output = command_output([str(smoke_prefix / "bin" / "nemoclaw"), "--version"])
        if output != lock["nemoclaw"]["version_output"]:
            raise ToolchainError(
                f"offline NemoClaw smoke test returned {output!r}; "
                f"expected {lock['nemoclaw']['version_output']!r}"
            )

    image_staged = False
    if not args.skip_sandbox_image:
        image_ref = lock["openclaw"]["sandbox_image"]
        run(["docker", "pull", "--platform", lock["platform"], image_ref])
        require_local_image_identity(lock)
        image_archive = artifacts / lock["openclaw"]["archive_filename"]
        run(["docker", "save", "--output", str(image_archive), image_ref])
        verify_sandbox_archive(lock, image_archive)
        tracked.append(image_archive)
        image_staged = True

    cached_lock = cache / "toolchain.lock.json"
    shutil.copy2(args.lock, cached_lock)
    tracked.append(cached_lock)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "lock_sha256": sha256(args.lock),
        "npm_registry": args.npm_registry,
        "npm_cache_verified_offline": True,
        "sandbox_image_staged": image_staged,
        "artifacts": manifest_entries(cache, tracked),
    }
    (cache / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"staged cache: {cache}")
    if not image_staged:
        print("PARTIAL: sandbox image archive was skipped; cache is not air-gap complete")
    return 0


def cmd_stage_sandbox_image(lock: dict, args: argparse.Namespace) -> int:
    """Promote an exact verified partial cache without repeating npm staging."""

    ensure_platform(lock)
    cache = args.cache.resolve()
    manifest, _ = verify_manifest(args.lock, cache, require_image=False)
    if manifest["sandbox_image_staged"]:
        verify_manifest(args.lock, cache, require_image=True)
        print(f"PASS: sandbox image is already staged in complete cache at {cache}")
        return 0

    image_ref = lock["openclaw"]["sandbox_image"]
    run(["docker", "pull", "--platform", lock["platform"], image_ref])
    require_local_image_identity(lock)

    artifacts = cache / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    archive = artifacts / lock["openclaw"]["archive_filename"]
    if archive.exists() or archive.is_symlink():
        raise ToolchainError(
            "partial cache contains an unlisted sandbox archive; refusing to replace it"
        )

    archive_temp: Path | None = None
    manifest_temp: Path | None = None
    manifest_published = False
    try:
        with tempfile.NamedTemporaryFile(
            dir=artifacts,
            prefix=f".{archive.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            archive_temp = Path(handle.name)
        archive_temp.unlink()
        run(["docker", "save", "--output", str(archive_temp), image_ref])
        verify_sandbox_archive(lock, archive_temp)
        archive_temp.replace(archive)
        archive_temp = None

        tracked = [cache / item["path"] for item in manifest["artifacts"]]
        tracked.append(archive)
        updated = {
            **manifest,
            "sandbox_image_staged": True,
            "artifacts": manifest_entries(cache, tracked),
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache,
            prefix=f".{MANIFEST_NAME}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            manifest_temp = Path(handle.name)
            json.dump(updated, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        manifest_temp.replace(cache / MANIFEST_NAME)
        manifest_temp = None
        manifest_published = True
        verify_manifest(args.lock, cache, require_image=True)
    except Exception:
        if archive_temp is not None:
            archive_temp.unlink(missing_ok=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)
        if not manifest_published:
            archive.unlink(missing_ok=True)
        raise

    print(f"PASS: promoted partial cache to complete image-bearing cache at {cache}")
    return 0


def verify_manifest(lock_path: Path, cache: Path, *, require_image: bool) -> tuple[dict, Path]:
    lock = load_json(lock_path)
    manifest = load_json(cache / MANIFEST_NAME)
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise ToolchainError("cache manifest schema is incomplete or has unknown fields")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ToolchainError("cache manifest schema version is unsupported")
    if manifest.get("lock_sha256") != sha256(lock_path):
        raise ToolchainError("cache manifest was produced from a different toolchain lock")
    image_staged = manifest.get("sandbox_image_staged")
    if not isinstance(image_staged, bool):
        raise ToolchainError("cache manifest has an invalid sandbox-image state")
    if require_image and not image_staged:
        raise ToolchainError("sandbox image archive is absent; cache is not air-gap complete")
    if manifest.get("npm_cache_verified_offline") is not True:
        raise ToolchainError("npm cache has not passed the forced-offline smoke test")
    registry = manifest.get("npm_registry")
    if not isinstance(registry, str) or validated_registry(registry) != registry:
        raise ToolchainError("cache manifest has no valid HTTPS npm registry identity")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ToolchainError("cache manifest artifacts must be a list")
    entries: dict[str, tuple[str, int, Path]] = {}
    for item in artifacts:
        relative, expected_hash, size, path = _validate_manifest_item(cache, item)
        if relative in entries:
            raise ToolchainError(f"duplicate cache manifest path: {relative}")
        entries[relative] = (expected_hash, size, path)

    expected = expected_cache_entries(lock, lock_path, image_staged=image_staged)
    if set(entries) != set(expected):
        missing = sorted(set(expected) - set(entries))
        extra = sorted(set(entries) - set(expected))
        raise ToolchainError(
            f"cache artifact inventory mismatch (missing={missing}, extra={extra})"
        )
    discovered = {"toolchain.lock.json"}
    for directory in (cache / "downloads", cache / "artifacts"):
        if directory.exists():
            discovered.update(
                str(path.relative_to(cache))
                for path in directory.rglob("*")
                if path.is_file() or path.is_symlink()
            )
    if discovered != set(expected):
        missing = sorted(set(expected) - discovered)
        extra = sorted(discovered - set(expected))
        raise ToolchainError(
            f"cache filesystem inventory mismatch (missing={missing}, extra={extra})"
        )

    for relative, committed_hash in expected.items():
        manifest_hash, size, path = entries[relative]
        if committed_hash is not None and manifest_hash != committed_hash:
            raise ToolchainError(f"manifest hash for {relative} does not match the committed lock")
        require_hash(path, manifest_hash)
        if path.stat().st_size != size:
            raise ToolchainError(f"size mismatch for {path}")
    if image_staged:
        verify_sandbox_archive(lock, cache / "artifacts" / lock["openclaw"]["archive_filename"])
    package = cache / "artifacts" / lock["nemoclaw"]["package_filename"]
    return manifest, package


def cmd_verify_cache(lock: dict, args: argparse.Namespace) -> int:
    ensure_platform(lock)
    ensure_runtime(lock)
    cache = args.cache.resolve()
    manifest, package = verify_manifest(
        args.lock, cache, require_image=not args.allow_missing_image
    )
    with tempfile.TemporaryDirectory(prefix="vss-openclaw-offline-verify-") as tmp:
        prefix = Path(tmp) / "prefix"
        npm_offline_install(
            package,
            cache / "artifacts" / "nemoclaw-package-lock.json",
            cache / "npm-cache",
            prefix,
            manifest["npm_registry"],
        )
        output = command_output([str(prefix / "bin" / "nemoclaw"), "--version"])
        if output != lock["nemoclaw"]["version_output"]:
            raise ToolchainError(f"offline CLI verification returned {output!r}")
    state = "complete" if manifest["sandbox_image_staged"] else "partial-no-image"
    print(f"PASS: verified {state} cache at {cache}")
    return 0


def install_openshell(lock: dict, cache: Path, prefix: Path) -> None:
    bin_dir = prefix / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vss-openshell-install-") as tmp:
        unpacked = Path(tmp)
        for item in lock["openshell"]["artifacts"]:
            archive = cache / "downloads" / item["filename"]
            require_hash(archive, item["sha256"])
            extract_tar(archive, unpacked)
        for name in ("openshell", "openshell-gateway", "openshell-sandbox"):
            candidates = list(unpacked.rglob(name))
            if len(candidates) != 1 or not candidates[0].is_file():
                raise ToolchainError(f"expected exactly one {name} binary in OpenShell archives")
            destination = bin_dir / name
            shutil.copy2(candidates[0], destination)
            destination.chmod(0o755)


def require_openshell_features(binary: Path) -> None:
    try:
        content = binary.read_bytes()
    except OSError as exc:
        raise ToolchainError(f"cannot inspect OpenShell binary {binary}: {exc}") from exc
    for marker in (
        b"request-body-credential-rewrite",
        b"websocket-credential-rewrite",
    ):
        if marker not in content:
            raise ToolchainError(
                f"OpenShell binary is missing required feature marker {marker.decode()}"
            )


def require_fresh_prefix(prefix: Path) -> None:
    targets = [
        prefix / "lib" / "node_modules" / "nemoclaw",
        *(prefix / "bin" / name for name in ("nemoclaw", "nemohermes", "openshell", "openshell-gateway", "openshell-sandbox")),
    ]
    existing = [str(path) for path in targets if path.exists() or path.is_symlink()]
    if existing:
        raise ToolchainError(
            "refusing to overwrite an existing toolchain target: " + ", ".join(existing)
        )


def cmd_install(lock: dict, args: argparse.Namespace) -> int:
    ensure_platform(lock)
    ensure_runtime(lock)
    cache = args.cache.resolve()
    prefix = args.prefix.resolve()
    manifest, package = verify_manifest(args.lock, cache, require_image=args.load_sandbox_image)
    require_fresh_prefix(prefix)
    npm_offline_install(
        package,
        cache / "artifacts" / "nemoclaw-package-lock.json",
        cache / "npm-cache",
        prefix,
        manifest["npm_registry"],
    )
    install_openshell(lock, cache, prefix)
    nemoclaw_output = command_output([str(prefix / "bin" / "nemoclaw"), "--version"])
    openshell_output = command_output([str(prefix / "bin" / "openshell"), "--version"])
    if nemoclaw_output != lock["nemoclaw"]["version_output"]:
        raise ToolchainError(f"installed NemoClaw returned {nemoclaw_output!r}")
    if not openshell_output or lock["openshell"]["version_output_pattern"] not in openshell_output:
        raise ToolchainError(f"installed OpenShell returned {openshell_output!r}")
    require_openshell_features(prefix / "bin" / "openshell")
    if args.load_sandbox_image:
        if not manifest["sandbox_image_staged"]:
            raise ToolchainError("sandbox image was requested but is not staged")
        run(
            [
                "docker",
                "load",
                "--input",
                str(cache / "artifacts" / lock["openclaw"]["archive_filename"]),
            ]
        )
    print(f"PASS: installed pinned user-local toolchain at {prefix}")
    print(f"PATH={prefix / 'bin'}:$PATH")
    if not args.load_sandbox_image:
        print("NOTE: sandbox image was not loaded")
    return 0


def model_ids(url: str) -> list[str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ToolchainError(f"model discovery failed at {url}: {exc}") from exc
    return [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]


def image_present(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def cmd_verify_host(lock: dict, args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    try:
        ensure_platform(lock)
        checks.append(("platform", True, lock["platform"]))
    except ToolchainError as exc:
        checks.append(("platform", False, str(exc)))
    node = command_output(["node", "--version"])
    checks.append(
        (
            "node",
            node is not None and version_tuple(node) >= version_tuple(lock["runtime"]["node_minimum"]),
            node or "missing",
        )
    )
    prefix_bin = args.prefix.resolve() / "bin"
    nemoclaw = command_output([str(prefix_bin / "nemoclaw"), "--version"])
    checks.append(("nemoclaw", nemoclaw == lock["nemoclaw"]["version_output"], nemoclaw or "missing"))
    openshell = command_output([str(prefix_bin / "openshell"), "--version"])
    openshell_ok = bool(
        openshell and lock["openshell"]["version_output_pattern"] in openshell
    )
    if openshell_ok:
        try:
            require_openshell_features(prefix_bin / "openshell")
        except ToolchainError:
            openshell_ok = False
    checks.append(
        (
            "openshell",
            openshell_ok,
            openshell or "missing",
        )
    )
    image = lock["openclaw"]["sandbox_image"]
    checks.append(("sandbox-image", image_present(image), image))
    try:
        ids = model_ids(lock["provider"]["host_probe_url"])
        checks.append(
            (
                "local-provider",
                lock["provider"]["model"] in ids,
                ", ".join(ids) if ids else "no model ids",
            )
        )
    except ToolchainError as exc:
        checks.append(("local-provider", False, str(exc)))
    failed = 0
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'BLOCKED'} {name}: {detail}")
        failed += not passed
    if failed:
        print(
            "BLOCKED runtime acceptance: no sandbox/chat/tool/MCP/hook action was performed; "
            "install/load and explicit lifecycle authorization are still required."
        )
        return 2
    print(
        "READY FOR RUNTIME ACCEPTANCE: toolchain, image, and local provider are present; "
        "sandbox/chat/tool/MCP/hook qualification remains separate."
    )
    return 0


def cmd_provider_env(lock: dict, args: argparse.Namespace) -> int:
    values = {
        "NEMOCLAW_PROVIDER": "custom",
        "NEMOCLAW_SANDBOX_NAME": args.sandbox_name,
        "NEMOCLAW_MODEL": lock["provider"]["model"],
        "NEMOCLAW_ENDPOINT_URL": lock["provider"]["sandbox_base_url"],
        "COMPATIBLE_API_KEY": lock["provider"]["api_key"],
        "OPENSHELL_PROVIDER_NAME": "vss-thor-local",
    }
    print(f'export PATH={shlex.quote(str(args.prefix.resolve() / "bin"))}:"$PATH"')
    for key, value in values.items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", parents=[common])
    stage = sub.add_parser("stage", parents=[common])
    stage.add_argument("--cache", type=Path, required=True)
    stage.add_argument("--skip-sandbox-image", action="store_true")
    stage.add_argument(
        "--npm-registry",
        default="https://registry.npmjs.org/",
        help="explicit HTTPS staging registry; recorded for offline cache identity",
    )
    stage_image = sub.add_parser("stage-sandbox-image", parents=[common])
    stage_image.add_argument("--cache", type=Path, required=True)
    verify_cache = sub.add_parser("verify-cache", parents=[common])
    verify_cache.add_argument("--cache", type=Path, required=True)
    verify_cache.add_argument("--allow-missing-image", action="store_true")
    install = sub.add_parser("install", parents=[common])
    install.add_argument("--cache", type=Path, required=True)
    install.add_argument("--prefix", type=Path, required=True)
    install.add_argument("--load-sandbox-image", action="store_true")
    verify_host = sub.add_parser("verify-host", parents=[common])
    verify_host.add_argument("--prefix", type=Path, required=True)
    provider = sub.add_parser("provider-env", parents=[common])
    provider.add_argument("--prefix", type=Path, required=True)
    provider.add_argument("--sandbox-name", default="vss-thor")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.lock = args.lock.resolve()
    lock = load_json(args.lock)
    handlers = {
        "plan": cmd_plan,
        "stage": cmd_stage,
        "stage-sandbox-image": cmd_stage_sandbox_image,
        "verify-cache": cmd_verify_cache,
        "install": cmd_install,
        "verify-host": cmd_verify_host,
        "provider-env": cmd_provider_env,
    }
    try:
        return handlers[args.command](lock, args)
    except ToolchainError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
