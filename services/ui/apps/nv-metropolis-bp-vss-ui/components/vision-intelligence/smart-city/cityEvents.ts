// SPDX-License-Identifier: MIT
/** One bounded SSE transport per document, shared by health and both cameras. */
const listeners = new Map<string, Set<EventListener>>();
const manifests = new Map<string, Event>();
let source: EventSource | null = null;
let video = false;
let cameraSet = '';
const attached = new Set<string>();
let scheduled = false;
const dispatch = (type: string, event: Event) => {
  if (type.startsWith('video-manifest:')) {
    manifests.set(type, event);
    if (manifests.size > 2) manifests.delete(manifests.keys().next().value!);
  } else if (type.startsWith('video-reset:')) manifests.delete(type.replace('video-reset:', 'video-manifest:'));
  listeners.get(type)?.forEach(listener => listener(event));
};
function reconcile() {
  const cameras = [...new Set([...listeners.keys()].filter(type => type.startsWith('video-')).map(type => type.slice(type.indexOf(':') + 1)))].sort().join('\0');
  const needsVideo = Boolean(cameras);
  if (!listeners.size) { source?.close(); source = null; manifests.clear(); return; }
  if (source && video === needsVideo && cameraSet === cameras) return;
  // A newly mounted camera needs a fresh manifest before its frames. Reopen
  // the single SSE stream; existing media peers and RTP caches stay alive.
  source?.close(); video = needsVideo; cameraSet = cameras; manifests.clear(); attached.clear();
  source = new EventSource('/api/vision/city/stream' + (video ? '?video=1' : ''));
  const connection = source;
  const deliver = (type: string, event: Event) => { if (source === connection) dispatch(type, event); };
  source.onmessage = event => deliver('message', event);
  source.onopen = event => deliver('open', event);
  source.onerror = event => deliver('error', event);
  for (const type of listeners.keys()) if (!['message', 'open', 'error'].includes(type)) {
    source.addEventListener(type, event => deliver(type, event)); attached.add(type);
  }
}
function schedule() {
  if (scheduled) return;
  scheduled = true;
  void Promise.resolve().then(() => { scheduled = false; reconcile(); });
}
export function subscribeCityEvent(type: string, listener: EventListener): () => void {
  let set = listeners.get(type);
  if (!set) {
    listeners.set(type, set = new Set());
    if (source && !attached.has(type) && !['message', 'open', 'error'].includes(type)) { const connection = source; source.addEventListener(type, event => { if (source === connection) dispatch(type, event); }); attached.add(type); }
  }
  set.add(listener); schedule();
  const cached = manifests.get(type);
  if (cached) void Promise.resolve().then(() => { if (listeners.get(type)?.has(listener)) listener(cached); });
  return () => {
    const current = listeners.get(type); current?.delete(listener);
    if (!current?.size) listeners.delete(type);
    schedule();
  };
}
