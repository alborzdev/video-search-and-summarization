// SPDX-License-Identifier: MIT
import { context, manifest, wire } from '../__fixtures__/video';
import { parseVideoFrame, parseVideoManifest, RtpFrameBuffer } from '../trackedVideo';
describe('exact WebRTC metadata identity', () => {
  const parse = (value = wire(), config = manifest) => parseVideoFrame(JSON.stringify(value), config, context, 'epoch');
  it('reconstructs only the matching immutable geometry manifest', () => {
    expect(parseVideoManifest(JSON.stringify(manifest), 'a', 'epoch')).toEqual(manifest);
    const frame = parse(); expect(frame.snapshot.sources[0].width).toBe(1000); expect(frame.snapshot.sources[0].sequence).toBe('1');
    expect(frame.snapshot.tracks[0].bboxPx).toEqual([100, 100, 100, 200]);
    expect(() => parse(wire(), { ...manifest, key: 'b'.repeat(64) })).toThrow();
    expect(() => parse(wire(), { ...manifest, snapshot: { ...manifest.snapshot, siteRevision: 2 } })).toThrow();
    expect(() => parseVideoManifest(JSON.stringify(manifest), 'a', 'other')).toThrow();
  });
  it.each([-1, 2 ** 32, 4.5, undefined])('rejects an invalid actual RTP timestamp %s', rtp => {
    const value = wire(); (value.transport as any).rtpTimestamp = rtp; expect(() => parse(value)).toThrow();
  });
  it('rejects cross-source/session metadata and malformed boxes', () => {
    for (const change of [{ sourceId: 'other' }, { sessionId: 'other' }, { sourceSessionId: 'other' }, { sourceTimeNs: '1' }, { modelRevision: 'other' }]) {
      expect(() => parse({ ...wire(), ...change })).toThrow();
    }
    const frame = wire(); frame.snapshot.tracks[0].bboxPx[0] = Infinity; expect(() => parse(frame)).toThrow();
  });
  it('never borrows a nearby frame, handles timestamp wrap, and bounds memory and age', () => {
    const cache = new RtpFrameBuffer(2);
    cache.push(parse(wire(1, 4294967295)), 0); cache.push(parse(wire(2, 0)), 10);
    expect(cache.get(4294967294, 20)).toBeNull(); expect(cache.get(0, 20)?.sequence).toBe('2');
    cache.push(parse(wire(3, 9000)), 30); expect(cache.get(4294967295, 40)).toBeNull();
    expect(cache.get(9000, 2031)).toBeNull();
    cache.push(parse(wire()), 3000); expect(cache.get(9000, 2999)).toBeNull();
  });
  it('fails closed on conflicting frame identities sharing one RTP timestamp', () => {
    const cache = new RtpFrameBuffer(); cache.push(parse(wire(1, 9000)), 0);
    expect(() => cache.push(parse(wire(2, 9000)), 10)).toThrow(); expect(cache.get(9000, 10)).toBeNull();
  });
});
