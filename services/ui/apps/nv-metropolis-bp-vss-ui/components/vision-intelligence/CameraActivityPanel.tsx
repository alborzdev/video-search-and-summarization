// SPDX-License-Identifier: MIT

import type {
  SourceAnalysisState,
  SourceIntelligence,
} from "./OperationsWorkspace";
import type { SourceAnalysisProfile } from "./analysisProfiles";
import type { VisionStream } from "./types";
import type { useLiveCapture } from "./useLiveCapture";
import { sourceKind } from "./utils";
import {
  IconArrowRight,
  IconChevronDown,
  IconPlayerPause,
  IconPlayerPlayFilled,
  IconPlayerStopFilled,
  IconSearch,
  IconSettings,
} from "@tabler/icons-react";
import React, { useState } from "react";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="vi-intelligence-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function CameraActivityPanel({
  stream,
  analysisState,
  analysisProfile,
  analysisProfiles,
  intelligence,
  isLoading,
  isUpdating,
  isAsking,
  controlError,
  capture,
  livePreviewAvailable = false,
  visualAnalystAvailable,
  onToggleAnalysis,
  onSetAnalysisProfile,
  onInvestigate,
}: {
  stream: VisionStream;
  analysisState: SourceAnalysisState;
  analysisProfile: SourceAnalysisProfile | null;
  analysisProfiles: SourceAnalysisProfile[];
  intelligence: SourceIntelligence | null;
  isLoading: boolean;
  isUpdating: boolean;
  isAsking: boolean;
  controlError: string | null;
  capture: ReturnType<typeof useLiveCapture>;
  livePreviewAvailable?: boolean;
  visualAnalystAvailable?: boolean | null;
  onToggleAnalysis: () => void;
  onSetAnalysisProfile: (profileId: string) => void;
  onInvestigate: () => void;
}) {
  const [pendingProfileId, setPendingProfileId] = useState(
    analysisProfile?.id ?? ""
  );
  const live = sourceKind(stream) === "Live";
  const removed = stream.connectionState === "removed";
  const disconnected =
    live && (removed || (stream.connectionState === "offline" && !livePreviewAvailable));
  const count = (value: number | null | undefined, suffix = "") =>
    value === null || value === undefined
      ? isLoading
        ? "Checking…"
        : "Unavailable"
      : `${value.toLocaleString()}${suffix}`;
  const lastIndexed = intelligence?.lastSemanticAt;
  const indexedTime =
    lastIndexed && Number.isFinite(Date.parse(lastIndexed))
      ? new Date(lastIndexed).toLocaleString([], {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : isLoading
      ? "Checking…"
      : "Not available";
  const profileId = pendingProfileId || analysisProfile?.id || "";
  const indexingLabel =
    analysisState === "paused"
      ? "Paused"
      : analysisState === "active"
      ? "Active"
      : analysisState === "changing"
      ? "Updating"
      : analysisState === "partial"
      ? "Needs attention"
      : "Checking";
  return (
    <aside
      className="vi-camera-activity"
      aria-label="Source intelligence status"
    >
      <h2>{live ? "Camera activity" : "Recording activity"}</h2>
      {live && (
        <section className="vi-camera-recording" aria-label="Live recording">
          <div className="vi-camera-section-heading">
            <h3>
              <i className={capture.capture === "on" ? "is-on" : ""} />
              Live recording
            </h3>
            <span className={capture.capture === "on" ? "is-on" : ""}>
              {capture.changing
                ? "Updating"
                : capture.capture === "on"
                ? "On"
                : capture.capture === "off"
                ? "Off"
                : "Checking"}
            </span>
          </div>
          <p>
            {capture.capture === "on"
              ? "Recent footage is available for questions and replay."
              : capture.capture === "off"
              ? "Start capture to ask questions and replay recent activity."
              : "Checking recording before enabling live questions."}
          </p>
          <button
            className="vi-camera-button"
            type="button"
            disabled={
              isAsking ||
              capture.changing ||
              capture.capture === "unknown" ||
              (removed && capture.capture === "off")
            }
            onClick={() => void capture.toggle()}
          >
            {capture.capture === "on" ? (
              <IconPlayerStopFilled size={16} />
            ) : (
              <IconPlayerPlayFilled size={16} />
            )}
            {capture.changing
              ? "Updating capture…"
              : capture.capture === "on"
              ? "Stop capture"
              : "Start live capture"}
          </button>
          {capture.error && (
            <p className="vi-camera-error" role="alert">
              {capture.error}
            </p>
          )}
        </section>
      )}
      <section
        className="vi-camera-indexing"
        aria-label={live ? "Search indexing" : "Recording analysis"}
      >
        <div className="vi-camera-section-heading">
          <h3>{live ? "Search indexing" : "Recorded evidence"}</h3>
          {live && (
            <span className={analysisState === "paused" ? "is-paused" : ""}>
              {analysisState === "paused" && <IconPlayerPause size={15} />}{" "}
              {indexingLabel}
            </span>
          )}
        </div>
        <p>
          {disconnected
            ? "Check the camera or simulator connection, then retry analysis to verify recovery."
            : !live
            ? "Search and inspect this recording at its playback position."
            : analysisState === "paused"
            ? "Earlier footage stays searchable. Resume to index new activity."
            : analysisState === "active"
            ? "Cosmos Embed turns video segments into searchable embeddings. Coverage below shows how recent the index is."
            : "Live analysis is not confirmed. Check readiness or retry this source."}
        </p>
        {live && (
          <button
            className="vi-camera-primary"
            type="button"
            disabled={isUpdating || analysisState === "unknown" || removed}
            onClick={onToggleAnalysis}
          >
            {analysisState !== "active" ? (
              <IconPlayerPlayFilled size={16} />
            ) : (
              <IconPlayerPause size={16} />
            )}
            {isUpdating
              ? "Updating analysis…"
              : analysisState === "unknown"
              ? "Analysis status unavailable"
              : analysisState === "paused"
              ? "Resume analysis"
              : analysisState === "partial"
              ? "Retry analysis"
              : "Pause analysis"}
          </button>
        )}
        {controlError && (
          <p className="vi-camera-error" role="alert">
            {controlError}
          </p>
        )}
      </section>
      <div className="vi-camera-metrics">
        <Metric
          label="Searchable video segments"
          value={count(intelligence?.semanticSegments)}
        />
        {live && <Metric label="Searchable through" value={indexedTime} />}
      </div>
      <button
        className="vi-camera-button"
        type="button"
        onClick={onInvestigate}
      >
        <IconSearch size={17} />
        {live ? "Search this camera" : "Search this recording"}
        <IconArrowRight size={16} />
      </button>
      <details className="vi-camera-processing">
        <summary>
          <IconSettings size={19} />
          Processing details
          <IconChevronDown size={17} />
        </summary>
        <Metric
          label={live ? "Ask this camera" : "Ask this recording"}
          value={
            disconnected && !capture.canAsk
              ? "No live frames — camera disconnected"
              : visualAnalystAvailable !== true
              ? visualAnalystAvailable === false
                ? "Unavailable"
                : "Checking…"
              : live && capture.capture === "unknown"
              ? "Checking recording…"
              : live && capture.capture === "off"
              ? "Start capture"
              : capture.warming
              ? "Preparing footage"
              : isAsking
              ? "Inspecting footage"
              : "Ready"
          }
        />
        <Metric
          label="Caption history"
          value={count(intelligence?.captionSegments, " captioned moments")}
        />
        <Metric
          label="Detection + tracking"
          value={
            disconnected
              ? "No live input"
              : analysisProfile?.detectionEnabled
              ? count(intelligence?.trackedObservations, " observations")
              : "Not enabled"
          }
        />
        <Metric
          label="Event candidates"
          value={count(intelligence?.evidenceEvents, " saved candidates")}
        />
        <Metric
          label="Analysis profile"
          value={
            analysisProfile?.shortName ??
            (isLoading ? "Checking…" : "Unavailable")
          }
        />
        {analysisProfile && (
          <label className="vi-camera-profile">
            <span>{live ? "Source analysis" : "Recording analysis"}</span>
            <select
              aria-label="Source analysis profile"
              disabled={isUpdating}
              value={live ? analysisProfile.id : profileId}
              onChange={(event) =>
                live
                  ? onSetAnalysisProfile(event.target.value)
                  : setPendingProfileId(event.target.value)
              }
            >
              {analysisProfiles.map((profile) => (
                <option
                  key={profile.id}
                  value={profile.id}
                  disabled={!profile.ready}
                >
                  {profile.shortName}
                  {profile.ready ? "" : " · offline"}
                </option>
              ))}
            </select>
            <small>
              {live
                ? analysisProfile.modelLabel
                : "Changing this replaces detector-derived evidence; semantic search and the uploaded video stay intact."}
            </small>
            {!live && (
              <button
                className="vi-camera-button"
                type="button"
                disabled={
                  isUpdating || !profileId || profileId === analysisProfile.id
                }
                onClick={() => onSetAnalysisProfile(profileId)}
              >
                {isUpdating ? "Reprocessing…" : "Apply and reprocess recording"}
              </button>
            )}
          </label>
        )}
      </details>
    </aside>
  );
}
