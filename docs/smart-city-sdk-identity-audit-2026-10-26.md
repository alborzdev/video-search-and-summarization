# MV3DT ID continuity and bounded stable-ID trial

The SDK target ID is currently used for both native identity and camera-local
journey identity. A native ID change therefore starts a new local journey.
This can interrupt crossing, curb and dwell measurements even while a box
remains on screen. There is no qualified alias adapter in the current app.

This audit and preparation made no live changes. The trial is named
`stable-local-ids-experimental`; the name describes the intended test, not a
guarantee that the SDK can no longer lose or replace a track.

## What the installed SDK exposes

Read directly from the running worker's installed DeepStream 9.2 source:

| Source | Finding |
| --- | --- |
| `sources/includes/nvdstracker.h`, `NvMOTTrackedObj` | One `trackingId`, plus class, box, age, confidence, input association, 3D fields and reserved bytes. No documented second local target handle. |
| `sources/includes/nvds_tracker_meta.h`, `NvDsTargetMiscDataObject` | One `uniqueId` for target history. Frame age/state is not a unique object identity. |
| `sources/includes/nvdsmeta.h`, `NvDsObjectMeta` | One `object_id`; `unique_component_id` identifies the inference component. User and reserved fields are not an SDK local identity. |
| `sources/gst-plugins/gst-nvtracker/nvtracker_proc.cpp:1783`, `:1841` | Both associated detections and tracker-generated objects receive `objectIdMapping(pTrackedObj->trackingId, streamID)`. |
| Same file `:2195` | The mapping returns this ID, with an optional stream-EOS offset. It does not retain the original identity before a peer ID change. |
| `services/rtvi/rt-cv/smart-city/src/city_worker.cpp:540`, `:552` | The worker serializes `object_id` as `localTrackId` and native `targetId`. |

Neither a metadata-pool address nor reserved bytes may be used as a stable
handle. The associated input pointer identifies the present detector object,
not a persistent person. Splitting numeric ID bits is also unsupported.

The public API documentation agrees with the installed field layout.
[NVIDIA tracker API](https://docs.nvidia.com/metropolis/deepstream/9.1/sdk-api/sources_2includes_2nvdstracker_8h_source.html)

## Native ID changes

Late peer association can replace a recently active target's ID with a peer ID.
Correction can discard an incorrect ID, retry association and allocate a new
ID. `ADOPTED_ID` documents a previous-to-adopted-ID message for peer adoption;
it is not documented as a complete history of correction without adoption.
`TRACKLET` also appears when a target acquires an ID, but its documented data
does not establish the old identity. Thus an adoption subscriber alone is not
yet a complete continuity solution.
[NVIDIA MV3DT architecture and message types](https://docs.nvidia.com/deepstream/9.2/text/DS_MV3DT)

No raw SDK adoption/correction event capture was collected during this audit.
Existing files named `telemetry.ndjson` contain resource readings, not MQTT ID
events. Do not present them as correction-event evidence.

## Prepared trial

The baseline has both `enableLatePeerReAssoc: 1` and `enableIDCorrection: 1`.
Both are documented sample configuration switches.
[NVIDIA reference tracker configuration](https://raw.githubusercontent.com/NVIDIA/DeepStream/main/src/apps/reference_apps/deepstream-tracker-3d-multi-view/config_templates/config_tracker.yml)

The new candidate changes only those two numerical settings to `0`. Camera,
package, source export, MQTT configuration and broker topic bytes remain
identical. File references move to a separate pinned snapshot. The manifest
adds explicit experimental policy/provenance fields. Initial native peer
association, monocular tracking, local re-association, detector, class priors,
pose/ReID settings, image and all map guards remain as before.

This removes two known causes of later ID replacement. It also prevents missed
initial matches from converging later and prevents correction of incorrect
initial matches. Local loss, re-detection and tracker errors remain possible.
This is a reversible trial, not a general recommendation to disable SDK
correction in a production camera network.

Prepared bundle:

`/home/sparkdev/vss/.spark/city/runtime/intersection-rebuild-20261026/review-stable-local-ids-20261026`

| Artifact | SHA256 |
| --- | --- |
| Original `active.json`, exact rollback bytes retained | `1f946a9efd1b17a7f19a521fb2d6ff7db43b5c273291082c4ccb449ed57e8831` |
| Candidate `active.json` | `13c9ed3114a8a419f4d60fa561f431ee04eeea8a45de7a621eedaa6dbb6101a3` |
| Candidate tracker | `4b1b254c11f0d57223343aea6a117a68d0f34da65542dd7dcb30b1be830f232c` |

The seven source/candidate file hashes, calibration, export and image identity
are in `receipt.json`. `rollback-active.json` preserves the original profile
exactly. The actual production profile loader passes against a temporary copy
of the bundle. Fourteen new preparation cases and four existing loader cases
pass with CPU-only pytest. No service, GPU, MQTT subscription or Kit operation
was used for preparation.

Reproduce preparation in a **new** review directory and with a new snapshot:

```bash
python3 tools/smart-city/prepare_mv3dt_stable_ids.py \
  --snapshot UNIQUE-SNAPSHOT \
  --output NEW-REVIEW-DIRECTORY
```

Preparation refuses existing snapshots/output, altered source pins, unpinned
references, swapped cameras, wrong calibration and unexpected baseline flags.
It rechecks source identity before returning. It never applies the candidate.

## Controlled activation and rollback

1. Confirm no booth episode owns actors, then pause both sources through the
   normal Agent controls. Keep the simulator and cameras running.
2. Recheck the original active SHA and all seven source pins against the
   receipt. Copy only the new `native/mv3dt-demo/intersection-stable-local-ids-20261026`
   directory from the review into `.spark/city/state`; fail if it exists.
3. Install the reviewed candidate `active.json` atomically into the existing
   profile location. Validate with `mv3dt_demo_profile.load(root, 'spark')`.
4. Resume sources in the existing SW/NE order. Confirm the launched worker
   uses the pinned unchanged image and new tracker path. A new tracking epoch
   must start. Do not carry durations or histories across the cutover.
5. Observe 60 seconds of normal flow, then the full pedestrian scenario.
   Compare per-camera observed track lifetimes, actual ID replacements,
   completed crossings and per-source counts. Report map join coverage and
   any new same-ID inconsistencies. High-IoU replacement is a churn diagnostic,
   never authority to merge tracks. These are different live windows; do not
   call this an identical-input benchmark or identity-accuracy qualification.

For rollback, pause both sources, atomically restore `rollback-active.json`,
validate its original seven pins, then resume in normal order. Keep both trial
receipts and the unused derived snapshot. No gateway, UI, rule, scene or map
geometry change is required for either direction.

If this trial does not give useful local continuity, the next sound options
are an SDK-supported complete transition event adapter or a separately tracked
native local identity. Both need explicit association provenance, epoch and
generation scoping, collision/split tests and cost measurements. Box overlap,
nearest map distance and guessed numeric aliases are not substitutes.

## Independent audit of a two-native-tracker candidate

A separate candidate can run native NvDCF first and native MV3DT second.
The first ID must travel as application-owned metadata on the same actual
detector object. It must never be recovered by comparing boxes or positions.
The pipeline agent owns this implementation; this audit changed no worker
source or live pipeline.

The installed tracker source supports this propagation path:

- `fillMOTFrame` at lines 1395–1421 sends each input object's box/class/confidence
  and stores that exact `NvDsObjectMeta*` as `pPreservedData`.
- At line 1780, a result with `associatedObjectIn` reuses that input object.
  Its application user metadata is not cleared. Projection/ReID functions
  append their own typed metadata.
- At line 1813, a result without an associated current input acquires a fresh
  metadata object. It has no authoritative first-tracker stamp and must be
  rejected by the candidate exporter.
- `removeUntrackedObjects` at line 2181 removes unchanged input objects left
  with `UNTRACKED_OBJECT_ID`. Clearing this field before the second tracker
  ensures unmatched inputs cannot masquerade as second-tracker outputs.

Stamp raw PGIE detections, retain the first native ID only on a matching
current detector stamp, restore the raw detector fields before the second
tracker and require the retained current-frame stamp at final export. Remove
only the first tracker's four batch misc types: past frames, batch ReID,
terminated tracks and shadow tracks. Preserve PGIE, preprocessing, timestamps
and unrelated metadata. Reject first-tracker configurations that emit 3D
projection metadata, or explicitly remove only those first outputs, so the
second tracker remains the sole 3D authority.

**Frame-token warning:** line 1735 replaces `NvDsFrameMeta.frame_num` with the
tracker's returned frame number. With `useBatchNumForFrameId: 1`, MV3DT replaces
the original source frame number with its batch counter. Preserve the original
frame token in application frame metadata. Comparing a PGIE frame-number stamp
to the final `frame_num` can reject every valid object or accept wrong evidence.

An independent **CPU-only actual metadata API proof passed** in the pinned
worker image `sha256:6b74dbe97296e40adcd019f20422d4a1dc3b7f301e0bff2e9fab88f24f705cf1`,
with `runtime=runc`, network disabled and no GPU tracker execution. It used
`nvds_create_batch_meta`, custom object/frame user metadata,
`nvds_copy_obj_meta` and the official metadata removal APIs. It confirmed a
full uint64 local ID survives an ID-field change, deep-copied payloads are
independent, a newly acquired shadow object has no stamp, removing the four
tracker batch types preserves unrelated metadata, and all **9 allocations / 9
releases** balance. Copy/release callbacks receive an `NvDsUserMeta*` wrapper;
they must access its `user_meta_data`, not cast the callback argument directly
to the application payload.

Source and pinned receipt:

`/home/sparkdev/vss/.spark/city/runtime/intersection-rebuild-20261026/sdk-user-meta-proof/{proof.cpp,receipt.json}`

This proves metadata ownership/copy/removal behavior. It does not execute
`NvMOT_Process`, measure tracker cost or validate local/global association
accuracy. Those remain separate live or paired-input trial requirements.
