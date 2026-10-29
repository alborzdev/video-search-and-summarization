# Native tracking ID audit — 26 October 2026

The original single MV3DT tracker used its corrected global SDK handle as the camera-local handle too. That made a cross-camera ID correction restart an otherwise continuous local walking journey. The evidence supports separating those two handles; it does not prove that every lost journey came from this cause.

The retained original prefix contains 17,406 rows (81,846,802 bytes). The latest source sessions select 17,322 rows after explicitly excluding 84 older-epoch rows. Their observed durations are 595.23 seconds southwest and 588.31 seconds northeast. There were no sequence gaps, duplicate-ID omissions or same-ID class collisions in those selected sessions. Nonetheless, the southwest camera emitted 208 person IDs and northeast emitted 263. Adjacent boxes sometimes changed SDK ID at IoU above .98 with detector confidence near .9; several replacement IDs already existed in the other camera. These are continuity diagnostics, not physical-person ground truth.

The retained bytes and their SHA-256 are recorded in [tracking-id-baseline.json](tracking-id-baseline.json). The read-only tool is [audit_track_lifecycle.py](../../../tools/smart-city/audit_track_lifecycle.py). It reports source epochs, input byte bounds/hash, source clocks, observation spans, left/right window censoring, replacement examples and ambiguities. It does not create operational aliases or decode video.

## Comparable duration, separate live cohorts

Each following sample uses the first common 60 source seconds after five seconds of warmup. These are different live inputs; the original sample has no independent ground-truth scenario label. The flags-off sample was captured before any new scenario, Ask request or base-flow reload after activation.

| Diagnostic | Original SW / NE | Flags-off SW / NE |
| --- | --- | --- |
| Frames | 777 / 773 | 934 / 934 |
| Distinct person IDs | 28 / 30 | 20 / 17 |
| Adjacent different-ID replacements, IoU ≥ .8 | 12 / 11 | 3 / 0 |
| Those replacements with new ID already seen in peer | 8 / 4 | 0 / 0 |
| Median bounded observation span, seconds | 11.09 / 6.73 | 10.24 / 11.16 |
| Sequence gaps / ambiguous omissions | 0 / 0 | 0 / 0 |

The southwest median did not improve. Observation spans are bounded by scene entry/exit and both sides of the sample window; they are not complete person lifetimes. See the explicit censoring fields in [original 60-second audit](tracking-baseline-normal-60s.json) and [flags-off 60-second audit](tracking-stable-id-normal-60s.json).

Turning off both late peer adoption and ID correction reduced high-IoU replacements in these cohorts, but it also removed shared-person-ID opportunities. For every southwest frame, [tracking-same-id-opportunities.json](tracking-same-id-opportunities.json) selects the nearest northeast source timestamp within 150 ms and reports reuse. The original cohort had 293 pairs with a matching eligible native global ID (338 object opportunities); 137 northeast frames were reused. The flags-off cohort had zero matching IDs across 934 pairs, with no reuse, even though 831 pairs had eligible hints in both views. This tests the native ID and clock preconditions only; it does not prove correct identity, map distance, exact displayed-frame matching or browser qualification.

## Source candidate

The next candidate runs ordinary camera-local NvDCF first and full MV3DT second. Local journey identity and boxes come from the first tracker. A current detector-object application stamp is the only join to the second tracker's optional native global handle and 3D evidence. Second-stage predicted or peer-created objects cannot borrow a local identity. Missing or ambiguous global evidence removes the optional map hint, while preserving the first local observation.

The flags-off profile remains a continuity experiment, not a final shared-map solution. The staged candidate has CPU metadata/serialization tests and an independent source review, but no live dual-tracker performance or accuracy qualification at preparation time. See [architecture and limits](../../smart-city-tracker-stages-2026-10-26.md), [candidate build receipt](staged-native-candidate-build.json), [eight-pin profile receipt](staged-native-profile-preparation.json) and the private review bundle's `INSTALL.md` for controlled activation and rollback.

## First staged live cohort

After root installed the reviewed staged image/profile and confirmed new camera sessions, the read-only audit retained 06:31:48.318–06:32:48.318 UTC, five seconds after both sources first appeared. The 1,202-row file is hashed and retained separately; see [local lifecycle receipt](tracking-staged-normal-60s.json) and [association receipt](tracking-staged-association-60s.json).

The southwest/northeast samples contain 599/603 frames and 12/3 distinct person IDs. Their bounded median spans are 33.77/10.16 seconds. These different live cohorts do not establish a causal speed or accuracy comparison. Southwest still has 24 adjacent high-IoU different-local-ID replacements; at least the twelve stored strongest examples switch to IDs already seen earlier in this cohort. Local continuity is improved in some measures but remains imperfect.

The architectural separation works in actual inference: 29 southwest and one northeast consecutive observations changed their native global hint while retaining the exact first-stage local handle. There were zero exported duplicate-local/global-ID omissions, zero rejected-map ambiguity counts and no observation sequence gaps. Southwest has 3,152 native 3D samples out of 3,270 observed person samples, northeast 434 out of 442. All exported native feet pass the finite/bounded SDK-world guard and all exported local provenance matches. There is no explicit stamp-missing diagnostic counter; the 118/8 missing optional native 3D samples cannot be attributed uniquely to tentative second outputs, missing projection or rejected provenance from current output alone.

Nearest source-timestamp pairing within 150 ms recovered 291 same-native-global-ID object opportunities; 209 also have first-local homography positions within 1 metre. There are 108 reused peer frames. This is retained-history analysis, not proof of browser presentation or physical identity. Same-ID homography distance has median .899 m and 95th percentile 1.213 m, so projection disagreement is a secondary limit.

The immediate shared-map blocker is the pair of frames delivered together: the latest-output approximation has median 452.6 ms skew and only 4 of 1,198 updates within the unchanged 150 ms guard. A separately fetched [exact processed-preview pair](staged-latest-exact-preview-clock-pair.json) shares a genuine native global ID and has positions .650 m apart, yet its actual frame timestamps differ by 452.757 ms. That pair fails only the timestamp guard.

## Clock boundary checks

Two ten-second encoded-only captures compared native SEI capture-wall timestamps with real GStreamer RTCP reference metadata. No video decoding, inference, server reset or clock rewriting was used.

- [Native-origin measurement](staged-native-origin-capture-clock.json): 131 exact common render ticks; capture handoff skew median -.346 ms. RTCP minus native capture wall is +14.947 ms southwest and -14.789 ms northeast. Only 65 northeast packets have RTCP reference metadata because the sender report arrived during the bounded capture.
- [Actual VIOS worker-input measurement](staged-vios-input-capture-clock.json): 122 exact common render ticks. RTCP minus native capture wall is +15.043 ms southwest and +.147 ms northeast; there are 10/40 referenced packets after sender reports arrive. Parsed receive latency median is 16.47/1.55 ms. Both-reference common-tick skew is 14.424 ms.

These measurements reject a current 450 ms producer-start offset and do not show a 450 ms VIOS wire-clock error. They use independent encoded-only clients, so they do not prove the NTP metadata reconstructed inside the long-running native worker. The next precise boundary check is to compare actual same-buffer `GstReferenceTimestampMeta` at decoded-source output with downstream `NvDsFrameMeta.ntp_timestamp`, using the documented RTSP reference-metadata property. Do not subtract a guessed offset, relax the map guard or use simulator ground-truth IDs to hide the discrepancy.

## Actual worker reference proof

Root subsequently deployed the explicit observe-only diagnostic profile with baseline mux settings unchanged. [source-clock-actual-worker-proof.json](source-clock-actual-worker-proof.json) retains 634 observations over thirty common source seconds, starting two seconds after both cameras have reference metadata at all four probe stages. Every selected observation carries the same real packet reference through depay, parser, CPU decode and NVMM upload/before-mux. SDK-minus-reference median is 0 ns southwest and 1 ns northeast; maximum absolute disagreement is 3.555 microseconds. No new clock authority is justified by this run.

The new unsynchronized worker also no longer has the old persistent 450 ms output offset. Non-overlapping adjacent output pairs have median skew 14.56 ms and 95th percentile 37.88 ms; 312 of 313 meet the unchanged 150 ms display guard. The latest-output-update approximation has 608 of 633 updates within that guard. A [later exact preview pair](source-clock-diagnostic-exact-preview-pair.json) has 14.550 ms skew, although it has no simultaneous shared native hint at that instant. Passing clock guards does not prove a shared identity is visible.

Before-mux packet age has 95th percentile about 47.3 ms and maximum 49.72 ms in the retained window. The historic uninstrumented epoch cannot establish whether its 450 ms discrepancy came from reconstruction or FIFO/frame selection; the restart and added reference instrumentation occurred together. The subsequent bounded PTS-sync trial failed and was rolled back, as recorded below.


## Actual map guards after clock measurement

The [map guard receipt](source-clock-map-guard-proof.json) replays the actual pure UI `mapObjects.ts` function over the retained 634 observations. This is explicitly conditional on presenting the exact paired camera frames; it does not fabricate browser presentation evidence. Of 633 latest-source output updates, 608 produce one shared person object and 25 correctly refuse a join solely because frame timestamps differ by more than 150 ms. Every paired update has one genuine eligible shared native target. Its first-local homography separation has median .475 m, 95th percentile .575 m and maximum .631 m; none fails the unchanged 1 m initial-join guard. Fresh joins and the existing membership hysteresis give the same 608 outcomes.

The observation-level exclusions remain honest: southwest/northeast have 52/11 observed person samples without optional native 3D and 5/13 below .25 visibility. Separately, 68/61 person anchors fall outside the valid projection region. Those categories can overlap; they must not be added as independent rejected-person totals. There is still no dedicated stamp-missing cause counter.

After the failed-sync rollback, a later concurrent exact-preview pair has 14.485 ms skew and genuine native target121 in both cameras, with homography positions .723 m apart. The actual map function returns one shared object for those exact envelopes if presented. A separate later actual browser capture, [queue-final-active.jpg](queue-final-active.jpg), shows both exact previews and “Experimental shared people IDs · 2 joined,” as inspected by root. That is browser evidence from the later queue scenario, not the retained normal cohort or the target121 pair. These checks demonstrate usable guarded shared hints; they do not establish physical identity accuracy or production fusion qualification.

## Failed PTS synchronization and rollback

The [bounded trial receipt](source-clock-pts-sync-failure.json) preserves a real failure, including actual worker identity, readback and original file hashes. The candidate read back `sync-inputs=true`, maximum latency 200,000,000 ns and NTP window zero. After startup it emitted only one northeast observation, sequence0, with arrival-PTS fallback and no RTCP reference; southwest emitted none. Strict readiness remained false, and the sources became awaiting/stale. The preserved log shows initialized trackers/engine and no explicit fatal pipeline error. The data cannot distinguish mux waiting/dropping from upstream blockage, so a guessed offset or another latency value is not justified.

Root restored the diagnostic baseline with all mux synchronization controls off; its health/readiness recovered and later exact preview skew was 14.485 ms. This remains a restart-sensitive observation, not proof that restart is a general clock repair. NTP-only synchronization was not tried: installed legacy documentation and property metadata do not establish its behavior without PTS sync or before sender reports. Missing/delayed RTCP, one-camera absence and reconnect skew recovery remain unqualified. The final profile can disable observe-only diagnostics without changing clock authority or the unchanged map guards; deployment and final acceptance belong to the parent integration run.
