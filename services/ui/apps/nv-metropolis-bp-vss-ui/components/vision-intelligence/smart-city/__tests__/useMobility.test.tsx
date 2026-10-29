// SPDX-License-Identifier: MIT
import { act, renderHook, waitFor } from '@testing-library/react';
import { useMobility, mobilityReportMatches } from '../useMobility';
import { cityRequest } from '../useCity';
import { useDocumentVisible } from '../useDocumentVisible';
import type { CitySite } from '../types';
import type { MobilityReport } from '../mobilityTypes';
jest.mock('../useCity', () => ({ cityRequest: jest.fn() }));
jest.mock('../useDocumentVisible', () => ({ useDocumentVisible: jest.fn() }));
const site: CitySite = { id: 'city', name: 'City', revision: 1, mode: 'live', sources: [], map: { bounds: [0,0,10,10], roads: [], buildings: [] } };
const report: MobilityReport = { schemaVersion: 'city.mobility.v1', siteId: 'city', siteRevision: 1, mode: 'live', configRevision: 0, windowMinutes: 5, timeBasis: 'per-camera-source-time', globalFusionEnabled: false, config: { revision: 0, movements: [], crossings: [], queues: [] }, coverage: [], lineCounts: [], movements: [], obstructions: [], queues: [], crossings: [], configurationIssues: [], limitations: [] };
beforeEach(() => { (useDocumentVisible as jest.Mock).mockReturnValue(true); (cityRequest as jest.Mock).mockResolvedValue(report); });
afterEach(() => jest.useRealTimers());
it('rejects a report for another site revision, window, or fused identity policy', () => {
  expect(mobilityReportMatches(report, site, 5)).toBe(true);
  expect(mobilityReportMatches({ ...report, siteRevision: 2 }, site, 5)).toBe(false);
  expect(mobilityReportMatches(report, site, 1)).toBe(false);
  expect(mobilityReportMatches({ ...report, globalFusionEnabled: true } as any, site, 5)).toBe(false);
});
it('polls at three-second intervals without overlapping and pauses when hidden', async () => {
  jest.useFakeTimers(); const { result, rerender, unmount } = renderHook(() => useMobility(site));
  await act(async () => {}); expect(result.current.report).toEqual(report); expect(cityRequest).toHaveBeenCalledTimes(1);
  await act(async () => { jest.advanceTimersByTime(2999); }); expect(cityRequest).toHaveBeenCalledTimes(1);
  await act(async () => { jest.advanceTimersByTime(1); }); expect(cityRequest).toHaveBeenCalledTimes(2);
  (useDocumentVisible as jest.Mock).mockReturnValue(false); rerender();
  await act(async () => { jest.advanceTimersByTime(20000); }); expect(cityRequest).toHaveBeenCalledTimes(2); expect(result.current.report).toBeNull();
  (useDocumentVisible as jest.Mock).mockReturnValue(true); rerender(); await act(async () => {}); expect(cityRequest).toHaveBeenCalledTimes(3);
  const signal = (cityRequest as jest.Mock).mock.calls[2][1].signal; unmount(); expect(signal.aborted).toBe(true);
});
it('ignores a late report after window change and aborts the prior request', async () => {
  let complete!: (value: MobilityReport) => void;
  (cityRequest as jest.Mock).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; })).mockResolvedValue({ ...report, windowMinutes: 1 });
  const { result } = renderHook(() => useMobility(site)); const signal = (cityRequest as jest.Mock).mock.calls[0][1].signal;
  act(() => result.current.setWindowMinutes(1)); expect(signal.aborted).toBe(true);
  await waitFor(() => expect(result.current.report?.windowMinutes).toBe(1));
  await act(async () => complete(report)); expect(result.current.report?.windowMinutes).toBe(1);
});
it('uses expected revision, refreshes after a confirmed save and propagates conflicts', async () => {
  const config = { ...report.config, revision: 1 };
  (cityRequest as jest.Mock).mockImplementation((path: string) => path === 'mobility/config' ? Promise.resolve({ config, configRevision: 1 }) : Promise.resolve(report));
  const { result } = renderHook(() => useMobility(site)); await waitFor(() => expect(result.current.report).not.toBeNull());
  await act(async () => { await result.current.saveConfig({ expectedRevision: 0, movements: [], crossings: [], queues: [] }); });
  expect(cityRequest).toHaveBeenCalledWith('mobility/config', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ expectedRevision: 0, movements: [], crossings: [], queues: [] }) }));
  expect(result.current.saving).toBe(false);
  (cityRequest as jest.Mock).mockRejectedValueOnce(new Error('Mobility settings revision conflict.'));
  await act(async () => { await expect(result.current.saveConfig({ expectedRevision: 0, movements: [], crossings: [], queues: [] })).rejects.toThrow('revision conflict'); });
});
it('aborts a pending save when the site changes and rejects its late result', async () => {
  let finish!: (value: unknown) => void;
  (cityRequest as jest.Mock).mockImplementation((path: string) => path === 'mobility/config' ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(report));
  const { result, rerender } = renderHook(({ value }) => useMobility(value), { initialProps: { value: site } });
  await waitFor(() => expect(result.current.report).not.toBeNull());
  let pending!: Promise<unknown>; act(() => { pending = result.current.saveConfig({ expectedRevision: 0, movements: [], crossings: [], queues: [] }); });
  const signal = (cityRequest as jest.Mock).mock.calls.find(call => call[0] === 'mobility/config')[1].signal;
  rerender({ value: { ...site, revision: 2 } }); expect(signal.aborted).toBe(true);
  await act(async () => { finish({ config: report.config, configRevision: 0 }); await expect(pending).rejects.toHaveProperty('name', 'AbortError'); });
});
