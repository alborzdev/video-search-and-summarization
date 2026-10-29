// SPDX-License-Identifier: MIT
import { subscribeCityEvent } from '../cityEvents';
class Events {
  static instances: Events[] = [];
  listeners = new Map<string, Function>();
  onmessage?: Function; onopen?: Function; onerror?: Function;
  close = jest.fn();
  constructor(public url: string) { Events.instances.push(this); }
  addEventListener(type: string, callback: Function) { this.listeners.set(type, callback); }
  send(type: string, value: unknown) { this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(value) })); }
}
const flush = async () => { await Promise.resolve(); };
it('shares one connection across health and two cameras; replays only bounded static manifests and retires old events', async () => {
  const original = global.EventSource; global.EventSource = Events as any;
  const stops: (() => void)[] = [];
  try {
    const health = jest.fn(), a = jest.fn(), b = jest.fn();
    stops.push(subscribeCityEvent('snapshot', health), subscribeCityEvent('video-manifest:a', a), subscribeCityEvent('video-frame:a', a),
      subscribeCityEvent('video-manifest:b', b), subscribeCityEvent('video-frame:b', b));
    await flush(); expect(Events.instances).toHaveLength(1);
    const first = Events.instances[0]; expect(first.url).toBe('/api/vision/city/stream?video=1');
    first.send('video-manifest:a', { key: 'epoch-a' }); first.send('video-frame:a', { sequence: 1 });
    first.send('video-manifest:b', { key: 'epoch-b' }); first.send('video-frame:b', { sequence: 2 });
    expect(a).toHaveBeenCalledTimes(2); expect(b).toHaveBeenCalledTimes(2);
    const replay = jest.fn(), noFrameReplay = jest.fn();
    stops.push(subscribeCityEvent('video-manifest:a', replay), subscribeCityEvent('video-frame:a', noFrameReplay));
    await flush(); expect(replay).toHaveBeenCalledTimes(1); expect(noFrameReplay).not.toHaveBeenCalled();
    while (stops.length > 1) stops.pop()!();
    await flush(); expect(first.close).toHaveBeenCalledTimes(1); expect(Events.instances).toHaveLength(2);
    expect(Events.instances[1].url).toBe('/api/vision/city/stream');
    first.send('snapshot', { sequence: 'obsolete' }); expect(health).not.toHaveBeenCalled();
  } finally { stops.forEach(stop => stop()); await flush(); global.EventSource = original; }
  expect(Events.instances[1].close).toHaveBeenCalledTimes(1);
});

it('refreshes the shared manifest stream for a camera mounted after the initial SSE handshake', async () => {
  const original = global.EventSource; global.EventSource = Events as any; Events.instances = [];
  const stops: (() => void)[] = [];
  try {
    const a = jest.fn(), b = jest.fn();
    stops.push(subscribeCityEvent('video-manifest:a', a)); await flush();
    const first = Events.instances[0]; first.send('video-manifest:a', { key: 'a' });
    stops.push(subscribeCityEvent('video-manifest:b', b)); await flush();
    expect(first.close).toHaveBeenCalledTimes(1); expect(Events.instances).toHaveLength(2);
    const second = Events.instances[1]; second.send('video-manifest:a', { key: 'a' }); second.send('video-manifest:b', { key: 'b' });
    expect(a).toHaveBeenCalledTimes(2); expect(b).toHaveBeenCalledTimes(1);
  } finally { stops.forEach(stop => stop()); await flush(); global.EventSource = original; }
});
