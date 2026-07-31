// SPDX-License-Identifier: MIT
/**
 * Typed client hook for candidate-verification rule configuration.
 *
 * `alertsApiUrl` is expected to include the API version prefix. Endpoints:
 *   GET    /verification/config
 *   POST   /verification/config
 *   PUT    /verification/config/{alert_type}
 *   DELETE /verification/config/{alert_type}
 */

import { useCallback, useEffect, useState } from 'react';
import {
  VerificationAlertConfig,
  VerificationVlmParams,
} from '../types';

interface UseVerificationAlertConfigsOptions {
  alertsApiUrl?: string;
}

export interface CreateVerificationAlertConfigInput {
  alert_type: string;
  prompt: string;
  system_prompt?: string | null;
  enrichment_prompt?: string | null;
  vlm_params?: VerificationVlmParams | null;
  output_category?: string | null;
}

export interface UpdateVerificationAlertConfigInput {
  prompt?: string | null;
  system_prompt?: string | null;
  enrichment_prompt?: string | null;
  vlm_params?: VerificationVlmParams | null;
  output_category?: string | null;
}

const VERIFICATION_CONFIG_PATH = '/verification/config';

const buildBase = (alertsApiUrl?: string) => (alertsApiUrl ?? '').replace(/\/+$/, '');

const detailMessage = (detail: unknown): string | null => {
  if (typeof detail === 'string') return detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const entry = item as { msg?: unknown; loc?: unknown };
      if (typeof entry.msg !== 'string') return null;
      const location = Array.isArray(entry.loc)
        ? entry.loc.filter((part) => part !== 'body').join('.')
        : '';
      return location ? `${location}: ${entry.msg}` : entry.msg;
    })
    .filter((message): message is string => Boolean(message));
  return messages.length > 0 ? messages.join('; ') : null;
};

const parseError = async (response: Response): Promise<string> => {
  try {
    const body = await response.json();
    if (body && typeof body === 'object') {
      const envelope = body as {
        message?: unknown;
        detail?: unknown;
        error?: unknown;
        code?: unknown;
      };
      if (typeof envelope.message === 'string') return envelope.message;
      const detail = detailMessage(envelope.detail);
      if (detail) return detail;
      if (typeof envelope.error === 'string') return envelope.error;
      if (typeof envelope.code === 'string') return envelope.code;
    }
  } catch {
    // Fall back to the HTTP status below when the error body is not JSON.
  }
  return `${response.status} ${response.statusText}`.trim();
};

export const useVerificationAlertConfigs = ({
  alertsApiUrl,
}: UseVerificationAlertConfigsOptions) => {
  const [configs, setConfigs] = useState<VerificationAlertConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);

  const fetchConfigs = useCallback(
    async (signal?: AbortSignal): Promise<VerificationAlertConfig[]> => {
      if (!alertsApiUrl) {
        setError('Alerts API URL is not configured');
        return [];
      }
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `${buildBase(alertsApiUrl)}${VERIFICATION_CONFIG_PATH}`,
          { signal },
        );
        if (!response.ok) throw new Error(await parseError(response));
        const body = await response.json();
        const nextConfigs: VerificationAlertConfig[] = Array.isArray(body?.configs)
          ? body.configs
          : [];
        if (signal?.aborted) return [];
        setConfigs(nextConfigs);
        setLastRefreshedAt(new Date());
        return nextConfigs;
      } catch (err) {
        if (signal?.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
          return [];
        }
        setError(err instanceof Error ? err.message : 'Failed to load verification rules');
        return [];
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [alertsApiUrl],
  );

  const refetch = useCallback(() => fetchConfigs(), [fetchConfigs]);

  const createConfig = useCallback(
    async (
      input: CreateVerificationAlertConfigInput,
    ): Promise<VerificationAlertConfig> => {
      if (!alertsApiUrl) throw new Error('Alerts API URL is not configured');
      const response = await fetch(
        `${buildBase(alertsApiUrl)}${VERIFICATION_CONFIG_PATH}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        },
      );
      if (!response.ok) throw new Error(await parseError(response));
      const created = (await response.json()) as VerificationAlertConfig;
      if (!created?.alert_type) {
        throw new Error('Invalid server response: missing alert_type');
      }
      setConfigs((current) => {
        const withoutDuplicate = current.filter(
          (config) => config.alert_type !== created.alert_type,
        );
        return [...withoutDuplicate, created];
      });
      return created;
    },
    [alertsApiUrl],
  );

  const updateConfig = useCallback(
    async (
      alertType: string,
      input: UpdateVerificationAlertConfigInput,
    ): Promise<VerificationAlertConfig> => {
      if (!alertsApiUrl) throw new Error('Alerts API URL is not configured');
      const response = await fetch(
        `${buildBase(alertsApiUrl)}${VERIFICATION_CONFIG_PATH}/${encodeURIComponent(alertType)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        },
      );
      if (!response.ok) throw new Error(await parseError(response));
      const updated = (await response.json()) as VerificationAlertConfig;
      if (!updated?.alert_type) {
        throw new Error('Invalid server response: missing alert_type');
      }
      setConfigs((current) =>
        current.map((config) =>
          config.alert_type === alertType ? updated : config,
        ),
      );
      return updated;
    },
    [alertsApiUrl],
  );

  const deleteConfig = useCallback(
    async (alertType: string): Promise<void> => {
      if (!alertsApiUrl) throw new Error('Alerts API URL is not configured');
      const response = await fetch(
        `${buildBase(alertsApiUrl)}${VERIFICATION_CONFIG_PATH}/${encodeURIComponent(alertType)}`,
        { method: 'DELETE' },
      );
      if (!response.ok) throw new Error(await parseError(response));
      setConfigs((current) =>
        current.filter((config) => config.alert_type !== alertType),
      );
    },
    [alertsApiUrl],
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetchConfigs(controller.signal);
    return () => controller.abort();
  }, [fetchConfigs]);

  return {
    configs,
    loading,
    error,
    lastRefreshedAt,
    refetch,
    createConfig,
    updateConfig,
    deleteConfig,
  };
};
