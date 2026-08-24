// SPDX-License-Identifier: MIT
import { useDialogAccessibility } from '@aiqtoolkit-ui/common';
import React, { useCallback, useEffect, useState } from 'react';
import { Button, TextInput, Select } from '@nvidia/foundations-react-core';
import { IconChevronDown, IconVideo, IconX } from '@tabler/icons-react';
import {
  SEMANTIC_ANALYSIS_PROFILE_ID,
  type AnalysisProfile,
  loadAnalysisProfiles,
  recommendAnalysisProfile,
} from '../analysisProfiles';

const ACCEPTED_EXTENSIONS = ['.mp4', '.mkv'];

const POPUP_OVERLAY_VIEWPORT = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50';
/** Covers only the parent `relative` region (e.g. Video Management main pane), not the whole browser window */
const POPUP_OVERLAY_CONTAINED = 'absolute inset-0 z-40 flex items-center justify-center bg-black/50';
const POPUP_CONTAINER_CLASS = 'mx-4 w-full max-w-xl rounded-lg bg-white p-6 shadow-xl dark:bg-neutral-900';

interface AgentUploadFileItem {
  id: string;
  file: File;
  isExpanded: boolean;
  formData: Record<string, any>;
}

interface AgentUploadDialogProps {
  agentApiUrl?: string | null;
  open: boolean;
  files: AgentUploadFileItem[];
  configTemplate: any;
  onAddMore: () => void;
  onFilesDropped: (files: File[]) => void;
  onClose: () => void;
  onConfirmUpload: () => void;
  onToggleExpand: (fileId: string) => void;
  onRemoveFile: (fileId: string) => void;
  onFieldChange: (fileId: string, fieldName: string, value: any) => void;
  /** `contained` = overlay only the nearest positioned ancestor (Video Management pane). Default `viewport` = full window. */
  overlay?: 'viewport' | 'contained';
}

export const AgentUploadDialog: React.FC<AgentUploadDialogProps> = ({
  agentApiUrl,
  open,
  files,
  configTemplate,
  onAddMore,
  onFilesDropped,
  onClose,
  onConfirmUpload,
  onToggleExpand,
  onRemoveFile,
  onFieldChange,
  overlay = 'viewport',
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const [analysisProfiles, setAnalysisProfiles] = useState<AnalysisProfile[]>([]);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [intentByFile, setIntentByFile] = useState<Record<string, string>>({});
  const [recommendationByFile, setRecommendationByFile] = useState<Record<string, string>>({});
  const [recommendingFileId, setRecommendingFileId] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !agentApiUrl) return;
    const controller = new AbortController();
    setProfileLoading(true);
    setProfileError(null);
    loadAnalysisProfiles(agentApiUrl, controller.signal)
      .then((profiles) => {
        setAnalysisProfiles(profiles);
        const fallback =
          profiles.find((profile) => profile.id === SEMANTIC_ANALYSIS_PROFILE_ID && profile.ready) ??
          profiles.find((profile) => profile.ready);
        if (!fallback) throw new Error('No analysis profile is currently ready on this Thor.');
        files.forEach((item) => {
          const selected = profiles.find(
            (profile) => profile.id === item.formData.analysisProfileId && profile.ready,
          );
          if (!selected) onFieldChange(item.id, 'analysisProfileId', fallback.id);
        });
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setProfileError(
            requestError instanceof Error
              ? requestError.message
              : 'Analysis profiles are unavailable.',
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setProfileLoading(false);
      });
    return () => controller.abort();
  // Files already carry a safe semantic default, so this fetch is tied to the
  // dialog session rather than every field edit.
  }, [agentApiUrl, open]);

  const recommendForFile = async (item: AgentUploadFileItem) => {
    if (!agentApiUrl) return;
    setRecommendingFileId(item.id);
    setProfileError(null);
    try {
      const recommendation = await recommendAnalysisProfile(agentApiUrl, {
        intent: intentByFile[item.id] ?? '',
        sourceKind: 'recorded',
        sourceName: item.file.name,
      });
      const profile = analysisProfiles.find(
        (candidate) => candidate.id === recommendation.profileId,
      );
      if (!profile?.ready) {
        throw new Error(`${profile?.name ?? 'The recommended profile'} is not ready on this Thor.`);
      }
      onFieldChange(item.id, 'analysisProfileId', profile.id);
      setRecommendationByFile((current) => ({
        ...current,
        [item.id]: `${recommendation.reason} ${Math.round(recommendation.confidence * 100)}% confidence.`,
      }));
    } catch (requestError) {
      setProfileError(
        requestError instanceof Error
          ? requestError.message
          : 'Thor could not recommend a profile.',
      );
    } finally {
      setRecommendingFileId(null);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = Array.from(e.dataTransfer.files).filter((f) =>
      ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)),
    );
    if (dropped.length > 0) onFilesDropped(dropped);
  }, [onFilesDropped]);

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onAddMore();
    }
  }, [onAddMore]);

  const dialogRef = useDialogAccessibility({ isOpen: open, onClose });

  if (!open) return null;

  const renderField = (fileItem: AgentUploadFileItem, field: any) => {
    const fieldName = field['field-name'];
    const value = fileItem.formData[fieldName] ?? field['field-default-value'];
    const isChangeable = field['changeable'] !== false;

    if (field['field-type'] === 'boolean') {
      return (
        <label
          className={`flex items-center gap-3 ${
            isChangeable ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'
          }`}
        >
          <button
            type="button"
            role="switch"
            aria-checked={value}
            disabled={!isChangeable}
            onClick={() => isChangeable && onFieldChange(fileItem.id, fieldName, !value)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              value ? 'bg-[#76b900]' : 'bg-neutral-600'
            } ${!isChangeable ? 'opacity-60 cursor-not-allowed' : ''}`}
          >
            <span
              className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                value ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
          <span className="text-sm text-gray-400 dark:text-gray-400">{value ? 'Yes' : 'No'}</span>
        </label>
      );
    }

    if (field['field-type'] === 'select') {
      return (
        <Select
          value={String(value)}
          disabled={!isChangeable}
          onValueChange={(val: string) => onFieldChange(fileItem.id, fieldName, val)}
          items={field['field-options']?.map((opt: any) => String(opt)) ?? []}
        />
      );
    }

    if (field['field-type'] === 'number') {
      return (
        <TextInput
          type="number"
          value={String(value)}
          disabled={!isChangeable}
          onValueChange={(val: string) => onFieldChange(fileItem.id, fieldName, Number(val))}
        />
      );
    }

    return (
      <TextInput
        value={String(value ?? '')}
        disabled={!isChangeable}
        onValueChange={(val: string) => onFieldChange(fileItem.id, fieldName, val)}
        placeholder={`Enter ${fieldName}`}
      />
    );
  };

  const overlayClass =
    overlay === 'contained' ? POPUP_OVERLAY_CONTAINED : POPUP_OVERLAY_VIEWPORT;

  return (
    <div ref={dialogRef as React.RefObject<HTMLDivElement>} className={overlayClass} role="dialog" aria-modal="true" aria-labelledby="agent-upload-dialog-title">
      <div className={POPUP_CONTAINER_CLASS}>
        <h3 id="agent-upload-dialog-title" className="mb-6 text-center text-lg font-semibold text-gray-900 dark:text-white">
          Upload Files
        </h3>

        {/* Files list */}
        <div className="mb-4">
          <div className="mb-2 flex items-center justify-between">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Files <span className="text-red-500">*</span>
              {files.length > 0 && (
                <span className="ml-2 rounded-full bg-[#76b900] px-2 py-0.5 text-xs text-white">
                  {files.length}
                </span>
              )}
            </label>
            {files.length > 0 && (
              <Button
                kind="primary"
                onClick={onAddMore}
              >
                + Add More
              </Button>
            )}
          </div> 

          {files.length > 0 ? (
            <div className="max-h-96 space-y-2 overflow-y-auto">
              {files.map((item) => {
                const hasTemplateFields = configTemplate && Array.isArray(configTemplate.fields) && configTemplate.fields.length > 0;
                const hasExpandableContent = true;
                const selectedProfile = analysisProfiles.find(
                  (profile) => profile.id === item.formData.analysisProfileId,
                );
                return (
                  <div
                    key={item.id}
                    className="overflow-hidden rounded-lg border border-gray-300 dark:border-gray-600"
                  >
                    <div className="flex items-center justify-between bg-white p-3 dark:bg-neutral-900">
                      <div
                        className={`flex flex-1 items-center gap-2 overflow-hidden ${hasExpandableContent ? 'cursor-pointer' : ''}`}
                        onClick={() => hasExpandableContent && onToggleExpand(item.id)}
                      >
                        {hasExpandableContent && (
                          <IconChevronDown
                            size={16}
                            className={`flex-shrink-0 text-gray-400 transition-transform duration-200 ${
                              item.isExpanded ? 'rotate-180' : ''
                            }`}
                          />
                        )}
                        <IconVideo size={18} className="flex-shrink-0 text-[#76b900]" />
                        <span className="truncate text-sm text-gray-700 dark:text-gray-300">
                          {item.file.name}
                        </span>
                        <span className="flex-shrink-0 text-xs text-gray-400">
                          ({(item.file.size / 1024 / 1024).toFixed(2)} MB)
                        </span>
                        {selectedProfile && (
                          <span className="ml-2 hidden flex-shrink-0 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-700 dark:text-cyan-300 sm:inline">
                            {selectedProfile.shortName}
                          </span>
                        )}
                      </div>
                      <button
                        onClick={() => onRemoveFile(item.id)}
                        aria-label="Remove file"
                        className="p-1.5 rounded transition-colors text-gray-400 hover:text-gray-200 hover:bg-neutral-700 dark:text-gray-400 dark:hover:text-white dark:hover:bg-neutral-700"
                      >
                        <IconX size={18} />
                      </button>
                    </div>

                    {hasExpandableContent && item.isExpanded && (
                      <div className="space-y-4 border-t border-gray-200 bg-gray-50 p-4 dark:border-gray-600 dark:bg-neutral-950">
                        <div>
                          <div className="mb-3">
                            <strong className="text-sm text-gray-900 dark:text-gray-100">Choose how Thor analyzes this video</strong>
                            <p className="mt-1 text-xs leading-5 text-gray-500">
                              Semantic indexing is always available. A detector adds compatible tracks, overlays, and rules.
                            </p>
                          </div>
                          <div className="grid gap-2">
                            {analysisProfiles.map((profile) => (
                              <label
                                className={`rounded-md border p-3 ${
                                  profile.ready ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'
                                } ${
                                  item.formData.analysisProfileId === profile.id
                                    ? 'border-cyan-500 bg-cyan-500/10'
                                    : 'border-gray-300 bg-white dark:border-gray-700 dark:bg-black'
                                }`}
                                key={profile.id}
                              >
                                <span className="flex items-start gap-3">
                                  <input
                                    checked={item.formData.analysisProfileId === profile.id}
                                    className="mt-1"
                                    disabled={!profile.ready}
                                    name={`analysis-profile-${item.id}`}
                                    onChange={() => {
                                      onFieldChange(item.id, 'analysisProfileId', profile.id);
                                      setRecommendationByFile((current) => ({ ...current, [item.id]: '' }));
                                    }}
                                    type="radio"
                                  />
                                  <span className="min-w-0 flex-1">
                                    <span className="flex items-center justify-between gap-3">
                                      <strong className="text-sm text-gray-900 dark:text-gray-100">{profile.name}</strong>
                                      <em className="whitespace-nowrap text-[10px] not-italic uppercase tracking-wider text-gray-500">{profile.resourceTier} load</em>
                                    </span>
                                    <span className="mt-1 block text-xs leading-5 text-gray-500">{profile.description}</span>
                                    <span className="mt-1 block text-[11px] text-gray-500">{profile.modelLabel}</span>
                                    {!profile.ready && <span className="mt-1 block text-xs text-amber-600 dark:text-amber-400">Unavailable: {profile.readyDetail}</span>}
                                  </span>
                                </span>
                              </label>
                            ))}
                          </div>
                        </div>

                        <div className="rounded-md border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-white/[0.03]">
                          <label className="text-xs font-medium text-gray-700 dark:text-gray-300" htmlFor={`analysis-intent-${item.id}`}>
                            Let Thor recommend a profile
                          </label>
                          <textarea
                            className="mt-2 min-h-[64px] w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500 dark:border-gray-700 dark:bg-black dark:text-gray-100"
                            id={`analysis-intent-${item.id}`}
                            onChange={(event) => setIntentByFile((current) => ({ ...current, [item.id]: event.target.value }))}
                            placeholder="Example: Detect pedestrians and vehicles entering a crosswalk."
                            value={intentByFile[item.id] ?? ''}
                          />
                          <div className="mt-2 flex items-center justify-between gap-3">
                            <span className="text-[11px] leading-4 text-gray-500">Only installed VSS-owned pipelines can be selected.</span>
                            <Button
                              disabled={recommendingFileId === item.id || profileLoading}
                              kind="secondary"
                              onClick={() => void recommendForFile(item)}
                            >
                              {recommendingFileId === item.id ? 'Checking…' : 'Recommend with Thor'}
                            </Button>
                          </div>
                          {recommendationByFile[item.id] && (
                            <p className="mt-2 rounded border border-cyan-500/30 bg-cyan-500/10 p-2 text-xs leading-5 text-cyan-800 dark:text-cyan-200">
                              {recommendationByFile[item.id]}
                            </p>
                          )}
                        </div>

                        {hasTemplateFields && (
                        <div className="space-y-3 border-t border-gray-200 pt-4 dark:border-gray-700">
                          {configTemplate.fields.map((field: any) => (
                            <div key={field['field-name']} className="flex items-center gap-3">
                              <label className="w-24 flex-shrink-0 text-xs font-medium text-gray-600 dark:text-gray-400">
                                {field['field-name']}
                              </label>
                              <div className="flex-1">{renderField(item, field)}</div>
                            </div>
                          ))}
                        </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div
              role="button"
              tabIndex={0}
              aria-label="Click or drag movie files here to upload (mp4, mkv)"
              onClick={onAddMore}
              onKeyDown={handleKeyDown}
              onDragOver={handleDragOver}
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`w-full cursor-pointer rounded-lg border-2 border-dashed p-4 text-center transition-colors ${
                isDragOver
                  ? 'border-[#76b900] bg-[#76b900]/10 dark:border-[#76b900] dark:bg-[#76b900]/10'
                  : 'border-gray-300 hover:border-[#76b900] hover:bg-gray-50 dark:border-gray-600 dark:hover:border-[#76b900] dark:hover:bg-black'
              }`}
            >
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Click or drag files here
              </span>
              <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">Movie Files (mp4, mkv)</div>
            </div>
          )}
        </div>

        <div className="flex gap-3">
          <Button
            kind="secondary"
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            kind="primary"
            onClick={onConfirmUpload}
            disabled={
              files.length === 0 ||
              profileLoading ||
              Boolean(profileError) ||
              files.some(
                (item) =>
                  !analysisProfiles.some(
                    (profile) => profile.id === item.formData.analysisProfileId && profile.ready,
                  ),
              )
            }
          >
            Upload {files.length > 0 ? `(${files.length})` : ''}
          </Button>
        </div>
        {profileError && (
          <p className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {profileError}
          </p>
        )}
      </div>
    </div>
  );
};
