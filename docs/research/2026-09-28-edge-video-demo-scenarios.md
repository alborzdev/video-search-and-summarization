# Customer scenarios for a local edge-video demonstration

Research date: September 28, 2026. Status: **proposal awaiting audience and
presentation alignment**. No app, simulator, or runtime changes were made for
this research. External capabilities below are documented capabilities, not
proof that this Thor deployment currently supports them.

This note complements the [August capability comparison](2026-08-23-vss-market-capability-gap-analysis.md)
and [running progress record](../demo-transformation-progress.md). It does not
repeat the vendor comparison or recommend its production-oriented investments.
The accepted [ADR 0005](../adr/0005-one-general-application-across-operational-scenarios.md)
calls for one general application across scenarios. The recommendation here is
one strong presentation story within that application, not separate industry
interfaces or a return to superseded scenario-switching architecture.

## Source facts that matter to the story

- NVIDIA describes VSS as modular video-search, summarization, and analytics
  reference architectures, including edge/on-premises deployment. This provides
  architectural context; runtime locality must still be checked on this device.
  [VSS 3.2 introduction](https://docs.nvidia.com/vss/3.2.0/index.html).
- VSS distinguishes verification of upstream candidate alerts from continuous
  VLM monitoring. A candidate incident and an AI-reviewed incident should
  therefore be separate visible states, rather than one ambiguous “alert.”
  [Alert verification workflow](https://docs.nvidia.com/vss/3.2.0/agent-workflow-alert-verification.html).
- VSS search supports semantic and visual retrieval workflows. Retrieving
  relevant footage is a distinct capability from generating an explanation;
  the presenter can show evidence before requesting a fresh model answer.
  [Search workflow](https://docs.nvidia.com/vss/3.2.0/agent-workflow-search.html).
- NVIDIA's behavior-analytics source describes tracked-object metadata,
  calibration, trajectories, regions, tripwires, and incident processing. These
  are possible building blocks, not a guarantee that a requested rule or object
  class works in the local configuration.
  [Behavior analytics README](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/blob/main/services/analytics/behavior-analytics/README.md).
- Isaac Sim documents cameras and rendered RGB output, including warehouse
  examples. That makes a controlled visual scenario plausible, but does not
  establish the user's installed scene, assets, camera placement, or speed.
  [Camera sensors, version 6.0.1](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/sensors/isaacsim_sensors_camera.html).
- Native scene-camera RTSP is documented through `isaacsim.streaming.rtsp` and
  `RTSPCameraHelper`; the 6.0 release notes also list the extension. Confirm the
  installed Spark version before assuming this path exists. Desktop WebRTC
  streaming and a scene-camera RTSP feed are different integration surfaces.
  [Camera RTSP tutorial, version 6.1](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/digital_twin/rtsp_camera_streaming.html),
  [6.0 release notes](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/overview/release_notes.html).

## Industry relevance and proposed visible scenarios

The business motivations below come from primary sources. All proposed scenes,
app journeys, and feasibility rankings are this research's recommendations.
They are not claims that these organizations use this app.

| Audience / primary-source motivation | Business question and visible scene | Proposed app journey | Repeatable simulation feasibility | Dependency and claim boundary |
| --- | --- | --- | --- | --- |
| Warehouse and logistics. DHL describes computer vision for asset/facility visibility, vehicle movements, and operational review. [DHL Computer Vision](https://www.dhl.com/nl-en/home/innovation-in-logistics/logistics-trend-radar/computer-vision.html) | “What blocked this aisle, and when did it clear?” A conspicuous pallet enters a marked passage, remains, then moves away. Optional forklift approaches and stops. | Watch scene → candidate event → exact replay → find earlier similar footage → attach evidence to a concise review. | **Best first candidate:** fixed camera, large visible prop, scripted placement/removal, simple reset. Warehouse assets are documented; actual asset and script availability remains unknown. | Need the appropriate object/rule implementation or a qualified bounded VLM check. Do not pretend generic person/vehicle tracking automatically detects a stationary pallet obstruction. A marked image region does not prove measured physical clearance. |
| Manufacturing. BMW describes AI-assisted visual quality checks in production. [BMW production](https://www.bmwgroup.com/en/company/production.html) | “When did material stop reaching this station?” A clearly visible tote stops at a handoff while another station continues. Optional later extension: conspicuous missing component. | Watch station → review dwell/flow event → retrieve before/after → explain only visible changes. | **Moderate:** conveyor or scripted tote motion; simpler than realistic fine-defect inspection. Requires matching assets and controllable timing. | Dwell needs stable detection/tracking and threshold configuration. Root cause, downtime attribution, and defect acceptance require process context or specialized models; a VLM description is not process diagnosis. |
| Retail and service operations. NVIDIA documents occupancy, queue, dwell, and line-crossing analytics. [Retail Store Analytics](https://www.nvidia.com/en-eu/ai-data-science/ai-workflows/retail-store-analytics/) | “Where is a queue building?” Several actors gather within a checkout region, then disperse. | Live region → count/trend with scope → relevant replay → compare another interval. | **Moderate to high effort:** credible people animation, placement, occlusion, and store assets. Recorded, permitted example footage may be a better initial extension. | Queue semantics need configuration beyond raw person count. Do not claim identity, intent, purchases, conversion, or loss prevention from occupancy evidence. |
| Transportation and yards. USDOT identifies video incident detection and queue detection as relevant ITS applications. [ITS use cases](https://www.transportation.gov/grants/ss4a/ITS-use-cases) | “Which approach is backing up?” Vehicles accumulate in one region while an adjacent path remains clear. Prefer a private-yard scene for reuse of industrial assets. | Traffic overview → region/vehicle evidence → replay buildup → search for similar episodes. | **Moderate:** scripted vehicle movement in a yard is simpler than a credible road network. Existing traffic footage could demonstrate retrieval first. | Need vehicle detection, stable tracks, meaningful region definitions, and calibrated geometry before physical speed/distance claims. Do not infer crashes or guaranteed early warning from generic congestion. |

**Recommendation:** choose warehouse flow interruption as the first story if the
user has no stronger audience preference. The event is legible without a long
explanation, links live observation to historical evidence, and avoids needing
fine defect recognition or realistic crowds. A person/forklift interaction is a
visually stronger second scenario only after detection, timing, and viewpoint
are proven. Do not label ordinary apparent proximity a measured “near miss.”

## Proposed five-minute presenter journey

This is an editorial target, not a measured performance result or an approved
implementation plan.

| Time | Presenter action | What the visitor should understand | Required proof before using it |
| --- | --- | --- | --- |
| 0:00–0:30 | Open a genuinely playable warehouse scene; identify the camera and Jetson. | “These are ordinary video feeds; intelligence happens here.” | Actual frame freshness, source label, confirmed inference location. Label simulator origin explicitly. |
| 0:30–1:15 | Trigger the scripted obstruction, or open a clearly labeled previous run while a fresh run proceeds. | “The system brings a relevant change to my attention.” | Measured event timing, active analysis state, correct rule and candidate status. No fabricated alert or unmarked replay. |
| 1:15–2:00 | Open the event's short clip, with source and timestamp. | “I can check what the system saw.” | Playable bounded evidence, correct temporal association, no invented verdict. |
| 2:00–3:00 | Ask a specific, footage-supported question such as “Show the pallet entering this aisle.” | “I can find moments without scrubbing hours of video.” | Qualified index coverage and reproducible retrieval. Avoid suggesting all camera history is searchable. |
| 3:00–4:15 | Compare before/after; request one bounded explanation if the lane is available. | “The explanation stays tied to visible evidence.” | Measured fresh inference latency; evidence references; honest inability to conclude when needed. |
| 4:15–5:00 | Save/export the reviewed evidence and briefly show local processing status. | “This becomes an actionable review, on the device.” | Persistence/export verified; real local model routing; any external dependencies disclosed. No automatic physical intervention claim. |

Do not spend the opening explaining service names, rule setup, or calibration.
Keep those available for technical follow-up. Business-value wording should be
“find the relevant moment,” “review the change,” and “share the evidence,” not
unmeasured savings, prevented incidents, or generic claims of autonomy.

## Making the presentation fast without hiding work

Recommended UX/performance acceptance targets, **not current measurements**:

- Navigation and a clear acknowledgement should feel immediate; target under
  one second for visible feedback and under two seconds to playable prepared
  evidence after selection, then measure on the real device/network.
- Show available retrieval results before optional narrative generation.
  Measure retrieval-to-first-useful-result separately from answer completion.
- Keep the core five-minute path usable without synchronous long reports.
  A fresh explanation should have a measured bounded scope and cancellable
  progress. If routine 30+ second generation remains, it belongs outside the
  core path until improved; a spinner or token animation does not fix it.
- Pre-indexing real footage is legitimate. Label “previous recorded run” and
  “previously generated analysis” where applicable; never imply it is a fresh
  event or a fresh model response. Keep an honestly labeled replay available
  when the live source or compute lane is unavailable.
- Measure capture→candidate event, event→review-ready clip,
  query→retrieval evidence, question→first useful content, and final completion.
  Record cold and warm behavior over repeated runs. Avoid a single best-case
  number or claiming the user sees a result before it actually renders.

## Simulator handoff and qualification checklist

Before implementation, obtain audience/format alignment and Spark access or an
operator arrangement. Then establish installed Isaac Sim version, scene path,
RTSP endpoint(s), available props/actors, camera positions, and reset ownership.
Do not assume an SDK upgrade is necessary or authorized just because newer docs
show a convenient feature.

A useful scene package should contain a scene version, deterministic trigger and
reset, camera naming, expected event interval, a normal control run, and a short
recorded reference run. Keep simulator ground truth separate from app inference:
it can judge detection quality, but must not secretly drive supposedly visual
alerts. Verify video timestamps and capture-to-wall-clock alignment before
scoring latency; simulation-time timing alone is not user-visible latency.

Start with one camera and one event under the existing runtime admission rules.
The progress record says live ingestion is paused and sustained ingestion is
unqualified; preserve the active 48 GiB diagnostic guard. Do not increase
concurrency, lower the guard, or promise a camera count based on NVIDIA's generic
capability descriptions. A second camera, continuous VLM, and calibrated 3D are
separate qualification steps, not prerequisites for an effective first story.

## Remaining evidence needed

1. User-approved primary audience and presentation length.
2. Spark version/scene/access and actual stream availability.
3. Complete current app audit and identification of a playable, indexed example.
4. Proven local object/rule coverage for the chosen incident.
5. Repeated timing measurements and a complete live-to-evidence rehearsal.
6. Verified local inference routing before making an offline/local-only claim.

Research outcome: the strongest demo is a short **notice → inspect → find →
explain → share** story with real footage and clear provenance. Broader industry
examples should reuse this journey and explain what changes in the footage and
rules. They should not multiply navigation surfaces or imply unqualified model
capabilities.
