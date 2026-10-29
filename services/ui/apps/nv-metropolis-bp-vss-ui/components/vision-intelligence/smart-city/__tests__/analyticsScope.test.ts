// SPDX-License-Identifier: MIT
import { analyticsScopeLabel } from '../analyticsScope';

it('distinguishes a current prepared run from an earlier event run', () => {
  const scope = { kind: 'scenario', epoch: 'epoch', runId: 'run', suppressed: false };
  expect(analyticsScopeLabel(scope)).toBe('This prepared run');
  expect(analyticsScopeLabel(scope, true)).toBe('Prepared run');
  expect(analyticsScopeLabel(undefined, true)).toBe('Earlier / unspecified scope');
});
it('labels suppression, normal starts and historical per-camera scopes honestly', () => {
  expect(analyticsScopeLabel({ kind: 'settling', suppressed: true })).toBe('Preparing — analytics paused');
  expect(analyticsScopeLabel({ kind: 'normal', startedAt: '2026-10-26T15:00:00Z' })).toMatch(/^Normal traffic since /);
  expect(analyticsScopeLabel({ kind: 'normal', startedAt: 'invalid' })).toBe('Normal traffic');
  expect(analyticsScopeLabel({ kind: 'historical-per-camera', sources: {} })).toBe('Historical scope by camera');
});
