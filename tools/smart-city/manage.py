#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Manage the additive VSS Smart City services without replacing the base stack."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
import platform
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:9184/api/v1/city"
CONTROLLER_BASE = "http://127.0.0.1:9190"


def run(*arguments: str, **kwargs):
    return subprocess.run([str(arg) for arg in arguments], check=True, **kwargs)


def hardware_inventory() -> dict:
    spec = importlib.util.spec_from_file_location("city_host_platform", ROOT / "tools/runtime/platforms.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot inspect the actual host hardware")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.inventory()


@lru_cache(maxsize=1)
def city_model_module():
    """Retain stat-keyed digests; selection and receipt validation still run."""
    spec = importlib.util.spec_from_file_location("city_selected_model", Path(__file__).with_name("model_profile.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the selected detector contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_city_model(device: str) -> dict:
    return city_model_module().selected_model(ROOT, device)


@lru_cache(maxsize=1)
def city_demo_module():
    spec = importlib.util.spec_from_file_location('city_mv3dt_demo_profile', Path(__file__).with_name('mv3dt_demo_profile.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load the experimental map association profile')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def live_runtime_tuning(device: str) -> dict[str, int | str]:
    """Read bounded live scheduling/display/decoder settings; no arbitrary flags."""
    path = ROOT / f".{device}/city/state/runtime-tuning.json"
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if isinstance(value, dict) and "inferenceInterval" in value:
        # DeepStream 9.2's preprocessed-tensor path does not use the full-frame
        # interval counter. Accepting this key would claim ineffective tuning.
        raise ValueError("inferenceInterval is unsupported with preprocessed tensor input; remove it from runtime tuning")
    if not isinstance(value, dict) or not value or not set(value) <= {"muxTimeoutUs", "previewFps", "previewTransport", "decoder", "decoderExtraSurfaces", "decoderLowLatency"}:
        raise ValueError("Runtime tuning only supports muxTimeoutUs, previewFps, previewTransport, decoder, decoderExtraSurfaces and decoderLowLatency")
    if "previewTransport" in value and value["previewTransport"] not in ("jpeg", "webrtc"):
        raise ValueError("previewTransport must be jpeg or webrtc")
    for key, low, high in (("muxTimeoutUs", 1000, 1000000), ("previewFps", 1, 30), ("decoderExtraSurfaces", 0, 8)):
        if key in value and (type(value[key]) is not int or not low <= value[key] <= high):
            raise ValueError(f"{key} must be an integer between {low} and {high}")
    if "decoder" in value and (not isinstance(value["decoder"], str) or value["decoder"] not in ("cpu", "hardware")):
        raise ValueError("decoder must be exactly cpu or hardware")
    if value.get("decoderExtraSurfaces", 0) and value.get("decoder") != "hardware":
        raise ValueError("decoderExtraSurfaces requires explicit hardware decoding")
    if "decoderLowLatency" in value and type(value["decoderLowLatency"]) is not bool:
        raise ValueError("decoderLowLatency must be a boolean")
    if value.get("decoderLowLatency") and value.get("decoder") != "hardware":
        raise ValueError("decoderLowLatency requires explicit hardware decoding and I/P-only input")
    return value


def live_mux_timeout(device: str) -> int | None:
    return live_runtime_tuning(device).get("muxTimeoutUs")


def mux_dimensions(sources: list[dict]) -> tuple[int, int]:
    """Use decoded geometry instead of upscaling every source to 1080p.

    Equal-sized cameras keep that exact geometry. Mixed sources use per-axis
    maxima; downstream boxes are still scaled into each original image and the
    tracker retains its separately calibrated 640x384 input.
    """
    if not 1 <= len(sources) <= 2:
        raise ValueError("Mux geometry requires one or two decoded sources")
    for source in sources:
        if any(type(source.get(key)) is not int or not 1 <= source[key] <= 16384 for key in ("width", "height")):
            raise ValueError("Each source needs valid decoded width and height before inference")
    return max(source["width"] for source in sources), max(source["height"] for source in sources)


def require_actual_device(device: str) -> None:
    if device != "thor":
        return
    actual = hardware_inventory()
    if actual.get("platform") != "thor":
        raise RuntimeError("Thor build/start/analyze requires an actual Thor host; Spark may render Thor configuration only")


def require_native_engine(device: str) -> None:
    if device != "thor":
        return
    directory = ROOT / ".thor/city/models"
    size = city_model_module().selection_name(ROOT, device)
    engine = directory / f"rfdetr-{size}-fp16-b2.engine"
    receipt_path = engine.with_suffix(".build.json")
    if not receipt_path.exists():
        receipt_path = directory / "engine-build.json"
    if engine.is_symlink() or not engine.is_file() or not engine.resolve().is_relative_to(directory.resolve()):
        raise RuntimeError("Thor needs its own locally built TensorRT engine; Spark links/copies are unsupported")
    if not receipt_path.is_file():
        raise RuntimeError("Thor engine-build.json must identify a Thor GPU build and the actual engine hash")
    receipt = json.loads(receipt_path.read_text())
    digest = hashlib.sha256(engine.read_bytes()).hexdigest()
    if receipt.get("device") != "thor" or "THOR" not in str(receipt.get("gpu", "")).upper() or receipt.get("engineSha256") != digest:
        raise RuntimeError("Thor engine receipt does not prove this engine was built for the target device")
    spark_engine = ROOT / f".spark/city/models/rfdetr-{size}-fp16-b2.engine"
    if spark_engine.is_file() and hashlib.sha256(spark_engine.read_bytes()).hexdigest() == digest:
        raise RuntimeError("Refusing a Spark TensorRT engine in the Thor deployment")


def available_gib() -> float:
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(values["MemAvailable"].strip().split()[0]) / 1024**2


def saved_reserve(device: str) -> float:
    path = ROOT / f".{device}/settings.json"
    if not path.is_file():
        raise RuntimeError(f"Initialize the existing {device} deployment and its saved guard before launch")
    settings = json.loads(path.read_text())
    value = settings.get("reserve_gib")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError("Saved memory reserve is missing or invalid; refusing an unguarded launch")
    return float(value)


def ensure_headroom(device: str) -> None:
    floor = saved_reserve(device)
    available = available_gib()
    if available < floor:
        raise RuntimeError(f"{available:.1f} GiB available; need saved {floor:.1f} GiB reserve")
    guard = ROOT / f".{device}/guard-status.json"
    if not guard.is_file() or time.time() - guard.stat().st_mtime > 15:
        raise RuntimeError("Existing device memory guard telemetry is absent or stale")


def request(path: str, payload=None, method="GET"):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + "/" + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def wait_for_gateway(timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return request("health")
        except (OSError, ValueError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"City analytics did not become ready: {last_error}")


def approved_uri(uri: str, device: str) -> bool:
    parsed = urlsplit(uri)
    if parsed.scheme in ("rtsp", "rtsps"):
        return bool(parsed.hostname)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        if parsed.netloc or not path.is_relative_to("/media") or ".." in path.parts:
            return False
        media = ROOT / f".{device}/city/media"
        candidate = (media / path.relative_to("/media")).resolve()
        return candidate.is_relative_to(media.resolve()) and candidate.is_file()
    if parsed.scheme in ("http", "https"):
        settings = json.loads((ROOT / f".{device}/settings.json").read_text())
        return (parsed.hostname in {"127.0.0.1", "localhost", settings.get("host_ip")}
                and parsed.port == 30888 and parsed.path.startswith("/vst/api/v1/storage/"))
    return False


def state_dir(device: str) -> Path:
    directory = ROOT / f".{device}/city"
    for child in ("state", "media", "models", "runtime"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    return directory


def controller_setup(device: str) -> Path:
    """Create only a CPU host control environment; no model containers start."""
    directory = state_dir(device)
    environment = directory / "control-env"
    python = environment / "bin/python"
    if not python.is_file():
        run(sys.executable, "-m", "venv", str(environment))
    run(str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r",
        str(ROOT / "tools/smart-city/controller-requirements.txt"))
    return python


def controller_process(device: str) -> dict | None:
    path = state_dir(device) / "runtime/controller-process.json"
    if not path.is_file():
        return None
    record = json.loads(path.read_text())
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
        ticks = (Path("/proc") / str(pid) / "stat").read_text().split()[21]
    except OSError:
        return None
    expected = str(ROOT / "tools/smart-city/controller.py").encode()
    if expected not in command or record.get("startTicks") != ticks:
        return None
    return record


def controller_health() -> dict:
    with urllib.request.urlopen(CONTROLLER_BASE + "/api/v1/health", timeout=20) as response:
        return json.load(response)


def controller_start(device: str) -> None:
    require_actual_device(device)
    ensure_headroom(device)
    existing = controller_process(device)
    if existing:
        print(json.dumps({"pid": existing["pid"], "health": controller_health()}, indent=2))
        return
    directory = state_dir(device)
    python = directory / "control-env/bin/python"
    if not python.is_file():
        raise RuntimeError("Run controller-setup before starting its isolated CPU service")
    # Do not replace a controller started through an existing user service.
    try:
        health = controller_health()
    except (OSError, ValueError):
        health = None
    if health is not None:
        print(json.dumps({"running": True, "managedBy": "existing-user-service", "health": health}, indent=2))
        return
    log = directory / "runtime/controller.log"
    environment = os.environ.copy()
    environment_file = directory / "controller.env"
    if environment_file.is_file():
        allowed = {"CITY_RTSP_ALLOWED_HOSTS", "CITY_VSS_ORIGIN", "CITY_GATEWAY_URL"}
        for line in environment_file.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or key not in allowed:
                raise RuntimeError("controller.env contains an unsupported setting")
            environment[key] = value
    with log.open("a") as output:
        process = subprocess.Popen([str(python), str(ROOT / "tools/smart-city/controller.py"), "--device", device],
                                   cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True, env=environment)
    record = {"pid": process.pid, "startTicks": (Path("/proc") / str(process.pid) / "stat").read_text().split()[21],
              "device": device, "log": str(log)}
    (directory / "runtime/controller-process.json").write_text(json.dumps(record, indent=2) + "\n")
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Controller exited {process.returncode}; inspect {log}")
        try:
            print(json.dumps({"pid": process.pid, "health": controller_health()}, indent=2))
            return
        except (OSError, ValueError):
            time.sleep(0.2)
    raise RuntimeError(f"Controller startup is still unconfirmed; inspect {log}")


def controller_stop(device: str) -> None:
    record = controller_process(device)
    if record is None:
        print("No matching standalone controller process. A systemd user service must be stopped with systemctl --user.")
        return
    os.kill(record["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and controller_process(device):
        time.sleep(0.2)
    if controller_process(device):
        raise RuntimeError("Controller is still stopping; inspect its log before retrying")
    (state_dir(device) / "runtime/controller-process.json").unlink(missing_ok=True)
    print("Standalone Smart City controller stopped.")


def controller_service(device: str) -> Path:
    """Write a reviewable host-user unit; enabling it is a separate command."""
    directory = state_dir(device)
    python = directory / "control-env/bin/python"
    if not python.is_file():
        raise RuntimeError("Run controller-setup before installing its service")
    destination = Path.home() / ".config/systemd/user" / f"vss-city-controller-{device}.service"
    destination.parent.mkdir(parents=True, exist_ok=True)
    unit = ("[Unit]\nDescription=VSS Smart City local source controller\nAfter=default.target\n\n[Service]\nType=simple\n"
            f"WorkingDirectory={ROOT}\nExecStart={python} {ROOT}/tools/smart-city/controller.py --device {device}\n"
            f"EnvironmentFile=-{directory}/controller.env\nRestart=on-failure\nRestartSec=3\nTimeoutStopSec=30\n"
            "KillMode=mixed\nMemoryMax=512M\nCPUQuota=200%\nNoNewPrivileges=true\n\n[Install]\nWantedBy=default.target\n")
    destination.write_text(unit)
    print(f"Wrote {destination}. Stop any standalone controller, then run:")
    print(f"systemctl --user daemon-reload\nsystemctl --user enable --now vss-city-controller-{device}.service")
    return destination


def profile_overlay(device: str, enabled: bool) -> Path:
    directory = state_dir(device)
    path = directory / "agent-city-overlay.json"
    value = json.loads(path.read_text()) if path.exists() else {'services': {'vss-agent': {'environment': {}}}}
    value['services']['vss-agent'].setdefault('environment', {})['VSS_CITY_RTVI_CV_URL'] = CONTROLLER_BASE if enabled else ''
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


def profile_activate(device: str, enabled: bool) -> None:
    """Recreate only the source-mounted CPU Agent, keeping other roles/budgets."""
    require_actual_device(device)
    ensure_headroom(device)
    health = controller_health()
    if not enabled and health.get("stream-info", {}).get("stream-info"):
        raise RuntimeError("Pause all Smart City sources through the Agent before disabling its controller URL")
    base = ROOT / f".{device}/compose.json"
    if not base.is_file():
        raise RuntimeError("Render the existing base VSS deployment before enabling an additive city profile")
    overlay = profile_overlay(device, enabled)
    run("docker", "compose", "-f", str(base), "-f", str(overlay), "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "--wait", "--wait-timeout", "120", "vss-agent", cwd=ROOT)
    print("Smart City profile enabled through the existing VSS Agent." if enabled else "Smart City worker URL disabled; other profiles remain configured.")
    print("Reapply this additive overlay after rendering/recreating the base Agent.")


def agent_request(path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8100/api/v1/" + path, data=body,
                                 method="POST" if payload is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def source_analysis(source_id: str, kind: str, profile: str, name: str, action: str) -> dict:
    """Use the existing Agent source controls; never bypass admission with Docker."""
    identifier = quote(source_id, safe="")
    if kind == "recorded":
        if action != "configure":
            raise ValueError("Recorded sources use configure; choose semantic-search to remove detector analysis")
        return agent_request(f"videos/{identifier}/analysis", {"analysisProfileId": profile})
    if not name:
        raise ValueError("Live controls require the exact registered VIOS source name")
    return agent_request(f"rtsp-streams/{identifier}/analysis", {"action": action, "name": name, "analysisProfileId": profile})


def preview_register(uri: str, name: str) -> dict:
    if urlsplit(uri).scheme not in {"rtsp", "rtsps"} or not urlsplit(uri).hostname:
        raise ValueError("A preview source requires an explicit RTSP URL")
    with urllib.request.urlopen("http://127.0.0.1:30888/vst/api/v1/sensor/list", timeout=15) as response:
        existing = json.load(response)
    if any(source.get("name") == name for source in existing):
        raise ValueError("That VIOS name is already registered; use the existing source ID instead of uploading it again")
    return agent_request("rtsp-streams/add", {"sensorUrl": uri, "name": name, "startAnalysis": False,
                                              "analysisProfileId": "semantic-search", "tags": "smart-city"})


def compose_file(device: str) -> Path:
    directory = state_dir(device)
    demo = city_demo_module().load(ROOT, device)
    registry_file = directory / "media-registry.json"
    registry = json.loads(registry_file.read_text()) if registry_file.exists() else {
        "traffic-cam-1": "traffic-sample.mp4", "pedestrian-cam-2": "pedestrian-sample.mp4"}
    body = {"name": f"vss-{device}-city", "services": {
        "city-analytics": {
            "image": "vss-city-analytics:dev", "container_name": "vss-city-analytics",
            "network_mode": "host", "user": "1000:1000", "mem_limit": "768m", "memswap_limit": "768m", "cpus": 2,
            "labels": {"com.connecttech.vss.city": "analytics"},
            "command": ["uvicorn", "apps.city.main:app", "--host", "127.0.0.1", "--port", "9184", "--workers", "1"],
            "environment": {"CITY_STATE_DB": "/var/lib/vss-city/state.sqlite3", "CITY_MEDIA_ROOT": "/opt/city/media",
                            "CITY_NATIVE_CONFIG_DIR": "/var/lib/vss-city/native", "CITY_MEDIA_REGISTRY_JSON": json.dumps(registry)},
            "volumes": [f"{directory}/state:/var/lib/vss-city", f"{directory}/media:/opt/city/media:ro",
                        f"{ROOT}/services/analytics/behavior-analytics/apps/city:/opt/vss/services/analytics/behavior-analytics/apps/city:ro"],
            "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9184/api/v1/city/health',timeout=2)"],
                            "interval": "10s", "timeout": "3s", "retries": 3},
        },
        "city-detector": {
            "image": f"vss-city-perception:{device}", "profiles": ["perception"],
            "network_mode": "host", "runtime": "nvidia", "user": "1000:1000",
            "mem_limit": "8g", "memswap_limit": "8g", "cpus": 6,
            "labels": {"com.connecttech.vss.city": "detector"},
            "environment": {"NVIDIA_VISIBLE_DEVICES": "all", "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,video"},
            "volumes": [f"{directory}/models:/models", f"{directory}/media:/media:ro", f"{directory}/state:/state"],
        },
    }}
    if demo is not None:
        body['services']['city-detector']['image'] = demo['imageId']
        body['services']['city-analytics']['environment'].update(city_demo_module().gateway_environment(demo))
    if live_runtime_tuning(device).get("previewTransport") == "webrtc":
        if demo is None:
            raise ValueError("WebRTC video requires the pinned native camera profile")
        import runpy
        relay = runpy.run_path(str(ROOT / "tools/smart-city/video_transport.py"))["relay_service"]
        body["services"]["city-video"] = relay(ROOT, device, demo["cameraOrder"])
    path = directory / "compose.json"
    path.write_text(json.dumps(body, indent=2) + "\n")
    return path


def build(device: str, perception: bool) -> None:
    require_actual_device(device)
    ensure_headroom(device)
    if shutil.disk_usage(ROOT).free < 8 * 1024**3:
        raise RuntimeError("Need 8 GiB free for the bounded image build; no cache pruning is performed")
    role = "perception" if perception else "analytics"
    tag = f"vss-city-perception:{device}" if perception else "vss-city-analytics:dev"
    arguments = ["docker", "build", "--network", "host", "-f", f"deploy/docker/smart-city/Dockerfile.{role}", "-t", tag]
    if perception and device == "thor":
        # Build on Thor only; do not copy a Spark engine into this deployment.
        arguments += ["--build-arg", "CITY_DS_IMAGE=ghcr.io/nvidia/deepstream:9.2-samples-multiarch"]
    run(*arguments, ".", cwd=ROOT)


def recorded(device: str) -> None:
    directory = state_dir(device)
    current = request("site")
    registration = directory / "vss-media-registration.json"
    registrations = json.loads(registration.read_text()) if registration.exists() else {}
    sources, registry = [], {}
    for source_id, name, filename, width, height, duration in (
        ("traffic-cam-1", "Traffic detector test · moving camera", "traffic-sample.mp4", 1920, 1080, 48.1),
        ("pedestrian-cam-2", "Pedestrian detector test · fixed camera", "pedestrian-sample.mp4", 768, 576, 79.5),
    ):
        if not (directory / "media" / filename).is_file():
            raise RuntimeError(f"Stage the registered recording first: {filename}")
        sensor = registrations.get(filename, {}).get("sensorId")
        canonical_id = sensor or source_id
        sources.append({"id": canonical_id, "name": name, "width": width, "height": height,
                        "durationSeconds": duration, "deepstreamStreamIndex": len(sources),
                        "mediaUrl": f"/api/vision/city/media/{canonical_id}", "vssSensorId": sensor,
                        "inputUri": f"file:///media/{filename}", "calibrationStatus": "not-calibrated"})
        registry[canonical_id] = filename
    site = {"id": "recorded-traffic-tests", "name": "Recorded traffic · real inference",
            "revision": current["revision"] + 1 if current["id"] == "recorded-traffic-tests" else 1,
            "expectedRevision": current["revision"],
            "mode": "recorded-inference", "sources": sources,
            "qualification": "Independent recordings, not overlapping cameras. Ground map requires a calibrated static site.",
            "map": {"bounds": [-50, -50, 50, 50], "roads": [], "buildings": []}}
    (directory / "media-registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    (directory / "recorded-site.json").write_text(json.dumps(site, indent=2) + "\n")
    print(json.dumps(request("site", site, "PUT"), indent=2))
    rules = [{"id": "recorded-person-area", "name": "Pedestrian area occupancy", "kind": "occupancy-threshold",
              "sourceId": sources[1]["id"], "classes": ["person"], "enabled": True, "revision": 1,
              "geometry": {"space": "image-normalized", "points": [[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]]},
              "conditions": {"countThreshold": 2, "minimumDurationMs": 500, "clearAfterMs": 500}}]
    print(json.dumps(request("rules", {"rules": rules}, "PUT"), indent=2))
    print("Recorded sources configured; restart only city-analytics after rendering to apply its controlled media registry.")


def native(device: str, frames: int, unpaced: bool, live: bool = False) -> None:
    require_actual_device(device)
    require_native_engine(device)
    ensure_headroom(device)
    directory = state_dir(device)
    site = request("site")
    if site["mode"] != "recorded-inference" and site["mode"] != "live":
        raise RuntimeError("Select real recorded or live sources before starting model inference")
    if not site["sources"] or len(site["sources"]) > 2:
        raise RuntimeError("The qualified worker supports one or two explicit sources")
    width, height = mux_dimensions(site["sources"])
    tuning = live_runtime_tuning(device) if live else {}
    if live and (site["mode"] != "live" or any(urlsplit(s.get("inputUri", "")).scheme not in ("rtsp", "rtsps") for s in site["sources"])):
        raise RuntimeError("Continuous live mode requires an explicit live site with RTSP sources")
    model = city_model_module().config_for_launch(ROOT, device)
    demo_profile = city_demo_module().load(ROOT, device)
    if model.get('adapterImage') and (demo_profile is None or demo_profile.get('imageId') != model['adapterImage']):
        raise RuntimeError('TrafficCamNet adapter requires its pinned DeepStream demo image')
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    compose = compose_file(device)
    if live and tuning.get("previewTransport") == "webrtc":
        run("docker", "compose", "-f", str(compose), "up", "-d", "--no-build", "--pull", "never", "city-video")
    arguments = ["docker", "compose", "-f", str(compose), "run", "--rm", "--name", "vss-city-detector"]
    # The experimental adapter is bound only for its validated model profile.
    # The selected profile pins each binary and the receipt; RF-DETR keeps the
    # original image contents and requires no extra mounts.
    for mount in model.get("adapterMounts", []):
        arguments += ["--volume", f"{mount['hostPath']}:{mount['containerPath']}:ro"]
    arguments.append("city-detector")
    for source in site["sources"]:
        uri = source.get("inputUri")
        if not isinstance(uri, str) or not approved_uri(uri, device):
            raise RuntimeError("Each source needs a registered local/VSS recording or RTSP URI")
        arguments += ["--source", f"{source['id']}={uri}"]
    arguments += ["--site-id", site["id"], "--post-url", BASE + "/observations",
                  "--analytics-config", "/state/native/analytics.ini", "--analytics-ack-file", "/state/native/analytics-ack.json",
                  "--output", "/state/live-observations.ndjson" if live else f"/state/observations-{stamp}.ndjson",
                  "--frames", str(frames), "--width", str(width), "--height", str(height)]
    arguments += model["nativeArgs"]
    arguments += city_demo_module().native_args(demo_profile, site, live=live)
    if live:
        # Bound future continuous sessions without touching finite QA artifacts.
        # Two retained generations plus current total at most 768 MiB.
        arguments += ["--output-max-bytes", str(256 * 1024**2), "--output-retained-files", "2"]
        # Display frames retain their exact observation identity in either transport.
        transport = tuning.get("previewTransport", "jpeg")
        arguments += ["--preview-url", BASE + ("/video/frame" if transport == "webrtc" else "/preview"), "--preview-fps", str(tuning.get("previewFps", 15)),
                      "--preview-stats-file", "/state/native/preview-stats.json"]
        if transport == "webrtc":
            arguments += ["--preview-transport", "webrtc"]
    if live and (timeout := tuning.get("muxTimeoutUs")) is not None:
        arguments += ["--mux-timeout-us", str(timeout)]
    if live and "decoderExtraSurfaces" in tuning:
        arguments += ["--decoder-extra-surfaces", str(tuning["decoderExtraSurfaces"])]
    if live and tuning.get("decoderLowLatency"):
        arguments += ["--decoder-low-latency"]
    # Preserve the measured platform defaults unless a live trial explicitly
    # requests another decoder. Hardware permits decodebin's NVIDIA path;
    # successful selection and frame delivery still need runtime verification.
    if tuning.get("decoder", "cpu" if device == "spark" else "hardware") == "cpu":
        arguments.append("--cpu-decode")
    if unpaced:
        arguments.append("--unpaced")
    log = directory / "runtime" / f"detector-{stamp}.log"
    with log.open("w") as output:
        if live:
            # Record this worker's supported runtime settings without secrets.
            output.write("City runtime settings: " + json.dumps({
                "modelRevision": model.get("modelRevision"), "configDir": model.get("configDir"),
                "muxDimensions": [width, height],
                "decoder": tuning.get("decoder", "cpu" if device == "spark" else "hardware"),
                "previewFps": tuning.get("previewFps", 15), "previewTransport": tuning.get("previewTransport", "jpeg"), "muxTimeoutUs": tuning.get("muxTimeoutUs", 40000),
                "decoderExtraSurfaces": tuning.get("decoderExtraSurfaces", 0),
                "decoderLowLatency": tuning.get("decoderLowLatency", False),
            }) + "\n")
            output.flush()
        process = subprocess.Popen(arguments, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                try:
                    ensure_headroom(device)
                except RuntimeError:
                    subprocess.run(["docker", "stop", "-t", "5", "vss-city-detector"], check=False, capture_output=True)
                    raise
                time.sleep(0.5)
            if process.returncode:
                raise RuntimeError(f"Detector exited {process.returncode}; inspect {log}")
        finally:
            if process.poll() is None:
                # Stopping a compose client alone does not prove its GPU container stopped.
                subprocess.run(["docker", "stop", "-t", "5", "vss-city-detector"], check=False, capture_output=True)
                process.terminate()
                process.wait(timeout=10)
    print(f"Native inference complete. Receipt log: {log}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("spark", "thor"), default="spark")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "render", "start", "stop", "status", "recorded", "controller-setup", "controller-start", "controller-stop", "controller-status", "controller-service", "profile-enable", "profile-disable"):
        sub.add_parser(command)
    builder = sub.add_parser("build")
    builder.add_argument("--perception", action="store_true")
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--repeat", action="store_true")
    fixture.add_argument("--fast", action="store_true")
    detector = sub.add_parser("analyze")
    detector.add_argument("--frames", type=int, default=3000)
    detector.add_argument("--unpaced", action="store_true")
    detector.add_argument("--live", action="store_true", help="Explicit continuous RTSP mode; saved guard remains required")
    source = sub.add_parser("source-analysis", help="Configure/pause/resume through existing VSS Agent source APIs")
    source.add_argument("--source-id", required=True)
    source.add_argument("--kind", choices=("recorded", "live"), required=True)
    source.add_argument("--profile", choices=("smart-city", "semantic-search", "warehouse-safety", "traffic-monitoring"), default="smart-city")
    source.add_argument("--name", default="")
    source.add_argument("--action", choices=("configure", "pause", "resume"), default="configure")
    preview = sub.add_parser("preview-register", help="Register an RTSP preview with AI analysis explicitly paused")
    preview.add_argument("--url", required=True)
    preview.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.command == "doctor":
        print(json.dumps({"architecture": platform.machine(), "device": args.device,
                          "availableGiB": available_gib(), "reserveGiB": saved_reserve(args.device),
                          "diskFreeGiB": shutil.disk_usage(ROOT).free / 1024**3}, indent=2))
        ensure_headroom(args.device)
    elif args.command == "render":
        print(compose_file(args.device))
    elif args.command == "build":
        build(args.device, args.perception)
    elif args.command == "start":
        require_actual_device(args.device)
        ensure_headroom(args.device)
        run("docker", "compose", "-f", str(compose_file(args.device)), "up", "-d", "--no-build", "--pull", "never", "city-analytics")
        print(json.dumps(wait_for_gateway(), indent=2))
    elif args.command == "stop":
        run("docker", "compose", "-f", str(compose_file(args.device)), "stop")
    elif args.command == "status":
        print(json.dumps(request("health"), indent=2))
    elif args.command == "recorded":
        recorded(args.device)
    elif args.command == "controller-setup":
        print(controller_setup(args.device))
    elif args.command == "controller-start":
        controller_start(args.device)
    elif args.command == "controller-stop":
        controller_stop(args.device)
    elif args.command == "controller-status":
        print(json.dumps({"process": controller_process(args.device), "health": controller_health()}, indent=2))
    elif args.command == "controller-service":
        controller_service(args.device)
    elif args.command in {"profile-enable", "profile-disable"}:
        profile_activate(args.device, args.command == "profile-enable")
    elif args.command == "source-analysis":
        print(json.dumps(source_analysis(args.source_id, args.kind, args.profile, args.name, args.action), indent=2))
    elif args.command == "preview-register":
        print(json.dumps(preview_register(args.url, args.name), indent=2))
    elif args.command == "fixture":
        arguments = [sys.executable, "-m", "apps.city.fixtures", "--base-url", "http://127.0.0.1:9184"]
        if args.repeat:
            arguments.append("--repeat")
        if args.fast:
            arguments.append("--no-realtime")
        run(*arguments, cwd=ROOT / "services/analytics/behavior-analytics")
    elif args.command == "analyze":
        if not (1 <= args.frames <= 18000 or (args.live and args.frames == 0)):
            parser.error("frames must be 1–18000, or zero with explicit --live RTSP mode")
        native(args.device, args.frames, args.unpaced, args.live)


if __name__ == "__main__":
    main()
