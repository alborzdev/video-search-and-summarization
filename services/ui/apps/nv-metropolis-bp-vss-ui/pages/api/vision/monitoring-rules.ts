// SPDX-License-Identifier: MIT

import type {
  MonitoringPoint,
  MonitoringRule,
  MonitoringRuleDraft,
} from '../../../components/vision-intelligence/monitoringRules';
import type { NextApiRequest, NextApiResponse } from 'next';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const STORE_DIR = process.env.VISION_RULES_DIR || '/tmp/vss-vision-intelligence-rules';
const STORE_PATH = path.join(STORE_DIR, 'rules.json');
const VIDEO_ANALYTICS_URL = (
  process.env.VIDEO_ANALYTICS_INTERNAL_URL || 'http://127.0.0.1:8081'
).replace(/\/$/, '');
const AGENT_URL = (
  process.env.VISION_AGENT_INTERNAL_URL || 'http://127.0.0.1:8100/api/v1'
).replace(/\/$/, '');
const ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;
const MANAGED_ID_PREFIX = 'ctai-rule-';

interface CalibrationPoint {
  x: number;
  y: number;
}

interface CalibrationSensor {
  attributes?: Array<{ name: string; value: string }>;
  coordinates?: { x: number; y: number };
  geoLocation?: { lat: number; lng: number };
  globalCoordinates?: CalibrationPoint[];
  id: string;
  imageCoordinates?: CalibrationPoint[];
  origin?: { lat: number; lng: number };
  place?: Array<{ name: string; value: string }>;
  rois?: Array<{
    confinedObjectTypes?: string[];
    id: string;
    restrictedObjectTypes?: string[];
    roiCoordinates: CalibrationPoint[];
    type?: string;
  }>;
  scaleFactor?: number;
  tripwires?: unknown[];
  type?: string;
}

interface Calibration {
  calibrationType?: string;
  osmURL?: string;
  sensors?: CalibrationSensor[];
  version?: string;
}

let mutationQueue: Promise<void> = Promise.resolve();

function exclusive<T>(operation: () => Promise<T>): Promise<T> {
  const previous = mutationQueue;
  let release: () => void = () => undefined;
  mutationQueue = new Promise<void>((resolve) => { release = resolve; });
  return previous.then(operation).finally(release);
}

async function readRules(): Promise<MonitoringRule[]> {
  try {
    const parsed = JSON.parse(await readFile(STORE_PATH, 'utf8')) as unknown;
    return Array.isArray(parsed)
      ? (parsed as MonitoringRule[]).map((rule) => ({
          ...rule,
          analysisProfileId:
            typeof rule.analysisProfileId === 'string'
              ? rule.analysisProfileId
              : rule.engine === 'deepstream'
                ? 'warehouse-safety'
                : 'semantic-search',
        }))
      : [];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}

async function writeRules(rules: MonitoringRule[]): Promise<void> {
  await mkdir(STORE_DIR, { recursive: true });
  const temporary = path.join(STORE_DIR, `.rules-${randomUUID()}.tmp`);
  await writeFile(temporary, `${JSON.stringify(rules, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, STORE_PATH);
}

async function jsonRequest(url: string, init: RequestInit = {}, timeoutMs = 25_000) {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  const text = await response.text();
  let payload: Record<string, any> = {};
  try { payload = text ? JSON.parse(text) as Record<string, any> : {}; } catch { /* use empty */ }
  if (!response.ok) {
    throw new Error(String(payload.message || payload.error || `${url} returned ${response.status}.`));
  }
  return payload;
}

function finitePoint(value: unknown): value is MonitoringPoint {
  if (!value || typeof value !== 'object') return false;
  const point = value as MonitoringPoint;
  return Number.isFinite(point.x) && Number.isFinite(point.y)
    && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1;
}

function validateDraft(value: unknown): MonitoringRuleDraft {
  if (!value || typeof value !== 'object') throw new Error('A monitoring rule is required.');
  const rule = value as MonitoringRuleDraft;
  if (!ID_PATTERN.test(rule.sourceId || '') || !rule.sourceName?.trim()) {
    throw new Error('Choose a valid source.');
  }
  if (!['live', 'recorded'].includes(rule.sourceKind)) throw new Error('Choose a valid source type.');
  if (!['deepstream', 'vlm'].includes(rule.engine)) throw new Error('Choose a valid monitoring engine.');
  if (!ID_PATTERN.test(rule.analysisProfileId || '')) throw new Error('Choose a valid source analysis profile.');
  if (!['area-entry', 'proximity', 'semantic'].includes(rule.kind)) {
    throw new Error('Choose a supported monitoring condition.');
  }
  if (!['active', 'draft', 'paused'].includes(rule.status)) throw new Error('Choose a valid rule status.');
  if (!['critical', 'warning', 'info'].includes(rule.severity)) throw new Error('Choose a valid severity.');
  if (!rule.name?.trim() || rule.name.trim().length > 160) throw new Error('Give the rule a short name.');
  if (!Number.isFinite(rule.cooldownSeconds) || rule.cooldownSeconds < 5 || rule.cooldownSeconds > 3600) {
    throw new Error('Cooldown must be between 5 seconds and 1 hour.');
  }
  if (rule.engine === 'vlm') {
    if (rule.sourceKind !== 'live') throw new Error('Continuous visual rules require a live source.');
    if (!rule.prompt?.trim() || rule.prompt.trim().length > 2000) throw new Error('Describe the visual condition to verify.');
  } else if (!Array.isArray(rule.objectTypes) || !rule.objectTypes.length) {
    throw new Error('Choose at least one object type.');
  }
  if (rule.geometry?.kind === 'polygon') {
    if (!Array.isArray(rule.geometry.points) || rule.geometry.points.length < 3 || !rule.geometry.points.every(finitePoint)) {
      throw new Error('Draw a valid monitoring area with at least three points.');
    }
  } else if (rule.kind === 'area-entry') {
    throw new Error('Draw the area that should be monitored.');
  }
  return {
    ...rule,
    description: String(rule.description || '').trim().slice(0, 500),
    name: rule.name.trim(),
    objectTypes: rule.objectTypes.map((item) => String(item).trim()).filter(Boolean).slice(0, 12),
    prompt: rule.prompt?.trim(),
    sourceName: rule.sourceName.trim().slice(0, 256),
    sourceRuntimeName: rule.sourceRuntimeName?.trim().slice(0, 256),
  };
}

function defaultSensor(sourceId: string): CalibrationSensor {
  return {
    attributes: [
      { name: 'source', value: 'vst' },
      { name: 'frameWidth', value: '1920' },
      { name: 'frameHeight', value: '1080' },
    ],
    coordinates: { x: 0, y: 0 },
    geoLocation: { lat: 0, lng: 0 },
    globalCoordinates: [],
    id: sourceId,
    imageCoordinates: [],
    origin: { lat: 0, lng: 0 },
    place: [],
    rois: [],
    scaleFactor: 1,
    tripwires: [],
    type: 'camera',
  };
}

function asPixels(points: MonitoringPoint[], width: number, height: number): CalibrationPoint[] {
  return points.map((point) => ({
    x: Math.round(point.x * width * 100) / 100,
    y: Math.round(point.y * height * 100) / 100,
  }));
}

async function syncStructuredSource(sourceId: string, rules: MonitoringRule[]): Promise<void> {
  const allActive = rules.filter(
    (rule) => rule.engine === 'deepstream' && rule.status === 'active',
  );
  const active = rules.filter(
    (rule) => rule.sourceId === sourceId && rule.engine === 'deepstream' && rule.status === 'active',
  );
  const calibration = await jsonRequest(
    `${VIDEO_ANALYTICS_URL}/config/calibration?sensorId=${encodeURIComponent(sourceId)}`,
    { cache: 'no-store' },
  ) as Calibration;
  const existing = calibration.sensors?.[0] ?? defaultSensor(sourceId);
  const unmanagedRois = (existing.rois ?? []).filter((roi) => !roi.id.startsWith(MANAGED_ID_PREFIX));
  const managedRois = active
    .filter((rule) => rule.kind === 'area-entry' && rule.geometry.kind === 'polygon')
    .map((rule) => ({
      id: `${MANAGED_ID_PREFIX}${rule.id}`,
      restrictedObjectTypes: rule.objectTypes,
      roiCoordinates: asPixels(
        rule.geometry.points,
        rule.geometry.frameWidth || 1920,
        rule.geometry.frameHeight || 1080,
      ),
      type: 'restricted-area',
    }));
  const attributes = [
    ...(existing.attributes ?? []).filter((entry) => !['frameWidth', 'frameHeight'].includes(entry.name)),
    { name: 'frameWidth', value: String(active[0]?.geometry.frameWidth || 1920) },
    { name: 'frameHeight', value: String(active[0]?.geometry.frameHeight || 1080) },
  ];
  await jsonRequest(`${VIDEO_ANALYTICS_URL}/config/calibration/upsert`, {
    body: JSON.stringify({
      calibrationType: calibration.calibrationType || 'image',
      osmURL: calibration.osmURL || '',
      sensors: [{
        ...defaultSensor(sourceId),
        ...existing,
        attributes,
        id: sourceId,
        rois: [...unmanagedRois, ...managedRois],
        // VST may return a placeholder calibration with an empty sensor type.
        // The analytics schema requires a non-empty value, and spreading that
        // placeholder over our defaults would otherwise invalidate every ROI
        // upsert for the source.
        type: existing.type?.trim() || 'camera',
      }],
      version: calibration.version || '1.0',
    }),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  });

  const proximity = active.find((rule) => rule.kind === 'proximity');
  const app = [
    { name: 'restrictedAreaViolationIncidentEnable', value: allActive.some((rule) => rule.kind === 'area-entry') ? 'true' : 'false' },
    { name: 'restrictedAreaViolationIncidentThreshold', value: '1' },
    { name: 'restrictedAreaViolationIncidentExpirationWindow', value: String(Math.max(1, Math.round(Math.max(...allActive.map((rule) => rule.cooldownSeconds), 30) / 60))) },
    { name: 'proximityViolationIncidentEnable', value: allActive.some((rule) => rule.kind === 'proximity') ? 'true' : 'false' },
  ];
  const sensors = [{
    configs: [
      { name: 'proximityDetectionEnable', value: proximity ? 'true' : 'false' },
      { name: 'proximityDetectionThreshold', value: String(proximity?.threshold.proximityPixels ?? 140) },
      { name: 'proximityDetectionCenterClasses', value: JSON.stringify(proximity?.objectTypes.slice(0, 1) ?? ['Person']) },
      { name: 'proximityDetectionSurroundingClasses', value: JSON.stringify(proximity?.objectTypes.slice(1) ?? ['Forklift']) },
    ],
    id: sourceId,
  }];
  await jsonRequest(`${VIDEO_ANALYTICS_URL}/config/update/behavior-analytics`, {
    body: JSON.stringify({ app, sensors }),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  });
}

async function enableLiveDetection(rule: MonitoringRule): Promise<void> {
  if (rule.sourceKind !== 'live' || rule.engine !== 'deepstream' || rule.status !== 'active') return;
  await jsonRequest(`${AGENT_URL}/rtsp-streams/${encodeURIComponent(rule.sourceId)}/analysis`, {
    body: JSON.stringify({
      action: 'configure',
      analysisProfileId: rule.analysisProfileId,
      name: rule.sourceRuntimeName || rule.sourceName,
    }),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  }, 90_000);
}

interface RuntimeAnalysisProfile {
  detectionEnabled: boolean;
  id: string;
  objectTypes: string[];
  ruleKinds: string[];
}

async function assertProfileSupportsRule(rule: MonitoringRuleDraft): Promise<void> {
  const payload = await jsonRequest(
    `${AGENT_URL}/analysis-profiles/sources/${encodeURIComponent(rule.sourceId)}`,
    { cache: 'no-store' },
  );
  const profile = payload.profile as RuntimeAnalysisProfile | undefined;
  if (!profile || profile.id !== rule.analysisProfileId) {
    throw new Error('The source analysis profile changed. Reopen the rule builder and try again.');
  }
  if (rule.engine === 'vlm') return;
  if (!profile.detectionEnabled || !profile.ruleKinds.includes(rule.kind)) {
    throw new Error(`${profile.id} does not support this structured monitoring rule.`);
  }
  const unsupported = rule.objectTypes.filter((objectType) => !profile.objectTypes.includes(objectType));
  if (unsupported.length > 0) {
    throw new Error(`${profile.id} does not detect: ${unsupported.join(', ')}.`);
  }
}

async function createRule(req: NextApiRequest, res: NextApiResponse) {
  let draft: MonitoringRuleDraft;
  try { draft = validateDraft(req.body); } catch (error) {
    return res.status(422).json({ error: error instanceof Error ? error.message : 'Invalid monitoring rule.' });
  }
  return exclusive(async () => {
    const rules = await readRules();
    if (draft.engine === 'vlm' && rules.some((rule) => rule.engine === 'vlm' && rule.status === 'active')) {
      return res.status(409).json({ error: 'Thor is already focused on one continuous visual rule. Detection-based rules can continue in parallel.' });
    }
    const now = new Date().toISOString();
    const rule: MonitoringRule = {
      ...draft,
      backendStatus: draft.status === 'draft' ? 'pending' : 'active',
      createdAt: now,
      id: randomUUID(),
      updatedAt: now,
    };
    try {
      await assertProfileSupportsRule(rule);
      if (rule.engine === 'deepstream' && rule.status === 'active') {
        await enableLiveDetection(rule);
        await syncStructuredSource(rule.sourceId, [...rules, rule]);
      }
    } catch (error) {
      rule.backendStatus = 'unavailable';
      // A rule that never reached the analytics backend must not count as
      // active or imply that it can emit alerts. Keep it as a visible draft so
      // the operator can resume it after the backend issue is corrected.
      rule.status = 'draft';
      await writeRules([...rules, rule]);
      return res.status(502).json({
        error: error instanceof Error ? error.message : 'The monitoring backend could not apply this rule.',
        rule,
      });
    }
    await writeRules([...rules, rule]);
    res.setHeader('Cache-Control', 'no-store');
    return res.status(201).json({ rule });
  });
}

async function updateRule(req: NextApiRequest, res: NextApiResponse) {
  const id = typeof req.query.id === 'string' ? req.query.id : '';
  if (!ID_PATTERN.test(id)) return res.status(422).json({ error: 'Choose a valid rule.' });
  return exclusive(async () => {
    const rules = await readRules();
    const index = rules.findIndex((rule) => rule.id === id);
    if (index < 0) return res.status(404).json({ error: 'Monitoring rule not found.' });
    const action = (req.body as { action?: string }).action;
    if (action !== 'pause' && action !== 'resume') return res.status(422).json({ error: 'Choose pause or resume.' });
    const next: MonitoringRule = {
      ...rules[index],
      status: action === 'pause' ? 'paused' : 'active',
      updatedAt: new Date().toISOString(),
    };
    const updated = rules.map((rule, ruleIndex) => ruleIndex === index ? next : rule);
    try {
      if (next.engine === 'deepstream') {
        if (action === 'resume') await enableLiveDetection(next);
        await syncStructuredSource(next.sourceId, updated);
      }
      next.backendStatus = action === 'pause' ? 'pending' : 'active';
      updated[index] = next;
      await writeRules(updated);
      return res.status(200).json({ rule: next });
    } catch (error) {
      return res.status(502).json({ error: error instanceof Error ? error.message : 'The rule state could not be applied.' });
    }
  });
}

async function deleteRule(req: NextApiRequest, res: NextApiResponse) {
  const id = typeof req.query.id === 'string' ? req.query.id : '';
  if (!ID_PATTERN.test(id)) return res.status(422).json({ error: 'Choose a valid rule.' });
  return exclusive(async () => {
    const rules = await readRules();
    const target = rules.find((rule) => rule.id === id);
    if (!target) return res.status(404).json({ error: 'Monitoring rule not found.' });
    const remaining = rules.filter((rule) => rule.id !== id);
    try {
      if (target.engine === 'deepstream') await syncStructuredSource(target.sourceId, remaining);
      await writeRules(remaining);
      return res.status(200).json({ deleted: id });
    } catch (error) {
      return res.status(502).json({ error: error instanceof Error ? error.message : 'The rule could not be removed from analytics.' });
    }
  });
}

async function deleteSourceRules(sourceId: string, res: NextApiResponse) {
  if (!ID_PATTERN.test(sourceId)) return res.status(422).json({ error: 'Choose a valid source.' });
  return exclusive(async () => {
    const rules = await readRules();
    const targets = rules.filter((rule) => rule.sourceId === sourceId);
    const remaining = rules.filter((rule) => rule.sourceId !== sourceId);
    try {
      if (targets.some((rule) => rule.engine === 'deepstream')) {
        await syncStructuredSource(sourceId, remaining);
      }
      await writeRules(remaining);
      return res.status(200).json({ deleted: targets.length, sourceId });
    } catch (error) {
      return res.status(502).json({ error: error instanceof Error ? error.message : 'The source rules could not be removed from analytics.' });
    }
  });
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method === 'GET') {
    const sourceId = typeof req.query.sourceId === 'string' ? req.query.sourceId : '';
    const rules = await readRules();
    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({ rules: sourceId ? rules.filter((rule) => rule.sourceId === sourceId) : rules });
  }
  if (req.method === 'POST') return createRule(req, res);
  if (req.method === 'PATCH') return updateRule(req, res);
  if (req.method === 'DELETE') {
    const sourceId = typeof req.query.sourceId === 'string' ? req.query.sourceId : '';
    return sourceId ? deleteSourceRules(sourceId, res) : deleteRule(req, res);
  }
  res.setHeader('Allow', 'GET, POST, PATCH, DELETE');
  return res.status(405).json({ error: 'Method not allowed.' });
}
