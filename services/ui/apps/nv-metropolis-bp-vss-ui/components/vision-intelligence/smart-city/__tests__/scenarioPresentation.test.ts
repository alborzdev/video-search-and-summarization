// SPDX-License-Identifier: MIT
import { getScenarioPresentation, rulesForScenario } from '../scenarioPresentation';

it.each([
  ['turning-demand', 'movements', 'cam_sw-northbound-line', ['cam_sw-northbound-line', 'mobility-isaac-north-exit', 'mobility-isaac-west-exit', 'mobility-isaac-east-right-exit']],
  ['queue-recovery', 'queues', 'mobility-isaac-northbound-queue', ['mobility-isaac-northbound-queue', 'cam_sw-blocked-crossing']],
  ['pedestrian-service', 'crossings', 'mobility-isaac-east-crossing-measurement', ['mobility-isaac-east-waiting-south', 'mobility-isaac-east-crossing-measurement', 'mobility-isaac-east-waiting-north']],
  ['curb-obstruction', 'curbs', 'mobility-isaac-north-curbside-lane', ['mobility-isaac-north-curbside-lane']],
  ['crossing-obstruction', 'obstructions', 'cam_sw-blocked-crossing', ['cam_sw-blocked-crossing']],
])('selects the configured measurement areas for %s', (id, topic, primaryRuleId, ruleIds) => {
  const scenario = getScenarioPresentation(id);
  expect(scenario).toEqual(expect.objectContaining({ id, topic, primaryRuleId, ruleIds }));
  expect(scenario?.explanation).toBeTruthy();
  expect(ruleIds).toContain(primaryRuleId);
});

it('does not invent a presentation for unknown scenario IDs', () => {
  expect(getScenarioPresentation(null)).toBeNull();
  expect(getScenarioPresentation('not-a-scenario')).toBeNull();
  expect(getScenarioPresentation('constructor')).toBeNull();
});

it('filters existing rules without replacing geometry or revisions', () => {
  const included = { id: 'mobility-isaac-north-curbside-lane', revision: 7, geometry: { points: [[1, 2]] } };
  const other = { id: 'cam_sw-blocked-crossing', revision: 3, geometry: { points: [[3, 4]] } };
  const rules = [included, other];
  const filtered = rulesForScenario(rules, getScenarioPresentation('curb-obstruction')!);
  expect(filtered).toEqual([included]);
  expect(filtered[0]).toBe(included);
  expect(rules).toEqual([included, other]);
});
