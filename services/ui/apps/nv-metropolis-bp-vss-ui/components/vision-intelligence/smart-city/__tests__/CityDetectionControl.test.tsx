// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CityDetectionControl } from '../CityDetectionControl';
const status = (state = 'stopped') => ({ schemaVersion: 'city.detections.v1', state, ready: true, detail: 'Ready',
  sources: [{ id: 'a', name: 'Camera A' }, { id: 'b', name: 'Camera B' }], lastExitCode: state === 'stopped' ? 1 : null });
const response = (value: unknown, ok = true) => ({ ok, json: async () => value });
beforeEach(() => { global.fetch = jest.fn().mockResolvedValue(response(status())); });
afterEach(() => { jest.restoreAllMocks(); });
it('offers a visible start after a failed worker without starting anything automatically', async () => {
  render(<CityDetectionControl siteId="city" analyzedCount={0} />);
  expect(await screen.findByText('Detections stopped')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start detections' })).toBeEnabled();
  expect((fetch as jest.Mock).mock.calls.every(([, options]) => options.method !== 'POST')).toBe(true);
});
it('starts once and distinguishes running detections from preview readiness', async () => {
  let complete!: (value: unknown) => void;
  (fetch as jest.Mock).mockImplementation((_url, options) => options.method === 'POST'
    ? new Promise(resolve => { complete = resolve; }) : Promise.resolve(response(status())));
  const changed = jest.fn(); const { rerender } = render(<CityDetectionControl siteId="city" analyzedCount={0} onChanged={changed} />);
  const start = await screen.findByRole('button', { name: 'Start detections' });
  await waitFor(() => expect(start).toBeEnabled()); fireEvent.click(start); fireEvent.click(start);
  expect(screen.getByText('Connecting detections…')).toBeInTheDocument();
  expect((fetch as jest.Mock).mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1);
  (fetch as jest.Mock).mockResolvedValue(response(status('running')));
  await act(async () => { complete(response(status('running'))); });
  expect(await screen.findByText('Detections on · 2 cameras')).toBeInTheDocument();
  expect(screen.getByText('Waiting for camera previews · detections remain on')).toBeInTheDocument(); expect(changed).toHaveBeenCalledTimes(1);
  rerender(<CityDetectionControl siteId="city" analyzedCount={2} onChanged={changed} />);
  expect(screen.getByText('Detections on · 2 cameras')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reconnect detections' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Stop detections' }));
  await waitFor(() => expect((fetch as jest.Mock).mock.calls.some(([, options]) => options.body === JSON.stringify({ action: 'stop' }))).toBe(true));
});

it('does not flash the detector status or its indicator when preview readiness changes', async () => {
  (fetch as jest.Mock).mockResolvedValue(response(status('running')));
  const { rerender } = render(<CityDetectionControl siteId="city" analyzedCount={2} />);
  const label = await screen.findByText('Detections on · 2 cameras');
  for (const count of [0, 1, 2, 0, 2]) {
    rerender(<CityDetectionControl siteId="city" analyzedCount={count} />);
    expect(label).toHaveTextContent('Detections on · 2 cameras');
    expect(screen.getByLabelText('Detection controls').querySelector('[data-active]')).toHaveAttribute('data-active', 'true');
  }
  rerender(<CityDetectionControl siteId="city" analyzedCount={0} disabled />);
  expect(screen.getByText('Preparing scenario…')).toBeInTheDocument();
  expect(screen.queryByText(/After restarting/)).not.toBeInTheDocument();
});

it('keeps the last explicit paused state when a health poll fails', async () => {
  jest.useFakeTimers();
  try {
    const onStatusChange = jest.fn();
    (fetch as jest.Mock).mockResolvedValue(response(status('paused')));
    render(<CityDetectionControl siteId="city" analyzedCount={0} onStatusChange={onStatusChange} />);
    await act(async () => {});
    expect(onStatusChange).toHaveBeenLastCalledWith('paused');
    (fetch as jest.Mock).mockRejectedValue(new Error('Temporary status failure'));
    await act(async () => { jest.advanceTimersByTime(3000); });
    expect(screen.getByText('Detection status unavailable')).toBeInTheDocument();
    expect(onStatusChange).toHaveBeenLastCalledWith('paused');
    expect(screen.getByRole('button', { name: 'Start detections' })).toBeDisabled();
  } finally { jest.useRealTimers(); }
});
it('retains camera count and offers Start again after an explicit stop', async () => {
  (fetch as jest.Mock).mockResolvedValue(response(status('paused')));
  render(<CityDetectionControl siteId="city" analyzedCount={0} />);
  expect(await screen.findByText('Detections off')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start detections' })).toBeEnabled();
  expect(screen.getByText('Camera video stays available.')).toBeInTheDocument();
});
it('shows start failures without claiming detections are active', async () => {
  (fetch as jest.Mock).mockImplementation((_url, options) => Promise.resolve(options.method === 'POST'
    ? response({ error: 'Saved memory reserve unavailable' }, false) : response(status())));
  render(<CityDetectionControl siteId="city" analyzedCount={0} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start detections' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Start detections' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Saved memory reserve unavailable');
  expect(screen.getByText('Detections stopped')).toBeInTheDocument();
});
it('disables starts when admission fails but still permits stopping a running worker', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ ...status('running'), ready: false, detail: 'Reserve low' }));
  render(<CityDetectionControl siteId="city" analyzedCount={2} />);
  expect(await screen.findByRole('button', { name: 'Stop detections' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Reconnect detections' })).toBeDisabled();
});
it('does not reuse a status or action completion from another site', async () => {
  let complete!: (value: unknown) => void;
  (fetch as jest.Mock).mockImplementation((_url, options) => options.method === 'POST'
    ? new Promise(resolve => { complete = resolve; }) : Promise.resolve(response(status())));
  const changed = jest.fn(); const { rerender } = render(<CityDetectionControl siteId="old" analyzedCount={0} onChanged={changed} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start detections' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Start detections' }));
  rerender(<CityDetectionControl siteId="new" analyzedCount={0} onChanged={changed} />);
  await act(async () => { complete(response(status('running'))); });
  expect(changed).not.toHaveBeenCalled(); expect(screen.queryByRole('button', { name: 'Stop detections' })).toBeNull();
});

it('reports paused and running state to the camera presentation', async () => {
  const onStatusChange = jest.fn();
  (fetch as jest.Mock).mockImplementation((_url, options) => Promise.resolve(response(status(options.method === 'POST' ? 'running' : 'paused'))));
  render(<CityDetectionControl siteId="city" analyzedCount={0} onStatusChange={onStatusChange} />);
  await waitFor(() => expect(onStatusChange).toHaveBeenLastCalledWith('paused'));
  (fetch as jest.Mock).mockResolvedValue(response(status('running')));
  fireEvent.click(screen.getByRole('button', { name: 'Start detections' }));
  await waitFor(() => expect(onStatusChange).toHaveBeenLastCalledWith('running'));
});
