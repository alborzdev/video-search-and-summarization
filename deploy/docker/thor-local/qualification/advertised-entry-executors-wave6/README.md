# Advertised-entry executors: wave six

This isolated package checks exactly eight advertised-entry gaps: all seven
`vios-ui` literals and the `agent-and-mcp-apis` `NAT generate/chat` literal. It
digest-locks the exact 87-entry gap plan, manifest, all five predecessor
inventories (8 + 21 + 23 + 5 + 6 entries), and every source or static evidence
file it reads. These eight cases leave 16 plan entries without a candidate
executor.

The executor performs bounded TypeScript/TSX source assertions, strict JSON
inspection, and exact NAT dependency-lock checks. It does not import or build
the UI, open a browser, render a route, start a service, make an API request,
correlate backend state, invoke Docker, use the network, or create files.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave6/executor.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave6/tests \
  -p 'test_*.py' -v
```

Use `--list` to print exact IDs and repeat `--case <entry-id>` to run a bounded
subset.

## Boundary

Every observation is candidate-only static source/evidence. The dashboard,
sensor/stream management, recording, and media-management source routes are
mounted in the checked-in route table. The live, replay, video-wall, and
Experimental paths are explicitly empty placeholders even though their page
components exist. Wave six records that mismatch and does not claim those
components are mounted or rendered.

The NAT case proves only an exact `nvidia-nat==1.6.0` dependency lock, inherited
NAT route registration in the custom worker, and the checked-in static agent
inventory's generate/chat operations. It does not prove a request, response,
schema response, service readiness, or MCP operation.

All seven `runtime_browser_interaction` oracles and the one
`runtime_api_or_mcp_operation` oracle remain `open_unexecuted`. The optional
Warehouse sample bundle is neither used nor relevant. See
[EVIDENCE.md](EVIDENCE.md) for exact non-claims.
