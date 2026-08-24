# VSS market capability and Thor gap analysis

**Research date:** 2026-08-23  
**Scope:** NVIDIA's current VSS documentation and first-party product
documentation from AWS, Google Cloud, and Microsoft. This is a product and
implementation review, not a performance benchmark or a claim that every
checked-in capability is presently qualified on the target device.

## Executive assessment

The local deployment is already materially beyond a generic video-search demo:
it exposes evidence-grounded semantic and image search, bounded playable clips,
source-scoped caption history, investigation reports, alert-rule management,
and source lifecycle controls. Its clearest differentiation is the ability to
keep video and inference on an AGX Thor in a trusted LAN, rather than sending
the archive to a cloud API.

The best next investments are therefore operational rather than another search
surface: make resource admission and degradation explicit; turn the currently
inactive audio lane into a qualified, searchable capability; make calibrated
multi-camera workflows consumable from the main product; and close the trusted-
LAN-only security boundary before broader access. These recommendations are
ordered later in this document and deliberately distinguish code presence from
runtime proof.

## Market and source-linked capability matrix

All external links below are first-party product documentation. "Advertised"
means that the named vendor documents the capability; it is not a comparative
accuracy, latency, or cost claim.

| Capability | NVIDIA VSS, officially advertised | Relevant first-party alternatives | Product implication for this repository |
| --- | --- | --- | --- |
| Natural-language archive search | [Search workflow](https://docs.nvidia.com/vss/latest/agent-workflow-search.html) documents semantic action/event and attribute search, fusion search, query decomposition, filters, and selected-box search-by-image. | [Azure AI Video Indexer](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-overview) documents deep search over indexed speech, faces, and other insights. [Google Video Intelligence](https://docs.cloud.google.com/video-intelligence/docs/reference/rest/v1/videos/annotate) exposes annotation features rather than an end-user semantic-search product. [Amazon Rekognition Video](https://docs.aws.amazon.com/rekognition/latest/dg/labels-detecting-labels-video.html) returns timestamped label detections asynchronously. | Preserve the existing evidence-first/search-by-object distinction; a plain text search box is not sufficient differentiation. |
| Long-video summaries and reports | [Video Summarization workflow](https://docs.nvidia.com/vss/latest/agent-workflow-lvs.html) advertises long uploaded-video summaries, multi-video reports, timestamped highlights, and experimental live-stream caption/Q&A/report paths. [Summarization microservice](https://docs.nvidia.com/vss/latest/long-video-summarization.html) specifies timestamped events and high-level summaries. | [Azure Video Indexer](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-overview) advertises video/audio summarization and edge or cloud deployment; its [summarization note](https://learn.microsoft.com/en-us/azure/azure-video-indexer/text-summarization-overview) explicitly cautions that summaries are not a replacement for complete review. | Keep every generated conclusion tied to replayable timestamped evidence, particularly for incident use. |
| Live understanding and alerting | [RT-VLM](https://docs.nvidia.com/vss/latest/real-time-vlm.html) documents RTSP captioning, alert generation, sampling control, SSE/Kafka output, and metrics. [Real-time alerts](https://docs.nvidia.com/vss/latest/agent-workflow-rt-alert.html) documents continuous sampling, prompt/invocation configuration, and reports. | Azure Arc's [Video Indexer overview](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-overview) documents real-time edge insights with bounding boxes for live streams. AWS and Google official sources reviewed here describe asynchronous annotation rather than a comparable all-in-one VLM alert workflow. | Surface actual model-lane availability and backlog before enabling rules; never represent a queued or paused source as continuously analyzed. |
| Candidate-alert verification | [VSS alert verification](https://docs.nvidia.com/vss/latest/agent-workflow-alert-verification.html) distinguishes sparse VLM verification of upstream candidate alerts from continuously running VLM alerts and explicitly calls out their different GPU needs. [Alerts microservice](https://docs.nvidia.com/vss/latest/alert-verification-service.html) documents verification, on-demand processing, and persisted incident outcomes. | Cloud services offer detect/index primitives, but the reviewed official cloud pages do not document the same VLM-verdict workflow. This is a scope observation, not a claim that no cloud integration can be built. | This is a differentiated workflow; put confirmed/rejected/unverified state, reasoning, and the exact clip together in the UI. |
| Detection, tracking, and spatial analytics | [RT-CV](https://docs.nvidia.com/vss/latest/object-detection-tracking.html) documents DeepStream-based 2D RT-DETR/Grounding DINO and multi-camera Sparse4D detection/tracking. [Behavior Analytics](https://docs.nvidia.com/vss/latest/behavior-analytics.html) documents tracked-object metadata via Kafka, Redis Streams, or MQTT. | Google documents [object tracking, person detection, labels, faces, OCR, logos, shot change, and speech](https://docs.cloud.google.com/video-intelligence/docs/features?authuser=2&hl=en). Azure documents object/scene/shot detection and customizable live people/vehicle detection in its [feature inventory](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-overview). | VSS's local multi-camera/spatial path is valuable, but it needs an operator-safe calibration and capacity story before being foregrounded. |
| Video, image, and text embeddings | [RTVI-Embed](https://docs.nvidia.com/vss/latest/real-time-embedding.html) documents video/image/text embeddings for files and RTSP, chunk/overlap controls, SSE/Kafka, health, Prometheus, and OpenTelemetry. | Azure and Google documents focus on indexed insight/annotation results; the cited product pages do not promise a self-hosted multimodal embedding microservice. | Continue to show the user result provenance and source/time filters rather than embedding internals. |
| Video I/O, retention, and replay | [VSS introduction](https://docs.nvidia.com/vss/latest/index.html) lists VIOS plus VST sensor, live/replay/record/proxy/storage APIs. | Azure supports uploaded and live video in cloud and Arc modes; see its [overview](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-overview). AWS label detection assumes video stored in S3 in the cited workflow. | The repository's exact bounded evidence clips are a strong response to cloud-style timestamp links; retention disclosure remains essential. |
| Multi-camera calibration | [AutoMagicCalib](https://docs.nvidia.com/vss/latest/auto-calibration.html) advertises a guided multi-camera workflow that estimates intrinsics/extrinsics from naturally moving objects, including archived video, plus AMC and model-based VGGT approaches. | The reviewed cloud product pages advertise edge/live object insights, but not this NVIDIA-style calibration workflow. | Treat it as a separately admitted specialist workflow, not an automatic background feature on a single Thor. |
| Audio, transcription, and accessibility | VSS's current RT-VLM documentation describes video captions and does not establish universal local ASR/transcription for the default edge lane. | Azure advertises transcription, translation, and more than 50 languages in cloud Video Indexer; [insights documentation](https://learn.microsoft.com/en-us/azure/azure-video-indexer/insights-overview) also lists audio effects, entities, keywords, topics, and transcript-derived emotion. Google documents [speech transcription](https://docs.cloud.google.com/video-intelligence/docs/feature-speech-transcription). | Audio is the most visible parity opportunity, but the local model, ASR, codec, memory, and evidence requirements make it a high-risk Thor feature. |
| Deployment and security model | [VSS introduction](https://docs.nvidia.com/vss/latest/index.html) describes modular microservices, MCP, isolated-network/on-premises/edge deployment including AGX Thor. Its [secure deployment recipe](https://docs.nvidia.com/vss/latest/secure-deployment.html) says to use a trusted, isolated network and supply external authentication, TLS, rate limiting, and monitoring. | Azure explicitly supports cloud and Azure Arc edge deployment; Google and AWS cited APIs are managed cloud services. | The local/air-gapped narrative is credible only when access controls are made as visible and enforceable as local inference. |

## Existing implementation evidence

This table records evidence found in the checkout on 2026-08-23. A document or
source file demonstrates intent/implementation; it does **not** by itself prove
current live behavior. The existing acceptance record is useful operational
evidence, but should be rerun when the currently dirty worktree is deployed.

| Area | Status from review | Evidence in this checkout |
| --- | --- | --- |
| Operator semantic search, filters, visual similarity, and exact clip playback | Implemented and documented as accepted | [docs/vision-intelligence-parity.md](../vision-intelligence-parity.md); [docs/vision-intelligence-acceptance.md](../vision-intelligence-acceptance.md); [Investigate workspace](../../services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/InvestigateWorkspace.tsx); [evidence route](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/evidence.ts); [evidence media route](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/evidence-media.ts). |
| Evidence selection, analysis, persistent investigations, and report export | Implemented UI/API seam | [EvidenceAnalysisPanel](../../services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/EvidenceAnalysisPanel.tsx); [evidence-analysis API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/evidence-analysis.ts); [investigations API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/investigations.ts). |
| Source-scoped caption history and GraphRAG | Implemented local extension; prior acceptance document says it was exercised | [video-history API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/video-history.ts); [VideoHistoryPanel](../../services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/VideoHistoryPanel.tsx); [Thor LVS derivative](../../deploy/docker/thor-local/Dockerfile.video-summarization). |
| Alert incident review and live rule management | Implemented UI/API seam | [Activity/Insights workspace](../../services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/ActivityInsightsWorkspace.tsx); [AlertRulesWorkspace](../../services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/AlertRulesWorkspace.tsx); [live-alert API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/live-alert-rules.ts); [reservation control](../../services/ui/apps/nv-metropolis-bp-vss-ui/server/vision/liveAlertReservation.ts). |
| Source lifecycle and analytic profiles | Implemented UI/API seam | [source-analysis API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/source-analysis.ts); [source-intelligence API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/source-intelligence.ts); [analysis profiles API](../../services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/analysis-profiles.ts). |
| Thor-safe caption and alert sampling | Implemented fixed resource profile | [liveCaptionProfile.ts](../../services/ui/apps/nv-metropolis-bp-vss-ui/server/vision/liveCaptionProfile.ts) limits continuous work to 30-second chunks, four frames, 512 px inputs, and bounded tokens; it disables audio in the alert profile. |
| Local resource telemetry and operational guidance | Implemented | [Thor README](../../deploy/docker/thor-local/README.md); [tegrastats exporter](../../deploy/docker/thor-local/observability/tegrastats_exporter.py); [exporter tests](../../deploy/docker/thor-local/observability/tests/test_tegrastats_exporter.py). |
| AutoMagicCalib | Separate Thor qualification lane, including a documented prior run; not established as a main-app workflow | [AMC lane README](../../deploy/docker/thor-local/auto-calibration/README.md); [AMC compose overlay](../../deploy/docker/thor-local/auto-calibration/compose.yml). |
| Native audio understanding | Deliberately inactive/candidate-only, not a default feature | [audio lane README](../../deploy/docker/thor-local/audio/README.md); the normal Thor profile sets `enable_audio: false` in [liveCaptionProfile.ts](../../services/ui/apps/nv-metropolis-bp-vss-ui/server/vision/liveCaptionProfile.ts). |
| Scale-out alert/VIOS profiles | Configuration-only; explicitly not runtime evidence | [scaling README](../../deploy/docker/thor-local/scaling/README.md). |
| External authentication/TLS boundary | Not a product capability in the inspected UI; VSS documentation places it at infrastructure layer | [ADR 0013](../adr/0013-defer-authentication-from-the-tradeshow-overhaul.md); [Thor README](../../deploy/docker/thor-local/README.md); NVIDIA's [secure-deployment recipe](https://docs.nvidia.com/vss/latest/secure-deployment.html). |

## High-value gaps, in recommended order

Impact, effort, and resource risk are relative to the present single-AGX-Thor
deployment. "Resource risk" includes unified-memory pressure, GPU contention,
thermal margin, storage, and unqualified multi-service co-residency.

| Priority | Gap and expected value | Impact / effort / resource risk | Proposed UX exposure | Backend dependencies and gates |
| --- | --- | --- | --- | --- |
| 1 | **Workload admission, queueing, and graceful degradation.** The product already reserves a local VLM lane in individual flows, but operators need one truthful answer to “what can run now?” before starting captions, a live rule, evidence analysis, summaries, or calibration. | High / Medium / High | A persistent “Compute plan” panel: active GPU lanes, estimated queue, admission decision, current reserve, and one-click safe choices (pause captions, run offline, retry later). Every expensive action shows its scope and cannot silently compete. | A central scheduler/admission API consuming tegrastats, process/container health, source state, disk headroom, and per-job cost profiles. Start with conservative static limits, then measure. Existing foundations: `liveAlertReservation.ts`, `liveCaptionProfile.ts`, and the tegrastats exporter. |
| 2 | **Qualified local audio + transcript search.** Azure/Google make speech-derived search and accessibility an expected comparison point. The repository has a carefully bounded but inactive Omni candidate lane; there is no basis to advertise it yet. | High / High / Very high | An opt-in “Audio intelligence (experimental)” source profile, with audio-on/off badge, transcript/timestamp evidence, and a separate “not available on this device right now” state. Do not merge audio and visual claims in one unmarked answer. | Complete the audio lane's stated qualification: immutable model snapshot, codec image, memory gate, `/v1/models` audio support, known-speech fixture, audio-disabled control, LVS and alert tests. Per-chunk transcription specifically needs a verified ASR path; the lane README says native Omni alone is insufficient for that claim. |
| 3 | **Main-product calibration-to-multi-camera workflow.** VSS officially promotes AMC and multi-camera 3D; this checkout has an isolated, documented Thor lane rather than a main UI journey. | High / Medium-high / High | Add a “Calibrate camera group” wizard under Manage: source synchronization checks, footage-quality preflight, explicit run estimate, results/errors, approval, and a clear link from calibrated group to a 3D/warehouse workspace. Keep it inaccessible while normal inference is active unless admission approves it. | AMC service/VIOS integration, durable project state, result import, calibration schema validation, and a scheduler lock that makes it mutually exclusive with CV-heavy/3D lanes. Use the existing `thor-auto-calibration` preflight and only represent base AMC versus optional VGGT accurately. |
| 4 | **Secure multi-user ingress.** The current trusted-LAN assumption is appropriate for a demo, but it is a deployment limitation for real shared operation. NVIDIA explicitly says VSS connections need external authentication, TLS, rate limiting, and monitoring. | High / Medium / Low GPU, medium operational | A signed-in operator identity, role-aware controls (viewer/investigator/admin), source/retention policy disclosure, and an “access boundary healthy” readiness item. Keep external-facing choices out of the primary investigation path. | Auth proxy/identity provider, TLS termination, RBAC enforcement for UI/API/MCP, audit logs, rate limits, and network segmentation. Validate that internal VSS ports remain unreachable from untrusted networks. This is security engineering, not a cosmetic login screen. |
| 5 | **Search/index coverage and quality operations.** Cloud products lead with familiar indexed “insights”; an evidence-grounded local product should instead expose what times/sources were actually indexed, model/profile, missing ranges, and a human review feedback loop. | Medium-high / Medium / Low-medium | Add a compact “coverage & confidence” drawer to each search: indexed time coverage, analysis profile, retrieval/critic state, gaps, and a result feedback action that never alters evidence. | Indexing/caption/alert lifecycle events, source state, and a small immutable feedback/audit store. Ensure a feedback label is never treated as ground truth or used for automatic model changes. |
| 6 | **Qualified scale-out topology.** VSS's multi-stream premise is compelling, but the repository says the current alert and VIOS scale profiles are configuration-only. | Medium-high / High / Very high | An admin-only capacity planner rather than a “scale” toggle: camera count, requested profiles, required disk/GPU budget, and “requires separate benchmark” status. | Live qualification of VIOS ownership/failover, Kafka partitions, replica routing, cleanup, alert worker semantics, and measured Thor capacity. Do not enable normal Compose scaling on the single device based only on static config validation. |

## Proposed experience: one operator flow

```text
Add source / camera group
        |
        v
Readiness + capacity admission ---- insufficient ----> truthful wait/pause/offline option
        |
        v
Choose analysis profile: search | captions | alerts | calibrated group | audio (experimental)
        |
        v
Evidence-first Investigate workspace
  search -> exact clip -> select evidence -> observed facts / report
        |
        v
Activity / History retains source, time, model profile, coverage, and access audit
```

The key design rule is that every action states its resource class and evidence
scope. A result should not look live when it is replayed, not look fully indexed
when it is partial, and not look audio-grounded when audio was unavailable.

## Jetson AGX Thor cautions

1. **Treat memory as unified and shared.** GPU model weights/KV cache, CUDA
   allocations, CPU services, filesystem cache, browser playback, and multiple
   containers draw from the same system memory budget. GPU utilization alone is
   not an admission signal. NVIDIA's VSS prerequisites prescribe a persistent
   cache cleaner for Thor-class systems and maximum power/clocks for the
   platform; see [prerequisites](https://docs.nvidia.com/vss/latest/prerequisites.html).

2. **Do not co-reside heavy lanes by default.** The repository deliberately
   bounds captioning and alerts, describes AMC/warehouse/3D work as separate
   lanes, and marks fixed-topology scaling as unqualified. Keep RT-CV, RT-Embed,
   VLM, LLM, LVS, alert verification, video transcode/replay, and calibration
   under a measured concurrency plan, not only per-container limits.

3. **Audio is a special memory cliff.** The candidate 30B Omni lane has an
   80-GiB `MemAvailable` admission floor, fixed 20% reserve, and one sequence
   in [the local audio contract](../../deploy/docker/thor-local/audio/README.md).
   That is a safety gate, not a supported throughput or quality claim. Leave it
   off in the default demo until an end-to-end run proves the intended model,
   codec, ASR behavior, and co-residency.

4. **Throttle continuous VLM work to wall-clock reality.** The checked-in
   profile chooses four frames over each 30-second window because a shorter
   producer interval can build an unbounded queue on a single Thor. Preserve
   cancellation, per-source queue visibility, and recovery after a failed job.

5. **Disk and retention are part of accelerator reliability.** Raw recordings,
   exact evidence clips, embeddings, Elasticsearch/Neo4j state, report assets,
   container logs, and staged models compete for local storage. The user-facing
   cleanup policy must say which derived artifacts disappear and which remain;
   never let clip creation or report export bypass a retention ceiling.

6. **Watch thermals and power over the entire workload.** A short successful
   inference is insufficient evidence for continuous alerts or multi-camera
   operation. Use the existing tegrastats exporter to record temperature,
   power, memory, and GPU readings alongside source count, model profile, and
   queue latency; test at expected ambient temperature and target duration.

7. **Maintain the network boundary.** NVIDIA says this VSS release is intended
   for a trusted isolated network and notes non-TLS component paths in its
   [known limitations](https://docs.nvidia.com/vss/latest/Known-Limitations.html).
   Local inference does not by itself make the system safe to expose publicly.

## Evidence standards for the next release

- Mark capability state as **implemented**, **qualified on this Thor build**,
  **experimental**, or **planned**; do not collapse those states into a single
  feature checkmark.
- Test each new profile with an owned fixture plus a failure/cancellation path,
  then record model identity, source count, resolution, sampling, duration,
  memory/thermal telemetry, disk delta, and exact artifact retention behavior.
- Keep generated reports and answers source/time scoped with direct playable
  citations. For alerts, retain original candidate, VLM verdict, rationale, and
  verification time.
- For cloud comparisons, state deployment and modality scope rather than
  asserting unmeasured accuracy, price, privacy, or throughput differences.

## Sources

- NVIDIA: [VSS introduction](https://docs.nvidia.com/vss/latest/index.html),
  [prerequisites](https://docs.nvidia.com/vss/latest/prerequisites.html),
  [search workflow](https://docs.nvidia.com/vss/latest/agent-workflow-search.html),
  [video summarization workflow](https://docs.nvidia.com/vss/latest/agent-workflow-lvs.html),
  [RT-VLM](https://docs.nvidia.com/vss/latest/real-time-vlm.html),
  [RTVI-Embed](https://docs.nvidia.com/vss/latest/real-time-embedding.html),
  [RT-CV](https://docs.nvidia.com/vss/latest/object-detection-tracking.html),
  [alert verification](https://docs.nvidia.com/vss/latest/agent-workflow-alert-verification.html),
  [real-time alerts](https://docs.nvidia.com/vss/latest/agent-workflow-rt-alert.html),
  [alerts microservice](https://docs.nvidia.com/vss/latest/alert-verification-service.html),
  [AutoMagicCalib](https://docs.nvidia.com/vss/latest/auto-calibration.html),
  [edge deployment](https://docs.nvidia.com/vss/latest/edge-deployment.html),
  [secure deployment](https://docs.nvidia.com/vss/latest/secure-deployment.html),
  and [known limitations](https://docs.nvidia.com/vss/latest/Known-Limitations.html).
- Microsoft: [Azure AI Video Indexer overview](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-overview),
  [insights overview](https://learn.microsoft.com/en-us/azure/azure-video-indexer/insights-overview),
  [textual summarization](https://learn.microsoft.com/en-us/azure/azure-video-indexer/text-summarization-overview).
- Google Cloud: [Video Intelligence features](https://docs.cloud.google.com/video-intelligence/docs/features?authuser=2&hl=en),
  [videos.annotate API](https://docs.cloud.google.com/video-intelligence/docs/reference/rest/v1/videos/annotate),
  [speech transcription](https://docs.cloud.google.com/video-intelligence/docs/feature-speech-transcription).
- AWS: [Amazon Rekognition Video label detection](https://docs.aws.amazon.com/rekognition/latest/dg/labels-detecting-labels-video.html).

