# Vision Intelligence UI parity

This matrix records how the current CT AI Labs experience maps NVIDIA VSS
capabilities into seven operator workspaces. It is a workflow redesign, not a
tab-for-tab reskin.

| NVIDIA VSS capability | Vision Intelligence location | Disposition | Verified behavior |
| --- | --- | --- | --- |
| Environment overview | **Home** | Added | A backend-derived brief, representative source, all-source question entry, source intelligence grid, and local-edge rail establish current state without inventing activity. |
| Single and multi-camera operations | **Live** | Improved | Responsive source grid, focused media, truthful Live/Replay/Analyzing/Paused state, source-scoped visual questions, analytics layers, Activity, Insights, and History remain in one workspace. |
| Current-camera visual question | **Live → focused source** | Improved | Exact recent retained context is inspected through the one guarded Cosmos lane; results stay source-scoped and admission conflicts are explicit. |
| Source-history GraphRAG | **Live → History** | Activated and redesigned | Timestamped captions build source-scoped history asynchronously. Questions return graph-grounded answers with playable retained-video citations; heavy builds are admission-gated. |
| Alert/event review | **Events** | Redesigned | Confirmed/rejected candidates expose source, time, reasoning, workflow state, evidence actions, filters, and honest empty states. Native Insights replaces customer-facing Kibana. |
| Alert-rule authoring | **Monitoring** | Improved | Rules are listed and managed by source. Semantic and qualified detector templates use a guided dialog; polygon regions work by pointer or keyboard, and live-VLM creation is admission-gated. |
| Natural-language search | **Explore** | Redesigned | All-source/source scope, live/recorded scope, time, status, sorting, pagination, provenance filters, and explicit search/index coverage use the local search API. |
| Search playback and evidence | **Explore → result/evidence** | Improved | Exact bounded same-origin VST MP4s support playback, evidence selection, multi-clip analysis, grounded follow-up, investigations, and standalone local reports. |
| Search by image | **Explore → Play clip → Find similar object** | Improved | The operator selects a real detector/tracker object at an exact frame. Object ID, sensor identity, and timestamp are preserved; no guessed crop or synthetic box is generated. |
| Capability explanation | **Capabilities** | Added | Each visitor-facing workflow names its local services, example input, state, and proof path without exposing low-level tuning controls. |
| Video/source management | **System → Sources** | Improved | Recorded and RTSP inventory, upload, registration, preview, pause/resume, analysis profile, derived-data cleanup, and deletion use VIOS/VST with explicit cleanup scope. |
| Runtime readiness | **System → Edge system** | Improved | Seven service checks, real Thor temperature/power/memory, guarded-workload admission, per-source search/retention state, and the pixels-to-evidence pipeline provide an operator contract rather than a cosmetic health badge. |
| Workload capacity | **System → What Thor can run now** | Added | Stable allow/queue/block decisions cover visual questions, evidence synthesis, live VLM alerts, history builds, calibration, and experimental audio. Agent-owned boundaries prevent bypass of heavy-work admission. |
| Search/index operations | **System → What remains usable as evidence** | Added | Every configured source independently reports indexed/not-indexed/unknown and retained/expired/unavailable state, exact counts and times, and truthful remediation; no synthetic coverage percentage is shown. |
| Durable investigations and reports | **Explore → Create investigation/report** | Improved | Ordered evidence, severity, disposition, notes, timeline, and exact playable citations persist locally without an external report service. |
| Appearance and presentation | Global header | Improved | Accepted CT AI Labs warm-light and graphite-dark themes share the same information hierarchy; both themes have serious/critical WCAG regression coverage. Presentation Mode uses browser fullscreen. |
| Stable navigation | Global shell | Added | `?workspace=` deep links, browser back/forward, all seven desktop destinations, and all seven mobile bottom-navigation destinations stay synchronized. |
| Map | Not shown | Genuinely unavailable | The Thor profile has no approved map service. The UI does not display a dead navigation item. |

## Data integrity rules

- Live, replay, indexed, retained, available, analyzing, paused, offline,
  confirmed, rejected, and health labels come from backend state.
- AI requests and media stay on the Thor runtime endpoints. Recorded fallback
  footage is labeled replay rather than live.
- An unavailable backend produces a loading, empty, offline, unknown, or error
  state instead of fabricated analytics or a guessed percentage.
- Detector-backed profiles enforce their advertised finite source capacity on
  the server, not only in the UI.
- Calibration and local audio remain disabled until this exact Thor workflow is
  qualified. Their presence in admission state is not a claim that they run.

## Intentional tradeshow omissions

- Raw cosine thresholds, `top_k`, index names, and model engineering controls
  stay outside the primary operator workflow.
- Freehand crop is not presented as object search. Visual similarity requires a
  real indexed detector/tracker identity.
- Authentication is deliberately deferred by ADR 0013. The gateway is a
  trusted-LAN surface, not an Internet-facing security boundary.
- Scale-out, multi-node scheduling, calibration, and experimental audio are not
  enabled merely to match a marketing checklist; they require device-specific
  qualification and resource evidence.
