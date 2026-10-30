// SPDX-License-Identifier: MIT
import { animateViewChange } from '../viewTransition';

const originalMatchMedia = window.matchMedia;
const originalStart = Object.getOwnPropertyDescriptor(document, 'startViewTransition');
const reducedMotion = (matches: boolean) => {
  window.matchMedia = jest.fn().mockReturnValue({ matches });
};
const installTransition = () => {
  const transitions: Array<{ ready: Promise<void>; finished: Promise<void>; skipTransition: jest.Mock; complete: () => void }> = [];
  const start = jest.fn((update: () => void) => {
    let complete!: () => void;
    const finished = new Promise<void>(resolve => { complete = resolve; });
    const transition = { ready: Promise.resolve(), finished, skipTransition: jest.fn(), complete };
    transitions.push(transition);
    update();
    return transition;
  });
  Object.defineProperty(document, 'startViewTransition', { configurable: true, value: start });
  return { start, transitions };
};
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  if (originalStart) Object.defineProperty(document, 'startViewTransition', originalStart);
  else delete (document as Document & { startViewTransition?: unknown }).startViewTransition;
  delete document.documentElement.dataset.viTransition;
});
it('applies navigation immediately with reduced motion', () => {
  reducedMotion(true);
  const { start } = installTransition();
  const update = jest.fn();
  animateViewChange(update);
  expect(update).toHaveBeenCalledTimes(1);
  expect(start).not.toHaveBeenCalled();
});
it('keeps navigation working when view transitions are unsupported', () => {
  reducedMotion(false);
  Object.defineProperty(document, 'startViewTransition', { configurable: true, value: undefined });
  const update = jest.fn();
  animateViewChange(update);
  expect(update).toHaveBeenCalledTimes(1);
});
it('groups nested parent and workspace updates in one transition', async () => {
  reducedMotion(false);
  const { start, transitions } = installTransition();
  const update = jest.fn();
  animateViewChange(() => animateViewChange(update));
  expect(start).toHaveBeenCalledTimes(1);
  expect(update).toHaveBeenCalledTimes(1);
  transitions[0].complete();
  await transitions[0].finished;
  await Promise.resolve();
  expect(document.documentElement.dataset.viTransition).toBeUndefined();
});
it('interrupts an old animation while retaining the newest navigation', async () => {
  reducedMotion(false);
  const { transitions } = installTransition();
  const first = jest.fn(); const second = jest.fn();
  animateViewChange(first);
  animateViewChange(second);
  expect(transitions[0].skipTransition).toHaveBeenCalledTimes(1);
  expect(first).toHaveBeenCalledTimes(1);
  expect(second).toHaveBeenCalledTimes(1);
  transitions[0].complete();
  await transitions[0].finished;
  await Promise.resolve();
  expect(document.documentElement.dataset.viTransition).toBe('navigation');
  transitions[1].complete();
  await transitions[1].finished;
  await Promise.resolve();
  expect(document.documentElement.dataset.viTransition).toBeUndefined();
});
