// SPDX-License-Identifier: MIT

/** Wait for an Elasticsearch receipt for this exact uploaded source. */
export async function waitForSourceIndex(
  sensorId: string,
  options: { signal: AbortSignal; timeoutMs?: number; pollIntervalMs?: number },
): Promise<void> {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  if (options.signal.aborted) controller.abort();
  options.signal.addEventListener('abort', cancel, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? 30_000);
  const aborted = new Promise<never>((_, reject) => {
    controller.signal.addEventListener('abort', () => reject(new DOMException('Index check cancelled', 'AbortError')), { once: true });
  });
  // The adapter supports legacy name matching. Using only the UUID for both
  // inputs prevents an older upload with the same filename satisfying this one.
  const params = new URLSearchParams({ sensorId, name: sensorId });
  try {
    while (!controller.signal.aborted) {
      try {
        const receipt = await Promise.race([
          fetch(`/api/vision/source-intelligence?${params}`, {
            cache: 'no-store', signal: controller.signal,
          }).then(async response => response.ok ? response.json() : null),
          aborted,
        ]);
        if (!controller.signal.aborted && receipt?.source?.sensorId === sensorId &&
            typeof receipt.semanticSegments === 'number' && receipt.semanticSegments > 0) return;
      } catch (error) {
        if (controller.signal.aborted) throw error;
        // A temporary index/API outage can recover within the same deadline.
      }
      let sleep: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          new Promise<void>(resolve => { sleep = setTimeout(resolve, options.pollIntervalMs ?? 1_000); }),
          aborted,
        ]);
      } finally {
        if (sleep !== undefined) clearTimeout(sleep);
      }
    }
    throw new DOMException('Index check cancelled', 'AbortError');
  } catch (error) {
    if (timedOut) throw new Error('Video saved, but search indexing was not confirmed within 30 seconds. Check the search services, then Retry indexing. Your uploaded video is preserved.');
    throw error;
  } finally {
    clearTimeout(timeout);
    options.signal.removeEventListener('abort', cancel);
  }
}
