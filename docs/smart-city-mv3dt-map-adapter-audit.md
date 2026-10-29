# MV3DT map adapter: current behavior and safe candidate contract

Reviewed 2026-10-23 against the working tree. This is a CPU/source audit, not a promotion or a live tracking result. The running camera-local pipeline was not changed. The failed trials and current deployment decision remain in [the MV3DT decision](smart-city-mv3dt-decision.md).

## Answer

**A valid shared MV3DT ID does not currently produce one map marker.** The backend preserves it as a label, but keeps two camera tracks. The map draws those tracks separately. Native world-foot coordinates do not reach the public map DTO. A tracker flag alone cannot complete this integration.

Keep two data layers: camera observations for exact-frame boxes and local analytics; a separately qualified map-object view for one marker per eligible shared identity. Begin with people only. Vehicle positions, counts and rules stay camera-local until separately qualified.

## Code evidence

| Path | Current behavior and consequence |
| --- | --- |
| `services/rtvi/rt-cv/smart-city/src/city_worker.cpp:461` | The optional `mv3dt` mode writes person IDs as `mv3dt:<process epoch>:<SDK object_id>`. Feet, image feet and visibility metadata must exist, but this condition does not require positive visibility, a valid peer association, a qualified calibration receipt or synchronized capture time. `std::optional` presence accepts a visibility value of zero. The diagnostic mode exports metadata without setting a global ID. |
| `city_worker.cpp:467` | Observed state is inferred from nonnegative detector confidence. Native metadata reports `observed` or `predicted-or-peer`; it cannot distinguish prediction from peer support. That distinction and any detector-confidence behavior under peer-created tracks need the native candidate's control tests. |
| `city_worker.cpp:86` and `:398` | Fusion epoch is created at process start. A per-source clock reset rotates that source session but does not rotate the fusion epoch. A consumer must not carry old peer membership through such a reset. |
| `services/analytics/behavior-analytics/apps/city/models.py:211` | `globalTrackId` and `associationMethod` are nullable strings, without a qualification, class or epoch contract. Extra `native3D`/`fusionEpoch` fields can be parsed because the base model permits extras, but that does not connect them to map semantics. There is no typed `trackerMetadata` association path. |
| `engine.py:268` and `:294` | Public identity is `sourceId:effectiveSessionId:localTrackId`. The global ID and method survive, while native metadata and fusion epoch are not copied into the public track. Position remains bbox-bottom-center projection through the configured class homography. |
| `engine.py:271` | A class change retires the camera-local track state, correctly breaking its dwell/speed chain. It does not validate a shared ID against other sources' classes. |
| `engine.py:360` | Event identity and rule state are source/session/rule/local-track scoped. A shared ID does not deduplicate events, journeys, curb visits or crossing counts. |
| `preview.py:337`, `engine.py:694`, `main.py:110` | Preview, snapshot and health advertise camera-local association/fusion disabled. Merely accepting a string ID is not a promotion. |
| `services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/smart-city/alignedSnapshot.ts:5` | The UI joins each camera's accepted displayed frame. This protects exact camera overlays, but does not guarantee the two displayed cameras have close capture times. It does not perform association. |
| `CityMap.tsx:31` and `:75` | The map loops through non-stale observed tracks and uses each local `track.id` as the key. Its legend explicitly says shared IDs are not deduplicated. |
| `CityInspector.tsx:137` and `geometry.ts:64` | A nonempty global ID already changes labels and is described as associated across cameras. Promotion must gate these claims on validated association rather than string presence. |
| `useMobility.ts:10` | Mobility reports explicitly require `globalFusionEnabled:false`; their counts remain owner-camera counts. A map-only feature must preserve that authority and describe the scope separately. |

In-memory smoke test using the current engine (no runtime API or files): two camera observations with one global ID remained two tracks; supplied SDK position `[9,9]` was ignored in favor of projected bbox position `[2.5,4]`; a person and a car could share the same global ID. The snapshot still declared `{"mode":"camera-local","globalFusionEnabled":false}`. This is current behavior, not a claim that such input is safe to fuse.

## Smallest safe map-only adapter

1. **Validate association at ingestion, not from arbitrary UI strings.** Add a typed optional sidecar to each accepted camera observation. It carries the SDK target ID as a string, a gateway-approved method/profile revision, fusion epoch, calibration revision, class and association revision. An allowlisted local deployment manifest must identify the enabled classes and qualified native profile. Unknown methods and a failed/missing qualification remain camera-local.
2. **Keep source identity intact.** Preserve the exact source ID, effective source session, local track ID, sequence and source time used by the accepted preview. Do not overwrite `track.id`, camera bbox, homography position, speed, trail or event state to make a map merge work. Validate bounded ID lengths and use structured tuple keys rather than ambiguous string splitting.
3. **Separate identity from position provenance.** A shared identity can select a single currently observed representative without averaging uncertain coordinates. Initially use the qualified camera projection if native 3D positions have failed their gate; label this `camera-projection`, not fused 3D. A later `sdk-world-foot` position path requires its own finite/metre/frame/calibration/bounds/visibility validation and position-accuracy gate. Neither detector confidence nor tracker confidence is a position covariance.
4. **Bind each member to real current evidence.** Require an actual current detector observation for a solid map marker. Keep predicted and peer-supported states explicit and separate. At least one fresh observed member is necessary. If both views are hidden/unobserved, remove the observed marker; do not let a peer prediction create occupancy. Keep both cameras' own boxes and their own observed state.
5. **Derive map objects from exact displayed members.** Pass validated association sidecars through immutable preview history. After `displaySnapshot` has selected the shown source frames, derive `mapObjects` from that specific observation set, or request a backend map view using those exact frame identities. A latest backend `mapTracks` array must not bypass displayed-frame binding. Compare integer nanosecond strings with `BigInt`/integer arithmetic. Reject grouping across incompatible clock bases, calibration/profile epochs or measured capture skew beyond the qualified threshold.
6. **Group conservatively.** The key is `(site, qualification/profile revision, fusion epoch, canonical class, canonical SDK target ID)`. Allow at most one active member per camera. Class disagreement, same-camera duplicate membership, implausible position disagreement, excessive skew or an unresolved correction invalidates that group; expose local observations instead. Select a deterministic current observed representative and disclose its evidence camera(s). Do not apply the experimental confidence-weighted coordinate average.
7. **Invalidate across lifecycle boundaries.** Any participating source restart, clock discontinuity/basis change, calibration change, tracker/config change or peer-cluster restart retires the affected shared epoch and alias state. Conservative first candidate: retire the whole two-camera fusion epoch, return to local observations, and qualify fresh associations. A gateway adapter epoch can wrap the native process epoch while native lifecycle emission is developed.
8. **Treat ID correction as an explicit discontinuity until proven otherwise.** The worker currently exports SDK `object_id` as both local and global target ID. A correction can therefore change the local engine key and break local dwell/journey continuity. Do not infer aliases by proximity, confidence or a matching numeric suffix. If authoritative SDK correction metadata becomes available, retain versioned merge/split/reassignment records with effective source times; preserve historical evidence and prevent alias cycles or cross-class/epoch merges. Without it, retire the old map identity/trail and start a new one. Do not claim continuous identity or carry event duration across that transition.

Proposed derived map record (design only):

```text
MapObject {
  id, class,
  identity: {method, profileRevision, epoch, targetId, associationRevision},
  positionM, positionBasis: camera-projection | sdk-world-foot,
  representativeTrackId,
  members: [{trackId, sourceId, sessionId, sequence, sourceTimeNs, observedThisFrame}],
  evidenceSourceIds, captureSkewNs,
  state: observed,
  correctionState: unchanged | reset
}
```

For an established group observed by one camera, show one marker with that camera as evidence. Selecting it should highlight its camera member(s); camera selections should resolve back to the corresponding map object. Keep original camera IDs visible in details. Mixed coverage should read, for example, “People: shared identities; vehicles: camera-local.” A total of mixed markers is a display-object count, not a unique count of every road user.

## Event authority and candidate gates

The first adapter changes map presentation only. Per-camera rules, movement counts, visits and immutable event evidence stay unchanged. Global event aggregation is a separate feature that needs site-level rule ownership and tested merge/split/correction handling; summing camera counts or counting map markers is not that feature.

CPU controls before connecting a candidate:

- Two synchronized eligible person observations produce one map object and leave two camera tracks/boxes untouched.
- Non-qualified method, vehicle class, missing epoch/calibration, empty ID, cross-class ID and two members from one camera cannot fuse.
- One observed plus one predicted/peer-only member produces one observed marker with only the actual camera in its evidence list; two unobserved members produce none.
- Delayed frame, old session, clock-basis change, excessive skew and hidden/stale displayed preview cannot join a fresh group.
- Native world coordinates cannot silently replace calibrated camera positions; disagreement or unsupported position provenance fails closed.
- Late correction, conflicting correction, alias split and epoch reuse cannot join old trails, select an unrelated camera box or alter recorded events.
- Map merge leaves all per-camera rule metrics and mobility reports byte-for-byte equivalent for the same inputs.
- Large integer IDs and nanosecond timestamps round-trip as strings without JavaScript precision loss.

These controls would establish adapter behavior only. They cannot overturn the saved failed identity/position trials. Native tracking promotion still needs the paired, class-scoped geometric and identity evidence described in the decision document.
