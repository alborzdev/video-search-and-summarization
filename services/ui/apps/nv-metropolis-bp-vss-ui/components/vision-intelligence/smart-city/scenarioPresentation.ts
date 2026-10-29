// SPDX-License-Identifier: MIT
import type { InsightTopic } from './CityMobilityPanel';

/**
 * The scene tells a story; these IDs select the existing camera-owned rules
 * that actually measure it. This only changes presentation, never analytics.
 */
export interface ScenarioPresentation {
  id: string;
  title: string;
  explanation: string;
  question: string;
  scene: string;
  value: string;
  topic: InsightTopic;
  primaryRuleId: string;
  ruleIds: readonly string[];
}

const SCENARIOS: Readonly<Record<string, ScenarioPresentation>> = {
  'crossing-occupancy': {
    id: 'crossing-occupancy', title: 'Crossing occupied',
    explanation: 'See who is still crossing and how long the crossing stays occupied.',
    question: 'Is everyone across?', scene: 'Four people cross together through the East crossing.',
    value: 'Measure crossing demand and occupied time to review pedestrian service.',
    topic: 'crossings', primaryRuleId: 'expo-crossing-occupancy', ruleIds: ['expo-crossing-occupancy'],
  },
  'queue-blockage': {
    id: 'queue-blockage', title: 'Queue → blockage',
    explanation: 'Spot the moment a queue takes away space inside the junction.',
    question: 'Roadwork backs traffic into the junction', scene: 'A downstream lane closure slows traffic until the queue reaches the junction.',
    value: 'Locate stopped traffic inside the junction and retain the evidence for review.',
    topic: 'queues', primaryRuleId: 'expo-junction-blockage', ruleIds: ['expo-junction-blockage'],
  },
  'emergency-access': {
    id: 'emergency-access', title: 'Emergency access blocked',
    explanation: 'See stopped traffic blocking an ambulance and save the camera event.',
    question: 'Can the ambulance get through?', scene: 'Traffic builds across an ambulance’s path, then clears.',
    value: 'Flag a blocked junction and save the incident for an operator to act on.',
    topic: 'obstructions', primaryRuleId: 'expo-emergency-blockage', ruleIds: ['expo-emergency-blockage'],
  },
  'turning-demand': {
    id: 'turning-demand',
    title: 'Turning traffic',
    explanation: 'Count observed turns to understand where traffic goes.',
    question: 'Where does traffic go?',
    scene: 'Vehicles approach and take different turns.',
    value: 'Use movement counts to review lanes and signal timing.',
    topic: 'movements',
    primaryRuleId: 'cam_sw-northbound-line',
    ruleIds: ['cam_sw-northbound-line', 'mobility-isaac-north-exit', 'mobility-isaac-west-exit', 'mobility-isaac-east-right-exit'],
  },
  'queue-recovery': {
    id: 'queue-recovery',
    title: 'Queue build-up',
    explanation: 'Measure the observed queue and check crossing access.',
    question: 'Where is traffic backing up?',
    scene: 'A queue forms on the south approach.',
    value: 'Find approaches where traffic may need more capacity.',
    topic: 'queues',
    primaryRuleId: 'mobility-isaac-northbound-queue',
    ruleIds: ['mobility-isaac-northbound-queue', 'cam_sw-blocked-crossing'],
  },
  'pedestrian-service': {
    id: 'pedestrian-service',
    title: 'Pedestrian crossing',
    explanation: 'Measure observed waiting and crossings to understand pedestrian demand.',
    question: 'How are people using the crossing?',
    scene: 'A person waits, then crosses the street.',
    value: 'Understand pedestrian demand and review crossing service.',
    topic: 'crossings',
    primaryRuleId: 'mobility-isaac-east-crossing-measurement',
    ruleIds: ['mobility-isaac-east-waiting-south', 'mobility-isaac-east-crossing-measurement', 'mobility-isaac-east-waiting-north'],
  },
  'curb-obstruction': {
    id: 'curb-obstruction',
    title: 'Curb stop',
    explanation: 'See how long vehicles occupy the curbside lane.',
    question: 'Is curb access available?',
    scene: 'A vehicle stops in the curbside lane.',
    value: 'See how long curb space stays occupied.',
    topic: 'curbs',
    primaryRuleId: 'mobility-isaac-north-curbside-lane',
    ruleIds: ['mobility-isaac-north-curbside-lane'],
  },
  'crossing-obstruction': {
    id: 'crossing-obstruction',
    title: 'Blocked crossing',
    explanation: 'Detect stopped vehicles in the crossing and check when it clears.',
    question: 'Is the crossing blocked?',
    scene: 'A vehicle stops across the crosswalk.',
    value: 'Help operators find and review blocked access.',
    topic: 'obstructions',
    primaryRuleId: 'cam_sw-blocked-crossing',
    ruleIds: ['cam_sw-blocked-crossing'],
  },
};

export function getScenarioPresentation(id: string | null | undefined): ScenarioPresentation | null {
  // Avoid inherited Object properties being mistaken for a configured scenario.
  return id && Object.prototype.hasOwnProperty.call(SCENARIOS, id) ? SCENARIOS[id] : null;
}

/** Keep the current frame's own rule objects, including geometry and revision. */
export function rulesForScenario<T extends { id: string }>(rules: readonly T[], presentation: ScenarioPresentation): T[] {
  const selected = new Set(presentation.ruleIds);
  return rules.filter(rule => selected.has(rule.id));
}
