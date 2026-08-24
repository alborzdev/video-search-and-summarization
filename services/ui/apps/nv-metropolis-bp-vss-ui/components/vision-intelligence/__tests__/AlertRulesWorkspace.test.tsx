// SPDX-License-Identifier: MIT
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import { AlertRulesWorkspace, MonitoringRuleWizard } from '../AlertRulesWorkspace';

const liveCatalog = [{
  live: [{
    isMain: true,
    metadata: {},
    name: 'traffic-intersection-live',
    streamId: 'live-1',
    type: 'Camera',
    url: 'rtsp://camera.local/live',
    vodUrl: 'rtsp://camera.local/live',
  }],
}];

const semanticProfile = {
  description: 'Semantic', detectionEnabled: false, id: 'semantic-search', maxSources: 8,
  modelId: null, modelLabel: 'Cosmos Embed + Cosmos Reason', name: 'Semantic search + Vision Analyst',
  objectTypes: [], ready: true, readyDetail: 'Ready', resourceTier: 'low',
  ruleKinds: ['semantic'], sceneTypes: ['general'], shortName: 'Search only',
};

const warehouseProfile = {
  description: 'Warehouse', detectionEnabled: true, id: 'warehouse-safety', maxSources: 8,
  modelId: 'warehouse', modelLabel: 'NVIDIA RT-DETR Warehouse', name: 'Warehouse safety',
  objectTypes: ['Person', 'Forklift'], ready: true, readyDetail: 'Ready', resourceTier: 'medium',
  ruleKinds: ['area-entry', 'proximity'], sceneTypes: ['warehouse'], shortName: 'Warehouse',
};

describe('AlertRulesWorkspace', () => {
  afterEach(() => jest.restoreAllMocks());

  it('guides an operator through a semantic live rule and persists its backend link', async () => {
    const created = {
      backendRuleId: 'bridge-rule-1', backendStatus: 'active', cooldownSeconds: 30,
      createdAt: '2026-08-20T12:00:00Z', description: 'Visual condition', engine: 'vlm',
      geometry: { frameHeight: 1080, frameWidth: 1920, kind: 'none', points: [] },
      id: 'monitor-rule-1', kind: 'semantic', name: 'Custom visual condition', notify: false,
      objectTypes: [], prompt: 'Alert when a visually important condition requires operator attention.',
      severity: 'warning', sourceId: 'live', sourceKind: 'live', sourceName: 'traffic-intersection-live',
      status: 'active', threshold: {}, updatedAt: '2026-08-20T12:00:00Z',
    };
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/live/streams')) return { ok: true, json: async () => liveCatalog } as Response;
      if (url === '/api/vision/analysis-profiles') return { ok: true, json: async () => ({ profiles: [semanticProfile] }) } as Response;
      if (url.startsWith('/api/vision/analysis-profiles?sourceId=')) return { ok: true, json: async () => ({ profile: semanticProfile }) } as Response;
      if (url === '/api/vision/monitoring-rules' && !init?.method) return { ok: true, json: async () => ({ rules: [] }) } as Response;
      if (url === '/api/vision/live-alert-rules' && init?.method === 'POST') return { ok: true, json: async () => ({ id: 'bridge-rule-1' }) } as Response;
      if (url === '/api/vision/monitoring-rules' && init?.method === 'POST') return { ok: true, status: 201, json: async () => ({ rule: created }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }) as jest.Mock;

    const onCreated = jest.fn();
    render(<MonitoringRuleWizard onClose={jest.fn()} onCreated={onCreated} streams={[{ ...liveCatalog[0].live[0], sensorId: 'live' }]} vstApiUrl="http://thor.test/vst/api" />);

    fireEvent.click(await screen.findByRole('button', { name: /Custom visual condition/i }));
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));
    fireEvent.click(screen.getByRole('button', { name: /Activate monitoring/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    const monitoringPost = (global.fetch as jest.Mock).mock.calls.find(([url, init]) => url === '/api/vision/monitoring-rules' && init?.method === 'POST');
    expect(JSON.parse(String(monitoringPost?.[1]?.body))).toMatchObject({ backendRuleId: 'bridge-rule-1', engine: 'vlm', sourceId: 'live' });
  });

  it('directs operators to source management when no source exists', async () => {
    const onManageSources = jest.fn();
    const onModeChange = jest.fn();
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/vision/analysis-profiles') return { ok: true, json: async () => ({ profiles: [semanticProfile] }) } as Response;
      if (String(input).startsWith('/api/vision/analysis-profiles?sourceId=')) return { ok: true, json: async () => ({ profile: semanticProfile }) } as Response;
      if (String(input).endsWith('/v1/live/streams')) return { ok: true, json: async () => [] } as Response;
      if (String(input) === '/api/vision/monitoring-rules') return { ok: true, json: async () => ({ rules: [] }) } as Response;
      return { ok: true, json: async () => ({}) } as Response;
    }) as jest.Mock;

    render(<AlertRulesWorkspace onManageSources={onManageSources} onModeChange={onModeChange} vstApiUrl="http://thor.test/vst/api" />);
    await screen.findByText('No monitoring rules yet');
    const navigation = screen.getByRole('navigation', { name: 'Monitoring views' });
    expect(navigation.parentElement).toHaveClass('vi-monitoring-workspace');
    expect(screen.getByRole('heading', { name: 'Rules by source' }).closest('.vi-monitoring-content')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rules' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByText('NVIDIA verification controls')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
    expect(onModeChange).toHaveBeenCalledWith('monitor');
    fireEvent.click(screen.getByRole('button', { name: 'Create first rule' }));
    expect(await screen.findByRole('heading', { name: 'Connect a source first' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back to sources' }));
    await waitFor(() => expect(onManageSources).toHaveBeenCalledTimes(1));
  });

  it('initializes the requested source when its catalog arrives after the wizard opens', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/vision/analysis-profiles') return { ok: true, json: async () => ({ profiles: [semanticProfile] }) } as Response;
      if (String(input).startsWith('/api/vision/analysis-profiles?sourceId=')) return { ok: true, json: async () => ({ profile: semanticProfile }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }) as jest.Mock;
    const props = { onClose: jest.fn(), onCreated: jest.fn(), preselectedSourceId: 'live', vstApiUrl: 'http://thor.test/vst/api' };
    const { rerender } = render(<MonitoringRuleWizard {...props} streams={[]} />);
    expect(screen.getByRole('heading', { name: 'Connect a source first' })).toBeInTheDocument();
    rerender(<MonitoringRuleWizard {...props} streams={[{ ...liveCatalog[0].live[0], sensorId: 'live' }]} />);
    expect(await screen.findByRole('heading', { name: 'What should Thor watch for?' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Monitoring source' })).toHaveTextContent('Traffic Intersection Live');
  });

  it('keeps the explicitly selected upload profile while durable source state is pending', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/vision/analysis-profiles') {
        return { ok: true, json: async () => ({ profiles: [semanticProfile, warehouseProfile] }) } as Response;
      }
      if (String(input).startsWith('/api/vision/analysis-profiles?sourceId=')) {
        return { ok: true, json: async () => ({ profile: warehouseProfile }) } as Response;
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }) as jest.Mock;

    render(<MonitoringRuleWizard
      analysisProfileId="semantic-search"
      onClose={jest.fn()}
      onCreated={jest.fn()}
      preselectedSourceId="recorded-new"
      streams={[{
        isMain: true, metadata: {}, name: 'New replay', sensorId: 'recorded-new',
        streamId: 'recorded-new', type: 'file', url: '', vodUrl: '',
      }]}
    />);

    expect(await screen.findByText(/Search-only recordings do not publish object tracks/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Object enters an area/i })).not.toBeInTheDocument();
  });
});
