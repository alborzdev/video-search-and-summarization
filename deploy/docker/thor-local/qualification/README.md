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
- VA/LVS MCP declarations.

OpenAPI prose such as descriptions and examples is ignored. Its validation
shape, method, path, operation ID, and component definitions are retained.
The VIOS Swagger extractor retains route metadata and a whole-file digest, so
schema changes still fail qualification without requiring PyYAML on an offline
host. VIOS paths are normalized to their deployed `/vst/api/v1/...` form.
Parameter names are normalized separately when finding runtime route
collisions.

## Locally captured live documents

The helper can compare a previously captured local OpenAPI JSON document
without making a network request:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py \
  --live-openapi alerts=/tmp/alerts-openapi.json
```

URLs are intentionally unsupported. A later runtime qualification tier can
own loopback HTTP/MCP collection without weakening this contract tier's
offline guarantee.

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
