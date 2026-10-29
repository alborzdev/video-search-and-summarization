// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CityCaptureEvidenceDrawer } from '../CityCaptureEvidenceDrawer';
import type { CityIndexingMatch } from '../cityIndexing';

const match: CityIndexingMatch = { sensor_id: '997d3a69-e052-45a4-a1ce-be1b046670c4', video_name: 'Southwest', description: 'A bus at the curb', start_time: '2026-10-26T08:00:00Z', end_time: '2026-10-26T08:00:05Z' };
const url = `/api/vision/evidence-media?key=${'a'.repeat(64)}`;
const reply = (value: unknown, status = 200) => ({ ok: status < 300, status, json: async () => value });
function duration(element: HTMLElement, seconds: number) { Object.defineProperty(element, 'duration', { value: seconds, configurable: true }); fireEvent.loadedMetadata(element); }
beforeEach(() => {
  jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  jest.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  global.fetch = jest.fn().mockResolvedValue(reply({ startTime: match.start_time, videoUrl: url }));
});
afterEach(() => { jest.useRealTimers(); });

it('requests only the selected exact source/time clip and waits for length verification before offering playback', async () => {
  render(<CityCaptureEvidenceDrawer match={match} sourceName="Intersection southwest" onClose={jest.fn()} />);
  const video = await screen.findByLabelText('Retained clip from Intersection southwest');
  const sent = new URL((fetch as jest.Mock).mock.calls[0][0], 'http://localhost');
  expect(sent.pathname).toBe('/api/vision/evidence');
  expect(Object.fromEntries(sent.searchParams)).toEqual({ sensorId: match.sensor_id, startTime: match.start_time, endTime: match.end_time });
  expect(fetch).toHaveBeenCalledTimes(1); expect(video).not.toHaveAttribute('autoplay'); expect(video).not.toHaveAttribute('controls');
  expect(screen.getByRole('dialog')).toHaveAttribute('data-source-id', match.sensor_id);
  duration(video, 5.2); expect(video).toHaveAttribute('controls');
  expect(screen.getByText('5.0 s retained clip · Play to review')).toBeInTheDocument();
  expect(screen.getByText(match.sensor_id)).toBeInTheDocument();
});

it('rejects a full recording or truncated video instead of calling it the requested clip', async () => {
  const { rerender } = render(<CityCaptureEvidenceDrawer match={match} onClose={jest.fn()} />);
  const video = await screen.findByLabelText('Retained clip from Southwest'); duration(video, 48);
  expect(screen.getByRole('alert')).toHaveTextContent('length does not match');
  expect(screen.queryByLabelText('Retained clip from Southwest')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry clip' }));
  const retry = await screen.findByLabelText('Retained clip from Southwest'); duration(retry, 2);
  expect(screen.getByRole('alert')).toHaveTextContent('length does not match');
  rerender(<CityCaptureEvidenceDrawer match={match} onClose={jest.fn()} />);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each([{ startTime: '2026-10-26T07:00:00Z', videoUrl: url }, { videoUrl: url }, { startTime: match.start_time, videoUrl: 'https://outside.test/clip.mp4' }])('withholds unverified time or unsupported media without fetching that URL', async payload => {
  (fetch as jest.Mock).mockResolvedValue(reply(payload));
  render(<CityCaptureEvidenceDrawer match={match} onClose={jest.fn()} />);
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByLabelText('Retained clip from Southwest')).not.toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(1);
});

it('shows retention loss honestly and retries only when requested', async () => {
  (fetch as jest.Mock).mockResolvedValue(reply({ error: 'expired' }, 410));
  render(<CityCaptureEvidenceDrawer match={match} onClose={jest.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('no longer retained');
  expect(fetch).toHaveBeenCalledTimes(1); fireEvent.click(screen.getByRole('button', { name: 'Retry clip' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
});

it('does not request media for an invalid or unbounded time window', async () => {
  render(<CityCaptureEvidenceDrawer match={{ ...match, end_time: '2026-10-26T09:00:00Z' }} onClose={jest.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('no valid camera'); expect(fetch).not.toHaveBeenCalled();
});

it('aborts on close and does not accept a late clip', async () => {
  let finish!: (value: unknown) => void; let signal!: AbortSignal;
  (fetch as jest.Mock).mockImplementation((_input, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); });
  const close = jest.fn(); const { unmount } = render(<CityCaptureEvidenceDrawer match={match} onClose={close} />);
  fireEvent.click(screen.getByRole('button', { name: 'Close retained clip' })); expect(signal.aborted).toBe(true); expect(close).toHaveBeenCalledTimes(1);
  unmount(); await act(async () => finish(reply({ startTime: match.start_time, videoUrl: url })));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('aborts the previous source request and never displays its result for a new source', async () => {
  let finish!: (value: unknown) => void; let firstSignal!: AbortSignal;
  (fetch as jest.Mock).mockImplementationOnce((_input, options) => { firstSignal = options.signal; return new Promise(resolve => { finish = resolve; }); }).mockResolvedValue(reply({ startTime: match.start_time, videoUrl: url }));
  const { rerender } = render(<CityCaptureEvidenceDrawer match={match} onClose={jest.fn()} />);
  rerender(<CityCaptureEvidenceDrawer match={{ ...match, sensor_id: '40af41ea-2180-4b7b-83d6-bb5d08ff094a', video_name: 'Northeast' }} onClose={jest.fn()} />);
  expect(firstSignal.aborted).toBe(true); await screen.findByLabelText('Retained clip from Northeast');
  await act(async () => finish(reply({ startTime: match.start_time, videoUrl: 'http://outside.test/old.mp4' })));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument(); expect(screen.queryByLabelText('Retained clip from Southwest')).not.toBeInTheDocument();
});

it('bounds preparation and supports Escape with the shared dialog handler', async () => {
  jest.useFakeTimers(); let signal!: AbortSignal;
  (fetch as jest.Mock).mockImplementation((_input, options) => { signal = options.signal; return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))); });
  const close = jest.fn(); render(<CityCaptureEvidenceDrawer match={match} onClose={close} />);
  await act(async () => jest.advanceTimersByTime(90_000)); expect(signal.aborted).toBe(true);
  expect(screen.getByRole('alert')).toHaveTextContent('timed out');
  fireEvent.keyDown(document, { key: 'Escape' }); expect(close).toHaveBeenCalledTimes(1);
});
