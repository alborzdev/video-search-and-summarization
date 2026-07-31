#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

python3 - "${repo_root}" <<'PY'
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1])
docker_dir = root / "deploy/docker"
monitoring_dir = docker_dir / "services/monitoring"
compose_path = monitoring_dir / "compose.yml"
thor_prometheus_path = docker_dir / "thor-local/observability/prometheus.yml"

with compose_path.open(encoding="utf-8") as stream:
    source = yaml.safe_load(stream)
services = source["services"]

thor_profile = "bp_developer_thor_full_2d"
thor_services = {"prometheus", "grafana", "node-exporter", "cadvisor"}
published_port_variables = {
    "prometheus": "${PROMETHEUS_PORT:-9090}",
    "grafana": "${GRAFANA_PORT:-35000}",
    "node-exporter": "${NODE_EXPORTER_PORT:-19100}",
    "cadvisor": "${CADVISOR_PORT:-18080}",
}
assert thor_services <= services.keys()
for service_name in thor_services:
    service = services[service_name]
    assert thor_profile in service["profiles"], service_name
    # Preserve the upstream warehouse exposure contract. Thor passes an
    # explicit loopback override when resolving its profile.
    assert service["ports"][0].startswith(
        "${MONITORING_BIND_ADDRESS:-0.0.0.0}:"
    ), service_name
    assert f":{published_port_variables[service_name]}:" in service["ports"][0]
    image = service["image"]
    assert ":" in image and not image.endswith(":latest"), (service_name, image)
    assert service["logging"] == {
        "driver": "local",
        "options": {
            "max-file": "${MONITORING_LOG_MAX_FILES:-3}",
            "max-size": "${MONITORING_LOG_MAX_SIZE:-10m}",
        },
    }

# DCGM is intentionally not selected on Jetson/Thor. It remains available to
# the datacenter warehouse profiles where NVIDIA DCGM is supported.
assert thor_profile not in services["dcgm-exporter"]["profiles"]

prometheus = services["prometheus"]
assert "--storage.tsdb.retention.time=${PROMETHEUS_RETENTION_TIME:-7d}" in prometheus["command"]
assert "--storage.tsdb.retention.size=${PROMETHEUS_RETENTION_SIZE:-10GB}" in prometheus["command"]
assert "${PROMETHEUS_CONFIG_FILE:-$VSS_APPS_DIR/services/monitoring/config/prometheus.yml}:/etc/prometheus/prometheus.yml:ro" in prometheus["volumes"]
assert "prometheus-storage:/prometheus" in prometheus["volumes"]
assert prometheus["extra_hosts"] == ["host.docker.internal:host-gateway"]
assert prometheus["healthcheck"]["test"] == [
    "CMD",
    "/bin/promtool",
    "query",
    "instant",
    "http://127.0.0.1:9090",
    "up",
]

grafana = services["grafana"]
grafana_environment = set(grafana["environment"])
for expected in (
    "GF_ANALYTICS_REPORTING_ENABLED=false",
    "GF_ANALYTICS_CHECK_FOR_UPDATES=false",
    "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES=false",
    "GF_NEWS_NEWS_FEED_ENABLED=false",
    "GF_PLUGINS_PREINSTALL=",
    "GF_INSTALL_PLUGINS=",
    "GF_SECURITY_DISABLE_GRAVATAR=true",
    "GF_SNAPSHOTS_EXTERNAL_ENABLED=false",
    "GF_USERS_ALLOW_SIGN_UP=false",
):
    assert expected in grafana_environment, expected
assert all(mount.endswith(":ro") for mount in grafana["volumes"] if "/etc/grafana/" in mount)
assert grafana["depends_on"] == {"prometheus": {"condition": "service_healthy"}}
assert grafana["healthcheck"]["test"] == [
    "CMD",
    "curl",
    "--fail",
    "--silent",
    "--show-error",
    "http://127.0.0.1:3000/api/health",
]

with (monitoring_dir / "config/prometheus.yml").open(encoding="utf-8") as stream:
    prometheus_config = yaml.safe_load(stream)
assert prometheus_config["global"] == {
    "scrape_interval": "15s",
    "scrape_timeout": "10s",
    "evaluation_interval": "15s",
}
assert "remote_write" not in prometheus_config
assert "remote_read" not in prometheus_config
jobs = {job["job_name"]: job for job in prometheus_config["scrape_configs"]}
assert {"prometheus", "dcgm-exporter", "cadvisor", "node-exporter"} == jobs.keys()

with thor_prometheus_path.open(encoding="utf-8") as stream:
    thor_prometheus_config = yaml.safe_load(stream)
assert thor_prometheus_config["global"] == prometheus_config["global"]
assert "remote_write" not in thor_prometheus_config
assert "remote_read" not in thor_prometheus_config
thor_jobs = {
    job["job_name"]: job for job in thor_prometheus_config["scrape_configs"]
}
assert {
    "prometheus",
    "cadvisor",
    "node-exporter",
    "rtvi-vlm",
    "rtvi-embed",
    "lvs",
} == thor_jobs.keys()
assert "dcgm-exporter" not in thor_jobs
assert thor_jobs["rtvi-vlm"]["metrics_path"] == "/v1/metrics"
assert thor_jobs["rtvi-vlm"]["static_configs"] == [{"targets": ["rtvi-vlm:8000"]}]
assert thor_jobs["rtvi-embed"]["metrics_path"] == "/v1/metrics"
assert thor_jobs["rtvi-embed"]["static_configs"] == [{"targets": ["rtvi-embed:8000"]}]
assert thor_jobs["lvs"]["metrics_path"] == "/metrics"
assert thor_jobs["lvs"]["static_configs"] == [
    {"targets": ["host.docker.internal:38111"]}
]

# Route assertions are tied directly to source. Alert Bridge and Phoenix have
# disabled, separate Prometheus listeners, while RT-CV only exposes OTLP
# exporter configuration in this checkout; none may become a guaranteed-down
# static scrape target.
rtvi_vlm_source = (root / "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py").read_text(encoding="utf-8")
rtvi_embed_source = (root / "services/rtvi/rt-embed/src/server/rtvi_embed_server.py").read_text(encoding="utf-8")
lvs_source = (root / "services/video-summarization/src/via_server.py").read_text(encoding="utf-8")
lvs_inventory = json.loads((docker_dir / "thor-local/qualification/api_inventory.json").read_text(encoding="utf-8"))
alert_source = (root / "services/alert/enhance_alert_with_vlm.py").read_text(encoding="utf-8")
alert_compose = yaml.safe_load((docker_dir / "services/alert/compose.yml").read_text(encoding="utf-8"))
rtcv_compose = (docker_dir / "services/rtvi/rtvi-cv/compose.yaml").read_text(encoding="utf-8")
assert 'API_PREFIX = "/v1"' in rtvi_vlm_source and 'f"{API_PREFIX}/metrics"' in rtvi_vlm_source
assert 'API_PREFIX = "/v1"' in rtvi_embed_source and 'f"{API_PREFIX}/metrics"' in rtvi_embed_source
assert 'f"{API_PREFIX}/metrics"' in lvs_source
lvs_surface = next(item for item in lvs_inventory["surfaces"] if item["id"] == "lvs")
assert lvs_surface["substitutions"]["API_PREFIX"] == ""
assert 'os.getenv("PROMETHEUS_PORT", 9081)' in alert_source
assert "start_prometheus_server" in alert_source
assert not any(
    str(item).startswith("PROMETHEUS_METRICS_ENABLED=")
    for item in alert_compose["services"]["alert-bridge"]["environment"]
)
assert "OTEL_METRICS_EXPORTER" in rtcv_compose
assert {"alert-bridge", "rt-cv", "phoenix"}.isdisjoint(thor_jobs)

with (monitoring_dir / "config/grafana-provisioning/datasources/datasource.yml").open(encoding="utf-8") as stream:
    datasource = yaml.safe_load(stream)["datasources"][0]
assert datasource["uid"] == "prometheus"
assert datasource["url"] == "http://prometheus:9090"
assert datasource["isDefault"] is True
assert datasource["editable"] is False

dashboard_path = monitoring_dir / "config/grafana-dashboard/thor-vss-observability.json"
dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
assert dashboard["uid"] == "thor-vss-observability"
assert dashboard["editable"] is False
assert {panel["type"] for panel in dashboard["panels"]} == {"stat", "timeseries"}
for panel in dashboard["panels"]:
    assert panel["datasource"] == {"type": "prometheus", "uid": "prometheus"}
    assert all("|lvs" in target["expr"] for target in panel["targets"])
dashboard_text = dashboard_path.read_text(encoding="utf-8").lower()
assert "http://" not in dashboard_text
assert "https://" not in dashboard_text

environment = os.environ.copy()
environment.update(
    {
        "VSS_REPO_ROOT": str(root),
        "VSS_APPS_DIR": str(docker_dir),
        "VSS_DATA_DIR": str(docker_dir / "data-dir"),
        "MONITORING_BIND_ADDRESS": "127.0.0.1",
        "PROMETHEUS_CONFIG_FILE": str(thor_prometheus_path),
        "PROMETHEUS_PORT": "9090",
        "GRAFANA_PORT": "35000",
        "NODE_EXPORTER_PORT": "19100",
        "CADVISOR_PORT": "18080",
    }
)
command = [
    "docker",
    "compose",
    "--env-file",
    str(docker_dir / "developer-profiles/dev-profile-thor-full/.env"),
    "-f",
    str(docker_dir / "compose.yml"),
    "-f",
    str(docker_dir / "thor-local/compose.yml"),
    "config",
    "--format",
    "json",
]
resolved = json.loads(
    subprocess.run(
        command,
        check=True,
        cwd=docker_dir,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
)
resolved_services = resolved["services"]
assert thor_services <= resolved_services.keys()
assert "dcgm-exporter" not in resolved_services
for service_name in thor_services:
    published = resolved_services[service_name]["ports"][0]
    assert published["host_ip"] == "127.0.0.1", (service_name, published)
    assert resolved_services[service_name]["logging"] == {
        "driver": "local",
        "options": {"max-file": "3", "max-size": "10m"},
    }
assert "prometheus-storage" in resolved["volumes"]
prometheus_config_mount = next(
    volume
    for volume in resolved_services["prometheus"]["volumes"]
    if volume["target"] == "/etc/prometheus/prometheus.yml"
)
assert prometheus_config_mount["source"] == str(thor_prometheus_path)
assert prometheus_config_mount["read_only"] is True

# On an ARM64 runner, any already-staged image must itself be ARM64. Missing
# images are reported, never pulled, so this static test remains offline-safe.
missing_images = []
if platform.machine().lower() in {"aarch64", "arm64"}:
    for service_name in sorted(thor_services):
        image = resolved_services[service_name]["image"]
        inspected = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Architecture}}", image],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if inspected.returncode:
            missing_images.append(image)
            continue
        assert inspected.stdout.strip() in {"arm64", "aarch64"}, (image, inspected.stdout)

print("All Thor observability static contracts passed.")
if missing_images:
    print("SKIP: runtime images are not staged (test never pulls):")
    for image in missing_images:
        print(f"  {image}")
PY
