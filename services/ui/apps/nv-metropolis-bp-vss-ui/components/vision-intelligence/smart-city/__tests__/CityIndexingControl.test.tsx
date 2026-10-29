// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { CityIndexingControl } from '../CityIndexingControl';
import type { CityCaptureSearch, CityIndexingStatus } from '../cityIndexing';

const sources = [{ id: 'southwest', name: 'Intersection southwest' }, { id: 'northeast', name: 'Intersection northeast' }];
function status(patch: Partial<CityIndexingStatus> = {}): CityIndexingStatus {
  return { sensorId: 'southwest', name: sources[0].name, mode: 'on-demand', state: 'idle', configured: true,
    revision: 1, indexingRequested: false, generationConnected: false, generationManaged: false, sourcePaused: false,
    session: null, cleanup: { status: 'confirmed' }, evidence: { status: 'unverified', documentCount: null, latestTimestamp: null, liveFresh: false },
    searchScope: { available: false, timestampStart: null, timestampEnd: null }, ...patch };
}
const session = { id: 'session-one', requestedAt: '2026-10-26T15:00:00Z', startedAt: '2026-10-26T15:00:01Z',
  deadlineAt: '2026-10-26T15:02:00Z', endedAt: '2026-10-26T15:02:00Z', durationSeconds: 120, state: 'completed' };
const captured = () => status({ state: 'completed', session, evidence: { status: 'indexed-window', documentCount: 10, latestTimestamp: '2026-10-26T15:01:50Z', liveFresh: false },
  searchScope: { available: true, timestampStart: session.startedAt, timestampEnd: session.endedAt } });
const response = (value: unknown, ok = true) => ({ ok, json: async () => value });
beforeEach(() => { global.fetch = jest.fn().mockResolvedValue(response(status())); });
afterEach(() => { jest.useRealTimers(); });
async function open() { fireEvent.click(screen.getByRole('button', { name: 'Search capture' })); await screen.findByText('Ready for a short capture'); }

it('stays idle until opened and names the actual camera before an explicit finite start', async () => {
  render(<CityIndexingControl sources={sources} />);
  expect(global.fetch).not.toHaveBeenCalled();
  await open();
  expect(screen.getByRole('combobox', { name: 'Camera' })).toHaveValue('southwest');
  expect(screen.getByRole('button', { name: 'Find clips' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Index next 2 min' }));
  await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([, init]) => init.method === 'POST')).toBe(true));
  const mutation = (global.fetch as jest.Mock).mock.calls.find(([, init]) => init.method === 'POST');
  expect(JSON.parse(mutation[1].body)).toEqual({ sourceId: 'southwest', name: sources[0].name, action: 'start', durationSeconds: 120 });
  expect(mutation[0]).toBe('/api/vision/city-indexing');
});

it('makes an existing continuous producer visible and switches only after an operator action', async () => {
  (global.fetch as jest.Mock).mockImplementation((_url, init) => Promise.resolve(response(init.method === 'GET' ? status({ mode: 'continuous', state: 'running', generationConnected: true }) : status())));
  render(<CityIndexingControl sources={sources} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  expect(await screen.findByText(/Continuous indexing is active/)).toBeInTheDocument();
  expect((global.fetch as jest.Mock).mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Use short captures' }));
  await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([, init]) => init.method === 'POST')).toBe(true));
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls.find(([, init]) => init.method === 'POST')[1].body)).toMatchObject({ action: 'policy', mode: 'on-demand', sourceId: 'southwest' });
});

it('searches the selected acknowledged session and keeps its immutable result interval', async () => {
  const found: CityCaptureSearch = { sessionId: session.id, scope: { sourceId: 'southwest', sourceName: sources[0].name, timestampStart: session.startedAt, timestampEnd: session.endedAt, executed: true },
    results: [{ sensor_id: 'southwest', video_name: sources[0].name, description: 'A bus at the curb', start_time: '2026-10-26T15:00:30Z', end_time: '2026-10-26T15:00:35Z', screenshot_url: 'http://172.17.0.1:7777/vst/api/v1/replay/stream/southwest/picture?startTime=2026-10-26T15:00:30Z' }] };
  (global.fetch as jest.Mock).mockImplementation((_url, init) => Promise.resolve(response(init.method === 'POST' ? found : captured())));
  const view = jest.fn(); render(<CityIndexingControl sources={sources} onOpenEvidence={view} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  await screen.findByText('Capture ended');
  fireEvent.change(screen.getByLabelText('Find something in this capture'), { target: { value: 'a bus stops' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find clips' }));
  expect(await screen.findByText('1 matching clip')).toBeInTheDocument();
  expect(screen.getByText('A bus at the curb')).toBeInTheDocument();
  expect(document.querySelector('img')).toHaveAttribute('src',expect.stringContaining('/api/vision/vst-image?path='));
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls.find(([, init]) => init.method === 'POST')[1].body)).toEqual({ sourceId: 'southwest', name: sources[0].name, action: 'search', sessionId: session.id, query: 'a bus stops', topK: 6 });
  fireEvent.click(screen.getByRole('button', { name: 'Open clip' }));
  expect(view).toHaveBeenCalledWith(found.results[0]);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('cancels a finite producer without using camera analysis controls', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response(status({ state: 'running', generationConnected: true, session: { ...session, state: 'running', endedAt: null } })));
  render(<CityIndexingControl sources={sources} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Stop capture' }));
  await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([, init]) => init.method === 'POST')).toBe(true));
  expect((global.fetch as jest.Mock).mock.calls.every(([url]) => String(url).startsWith('/api/vision/city-indexing'))).toBe(true);
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls.find(([, init]) => init.method === 'POST')[1].body).action).toBe('cancel');
});

it('does not offer a searchable history from a start acknowledgement alone', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response(status({ state: 'running', generationConnected: true, session: { ...session, state: 'running', endedAt: null } })));
  render(<CityIndexingControl sources={sources} />); fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  await screen.findByText('Indexing this capture');
  expect(screen.getByRole('button', { name: 'Find clips' })).toBeDisabled();
  expect(screen.getByText('Search is ready when clips reach the index.')).toBeInTheDocument();
});

it('changes the selected camera without retaining another camera’s results or status', async () => {
  (global.fetch as jest.Mock).mockImplementation(url => Promise.resolve(response(String(url).includes('northeast') ? status({ sensorId: 'northeast', name: sources[1].name }) : captured())));
  render(<CityIndexingControl sources={sources} />); fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  await screen.findByText('Capture ended');
  fireEvent.change(screen.getByRole('combobox', { name: 'Camera' }), { target: { value: 'northeast' } });
  await screen.findByText('Ready for a short capture');
  expect(screen.queryByText('Capture ended')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Find clips' })).toBeDisabled();
  expect((global.fetch as jest.Mock).mock.calls.some(([url]) => String(url).includes('sourceId=northeast'))).toBe(true);
});

it('offers retry for a failed stop and never presents it as a completed capture', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response(status({ state: 'stop-failed', session, cleanup: { status: 'failed' } })));
  render(<CityIndexingControl sources={sources} />); fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  expect(await screen.findByText('Stop not confirmed')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry stop' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Index next 2 min' })).not.toBeInTheDocument();
});

it('waits for cleanup confirmation before offering another finite start', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response(status({ state: 'stopping', session })));
  render(<CityIndexingControl sources={sources} />); fireEvent.click(screen.getByRole('button', { name: 'Search capture' }));
  expect(await screen.findByText('Stopping indexing')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Index next 2 min' })).toBeDisabled();
});

it('has no background polling after the popover is closed', async () => {
  jest.useFakeTimers(); render(<CityIndexingControl sources={sources} />);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Search capture' })));
  expect(within(screen.getByRole('dialog')).getByText('Ready for a short capture')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close capture search' }));
  const count = (global.fetch as jest.Mock).mock.calls.length;
  await act(async () => jest.advanceTimersByTime(20_000));
  expect(global.fetch).toHaveBeenCalledTimes(count);
});

it('embeds capture controls without a popup and retires selected clip context on camera change', async () => {
  (global.fetch as jest.Mock).mockImplementation(url => Promise.resolve(response(status({sensorId:new URL(String(url),'http://localhost').searchParams.get('sourceId')!}))));
  const changed = jest.fn(); render(<CityIndexingControl inline sources={sources} onSourceChange={changed} />);
  expect(await screen.findByText('Ready for a short capture')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('Describe a moment to find it.')).toBeInTheDocument();
  expect(changed).toHaveBeenLastCalledWith(sources[0].id);
  fireEvent.change(screen.getByLabelText('Camera'), {target:{value:sources[1].id}});
  expect(changed).toHaveBeenLastCalledWith(sources[1].id);
  await screen.findByText('Ready for a short capture');
});

it('formats a camera name only for display and preserves a failed search across successful status refreshes', async () => {
  const registered = {...sources[0],name:'isaac-intersection-southwest'};
  (global.fetch as jest.Mock).mockImplementation((_url,init) => Promise.resolve(init.method === 'GET' ? response(captured()) : response({error:'Search is unavailable.'},false)));
  render(<CityIndexingControl inline sources={[registered]} />);
  await screen.findByText('Capture ended');
  expect(screen.getByRole('option',{name:'Southwest corner'})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Find something in this capture'),{target:{value:'People crossing'}});
  fireEvent.click(screen.getByRole('button',{name:'Find clips',exact:true}));
  await screen.findByRole('alert');
  await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.filter(([,init])=>init.method==='GET').length).toBeGreaterThan(1));
  expect(screen.getByRole('alert')).toHaveTextContent('Search is unavailable.');
  const mutation = (global.fetch as jest.Mock).mock.calls.find(([,init])=>init.method==='POST');
  expect(JSON.parse(mutation[1].body).name).toBe('isaac-intersection-southwest');
  expect(screen.getByRole('button',{name:'Find clips',exact:true})).toBeEnabled();
});
