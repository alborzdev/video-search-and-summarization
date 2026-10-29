// SPDX-License-Identifier: MIT
import type { CitySite, CitySnapshot, CityTrack } from './types';
import { nativeSeiSourceClock } from './sourceClock';

export interface CityMapObject {
  id: string; track: CityTrack; memberTrackIds: string[]; sourceIds: string[]; shared: boolean;
  membershipKey?: string;
  nativePositionSpreadM?: number;
}
// Demo display tolerance for the approximately 8 fps cameras; the production evaluator remains at 50 ms.
export const DEMO_MAX_CAPTURE_SKEW_NS = 150_000_000;
export const DEMO_JOIN_DISTANCE_M = 1;
export const DEMO_SPLIT_DISTANCE_M = 1.5;
const clock = (value: unknown): bigint | null => typeof value === 'string' && /^\d{1,24}$/.test(value) ? BigInt(value) : null;
const token = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 256;
const nativeClasses = new Set(['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler']);
const point = (track: CityTrack) => track.positionM?.length === 2 && track.positionM.every(Number.isFinite);

export const usesNativeMapPositions = (snapshot: CitySnapshot | null) => snapshot?.mode === 'live' &&
  snapshot.association?.mapFusion?.enabled === true && snapshot.association.mapFusion.positionBasis === 'native-mv3dt-world-foot';

export function hasNativeMapPosition(track: CityTrack): boolean {
  const association = track.mapAssociation;
  return association?.method === 'mv3dt-demo' && association.positionBasis === 'native-mv3dt-world-foot' &&
    association.positionM?.length === 2 && association.positionM.every(Number.isFinite) &&
    Number.isFinite(association.visibility) && association.visibility >= .25 && association.visibility <= 1;
}

/** Map-only grouping of already displayed observations. Camera tracks/rules are untouched. */
export function deriveMapObjects(site: CitySite | null, snapshot: CitySnapshot | null, previousMapObjects: CityMapObject[] = []): CityMapObject[] {
  if (!site || !snapshot) return [];
  const nativePositions = usesNativeMapPositions(snapshot);
  const tracks = snapshot.tracks.map(track => {
    const association = track.mapAssociation;
    // A failed native position must not turn into a different ground anchor.
    // Keep the original camera track and analytics projection untouched.
    return hasNativeMapPosition(track)
      ? { ...track, positionM: association!.positionM!, trail: [] }
      : nativePositions ? { ...track, positionM: null, trail: [] } : track;
  }).filter(track => point(track) && !track.stale && track.observedThisFrame !== false);
  const groups = new Map<string, CityTrack[]>();
  const previousShared = new Map(previousMapObjects.filter(object => object.shared).map(object => [object.id, object]));
  const local = (track: CityTrack): CityMapObject => ({ id: track.id,
    // The candidate does not carry map trails through SDK reassociation.
    track: track.mapAssociation?.method === 'mv3dt-demo' ? { ...track, trail: [] } : track,
    memberTrackIds: [track.id], sourceIds: [track.sourceId], shared: false });
  const result: CityMapObject[] = [];
  if (site.mode !== 'live' || snapshot.siteId !== site.id || snapshot.siteRevision !== site.revision ||
      snapshot.association?.mapFusion?.enabled !== true || snapshot.association.mapFusion.mode !== 'mv3dt-demo' ||
      !(snapshot.videoFrameMatched || snapshot.videoClockAligned)) return tracks.map(local);
  const eligible = (track: CityTrack) => {
    const association = track.mapAssociation;
    const source = site.sources.find(source => source.id === track.sourceId);
    const displayed = snapshot.sources.find(source => source.id === track.sourceId);
    return (track.class === 'person' || (nativeClasses.has(track.class) && association?.positionBasis === 'native-mv3dt-world-foot')) &&
      track.observedThisFrame === true && association?.method === 'mv3dt-demo' &&
      token(association.globalTrackId) && token(association.targetId) && token(association.fusionEpoch) && token(association.calibrationRevision) &&
      (association.sourceClockBasis === 'source-rtcp' || association.sourceClockBasis === 'source-native-sei') &&
      Number.isFinite(association.visibility) && association.visibility >= .25 && association.visibility <= 1 &&
      source?.calibrationRevision === association.calibrationRevision && displayed?.calibrationRevision === source.calibrationRevision &&
      displayed?.timestampBasis === association.sourceClockBasis &&
      (association.sourceClockBasis !== 'source-native-sei' || (nativeSeiSourceClock(displayed)
        && token(track.modelRevision) && track.modelRevision === displayed.modelRevision)) &&
      displayed.status === 'live' && displayed.sessionId === track.sessionId &&
      clock(track.sourceTimeNs) !== null && track.sourceTimeNs === displayed.lastSourceTimeNs;
  };
  for (const track of tracks) {
    const association = track.mapAssociation;
    if (!association || association.method !== 'mv3dt-demo') { result.push(local(track)); continue; }
    const key = JSON.stringify([site.id, site.revision, association.method, association.fusionEpoch,
      association.globalTrackId, association.targetId, association.sourceClockBasis,
      association.sourceClockBasis === 'source-native-sei' ? track.modelRevision : null]);
    const group = groups.get(key) ?? []; group.push(track); groups.set(key, group);
  }
  for (const [key, members] of groups) {
    // The optional native input policy treats car/truck as one association
    // family. Require matching explicit policy evidence from every member;
    // keep raw detector classes, camera tracks and analytics unchanged.
    const sameClass = new Set(members.map(track => track.class)).size === 1;
    const carTruckFamily = members.every(track => ['car', 'truck'].includes(track.class)
      && track.mapAssociation?.classPolicy === 'car-truck-family-v1'
      && track.mapAssociation.positionBasis === 'native-mv3dt-world-foot');
    let valid = members.length > 1 && members.every(eligible) && new Set(members.map(track => track.sourceId)).size === members.length &&
      (sameClass || carTruckFamily) &&
      new Set(members.map(track => track.mapAssociation?.positionBasis ?? 'camera-local-homography')).size === 1;
    const objectId = `experimental:${key}`;
    const membershipKey = JSON.stringify(members.map(track => [track.id, track.localTrackId, track.sourceId, track.sessionId,
      track.mapAssociation?.calibrationRevision]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
    // Hysteresis changes only the current-position split threshold. Never reuse old positions or evidence.
    const established = previousShared.get(objectId)?.membershipKey === membershipKey;
    const maximumDistance = established ? DEMO_SPLIT_DISTANCE_M : DEMO_JOIN_DISTANCE_M;
    const nativeIdentity = members.every(track => track.mapAssociation?.positionBasis === 'native-mv3dt-world-foot');
    let nativePositionSpreadM = 0;
    for (let i = 0; valid && i < members.length; i++) {
      for (let j = i + 1; j < members.length; j++) {
        const first = clock(members[i].sourceTimeNs)!; const second = clock(members[j].sourceTimeNs)!;
        const distance = Math.hypot(members[i].positionM![0]-members[j].positionM![0], members[i].positionM![1]-members[j].positionM![1]);
        nativePositionSpreadM = Math.max(nativePositionSpreadM, distance);
        // Native SDK identity and position agreement are separate evidence.
        // Splitting an SDK ID on a noisy position creates a second object the
        // tracker never created. Preserve that ID and disclose the spread.
        if ((first > second ? first-second : second-first) > BigInt(DEMO_MAX_CAPTURE_SKEW_NS) ||
            (!nativeIdentity && distance > maximumDistance)) valid = false;
      }
    }
    if (!valid) { result.push(...members.map(local)); continue; }
    // A fixed camera order avoids confidence-driven position hopping. Never average anchors.
    const ordered = [...members].sort((a, b) => site.sources.findIndex(source => source.id === a.sourceId) - site.sources.findIndex(source => source.id === b.sourceId));
    result.push({ id: objectId, membershipKey, track: { ...ordered[0], trail: [] },
      ...(nativeIdentity ? { nativePositionSpreadM } : {}),
      memberTrackIds: ordered.map(track => track.id), sourceIds: ordered.map(track => track.sourceId), shared: true });
  }
  return result;
}
