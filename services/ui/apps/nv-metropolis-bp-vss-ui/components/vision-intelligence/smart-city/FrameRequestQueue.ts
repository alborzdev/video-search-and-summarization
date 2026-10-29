// SPDX-License-Identifier: MIT
/** One request at a time, with only the newest pending frame retained. */
export class FrameRequestQueue<T> {
  private pending: { value: T } | null = null;
  private active: { controller: AbortController; timeout: ReturnType<typeof setTimeout> } | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private lastStarted = -Infinity;
  constructor(private readonly work: (value: T, signal: AbortSignal) => Promise<void>, private readonly onTimeout?: () => void) {}
  enqueue(value: T, force = false) {
    this.pending = { value };
    if (force) { this.abortActive(); this.clearTimer(); this.lastStarted = -Infinity; }
    this.pump();
  }
  clear() {
    this.pending = null; this.clearTimer(); this.abortActive(); this.lastStarted = -Infinity;
  }
  private clearTimer() { if (this.timer !== null) clearTimeout(this.timer); this.timer = null; }
  private abortActive() {
    const active = this.active; this.active = null;
    if (active) { clearTimeout(active.timeout); active.controller.abort(); }
  }
  private pump() {
    if (this.active || !this.pending) return;
    const remaining = Math.ceil(85 - (performance.now() - this.lastStarted));
    if (remaining > 0) {
      if (this.timer === null) this.timer = setTimeout(() => { this.timer = null; this.pump(); }, remaining);
      return;
    }
    this.clearTimer();
    const { value } = this.pending; this.pending = null; this.lastStarted = performance.now();
    const controller = new AbortController();
    const active: { controller: AbortController; timeout: ReturnType<typeof setTimeout> } = { controller, timeout: setTimeout(() => {
      if (this.active !== active) return;
      this.active = null; controller.abort('timeout'); this.onTimeout?.(); this.pump();
    }, 5000) };
    this.active = active;
    void Promise.resolve().then(() => { if (!controller.signal.aborted) return this.work(value, controller.signal); })
      .catch(() => { /* The caller reports request failures; cancellation cannot strand the queue. */ })
      .finally(() => {
        if (this.active !== active) return;
        clearTimeout(active.timeout); this.active = null; this.pump();
      });
  }
}
