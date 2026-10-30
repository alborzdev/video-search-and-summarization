#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a guarded CPU-only Smart City UI artifact; never recreate running services."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
APP = "nv-metropolis-bp-vss-ui"
MEMORY_GIB = 4
MAX_SECONDS = 1200
GENERATED = {"node_modules", ".next", ".turbo", ".git", "coverage", "playwright-report", "test-results", "__pycache__"}
RUNTIME_MODULES = ("next-runtime-env", "chalk", "ansi-styles", "supports-color", "color-convert", "color-name", "has-flag")


def run(arguments, **kwargs):
    return subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def private_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def available_gib() -> float:
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(values["MemAvailable"].split()[0]) / 1024**2


def saved_floor(root: Path) -> float:
    value = json.loads((root / ".spark/settings.json").read_text()).get("reserve_gib")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise RuntimeError("Packaging requires a finite nonnegative saved Spark reserve; it never lowers that reserve")
    return float(value)


def require_guard(root: Path, *, check_service: bool = True) -> float:
    floor = saved_floor(root)
    status = root / ".spark/guard-status.json"
    if not status.is_file() or not 0 <= time.time() - status.stat().st_mtime <= 15:
        raise RuntimeError("Spark memory-guard telemetry is absent or stale")
    if check_service:
        run(["systemctl", "--user", "is-active", "--quiet", "vss-spark-guard.service"], stdout=subprocess.DEVNULL)
    if available_gib() < floor:
        raise RuntimeError(f"Packaging needs the saved {floor:g} GiB reserve available")
    return floor


def registry_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The saved npm registry must be HTTPS without credentials, query or fragment")
    return value


def excluded(name: str) -> bool:
    return name in GENERATED or name in {".npmrc", ".netrc", "__ENV.js", ".DS_Store"} or name.startswith(".env") or name.endswith((".log", ".tsbuildinfo"))


def source_copy(source: Path, destination: Path) -> None:
    def ignore(directory, names):
        ignored = {name for name in names if excluded(name)}
        # Workspace lib/ is generated, whereas lib-src/ and source libraries remain inputs.
        if "lib" in names and (Path(directory) / "package.json").is_file():
            ignored.add("lib")
        for name in set(names) - ignored:
            if (Path(directory) / name).is_symlink():
                raise RuntimeError(f"Review source symlink before packaging: {Path(directory).relative_to(source) / name}")
        return ignored
    shutil.copytree(source, destination, ignore=ignore)


def tree_paths(directory: Path, *, exclude_dependencies: bool = False):
    for current, directories, files in os.walk(directory, followlinks=False):
        current = Path(current)
        if exclude_dependencies:
            directories[:] = [name for name in directories if name != "node_modules"]
        for name in directories[:]:
            if (current / name).is_symlink():
                directories.remove(name)
                yield current / name
        for name in files:
            yield current / name


def tree_digest(directory: Path, *, internal_links: bool = False, exclude_dependencies: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(tree_paths(directory, exclude_dependencies=exclude_dependencies)):
        if path.is_symlink():
            if not internal_links or not path.resolve().is_relative_to(directory.resolve()):
                raise RuntimeError("Prepared artifact contains an external or unexpected symlink")
            digest.update(str(path.relative_to(directory)).encode() + b"\0link\0" + os.readlink(path).encode())
            continue
        if path.is_file():
            digest.update(str(path.relative_to(directory)).encode() + b"\0")
            digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def dependency_roots(directory: Path) -> list[Path]:
    roots = []
    for current, directories, _ in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories if not excluded(name) or name == "node_modules"]
        if "node_modules" in directories:
            roots.append(Path(current) / "node_modules")
            directories.remove("node_modules")
        directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
    return sorted(roots)


def validate_installed_dependencies(directory: Path) -> dict:
    frozen_path = directory / "package-lock.json"
    installed_path = directory / "node_modules/.package-lock.json"
    frozen, installed = json.loads(frozen_path.read_text()), json.loads(installed_path.read_text())
    if frozen.get("lockfileVersion") != 3 or installed.get("lockfileVersion") != 3:
        raise RuntimeError("Offline reuse requires root and installed lockfile version 3")
    expected, actual = frozen.get("packages"), installed.get("packages")
    if not isinstance(expected, dict) or not isinstance(actual, dict) or not actual:
        raise RuntimeError("Offline reuse requires populated package lock entries")
    roots = dependency_roots(directory)
    if directory / "node_modules" not in roots:
        raise RuntimeError("Offline reuse requires the tested root node_modules installation")
    workspaces = [directory / path for path in expected if path and "node_modules" not in Path(path).parts]
    allowed_targets = roots + workspaces
    manifests = hashlib.sha256()
    optional_absent = 0
    for relative, entry in expected.items():
        if not relative:
            continue
        if relative not in actual:
            if entry.get("optional") is True:
                optional_absent += 1
                continue
            raise RuntimeError(f"Required installed lock entry is absent: {relative}")
    for relative, entry in sorted(actual.items()):
        path = Path(relative)
        if not relative or path.is_absolute() or ".." in path.parts or not isinstance(entry, dict):
            raise RuntimeError("Unsafe installed package lock path or entry")
        wanted = expected.get(relative)
        if not isinstance(wanted, dict) or any(entry.get(field) != wanted.get(field) for field in ("version", "resolved", "integrity", "link")):
            raise RuntimeError(f"Installed lock metadata differs from the frozen lock: {relative}")
        package = directory / path
        if entry.get("link"):
            target = directory / str(entry.get("resolved", ""))
            if not package.is_symlink() or package.resolve() != target.resolve():
                raise RuntimeError(f"Workspace dependency link differs from the lock: {relative}")
        manifest = package / "package.json"
        if not manifest.is_file() or not manifest.resolve().is_relative_to(directory.resolve()):
            raise RuntimeError(f"Installed package manifest is absent or external: {relative}")
        metadata = json.loads(manifest.read_text())
        if entry.get("version") is not None and metadata.get("version") != entry["version"]:
            raise RuntimeError(f"Installed package version differs from the lock: {relative}")
        manifests.update(relative.encode() + b"\0" + bytes.fromhex(sha256(manifest)))
    for root in roots:
        if root.is_symlink():
            raise RuntimeError("A dependency root cannot be a symlink")
        for path in tree_paths(root):
            if path.is_symlink():
                target = path.resolve()
                if os.path.isabs(os.readlink(path)) or not path.exists() or not target.is_relative_to(directory.resolve()) or not any(target.is_relative_to(allowed.resolve()) for allowed in allowed_targets):
                    raise RuntimeError(f"External, absolute or broken dependency symlink: {path.relative_to(directory)}")
    return {"installedLockSha256": sha256(installed_path), "installedManifestsSha256": manifests.hexdigest(),
            "installedPackageCount": len(actual), "absentOptionalPackageCount": optional_absent,
            "dependencyRoots": [str(path.relative_to(directory)) for path in roots]}


def dependencies_digest(directory: Path, roots: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(roots):
        for path in sorted(tree_paths(directory / relative)):
            digest.update(str(path.relative_to(directory)).encode() + b"\0")
            digest.update(str(path.lstat().st_mode & 0o777).encode() + b"\0")
            digest.update(b"link\0" + os.readlink(path).encode() if path.is_symlink() else bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def reuse_installed_dependencies(source: Path, workspace: Path) -> dict:
    if sha256(source / "package-lock.json") != sha256(workspace / "package-lock.json"):
        raise RuntimeError("Tested installation and frozen source lockfiles differ")
    receipt = validate_installed_dependencies(source)
    for relative in receipt["dependencyRoots"]:
        shutil.copytree(source / relative, workspace / relative, symlinks=True)
    copied = validate_installed_dependencies(workspace)
    if copied != receipt:
        raise RuntimeError("Copied dependency manifests differ from the tested installation")
    copied["dependencyTreeSha256"] = dependencies_digest(workspace, copied["dependencyRoots"])
    copied["provenance"] = "existing-tested-unpacked-installation; tarball integrity metadata compared, not recomputed"
    return copied


def inspect_image(reference: str) -> dict:
    result = run(["docker", "image", "inspect", reference, "--format", '{{json .Id}} {{json .Architecture}}'], capture_output=True, text=True)
    identifier, architecture = result.stdout.strip().split()
    identifier, architecture = json.loads(identifier), json.loads(architecture)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier) or architecture != "arm64":
        raise RuntimeError("A locally cached immutable ARM64 UI image is required")
    return {"id": identifier, "architecture": architecture}


def package_directory(root: Path, directory: Path) -> Path:
    parent = (root / ".spark/smart-city-ui").resolve()
    resolved = directory.resolve()
    if not resolved.is_relative_to(parent) or resolved == parent or directory.is_symlink():
        raise ValueError("Package directory must be a child of .spark/smart-city-ui")
    return resolved


def prepare(root: Path, *, reuse_dependencies: bool = False) -> Path:
    if platform.machine() != "aarch64":
        raise RuntimeError("This Spark packaging helper requires an ARM64 host")
    require_guard(root)
    if shutil.disk_usage(root).free < 10 * 1024**3:
        raise RuntimeError("Packaging requires at least 10 GiB free disk space")
    settings = json.loads((root / ".spark/settings.json").read_text())
    service = json.loads((root / ".spark/compose.json").read_text())["services"]["vss-ui"]
    reference = service["image"]
    if not reference.startswith("vss-spark-"):
        raise RuntimeError("Refusing to package outside the existing Spark UI candidate")
    image = inspect_image(reference)
    registry = registry_url(settings.get("npm_registry", "https://registry.npmjs.org"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / ".spark/smart-city-ui" / timestamp
    directory.mkdir(parents=True, mode=0o700)
    workspace = directory / "workspace"
    source_copy(root / "services/ui", workspace)
    dash = workspace / "external/vios-dash"
    if dash.exists():
        shutil.rmtree(dash)
    source_copy(root / "services/vios/ui/streaming-lib/src/dash", dash)
    context = directory / "context"
    context.mkdir(mode=0o700)
    shutil.copy2(root / "deploy/docker/smart-city/Dockerfile.ui-artifact", context / "Dockerfile")
    fallback = f"vss-spark-vss-ui:pre-city-{image['id'][7:19]}"
    run(["docker", "image", "tag", image["id"], fallback])
    manifest = {"schemaVersion": 1, "createdAt": timestamp, "sourceSha256": tree_digest(workspace, exclude_dependencies=True),
                "lockSha256": sha256(workspace / "package-lock.json"), "dockerfileSha256": sha256(context / "Dockerfile"), "baseImageId": image["id"],
                "baseReference": reference, "fallbackReference": fallback, "builderImageId": image["id"],
                "nodeVersion": "22.22.3", "registry": registry, "memoryGiB": MEMORY_GIB, "cpus": 2,
                "maximumSeconds": MAX_SECONDS, "status": "prepared", "dependencyMode": "reuse-installed" if reuse_dependencies else "npm-ci"}
    if reuse_dependencies:
        manifest["reusedDependencies"] = reuse_installed_dependencies(root / "services/ui", workspace)
    private_json(directory / "manifest.json", manifest)
    return directory


def container_command(directory: Path, manifest: dict, stage: str, cache: Path) -> list[str]:
    if stage not in ("dependencies", "compile"):
        raise ValueError("Unknown build stage")
    common = ["docker", "run", "--rm", "--name", f"city-ui-{stage}-{directory.name.lower()}",
              "--runtime", "runc", "--memory", "4g", "--memory-swap", "4g", "--cpus", "2", "--pids-limit", "512",
              "--user", f"{os.getuid()}:{os.getgid()}", "--network", "host" if stage == "dependencies" else "none",
              "--mount", f"type=bind,source={directory / 'workspace'},target=/workspace", "--workdir", "/workspace",
              "-e", "NODE_OPTIONS=--max-old-space-size=2048", "-e", "CIRCLE_NODE_TOTAL=2",
              "-e", "NODE_ENV=production", "-e", "NEXT_TELEMETRY_DISABLED=1", "-e", "TURBO_TELEMETRY_DISABLED=1",
              "-e", "NVIDIA_VISIBLE_DEVICES=void", "-e", "CUDA_VISIBLE_DEVICES=", "-e", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1",
              "-e", "NPM_CONFIG_REPLACE_REGISTRY_HOST=always", "-e", f"NPM_CONFIG_REGISTRY={registry_url(manifest['registry'])}"]
    if stage == "dependencies":
        common += ["--mount", f"type=bind,source={cache},target=/npm-cache"]
    script = "umask 0002; test -x /bin/sh; command -v npm >/dev/null; npm --version; node -e \"if(process.versions.node!=='22.22.3')process.exit(1)\"; "
    script += ("exec npm ci --include=dev --prefer-offline --no-audit --no-fund --cache /npm-cache" if stage == "dependencies" else
               "exec ./node_modules/.bin/turbo run build bundle --filter=nv-metropolis-bp-vss-ui... --concurrency=1 --env-mode=loose")
    return common + ["--entrypoint", "/bin/sh", manifest["builderImageId"], "-ec", script]


def bounded_run(arguments: list[str], log: Path, root: Path, deadline: float, container_name: str | None = None) -> None:
    require_guard(root)
    if time.monotonic() >= deadline:
        raise RuntimeError("UI package exceeded its total 20-minute build deadline")
    process = None
    try:
        with log.open("wb") as handle:
            log.chmod(0o600)
            process = subprocess.Popen(arguments, stdout=handle, stderr=subprocess.STDOUT)
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("UI package exceeded its total 20-minute build deadline")
                require_guard(root, check_service=False)
                time.sleep(1)
            if process.returncode:
                raise RuntimeError(f"Packaging stage failed (exit {process.returncode}); inspect private {log.name}")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if container_name:
            # A killed Docker client must not leave a compiler consuming memory.
            subprocess.run(["docker", "rm", "--force", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)


def production_override(image: str) -> dict:
    # Inherit private base environment and saved data mounts without duplicating them.
    return {"services": {"vss-ui": {"image": image, "working_dir": "/repo", "user": f"65532:{os.getgid()}",
             "entrypoint": ["docker-entrypoint.sh"], "command": ["node", "custom-server.js"], "runtime": "runc",
             "environment": {"NODE_ENV": "production", "NODE_OPTIONS": "--max-old-space-size=1024",
                             "NEXT_TELEMETRY_DISABLED": "1", "VSS_CITY_ANALYTICS_URL": "http://127.0.0.1:9184"},
             "mem_limit": "2g", "memswap_limit": "2g", "cpus": 2}}}


def build(root: Path, selected: Path) -> Path:
    directory = package_directory(root, selected)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "prepared" or tree_digest(directory / "workspace", exclude_dependencies=True) != manifest.get("sourceSha256"):
        raise RuntimeError("Prepared inputs changed or were already built; prepare a fresh snapshot")
    if sha256(directory / "context/Dockerfile") != manifest.get("dockerfileSha256"):
        raise RuntimeError("Prepared packaging Dockerfile changed")
    if inspect_image(manifest["fallbackReference"])["id"] != manifest["baseImageId"] or manifest["builderImageId"] != manifest["baseImageId"]:
        raise RuntimeError("Saved fallback image identity changed")
    require_guard(root)
    deadline = time.monotonic() + MAX_SECONDS
    cache = root / ".spark/ui-npm-cache"
    cache.mkdir(mode=0o700, exist_ok=True)
    manifest["status"] = "building"
    private_json(manifest_path, manifest)
    try:
        if manifest.get("dependencyMode") == "reuse-installed":
            copied = validate_installed_dependencies(directory / "workspace")
            receipt = manifest["reusedDependencies"]
            if any(copied.get(field) != receipt.get(field) for field in copied) or dependencies_digest(directory / "workspace", copied["dependencyRoots"]) != receipt.get("dependencyTreeSha256"):
                raise RuntimeError("Reused dependency bytes or installed manifests changed after prepare")
        stages = ("compile",) if manifest.get("dependencyMode") == "reuse-installed" else ("dependencies", "compile")
        for stage in stages:
            command = container_command(directory, manifest, stage, cache)
            bounded_run(command, directory / f"{stage}.log", root, deadline, command[command.index("--name") + 1])
        workspace = directory / "workspace"
        app = workspace / "apps" / APP
        standalone = app / ".next/standalone"
        if not (standalone / "apps" / APP / "server.js").is_file():
            raise RuntimeError("VSS standalone server was not produced")
        context = directory / "context"
        for source, name in ((standalone, "standalone"), (app / ".next/static", "static"), (app / "public", "public")):
            shutil.copytree(source, context / name, symlinks=True)
        shutil.copy2(workspace / "custom-server.js", context / "custom-server.js")
        for name in RUNTIME_MODULES:
            shutil.copytree(workspace / "node_modules" / name, context / "runtime-node-modules" / name, symlinks=False)
        artifact_hash = tree_digest(context, internal_links=True)
        tag = f"vss-spark-vss-ui:smart-city-{manifest['sourceSha256'][:12]}-{directory.name.lower()}"
        command = ["docker", "build", "--builder", "default", "--pull=false", "--network=none", "--build-arg", f"UI_BASE_IMAGE={manifest['fallbackReference']}",
                   "--iidfile", str(directory / "image.id"), "--tag", tag, str(context)]
        bounded_run(command, directory / "image.log", root, deadline)
        image_id = (directory / "image.id").read_text().strip()
        if inspect_image(tag)["id"] != image_id:
            raise RuntimeError("Candidate image identity does not match its packaging receipt")
        overlay = directory / "compose-ui-production.json"
        private_json(overlay, production_override(tag))
        run(["docker", "compose", "--project-name", "vss-spark", "-f", str(root / ".spark/compose.json"), "-f", str(overlay), "config", "--quiet"], stdout=subprocess.DEVNULL)
        manifest.update(status="built", imageId=image_id, imageReference=tag, composeOverride=str(overlay),
                        artifactSha256=artifact_hash)
        private_json(manifest_path, manifest)
        return overlay
    except BaseException:
        manifest["status"] = "failed"
        private_json(manifest_path, manifest)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "build"))
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--reuse-installed-dependencies", action="store_true", help="Explicitly validate and copy the tested local installation; perform no npm/network install")
    args = parser.parse_args()
    if args.mode == "prepare":
        if args.package_dir:
            parser.error("prepare allocates its own new private directory")
        directory = prepare(ROOT, reuse_dependencies=args.reuse_installed_dependencies)
        print(f"Prepared frozen UI source: {directory}")
        print(f"Next: python3 tools/smart-city/ui_package.py build --package-dir {directory}")
    else:
        if args.reuse_installed_dependencies:
            parser.error("dependency reuse must be selected explicitly during prepare")
        if not args.package_dir:
            parser.error("build requires --package-dir from prepare")
        overlay = build(ROOT, args.package_dir)
        print(f"Candidate built; running services were not recreated. Override: {overlay}")
        print(f"Review, then switch only UI: docker compose --project-name vss-spark -f {ROOT / '.spark/compose.json'} -f {overlay} up -d --no-deps --force-recreate --no-build --pull never vss-ui")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
