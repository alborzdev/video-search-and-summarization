# Thor service inventory and acceptance plan — 2026-09-09

Read-only inventory of existing `mdx` containers and checked-in Thor overlays. Existing-container dependency labels can differ from current Compose source after edits; resolve the candidate graph again before launch. This inventory does not certify current service health or memory fit.

Default profiles are `bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d,bp_developer_thor_traffic_perception_2d`. The two RT-CV workers serve different warehouse/search and traffic paths, not accidental duplicate instances. Optional MV3DT, sparse4D, legacy calibration, audio/Omni, OpenClaw and NVStreamer lanes are not needed for this 2D full graph. Auto-calibration backend/UI were present historically but are optional setup tools; existing calibration permits the main app to operate without these model services. Monitoring services belong to the full profile even though core inference can work without their UIs.

## Existing service map

`—` means no Docker health check/dependency label, not that functional dependencies are absent. Endpoint probes are container-local unless otherwise marked. Source for actual probes: `docker inspect` read on this date; the read-only doctor also checks application endpoints.

| Compose service | Container | Class | Declared dependency labels | Docker readiness probe |
|---|---|---|---|---|
| alert-bridge | vss-alert-bridge | long-running | — | `` |
| broker-health-check | vss-broker-health-check | one-shot, exit 0 | — | `` |
| cadvisor | mdx-cadvisor-1 | long-running | — | `/usr/bin/healthcheck.sh` |
| centralizedb | vss-vios-postgres | long-running | — | `pg_isready -h /var/run/postgresql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1` |
| elasticsearch | elasticsearch | long-running | — | `curl -fsS 'http://localhost:9200/_cluster/health?local=false&wait_for_status=yellow&wait_for_events=normal&timeout=5s' \| grep -q '"timed_out"[[:space:]]*:[[:space:]]*false'` |
| elasticsearch-init-container | vss-elasticsearch-init | one-shot, exit 0 | elasticsearch:service_healthy:false | `` |
| evidence-clip | mdx-evidence-clip-1 | long-running | — | `python -c import urllib.request; urllib.request.urlopen('http://127.0.0.1:8098/health', timeout=2).read()` |
| grafana | grafana | long-running | — | `curl --fail --silent --show-error http://127.0.0.1:3000/api/health` |
| graph-db | vss-graph-db | long-running | — | `wget --spider --quiet http://127.0.0.1:7474/` |
| kafka | kafka | long-running | — | `kafka-broker-api-versions --bootstrap-server 127.0.0.1:9092` |
| kafka-topic-init-container | vss-kafka-topics | one-shot, exit 0 | kafka:service_healthy:false | `` |
| kibana | kibana | long-running | elasticsearch:service_healthy:false | `curl -f http://localhost:5601/kibana/api/status` |
| kibana-init-container-thor-full | vss-kibana-init-thor-full | one-shot, exit 0 | kibana:service_healthy:false | `` |
| logstash | logstash | long-running | elasticsearch-init-container:service_completed_successfully:false,broker-health-check:service_completed_successfully:false | `bash -ec 'exec 3<>/dev/tcp/127.0.0.1/9600; printf "GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" >&3; read -r status <&3; [[ "${status}" == HTTP/*" 200 "* ]]'` |
| lvs-server | vss-lvs | long-running | rtvi-vlm:service_healthy:false,graph-db:service_healthy:false | `curl -f http://localhost:38111/v1/ready` |
| nemotron-edge | vss-nemotron-edge-4b | long-running | rtvi-vlm:service_healthy:false | `python3 -c import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:30081/v1/models',timeout=5).status == 200 else 1)` |
| node-exporter | mdx-node-exporter-1 | long-running | — | `` |
| perception-2d-fusion | vss-rtvi-cv | long-running | — | `/usr/local/bin/rtvi-cv-healthcheck` |
| perception-2d-init | vss-rtvi-cv-init | one-shot, exit 0 | — | `` |
| perception-2d-smartcity-thor | vss-rtvi-cv-traffic | long-running | — | `/usr/local/bin/rtvi-cv-healthcheck` |
| phoenix | phoenix | long-running | — | `/usr/bin/python3.13 -c import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:6006/readyz', timeout=3).getcode() == 200 else sys.exit(1)` |
| prometheus | prometheus | long-running | — | `/bin/promtool query instant http://127.0.0.1:9090 up` |
| redis | redis | long-running | — | `redis-cli -h 127.0.0.1 ping` |
| rtvi-embed | vss-rtvi-embed | long-running | — | `curl -f http://localhost:8000/v1/ready` |
| rtvi-vlm | vss-rtvi-vlm | long-running | broker-health-check:service_completed_successfully:false,kafka:service_healthy:false | `curl -f http://localhost:8000/v1/health/ready` |
| sdr-streamprocessing | vss-vios-sdr | long-running | — | `bash -ec 'exec 3<>/dev/tcp/127.0.0.1/${PORT}; printf "GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" >&3; read -r status <&3; [[ "${status}" == HTTP/*" 200 "* ]]'` |
| sdr-streamprocessing-init | mdx-sdr-streamprocessing-init-1 | one-shot, exit 0 | redis:service_healthy:false | `` |
| sensor-ms | vss-vios-sensor | long-running | centralizedb:service_healthy:false | `bash -ec 'exec 3<>/dev/tcp/127.0.0.1/${HTTP_PORT:-30000}'` |
| streamprocessing-ms | vss-vios-streamprocessing | long-running | — | `bash -ec 'exec 3<>/dev/tcp/127.0.0.1/${HTTP_PORT:-30001}'` |
| tegrastats-exporter | tegrastats-exporter | long-running | — | `/usr/local/bin/python3 -c import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://172.17.0.1:19101/readyz', timeout=3).getcode() == 200 else sys.exit(1)` |
| vios-mcp | vss-vios-mcp | long-running | vst-ingress:service_healthy:false | `python -c import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',8001,timeout=3); c.request('GET','/mcp',headers={'Accept':'application/json'}); sys.exit(0 if c.getresponse().status in (200,400,406…` |
| vss-agent | vss-agent | long-running | vst-ingress:service_healthy:false,rtvi-embed:service_healthy:false,lvs-server:service_healthy:false,nemotron-edge:service_healthy:false,vss-va-mcp:service_healthy:false,rtvi-vlm:service_healthy:false,phoenix:service_healthy:false | `/usr/local/bin/python3 -c import urllib.request; import sys; sys.exit(0 if urllib.request.urlopen( 'http://0.0.0.0:8100/health', timeout=5).status == 200 else 1)` |
| vss-auto-calibration | vss-auto-calibration | optional calibration | — | `curl -f http://localhost:8010/v1/ready` |
| vss-auto-calibration-ui | vss-auto-calibration-ui | optional calibration | — | `` |
| vss-behavior-analytics-thor-candidates | vss-behavior-analytics-thor-candidates | long-running | broker-health-check:service_completed_successfully:false | `` |
| vss-haproxy-ingress | vss-haproxy-ingress | long-running | — | `` |
| vss-search-analytics-2d-fusion | vss-behavior-analytics | long-running | broker-health-check:service_completed_successfully:false | `` |
| vss-ui | vss-agent-ui | long-running | — | `` |
| vss-va-mcp | vss-va-mcp | long-running | — | `/usr/local/bin/python3 -c import urllib.request; import sys; sys.exit(0 if urllib.request.urlopen( 'http://127.0.0.1:9901/health', timeout=5).status == 200 else 1)` |
| vss-video-analytics-api-fusion | vss-video-analytics-api | long-running | elasticsearch-init-container:service_completed_successfully:false,broker-health-check:service_completed_successfully:false | `` |
| vst-ingress | vss-vios-ingress | long-running | — | `bash -ec 'exec 3<>/dev/tcp/127.0.0.1/${VST_INGRESS_HTTP_PORT:-30888}'` |

Observed inventory: **41 containers: 33 full-profile long-running services, 6 one-shot jobs, 2 optional calibration services.**

## Bring-up ordering and hidden workload triggers

1. Redis, PostgreSQL (`centralizedb`), Kafka, Elasticsearch, Neo4j. Run/check their existing one-shot topic/index/group initialization. An exited-zero initializer is successful; do not keep it running to satisfy a service-count objective.
2. Logstash, behavior analytics ordinary and candidate consumers, Video Analytics API and MCP, observability. Functional Kafka/Elasticsearch connectivity must be checked even for services lacking Docker dependencies/health checks.
3. VIOS sensor → streamprocessing → ingress, then SDR and VIOS MCP. `sensor-ms` depends on PostgreSQL; SDR dispatches sensor events from Redis to streamprocessing. Confirm no restored streams before GPU memory measurements. Current SDR has `WDM_INITIALIZE_FROM_VST=false`, `WDM_PRELOAD_WORKLOAD=""`, `WDM_CLEAR_DATA_WL=true`, and restart-on-add-failure false; it still consumes Redis events and has a workload-cache key, so verify actual catalog/state instead of assuming idle from these flags alone.
4. Isolated bounded models and RT-Embed, then each CV worker. The existing Nemotron dependency/PID1 memory gate deliberately blocks co-residence; a newly reviewed experiment path must preserve the old gate.
5. LVS consumes shared RT-VLM and LLM endpoints; it should not instantiate a second Cosmos model. Agent consumes all dependencies, Phoenix, VIOS, Embed, LVS, VA MCP, and LLM/VLM. Start Agent last; then UI, evidence-clip and ingress. Alert Bridge belongs after its analytics/VLM dependencies even though its container labels omit them.

Agent's `auto_resume_registered_live_sources=false` is critical: its `rtsp_ingest.py` background reconciler otherwise reconstructs desired-active Embed/CV resources. The official overlay mounts the patched module into the existing image. The Alert Bridge exact overlay disables `ALERT_ALWAYS_ON_ENABLED`; absent that it can replay persisted camera rules. GPU services have restart disabled in the exact overlay. The generic doctor/launcher still reflects the old exact-model lock and may intentionally reject an experimental replacement topology.

Sources: [Thor overlay](../../deploy/docker/thor-local/compose.yml), [exact overlay](../../deploy/docker/thor-local/official-edge/compose.yml), [launcher/doctor](../../deploy/docker/scripts/thor-local.sh), [Agent reconciler](../../services/agent/src/vss_agents/api/rtsp_ingest.py).

## Memory controls with the largest likely payoff

- **RT-Embed:** Thor source comments report auto batch64 allocating ~20 GiB activations. Current `RTVI_EMBED_BATCH_SIZE` default8 feeds `VLM_BATCH_SIZE`; isolated1/2/4 trials are worthwhile. Do not infer linear savings or throughput from batch alone. Its sender queues are bounded (default1024) but active stream frames and video decode add workload-dependent memory. Verify produced embeddings, Kafka delivery and indexed search, not only `/v1/ready`.
- **RT-VLM:** explicit cache bytes, one sequence/process, eager, 4096 prefill tokens, 16K context; possible isolated3GiB KV trial discussed in the research note. The full base compose also exposes media-cache and result cleanup options. Confirm actual installed wrapper mounts before assuming an environment control reaches the engine.
- **CPU infrastructure:** Kafka heap defaults1GiB via `THOR_LOCAL_KAFKA_HEAP_OPTS`; Elasticsearch/Logstash source sets max1GiB, initial256MiB each; Logstash pipeline workers already1. Neo4j initial256MiB/max512MiB heap +256MiB page cache. These are heap/cache controls, not whole-process limits. Avoid tightening first when larger model allocations remain unmeasured.
- **Video:** measure each RT-CV worker and each active VIOS decoder independently; bound active source count, resolution and retained chunk/frame queues. Merely starting APIs may leave their largest decoder/tracker allocations deferred until the first source. Evidence-clip uses a disk-backed cache and transient muxing. LVS also needs repeated-job checks for retained chat/session contexts.
- Existing Docker configs show no hard memory cap for most containers. SDR is300MiB; CV initializer6GiB. Cgroup memory and host MemAvailable overlap, and GPU/kernel allocations need host-wide observation. Do not sum Docker usage plus GPU usage as independent memory.

Sources: [RT-Embed override](../../deploy/docker/thor-local/compose.yml), [infra config](../../deploy/docker/services/infra/compose.yml), [Embed sender/stream code](../../services/rtvi/rt-embed/src/server/rtvi_stream_handler.py), [research](../../docs/research/2026-09-09-thor-vss-memory-runtime.md).

## Existing acceptance tools and what they really prove

Run these only after the candidate topology is admitted. Old source hashes/model locks may intentionally reject a tuned graph. Use separate new output receipts or adapt a fresh harness; never relabel historical receipts as current evidence.

| Stage | Existing tool or operation | Acceptance and limitations |
|---|---|---|
| Basic readiness | `deploy/docker/scripts/thor-local.sh doctor`; `qualify --tier runtime`; `model-check` | Doctor checks Agent8100 `/health`, UI, VA MCP9901 `/health`, LVS38111 `/v1/ready`, SDR4003 `/healthz`, Embed `/v1/ready`, VLM `/v1/health/ready`, both CV DS-ready routes. Model-check historically tests LLM chat and four-image VLM request; not proof of Agent tool selection. |
| Real embeddings | `python3 deploy/docker/thor-local/qualification/rt-embed-current-runtime/execute.py --ack I_ACK_RT_EMBED_CURRENT_RUNTIME_AND_EXACT_REVERSIBLE_CLEANUP` | Real text/uploaded-file/data-URL/live-RTSP vectors and cleanup, up to900s/50requests, three temporary helpers. Version/source locks may reject changes. |
| Search retrieval | In `qualification/search-semantic-current-runtime-successor`: `python3 executor.py execute-http --run-id thorsearch20260909a --ack I_ACK_SEARCH_CURRENT_RUNTIME_AND_EXACT_INDEX_CLEANUP` | Uses already recorded video plus owned synthetic behavior/raw docs. Does not ingest fresh video or call Agent. New full-path check must upload/embed new owned footage, wait for real vector-index visibility, query it, and remove only owned objects. |
| File captions + summary | `python3 deploy/docker/thor-local/qualification/lvs-file-caption-summary-runtime-successor/harness.py --ack I_ACK_ONE_OWNED_LVS_FILE_AND_TWO_LOCAL_CAPTION_SUMMARY_REQUESTS --output <new-receipt.json>` | Existing10s fixture, fresh captions and `/v1/summarize`, checks beginning/end events, chronology, no invented forklift, and restores file/graph baselines. Repeat several times while recording memory after each completion. |
| VLM live stream | `python3 deploy/docker/thor-local/qualification/rt-vlm-stream-apis-runtime-successor/harness.py --ack I_ACK_ONE_LOCAL_RTSP_PUBLISHER_AND_TWO_OWNED_RT_VLM_STREAMS` | Disposable local publisher, plural original `/v1/streams/*` and singular CV-compatible `/v1/stream/*`, exact cleanup. For the minimal fit trial use just one bounded source; add the second API-family validation later. |
| Real Agent tools | Fresh Agent `/generate` request through current API/UI schema; inspect actual tool trace and final answer | Historical `ui-global-chat-sidebar-runtime-successor` explicitly does **not** call `/generate`; neither does search semantic qualifier. Ask for a named owned video's evidence and confirm the expected search/video tool result is consumed, not merely a fluent model reply. |
| Whole app live path | Add one owned RTSP source via Agent API; verify VIOS capture, CV tracking, Embed vector/index, live caption/alert as applicable; explicitly stop/remove it | The model-only live harness does not prove the complete Agent reconciliation/media/search path. Keep one source, bounded duration, capture pre/post catalogs and verify cleanup. |

The August12 demo-ready receipt is explicitly superseded by August30 watchdog failures. It provides fixtures and expected semantics, not permission to reuse the old startup command or evidence of present reliability.

For every stage log baseline, load peak, first-request peak, repeated-request plateau, stop/reclaim state, swap/PSI, kernel warnings, and persistent D-state processes. Success requires all selected long-running services available together and representative workloads completing with measured spare RAM. A healthy idle graph alone does not meet the objective.
