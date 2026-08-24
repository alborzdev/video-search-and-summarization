// SPDX-License-Identifier: MIT

import type { VisionStream } from './types';
import { isLiveStream, streamDisplayName } from './utils';
import type { SourceAnalysisProfile } from './analysisProfiles';

export type MonitoringEngine = 'deepstream' | 'vlm';
export type MonitoringGeometryKind = 'none' | 'polygon' | 'tripwire';
export type MonitoringRuleKind =
  | 'area-entry'
  | 'area-occupancy'
  | 'line-crossing'
  | 'proximity'
  | 'semantic';
export type MonitoringRuleSeverity = 'critical' | 'warning' | 'info';
export type MonitoringRuleStatus = 'active' | 'draft' | 'paused';
export type MonitoringSourceKind = 'live' | 'recorded';

export interface MonitoringPoint {
  x: number;
  y: number;
}

export interface MonitoringGeometry {
  frameHeight: number;
  frameWidth: number;
  kind: MonitoringGeometryKind;
  points: MonitoringPoint[];
}

export interface MonitoringRule {
  analysisProfileId: string;
  backendRuleId?: string;
  backendStatus: 'active' | 'pending' | 'unavailable';
  cooldownSeconds: number;
  createdAt: string;
  description: string;
  engine: MonitoringEngine;
  geometry: MonitoringGeometry;
  id: string;
  kind: MonitoringRuleKind;
  name: string;
  notify: boolean;
  objectTypes: string[];
  prompt?: string;
  severity: MonitoringRuleSeverity;
  sourceId: string;
  sourceKind: MonitoringSourceKind;
  sourceName: string;
  sourceRuntimeName?: string;
  status: MonitoringRuleStatus;
  threshold: {
    count?: number;
    dwellSeconds?: number;
    proximityPixels?: number;
  };
  updatedAt: string;
}

export interface MonitoringRuleDraft {
  analysisProfileId: string;
  cooldownSeconds: number;
  description: string;
  engine: MonitoringEngine;
  geometry: MonitoringGeometry;
  kind: MonitoringRuleKind;
  name: string;
  notify: boolean;
  objectTypes: string[];
  prompt?: string;
  severity: MonitoringRuleSeverity;
  sourceId: string;
  sourceKind: MonitoringSourceKind;
  sourceName: string;
  sourceRuntimeName?: string;
  status: MonitoringRuleStatus;
  threshold: MonitoringRule['threshold'];
}

export interface MonitoringTemplate {
  description: string;
  engine: MonitoringEngine;
  geometry: MonitoringGeometryKind;
  id: MonitoringRuleKind;
  label: string;
  objectTypes: string[];
  prompt?: string;
  supportsRecorded: boolean;
  threshold: MonitoringRule['threshold'];
}

export const MONITORING_TEMPLATES: MonitoringTemplate[] = [
  {
    description: 'Create an incident when a selected object enters a zone you draw.',
    engine: 'deepstream',
    geometry: 'polygon',
    id: 'area-entry',
    label: 'Object enters an area',
    objectTypes: ['Person'],
    supportsRecorded: true,
    threshold: { dwellSeconds: 1 },
  },
  {
    description: 'Detect when selected object types get too close in the camera view.',
    engine: 'deepstream',
    geometry: 'none',
    id: 'proximity',
    label: 'Unsafe proximity',
    objectTypes: ['Person', 'Forklift'],
    supportsRecorded: true,
    threshold: { proximityPixels: 140 },
  },
  {
    description: 'Have Cosmos Reason verify one visually described condition on a live feed.',
    engine: 'vlm',
    geometry: 'none',
    id: 'semantic',
    label: 'Custom visual condition',
    objectTypes: [],
    prompt: 'Alert when a visually important condition requires operator attention.',
    supportsRecorded: false,
    threshold: {},
  },
];

export function sourceToMonitoringTarget(stream: VisionStream) {
  return {
    sourceId: stream.sensorId,
    sourceKind: (isLiveStream(stream) ? 'live' : 'recorded') as MonitoringSourceKind,
    sourceName: streamDisplayName(stream.name),
    sourceRuntimeName: stream.name,
  };
}

export function createMonitoringDraft(
  stream: VisionStream,
  template: MonitoringTemplate = MONITORING_TEMPLATES[0],
  profile?: SourceAnalysisProfile,
): MonitoringRuleDraft {
  const source = sourceToMonitoringTarget(stream);
  const supportedObjects = profile?.objectTypes ?? template.objectTypes;
  const objectTypes = template.id === 'proximity'
    ? [
        supportedObjects.includes('Person') ? 'Person' : supportedObjects[0],
        supportedObjects.includes('Forklift')
          ? 'Forklift'
          : supportedObjects.includes('Car')
            ? 'Car'
            : supportedObjects[1],
      ].filter((value): value is string => Boolean(value))
    : template.objectTypes.filter((value) => supportedObjects.includes(value));
  return {
    ...source,
    analysisProfileId: profile?.id ?? 'warehouse-safety',
    cooldownSeconds: 30,
    description: template.description,
    engine: template.engine,
    geometry: {
      frameHeight: 1080,
      frameWidth: 1920,
      kind: template.geometry,
      points: template.geometry === 'tripwire'
        ? [{ x: 0.3, y: 0.5 }, { x: 0.7, y: 0.5 }]
        : [],
    },
    kind: template.id,
    name: template.label,
    notify: false,
    objectTypes: objectTypes.length > 0 ? objectTypes : supportedObjects.slice(0, 1),
    prompt: template.prompt,
    severity: 'warning',
    status: 'active',
    threshold: { ...template.threshold },
  };
}

export function monitoringRuleIsComplete(rule: MonitoringRuleDraft): boolean {
  if (!rule.name.trim() || !rule.sourceId.trim()) return false;
  if (rule.engine === 'vlm') return Boolean(rule.prompt?.trim()) && rule.sourceKind === 'live';
  if (rule.geometry.kind === 'polygon') return rule.geometry.points.length >= 3;
  if (rule.geometry.kind === 'tripwire') return rule.geometry.points.length >= 2;
  return rule.objectTypes.length > 0;
}

export function monitoringEngineLabel(engine: MonitoringEngine): string {
  return engine === 'deepstream' ? 'Detection + tracking' : 'Visual reasoning';
}

export function ruleMatchesSource(
  rule: Pick<MonitoringRule, 'sourceId' | 'sourceName'>,
  sensorId?: string,
): boolean {
  if (!sensorId) return false;
  const normalize = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '');
  const sensor = normalize(sensorId);
  return [rule.sourceId, rule.sourceName]
    .map(normalize)
    .some((candidate) => candidate === sensor || candidate.includes(sensor) || sensor.includes(candidate));
}
