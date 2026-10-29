// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { CityInspector, type CityPanel } from '../CityInspector';
import type { CityEvent, CityMetric, CityRule, CitySite, CitySnapshot } from '../types';
import { observedWindowLabel } from '../answerEvidence';
jest.mock('../CityMobilityPanel', () => ({ CityMobilityPanel: () => <div>Mobility insights</div> }));
const site: CitySite = { id: 'test-city', name: 'Traffic', mode: 'recorded-inference', revision: 1, sources: [{ id: 'citycam', vssSensorId: 'real-vss-id', name: 'Traffic camera', width: 1920, height: 1080 }], map: { bounds: [-50, -50, 50, 50], roads: [], buildings: [] } };
const props = { panel: 'ask' as const, onPanel: jest.fn(), site, snapshot: null, rules: [], selectedEvent: null, selectedTrack: null, onEvent: jest.fn(), onSeek: jest.fn(), onClearSelection: jest.fn(), mediaTime: 6.5 };
describe('city evidence questions', () => {
  it('pages a retained event list without losing export history', async () => {
    const events = Array.from({length:10}, (_,i) => ({id:`saved-${i}`,sourceId:'citycam',mode:site.mode,ruleName:`Saved rule ${i}`,kind:'line-crossing',state:'cleared',trackIds:[],triggeredAt:`2026-10-22T00:00:${String(i).padStart(2,'0')}Z`}));
    global.fetch = jest.fn().mockResolvedValue({ok:true,json:async()=>({events,eventCount:10,truncated:false})});
    render(<CityInspector {...props} panel="reports" />);
    await screen.findByText('1–6 of 10 events');
    expect(screen.queryByText('Saved rule 0')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Next',exact:true}));
    expect(screen.getByText('7–10 of 10 events')).toBeInTheDocument();
    expect(screen.getByText('Saved rule 0')).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Next',exact:true})).toBeDisabled();
  });
  it('sends the actual registered source and displayed playback time to the existing analyst', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ answer: 'A bus passes the junction.', sourceNames: ['Traffic camera'], generatedAt: '2026-10-22T00:00:00Z', evidenceTools: ['inspect_video'] }) });
    render(<CityInspector {...props} />);
    fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What passes the junction?' } });
    fireEvent.click(screen.getByLabelText('Ask visual analyst'));
    expect(await screen.findByText('A bus passes the junction.')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith('/api/vision/analyst', expect.objectContaining({ body: expect.any(String) }));
    const request = JSON.parse((fetch as jest.Mock).mock.calls[0][1].body);
    expect(request.sources[0]).toEqual(expect.objectContaining({ sensorId: 'real-vss-id', streamId: 'real-vss-id', kind: 'replay', playback: expect.objectContaining({ currentTimeSeconds: 6.5 }) }));
    expect(request.lookbackSeconds).toBeUndefined();
  });
  it('shows the upstream failure without generating a canned answer', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Visual analyst is busy.' }) });
    render(<CityInspector {...props} />);
    fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is happening?' } });
    fireEvent.click(screen.getByLabelText('Ask visual analyst'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Visual analyst is busy.'));
    expect(screen.queryByText('View site report')).not.toBeInTheDocument();
  });
  it('exports the durable event history as real structured JSON', async () => {
    const event = { id: 'actual-event-1', sourceId: 'citycam', ruleName: 'Crossing', state: 'cleared', triggeredAt: '2026-10-22T00:00:00Z', message: 'Crossing detected', kind: 'line-crossing', trackIds: [] };
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [event], eventCount: 1, truncated: false }) });
    const create = jest.fn(() => 'blob:report'); const revoke = jest.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: create }); Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoke });
    const download = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<CityInspector {...props} panel="reports" />);
    const button = await screen.findByText('Download site JSON');
    await waitFor(() => expect(button).not.toBeDisabled()); fireEvent.click(button);
    const blob = create.mock.calls[0][0] as Blob;
    const text = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(blob); });
    expect(screen.getByText('Measured events')).toBeInTheDocument();
    expect(screen.getByText('Report exports')).toBeInTheDocument();
    expect(JSON.parse(text)).toEqual(expect.objectContaining({ historyScope: 'site', eventCount: 1, events: [expect.objectContaining({ id: 'actual-event-1' })], mode: 'recorded-inference' }));
    expect(download).toHaveBeenCalledTimes(1); download.mockRestore();
  });
  it('disables questions on synthetic geometry rather than submitting a fake sensor', () => {
    global.fetch = jest.fn();
    render(<CityInspector {...props} site={{ ...site, mode: 'fixture-replay' }} />);
    expect(screen.getByText(/Geometry fixtures have no camera video/)).toBeInTheDocument();
    expect(screen.getByLabelText('Question for the visual analyst')).toBeDisabled();
    expect(screen.getByLabelText('Ask visual analyst')).toBeDisabled(); expect(fetch).not.toHaveBeenCalled();
  });
  it('reviews and asks at activation instead of subtracting onset delay twice', () => {
    const event = { id: 'event', sourceId: 'citycam', ruleName: 'People area', kind: 'occupancy-threshold', mode: 'recorded-inference', state: 'active', startedAt: '2025-01-01T00:00:00.200Z', triggeredAt: '2025-01-01T00:00:00.700Z', trackIds: [], metrics: {}, evidence: { status: 'source-recording', mediaTimeSeconds: .19999999999999996 } } as CityEvent;
    const seek = jest.fn(); const panel = jest.fn();
    render(<CityInspector {...props} panel="now" selectedEvent={event} onSeek={seek} onPanel={panel} />);
    expect(screen.getByText('00:00.2')).toBeInTheDocument(); expect(screen.getByText('00:00.7')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review event' })); expect(seek).toHaveBeenLastCalledWith(.7);
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this event' })); expect(seek).toHaveBeenLastCalledWith(.7); expect(panel).toHaveBeenLastCalledWith('ask');
  });

  it('does not display an old camera answer after the site switches to synthetic fixtures', async () => {
    let finish!: (value: unknown) => void;
    global.fetch = jest.fn(() => new Promise(resolve => { finish = resolve; }));
    const { rerender } = render(<CityInspector {...props} />);
    fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is here?' } });
    fireEvent.click(screen.getByLabelText('Ask visual analyst'));
    rerender(<CityInspector {...props} site={{ ...site, mode: 'fixture-replay' }} />);
    await act(async () => { finish({ ok: true, json: async () => ({ answer: 'Old camera evidence', sourceNames: ['Traffic camera'], evidenceTools: [], generatedAt: '2026-10-22T00:00:00Z' }) }); });
    expect(screen.queryByText('Old camera evidence')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Ask visual analyst')).toBeDisabled();
  });

  it('does not show a retired source event as current activity in a replacement site', () => {
    const old = { id: 'old', sourceId: 'retired-camera', mode: 'recorded-inference', state: 'active', kind: 'line-crossing', ruleName: 'Retired crossing', startedAt: '2025-01-01T00:00:00Z', triggeredAt: '2025-01-01T00:00:00Z', metrics: {}, trackIds: [] } as unknown as CityEvent;
    const snapshot = { sources: site.sources, events: [old], metrics: [], rules: [], tracks: [], zones: [] } as unknown as CitySnapshot;
    render(<CityInspector {...props} panel="now" snapshot={snapshot} />);
    expect(screen.getByText('Watching the intersection')).toBeInTheDocument();
    expect(screen.queryByText('Retired crossing')).not.toBeInTheDocument();
  });

  it('labels live event questions as current footage and never seeks processor-relative media time', () => {
    const event = { id: 'live-event', sourceId: 'citycam', ruleName: 'People area', kind: 'occupancy-threshold', mode: 'live', state: 'active', startedAt: '2025-01-01T12:34:56Z', triggeredAt: '2025-01-01T12:34:57Z', trackIds: [], metrics: {}, evidence: { status: 'unavailable', mediaTimeSeconds: 9876 } } as CityEvent;
    const seek = jest.fn(); const panel = jest.fn();
    render(<CityInspector {...props} panel="now" site={{ ...site, mode: 'live' }} selectedEvent={event} onSeek={seek} onPanel={panel} />);
    expect(screen.queryByRole('button', { name: 'Review event' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ask about this event' })).not.toBeInTheDocument();
    expect(screen.getByText('A valid retained source interval is unavailable for this event.')).toBeInTheDocument();
    expect(screen.getByText(new Date(event.triggeredAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }))).toBeInTheDocument();
    expect(screen.queryByText('164:36.0')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ask current camera' })); expect(seek).not.toHaveBeenCalled(); expect(panel).toHaveBeenLastCalledWith('ask');
  });

  it('asks for five seconds explicitly and loads only the answered source/window on a user click', async () => {
    const liveSite: CitySite = { ...site, mode: 'live', sources: [...site.sources, { ...site.sources[0], id: 'other', vssSensorId: 'other-vss-id', name: 'Other camera' }] };
    const result: any = { answer: 'People walk past the traffic.', sourceNames: ['Traffic camera'], generatedAt: '2026-10-22T12:01:00Z', observedWindow: { startTime: '2026-10-22T12:00:00Z', endTime: '2026-10-22T12:00:05Z' } };
    const key = 'a'.repeat(64);
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, json: async () => result }).mockResolvedValue({ ok: true, json: async () => ({ startTime: result.observedWindow.startTime, videoUrl: `/api/vision/evidence-media?key=${key}` }) });
    const { rerender } = render(<CityInspector {...props} site={liveSite} vstApiUrl="http://video.test/vst/api" />);
    fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is moving?' } }); fireEvent.click(screen.getByLabelText('Ask visual analyst'));
    expect(await screen.findByText(result.answer)).toBeInTheDocument(); expect(JSON.parse((fetch as jest.Mock).mock.calls[0][1].body).lookbackSeconds).toBe(5);
    expect(screen.getByText(`Observed video · ${observedWindowLabel(result)}`)).toBeInTheDocument(); expect(screen.getByText('Analyzed source: Traffic camera.')).toBeInTheDocument();
    rerender(<CityInspector {...props} site={liveSite} snapshot={{ sequence: 'new-live-update' } as CitySnapshot} vstApiUrl="http://video.test/vst/api" />);
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' }));
    const video = await screen.findByLabelText('Inspected evidence from Traffic camera'); expect(video).toHaveAttribute('src', `/api/vision/evidence-media?key=${key}`);
    const request = new URL((fetch as jest.Mock).mock.calls[1][0], 'http://localhost');
    expect(request.pathname).toBe('/api/vision/evidence'); expect(request.searchParams.get('sensorId')).toBe('real-vss-id'); expect(request.searchParams.get('startTime')).toBe(result.observedWindow.startTime); expect(request.searchParams.get('endTime')).toBe(result.observedWindow.endTime);
    fireEvent.change(screen.getByLabelText('Visual analyst camera'), { target: { value: 'other' } }); expect(screen.queryByText(result.answer)).not.toBeInTheDocument(); expect(screen.queryByLabelText('Inspected evidence from Traffic camera')).not.toBeInTheDocument();
  });

  it('cancels an unfinished question when the selected camera changes', async () => {
    let finish!: (value: unknown) => void; let signal!: AbortSignal;
    global.fetch = jest.fn((_url, init) => { signal = init!.signal as AbortSignal; return new Promise(resolve => { finish = resolve; }); });
    const liveSite: CitySite = { ...site, mode: 'live', sources: [...site.sources, { ...site.sources[0], id: 'other', name: 'Other camera' }] };
    render(<CityInspector {...props} site={liveSite} />); fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is here?' } }); fireEvent.click(screen.getByLabelText('Ask visual analyst'));
    fireEvent.change(screen.getByLabelText('Visual analyst camera'), { target: { value: 'other' } }); expect(signal.aborted).toBe(true);
    await act(async () => finish({ ok: true, json: async () => ({ answer: 'Late old camera answer', sourceNames: ['Traffic camera'] }) })); expect(screen.queryByText('Late old camera answer')).not.toBeInTheDocument();
  });
  it('cancels a pending question when a map track changes the effective camera', async () => {
    let finish!: (value: unknown) => void; let signal!: AbortSignal;
    global.fetch = jest.fn((_url, init) => { signal = init!.signal as AbortSignal; return new Promise(resolve => { finish = resolve; }); });
    const liveSite: CitySite = { ...site, mode: 'live', sources: [...site.sources, { ...site.sources[0], id: 'other', name: 'Other camera' }] };
    const { rerender } = render(<CityInspector {...props} site={liveSite} />); fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is here?' } }); fireEvent.click(screen.getByLabelText('Ask visual analyst'));
    rerender(<CityInspector {...props} site={liveSite} selectedTrack={{ sourceId: 'other', id: 'other-track' } as any} />); expect(signal.aborted).toBe(true);
    await act(async () => finish({ ok: true, json: async () => ({ answer: 'Late previous track camera', sourceNames: ['Traffic camera'] }) })); expect(screen.queryByText('Late previous track camera')).not.toBeInTheDocument();
  });

  it('aborts pending answer evidence when the site revision changes and ignores its late URL', async () => {
    const result: any = { answer: 'People walk.', sourceNames: ['Traffic camera'], generatedAt: '2026-10-22T12:01:00Z', observedWindow: { startTime: '2026-10-22T12:00:00Z', endTime: '2026-10-22T12:00:05Z' } };
    let finish!: (value: unknown) => void; let signal!: AbortSignal;
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, json: async () => result }).mockImplementation((_url, init) => { signal = init.signal; return new Promise(resolve => { finish = resolve; }); });
    const liveSite: CitySite = { ...site, mode: 'live' }; const { rerender } = render(<CityInspector {...props} site={liveSite} />);
    fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is here?' } }); fireEvent.click(screen.getByLabelText('Ask visual analyst')); await screen.findByText(result.answer);
    fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' })); rerender(<CityInspector {...props} site={{ ...liveSite, revision: 2 }} />); expect(signal.aborted).toBe(true);
    await act(async () => finish({ ok: true, json: async () => ({ videoUrl: `/api/vision/evidence-media?key=${'a'.repeat(64)}` }) }));
    expect(screen.queryByText(result.answer)).not.toBeInTheDocument(); expect(screen.queryByText('Open inspected clip')).not.toBeInTheDocument();
  });
  it('ignores an old-site report body that resolves after the replacement site report', async () => {
    let finishOld!: (value: unknown) => void;
    const current = { id: 'current', sourceId: 'citycam', mode: 'recorded-inference', ruleName: 'Current saved event', kind: 'line-crossing', state: 'cleared', trackIds: [] };
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, json: () => new Promise(resolve => { finishOld = resolve; }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ events: [current], eventCount: 1 }) });
    const { rerender } = render(<CityInspector {...props} panel="reports" />); await act(async () => {});
    rerender(<CityInspector {...props} site={{ ...site, id: 'replacement-city' }} panel="reports" />); await screen.findByText('Current saved event');
    await act(async () => finishOld({ events: [{ ...current, id: 'old', ruleName: 'Obsolete saved event' }], eventCount: 99 }));
    expect(screen.queryByText('Obsolete saved event')).not.toBeInTheDocument(); expect(screen.getByText('Current saved event')).toBeInTheDocument(); expect(screen.getByText('Download site JSON')).not.toBeDisabled();
  });
  it('reloads history when the same site revision changes while Reports stays open', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ events: [], eventCount: 0 }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ events: [{ id: 'new', sourceId: 'citycam', mode: 'recorded-inference', ruleName: 'New revision history', kind: 'line-crossing', state: 'cleared', trackIds: [] }], eventCount: 1 }) });
    const { rerender } = render(<CityInspector {...props} panel="reports" />); await waitFor(() => expect(screen.getByText('Download site JSON')).not.toBeDisabled());
    rerender(<CityInspector {...props} site={{ ...site, revision: 2 }} panel="reports" />); expect(await screen.findByText('New revision history')).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('bounds stalled report loading and exposes a recoverable error', async () => {
    jest.useFakeTimers();
    try {
      global.fetch = jest.fn((_url, init) => new Promise((_resolve, reject) => init!.signal!.addEventListener('abort', () => reject(new Error('aborted')))));
      const { unmount } = render(<CityInspector {...props} panel="reports" />);
      await act(async () => { jest.advanceTimersByTime(10_000); }); expect(screen.getByRole('alert')).toHaveTextContent('Report history request timed out'); expect(screen.getByText('Download site JSON')).toBeDisabled(); unmount();
    } finally { jest.useRealTimers(); }
  });
  it('times out a live question, permits retry, and ignores an old response that arrives late', async () => {
    jest.useFakeTimers();
    try {
      let finishOld!: (value: unknown) => void; let oldSignal!: AbortSignal;
      global.fetch = jest.fn().mockImplementationOnce((_url, init) => {
        oldSignal = init.signal;
        // A late server response must be rejected even when transport cancellation is delayed.
        return new Promise(resolve => { finishOld = resolve; });
      }).mockResolvedValue({ ok: true, json: async () => ({ answer: 'The retry inspected the current camera.', sourceNames: ['Traffic camera'], evidenceTools: [], generatedAt: '2026-10-23T15:00:00Z' }) });
      const { unmount } = render(<CityInspector {...props} site={{ ...site, mode: 'live' }} />);
      fireEvent.change(screen.getByLabelText('Question for the visual analyst'), { target: { value: 'What is moving?' } });
      fireEvent.click(screen.getByLabelText('Ask visual analyst'));
      expect(screen.getByRole('status')).toHaveTextContent('Inspecting video evidence');
      await act(async () => { jest.advanceTimersByTime(89_999); });
      expect(oldSignal.aborted).toBe(false);
      await act(async () => { jest.advanceTimersByTime(1); });
      expect(oldSignal.aborted).toBe(true);
      expect(screen.getByRole('alert')).toHaveTextContent('The visual analyst took too long. Try again.');
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Ask visual analyst')).not.toBeDisabled();
      fireEvent.click(screen.getByLabelText('Ask visual analyst'));
      await act(async () => {});
      expect(screen.getByText('The retry inspected the current camera.')).toBeInTheDocument();
      await act(async () => { finishOld({ ok: true, json: async () => ({ answer: 'Old answer must not replace the retry.', sourceNames: ['Traffic camera'] }) }); });
      expect(screen.queryByText('Old answer must not replace the retry.')).not.toBeInTheDocument();
      expect(screen.getByText('The retry inspected the current camera.')).toBeInTheDocument();
      unmount();
    } finally { jest.useRealTimers(); }
  });
  it('supports roving focus and wrapping Arrow, Home and End tab navigation', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [], eventCount: 0 }) });
    function ControlledInspector() { const [panel, onPanel] = React.useState<CityPanel>('now'); return <CityInspector {...props} panel={panel} onPanel={onPanel} />; }
    render(<ControlledInspector />);
    const now = screen.getByRole('tab', { name: 'Now' }); const ask = screen.getByRole('tab', { name: 'Ask' }); const reports = screen.getByRole('tab', { name: 'Reports' });
    expect(now).toHaveAttribute('tabindex', '0'); expect(ask).toHaveAttribute('tabindex', '-1'); expect(reports).toHaveAttribute('tabindex', '-1'); now.focus();
    const insights = screen.getByRole('tab', { name: 'Insights' });
    fireEvent.keyDown(now, { key: 'ArrowRight' }); expect(insights).toHaveFocus(); expect(insights).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(insights, { key: 'ArrowRight' }); expect(ask).toHaveFocus(); expect(ask).toHaveAttribute('aria-selected', 'true'); expect(ask).toHaveAttribute('tabindex', '0'); expect(now).toHaveAttribute('tabindex', '-1');
    fireEvent.keyDown(ask, { key: 'End' }); expect(reports).toHaveFocus(); expect(reports).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(reports, { key: 'ArrowRight' }); expect(now).toHaveFocus(); expect(now).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(now, { key: 'ArrowLeft' }); expect(reports).toHaveFocus();
    fireEvent.keyDown(reports, { key: 'Home' }); expect(now).toHaveFocus(); expect(now).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel'); expect(panel).toHaveAttribute('aria-labelledby', now.id); expect(now).toHaveAttribute('aria-controls', panel.id);
    await act(async () => {});
  });
  it('uses unique tab and panel relationships for multiple inspector instances', () => {
    render(<><CityInspector {...props} panel="now" /><CityInspector {...props} panel="now" /></>);
    const tabs = screen.getAllByRole('tablist'); const panels = screen.getAllByRole('tabpanel');
    const first = within(tabs[0]).getByRole('tab', { name: 'Now' }); const second = within(tabs[1]).getByRole('tab', { name: 'Now' });
    expect(first.id).not.toBe(second.id); expect(panels[0].id).not.toBe(panels[1].id);
    expect(first).toHaveAttribute('aria-controls', panels[0].id); expect(panels[0]).toHaveAttribute('aria-labelledby', first.id);
    expect(second).toHaveAttribute('aria-controls', panels[1].id); expect(panels[1]).toHaveAttribute('aria-labelledby', second.id);
  });

});

describe('current rule and event presentation', () => {
  const baseRule: CityRule = { id: 'watch', name: 'Loading bay', kind: 'stopped-in-zone', sourceId: 'citycam', classes: ['car'], enabled: true, revision: 1, geometry: { space: 'image-normalized', points: [[0, 0], [1, 0], [1, 1]] }, conditions: {} };
  const baseMetric: CityMetric = { ruleId: 'watch', occupancy: 7, activeEventCount: 0, status: 'normal' };
  function snapshot(rules: CityRule[], metrics: CityMetric[], events: CityEvent[] = []): CitySnapshot {
    return { siteId: site.id, mode: site.mode, timestamp: '2026-10-23T15:00:00Z', sequence: 1, sources: site.sources, tracks: [], zones: [], rules, events, metrics };
  }
  beforeEach(() => { global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [], eventCount: 0 }) }); });

  it.each(['pending', 'clearing'] as const)('shows %s stop evidence without claiming a confirmed active event', status => {
    const stop: CityEvent = { id: 'retained-stop', ruleId: 'watch', sourceId: 'citycam', sessionId: 'actual-session',
      state: 'active', stopEvidenceStatus: status, mode: site.mode, ruleName: 'Loading bay', kind: 'stopped-in-zone',
      triggeredAt: '2026-10-23T15:00:00Z', startedAt: '2026-10-23T15:00:00Z', message: 'Vehicle stopped', trackIds: ['actual-track'],
      metrics: { durationMs: 4000 }, latestMetrics: { durationMs: 7300, durationBasis: 'consecutive-fresh-stopped-observations' } };
    const current = snapshot([baseRule], [{ ...baseMetric, status: 'unknown', evidenceReasons: ['stop-observation-pending'] }], [stop]);
    const { rerender } = render(<CityInspector {...props} panel="now" snapshot={current} />);
    expect(screen.getByRole('heading', { name: 'Checking camera evidence' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '1 active event' })).not.toBeInTheDocument();
    const label = status === 'pending' ? 'Checking evidence' : 'Checking clearance';
    expect(screen.getByRole('button', { name: new RegExp(`Vehicle stopped in the area.*${label}`) })).toBeInTheDocument();
    rerender(<CityInspector {...props} panel="now" snapshot={current} selectedEvent={stop} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(/Unconfirmed time is excluded\./)).toBeInTheDocument();
    expect(screen.getByText('7.3 s')).toBeInTheDocument();
    expect(screen.queryByText('The rule is active.')).not.toBeInTheDocument();
    expect(screen.queryByText('consecutive-fresh-stopped-observations')).not.toBeInTheDocument();
    const confirmed = { ...stop, stopEvidenceStatus: 'confirmed' as const };
    rerender(<CityInspector {...props} panel="now" snapshot={snapshot([], [], [confirmed])} selectedEvent={null} />);
    expect(screen.getByRole('heading', { name: '1 active event' })).toBeInTheDocument();
  });

  it('excludes pending stop evidence from the report confirmed active count', async () => {
    const pending = { id: 'retained-stop', sourceId: 'citycam', state: 'active', stopEvidenceStatus: 'pending', mode: site.mode,
      ruleName: 'Loading bay', kind: 'stopped-in-zone', triggeredAt: '2026-10-23T15:00:00Z', startedAt: '2026-10-23T15:00:00Z', trackIds: [], metrics: {} } as CityEvent;
    render(<CityInspector {...props} panel="reports" snapshot={snapshot([], [], [pending])} />);
    fireEvent.click(screen.getByRole('button', { name: 'active', exact: true })); expect(screen.queryByText('Stop evidence pending')).not.toBeInTheDocument();
    await act(async () => {});
  });

  it('prioritizes missing live observations over an active event retained in the last snapshot', () => {
    const active = { id: 'retained', sourceId: 'citycam', state: 'active', mode: 'live', ruleName: 'Retained crossing', kind: 'line-crossing', triggeredAt: '2026-10-23T15:00:00Z', startedAt: '2026-10-23T15:00:00Z', trackIds: [], metrics: {} } as CityEvent;
    const liveSnapshot = { ...snapshot([], [], [active]), mode: 'live' as const, sources: site.sources.map(source => ({ ...source, status: 'live' })) };
    const { rerender } = render(<CityInspector {...props} panel="now" site={{ ...site, mode: 'live' }} snapshot={liveSnapshot} liveAnalysisReady={false} />);
    expect(screen.getByRole('heading', { name: 'Waiting for observations' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '1 active event' })).not.toBeInTheDocument();
    rerender(<CityInspector {...props} panel="now" site={{ ...site, mode: 'live' }} snapshot={liveSnapshot} liveAnalysisReady />);
    expect(screen.getByRole('heading', { name: '1 active event' })).toBeInTheDocument();
  });

  it('uses reported stale camera status when explicit live readiness is not provided', () => {
    const liveSnapshot = { ...snapshot([], []), mode: 'live' as const, sources: site.sources.map(source => ({ ...source, status: 'waiting-for-frame-clock' })) };
    render(<CityInspector {...props} panel="now" site={{ ...site, mode: 'live' }} snapshot={liveSnapshot} />);
    expect(screen.getByRole('heading', { name: 'Waiting for observations' })).toBeInTheDocument();
    expect(screen.queryByText('Watching the intersection')).not.toBeInTheDocument();
  });

  it('preserves explicit historical event inspection while the live camera is unavailable', () => {
    const historical = { id: 'saved', sourceId: 'citycam', state: 'cleared', mode: 'live', ruleName: 'Historical crossing', kind: 'line-crossing', triggeredAt: '2026-10-23T15:00:00Z', startedAt: '2026-10-23T15:00:00Z', trackIds: [], metrics: {} } as CityEvent;
    render(<CityInspector {...props} panel="now" site={{ ...site, mode: 'live' }} snapshot={snapshot([], [])} liveAnalysisReady={false} selectedEvent={historical} />);
    expect(screen.getByRole('heading', { name: 'Line crossing detected' })).toBeInTheDocument();
    expect(screen.getByText('The event has cleared.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Waiting for observations' })).not.toBeInTheDocument();
  });

  it('marks the report current active count unavailable during a live outage', async () => {
    render(<CityInspector {...props} panel="reports" site={{ ...site, mode: 'live' }} snapshot={snapshot([], [])} liveAnalysisReady={false} />);
    expect(screen.getByText('Retained camera history · Each event keeps its run and scope.')).toBeInTheDocument(); expect(screen.queryByText('Active in view')).not.toBeInTheDocument();
    await act(async () => {});
  });

  it.each(['now', 'reports'] as const)('shows stopped alerts instead of area occupants in %s', async panel => {
    render(<CityInspector {...props} panel={panel} rules={[baseRule]} snapshot={snapshot([baseRule], [baseMetric])} />);
    expect(screen.getByText('No active alerts')).toBeInTheDocument();
    expect(screen.queryByText('7 in area')).not.toBeInTheDocument();
    expect(screen.queryByText('7 present')).not.toBeInTheDocument();
    await act(async () => {});
  });

  it.each(['now', 'reports'] as const)('marks stale rule observations unavailable in %s', async panel => {
    const stale = { ...baseMetric, occupancy: 7, activeEventCount: 2, status: 'unknown' };
    render(<CityInspector {...props} panel={panel} rules={[baseRule]} snapshot={snapshot([baseRule], [stale])} />);
    expect(screen.getByText('Not enough evidence')).toBeInTheDocument();
    expect(screen.queryByText('2 active alerts')).not.toBeInTheDocument();
    expect(screen.queryByText('7 present')).not.toBeInTheDocument();
    await act(async () => {});
  });

  it('shows the reported evidence cause without treating a live rule gap as a disconnected camera', () => {
    const metric = { ...baseMetric, status: 'unknown', evidenceReasons: ['speed-unavailable', 'observation-gap'] };
    const { rerender } = render(<CityInspector {...props} panel="now" rules={[baseRule]} snapshot={snapshot([baseRule], [metric])} />);
    expect(screen.getByText('Not enough evidence')).toBeInTheDocument();
    expect(screen.getByText('Speed is not available yet.')).toBeInTheDocument(); expect(screen.getByText('A gap interrupted object tracking.')).toBeInTheDocument();
    expect(screen.queryByText('Camera observations are delayed.')).not.toBeInTheDocument();
    rerender(<CityInspector {...props} panel="now" rules={[baseRule]} snapshot={snapshot([baseRule], [{ ...baseMetric, evidenceReasons: metric.evidenceReasons }])} />);
    expect(screen.getByText('No active alerts')).toBeInTheDocument();
    expect(screen.queryByText('Speed is not available yet.')).not.toBeInTheDocument();
  });

  it.each(['now', 'reports'] as const)('does not invent a zero crossing count before observations in %s', async panel => {
    const line = { ...baseRule, kind: 'line-crossing' };
    render(<CityInspector {...props} panel={panel} rules={[line]} snapshot={snapshot([line], [])} />);
    expect(screen.getByText('Waiting for observations')).toBeInTheDocument();
    expect(screen.queryByText('0 crossings')).not.toBeInTheDocument();
    await act(async () => {});
  });

  it('labels disabled rules in reports instead of showing their retained counts', async () => {
    const disabled = { ...baseRule, enabled: false, kind: 'occupancy-threshold' };
    render(<CityInspector {...props} panel="reports" rules={[disabled]} snapshot={snapshot([disabled], [baseMetric])} />);
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(screen.queryByText('7 in area')).not.toBeInTheDocument();
    await act(async () => {});
  });

  it('lists the latest event first even when camera event arrays arrive in source order', () => {
    const other = { ...site.sources[0], id: 'other-camera', name: 'Other camera' };
    const multiSite = { ...site, sources: [...site.sources, other] };
    const event = (id: string, sourceId: string, triggeredAt: string): CityEvent => ({ id, sourceId, triggeredAt, startedAt: triggeredAt, ruleId: 'watch', ruleName: id, kind: 'line-crossing', sessionId: 'session', trackIds: [], state: 'cleared', message: id, metrics: {}, mode: site.mode });
    const older = event('Older southwest crossing', 'citycam', '2026-10-23T15:00:00Z');
    const newer = event('New northeast crossing', 'other-camera', '2026-10-23T15:01:00Z');
    render(<CityInspector {...props} panel="now" site={multiSite} snapshot={{ ...snapshot([], [], [older, newer]), sources: multiSite.sources }} />);
    const buttons = screen.getAllByRole('button', { name: /Line crossing detected/ });
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveTextContent('New northeast crossing');
    expect(buttons[1]).toHaveTextContent('Older southwest crossing');
  });
});
