# Thor VA-MCP runtime and loopback-isolation qualification — 2026-08-10

## Result

PASS. The NVIDIA VSS 3.2.1 Video Analytics MCP service ran on this Thor,
advertised the complete seven-function analytics surface, executed every direct
read-only analytics function plus the VIOS sensor-list function, and was loaded
successfully by the co-resident VSS Agent. A discovered unauthenticated
physical-interface exposure was corrected at the Thor Compose source and the
post-fix service is reachable only on numeric loopback.

This evidence qualifies the runtime represented by the capability-matrix
`api.core.va-mcp-7` entry. It does not claim that the currently empty analytics
indices contain incidents or metrics.

## Runtime identity

- Compose project: `mdx`
- Containers: `vss-va-mcp`, `vss-agent`
- Image: `nvcr.io/nvidia/vss-core/vss-agent:3.2.1`
- Runtime image ID for both containers:
  `sha256:b7f3246aaf355ebf96e91a40b2f0abc5dea7e330e7bf9a7cf726107b560c3ac1`
- VA-MCP server: `NeMo Agent Toolkit MCP` `1.26.0`
- Direct-client protocol requested and negotiated: `2024-11-05`
- Local VA-MCP LLM provider: `vllm`
- Local LLM model: `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8`
- Local LLM endpoint: `http://127.0.0.1:30081`
- Agent endpoint remained healthy at `http://127.0.0.1:8100`.

No credential value or MCP session identifier is retained in this record.

## Two-step MCP session

The qualification followed the required session sequence:

1. `POST /mcp` with JSON-RPC `initialize`; HTTP 200 and a non-empty
   `mcp-session-id` response header were required.
2. Every subsequent `tools/list` and `tools/call` request sent that identifier
   in the `mcp-session-id` request header.

The post-fix `tools/list` receipt SHA-256 was
`0ac7021ec7e1c3594038d5bfea49af906846235f4a6dfdccfbb94e9f43366696`.
The server returned nine tools:

1. `vst_sensor_list`
2. `video_analytics__get_sensor_ids`
3. `video_analytics__get_incident`
4. `video_analytics__get_fov_histogram`
5. `video_analytics__get_average_speeds`
6. `video_analytics__analyze`
7. `video_analytics__get_incidents`
8. `video_analytics__get_places`
9. `react_agent`

The seven `video_analytics__*` functions are the advertised analytics surface;
the VIOS function and ReAct wrapper are additional tools.

## Direct runtime calls

Every direct call returned JSON-RPC success with `isError: false`:

| Tool | Runtime result |
| --- | --- |
| `vst_sensor_list` | `pit-POV`, `sample-sim-jaywalking`, `sample-sim-traffic` |
| `video_analytics__get_sensor_ids` | The same three sensor IDs |
| `video_analytics__get_places` | `{}` |
| `video_analytics__get_incidents` | `{"incidents": [], "has_more": false}` |
| `video_analytics__get_incident` | A deliberately nonexistent ID returned `{}` |
| `video_analytics__get_fov_histogram` | A one-minute `pit-POV` query returned ten six-second buckets and no objects |
| `video_analytics__get_average_speeds` | `{"metrics": []}` |
| `video_analytics__analyze` | `No vehicles detected at pit-POV between 2025-01-01T00:00:00.000Z and 2025-01-01T00:01:00.000Z.` |

Elasticsearch independently reported zero documents in each relevant local
index:

- `mdx-behavior-thor-bootstrap`: 0
- `mdx-raw-thor-bootstrap`: 0
- `mdx-vlm-incidents-2025-01-01`: 0

The empty tool results therefore match the local data boundary; no incident,
metric, place, or object was fabricated to make the test appear populated.

## Agent integration

After recreation, the Agent runtime environment contained
`VIDEO_ANALYSIS_MCP_URL=http://127.0.0.1:9901`. Its startup log recorded:

- configuration of the streamable-HTTP MCP client at
  `http://127.0.0.1:9901/mcp`;
- successful protocol negotiation;
- addition of all nine discovered tools;
- successful initialization of Report Agent Mode 1 with Video Analytics MCP;
- successful Top Agent initialization with 20 regular tools and 3 sub-agents.

`GET http://127.0.0.1:8100/health` and `/docs` both returned HTTP 200 after the
change.

## Security finding and correction

### Before

The released shared Compose command resolved VA-MCP to
`--host 0.0.0.0 --port 9901`, while the Thor Agent resolved its MCP client URL
to `http://0.0.0.0:9901`. The unauthenticated initialize endpoint was reachable
through Thor's physical `wlP1p1s0` address and returned HTTP 200 with a 307-byte
body.

### Source correction

`deploy/docker/thor-local/compose.yml` now overrides only the Thor deployment:

- VA-MCP command bind: `127.0.0.1:9901`
- VA-MCP health probe: `http://127.0.0.1:9901/health`
- VA-MCP service `VSS_AGENT_HOST`: `127.0.0.1`
- Agent `VIDEO_ANALYSIS_MCP_URL`: `http://127.0.0.1:9901`

The shared NVIDIA profiles retain their upstream bind behavior. The Thor
profile test now fails closed if either the server bind or Agent client URL
drifts away from numeric loopback.

### After

- `ss` reported only `127.0.0.1:9901` for VA-MCP.
- A physical-interface initialize request used `--noproxy '*'` and failed with
  curl exit 7 and HTTP `000`.
- A loopback initialize request returned HTTP 200 and the full tool surface.
- A `tools/list` call without a session returned HTTP 400 with JSON-RPC error
  `Bad Request: Missing session ID`.
- `DELETE /mcp` with the live session returned HTTP 200 and an empty body,
  closing the qualification session.

Only `vss-va-mcp` and `vss-agent` were force-recreated. The before/after
container inventory diff showed new IDs for exactly those two names; every
other container name and state remained unchanged. Both replacements reached
Docker health state `healthy`.

## Regression evidence

- `bash deploy/docker/test-scripts/test-dev-profile.sh`:
  **199 passed, 0 failed**.
- `python3 -m unittest discover -s
  deploy/docker/thor-local/qualification/tests -v`, in a temporary clean
  checkout with only this milestone's patch applied: **93 tests passed**.
- The clean-checkout run was necessary because the primary worktree contains a
  deliberately preserved, uncommitted Video Management `.env` change. That
  unrelated line changes the whole-file LVS source digest but is not part of
  this VA-MCP milestone.

The profile-suite LVS assertion was also corrected from the retired MCP 1.23.0
wheel checksum/install sequence to the already committed and runtime-verified
MCP 1.28.1 contract. No LVS runtime code changed in this milestone.

## Cleanup

- The direct MCP session was explicitly deleted.
- No video, stream, incident, analytics document, model, container beyond the
  two replacements, or persistent test asset was created.
- Temporary clean-checkout worktree was removed after its tests passed.
