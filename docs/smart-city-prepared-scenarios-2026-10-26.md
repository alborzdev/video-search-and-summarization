# Prepared Smart City scenarios — October 26, 2026

Status: implementation deployed and all five native/host flows, both cancellations and controlled preflight refusal checked live. The camera cover is verified. Camera analytics limits and a separate intermittent duplicate capture-metadata failure remain documented below. Earlier intersection receipts are a historical baseline, not validation of these changes.

## Intended operator flow

Choose a story, select **Prepare**, wait for **Ready**, then select **Play**. Preparation puts existing loaded actors at reviewed route and native navigation points and selects a coherent signal phase. The useful action should start within a few seconds of Play. Design targets are short 30–60 second presentations where native travel permits; these are not measured promises. Completion releases actor holds, restores normal programs and signal/arrival schedules, and resumes normal traffic without a manual reset. Cancel and failure use the same bounded cleanup.

The five stories are demand, a northbound queue, an East pedestrian crossing, a curbside obstruction and a South crossing obstruction. Operational detections and measurements still come only from camera images. A script receipt is never an AI completion.

## Implementation slices

- Native preparation: valid route state for pooled vehicles, native Fabric-aware teleport and navigation for loaded people, coherent owned signal phases, finite ready/play/recovery states.
- Analytics boundary: suppress preparation evidence, reset both tracker stages in place, clear transient journeys/trails/joins and start a fresh measured run. Retain prior history under its actual scope. Keep exact native AU clock checks and monotonic RTSP capture.
- Operator controls: explicit Prepare and Play, clear recovery status, event instructions and existing camera/map/Insights layout.
- Integration: inspect the current installation, deploy focused changes, exercise all stories plus cancel/failure, and save actual timing and camera evidence.

## Preserved constraints

One existing Isaac instance, two native 960×540 cameras, RF-DETR Medium FP16, local NvDCF analytics and optional guarded MV3DT person hints. Keep the memory guard and saved reserve, calibration, 19 rules, mobility settings, eight tracker pins, all original assets/media/backups and strict native capture-clock proof. No continuous indexing, new stack, installs, commits, publishing or resumed overnight heartbeat.

Stopped-vehicle evidence still needs four observed seconds; curb dwell needs eight. A native pedestrian crossing can complete while camera gaps over one second prevent an AI completion. Queue membership and clearance can remain incomplete. These limits must remain visible in the new results.

## Baseline inspection

The existing scene, native worker, gateway and isolated production UI were running. The latest old scenario was cancelled with normal flow restored. The worker image is `4e6b73d1…`; UI image is `1d94d035…`. Saved Spark reserve is 20 GiB and the active guard reported about 40 GiB available. The Thor 10 GiB selection is separate and unchanged. The working copies have extensive prior edits; no cleanup or reset of those edits is part of this work.

See [baseline receipt](qa/smart-city-prepared-2026-10-26/baseline.json). New source checks, deployment identities, measurements and limits will be recorded below as work proceeds.

## Preparation visibility

The camera pair and map are covered by an opaque **Preparing scene…** panel immediately before the Prepare request is sent. The existing streams remain mounted and running underneath. Reveal requires both the native scene and fresh tracking boundary to report Ready. Cancellation, an unknown response, and recovery keep the cover until readiness is established. Preview pixels and map snapshots also reject a previous analytics/tracking epoch, including when the underlying RTSP session did not change.

## Source checks and first live observation

The hardened worker compiled in a bounded CPU-only container using the existing local image. No packages or models were installed. Candidate image: `sha256:11019c98ba9bd1085c367b2e0b9f83fbaab0664c14023c0156d5546875f83737`; worker source SHA256: `2401bc272f32a760730da52210e239696561227edd9ce44d5f13356608b0d0f7`. Only the local profile image field changed; all eight tracker/calibration pins stayed identical. The isolated 7782 UI uses source-mounted hot reload with the previous production image retained for rollback.

CPU validation: 295 gateway tests; native serialized reset, capture-clock and staged-tracking checks; 18 focused prepared native controls; 740 traffic checks and 52 people checks. UI TypeScript and affected controls/frame/scope suites passed (reported suite counts overlap). Host transaction and controller checks passed before the later maintenance-recovery addition.

First live queue preparation took **0.850935 seconds** natively. The host observer first saw combined Ready about **3.5 seconds** after it first saw the new preparation. Both tracker stages acknowledged the reset. Source sessions stayed unchanged, clocks stayed monotonic, and preparation emitted no operational tracks/metrics. Twenty exact preview envelopes were checked. The browser screenshot confirms that camera/map repositioning was covered.

This first run did **not** reach Play: the user paused VSS detections in another chat while Ready. The owned test hold was cancelled; native normal motion was verified **0.542362 seconds** after release, with eight native people and 28 vehicle pool slots retained. Analytics correctly remained closed because the paused cameras could not provide recovery frames. The user subsequently authorized resuming detections in this chat. Initial resume returned an RTSP 454 session error; the ordinary Agent resume retry restored both live sources. The failure and interrupted evidence are retained.

The observer’s original `queue-first/summary.json` field named `native` contains the host-decorated scenario response; it is not a direct native status snapshot. The observer source now calls this field `sceneControl`. Direct native restoration evidence is recorded separately in `deployment-and-interruption.json` and native logs. A native movement proof means at least one actor moved after release, not that every walker completed a normal route.

Warm native source installation preserves actors/timeline/cameras but retires the previous scenario object. Apply it only after the host analytics boundary has returned to normal. The host now supports recovery from a previously proven released run whose native controller has returned to idle. It requires the saved exact run/token/scenario terminal receipt and current inactive, restored, unowned idle state; it never commands a replacement controller. The final host/controller checks passed: 37 tests, including 25 host transaction subtests.

Evidence: [first queue observation](qa/smart-city-prepared-2026-10-26/queue-first/summary.json), [preparation cover](qa/smart-city-prepared-2026-10-26/queue-first/preparing-cover.png), [deployment/interruption receipt](qa/smart-city-prepared-2026-10-26/deployment-and-interruption.json), [strict-clock/reset receipt](qa/smart-city-2026-10-26/prepared-scenario-boundary-interrupted-live.json).

## First playback checks and observed limits

These observations precede the final queue-clearance and reset-drain changes. They are preserved as evidence, not silently replaced by later runs.

| Story | Native preparation | Play to native motion | Play to native normal | Camera evidence |
| --- | ---: | ---: | ---: | --- |
| Queue | 0.777 s | 2.135 s | 26.336 s | 60 exact previews; queue reached two objects / 9.389 m, but still two objects at scope close |
| East pedestrian | 0.742 s | 1.888 s | 32.147 s | 64 exact previews; waiting and crossing seen; zero completed / one incomplete camera journey |
| Curb obstruction | 0.701 s | 1.847 s | 16.434 s | 36 exact previews; persistent stopped vehicle and 16.644 s dwell; no completed camera departure before scope close |
| South crossing | 0.737 s | No Play | Preparation failed safely | Strict capture-clock rejection stopped the worker; the owned scene was released and recovery completed after ordinary Agent resume |

The native East pedestrian task succeeded at its destination under coherent WALK. This does not change the incomplete camera journey. Camera anchor motion was separately observed about two seconds after Running for queue/pedestrian, and about fourteen seconds for the stopped curb vehicle. Anchor displacement is a limited image-path check, not identity or physical accuracy qualification.

The first queue completion checked the lead vehicle only. The updated native completion waits for the rear of all three prepared cars to pass the original hold position while moving and unowned. Queue, curb and crossing then keep the measured run open for five additional seconds before cleanup, giving the camera path an opportunity to observe departure. No native completion is converted to a camera count. The seventh warm installation retained all eight native people, 28 pool slots, runtime generations, exact simulation time and the running timeline; no actor placement or camera restart occurred during installation. Focused native checks passed: 20 prepared and 88 director/runtime tests.

The crossing failure occurred after three successful stories in the same worker session. All 5,356 accepted observations remained monotonic with unchanged source sessions. The first rejection had exact AU evidence but failed admission after reset; subsequent missing-proof errors were the fail-closed cleanup cascade. The correction keeps the strict two-second threshold and rejects invalid/missing/future proof. Only a finite tracker-reset drain may discard correctly decoded but stale queued batches before either tracker.

The first drain candidate (`9b0113f7…`, source `bf83278c…`) passed CPU controls but failed its first live demand preparation. Its detailed diagnostic proved a **2.001905613 s** frame age. The drain had ended on fresh input before the tracker's lazy MQTT initialization finished. This is evidence against that candidate's lifecycle closure, not a reason to widen the clock threshold. Native demand prepared in 0.773 s, never reached Play, and released all holds with normal motion verified after 1.335 s of cleanup. The browser kept its opaque cover throughout. The next correction closes the bounded drain only after fresh post-tracker output is established from both sources. Its live results follow when complete.

Receipts: [queue](qa/smart-city-prepared-2026-10-26/queue-play/summary.json), [pedestrian](qa/smart-city-prepared-2026-10-26/pedestrian-play/summary.json), [curb](qa/smart-city-prepared-2026-10-26/curb-play/summary.json), [crossing failure](qa/smart-city-prepared-2026-10-26/crossing-play/summary.json), [first drain candidate failure](qa/smart-city-prepared-2026-10-26/demand-final/summary.json), [covered recovery](qa/smart-city-prepared-2026-10-26/demand-final/recovery-cover.png).

## Final worker candidate

The revised worker is `sha256:17af10a349f2c1234c53fad139f5e533b47898d67dfa67fa06d085e5abf38506`, source SHA256 `eb80007df4da6707c26902fc5aacbcbf485c07240e957d534b57b2d0ac8d16e8`. Its reset drain closes only after each camera has at least three fresh post-tracker observations spanning one second. The original 20-second deadline never extends. Exact proof, two-second admission freshness, source monotonicity, both tracker stages, calibration and configuration pins remain enforced. CPU controls exercise the actual mux, boundary and output probes, including stale, missing, duplicate, future and old-epoch evidence. All focused reset, native clock and staged-tracker checks and the worker compile pass; see [CPU receipt](qa/smart-city-2026-10-26/prepared-scenario-post-tracker-drain-cpu.json).

Deployment used the existing local image and a bounded CPU-only build, followed by ordinary Agent pause/resume of the same two sources. Native Isaac was not restarted. The pending failed preparation recovered with fresh post-tracker output, the host closed its transaction, and both exact preview sources passed readiness. The source-mounted 7782 UI remains active.

## Final live scenario results

These five runs used one unchanged pair of source sessions on the final worker. Combined Ready was first observed 4.501–5.438 seconds after Preparing, at a 0.5-second observer cadence. Native placement completed sooner; the UI waited for fresh camera tracking before revealing the scene. Ready-to-Play waiting time was operator-controlled and is excluded from the playback durations.

| Story | Native prepare | First native motion after Play | Native normal after Play | Camera result |
| --- | ---: | ---: | ---: | --- |
| Demand | 0.683 s | 0.869 s | 46.649 s | One completed left, straight and right movement, each classified car |
| Queue | 1.041 s | 1.648 s | 42.894 s | Two observed queue members; maximum observed extent 9.545 m; ended empty with no lost tracks, but `clearanceConfirmed` remained false |
| East pedestrian | 0.770 s | 1.889 s | 31.554 s | Waiting/crossing observed; south-to-north completion zero, incomplete two; native endpoint success is separate |
| Curb | 0.730 s | 1.826 s | 21.169 s | Persistent stopped occupancy and one departure; visit began inside the zone, so no fully observed completed visit |
| South crossing | 0.715 s | 1.851 s | 19.745 s | One completed obstruction episode; 9.321 observed blocked seconds |

The queue's three full rear bodies cleared at 26.941, 32.823 and 37.798 seconds after Play, followed by 5.012 seconds of observation. The pedestrian's native task returned `SUCCEEDED` at the validated far-side endpoint under coherent WALK. All eight loaded people and 28 vehicle pool slots were retained. The timeline continued; no owners, signal freezes or arrival pauses remained. Sampled task failure/rejection/timeout deltas and signal phase mismatches were zero.

Cancellation was exercised through the real UI while it still displayed Preparing: native controls released at 0.522 seconds and normal motion was verified at 2.259 seconds from Prepare. A second test cancelled actual playback after visible movement; it restored normal flow. The controlled preflight test supplied an invalid copy of one navigation start to the real validator. It refused the start before any vehicle or person placement, disarmed itself and restored native normal flow in 0.202 seconds. In all cases the host subsequently closed its transaction and cameras returned after fresh tracking.

The eight root observations checked **409 exact preview envelopes**, with no observer errors, monotonic source clocks and no operational tracks/metrics during preparation. The independent boundary observer checked 13,523 native rows, 183 exact previews and ten two-stage reset acknowledgments. These counts overlap and must not be added. The stale-drain path was exercised during real resets; stale batches were discarded before trackers, and fresh output ended the drain.

Evidence: [eight-case results and camera snapshots](qa/smart-city-prepared-2026-10-26/acceptance-results.json), [independent native receipt](qa/smart-city-prepared-2026-10-26/final-native-acceptance-summary.json), [boundary lifecycle receipt](qa/smart-city-2026-10-26/prepared-scenario-final-boundary-live.json), [camera cover](qa/smart-city-prepared-2026-10-26/demand-retry-final/preparing-cover.png).

## Retained results and remaining capture issue

Live review found that archiving after invalidation erased prior queue and curb summaries. The gateway now snapshots the last observed mobility data before invalidation, labels it `last-observed-before-boundary`, and records the observation-end reason. Active events still become unknown when a scope ends; ending a run never invents a cleared event. All **298 gateway tests** pass. The gateway-only restart loaded this fix. Existing invalidated archives were preserved without retrospective fabrication; their saved live traces support the table above.

A fresh curb replay after this fix retained the empty final state, one observed departure, one partial visit and 17.145 occupied seconds in its archived scope. The partial visit correctly has zero full completed visits. See [archive fidelity checks](qa/smart-city-2026-10-26/prepared-scenario-archive-fidelity-cpu.json) and [live curb archive](qa/smart-city-prepared-2026-10-26/curb-archive-check/scope-archive.json).

A subsequent queue replay completed in 43.292 seconds after Play. Its archive retained the actual empty final queue, maximum observed extent 9.452 m, complete current membership, zero lost tracks and the still-unconfirmed clearance flag. These two archive replays checked another 126 exact previews with no observer errors; see [live queue archive](qa/smart-city-prepared-2026-10-26/queue-archive-check/scope-archive.json). New normal scopes remained separate from those saved results.

After the eight-case acceptance sequence returned to normal, the worker stopped on **duplicate native UUID metadata in one encoded access unit**, after publishing 13,739 rows. This is a separate fail-closed parser rejection before decoded/mux/tracker processing. Its origin is unproven without the offending encoded bytes; there is no evidence that resetting tracker state causes it. The navigation-failure probe did not modify streaming. No duplicate-proof, freshness or clock checks were relaxed. Ordinary Agent resume restored the same two registered sources, and subsequent live checks ran on the unchanged worker image. The saved [detector log](qa/smart-city-2026-10-26/prepared-scenario-final-worker-detector.log) and lifecycle receipt retain the failure; this work does not claim sustained capture qualification.

## Left running

Final checks confirmed both live cameras and exact paired previews ready, host transaction closed, analytics boundary normal, timeline playing, eight native people and 28 vehicle slots retained, and no actor owners, signal freeze or paused arrival schedule. The controlled failure probe is disarmed. The browser shows both cameras **AI live**; its final warning/error log is empty. All read-only acceptance observers have ended.

The profile differs from baseline only by worker image. All eight tracker/calibration file hashes match. All 19 rules are unchanged except their normal lifecycle revision counters; mobility configuration is unchanged. The Spark guard remains at 20 GiB with 35.454 GiB available at the final check. Thor settings, indexing policy and the paused overnight heartbeat were not changed. No Isaac restart, timeline reset, asset modification, package installation or commit occurred.

Final evidence: [runtime and invariant receipt](qa/smart-city-prepared-2026-10-26/final-runtime.json), [restored live view](qa/smart-city-prepared-2026-10-26/normal-restored.png).
