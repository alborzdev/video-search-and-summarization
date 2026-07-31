// SPDX-License-Identifier: MIT
/** Candidate-verification rule CRUD editor. */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  IconAlertCircle,
  IconCheck,
  IconDeviceFloppy,
  IconEdit,
  IconLoader2,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconX,
} from '@tabler/icons-react';
import {
  useVerificationAlertConfigs,
  CreateVerificationAlertConfigInput,
  UpdateVerificationAlertConfigInput,
} from '../hooks/useVerificationAlertConfigs';
import { VerificationAlertConfig, VerificationVlmParams } from '../types';

interface VerificationAlertsTabProps {
  isDark: boolean;
  alertsApiUrl?: string;
  inputClass: string;
  readOnlyCellClass: string;
  thClass: string;
  registerAddAction: (action: (() => void) | null) => void;
}

interface VerificationDraft {
  mode: 'create' | 'edit';
  originalAlertType?: string;
  alert_type: string;
  output_category: string;
  prompt: string;
  system_prompt: string;
  enrichment_prompt: string;
  num_frames: string;
  vlm_params: VerificationVlmParams;
}

const EMPTY_DRAFT: VerificationDraft = {
  mode: 'create',
  alert_type: '',
  output_category: '',
  prompt: '',
  system_prompt: '',
  enrichment_prompt: '',
  num_frames: '4',
  vlm_params: {},
};

const ALERT_TYPE_PATTERN = /^[A-Za-z0-9 _-]+$/;

const toDraft = (config: VerificationAlertConfig): VerificationDraft => ({
  mode: 'edit',
  originalAlertType: config.alert_type,
  alert_type: config.alert_type,
  output_category: config.output_category ?? '',
  prompt: config.prompt,
  system_prompt: config.system_prompt ?? '',
  enrichment_prompt: config.enrichment_prompt ?? '',
  num_frames: String(config.vlm_params?.num_frames ?? 4),
  vlm_params: config.vlm_params ?? {},
});

const trimmedOrNull = (value: string): string | null => value.trim() || null;

const validateDraft = (draft: VerificationDraft): string | null => {
  const alertType = draft.alert_type.trim();
  const prompt = draft.prompt.trim();
  if (!alertType) return 'Trigger alert type is required.';
  if (alertType.length > 100) return 'Trigger alert type must be 100 characters or fewer.';
  if (!ALERT_TYPE_PATTERN.test(alertType)) {
    return 'Trigger alert type may contain only letters, numbers, spaces, underscores, and hyphens.';
  }
  if (!prompt) return 'Verification prompt is required.';
  if (prompt.length > 5000) return 'Verification prompt must be 5,000 characters or fewer.';
  if (draft.system_prompt.length > 5000) {
    return 'System instructions must be 5,000 characters or fewer.';
  }
  if (draft.enrichment_prompt.length > 5000) {
    return 'Enrichment prompt must be 5,000 characters or fewer.';
  }
  if (draft.output_category.length > 200) {
    return 'Output label must be 200 characters or fewer.';
  }
  const frames = Number(draft.num_frames);
  if (!Number.isInteger(frames) || frames < 1 || frames > 4) {
    return 'Frame samples must be a whole number from 1 to 4.';
  }
  return null;
};

export const VerificationAlertsTab: React.FC<VerificationAlertsTabProps> = ({
  isDark,
  alertsApiUrl,
  inputClass,
  readOnlyCellClass,
  thClass,
  registerAddAction,
}) => {
  const {
    configs,
    loading,
    error,
    lastRefreshedAt,
    refetch,
    createConfig,
    updateConfig,
    deleteConfig,
  } = useVerificationAlertConfigs({ alertsApiUrl });
  const [draft, setDraft] = useState<VerificationDraft | null>(null);
  const [filter, setFilter] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const beginCreate = useCallback(() => {
    setDraft({ ...EMPTY_DRAFT, vlm_params: {} });
    setSaveError(null);
  }, []);

  useEffect(() => {
    registerAddAction(beginCreate);
    return () => registerAddAction(null);
  }, [beginCreate, registerAddAction]);

  const beginEdit = useCallback((config: VerificationAlertConfig) => {
    setDraft(toDraft(config));
    setSaveError(null);
  }, []);

  const updateDraft = useCallback((patch: Partial<VerificationDraft>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setSaveError(null);
  }, []);

  const saveDraft = useCallback(async () => {
    if (!draft) return;
    const validationError = validateDraft(draft);
    if (validationError) {
      setSaveError(validationError);
      return;
    }

    const frames = Number(draft.num_frames);
    const common = {
      prompt: draft.prompt.trim(),
      system_prompt: trimmedOrNull(draft.system_prompt),
      enrichment_prompt: trimmedOrNull(draft.enrichment_prompt),
      output_category: trimmedOrNull(draft.output_category),
      vlm_params: { ...draft.vlm_params, num_frames: frames },
    };

    setSaving(true);
    setSaveError(null);
    try {
      if (draft.mode === 'create') {
        const input: CreateVerificationAlertConfigInput = {
          alert_type: draft.alert_type.trim(),
          ...common,
        };
        await createConfig(input);
      } else {
        const input: UpdateVerificationAlertConfigInput = common;
        await updateConfig(draft.originalAlertType ?? draft.alert_type, input);
      }
      setDraft(null);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : 'Failed to save verification rule',
      );
    } finally {
      setSaving(false);
    }
  }, [createConfig, draft, updateConfig]);

  const handleDelete = useCallback(
    async (alertType: string) => {
      setDeleting(alertType);
      setDeleteError(null);
      try {
        await deleteConfig(alertType);
        if (draft?.originalAlertType === alertType) setDraft(null);
      } catch (err) {
        setDeleteError(
          err instanceof Error ? err.message : 'Failed to delete verification rule',
        );
      } finally {
        setDeleting(null);
        setPendingDelete(null);
      }
    },
    [deleteConfig, draft?.originalAlertType],
  );

  const visibleConfigs = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return configs;
    return configs.filter((config) =>
      [config.alert_type, config.output_category, config.prompt].some((value) =>
        (value ?? '').toLowerCase().includes(needle),
      ),
    );
  }, [configs, filter]);

  const panelClass = isDark
    ? 'bg-neutral-950 border-neutral-700'
    : 'bg-white border-gray-200';
  const secondaryButtonClass = `inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
    isDark
      ? 'border-neutral-700 bg-neutral-900 text-neutral-100 hover:bg-neutral-800'
      : 'border-gray-300 bg-white text-gray-800 hover:bg-gray-100'
  }`;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="verification-alerts-tab">
      <div className={`flex-shrink-0 border-b px-6 py-4 ${panelClass}`}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-[260px] flex-1">
            <h3 className="text-sm font-semibold">Candidate verification rules</h3>
            <p className={`mt-1 text-xs ${isDark ? 'text-neutral-400' : 'text-gray-600'}`}>
              Map a detector or behavior event to a VLM question. Only confirmed candidates become alerts.
            </p>
          </div>
          <label htmlFor="verification-rule-filter" className="sr-only">
            Filter candidate verification rules
          </label>
          <input
            id="verification-rule-filter"
            type="search"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter rules"
            className={`${inputClass} w-56`}
          />
          {lastRefreshedAt ? (
            <span className={`text-xs ${isDark ? 'text-neutral-400' : 'text-gray-500'}`}>
              Updated {lastRefreshedAt.toLocaleTimeString()}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={loading}
            aria-label={loading ? 'Refreshing verification rules' : 'Refresh verification rules'}
            className={secondaryButtonClass}
          >
            <IconRefresh className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        {error ? (
          <div
            role="alert"
            data-testid="verification-alerts-error"
            className={`mt-3 flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
              isDark
                ? 'border-red-500/30 bg-red-500/10 text-red-300'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            <IconAlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
        {deleteError ? (
          <div
            role="alert"
            className={`mt-3 flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
              isDark
                ? 'border-red-500/30 bg-red-500/10 text-red-300'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            <IconAlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{deleteError}</span>
            <button type="button" onClick={() => setDeleteError(null)} aria-label="Dismiss delete error">
              <IconX className="h-4 w-4" />
            </button>
          </div>
        ) : null}
      </div>

      {draft ? (
        <section
          aria-label={draft.mode === 'create' ? 'Create verification rule' : 'Edit verification rule'}
          className={`mx-6 mt-5 rounded-lg border p-4 ${panelClass}`}
          data-testid="verification-rule-editor"
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h3 className="text-base font-semibold">
                {draft.mode === 'create' ? 'New candidate verification rule' : `Edit ${draft.alert_type}`}
              </h3>
              <p className={`mt-1 text-xs ${isDark ? 'text-neutral-400' : 'text-gray-600'}`}>
                The trigger comes from video analytics; the prompt decides whether the candidate is real.
              </p>
            </div>
            <button type="button" onClick={() => setDraft(null)} aria-label="Close rule editor">
              <IconX className="h-5 w-5" />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Trigger alert type *</span>
              <input
                type="text"
                value={draft.alert_type}
                onChange={(event) => updateDraft({ alert_type: event.target.value })}
                disabled={draft.mode === 'edit'}
                maxLength={100}
                placeholder="FOV Count Violation"
                className={`${inputClass} disabled:cursor-not-allowed disabled:opacity-70`}
                data-testid="verification-alert-type-input"
              />
              <span className={`text-xs ${isDark ? 'text-neutral-400' : 'text-gray-500'}`}>
                Must exactly match the event category emitted by analytics. It cannot be renamed after creation.
              </span>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Output label</span>
              <input
                type="text"
                value={draft.output_category}
                onChange={(event) => updateDraft({ output_category: event.target.value })}
                maxLength={200}
                placeholder="PPE Compliance Violation"
                className={inputClass}
                data-testid="verification-output-category-input"
              />
              <span className={`text-xs ${isDark ? 'text-neutral-400' : 'text-gray-500'}`}>
                Friendly category shown when the VLM confirms the candidate.
              </span>
            </label>

            <label className="flex flex-col gap-1 text-sm lg:col-span-2">
              <span className="font-medium">Verification prompt *</span>
              <textarea
                value={draft.prompt}
                onChange={(event) => updateDraft({ prompt: event.target.value })}
                maxLength={5000}
                rows={3}
                placeholder="Is any visible person missing the required protective equipment? Return the configured verdict format."
                className={`${inputClass} resize-y`}
                data-testid="verification-prompt-input"
              />
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">System instructions</span>
              <textarea
                value={draft.system_prompt}
                onChange={(event) => updateDraft({ system_prompt: event.target.value })}
                maxLength={5000}
                rows={3}
                placeholder="Inspect only visible evidence and follow the required response schema."
                className={`${inputClass} resize-y`}
                data-testid="verification-system-prompt-input"
              />
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Enrichment prompt</span>
              <textarea
                value={draft.enrichment_prompt}
                onChange={(event) => updateDraft({ enrichment_prompt: event.target.value })}
                maxLength={5000}
                rows={3}
                placeholder="Optional follow-up description for confirmed alerts."
                className={`${inputClass} resize-y`}
                data-testid="verification-enrichment-prompt-input"
              />
            </label>

            <label className="flex max-w-xs flex-col gap-1 text-sm">
              <span className="font-medium">Frame samples *</span>
              <input
                type="number"
                min={1}
                max={4}
                step={1}
                value={draft.num_frames}
                onChange={(event) => updateDraft({ num_frames: event.target.value })}
                className={inputClass}
                data-testid="verification-num-frames-input"
              />
              <span className={`text-xs ${isDark ? 'text-neutral-400' : 'text-gray-500'}`}>
                Thor samples 1–4 snapshots across the candidate window.
              </span>
            </label>
          </div>

          {saveError ? (
            <div
              role="alert"
              data-testid="verification-save-error"
              className={`mt-4 flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
                isDark
                  ? 'border-red-500/30 bg-red-500/10 text-red-300'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              <IconAlertCircle className="h-4 w-4 flex-shrink-0" />
              {saveError}
            </div>
          ) : null}

          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setDraft(null)} className={secondaryButtonClass}>
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void saveDraft()}
              disabled={saving}
              className="inline-flex min-w-[112px] items-center justify-center gap-2 rounded-md border border-[#76b900] bg-[#76b900] px-3 py-2 text-sm font-semibold text-black transition-colors hover:bg-[#8bd000] disabled:cursor-not-allowed disabled:opacity-60"
              data-testid="verification-save-button"
            >
              {saving ? <IconLoader2 className="h-4 w-4 animate-spin" /> : <IconDeviceFloppy className="h-4 w-4" />}
              {saving ? 'Saving…' : draft.mode === 'create' ? 'Create rule' : 'Save changes'}
            </button>
          </div>
        </section>
      ) : null}

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        <table className={`w-full min-w-[960px] table-fixed border-collapse ${isDark ? '' : 'bg-white'}`} data-testid="verification-rules-table">
          <thead className={`sticky top-0 z-10 border-b ${isDark ? 'border-neutral-700 bg-neutral-900' : 'border-gray-300 bg-gray-100'}`}>
            <tr>
              <th className={`${thClass} w-24`}>Actions</th>
              <th className={`${thClass} w-48`}>Trigger type</th>
              <th className={`${thClass} w-44`}>Output label</th>
              <th className={thClass}>Verification prompt</th>
              <th className={`${thClass} w-24`}>Frames</th>
              <th className={`${thClass} w-44`}>Updated</th>
            </tr>
          </thead>
          <tbody>
            {loading && configs.length === 0 ? (
              <tr>
                <td colSpan={6} className={`py-10 text-center text-sm ${isDark ? 'text-neutral-400' : 'text-gray-500'}`}>
                  <span className="inline-flex items-center gap-2"><IconLoader2 className="h-4 w-4 animate-spin" />Loading verification rules…</span>
                </td>
              </tr>
            ) : visibleConfigs.length === 0 ? (
              <tr>
                <td colSpan={6} className={`py-10 text-center text-sm ${isDark ? 'text-neutral-400' : 'text-gray-500'}`}>
                  {configs.length === 0
                    ? 'No candidate verification rules yet. Create one to turn analytics events into verified alerts.'
                    : 'No verification rules match this filter.'}
                </td>
              </tr>
            ) : (
              visibleConfigs.map((config, index) => (
                <tr
                  key={config.alert_type}
                  data-testid="verification-rule-row"
                  className={`border-b ${isDark ? `border-neutral-800 ${index % 2 ? 'bg-neutral-950' : 'bg-black'}` : `border-gray-200 ${index % 2 ? 'bg-gray-50' : 'bg-white'}`}`}
                >
                  <td className="px-3 py-3 align-top">
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => beginEdit(config)}
                        aria-label={`Edit verification rule ${config.alert_type}`}
                        className={`rounded p-1.5 ${isDark ? 'text-neutral-300 hover:bg-neutral-800 hover:text-[#76b900]' : 'text-gray-600 hover:bg-gray-100 hover:text-green-700'}`}
                      >
                        <IconEdit className="h-4 w-4" />
                      </button>
                      {pendingDelete === config.alert_type ? (
                        <>
                          <button
                            type="button"
                            onClick={() => void handleDelete(config.alert_type)}
                            disabled={deleting === config.alert_type}
                            aria-label={`Confirm delete of verification rule ${config.alert_type}`}
                            className={`rounded p-1.5 ${isDark ? 'bg-red-500/10 text-red-400' : 'bg-red-50 text-red-600'}`}
                          >
                            {deleting === config.alert_type ? <IconLoader2 className="h-4 w-4 animate-spin" /> : <IconCheck className="h-4 w-4" />}
                          </button>
                          <button type="button" onClick={() => setPendingDelete(null)} aria-label="Cancel verification rule delete" className="rounded p-1.5">
                            <IconX className="h-4 w-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setPendingDelete(config.alert_type)}
                          aria-label={`Delete verification rule ${config.alert_type}`}
                          className={`rounded p-1.5 ${isDark ? 'text-neutral-300 hover:bg-neutral-800 hover:text-red-400' : 'text-gray-600 hover:bg-gray-100 hover:text-red-600'}`}
                        >
                          <IconTrash className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                  <td className={`px-3 py-3 align-top font-medium ${readOnlyCellClass}`}>{config.alert_type}</td>
                  <td className={`px-3 py-3 align-top ${readOnlyCellClass}`}>{config.output_category || '—'}</td>
                  <td className={`px-3 py-3 align-top ${readOnlyCellClass}`} title={config.prompt}>
                    <div
                      style={{
                        display: '-webkit-box',
                        WebkitBoxOrient: 'vertical',
                        WebkitLineClamp: 3,
                        overflow: 'hidden',
                      }}
                    >
                      {config.prompt}
                    </div>
                  </td>
                  <td className={`px-3 py-3 align-top ${readOnlyCellClass}`}>{config.vlm_params?.num_frames ?? 'Default'}</td>
                  <td className={`px-3 py-3 align-top text-xs ${readOnlyCellClass}`}>
                    {config.updated_at ? new Date(config.updated_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        <div className="flex justify-center pt-6">
          <button type="button" onClick={beginCreate} className={secondaryButtonClass} data-testid="add-verification-rule-button">
            <IconPlus className="h-4 w-4" />
            Create verification rule
          </button>
        </div>
      </div>
    </div>
  );
};
