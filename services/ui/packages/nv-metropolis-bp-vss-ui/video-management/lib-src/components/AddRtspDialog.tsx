// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import { addRtspStream } from "../rtspStream";
import {
  SEMANTIC_ANALYSIS_PROFILE_ID,
  type AnalysisProfile,
  loadAnalysisProfiles,
  recommendAnalysisProfile,
} from "../analysisProfiles";
import { requestMonitoringSetup } from "../monitoringSetup";
import { parseApiError } from "../utils";
import { Button, TextInput } from "@nvidia/foundations-react-core";
import React, { useEffect, useState } from "react";

const POPUP_OVERLAY_VIEWPORT =
  "fixed inset-0 z-50 flex items-center justify-center bg-black/50";
/** Covers only the parent `relative` region (e.g. Video Management main pane), not the whole browser window */
const POPUP_OVERLAY_CONTAINED =
  "absolute inset-0 z-40 flex items-center justify-center bg-black/50";

interface AddRtspDialogProps {
  isOpen: boolean;
  agentApiUrl?: string | null;
  onClose: () => void;
  onSuccess?: () => void;
  /** `contained` = overlay only the nearest positioned ancestor (Video Management pane). Default `viewport` = full window. */
  overlay?: "viewport" | "contained";
}

export const AddRtspDialog: React.FC<AddRtspDialogProps> = ({
  isOpen,
  agentApiUrl,
  onClose,
  onSuccess,
  overlay = "viewport",
}) => {
  const [rtspUrl, setRtspUrl] = useState("");
  const [sensorName, setSensorName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [analysisProfiles, setAnalysisProfiles] = useState<AnalysisProfile[]>([]);
  const [analysisProfileId, setAnalysisProfileId] = useState(SEMANTIC_ANALYSIS_PROFILE_ID);
  const [analysisIntent, setAnalysisIntent] = useState("");
  const [profileLoading, setProfileLoading] = useState(false);
  const [recommendation, setRecommendation] = useState<string | null>(null);
  const [userEditedName, setUserEditedName] = useState(false); // Track if user manually edited the name
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen || !agentApiUrl) return;
    const controller = new AbortController();
    setProfileLoading(true);
    loadAnalysisProfiles(agentApiUrl, controller.signal)
      .then((profiles) => {
        setAnalysisProfiles(profiles);
        const selected = profiles.find((profile) => profile.id === analysisProfileId && profile.ready);
        if (!selected) {
          setAnalysisProfileId(
            profiles.find((profile) => profile.id === SEMANTIC_ANALYSIS_PROFILE_ID && profile.ready)?.id ??
              profiles.find((profile) => profile.ready)?.id ??
              SEMANTIC_ANALYSIS_PROFILE_ID,
          );
        }
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : "Analysis profiles are unavailable.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setProfileLoading(false);
      });
    return () => controller.abort();
  }, [agentApiUrl, isOpen]);

  const extractNameFromUrl = (url: string): string =>
    url
      .split("?")[0]
      .split("/")
      .filter((p) => p.trim())
      .pop() ?? "";

  const handleRtspUrlChange = (value: string) => {
    setRtspUrl(value);
    if (error) setError(null);
    // Auto-fill sensor name if user hasn't manually edited it and URL is valid
    if (!userEditedName && value.trim().startsWith("rtsp://")) {
      setSensorName(extractNameFromUrl(value.trim()));
    }
  };

  const handleSensorNameChange = (value: string) => {
    setSensorName(value);
    setUserEditedName(true);
    if (error) setError(null);
  };

  const handleClose = () => {
    setRtspUrl("");
    setSensorName("");
    setUsername("");
    setPassword("");
    setAnalysisProfileId(SEMANTIC_ANALYSIS_PROFILE_ID);
    setAnalysisIntent("");
    setRecommendation(null);
    setUserEditedName(false);
    setError(null);
    setIsSubmitting(false);
    onClose();
  };

  const handleRecommend = async () => {
    if (!agentApiUrl || !sensorName.trim()) {
      setError("Name the camera before asking Thor for a recommendation.");
      return;
    }
    setProfileLoading(true);
    setError(null);
    try {
      const result = await recommendAnalysisProfile(agentApiUrl, {
        intent: analysisIntent.trim(),
        sourceKind: "live",
        sourceName: sensorName.trim(),
      });
      const profile = analysisProfiles.find((candidate) => candidate.id === result.profileId);
      if (!profile?.ready) {
        throw new Error(`${profile?.name ?? "The recommended profile"} is not ready on this Thor.`);
      }
      setAnalysisProfileId(profile.id);
      setRecommendation(`${result.reason} ${Math.round(result.confidence * 100)}% confidence.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Thor could not recommend a profile.");
    } finally {
      setProfileLoading(false);
    }
  };

  const handleSubmit = async (event?: React.FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const trimmed = rtspUrl.trim();
    const trimmedName = sensorName.trim();
    const validationError = !trimmed
      ? "RTSP URL is required."
      : !trimmed.startsWith("rtsp://")
      ? 'RTSP URL must start with "rtsp://".'
      : !trimmedName
      ? "Sensor Name is required."
      : !agentApiUrl
      ? "Agent API URL not configured."
      : null;
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      const result = await addRtspStream(agentApiUrl!, {
        sensorUrl: trimmed,
        name: trimmedName,
        username: username.trim(),
        password,
        analysisProfileId,
      });
      handleClose();
      onSuccess?.();
      void requestMonitoringSetup({
        blocking: false,
        analysisProfileId: result.analysisProfileId,
        detectionEnabled: result.detectionEnabled ?? false,
        name: result.name,
        sensorId: result.sensorId,
        sourceKind: "live",
        streamUrl: trimmed,
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("Error adding RTSP sensor via agent API:", err);
      setError(
        parseApiError(
          err instanceof Error ? err.message : "",
          "Failed to add RTSP. Please check the URL and try again."
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const dialogRef = useDialogAccessibility<HTMLFormElement>({ isOpen, onClose: handleClose });

  if (!isOpen) return null;

  const overlayClass =
    overlay === "contained" ? POPUP_OVERLAY_CONTAINED : POPUP_OVERLAY_VIEWPORT;
  const dialogMaxHeight = overlay === "contained" ? "calc(100% - 2rem)" : "calc(100vh - 2rem)";

  return (
    <div className={`${overlayClass} overflow-y-auto p-4`} onClick={handleClose}>
      <form
        ref={dialogRef}
        data-testid="add-rtsp-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-rtsp-dialog-title"
        className="vm-add-source-dialog relative z-50 my-auto flex w-full max-w-[680px] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-black"
        style={{ maxHeight: dialogMaxHeight }}
        onClick={(e) => e.stopPropagation()}
        onSubmit={(event) => void handleSubmit(event)}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-600">
          <div className="flex items-center gap-3">
            {/* Camera/monitor icon */}
            <svg
              className="text-gray-600 dark:text-gray-300"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            <span
              id="add-rtsp-dialog-title"
              className="text-sm font-medium uppercase tracking-wide text-gray-800 dark:text-gray-200"
            >
              ADD LIVE CAMERA
            </span>
          </div>
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close"
            className="p-1.5 rounded transition-colors text-gray-400 hover:text-white hover:bg-neutral-700 dark:text-gray-400 dark:hover:text-white dark:hover:bg-neutral-700"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="vm-add-source-dialog__body overflow-y-auto p-6 space-y-5">
          <p className="vm-dialog-intro">
            Connect an RTSP camera to local VSS processing on this NVIDIA Thor.
          </p>
          {/* RTSP URL (required) */}
          <div>
            <label
              className="block text-sm mb-3 text-gray-700 dark:text-gray-300"
              htmlFor="add-rtsp-url"
            >
              RTSP URL <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <TextInput
                value={rtspUrl}
                onValueChange={(val: string) => handleRtspUrlChange(val)}
                placeholder="rtsp://cam-warehouse.example.com:554/warehouse/cam01"
                attributes={{
                  TextInputValue: {
                    id: "add-rtsp-url",
                    required: true,
                    "aria-required": "true",
                  },
                }}
              />
            </div>
            <p className="text-xs flex items-center gap-2 mt-3 text-gray-500">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-gray-500 flex-shrink-0" />
              e.g. rtsp://192.168.1.10:554/stream1
            </p>
          </div>

          {/* Sensor Name (required) */}
          <div>
            <label
              className="block text-sm mb-3 text-gray-700 dark:text-gray-300"
              htmlFor="add-rtsp-sensor-name"
            >
              Sensor Name{" "}
              <span className="text-red-500" aria-hidden="true">
                *
              </span>
            </label>
            <TextInput
              value={sensorName}
              onValueChange={(val: string) => handleSensorNameChange(val)}
              placeholder="e.g. Warehouse Camera 01"
              attributes={{
                TextInputValue: {
                  id: "add-rtsp-sensor-name",
                  required: true,
                  "aria-required": "true",
                },
              }}
            />
          </div>

          <fieldset className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <legend className="text-sm font-medium text-gray-800 dark:text-gray-100">
                  AI analysis profile
                </legend>
                <p className="mt-1 text-xs leading-5 text-gray-500">
                  Every profile remains searchable. Detection profiles also publish tracked objects
                  for compatible alerts and overlays.
                </p>
              </div>
              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-[11px] text-cyan-700 dark:text-cyan-300">
                Runs locally on Thor
              </span>
            </div>

            {profileLoading && analysisProfiles.length === 0 ? (
              <div className="rounded-md border border-gray-200 p-4 text-sm text-gray-500 dark:border-gray-700">
                Loading installed profiles…
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3">
                {analysisProfiles.map((profile) => {
                  const selected = profile.id === analysisProfileId;
                  return (
                    <label
                      className={`rounded-md border p-4 transition-colors ${
                        profile.ready ? "cursor-pointer" : "cursor-not-allowed opacity-60"
                      } ${
                        selected
                          ? "border-cyan-500 bg-cyan-500/10"
                          : "border-gray-300 hover:border-gray-400 dark:border-gray-700 dark:hover:border-gray-600"
                      }`}
                      key={profile.id}
                    >
                      <span className="flex items-start gap-3">
                        <input
                          checked={selected}
                          className="mt-1"
                          disabled={!profile.ready}
                          name="analysis-profile"
                          onChange={() => {
                            setAnalysisProfileId(profile.id);
                            setRecommendation(null);
                            setError(null);
                          }}
                          type="radio"
                          value={profile.id}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center justify-between gap-2">
                            <strong className="text-sm text-gray-800 dark:text-gray-100">
                              {profile.name}
                            </strong>
                            <span className="text-[11px] uppercase tracking-wide text-gray-500">
                              {profile.resourceTier} load
                            </span>
                          </span>
                          <span className="mt-1 block text-xs leading-5 text-gray-500">
                            {profile.description}
                          </span>
                          <span className="mt-2 block text-[11px] text-gray-500">
                            {profile.modelLabel}
                            {profile.objectTypes.length > 0
                              ? ` · ${profile.objectTypes.join(", ")}`
                              : " · semantic search + visual reasoning"}
                          </span>
                          {!profile.ready && (
                            <span className="mt-2 block text-xs text-amber-600 dark:text-amber-400">
                              Unavailable: {profile.readyDetail}
                            </span>
                          )}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}

            <div className="rounded-md border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-white/[0.03]">
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300" htmlFor="analysis-intent">
                Not sure? Describe what matters in this camera
              </label>
              <textarea
                className="mt-2 min-h-[72px] w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-cyan-500 dark:border-gray-700 dark:bg-black dark:text-gray-100"
                id="analysis-intent"
                onChange={(event) => {
                  setAnalysisIntent(event.target.value);
                  setRecommendation(null);
                }}
                placeholder="Example: Monitor vehicles, pedestrians, and stopped traffic at this intersection."
                value={analysisIntent}
              />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <p className="max-w-md text-xs leading-5 text-gray-500">
                  Thor recommends from the profiles actually installed here; it never invents a pipeline.
                </p>
                <Button
                  disabled={profileLoading || !sensorName.trim()}
                  kind="secondary"
                  onClick={() => void handleRecommend()}
                  type="button"
                >
                  {profileLoading ? "Checking…" : "Recommend with Thor"}
                </Button>
              </div>
              {recommendation && (
                <p className="mt-3 rounded border border-cyan-500/30 bg-cyan-500/10 p-3 text-xs leading-5 text-cyan-800 dark:text-cyan-200">
                  {recommendation}
                </p>
              )}
            </div>
          </fieldset>

          <fieldset className="space-y-3">
            <legend className="text-sm text-gray-700 dark:text-gray-300">
              Authentication{" "}
              <span className="text-xs text-gray-500">(optional)</span>
            </legend>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label
                  className="mb-2 block text-sm text-gray-700 dark:text-gray-300"
                  htmlFor="add-rtsp-username"
                >
                  Username
                </label>
                <TextInput
                  value={username}
                  onValueChange={(value: string) => setUsername(value)}
                  placeholder="Camera username"
                  attributes={{
                    TextInputValue: {
                      id: "add-rtsp-username",
                      autoComplete: "username",
                    },
                  }}
                />
              </div>
              <div>
                <label
                  className="mb-2 block text-sm text-gray-700 dark:text-gray-300"
                  htmlFor="add-rtsp-password"
                >
                  Password
                </label>
                <TextInput
                  value={password}
                  onValueChange={(value: string) => setPassword(value)}
                  placeholder="Camera password"
                  attributes={{
                    TextInputValue: {
                      id: "add-rtsp-password",
                      type: "password",
                      autoComplete: "current-password",
                    },
                  }}
                />
              </div>
            </div>
            <p className="text-xs text-gray-500">
              Credentials are sent only to the local VSS agent.
            </p>
          </fieldset>

          {error && (
            <div className="max-h-24 overflow-auto rounded p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
              <p className="text-sm text-red-600 dark:text-red-400 break-words whitespace-pre-wrap">
                {error}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-600">
          <Button kind="secondary" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            kind="primary"
            type="submit"
            disabled={
              isSubmitting ||
              profileLoading ||
              !analysisProfiles.some((profile) => profile.id === analysisProfileId && profile.ready)
            }
          >
            {isSubmitting ? "Connecting..." : "Connect camera"}
          </Button>
        </div>
      </form>
    </div>
  );
};
