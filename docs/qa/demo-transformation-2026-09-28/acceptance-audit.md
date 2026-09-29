# Demo goal acceptance audit — September 28

This is an incomplete-goal audit, not a sign-off. It distinguishes demonstrated
behavior from narrow tests and missing proof. The running log contains detailed
changes; this matrix identifies the evidence still needed for the original goal.

| Goal area | Current authoritative evidence | Assessment / remaining proof |
| --- | --- | --- |
| Audience and business story | Research proposal and pending audience question | Not agreed. Warehouse is a candidate, not a user-approved choice. |
| Full UI critique | Primary page audit and D01–D26 findings in running log | Partial. Populated live, incident and analytics flows have not been fully inspected against current real data. |
| Home | Real recording preview, scoped search, current source state | Implemented and sampled. QA source naming and final scenario framing remain unfinished. |
| Explore | Real source-scoped search/playback; selection and answer persistence; refinements; 17 scoped tests | Core recorded path demonstrated. Larger multi-source and multi-clip customer narratives need rehearsal. |
| Live | Disconnected labels from VIOS; focused camera navigation | Offline-state behavior verified. Fresh live frames, overlays and active analysis are not demonstrated. |
| Monitoring | Loading/error/catalog distinctions; frame-gated zone editor; available rule forms | Configuration UI sampled. A real triggered condition, correct candidate/verification state and event delay remain unqualified. |
| Events | Real saved reports; simulated request failure recovery; pagination fixtures | Recorded reports demonstrated. Real incident acknowledge/resolve/reopen and evidence playback need a populated current event. |
| Insights | Evidence-aware empty view; navigation and responsive checks | Empty state verified. Chart accuracy and usefulness against an actual incident series remain unverified. |
| Source management | Current inventory, retained/unavailable previews; form inspection | Actual camera registration/recovery and full upload/analysis-profile paths need current input and bounded runtime testing. |
| Reports | Retained five-second clip, recording labels, offline export tests and browser inspection | Sampled single-clip flow verified. Multi-clip report usability and long export pagination remain open. |
| Local processing proof | Core status and System/admission inspection | Core is running locally. Some services only have process checks; admission telemetry is unknown. No assertion of full readiness. |
| Fast response | Latest rehearsal: 923 ms search, 15.244 s fresh answer | Useful improvement. Single sample, not a percentile; routine latency criterion still needs repeated representative scenarios. |
| Runtime safeguards | Active guard, 48 GiB reserve preserved; before/after 49.68/49.81 GiB | Guard maintained. Endpoint samples do not prove peak memory or sustained ingestion. |
| Industry applicability | Primary-source research file with warehouse/manufacturing/retail/transport mappings | Research complete as proposal. Concrete scenes and model/coverage support must be selected and proven. |
| Isaac Sim scenario | Four configured cameras offline; registered host responds to ping | Host reachability only. Current host identity, version, RTSP path, scene control and reset remain unknown. |
| Final demo rehearsal | Recorded-path receipt through saved-report playback | Partial. No full business/live scenario rehearsal or user audience review yet. |
| Running documentation | Progress log, screenshots, research, presenter runbook, rehearsal receipt | Maintained. Continue updating as evidence changes. |

## Next consequential work

1. Resolve audience/scene details, then select one visually obvious business event
   and agree its intended interpretation. Do not treat a generic semantic match
   as a verified policy violation.
2. Qualify one feed and one workload under the existing runtime procedure. Obtain
   actual live frames before testing event generation. Do not start every service
   to make the readiness display green.
3. Complete incident and populated-analytics flows with that real evidence.
4. Rehearse the integrated story, measuring time to evidence, event delay, fresh
   answer completion and memory behavior. Compare model claims against the video.
5. Review visual hierarchy and scenario wording on the populated app with the
   intended audience. Further generic cosmetic edits cannot substitute for this.

Independent work can continue where findings are concrete, but the full goal
cannot be accepted on recorded playback and unit tests alone.

## Connectivity check in this pass

VIOS `/v1/sensor/status` still reports CameraNotFoundError/offline for IsaacSim
NE, NW, SE and SW, and offline for the traffic source. The QA recording is online.
The registered simulator host `10.88.8.191` answered two ICMP probes (0% loss,
about 0.94 ms). Ping does not identify the device or validate an RTSP endpoint.
No network scan, camera rewrite, remote simulator command or ingestion start
was performed. Current Spark identity/RTSP scene details and audience were
requested from the user.

## Latest inference checkpoint

The [temperature evaluation](temperature-fix-evaluation.md) records 12.005/10.557 s
for the same specific question and 13.031 s for a general description. Parameter
fidelity is fixed; general accuracy remains unqualified. The broader model test
tripped the reserve guard, followed by documented recovery of all 31 core roles.
Use that receipt for current runtime state; earlier reserve snapshots above are
historical.

## Multi-clip checkpoint

A real two-interval API comparison improved from 40.178 to 30.762 seconds after
reducing redundant synthesis. It still misses the pacing target. See the
[two-clip receipt](two-clip-comparison.md); selection UX, multi-source narratives
and live scenarios are not qualified by this bounded API test.

## Progressive delivery checkpoint

[Progressive evidence](progressive-evidence.md) now delivers the first real
inspection at 13.462 s while comparison continues; final result in this sample
arrived at 27.581 s. This improves time to useful evidence but does not qualify
general latency or correctness. A real browser answer still contradicted itself
about placement, leaving accuracy open.
