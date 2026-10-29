// SPDX-License-Identifier: MIT
import { nativeSeiClockEvidence, nativeSeiSourceClock } from '../sourceClock';

const ns = '1792770000123456789';
const pts = '123400000';
const proof = () => ({ schemaVersion: 'city.source-native-sei.v1', method: 'isaac-native-sei-wall-capture', correlation: 'exact-au-pts', captureTimeNs: ns, auPtsNs: pts, frameCounter: '0' });
it('accepts exact AU handoff evidence without claiming an exposure or browser clock', () => {
  expect(nativeSeiClockEvidence(proof(), ns, pts)).toBe(true);
  expect(nativeSeiSourceClock({ timestampBasis: 'source-native-sei', sourceClockMode: 'source-native-sei', browserClockVerified: false, lastSourceTimeNs: ns, rawSourcePtsNs: pts, sourceClockEvidence: proof() } as any)).toBe(true);
});
it.each([
  ['missing', undefined], ['offset', { ...proof(), offset: 0 }], ['capture', { ...proof(), captureTimeNs: '1' }],
  ['pts', { ...proof(), auPtsNs: '1' }], ['negative counter', { ...proof(), frameCounter: '-1' }],
  ['numeric counter', { ...proof(), frameCounter: 1 }], ['overflow', { ...proof(), frameCounter: '18446744073709551616' }],
  ['method', { ...proof(), method: 'rtcp' }], ['correlation', { ...proof(), correlation: 'nearest-frame' }],
])('rejects %s native evidence', (_name, value) => expect(nativeSeiClockEvidence(value, ns, pts)).toBe(false));
it('requires explicit native provenance instead of accepting relabelled RTCP', () => {
  const source = { timestampBasis: 'source-rtcp', sourceClockMode: 'source-native-sei', lastSourceTimeNs: ns, rawSourcePtsNs: pts, sourceClockEvidence: proof() } as any;
  expect(nativeSeiSourceClock(source)).toBe(false);
  source.timestampBasis = 'source-native-sei'; source.sourceClockMode = 'source-rtcp';
  expect(nativeSeiSourceClock(source)).toBe(false);
});
