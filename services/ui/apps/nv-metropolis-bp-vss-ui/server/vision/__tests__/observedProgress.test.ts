import { observedProgress } from '../observedProgress';
it('requires advancement and expires even when the same old document remains present', () => {
  expect(observedProgress('camera-a', 100, 30_000, 0)).toBe(false);
  expect(observedProgress('camera-a', 101, 30_000, 10_000)).toBe(true);
  expect(observedProgress('camera-b', 101, 30_000, 10_000)).toBe(false);
  expect(observedProgress('camera-a', 101, 30_000, 40_001)).toBe(false);
});
