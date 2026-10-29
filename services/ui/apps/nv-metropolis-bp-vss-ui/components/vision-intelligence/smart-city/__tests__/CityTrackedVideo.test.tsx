// SPDX-License-Identifier: MIT
import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { CityTrackedVideo } from '../CityTrackedVideo';
import { context, manifest, source, wire } from '../__fixtures__/video';

class Events {
  static current: Events; listeners = new Map<string, Function>(); onerror?: () => void; close = jest.fn();
  constructor(_url: string) { Events.current = this; }
  addEventListener(name: string, callback: Function) { this.listeners.set(name, callback); }
  send(name: string, value: unknown) { this.listeners.get('video-' + name + ':a')?.({ data: JSON.stringify(value) }); }
}
describe('presented WebRTC frame and canvas pairing', () => {
  const oldEvents = global.EventSource; const oldPeer = global.RTCPeerConnection; const oldFetch = global.fetch;
  let present!: (now: number, value: any) => void; let peer: any;
  let imageCopies: { target: HTMLCanvasElement; source: CanvasImageSource }[];
  const draw = { setTransform: jest.fn(), beginPath: jest.fn(), roundRect: jest.fn(), fill: jest.fn(), clearRect: jest.fn(), strokeRect: jest.fn(), fillRect: jest.fn(), fillText: jest.fn(), drawImage: jest.fn() };
  beforeEach(() => {
    jest.useFakeTimers();
    imageCopies = [];
    Object.assign(global, { EventSource: Events, RTCPeerConnection: class {
      constructor() { peer = this; }
      iceGatheringState = 'complete'; localDescription = { sdp: 'v=0\r\n' };
      addTransceiver = jest.fn(); createOffer = jest.fn(async () => ({ type: 'offer', sdp: 'v=0\r\n' }));
      setLocalDescription = jest.fn(async () => {}); setRemoteDescription = jest.fn(async () => {});
      getStats = jest.fn(async () => new Map()); close = jest.fn();
    } });
    Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', { configurable: true, value: jest.fn(callback => { present = callback; return 1; }) });
    Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', { configurable: true, value: jest.fn() });
    jest.spyOn(HTMLVideoElement.prototype, 'videoWidth', 'get').mockReturnValue(1000);
    jest.spyOn(HTMLVideoElement.prototype, 'videoHeight', 'get').mockReturnValue(1000);
    jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
      const target = this;
      return { ...draw, drawImage: (...args: any[]) => { imageCopies.push({ target, source: args[0] }); draw.drawImage(...args); } } as any;
    });
    global.fetch = jest.fn(async () => ({ status: 201, ok: true, headers: { get: () => 'a'.repeat(32) }, text: async () => 'v=0\r\n' })) as any;
  });
  afterEach(() => { cleanup(); jest.useRealTimers(); global.EventSource = oldEvents; global.RTCPeerConnection = oldPeer; global.fetch = oldFetch; });
  it('retains the exact pair across jitter and labels a persistent outage without blanking the pixels', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { unmount } = render(<CityTrackedVideo {...props} />);
    await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire(1, 9000, 100)); });
    expect(peer.setRemoteDescription).toHaveBeenCalled(); expect(draw.strokeRect).not.toHaveBeenCalled();
    act(() => present(10, { rtpTimestamp: 9000 }));
    expect(draw.strokeRect).toHaveBeenLastCalledWith(100, 100, 100, 200);
    expect(reported).toHaveBeenLastCalledWith(expect.objectContaining({ sequence: '1' }));
    await act(async () => Events.current.send('frame', wire(2, 18000, 300)));
    expect(draw.strokeRect).toHaveBeenLastCalledWith(100, 100, 100, 200);
    act(() => present(20, { rtpTimestamp: 18000 }));
    expect(draw.strokeRect).toHaveBeenLastCalledWith(300, 100, 100, 200);
    const draws = draw.drawImage.mock.calls.length;
    act(() => present(30, { rtpTimestamp: 18001 }));
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'true');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-gap-reason', 'metadata-not-received');
    // The new frame is captured offscreen, but the displayed pixels stay put.
    expect(draw.drawImage).toHaveBeenCalledTimes(draws + 1);
    expect(reported).not.toHaveBeenLastCalledWith(null);
    act(() => jest.advanceTimersByTime(500));
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'true');
    const clears = draw.clearRect.mock.calls.length;
    act(() => jest.advanceTimersByTime(1500));
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'false');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-display-state', 'paused');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-display-interruptions', '1');
    expect(draw.clearRect).toHaveBeenCalledTimes(clears);
    expect(screen.getByRole('status')).toHaveTextContent('Video paused');
    expect(reported).toHaveBeenLastCalledWith(null);
    unmount(); await act(async () => {}); expect(Events.current.close).toHaveBeenCalled(); expect(peer.close).toHaveBeenCalled();
    expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/sessions/a/'), expect.objectContaining({ method: 'DELETE', keepalive: true }));
  });
  it('updates both pixels and boxes when metadata arrives within the gap', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire(1, 9000, 100)); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const draws = draw.drawImage.mock.calls.length;
    act(() => present(10, { rtpTimestamp: 18000 }));
    act(() => jest.advanceTimersByTime(50));
    await act(async () => Events.current.send('frame', wire(2, 18000, 300)));
    expect(draw.drawImage).toHaveBeenCalledTimes(draws + 2);
    expect(draw.strokeRect).toHaveBeenLastCalledWith(300, 100, 100, 200);
    act(() => jest.advanceTimersByTime(500));
    expect(reported).toHaveBeenLastCalledWith(expect.objectContaining({ sequence: '2' }));
  });
  it('flushes the latest displayed frame at the map deadline without waiting for another video frame', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire(1, 9000)); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    act(() => jest.advanceTimersByTime(75));
    await act(async () => Events.current.send('frame', wire(2, 18000)));
    act(() => present(75, { rtpTimestamp: 18000 }));
    expect(reported).toHaveBeenLastCalledWith(expect.objectContaining({ sequence: '1' }));
    act(() => jest.advanceTimersByTime(25));
    expect(reported).toHaveBeenLastCalledWith(expect.objectContaining({ sequence: '2' }));
  });
  it('publishes the held matched frame when a later video callback is awaiting metadata at the map deadline', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire(1, 9000)); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    act(() => jest.advanceTimersByTime(75));
    await act(async () => Events.current.send('frame', wire(2, 18000, 300)));
    act(() => present(75, { rtpTimestamp: 18000 }));
    act(() => present(80, { rtpTimestamp: 27000 }));
    act(() => jest.advanceTimersByTime(25));
    expect(reported).toHaveBeenLastCalledWith(expect.objectContaining({ sequence: '2' }));
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '2');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-rtp-timestamp', '18000');
  });
  it('keeps held pixels and boxes together when health props redraw during a metadata gap', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { rerender } = render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire(1, 9000, 100)); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    act(() => present(10, { rtpTimestamp: 18000 }));
    const draws = draw.drawImage.mock.calls.length;
    rerender(<CityTrackedVideo {...props} latestSource={{ ...source, sessionId: 'epoch' }} />);
    expect(draw.drawImage).toHaveBeenCalledTimes(draws);
    expect(draw.strokeRect).toHaveBeenLastCalledWith(100, 100, 100, 200);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '1');
    expect(reported).not.toHaveBeenLastCalledWith(null);
  });
  it('removes obsolete-scope overlays immediately without reconnecting for ordinary health updates', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { rerender } = render(<CityTrackedVideo {...props} />);
    await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(10, { rtpTimestamp: 9000 }));
    const oldPeer = peer;
    rerender(<CityTrackedVideo {...props} latestSource={{ ...source, sessionId: 'other' }} />);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'false');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-gap-reason', 'source-session-changed');
    expect(reported).toHaveBeenLastCalledWith(null); expect(peer).toBe(oldPeer); expect(peer.close).not.toHaveBeenCalled();
  });
  it('clears a held pair immediately when the source session changes during a metadata gap', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { rerender } = render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(10, { rtpTimestamp: 9000 }));
    act(() => present(20, { rtpTimestamp: 18000 }));
    rerender(<CityTrackedVideo {...props} latestSource={{ ...source, sessionId: 'other' }} />);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'false');
    expect(reported).toHaveBeenLastCalledWith(null);
  });
  it('keeps pairing exact captured pixels at 15 FPS when every metadata record trails by three video frames', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const captured = new Map<number, HTMLCanvasElement>();
    const visibleImage = screen.getByLabelText('Matched camera video');
    for (let sequence = 2; sequence <= 40; sequence++) {
      act(() => { jest.advanceTimersByTime(67); present(performance.now(), { rtpTimestamp: sequence * 9000 }); });
      captured.set(sequence, imageCopies[imageCopies.length - 1].target);
      if (sequence > 4) {
        const delayed = sequence - 3;
        await act(async () => Events.current.send('frame', wire(delayed, delayed * 9000, delayed * 10)));
        expect(imageCopies[imageCopies.length - 1]).toEqual({ target: visibleImage, source: captured.get(delayed) });
        expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', String(delayed));
        expect(draw.strokeRect).toHaveBeenLastCalledWith(delayed * 10, 100, 100, 200);
      }
      expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'true');
    }
    expect(reported.mock.calls.some(([frame]) => frame === null)).toBe(false);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-display-interruptions', '0');
    expect(Number(screen.getByLabelText('Frame matched WebRTC tracking overlay').getAttribute('data-video-pending-high-water'))).toBeLessThanOrEqual(5);
  });
  it('never moves backward when metadata arrives out of order or an RTP callback repeats', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    act(() => { jest.advanceTimersByTime(67); present(67, { rtpTimestamp: 18000 }); });
    act(() => { jest.advanceTimersByTime(67); present(134, { rtpTimestamp: 27000 }); });
    await act(async () => Events.current.send('frame', wire(3, 27000, 300)));
    const copies = imageCopies.filter(copy => copy.target === screen.getByLabelText('Matched camera video')).length;
    await act(async () => Events.current.send('frame', wire(2, 18000, 200)));
    act(() => { jest.advanceTimersByTime(67); present(201, { rtpTimestamp: 18000 }); });
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '3');
    expect(imageCopies.filter(copy => copy.target === screen.getByLabelText('Matched camera video'))).toHaveLength(copies);
    expect(draw.strokeRect).toHaveBeenLastCalledWith(300, 100, 100, 200);
  });
  it('retains a healthy pair through an SSE retry or malformed record without reconnecting media', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const clears = draw.clearRect.mock.calls.length;
    act(() => Events.current.onerror?.());
    await act(async () => { Events.current.send('frame', { invalid: true }); Events.current.send('manifest', { sessionId: 'epoch' }); });
    act(() => { jest.advanceTimersByTime(100); present(100, { rtpTimestamp: 18000 }); });
    await act(async () => Events.current.send('frame', wire(2, 18000)));
    expect(peer.close).not.toHaveBeenCalled();
    expect(draw.clearRect).toHaveBeenCalledTimes(clears + 1);
    expect(reported.mock.calls.some(([frame]) => frame === null)).toBe(false);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '2');
  });
  it('marks metadata-only outages paused once and requires sustained exact matches before declaring recovery', async () => {
    const reported = jest.fn(); const status = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: status };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const clears = draw.clearRect.mock.calls.length;
    for (let sequence = 2; sequence <= 36; sequence++) act(() => { jest.advanceTimersByTime(67); present(performance.now(), { rtpTimestamp: sequence * 9000 }); });
    expect(screen.getByRole('status')).toHaveTextContent('Video paused');
    expect(draw.clearRect).toHaveBeenCalledTimes(clears);
    expect(reported.mock.calls.filter(([frame]) => frame === null)).toHaveLength(1);
    expect(Number(screen.getByLabelText('Frame matched WebRTC tracking overlay').getAttribute('data-video-pending-high-water'))).toBeLessThanOrEqual(8);
    for (let sequence = 37; sequence <= 39; sequence++) {
      act(() => { jest.advanceTimersByTime(100); present(performance.now(), { rtpTimestamp: sequence * 9000 }); });
      await act(async () => Events.current.send('frame', wire(sequence, sequence * 9000)));
      if (sequence < 39) expect(screen.getByRole('status')).toHaveTextContent('Video paused');
    }
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-display-state', 'live');
    expect(status).toHaveBeenLastCalledWith('playing');
    expect(reported).toHaveBeenLastCalledWith(expect.objectContaining({ sequence: '39' }));
  });
  it('keeps the last pair visible during a media reconnect and clears it immediately on disable', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { rerender } = render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const clears = draw.clearRect.mock.calls.length;
    act(() => Events.current.send('reset', {}));
    expect(peer.close).toHaveBeenCalled();
    expect(draw.clearRect).toHaveBeenCalledTimes(clears);
    expect(screen.getByRole('status')).toHaveTextContent('Video paused');
    rerender(<CityTrackedVideo {...props} enabled={false} />);
    expect(draw.clearRect).toHaveBeenCalledTimes(clears + 2);
  });
  it('invalidates retained pixels immediately when scope changes during reconnect backoff', async () => {
    const reported = jest.fn(); const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { rerender } = render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    act(() => Events.current.send('reset', {}));
    const clears = draw.clearRect.mock.calls.length;
    rerender(<CityTrackedVideo {...props} latestSource={{ ...source, analyticsScope: { kind: 'normal', epoch: 'next' } }} />);
    expect(draw.clearRect).toHaveBeenCalledTimes(clears + 2);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).not.toHaveAttribute('data-video-sequence');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-gap-reason', 'scope-changed');
  });
  it('does not start a lease timer when negotiation resolves after unmount', async () => {
    const Peer = global.RTCPeerConnection; let finish!: () => void;
    global.RTCPeerConnection = class extends Peer {
      setRemoteDescription = jest.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    } as any;
    const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: jest.fn(), onStatus: jest.fn() };
    const { unmount } = render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    expect(peer.setRemoteDescription).toHaveBeenCalled();
    unmount(); await act(async () => finish());
    expect(jest.getTimerCount()).toBe(0);
  });
  it('ignores an obsolete scope record without clearing the newer scope currently on screen', async () => {
    const scope = { kind: 'normal', epoch: 'current' }; const reported = jest.fn();
    const scoped = (sequence: number, epoch: string) => {
      const frame = wire(sequence, sequence * 9000);
      frame.snapshot.analyticsScope = { kind: 'normal', epoch };
      frame.snapshot.sources[0].analyticsScope = frame.snapshot.analyticsScope;
      return frame;
    };
    const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true, latestSource: { ...source, sessionId: 'epoch', analyticsScope: scope },
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: reported, onStatus: jest.fn() };
    const { rerender } = render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', scoped(1, 'current')); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const clears = draw.clearRect.mock.calls.length;
    act(() => { jest.advanceTimersByTime(100); present(100, { rtpTimestamp: 18000 }); });
    await act(async () => Events.current.send('frame', scoped(2, 'old')));
    expect(draw.clearRect).toHaveBeenCalledTimes(clears);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '1');
    expect(reported.mock.calls.some(([frame]) => frame === null)).toBe(false);
    rerender(<CityTrackedVideo {...props} latestSource={{ ...props.latestSource, analyticsScope: { kind: 'normal', epoch: 'next' } }} />);
    expect(draw.clearRect).toHaveBeenCalledTimes(clears + 2);
    expect(reported).toHaveBeenLastCalledWith(null);
  });
  it('rejects metadata for an expired captured image and does not mistake repeated old pixels for recovery', async () => {
    const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: jest.fn(), onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    act(() => { jest.advanceTimersByTime(100); present(100, { rtpTimestamp: 18000 }); });
    act(() => jest.advanceTimersByTime(1700));
    await act(async () => Events.current.send('frame', wire(2, 18000)));
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '1');
    for (let i = 0; i < 5; i++) act(() => { jest.advanceTimersByTime(100); present(performance.now(), { rtpTimestamp: 9000 }); });
    expect(screen.getByRole('status')).toHaveTextContent('Video paused');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-matched', 'false');
  });
  it('survives a transient raw-video canvas capture error and continues requesting video frames', async () => {
    const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: jest.fn(), onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    draw.drawImage.mockImplementationOnce(() => { throw new Error('Video is briefly not drawable.'); });
    act(() => { jest.advanceTimersByTime(100); present(100, { rtpTimestamp: 18000 }); });
    await act(async () => Events.current.send('frame', wire(3, 27000)));
    act(() => { jest.advanceTimersByTime(100); present(200, { rtpTimestamp: 27000 }); });
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '3');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-capture-errors', '1');
    expect(HTMLVideoElement.prototype.requestVideoFrameCallback).toHaveBeenCalledTimes(4);
  });
  it('retries a temporary lease failure without restarting healthy media', async () => {
    const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: jest.fn(), onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    (fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 503 });
    for (let sequence = 2; sequence <= 34; sequence++) {
      await act(async () => { Events.current.send('frame', wire(sequence, sequence * 9000)); present(performance.now(), { rtpTimestamp: sequence * 9000 }); jest.advanceTimersByTime(1000); });
    }
    expect(peer.close).not.toHaveBeenCalled();
    expect((fetch as jest.Mock).mock.calls.filter(([, options]) => options.method === 'PUT')).toHaveLength(2);
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-lease-state', 'renewed');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-display-interruptions', '0');
  });
  it('reconnects before its lease expires when all bounded renewal retries fail', async () => {
    const props = { sourceId: 'a', context, expectedSession: 'epoch', enabled: true,
      selectedTrack: null, editing: false, fillFrame: false, color: '#37d5c1', onSelect: jest.fn(), onPresented: jest.fn(), onStatus: jest.fn() };
    render(<CityTrackedVideo {...props} />); await act(async () => {});
    await act(async () => { Events.current.send('manifest', manifest); Events.current.send('frame', wire()); });
    act(() => present(0, { rtpTimestamp: 9000 }));
    const original = peer;
    (fetch as jest.Mock).mockResolvedValue({ ok: false, status: 503 });
    for (let sequence = 2; sequence <= 76; sequence++) {
      await act(async () => { Events.current.send('frame', wire(sequence, sequence * 9000)); present(performance.now(), { rtpTimestamp: sequence * 9000 }); jest.advanceTimersByTime(1000); });
    }
    expect(original.close).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('Video paused');
    expect(screen.getByLabelText('Frame matched WebRTC tracking overlay')).toHaveAttribute('data-video-sequence', '76');
  });
});
