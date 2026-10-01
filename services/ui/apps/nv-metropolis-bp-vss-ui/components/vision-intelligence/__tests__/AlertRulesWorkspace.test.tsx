// SPDX-License-Identifier: MIT
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

it('does not present unknown rule counts or an outage as an empty rule catalog', async () => {
  global.fetch = jest.fn(async () => ({ok: false, status:503, json:async()=>({error:'Rules service unavailable'})}));
  render(<AlertRulesWorkspace onManageSources={jest.fn()} vstApiUrl="http://thor.test/vst/api" />);
  expect(screen.getByRole('status')).toHaveTextContent('Checking monitoring rules');
  expect(screen.queryByText('enabled rules')).not.toBeInTheDocument();
  expect(await screen.findByText('Rule counts unavailable')).toBeInTheDocument();
  expect(screen.queryByText('No monitoring rules yet')).not.toBeInTheDocument();
});

import { AlertRulesWorkspace, MonitoringRuleWizard, preferredMonitoringSource } from '../AlertRulesWorkspace';

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

  it('uses warehouse examples for the simulator even when its saved name is from the old hospital scene', async () => {
    global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).includes('?sourceId=') ? { profile: warehouseProfile } : { profiles: [warehouseProfile] } })) as jest.Mock;
    render(<MonitoringRuleWizard onClose={jest.fn()} onCreated={jest.fn()} streams={[{ ...liveCatalog[0].live[0], name: 'Spark Hospital Corridor', url: 'rtsp://camera/digital-twin', sensorId: 'sim' }]} />);
    await screen.findByText(/Warehouse safety · NVIDIA RT-DETR Warehouse/);
    expect(screen.queryByRole('button', { name: 'Medical cart visible' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Forklift visible' }));
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));
    expect(screen.getByRole('textbox', { name: 'Rule name' })).toHaveValue('Forklift visible');
    expect(screen.getByRole('textbox', { name: 'Visual condition' })).toHaveValue('A forklift is clearly visible in the warehouse in any sampled frame. Do not count storage racks or pallets as forklifts.');
    expect((global.fetch as jest.Mock).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it('prefers a connected camera but honors explicit source selection', () => {
    const offline = { ...liveCatalog[0].live[0], sensorId: 'offline', streamId: 'offline', connectionState: 'offline' as const };
    const online = { ...offline, sensorId: 'online', streamId: 'online', connectionState: 'online' as const };
    const recorded = { ...offline, sensorId: 'file', streamId: 'file', url: '', vodUrl: '' };
    expect(preferredMonitoringSource([offline, recorded, online])).toBe(online);
    expect(preferredMonitoringSource([offline, recorded, online], 'offline')).toBe(offline);
    expect(preferredMonitoringSource([offline, recorded])).toBe(recorded);
    expect(preferredMonitoringSource([])).toBeUndefined();
  });

  it('requires a custom condition and keeps the selected visual rule despite detection keywords', async () => {
    global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).includes('?sourceId=') ? { profile: warehouseProfile } : { profiles: [warehouseProfile] } })) as jest.Mock;
    render(<MonitoringRuleWizard onClose={jest.fn()} onCreated={jest.fn()} streams={[{ ...liveCatalog[0].live[0], sensorId: 'live' }]} />);
    await screen.findByText(/Warehouse safety · NVIDIA RT-DETR Warehouse/);
    expect(screen.getByRole('textbox', { name: 'Monitoring intent' })).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: /Custom visual condition/i }));
    expect(screen.getByRole('button', { name: /Continue/i })).toBeDisabled();
    const condition = 'Does any frame show a forklift near the marked entrance? Answer YES or NO.';
    fireEvent.change(screen.getByRole('textbox', { name: 'Monitoring intent' }), { target: { value: condition } });
    fireEvent.click(screen.getByRole('button', { name: /Custom visual condition/i }));
    expect(screen.getByRole('textbox', { name: 'Monitoring intent' })).toHaveValue(condition);
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));
    expect(screen.getByRole('textbox', { name: 'Visual condition' })).toHaveValue(condition);
    expect(screen.queryByText('Image-space proximity')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Repeat cooldown' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    fireEvent.click(screen.getByRole('button', { name: /Unsafe proximity/i }));
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));
    expect(screen.getByRole('combobox', { name: 'Repeat cooldown' })).toBeInTheDocument();
    expect((global.fetch as jest.Mock).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it.each([
    ['offline', 'Camera disconnected — this rule cannot receive live footage.'],
    ['online', 'Camera connected. Check that analysis is running in Live cameras.'],
    ['unknown', 'Camera connection is unconfirmed. Check Live cameras before relying on this rule.'],
  ])('distinguishes an enabled rule from its %s source connection', async (connection, expected) => {
    global.fetch = jest.fn(async input => {
      const url = String(input);
      if (url.endsWith('/v1/live/streams')) return {ok:true,json:async()=>liveCatalog};
      if (url.endsWith('/sensor/status')) return {ok:true,json:async()=>({live:{state:connection}})};
      if (url === '/api/vision/monitoring-rules') return {ok:true,json:async()=>({rules:[{
        id:'rule',name:'Area entry',sourceId:'live',sourceName:'Traffic camera',sourceKind:'live',status:'active',engine:'deepstream',cooldownSeconds:30,severity:'warning',backendStatus:'active'
      }]})};
      return {ok:false,status:404,json:async()=>({})};
    }) as jest.Mock;
    render(<AlertRulesWorkspace onManageSources={jest.fn()} vstApiUrl="http://thor.test/vst/api" />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.getByText('Enabled')).toBeInTheDocument();
  });

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
    fireEvent.change(screen.getByRole('textbox', { name: 'Monitoring intent' }), { target: { value: 'Alert when a pedestrian falls on the crossing' } });
    await waitFor(() => expect(screen.getByRole('button', { name: /Continue/i })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));
    expect(screen.getByRole('textbox', { name: 'Visual condition' })).toHaveValue('Alert when a pedestrian falls on the crossing');
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
    expect(screen.getByRole('button', { name: 'Alert rules' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByText('NVIDIA verification controls')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Live cameras' }));
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
    expect(await screen.findByRole('heading', { name: 'What should VSS watch for?' })).toBeInTheDocument();
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

it('scopes the rule catalog to the supplied source and opens its preselected wizard only on demand', async () => {
  const source = { ...liveCatalog[0].live[0], name: 'Hospital corridor', sensorId: 'hospital', streamId: 'hospital-stream' };
  const other = { ...source, name: 'Other corridor', sensorId: 'other', streamId: 'other-stream' };
  const rule = { engine: 'vlm', status: 'paused', backendStatus: 'pending', severity: 'info', sourceKind: 'live', description: '', cooldownSeconds: 30 };
  global.fetch = jest.fn(async input => {
    const url = String(input);
    const payload = url.endsWith('/v1/live/streams') ? [{ other: [other], hospital: [source] }]
      : url.endsWith('/sensor/status') ? { hospital: { state: 'online' }, other: { state: 'online' } }
      : url.includes('/analysis-profiles?sourceId=') ? { profile: semanticProfile }
      : { rules: [{ ...rule, id: 'hospital-rule', sourceId: 'hospital', sourceName: source.name, name: 'Hospital cart rule' }, { ...rule, id: 'other-rule', sourceId: 'other', sourceName: other.name, name: 'Other cart rule' }] };
    return { ok: true, json: async () => payload } as Response;
  }) as jest.Mock;
  render(<AlertRulesWorkspace source={source} onManageSources={jest.fn()} vstApiUrl="http://video.test" />);
  await screen.findByText('Hospital cart rule');
  expect(screen.queryByText('Other cart rule')).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'New monitoring rule' }));
  await screen.findByRole('dialog');
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Monitoring source' })).toHaveValue('hospital-stream'));
  expect((global.fetch as jest.Mock).mock.calls.some(([, init]) => init?.method && init.method !== 'GET')).toBe(false);
});


it('reports a failed source profile check accurately and recovers on retry without a page refresh', async () => {
  let available = false;
  global.fetch = jest.fn(async input => String(input).includes('?sourceId=')
    ? { ok: available, status: available ? 200 : 503, json: async () => available ? { profile: warehouseProfile } : { error: 'Local analytics unavailable' } }
    : { ok: true, json: async () => ({ profiles: [warehouseProfile] }) });
  const stream = { ...liveCatalog[0].live[0], sensorId: 'live' };
  const props = { onClose: jest.fn(), onCreated: jest.fn() };
  const { rerender } = render(<MonitoringRuleWizard {...props} streams={[stream]} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('analysis profile could not be verified');
  expect(screen.queryByText(/Search-only recordings do not publish object tracks/i)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Continue/i })).toBeDisabled();
  const calls = (global.fetch as jest.Mock).mock.calls.length;
  rerender(<MonitoringRuleWizard {...props} streams={[{ ...stream, connectionState: 'online' }]} />);
  expect((global.fetch as jest.Mock).mock.calls.length).toBe(calls);
  available = true;
  fireEvent.click(screen.getByRole('button', { name: 'Retry profile check' }));
  expect(await screen.findByRole('button', { name: /Object enters an area/i })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: /Continue/i })).toBeEnabled());
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
