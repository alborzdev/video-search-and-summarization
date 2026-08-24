// SPDX-License-Identifier: MIT

import {
  MONITORING_SETUP_EVENT,
  requestMonitoringSetup,
  type MonitoringSetupEventDetail,
} from '../lib-src/monitoringSetup';

describe('monitoring setup handshake', () => {
  afterEach(() => {
    jest.useRealTimers();
  });

  it('falls through when the Vision Intelligence shell is not mounted', async () => {
    await expect(requestMonitoringSetup({
      analysisProfileId: 'warehouse-safety',
      blocking: true,
      detectionEnabled: true,
      name: 'Dock replay',
      sensorId: 'recorded-1',
      sourceKind: 'recorded',
    })).resolves.toEqual({ analysisProfileId: 'warehouse-safety', detectionEnabled: true, ruleCreated: false });
  });

  it('waits for the shell and returns the completed monitoring choice', async () => {
    const listener = (event: Event) => {
      event.preventDefault();
      const detail = (event as CustomEvent<MonitoringSetupEventDetail>).detail;
      expect(detail).toMatchObject({ blocking: true, sensorId: 'recorded-2' });
      detail.complete({ detectionEnabled: true, ruleCreated: true });
    };
    window.addEventListener(MONITORING_SETUP_EVENT, listener, { once: true });

    await expect(requestMonitoringSetup({
      analysisProfileId: 'warehouse-safety',
      blocking: true,
      detectionEnabled: true,
      name: 'Aisle replay',
      sensorId: 'recorded-2',
      sourceKind: 'recorded',
    })).resolves.toEqual({ analysisProfileId: 'warehouse-safety', detectionEnabled: true, ruleCreated: true });
  });

  it('does not offer detector rules for a semantic-only recording', async () => {
    const listener = jest.fn((event: Event) => event.preventDefault());
    window.addEventListener(MONITORING_SETUP_EVENT, listener, { once: true });

    await expect(requestMonitoringSetup({
      analysisProfileId: 'semantic-search',
      blocking: true,
      detectionEnabled: false,
      name: 'Search-only replay',
      sensorId: 'recorded-search-only',
      sourceKind: 'recorded',
    })).resolves.toEqual({
      analysisProfileId: 'semantic-search',
      detectionEnabled: false,
      ruleCreated: false,
    });
    expect(listener).not.toHaveBeenCalled();
  });

  it('releases a blocked upload when an interrupted shell never completes', async () => {
    jest.useFakeTimers();
    const listener = (event: Event) => event.preventDefault();
    window.addEventListener(MONITORING_SETUP_EVENT, listener, { once: true });

    const result = requestMonitoringSetup({
      analysisProfileId: 'warehouse-safety',
      blocking: true,
      detectionEnabled: true,
      name: 'Interrupted replay',
      sensorId: 'recorded-3',
      sourceKind: 'recorded',
    });
    await jest.advanceTimersByTimeAsync(20 * 60 * 1000);

    await expect(result).resolves.toEqual({ analysisProfileId: 'warehouse-safety', detectionEnabled: true, ruleCreated: false });
  });
});
