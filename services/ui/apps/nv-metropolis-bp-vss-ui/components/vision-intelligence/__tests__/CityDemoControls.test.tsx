// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CityDemoControls } from '../smart-city/CityDemoControls';

const requestId = '11111111-2222-4333-8444-555555555555';
const runId = 'native-session:000007';
const catalog = [{ id: 'queue-blockage', title: 'A queue grows, then clears', question: 'Where does the queue end?',
  durationSimSeconds: 78, measurements: ['Observed queue extent'], available: true }];
const normal = { available: true, playing: true, scenario: { active: false, state: 'idle', catalog } };
const preparing = { ...normal, scenario: { ...normal.scenario, active: true, state: 'preparing', runId,
  title: catalog[0].title, scenarioId: catalog[0].id, analyticsBoundary: { ready: false } } };
const ready = { ...preparing, scenario: { ...preparing.scenario, state: 'ready', analyticsBoundary: { ready: true } } };
const running = { ...ready, scenario: { ...ready.scenario, state: 'running' } };
const restored = { ...normal, scenario: { ...normal.scenario, runId, state: 'completed', restored: true, normalFlowVerified: true,
  title: catalog[0].title, scenarioId: catalog[0].id } };
const response = (data: unknown) => ({ ok: true, json: async () => data } as Response);
const commands = () => (fetch as jest.Mock).mock.calls.filter(([, options]) => options?.method === 'POST').map(([, options]) => JSON.parse(options.body));
async function poll(data: unknown) {
  (fetch as jest.Mock).mockResolvedValueOnce(response(data));
  await act(async () => { fireEvent(document, new Event('visibilitychange')); });
}
async function start() { const button = await screen.findByRole('button', { name: catalog[0].title }); await act(async () => { fireEvent.click(button); }); }

beforeEach(() => {
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => requestId });
  global.fetch = jest.fn().mockResolvedValue(response(normal));
});
afterEach(() => jest.restoreAllMocks());

test('one click prepares, waits for camera readiness, and plays the confirmed run once', async () => {
  const started = jest.fn(); const cover = jest.fn(); render(<CityDemoControls onScenarioStarted={started} onPreparationChange={cover} />);
  await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockImplementationOnce(() => { expect(cover).toHaveBeenLastCalledWith(true); return Promise.resolve(response(preparing)); });
  await start(); await screen.findByRole('button', { name: 'Stop' });
  expect(commands()).toEqual([{ operation: 'prepare', scenarioId: catalog[0].id, requestId }]);
  await poll({ ...ready, scenario: { ...ready.scenario, analyticsBoundary: { ready: false } } });
  expect(commands()).toHaveLength(1); expect(started).not.toHaveBeenCalled();
  (fetch as jest.Mock).mockResolvedValueOnce(response(ready)).mockResolvedValueOnce(response(running));
  await act(async () => { fireEvent(document, new Event('visibilitychange')); });
  await waitFor(() => expect(started).toHaveBeenCalledWith(catalog[0].id));
  expect(started).toHaveBeenCalledTimes(1);
  expect(commands()).toEqual([{ operation: 'prepare', scenarioId: catalog[0].id, requestId }, { operation: 'play', runId, requestId }]);
  expect(cover.mock.calls).toEqual([[true], [false], [true], [false]]);
});

test('an immediately ready preparation also starts playback only once', async () => {
  const started = jest.fn(); render(<CityDemoControls onScenarioStarted={started} />);
  await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(ready)).mockResolvedValueOnce(response(running));
  await start(); await waitFor(() => expect(started).toHaveBeenCalledTimes(1));
  expect(commands()).toEqual([{ operation: 'prepare', scenarioId: catalog[0].id, requestId }, { operation: 'play', runId, requestId }]);
});

test('rapid clicks cannot submit multiple preparations', async () => {
  render(<CityDemoControls />); const button = await screen.findByRole('button', { name: catalog[0].title });
  let resolve!: (value: Response) => void;
  (fetch as jest.Mock).mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(button); fireEvent.click(button); fireEvent.click(button);
  expect(commands()).toHaveLength(1);
  await act(async () => resolve(response(preparing)));
});

test('stop during preparation cancels the confirmed run and cannot auto-play it later', async () => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start();
  const stop = await screen.findByRole('button', { name: 'Stop' });
  (fetch as jest.Mock).mockResolvedValueOnce(response({ ...preparing, scenario: { ...preparing.scenario, state: 'recovering' } }));
  fireEvent.click(stop); await screen.findByText('Returning…');
  await poll(restored);
  expect(commands()).toEqual([{ operation: 'prepare', scenarioId: catalog[0].id, requestId }, { operation: 'cancel', runId, requestId }]);
});

test.each([
  { ...ready, scenario: { ...ready.scenario, analyticsBoundary: undefined } },
  { ...ready, scenario: { ...ready.scenario, analyticsBoundary: { ready: 'true' } } },
  { ...ready, playing: false },
])('does not auto-play without explicit readiness and a playing simulator', async data => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start(); await screen.findByRole('button', { name: 'Stop' });
  await poll(data); expect(commands()).toHaveLength(1);
});

test('never auto-plays a different run returned by polling', async () => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start(); await screen.findByRole('button', { name: 'Stop' });
  await poll({ ...ready, scenario: { ...ready.scenario, runId: 'different-run' } });
  expect(commands()).toHaveLength(1);
});

test('failed or unconfirmed preparation does not start playback', async () => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response({ ...preparing, scenario: { ...preparing.scenario, runId: undefined } }));
  await start(); expect(await screen.findByRole('alert')).toHaveTextContent('did not confirm preparation');
  await poll(ready); expect(commands()).toHaveLength(1);
});

test('lost preparation response keeps the cover until a safe state is confirmed', async () => {
  const cover = jest.fn(); render(<CityDemoControls onPreparationChange={cover} />);
  await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockRejectedValueOnce(new Error('Response was lost.')); await start();
  expect(await screen.findByRole('alert')).toHaveTextContent('Response was lost.');
  await poll({ ...normal, available: false, playing: false }); expect(cover.mock.calls).toEqual([[true]]);
  await poll(restored); expect(cover.mock.calls).toEqual([[true], [false]]);
  expect(commands()).toHaveLength(1);
});

test('a ready run discovered on refresh needs an explicit play action', async () => {
  (fetch as jest.Mock).mockResolvedValue(response(ready)); render(<CityDemoControls />);
  fireEvent.click(await screen.findByRole('button', { name: catalog[0].title }));
  expect(commands()).toEqual([]);
  (fetch as jest.Mock).mockResolvedValueOnce(response(running));
  fireEvent.click(screen.getByRole('button', { name: 'Play scenario' }));
  await waitFor(() => expect(commands()).toEqual([{ operation: 'play', runId, requestId }]));
});

test('recovery failure remains visible and retries the same run', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ ...restored, scenario: { ...restored.scenario, state: 'recovery-failed', restored: false, reason: 'action-refused' } }));
  render(<CityDemoControls />); await screen.findByRole('alert', { name: 'Scenario recovery needs attention' });
  (fetch as jest.Mock).mockResolvedValueOnce(response(restored));
  fireEvent.click(screen.getByRole('button', { name: 'Retry recovery' }));
  await waitFor(() => expect(commands()).toEqual([{ operation: 'retry', runId, requestId }]));
});

test('a stale poll cannot replace confirmed preparation', async () => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  let resolve!: (value: Response) => void;
  (fetch as jest.Mock).mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent(document, new Event('visibilitychange'));
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start();
  await screen.findByRole('button', { name: 'Stop' }); await act(async () => resolve(response(normal)));
  expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument();
});

test('a scenario that fails asynchronously shows the reason without reopening controls', async () => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start();
  await poll({ ...restored, scenario: { ...restored.scenario, state: 'failed', reason: 'analytics-boundary-failed' } });
  expect(screen.getByRole('alert')).toHaveTextContent('Fresh camera tracking could not be confirmed.');
  expect(commands()).toHaveLength(1);
});

test('keeps native diagnostic details out of the visitor-facing failure notice', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ ...restored, scenario: { ...restored.scenario, state: 'failed', reason: "Prepared native actor lost its lease: {'character': 'Character_02'}" } }));
  render(<CityDemoControls />);
  expect(await screen.findByRole('alert')).toHaveTextContent('The scenario could not finish. Normal traffic has resumed.');
  expect(screen.queryByText(/Character_02/)).not.toBeInTheDocument();
});

test('an unconfirmed Play hides stale ready controls and covers until fresh recovery status', async () => {
  const cover = jest.fn(); render(<CityDemoControls onPreparationChange={cover} />);
  await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start();
  (fetch as jest.Mock).mockResolvedValueOnce(response(ready)).mockResolvedValueOnce({ ok: false, json: async () => ({ error: 'Prepared actor moved from its validated start' }) });
  await act(async () => { fireEvent(document, new Event('visibilitychange')); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Prepared actor moved');
  expect(screen.getByText('Checking scenario status…')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Play scenario' })).toBeNull();
  expect(cover.mock.calls).toEqual([[true], [false], [true]]);
  await poll(ready);
  expect(cover.mock.calls).toEqual([[true], [false], [true]]);
  await poll({ ...preparing, scenario: { ...preparing.scenario, state: 'recovering' } });
  expect(screen.getByRole('status', { name: 'Scripted scenario status' })).toHaveTextContent('Returning to normal');
  await poll({ ...restored, scenario: { ...restored.scenario, state: 'failed', reason: 'Play was not confirmed' } });
  expect(cover.mock.calls).toEqual([[true], [false], [true], [false]]);
  expect(screen.getByRole('button', { name: 'Start demo' })).toBeEnabled();
  expect(commands()).toEqual([{ operation: 'prepare', scenarioId: catalog[0].id, requestId }, { operation: 'play', runId, requestId }]);
});

test('a lost Play response can confirm the same running scene on a later status without replaying', async () => {
  const started = jest.fn(); render(<CityDemoControls onScenarioStarted={started} />);
  await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing)); await start();
  (fetch as jest.Mock).mockResolvedValueOnce(response(ready)).mockRejectedValueOnce(new Error('Response was lost.'));
  await act(async () => { fireEvent(document, new Event('visibilitychange')); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Response was lost.');
  expect(started).not.toHaveBeenCalled();
  await poll(running); expect(started).toHaveBeenCalledTimes(1);
  expect(started).toHaveBeenCalledWith(catalog[0].id);
  await poll(running); expect(started).toHaveBeenCalledTimes(1);
  expect(commands()).toEqual([{ operation: 'prepare', scenarioId: catalog[0].id, requestId }, { operation: 'play', runId, requestId }]);
});

test('covers synchronously before Play and waits for confirmed running before showing the scene', async () => {
  const cover = jest.fn(); render(<CityDemoControls onPreparationChange={cover} />);
  await screen.findByRole('button', { name: catalog[0].title });
  let finishPlay!: (value: Response) => void;
  (fetch as jest.Mock).mockResolvedValueOnce(response(ready)).mockImplementationOnce(() => {
    expect(cover).toHaveBeenLastCalledWith(true);
    return new Promise<Response>(done => { finishPlay = done; });
  });
  await start();
  expect(commands()).toHaveLength(2);
  expect(cover.mock.calls).toEqual([[true], [false], [true]]);
  await act(async () => finishPlay(response(running)));
  expect(cover.mock.calls).toEqual([[true], [false], [true], [false]]);
});

test('explains when a pedestrian must clear the scene during preparation', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ ...preparing, scenario: { ...preparing.scenario, phase: 'waiting-for-clearance' } }));
  render(<CityDemoControls />);
  expect(await screen.findByRole('status', { name: 'Scripted scenario status' })).toHaveTextContent('Waiting for clear space');
});

test.each([['person-waiting', 'Waiting at the crossing'], ['crossing', 'Group crossing'], ['observing-clearance', 'Watching for clearance']])('shows a clear scene cue for %s', async (phase, label) => {
  (fetch as jest.Mock).mockResolvedValue(response({ ...running, scenario: { ...running.scenario, phase } }));
  render(<CityDemoControls />);
  expect(await screen.findByRole('status', { name: 'Scripted scenario status' })).toHaveTextContent(label);
});

test('selection starts directly with no guide between the visitor and the scene', async () => {
  render(<CityDemoControls />); await screen.findByRole('button', { name: catalog[0].title });
  (fetch as jest.Mock).mockResolvedValueOnce(response(preparing));
  await start();
  expect(commands()).toEqual([{operation:'prepare',scenarioId:catalog[0].id,requestId}]);
  expect(screen.queryByText('The city problem')).not.toBeInTheDocument();
});

test('preparation progress portals into the opaque mount and stop targets the same run', async () => {
  (fetch as jest.Mock).mockResolvedValue(response(preparing));
  const mount=document.createElement('div');document.body.appendChild(mount);
  const {unmount}=render(<CityDemoControls preparationTarget={mount}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Stop and return to traffic'})).toBeEnabled());
  expect(mount).toHaveTextContent('Confirm fresh camera tracking');
  (fetch as jest.Mock).mockResolvedValueOnce(response(restored));
  fireEvent.click(screen.getByRole('button',{name:'Stop and return to traffic'}));
  await waitFor(()=>expect(commands()).toEqual([{operation:'cancel',runId,requestId}]));
  unmount();mount.remove();
});

test('advances preparation to camera tracking while the host is still preparing', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ ...preparing, scenario: { ...preparing.scenario, phase: 'settling' } }));
  const mount = document.createElement('div'); document.body.appendChild(mount);
  const {unmount} = render(<CityDemoControls preparationTarget={mount}/>);
  expect(await screen.findByRole('status', { name: 'Scripted scenario status' })).toHaveTextContent('Preparing camera tracking');
  const steps = screen.getByRole('list', { name: 'Scenario preparation steps' }).children;
  expect(steps[0]).toHaveAttribute('data-state', 'complete');
  expect(steps[1]).toHaveAttribute('data-state', 'working');
  expect(commands()).toEqual([]);
  unmount(); mount.remove();
});

test('one click switches an active scene only after confirmed restoration, keeping the cover throughout', async()=>{
 const crossing={...catalog[0],id:'crossing-occupancy',title:'Crossing occupied'};
 const entries=[...catalog,crossing];
 const withEntries=(value:typeof normal)=>({...value,scenario:{...value.scenario,catalog:entries}});
 let status=withEntries(running);
 const cover=jest.fn();
 (fetch as jest.Mock).mockImplementation((_url,options)=>{
  if(options?.method==='POST'){
   const command=JSON.parse(options.body);
   if(command.operation==='cancel') return Promise.resolve(response(withEntries({...preparing,scenario:{...preparing.scenario,state:'recovering'}})));
   expect(cover).toHaveBeenLastCalledWith(true);
   return Promise.resolve(response(withEntries({...preparing,scenario:{...preparing.scenario,scenarioId:crossing.id,runId:'new-run'}})));
  }
  return Promise.resolve(response(status));
 });
 render(<CityDemoControls onPreparationChange={cover}/>);
 const switchButton=await screen.findByRole('button',{name:crossing.title});
 await waitFor(()=>expect(switchButton).toBeEnabled());
 fireEvent.click(switchButton);
 await waitFor(()=>expect(commands()).toEqual([{operation:'cancel',runId,requestId}]));
 expect(cover.mock.calls).toEqual([[true]]);
 status=withEntries(restored);
 await act(async()=>{fireEvent(document,new Event('visibilitychange'));});
 await waitFor(()=>expect(commands()).toEqual([{operation:'cancel',runId,requestId},{operation:'prepare',scenarioId:crossing.id,requestId}]));
 expect(cover.mock.calls).toEqual([[true]]);
});
