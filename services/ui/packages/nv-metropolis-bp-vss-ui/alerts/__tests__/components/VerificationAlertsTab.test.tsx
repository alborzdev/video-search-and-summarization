// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  CreateAlertRulesView,
  triggerRealtimeAddDraft,
} from '../../lib-src/components/CreateAlertRulesView';
import type { VerificationAlertConfig } from '../../lib-src/types';

const jsonResponse = (body: unknown, ok = true, status = 200, statusText = 'OK') =>
  Promise.resolve({
    ok,
    status,
    statusText,
    json: () => Promise.resolve(body),
  } as Response);

const buildConfig = (overrides: Partial<VerificationAlertConfig> = {}): VerificationAlertConfig => ({
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

describe('CreateAlertRulesView candidate verification', () => {
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('switches tabs with the keyboard and completes create, update, and delete flows', async () => {
    let configs: VerificationAlertConfig[] = [];
    global.fetch = jest.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/realtime')) {
        return jsonResponse({ status: 'success', rules: [], count: 0 });
      }
      if (url.endsWith('/verification/config') && !init?.method) {
        return jsonResponse({ status: 'success', configs, count: configs.length });
      }
      if (url.endsWith('/verification/config') && init?.method === 'POST') {
        const body = JSON.parse(init.body as string);
        configs = [buildConfig({
          alert_type: 'fov count violation',
          prompt: body.prompt,
          system_prompt: body.system_prompt,
          enrichment_prompt: body.enrichment_prompt,
          output_category: body.output_category,
          vlm_params: body.vlm_params,
        })];
        return jsonResponse(configs[0], true, 201, 'Created');
      }
      if (url.includes('/verification/config/') && init?.method === 'PUT') {
        const body = JSON.parse(init.body as string);
        configs = [buildConfig({
          ...configs[0],
          ...body,
          updated_at: '2026-07-15T02:00:00Z',
        })];
        return jsonResponse(configs[0]);
      }
      if (url.includes('/verification/config/') && init?.method === 'DELETE') {
        configs = [];
        return jsonResponse({ status: 'success', message: 'Config deleted' });
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });

    render(
      <CreateAlertRulesView
        isDark={false}
        activeKind="real-time"
        onAddNew={jest.fn()}
        alertsApiUrl="http://alerts.test/api/v1/"
      />,
    );

    const realtimeTab = screen.getByRole('tab', { name: 'Real-time Alerts' });
    const verificationTab = screen.getByRole('tab', { name: 'Candidate Verification' });
    expect(realtimeTab).toHaveAttribute('aria-selected', 'true');

    fireEvent.keyDown(realtimeTab, { key: 'ArrowRight' });
    expect(verificationTab).toHaveAttribute('aria-selected', 'true');
    expect(verificationTab).toHaveFocus();
    expect(await screen.findByText(/No candidate verification rules yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('add-verification-rule-button'));
    fireEvent.change(screen.getByTestId('verification-num-frames-input'), {
      target: { value: '5' },
    });
    fireEvent.click(screen.getByTestId('verification-save-button'));
    expect(screen.getByRole('alert')).toHaveTextContent('Trigger alert type is required');

    fireEvent.change(screen.getByTestId('verification-alert-type-input'), {
      target: { value: 'FOV Count Violation' },
    });
    fireEvent.change(screen.getByTestId('verification-output-category-input'), {
      target: { value: 'PPE Compliance Violation' },
    });
    fireEvent.change(screen.getByTestId('verification-prompt-input'), {
      target: { value: '  Is anyone missing required PPE?  ' },
    });
    fireEvent.change(screen.getByTestId('verification-system-prompt-input'), {
      target: { value: '  Use visible evidence only.  ' },
    });
    fireEvent.change(screen.getByTestId('verification-num-frames-input'), {
      target: { value: '4' },
    });
    fireEvent.click(screen.getByTestId('verification-save-button'));

    await waitFor(() => expect(screen.getByText('fov count violation')).toBeInTheDocument());
    const postCall = (global.fetch as jest.Mock).mock.calls.find(
      (call: [string, RequestInit?]) => call[1]?.method === 'POST',
    );
    expect(postCall[0]).toBe('http://alerts.test/api/v1/verification/config');
    expect(JSON.parse(postCall[1].body as string)).toEqual({
      alert_type: 'FOV Count Violation',
      prompt: 'Is anyone missing required PPE?',
      system_prompt: 'Use visible evidence only.',
      enrichment_prompt: null,
      output_category: 'PPE Compliance Violation',
      vlm_params: { num_frames: 4 },
    });

    fireEvent.click(screen.getByLabelText('Edit verification rule fov count violation'));
    expect(screen.getByTestId('verification-alert-type-input')).toBeDisabled();
    fireEvent.change(screen.getByTestId('verification-prompt-input'), {
      target: { value: 'Is a worker missing a hardhat?' },
    });
    fireEvent.change(screen.getByTestId('verification-num-frames-input'), {
      target: { value: '3' },
    });
    fireEvent.click(screen.getByTestId('verification-save-button'));

    await waitFor(() =>
      expect(screen.getByText('Is a worker missing a hardhat?')).toBeInTheDocument(),
    );
    const putCall = (global.fetch as jest.Mock).mock.calls.find(
      (call: [string, RequestInit?]) => call[1]?.method === 'PUT',
    );
    expect(putCall[0]).toBe(
      'http://alerts.test/api/v1/verification/config/fov%20count%20violation',
    );
    expect(JSON.parse(putCall[1].body as string)).toEqual(
      expect.objectContaining({
        prompt: 'Is a worker missing a hardhat?',
        vlm_params: { num_frames: 3 },
      }),
    );

    fireEvent.click(screen.getByLabelText('Delete verification rule fov count violation'));
    fireEvent.click(
      screen.getByLabelText('Confirm delete of verification rule fov count violation'),
    );
    await waitFor(() =>
      expect(screen.queryByText('Is a worker missing a hardhat?')).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/No candidate verification rules yet/i)).toBeInTheDocument();
  });

  it('shows API and local validation errors without discarding the draft', async () => {
    global.fetch = jest.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/verification/config') && !init?.method) {
        return jsonResponse({ status: 'success', configs: [], count: 0 });
      }
      if (url.endsWith('/verification/config') && init?.method === 'POST') {
        return jsonResponse(
          { status: 'error', code: 'config_exists', message: 'Config already exists' },
          false,
          409,
          'Conflict',
        );
      }
      return jsonResponse({ status: 'success', rules: [], count: 0 });
    });

    render(
      <CreateAlertRulesView
        isDark
        activeKind="verification"
        onAddNew={jest.fn()}
        alertsApiUrl="http://alerts.test/api/v1"
      />,
    );
    expect(await screen.findByText(/No candidate verification rules yet/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('add-verification-rule-button'));
    fireEvent.change(screen.getByTestId('verification-alert-type-input'), {
      target: { value: 'invalid/type' },
    });
    fireEvent.change(screen.getByTestId('verification-prompt-input'), {
      target: { value: 'Verify this candidate' },
    });
    fireEvent.click(screen.getByTestId('verification-save-button'));
    expect(screen.getByTestId('verification-save-error')).toHaveTextContent(
      'only letters, numbers, spaces, underscores, and hyphens',
    );

    fireEvent.change(screen.getByTestId('verification-alert-type-input'), {
      target: { value: 'person present' },
    });
    fireEvent.click(screen.getByTestId('verification-save-button'));
    await waitFor(() =>
      expect(screen.getByTestId('verification-save-error')).toHaveTextContent(
        'Config already exists',
      ),
    );
    expect(screen.getByTestId('verification-rule-editor')).toBeInTheDocument();
  });

  it('routes the existing sidebar create action to the selected verification tab', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 'success', configs: [], count: 0 }),
    });

    render(
      <CreateAlertRulesView
        isDark={false}
        activeKind="verification"
        onAddNew={jest.fn()}
        alertsApiUrl="http://alerts.test/api/v1"
      />,
    );
    expect(await screen.findByText(/No candidate verification rules yet/i)).toBeInTheDocument();

    act(() => {
      expect(triggerRealtimeAddDraft()).toBe(true);
    });
    expect(screen.getByTestId('verification-rule-editor')).toBeInTheDocument();
  });
});
