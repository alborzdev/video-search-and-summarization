# Thor-local API qualification

This directory owns the machine-readable, static API acceptance contract for
the complete Thor-local VSS profile. The default qualification is deliberately
safe to run on an offline operator host: it reads only checked-in files, does
not inspect secrets, does not open sockets, and never starts, stops, or mutates
containers or VSS resources.

Run the contract tier from the repository root:

```bash
deploy/docker/scripts/thor-local.sh qualify --tier contract
```

For machine-readable output:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py \
  --tier contract --json
```

`api_inventory.json` records every REST and MCP surface, direct and public
route exposure, source provenance, release conditions, expected counts, and
reviewed contract differences. `expected/*.json` is the reviewed acceptance
baseline. The qualifier independently re-derives manifests from:

- OpenAPI JSON for Alerts and Video Analytics;
- all seven VIOS Swagger documents;
- Python route decorators for RT-VLM, RT-Embed, and LVS;
- the RT-CV API reference;
- the pinned NAT 1.6.0 route model plus VSS Agent config/source routes; and
- VA/LVS MCP declarations; and
- the VST/VIOS FastMCP gateway's 22 tools and five prompts.

OpenAPI prose such as descriptions and examples is ignored. Its validation
shape, method, path, operation ID, and component definitions are retained.
The VIOS Swagger extractor retains route metadata and a whole-file digest, so
schema changes still fail qualification without requiring PyYAML on an offline
host. VIOS paths are normalized to their deployed `/vst/api/v1/...` form.
Parameter names are normalized separately when finding runtime route
collisions.

MCP manifest schema version 2 records tools and prompts independently. For
FastMCP source, the qualifier parses top-level `@mcp.tool` and `@mcp.prompt`
decorators with Python's AST and hashes the function signature that derives
each input schema. It never imports the server module, so settings and backend
clients cannot create side effects during offline qualification. The complete
source-file hashes continue to protect decorator metadata and handler bodies.

Upstream includes the VST/VIOS MCP Python service and both stdio and
streamable-HTTP entry points but omits it from the released Compose graph.
Thor closes that packaging gap with a checksum-locked Linux/AArch64 wheel
closure, an exact Python base-image digest, a networkless derivative build,
and a read-only, loopback-only Compose service on `VST_MCP_PORT` (8001 by
default). Its direct `/mcp` endpoint is listed in `runtime_inventory.json`;
the static contract still derives all 22 tools and five prompts from source
without importing the service.

## Locally captured live documents

The helper can compare a previously captured local OpenAPI JSON document
without making a network request:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py \
  --live-openapi alerts=/tmp/alerts-openapi.json
```

URLs are intentionally unsupported here. The separate runtime tier below owns
loopback HTTP/MCP collection without weakening this contract tier's offline
guarantee.

## Read-only runtime qualification

`runtime.py` is isolated from the offline qualifier above. Run it only after
the operator has started the Thor-local stack:

```bash
deploy/docker/scripts/thor-local.sh qualify --tier runtime
```

The wrapper supplies the same Thor-local port defaults and environment
overrides as the deployment. Running `runtime.py` directly remains supported
for isolated tests.

It always emits JSON. A readiness response or live OpenAPI contract failure
produces `result: "fail"` and exit 1. A connection refusal, timeout, or other
transport outage produces `result: "unavailable"` and exit 2, making a stopped
stack distinguishable from a broken contract without treating it as a pass.
An OpenAPI endpoint marked optional is skipped only when it returns 404 or 405.
`runtime_inventory.json` defines the health, OpenAPI, MCP, UI, ingress,
VIOS, VIOS MCP, Elasticsearch, Kibana, Phoenix, Logstash, Prometheus, Grafana,
node-exporter, cAdvisor, and the Thor `tegrastats` exporter GET probes and their
default Thor-local ports. A valid port environment variable listed there
overrides its default. The deployment contract requires `TEGRASTATS_PORT=19101`
so the loopback-only exporter and checked-in Prometheus target cannot drift.

The Prometheus target probe is stronger than endpoint reachability: it reads
the bounded `/api/v1/targets` JSON document and requires the exact versioned
Thor job set (`prometheus`, `node-exporter`, `cadvisor`, `rtvi-vlm`,
`rtvi-embed`, `lvs`, and `tegrastats-exporter`) to be present once each with
`health: up`. Its report contains counts and a drift fingerprint, never live
scrape URLs or response bodies. The Grafana tier also requests the provisioned
`thor-vss-observability` dashboard by its checked-in UID.

The host-managed LLM and VLM intentionally bind to Docker's private bridge,
not loopback, so this loopback-only tier does not contact them directly. Use
the separate read-only `deploy/docker/scripts/thor-local.sh model-check`
contract once both local model containers are running.

For tests or a deliberately remapped local port, override an origin explicitly:

```bash
python3 deploy/docker/thor-local/qualification/runtime.py \
  --endpoint agent=http://127.0.0.1:18100
```

Only numeric IPv4/IPv6 loopback HTTP origins are accepted. The qualifier
disables ambient proxies and redirects, issues only GET requests, never calls
Docker or another process, never invokes an MCP tool, and never creates,
updates, or deletes a VSS resource. Error output contains stable categories,
HTTP status codes, counts, and drift fingerprints; response bodies, redirect
locations, raw exceptions, and live route names are not included.

## Updating a reviewed contract

After reviewing a deliberate upstream API change, regenerate expected files:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py --regenerate
git diff -- deploy/docker/thor-local/qualification
python3 deploy/docker/thor-local/qualification/qualify.py
```

Never regenerate merely to make a failure disappear. Review every added,
removed, or changed operation/tool and update `api_inventory.json` counts and
known differences explicitly.
