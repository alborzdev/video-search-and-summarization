# LVS semantic NAT Agent session successor

This additive package implements the maximal safe concrete NAT Agent subset of
the selected `runtime.agent.lvs-profile` semantic row. It does not edit either
predecessor, bind the frozen selected row, or claim full LVS executor readiness.

The default command is inert. An authorized run uses two direct numeric-loopback
RFC 6455 connections to the deployed Agent `/websocket` route. The built-in
client opens the socket directly, offers no extensions, uses no environment
proxy, and accepts only an HTTP 101 upgrade (never a redirect). Every inbound
message must carry the exact expected conversation ID. HITL replies echo the
server's exact `thread_id` and `parent_id` and also carry the conversation ID.

## Concrete semantic subset

A successful run proves five predecessor actions through the production Agent
transport:

1. Agent A requests one report for the first preprovisioned VST sensor. It
   supplies the first scenario, event list, object list, and confirmation over
   four ordered HITL interactions. The completed turn must contain the sensor,
   exact first values, a `report_agent` intermediate observation, and exactly
   one response-derived Markdown/PDF pair.
2. The same conversation requests two videos in one `report_agent` call. Each
   HITL popup must show Agent A's first values as `CURRENTLY SET`; the executor
   replaces them with the exact latest values. Completion must contain both
   distinct sensors, the latest values, and exactly two response-derived
   Markdown/PDF pairs.
3. A third Agent A report turn must expose the latest scenario as
   `CURRENTLY SET` and no longer expose the first scenario. The executor then
   sends `/cancel`, so this state probe creates no report.
4. Agent B uses a separately derived WebSocket session and conversation ID.
   Its first scenario popup must show `DEFAULT` and neither Agent A prompt. It
   is also cancelled before report generation.

The passing envelope is exactly 34 application requests/actions: two WebSocket
upgrades, fourteen outbound WebSocket messages, and eighteen exact artifact
HTTP requests. Inbound JSON messages are separately bounded per wait; protocol
ping/pong/close control frames are not application requests.

## Ownership and cleanup

The manifest requires two distinct safe sensor names, two distinct media
SHA-256 identities, durations strictly above the source-locked 60-second LVS
routing threshold, the run ID on both descriptors, and explicit operator
attestations for ownership, VST registration, and duration. This is an honest
preprovisioned-fixture boundary: the Agent surface does not independently read
back a media digest or duration for a VST sensor.

Only strict `vss_report_<safe-sensor>_YYYYMMDD_HHMMSS.{md,pdf}` paths returned
after an exact `system_intermediate_message` naming `report_agent` and in a
subsequent `system_response_message` can enter the cleanup ledger. HITL
`system_interaction_message` text is never an ownership source, even when it
contains a syntactically valid old report URL. On success this is exactly three
same-stem pairs. The executor reads every exact key, requires Markdown to be
valid UTF-8 and PDF content to start with `%PDF-`, deletes every exact key in
reverse response order, then requires HTTP 404 for every key. Cleanup also runs
after later semantic failure. It never attempts a namespace, recursive,
fixture, stream, or unrelated-resource delete, and it does not claim
preexisting absence.

The receipt includes only hashes, sizes, status codes, bounded counters, and
coverage flags. It omits raw WebSocket payloads, prompts, sensor names, URLs,
session/conversation/resource IDs, and the acknowledgement.

## Honest residual boundary

The exact five-tool declaration is source-locked across the LVS config and
the `report_agent` → `video_report_gen` binding. It is not runtime-discovered:
the deployed NAT WebSocket exposes conversation execution but no tool-catalog
list method. The successor also does not prove direct execution of all five
tools, local dependency/image/model identity, VST sensor-to-byte digest
readback, live caption Kafka/Logstash delivery, CA-RAG retrieval, disconnect
cancellation/quiescence, or complete unrelated Agent state restoration.

Consequently `executor_ready=false`, `promotion_eligible=false`, the selected
row remains `open_unexecuted`, and this package emits only a nonpromoting
candidate receipt.

## Safe commands

The plan and focused tests perform no runtime I/O:

```bash
python3 deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/executor.py plan
pytest -q deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/tests/test_executor.py
```

Future live execution requires an absolute reviewed manifest and the exact
acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/executor.py execute-agent-session \
  --manifest /absolute/reviewed/lvs-agent-session-manifest.json \
  --acknowledgement I_ACK_LVS_AGENT_SESSION_RUNTIME_AND_EXACT_REPORT_CLEANUP
```

The CLI rejects a wrong acknowledgement before reading the user-supplied
manifest path. The programmatic executor may read only its trusted static
contract, schemas, and source locks to compile the inert plan before the same
authorization check; it validates no caller manifest and opens no transport
until authorization succeeds.

No live execution was performed while building this package.
