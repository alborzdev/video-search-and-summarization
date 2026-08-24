#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

python3 - "${repo_root}" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1])
docker_dir = root / "deploy/docker"
thor_dir = docker_dir / "thor-local"

inventory = json.loads(
    (thor_dir / "qualification/runtime_inventory.json").read_text(encoding="utf-8")
)
services = {service["id"]: service for service in inventory["services"]}
assert len(services) == 23
assert sum(len(service["probes"]) for service in services.values()) == 34
assert services["vios-sdr"] == {
    "id": "vios-sdr",
    "port_env": "SDR_STREAMPROCESSING_PORT",
    "default_port": 4003,
    "probes": [
        {
            "id": "health",
            "kind": "health",
            "method": "GET",
            "path": "/healthz",
            "expected_status": [200],
        }
    ],
}
assert services["vios-mcp"] == {
    "id": "vios-mcp",
    "port_env": "VST_MCP_PORT",
    "default_port": 8001,
    "probes": [
        {
            "id": "transport",
            "kind": "mcp",
            "mode": "http",
            "method": "GET",
            "path": "/mcp",
            "expected_status": [200, 400, 406],
        }
    ],
}
assert services["kibana"]["probes"] == [
    {
        "id": "status",
        "kind": "health",
        "method": "GET",
        "path": "/kibana/api/status",
        "expected_status": [200],
    }
]
assert services["phoenix"]["probes"][0]["path"] == "/readyz"
assert services["logstash"]["probes"][0]["path"] == "/"

expected_jobs = {
    "alert-bridge",
    "prometheus",
    "cadvisor",
    "node-exporter",
    "tegrastats-exporter",
    "rtvi-vlm",
    "rtvi-embed",
    "lvs",
}
assert services["alerts-prometheus"] == {
    "id": "alerts-prometheus",
    "port_env": "ALERT_PROMETHEUS_PORT",
    "default_port": 9081,
    "probes": [
        {
            "id": "metrics",
            "kind": "health",
            "method": "GET",
            "path": "/metrics",
            "expected_status": [200],
        }
    ],
}
behavior_probe = next(
    probe
    for probe in services["video-analytics"]["probes"]
    if probe["id"] == "behavior-empty-store"
)
assert behavior_probe["path"] == "/behavior"
assert behavior_probe["query"] == {
    "sensorId": "thor-qualification-no-such-sensor",
    "fromTimestamp": "2026-01-01T00:00:00.000Z",
    "toTimestamp": "2026-01-01T00:00:01.000Z",
}
target_probe = next(
    probe
    for probe in services["prometheus"]["probes"]
    if probe["kind"] == "prometheus-targets"
)
assert target_probe["path"] == "/api/v1/targets"
assert set(target_probe["expected_jobs"]) == expected_jobs
assert any(
    probe["path"] == "/api/dashboards/uid/thor-vss-observability"
    for probe in services["grafana"]["probes"]
)

with (thor_dir / "observability/prometheus.yml").open(encoding="utf-8") as stream:
    prometheus = yaml.safe_load(stream)
assert {job["job_name"] for job in prometheus["scrape_configs"]} == expected_jobs
assert "remote_write" not in prometheus
assert "remote_read" not in prometheus

logstash_config = yaml.safe_load(
    (thor_dir / "infra/logstash.yml").read_text(encoding="utf-8")
)
assert logstash_config["api.http.host"] == "127.0.0.1"
assert logstash_config["api.http.port"] == 9600
kibana_config = yaml.safe_load(
    (
        docker_dir / "services/infra/elk/kibana/configs/kibana.yml"
    ).read_text(encoding="utf-8")
)
assert kibana_config["telemetry.optIn"] is False
assert kibana_config["telemetry.allowChangingOptInStatus"] is False
assert kibana_config["telemetry.tracing.enabled"] is False
assert kibana_config["telemetry.metrics.enabled"] is False
assert kibana_config["newsfeed.enabled"] is False
assert kibana_config["xpack.fleet.isAirGapped"] is True
kibana_init = (
    docker_dir
    / "developer-profiles/dev-profile-thor-full/kibana-dashboard/init-scripts/kibana-import-dashboards.sh"
).read_text(encoding="utf-8")
assert "ensure_dashboard_index mdx-raw-thor-bootstrap" in kibana_init
assert "ensure_dashboard_index mdx-behavior-thor-bootstrap" in kibana_init
assert '\"timestamp\":{\"type\":\"date\"}' in kibana_init
assert '\"end\":{\"type\":\"date\"}' in kibana_init
assert 'objects.confidence' in kibana_init
assert 'objects.id.keyword' in kibana_init
assert '\"confidence\":{\"type\":\"float\"}' in kibana_init
assert '\"number_of_shards\":1' in kibana_init

template_creation = (
    docker_dir
    / "services/infra/elk/elasticsearch/init-scripts/elasticsearch-template-creation.sh"
).read_text(encoding="utf-8")
assert template_creation.count('\"confidence\": { \"type\": \"float\" }') == 2
assert template_creation.count('\"keyword\": { \"type\": \"keyword\", \"ignore_above\": 256 }') >= 4
assert 'create_index_template "mdx-road-network-template"' in template_creation
assert 'create_index_template "mdx-usd-assets-template"' in template_creation
for field in (
    "roadNetwork.intersections.segments.start.lat",
    "roadNetwork.intersections.segments.end.lng",
    "roadNetwork.intersections.segments.points.alt",
):
    assert field in template_creation
for field in (
    "usdAssets.assets.bbox.dimension.x",
    "usdAssets.assets.bbox.dimension.y",
    "usdAssets.assets.bbox.dimension.z",
):
    assert field in template_creation

road_network_service = (
    root
    / "services/analytics/video-analytics-api/src/web-api-core/Services/RoadNetwork.js"
).read_text(encoding="utf-8")
usd_assets_service = (
    root
    / "services/analytics/video-analytics-api/src/web-api-core/Services/UsdAssets.js"
).read_text(encoding="utf-8")
assert road_network_service.count('"roadNetwork.intersections.segments.') == 7
assert '"intersections.segments.start.lat"' not in road_network_service
assert usd_assets_service.count('"usdAssets.assets.bbox.dimension.') == 3
assert '"assets.bbox.dimension.x"' not in usd_assets_service
environment = os.environ.copy()
environment.update(
    {
        "VSS_REPO_ROOT": str(root),
        "VSS_APPS_DIR": str(docker_dir),
        "VSS_DATA_DIR": str(docker_dir / "data-dir"),
        "COMPOSE_PROFILES": "bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d",
        "KIBANA_PORT": "5601",
        "PHOENIX_HOST": "127.0.0.1",
        "PHOENIX_PORT": "6006",
        "LOGSTASH_API_PORT": "9600",
        "ALERT_PROMETHEUS_PORT": "9081",
        "TEGRASTATS_PORT": "19101",
        "VST_MCP_PORT": "8001",
        "MONITORING_BIND_ADDRESS": "127.0.0.1",
        # The versioned profile intentionally carries no database secret.
        # Supply a test-only value so Compose can resolve the static graph.
        "GRAPH_DB_PASSWORD": "thor-runtime-infrastructure-test-only",
        "PROMETHEUS_CONFIG_FILE": str(
            thor_dir / "observability/prometheus.yml"
        ),
    }
)
resolved = json.loads(
    subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(docker_dir / "developer-profiles/dev-profile-thor-full/.env"),
            "-f",
            str(docker_dir / "compose.yml"),
            "-f",
            str(thor_dir / "compose.yml"),
            "config",
            "--format",
            "json",
        ],
        check=True,
        cwd=docker_dir,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
)
resolved_services = resolved["services"]
for key, value in {
    "cluster.routing.allocation.disk.watermark.low": "15gb",
    "cluster.routing.allocation.disk.watermark.high": "12gb",
    "cluster.routing.allocation.disk.watermark.flood_stage": "10gb",
}.items():
    assert resolved_services["elasticsearch"]["environment"][key] == value
assert resolved_services["alert-bridge"]["environment"][
    "PROMETHEUS_METRICS_ENABLED"
] == "true"
assert resolved_services["alert-bridge"]["environment"]["PROMETHEUS_PORT"] == "9081"
vios_mcp = resolved_services["vios-mcp"]
assert vios_mcp["image"] == "cti-vss-vios-mcp:thor-local"
assert vios_mcp["network_mode"] == "host"
assert vios_mcp["read_only"] is True
assert vios_mcp["cap_drop"] == ["ALL"]
assert vios_mcp["security_opt"] == ["no-new-privileges:true"]
assert vios_mcp["environment"] == {
    "MCP_GATEWAY_ALLOW_ALL_HOSTS": "false",
    "MCP_GATEWAY_CPP_API_BASE_URL": "http://127.0.0.1:30888/vst",
    "MCP_GATEWAY_SERVER_HOST": "127.0.0.1",
    "MCP_GATEWAY_SERVER_PORT": "8001",
}
assert vios_mcp["depends_on"]["vst-ingress"] == {
    "condition": "service_healthy",
    "required": True,
}
assert vios_mcp["command"] == [
    "--transport",
    "http",
    "--host",
    "127.0.0.1",
    "--port",
    "8001",
]
assert "/mcp" in vios_mcp["healthcheck"]["test"][-1]
for name in ("kibana", "phoenix", "logstash"):
    assert name in resolved_services, (name, sorted(resolved_services))

kibana_mount = next(
    mount
    for mount in resolved_services["kibana"]["volumes"]
    if mount["target"] == "/usr/share/kibana/config/kibana.yml"
)
assert kibana_mount["source"] == str(
    docker_dir / "services/infra/elk/kibana/configs/kibana.yml"
)
assert kibana_mount["read_only"] is True
assert resolved_services["vss-ui"]["environment"][
    "DASHBOARD_KIBANA_INTERNAL_URL"
] == "http://127.0.0.1:5601/kibana"

phoenix = resolved_services["phoenix"]
assert phoenix["network_mode"] == "host"
assert "ports" not in phoenix
for key, value in {
    "PHOENIX_HOST": "127.0.0.1",
    "PHOENIX_PORT": "6006",
    "PHOENIX_TELEMETRY_ENABLED": "false",
    "PHOENIX_ALLOW_EXTERNAL_RESOURCES": "false",
    "PHOENIX_ENABLE_PROMETHEUS": "false",
}.items():
    assert phoenix["environment"][key] == value
assert "/readyz" in phoenix["healthcheck"]["test"][-1]

logstash = resolved_services["logstash"]
logstash_mount = next(
    mount
    for mount in logstash["volumes"]
    if mount["target"] == "/usr/share/logstash/config/logstash.yml"
)
assert logstash_mount["source"] == str(thor_dir / "infra/logstash.yml")
assert logstash_mount["read_only"] is True
assert "127.0.0.1/9600" in logstash["healthcheck"]["test"][-1]

haproxy = resolved_services["vss-haproxy-ingress"]["environment"]
assert haproxy["PHOENIX_HOST"] == "127.0.0.1"
assert haproxy["VSS_PUBLIC_HOST"] == "<HOST_IP>"
assert resolved_services["vss-haproxy-ingress"]["network_mode"] == "host"
assert "ports" not in resolved_services["vss-haproxy-ingress"]
assert resolved_services["vss-agent"]["environment"]["PHOENIX_ENDPOINT"] == (
    "http://127.0.0.1:6006"
)
assert resolved_services["vss-agent"]["depends_on"]["phoenix"] == {
    "condition": "service_healthy",
    "required": True,
}
assert resolved_services["rtvi-vlm"]["depends_on"]["kafka"] == {
    "condition": "service_healthy",
    "required": True,
}
assert resolved_services["rtvi-vlm"]["entrypoint"] == [
    "python3",
    "/usr/local/bin/thor-startup-gate.py",
    "--tcp",
    "host.docker.internal:9092",
    "--",
]
assert resolved_services["rtvi-vlm"]["command"] == [
    "/opt/nvidia/rtvi/start_rtvi_vlm.sh"
]

# The shared HAProxy file keeps its original non-Thor behavior: without the
# two new variables, both backends inherit HOST_IP rather than loopback.
shared_environment = os.environ.copy()
for key in ("PHOENIX_HOST",):
    shared_environment.pop(key, None)
shared_environment.update(
    {
        "COMPOSE_PROFILES": "bp_developer_base_2d",
        "HOST_IP": "192.0.2.10",
        "EXTERNAL_IP": "192.0.2.10",
        "VSS_PUBLIC_HOST": "192.0.2.10",
        "VSS_PUBLIC_PORT": "7777",
    }
)
shared = json.loads(
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(docker_dir / "services/infra/haproxy/compose.yml"),
            "config",
            "--format",
            "json",
        ],
        check=True,
        cwd=docker_dir,
        env=shared_environment,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
)
shared_haproxy = shared["services"]["vss-haproxy-ingress"]["environment"]
assert shared_haproxy["PHOENIX_HOST"] == "192.0.2.10"

template = (
    docker_dir / "services/infra/haproxy/haproxy.cfg.template"
).read_text(encoding="utf-8")
assert 'server s1 "${HOST_IP}:${KIBANA_PORT}" check' in template
assert 'server s1 "${PHOENIX_HOST}:${PHOENIX_PORT}" check' in template

print("All Thor runtime-infrastructure static contracts passed.")
PY
