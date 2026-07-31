// SPDX-License-Identifier: MIT
import { act, renderHook, waitFor } from '@testing-library/react';
import { useVerificationAlertConfigs } from '../../lib-src/hooks/useVerificationAlertConfigs';
import type { VerificationAlertConfig } from '../../lib-src/types';

const jsonResponse = (body: unknown, ok = true, status = 200, statusText = 'OK') =>
  Promise.resolve({
    ok,
    status,
    statusText,
    json: () => Promise.resolve(body),
  } as Response);

const config = (overrides: Partial<VerificationAlertConfig> = {}): VerificationAlertConfig => ({
  alert_type: 'fov count violation',
  prompt: 'Is anyone missing required PPE?',
  system_prompt: 'Use visible evidence only.',
  enrichment_prompt: null,
  vlm_params: { num_frames: 4 },
  output_category: 'PPE Compliance Violation',
  created_at: '2026-07-15T01:00:00Z',
  updated_at: '2026-07-15T01:00:00Z',
  ...overrides,
});

describe('useVerificationAlertConfigs', () => {
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('lists, creates, updates, and deletes configs using alert_type as the key', async () => {
    const created = config();
    const updated = config({
      prompt: 'Is a worker missing a hardhat?',
      updated_at: '2026-07-15T02:00:00Z',
    });
    global.fetch = jest
      .fn()
      .mockImplementationOnce(() =>
        jsonResponse({ status: 'success', configs: [], count: 0 }),
      )
      .mockImplementationOnce((_url: string, init?: RequestInit) => {
        expect(init?.method).toBe('POST');
        expect(JSON.parse(init?.body as string)).toEqual({
          alert_type: 'FOV Count Violation',
          prompt: 'Is anyone missing required PPE?',
          system_prompt: 'Use visible evidence only.',
          enrichment_prompt: null,
          output_category: 'PPE Compliance Violation',
          vlm_params: { num_frames: 4 },
        });
        return jsonResponse(created, true, 201, 'Created');
      })
      .mockImplementationOnce((_url: string, init?: RequestInit) => {
        expect(init?.method).toBe('PUT');
        expect(JSON.parse(init?.body as string)).toEqual({
          prompt: 'Is a worker missing a hardhat?',
        });
        return jsonResponse(updated);
      })
      .mockImplementationOnce(() =>
        jsonResponse({ status: 'success', message: "Config 'fov count violation' deleted" }),
      );

    const { result } = renderHook(() =>
      useVerificationAlertConfigs({ alertsApiUrl: 'http://alerts.test/api/v1/' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      'http://alerts.test/api/v1/verification/config',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await act(async () => {
      await result.current.createConfig({
        alert_type: 'FOV Count Violation',
        prompt: 'Is anyone missing required PPE?',
        system_prompt: 'Use visible evidence only.',
        enrichment_prompt: null,
        output_category: 'PPE Compliance Violation',
        vlm_params: { num_frames: 4 },
      });
    });
    expect(result.current.configs).toEqual([created]);
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://alerts.test/api/v1/verification/config',
      expect.objectContaining({ method: 'POST' }),
    );

    await act(async () => {
      await result.current.updateConfig('fov count violation', {
        prompt: 'Is a worker missing a hardhat?',
      });
    });
    expect(result.current.configs).toEqual([updated]);
    expect(global.fetch).toHaveBeenNthCalledWith(
      3,
      'http://alerts.test/api/v1/verification/config/fov%20count%20violation',
      expect.objectContaining({ method: 'PUT' }),
    );

    await act(async () => {
      await result.current.deleteConfig('fov count violation');
    });
    expect(result.current.configs).toEqual([]);
    expect(global.fetch).toHaveBeenNthCalledWith(
      4,
      'http://alerts.test/api/v1/verification/config/fov%20count%20violation',
      { method: 'DELETE' },
    );
  });

  it('surfaces FastAPI validation details and missing API configuration', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: () =>
        Promise.resolve({
          detail: [{ loc: ['body', 'prompt'], msg: 'String should have at least 1 character' }],
        }),
    });

    const { result, rerender } = renderHook(
      ({ apiUrl }: { apiUrl?: string }) =>
        useVerificationAlertConfigs({ alertsApiUrl: apiUrl }),
      { initialProps: { apiUrl: 'http://alerts.test/api/v1' } },
    );

    await waitFor(() =>
      expect(result.current.error).toBe('prompt: String should have at least 1 character'),
    );

    rerender({ apiUrl: undefined });
    await waitFor(() =>
      expect(result.current.error).toBe('Alerts API URL is not configured'),
    );
  });
});
