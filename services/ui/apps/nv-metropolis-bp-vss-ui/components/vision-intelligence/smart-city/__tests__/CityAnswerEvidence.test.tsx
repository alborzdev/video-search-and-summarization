// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { CityAnswerEvidence } from '../CityAnswerEvidence';
const answer: any = { observedWindow: { startTime: '2026-10-22T12:00:00Z', endTime: '2026-10-22T12:00:05Z' } };
const source = { id: 'a', sensorId: 'vss-a', name: 'Camera A', mode: 'live', vstApiUrl: 'http://video.test/vst/api' };
describe('deliberate answer clip preparation', () => {
  it('does not request media without a valid returned short interval', () => {
    global.fetch = jest.fn(); render(<CityAnswerEvidence answer={{} as any} source={source} selectionKey="a" />);
    expect(screen.getByText(/valid inspected interval/)).toBeInTheDocument(); expect(fetch).not.toHaveBeenCalled();
  });
  it('keeps an unavailable clip error visible without inventing playback', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'The recording is no longer retained.' }) });
    render(<CityAnswerEvidence answer={answer} source={source} selectionKey="a" />); expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' })); expect(await screen.findByRole('alert')).toHaveTextContent('no longer retained'); expect(screen.queryByText('Open inspected clip')).not.toBeInTheDocument();
  });
  it('cancels a user-requested clip and rejects its late result', async () => {
    let finish!: (value: unknown) => void; let signal!: AbortSignal;
    global.fetch = jest.fn((_url, init) => { signal = init!.signal as AbortSignal; return new Promise(resolve => { finish = resolve; }); });
    render(<CityAnswerEvidence answer={answer} source={source} selectionKey="a" />); fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel evidence request' })); expect(signal.aborted).toBe(true);
    await act(async () => finish({ ok: true, json: async () => ({ videoUrl: 'http://video.test/vst/storage/temp_files/clip.mp4' }) }));
    expect(screen.queryByText('Open inspected clip')).not.toBeInTheDocument(); expect(screen.getByRole('alert')).toHaveTextContent('cancelled');
  });
  it('bounds a stalled preparation request to ninety seconds', async () => {
    jest.useFakeTimers(); let signal!: AbortSignal;
    try {
      global.fetch = jest.fn((_url, init) => { signal = init!.signal as AbortSignal; return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))); });
      const { unmount } = render(<CityAnswerEvidence answer={answer} source={source} selectionKey="a" />); fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' }));
      await act(async () => { jest.advanceTimersByTime(90_000); }); expect(signal.aborted).toBe(true); expect(screen.getByRole('alert')).toHaveTextContent('timed out'); unmount();
    } finally { jest.useRealTimers(); }
  });
  it('rejects a changed evidence start time and unsafe returned media URLs', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ startTime: '2026-10-22T11:00:00Z', videoUrl: 'http://video.test/vst/storage/temp_files/clip.mp4' }) }).mockResolvedValue({ ok: true, json: async () => ({ videoUrl: 'https://external.test/clip.mp4' }) });
    render(<CityAnswerEvidence answer={answer} source={source} selectionKey="a" />); fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('different observation start time'); fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' })); expect(await screen.findByRole('alert')).toHaveTextContent('unsupported media URL');
  });
  it('rejects a returned full recording instead of presenting it as five-second evidence', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ videoUrl: 'http://video.test/vst/storage/temp_files/clip.mp4' }) });
    const pause = jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    render(<CityAnswerEvidence answer={answer} source={source} selectionKey="a" />); fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' }));
    const video = await screen.findByLabelText('Inspected evidence from Camera A'); Object.defineProperty(video, 'duration', { value: 48.1 }); fireEvent.loadedMetadata(video);
    expect(screen.getByRole('alert')).toHaveTextContent('does not match'); expect(screen.queryByText('Open inspected clip')).not.toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(1); pause.mockRestore();
  });
  it('clears an already loaded clip when the effective camera selection changes without exporting again', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ videoUrl: 'http://video.test/vst/storage/temp_files/clip.mp4' }) });
    const { rerender } = render(<CityAnswerEvidence answer={answer} source={source} selectionKey="a" />); fireEvent.click(screen.getByRole('button', { name: 'Load inspected clip (up to 5 s)' })); await screen.findByText('Open inspected clip');
    rerender(<CityAnswerEvidence answer={answer} source={source} selectionKey="b" />); expect(screen.queryByText('Open inspected clip')).not.toBeInTheDocument(); expect(screen.queryByLabelText('Inspected evidence from Camera A')).not.toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(1);
  });
});
