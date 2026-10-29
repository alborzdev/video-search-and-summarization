// SPDX-License-Identifier: MIT
import type { CitySource, NativeSeiClockEvidence } from './types';

const unsigned = (value: unknown, limit: bigint): value is string => typeof value === 'string'
  && /^\d{1,20}$/.test(value) && BigInt(value) <= limit;

/** Exact encoded-AU handoff proof; it does not verify a browser/exposure clock. */
export function nativeSeiClockEvidence(value: unknown, ns: unknown, pts: unknown): value is NativeSeiClockEvidence {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proof = value as Partial<NativeSeiClockEvidence>;
  return Object.keys(value).length === 6 && proof.schemaVersion === 'city.source-native-sei.v1'
    && proof.method === 'isaac-native-sei-wall-capture' && proof.correlation === 'exact-au-pts'
    && unsigned(proof.captureTimeNs, BigInt('9223372036854775807')) && BigInt(proof.captureTimeNs) > BigInt(0)
    && unsigned(proof.auPtsNs, BigInt('9223372036854775807'))
    && unsigned(proof.frameCounter, BigInt('18446744073709551615'))
    && proof.captureTimeNs === ns && proof.auPtsNs === pts;
}

export function nativeSeiSourceClock(source: CitySource): boolean {
  return source.timestampBasis === 'source-native-sei' && source.sourceClockMode === 'source-native-sei'
    && source.browserClockVerified === false
    && nativeSeiClockEvidence(source.sourceClockEvidence, source.lastSourceTimeNs, source.rawSourcePtsNs);
}
