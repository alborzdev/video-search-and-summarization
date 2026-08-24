// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import { LiveModeNav } from "./LiveModeNav";
import { VideoHistoryPanel } from "./VideoHistoryPanel";
import { VisionStreamCanvas } from "./VisionStreamCanvas";
import type {
  VisionAnalystPlaybackContext,
  VisionAnalystRequest,
  VisionAnalystResponse,
} from "./analyst";
import { evidenceClipEndpoint } from "./evidenceClip";
import {
  loadAnalysisProfileCatalog,
  loadSourceAnalysisProfile,
  type SourceAnalysisProfile,
} from "./analysisProfiles";
import {
  consolidateIncidents,
  incidentTitle,
  incidentVerdict,
  isOperatorRelevantIncident,
  type AnalyticsIncident,
  type ConsolidatedIncident,
} from "./incidentModel";
import type { OperationsView, VisionStream } from "./types";
import { useVisionStreams } from "./useVisionStreams";
import { createPeerId, sourceKind, streamDisplayName } from "./utils";
import {
  IconAlertCircle,
  IconArrowRight,
  IconArrowsMaximize,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconClock,
  IconEye,
  IconGridDots,
  IconHistory,
  IconMicrophone,
  IconPlayerPlay,
  IconRefresh,
  IconSend2,
  IconShieldCheck,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";

interface OperationsWorkspaceProps {
  agentApiUrl?: string | null;
  initialPanel?: "history";
  initialStreamId?: string;
  initialView?: OperationsView;
  onInvestigate: (query: string, stream?: VisionStream) => void;
  onOpenActivity: () => void;
  onOpenInsights: () => void;
  onOpenRules: (stream?: VisionStream) => void;
  visualAnalystAvailable?: boolean | null;
  vstApiUrl?: string | null;
}

const defaultQuestion = "What is happening in this camera?";

interface SourceIntelligence {
  captionSegments: number | null;
  evidenceEvents: number | null;
  indexingDelaySeconds: number | null;
  lastCaptionAt?: string | null;
  lastSemanticAt?: string | null;
  semanticFresh?: boolean | null;
  semanticSegments: number | null;
  trackedObservations: number | null;
}

type SourceAnalysisState =
  | "active"
  | "changing"
  | "partial"
  | "paused"
  | "unknown";

function cameraAnalysisLabel(
  stream: VisionStream,
  analysisState?: SourceAnalysisState,
  intelligence?: SourceIntelligence | null
): string {
  if (sourceKind(stream) !== "Live") return "Ready";
  if (analysisState === "paused") return "Paused";
  if (analysisState === "changing") return "Updating";
  if (analysisState === "partial") return "Needs attention";
  if (intelligence?.semanticFresh === true) return "Analyzing";
  if (intelligence?.semanticFresh === false) return "Indexing delayed";
  return "Checking ingest";
}

function incidentMatchesStream(
  incident: ConsolidatedIncident,
  stream: VisionStream
): boolean {
  const normalize = (value: string) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const sensor = normalize(incident.sensorId ?? "");
  if (!sensor) return false;
  return [stream.name, stream.sensorId, stream.streamId]
    .map(normalize)
    .some(
      (sourceId) =>
        sourceId === sensor ||
        sourceId.includes(sensor) ||
        sensor.includes(sourceId)
    );
}

function sourceOverviewCopy(
  stream: VisionStream,
  analysisState?: SourceAnalysisState,
  intelligence?: SourceIntelligence,
  incident?: ConsolidatedIncident
): string {
  if (incident) return incidentTitle(incident);
  if (analysisState === "paused")
    return "Video is connected; intelligence processing is paused.";
  if ((intelligence?.trackedObservations ?? 0) > 0)
    return `${intelligence?.trackedObservations?.toLocaleString()} tracked observations are ready to review.`;
  if ((intelligence?.semanticSegments ?? 0) > 0)
    return `${intelligence?.semanticSegments?.toLocaleString()} searchable moments are available.`;
  return sourceKind(stream) === "Live"
    ? "Live video is connected and awaiting its first indexed moment."
    : "Recorded footage is ready to inspect and search.";
}

function CameraState({
  analysisState,
  intelligence,
  stream,
}: {
  analysisState?: SourceAnalysisState;
  intelligence?: SourceIntelligence | null;
  stream: VisionStream;
}) {
  const isLive = sourceKind(stream) === "Live";
  const analysisLabel = cameraAnalysisLabel(
    stream,
    analysisState,
    intelligence
  );
  return (
    <div className="vi-source-state">
      <span
        className={
          isLive && (analysisState === "paused" || analysisState === "partial")
            ? "vi-state-dot vi-state-dot--paused"
            : isLive
            ? "vi-state-dot"
            : "vi-state-dot vi-state-dot--replay"
        }
      />
      <span>{isLive ? "Live" : "Replay"}</span>
      <span className="vi-source-state-separator">•</span>
      <span>{analysisLabel}</span>
    </div>
  );
}

function IntelligenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="vi-intelligence-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SourceIntelligencePanel({
  analysisProfile,
  analysisProfiles,
  analysisState,
  controlError,
  intelligence,
  isLoading,
  isUpdating,
  onToggleAnalysis,
  onSetAnalysisProfile,
  onInvestigate,
  stream,
  visualAnalystAvailable,
}: {
  analysisProfile: SourceAnalysisProfile | null;
  analysisProfiles: SourceAnalysisProfile[];
  analysisState: SourceAnalysisState;
  controlError: string | null;
  intelligence: SourceIntelligence | null;
  isLoading: boolean;
  isUpdating: boolean;
  onToggleAnalysis: () => void;
  onSetAnalysisProfile: (profileId: string) => void;
  onInvestigate: () => void;
  stream: VisionStream;
  visualAnalystAvailable?: boolean | null;
}) {
  const [mobileExpanded, setMobileExpanded] = useState(false);
  const [pendingProfileId, setPendingProfileId] = useState(
    analysisProfile?.id ?? ""
  );
  useEffect(() => {
    setPendingProfileId(analysisProfile?.id ?? "");
  }, [analysisProfile?.id, stream.streamId]);
  const semantic = intelligence?.semanticSegments;
  const tracking = intelligence?.trackedObservations;
  const eventCandidates = intelligence?.evidenceEvents;
  const isLive = sourceKind(stream) === "Live";
  const detectionEnabled = analysisProfile?.detectionEnabled ?? false;
  const formatCount = (
    count: number | null | undefined,
    singular: string,
    plural: string
  ) => {
    if (isLoading) return "Checking…";
    if (count === null || count === undefined) return "Unavailable";
    return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
  };

  return (
    <aside
      className={`vi-source-intelligence${
        mobileExpanded ? " is-mobile-expanded" : ""
      }`}
      aria-label="Source intelligence status"
    >
      <div className="vi-source-intelligence-heading">
        <div>
          <IconSparkles size={18} />
          <span>Local intelligence</span>
        </div>
        <em>NVIDIA Thor</em>
        <button
          className="vi-source-intelligence-mobile-toggle"
          type="button"
          aria-label={
            mobileExpanded
              ? "Collapse source intelligence"
              : "Expand source intelligence"
          }
          aria-expanded={mobileExpanded}
          onClick={() => setMobileExpanded((expanded) => !expanded)}
        >
          <IconChevronDown size={16} />
        </button>
      </div>
      <IntelligenceRow
        label="Visual search"
        value={
          semantic
            ? `${semantic.toLocaleString()} indexed moments`
            : formatCount(semantic, "moment", "moments")
        }
      />
      {isLive && (
        <>
          <IntelligenceRow
            label="Searchable through"
            value={
              intelligence?.lastSemanticAt
                ? new Date(intelligence.lastSemanticAt).toLocaleTimeString([], {
                    hour: "numeric",
                    minute: "2-digit",
                    second: "2-digit",
                  })
                : isLoading
                ? "Checking…"
                : "Waiting for first moment"
            }
          />
          <IntelligenceRow
            label="Indexing delay"
            value={
              intelligence?.indexingDelaySeconds === null ||
              intelligence?.indexingDelaySeconds === undefined
                ? isLoading
                  ? "Checking…"
                  : "Not measured"
                : intelligence.indexingDelaySeconds < 2
                ? "Live"
                : `${intelligence.indexingDelaySeconds}s behind`
            }
          />
          <IntelligenceRow
            label="Caption history"
            value={formatCount(
              intelligence?.captionSegments,
              "captioned moment",
              "captioned moments"
            )}
          />
        </>
      )}
      <IntelligenceRow
        label="Ask this camera"
        value={
          visualAnalystAvailable === null
            ? "Checking…"
            : visualAnalystAvailable === false
            ? "Unavailable"
            : "Ready"
        }
      />
      <IntelligenceRow
        label="Analysis profile"
        value={
          analysisProfile
            ? analysisProfile.shortName
            : isLoading
            ? "Checking…"
            : "Unavailable"
        }
      />
      <IntelligenceRow
        label="Detection + tracking"
        value={
          !detectionEnabled
            ? "Not enabled"
            : tracking
            ? `${tracking.toLocaleString()} observations`
            : isLoading
            ? "Checking…"
            : detectionEnabled
            ? "Ready — no observations yet"
            : "Not enabled"
        }
      />
      <IntelligenceRow
        label="Event candidates"
        value={
          eventCandidates
            ? formatCount(eventCandidates, "candidate", "candidates")
            : isLoading
            ? "Checking…"
            : "None detected"
        }
      />
      <p>
        {sourceKind(stream) === "Live"
          ? detectionEnabled
            ? `Semantic intelligence plus ${analysisProfile?.modelLabel ?? "the selected detector"} are active.`
            : "Semantic search, live history, alerts, and Cosmos reasoning stay active without an object detector."
          : tracking
          ? "Recorded analytics and semantic evidence are available."
          : semantic
          ? "This replay is searchable. It does not publish visual tracking overlays."
          : "No indexed analytics are available for this replay yet."}
      </p>
      {controlError && (
        <p className="vi-source-control-error">{controlError}</p>
      )}
      {analysisProfile && (
        <label className="vi-source-analytics-mode">
          <span>{isLive ? "Source analysis" : "Recording analysis"}</span>
          <select
            aria-label="Source analysis profile"
            disabled={isUpdating || !analysisProfile}
            onChange={(event) => {
              const profileId = event.target.value;
              if (isLive) onSetAnalysisProfile(profileId);
              else setPendingProfileId(profileId);
            }}
            value={isLive ? analysisProfile.id : pendingProfileId}
          >
            {analysisProfiles.map((profile) => (
              <option disabled={!profile.ready} key={profile.id} value={profile.id}>
                {profile.shortName}{profile.ready ? "" : " · offline"}
              </option>
            ))}
          </select>
          {analysisProfile && (
            <small>
              {isLive
                ? analysisProfile.modelLabel
                : "Changing this replaces detector-derived evidence; semantic search and the uploaded video stay intact."}
            </small>
          )}
          {!isLive && (
            <button
              className="vi-recording-reprocess"
              type="button"
              disabled={
                isUpdating ||
                !pendingProfileId ||
                pendingProfileId === analysisProfile.id
              }
              onClick={() => onSetAnalysisProfile(pendingProfileId)}
            >
              {isUpdating ? "Reprocessing…" : "Apply and reprocess recording"}
            </button>
          )}
        </label>
      )}
      {isLive && (
        <button
          className="vi-source-analysis-toggle"
          type="button"
          disabled={isUpdating || analysisState === "unknown"}
          onClick={onToggleAnalysis}
        >
          {isUpdating
            ? "Updating analysis…"
            : analysisState === "paused"
            ? "Resume analysis"
            : "Pause analysis"}
        </button>
      )}
      {Boolean((semantic ?? 0) + (eventCandidates ?? 0)) && (
        <button
          className="vi-source-explore"
          type="button"
          onClick={onInvestigate}
        >
          Explore evidence <span>→</span>
        </button>
      )}
    </aside>
  );
}

function VisionAnalystBar({
  camera,
  grid,
  isLoading,
  onAsk,
  visualAnalystAvailable,
}: {
  camera?: VisionStream;
  grid: boolean;
  isLoading: boolean;
  onAsk: (query: string) => void;
  visualAnalystAvailable?: boolean | null;
}) {
  const [query, setQuery] = useState("");
  const suggestions = grid
    ? [
        "Where is activity occurring?",
        "Summarize verified events in these recordings",
        "Which sources need attention?",
      ]
    : /traffic|road|intersection|vehicle|jaywalk/i.test(camera?.name ?? "")
    ? [
        "What traffic risks are visible?",
        "Are pedestrians crossing safely?",
        "Describe vehicle flow",
      ]
    : /warehouse|forklift|loading|dock/i.test(camera?.name ?? "")
    ? [
        "What safety risks are visible?",
        "Where are people and forklifts?",
        "Describe the current activity",
      ]
    : [
        "What objects do you see?",
        "What risks are visible?",
        "Describe the current activity",
      ];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (visualAnalystAvailable === false) return;
    const nextQuery = query.trim() || defaultQuestion;
    onAsk(nextQuery);
  };

  return (
    <div className="vi-analyst-bar">
      <div
        className="vi-analyst-mode"
        aria-label={
          grid
            ? "Vision Analyst scope: all sources"
            : "Vision Analyst scope: selected source"
        }
      >
        <IconSparkles size={20} />
        <span>Ask Vision Analyst</span>
        <small>{grid ? "All sources" : "This source"}</small>
      </div>
      <form className="vi-analyst-form" onSubmit={submit}>
        <input
          aria-label="Ask Vision Analyst"
          disabled={visualAnalystAvailable === false || isLoading}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={
            visualAnalystAvailable === false
              ? "Visual reasoning is offline — check System readiness"
              : grid
              ? "Ask across all sources…"
              : `Ask about ${
                  camera ? streamDisplayName(camera.name) : "this source"
                }…`
          }
        />
        <button
          type="submit"
          aria-label="Send question"
          disabled={isLoading || visualAnalystAvailable === false}
          title={
            visualAnalystAvailable === false
              ? "Cosmos visual reasoning is unavailable"
              : undefined
          }
        >
          {isLoading ? (
            <span className="vi-spinner" />
          ) : (
            <IconSend2 size={21} />
          )}
        </button>
      </form>
      <button
        className="vi-icon-button vi-voice-button"
        type="button"
        aria-label="Voice input unavailable"
        disabled
        title="Voice input is not enabled on this deployment"
      >
        <IconMicrophone size={21} />
      </button>
      <div className="vi-analyst-suggestions">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={isLoading || visualAnalystAvailable === false}
            onClick={() => onAsk(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

function formatObservedRange(result: VisionAnalystResponse): string | null {
  if (!result.observedRange) return null;
  const format = (seconds: number) => {
    const whole = Math.round(seconds);
    return `${Math.floor(whole / 60)}:${(whole % 60)
      .toString()
      .padStart(2, "0")}`;
  };
  return `${format(result.observedRange.startSeconds)}–${format(
    result.observedRange.endSeconds
  )}`;
}

function AnalystAnswerPanel({
  error,
  isLoading,
  onClose,
  onInvestigate,
  onPlayEvidence,
  onRetry,
  result,
}: {
  error: string | null;
  isLoading: boolean;
  onClose: () => void;
  onInvestigate: () => void;
  onPlayEvidence?: () => void;
  onRetry: () => void;
  result: VisionAnalystResponse | null;
}) {
  const interval = result ? formatObservedRange(result) : null;
  return (
    <aside
      className="vi-analyst-answer"
      aria-live="polite"
      aria-label="Vision Analyst answer"
    >
      <div className="vi-analyst-answer-heading">
        <div className="vi-analyst-answer-icon">
          <IconSparkles size={19} />
        </div>
        <div>
          <strong>Vision Analyst</strong>
          <span>
            {isLoading
              ? "Inspecting local video evidence"
              : error
              ? "Could not complete this question"
              : "Grounded in local video"}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close Vision Analyst answer"
        >
          <IconX size={18} />
        </button>
      </div>

      {isLoading && (
        <div className="vi-analyst-answer-loading">
          <span className="vi-spinner" />
          <p>
            The local VSS agent is inspecting the selected footage. This may
            take a moment.
          </p>
        </div>
      )}
      {error && !isLoading && (
        <div className="vi-analyst-answer-error">
          <IconAlertCircle size={20} />
          <p>{error}</p>
          <button type="button" onClick={onRetry}>
            <IconRefresh size={16} /> Try again
          </button>
        </div>
      )}
      {result && !isLoading && !error && (
        <>
          <p className="vi-analyst-question">“{result.query}”</p>
          <p className="vi-analyst-response">{result.answer}</p>
          <div className="vi-analyst-grounding">
            <span>
              {result.sourceNames.length === 1
                ? streamDisplayName(result.sourceNames[0])
                : `${result.sourceNames.length} sources`}
            </span>
            {interval && <span>Observed {interval}</span>}
            <span>Processed locally on Thor</span>
          </div>
          <div className="vi-analyst-evidence-actions">
            {onPlayEvidence && (
              <button
                className="vi-analyst-investigate is-primary"
                type="button"
                onClick={onPlayEvidence}
              >
                <IconPlayerPlay size={17} /> Play inspected clip
              </button>
            )}
            <button
              className="vi-analyst-investigate"
              type="button"
              onClick={onInvestigate}
            >
              Find related clips <span>→</span>
            </button>
          </div>
        </>
      )}
    </aside>
  );
}

function AnalystEvidenceClip({
  onClose,
  range,
  stream,
  vstApiUrl,
}: {
  onClose: () => void;
  range: { endSeconds: number; startSeconds: number };
  stream: VisionStream;
  vstApiUrl: string;
}) {
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useDialogAccessibility<HTMLDivElement>({ isOpen: true, onClose });

  useEffect(() => {
    const controller = new AbortController();
    const prepare = async () => {
      try {
        const timelineResponse = await fetch(
          `${vstApiUrl}/v1/storage/${encodeURIComponent(
            stream.streamId
          )}/timelines`,
          { signal: controller.signal }
        );
        if (!timelineResponse.ok)
          throw new Error("The recording timeline is unavailable.");
        const timelines = (await timelineResponse.json()) as Array<{
          endTime: string;
          startTime: string;
        }>;
        const timeline = timelines.at(-1);
        if (!timeline) throw new Error("This source has no recorded timeline.");
        const timelineStart = Date.parse(timeline.startTime);
        const timelineEnd = Date.parse(timeline.endTime);
        if (!Number.isFinite(timelineStart) || !Number.isFinite(timelineEnd)) {
          throw new Error("The recording timeline is invalid.");
        }
        const startTime = new Date(
          Math.min(timelineEnd, timelineStart + range.startSeconds * 1_000)
        ).toISOString();
        const endTime = new Date(
          Math.min(timelineEnd, timelineStart + range.endSeconds * 1_000)
        ).toISOString();
        const response = await fetch(
          evidenceClipEndpoint(stream.streamId, startTime, endTime),
          { signal: controller.signal }
        );
        if (!response.ok)
          throw new Error("The inspected clip could not be prepared.");
        const payload = (await response.json()) as { videoUrl?: string };
        if (!payload.videoUrl)
          throw new Error("The inspected clip URL was not returned.");
        const origin = new URL(vstApiUrl).origin;
        const returnedUrl = new URL(payload.videoUrl, origin);
        setVideoUrl(`${origin}${returnedUrl.pathname}${returnedUrl.search}`);
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "The inspected clip is unavailable."
          );
        }
      }
    };
    void prepare();
    return () => controller.abort();
  }, [range.endSeconds, range.startSeconds, stream.streamId, vstApiUrl]);

  return (
    <div
      ref={dialogRef}
      className="vi-evidence-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Inspected evidence clip"
    >
      <div className="vi-analyst-clip-viewer">
        <button
          className="vi-evidence-close"
          type="button"
          onClick={onClose}
          aria-label="Close inspected evidence"
        >
          <IconX size={21} />
        </button>
        <div className="vi-analyst-clip-heading">
          <span>
            <IconSparkles size={17} /> Exact inspected evidence
          </span>
          <h2>{streamDisplayName(stream.name)}</h2>
          <p>
            The Analyst answer was grounded in{" "}
            {formatObservedRange({
              observedRange: range,
            } as VisionAnalystResponse)}{" "}
            of this recording.
          </p>
        </div>
        <div className="vi-analyst-clip-media">
          {videoUrl ? (
            <video src={videoUrl} controls autoPlay playsInline />
          ) : (
            <div>
              {error ?? (
                <>
                  <span className="vi-spinner" /> Preparing the exact inspected
                  interval…
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CameraPicker({
  analysisStateById,
  intelligenceById,
  onClose,
  onSelect,
  selectedId,
  streams,
  vstApiUrl,
}: {
  analysisStateById: Record<string, SourceAnalysisState>;
  intelligenceById: Record<string, SourceIntelligence>;
  onClose: () => void;
  onSelect: (stream: VisionStream) => void;
  selectedId?: string;
  streams: VisionStream[];
  vstApiUrl?: string | null;
}) {
  return (
    <aside className="vi-camera-picker" aria-label="Camera sources">
      <div className="vi-camera-picker-heading">
        <div>
          <span>Sources</span>
          <strong>{streams.length} available</strong>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close source picker"
        >
          ×
        </button>
      </div>
      <div className="vi-camera-picker-list">
        {streams.map((stream) => {
          const displayName = streamDisplayName(stream.name);
          const isSelected = stream.streamId === selectedId;
          return (
            <div
              className={
                isSelected ? "vi-camera-option is-selected" : "vi-camera-option"
              }
              key={stream.streamId}
            >
              <div className="vi-camera-option-media">
                <VisionStreamCanvas
                  stream={stream}
                  vstApiUrl={vstApiUrl}
                  eager={false}
                  liveSnapshotEnabled={
                    analysisStateById[stream.streamId] !== "paused"
                  }
                  showStatus={false}
                />
              </div>
              <button
                aria-label={`Select ${displayName}`}
                aria-pressed={isSelected}
                className="vi-camera-option-select"
                type="button"
                onClick={() => onSelect(stream)}
              >
                <strong>{displayName}</strong>
                <CameraState
                  analysisState={analysisStateById[stream.streamId]}
                  intelligence={intelligenceById[stream.streamId]}
                  stream={stream}
                />
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function EmptyOperations({
  error,
  isLoading,
  onRefresh,
}: {
  error: string | null;
  isLoading: boolean;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="vi-empty-workspace">
      <div className="vi-empty-icon">
        <IconEye size={28} />
      </div>
      <h1>
        {isLoading ? "Loading video sources" : "No video sources available"}
      </h1>
      <p>
        {error ??
          "Add a camera or video source in Manage to begin analyzing footage."}
      </p>
      {!isLoading && (
        <button
          type="button"
          className="vi-button vi-button--primary"
          onClick={() => void onRefresh()}
        >
          <IconRefresh size={18} /> Refresh sources
        </button>
      )}
    </div>
  );
}

function FocusedOperations({
  analysisProfile,
  analysisProfiles,
  analysisState,
  camera,
  controlError,
  intelligence,
  intelligenceLoading,
  isAsking,
  isUpdatingAnalysis,
  onAsk,
  onPlaybackContext,
  onOpenHistory,
  onInvestigateSource,
  onToggleAnalysis,
  onSetAnalysisProfile,
  onShowCameras,
  evidenceEvents,
  showIntelligence,
  observedRange,
  vstApiUrl,
  visualAnalystAvailable,
}: {
  analysisProfile: SourceAnalysisProfile | null;
  analysisProfiles: SourceAnalysisProfile[];
  analysisState: SourceAnalysisState;
  camera: VisionStream;
  controlError: string | null;
  intelligence: SourceIntelligence | null;
  intelligenceLoading: boolean;
  isAsking: boolean;
  isUpdatingAnalysis: boolean;
  onAsk: (query: string) => void;
  onPlaybackContext: (context: VisionAnalystPlaybackContext) => void;
  onOpenHistory: () => void;
  onInvestigateSource: () => void;
  onToggleAnalysis: () => void;
  onSetAnalysisProfile: (profileId: string) => void;
  onShowCameras: () => void;
  evidenceEvents: Array<{
    endTime?: string;
    id: string;
    label: string;
    startTime: string;
  }>;
  showIntelligence: boolean;
  observedRange?: { endSeconds: number; startSeconds: number };
  vstApiUrl?: string | null;
  visualAnalystAvailable?: boolean | null;
}) {
  return (
    <section className="vi-focused-workspace">
      <VisionStreamCanvas
        evidenceEvents={evidenceEvents}
        liveSnapshotEnabled={analysisState !== "paused"}
        observedRange={observedRange}
        showReplayControls={sourceKind(camera) === "Replay"}
        stream={camera}
        vstApiUrl={vstApiUrl}
        onPlaybackContext={onPlaybackContext}
      />
      <div className="vi-camera-label">
        <strong>{streamDisplayName(camera.name)}</strong>
        <CameraState
          analysisState={analysisState}
          intelligence={intelligence}
          stream={camera}
        />
      </div>
      <div className="vi-focused-actions">
        <button
          type="button"
          className="vi-control"
          aria-label="Sources"
          onClick={onShowCameras}
        >
          <IconEye size={21} /> <span>Sources</span>{" "}
          <IconChevronDown size={17} />
        </button>
      </div>
      {showIntelligence && (
        <SourceIntelligencePanel
          analysisProfile={analysisProfile}
          analysisProfiles={analysisProfiles}
          analysisState={analysisState}
          controlError={controlError}
          intelligence={intelligence}
          isLoading={intelligenceLoading}
          isUpdating={isUpdatingAnalysis}
          onInvestigate={onInvestigateSource}
          onToggleAnalysis={onToggleAnalysis}
          onSetAnalysisProfile={onSetAnalysisProfile}
          stream={camera}
          visualAnalystAvailable={visualAnalystAvailable}
        />
      )}
      <div className="vi-focused-bottom">
        <VisionAnalystBar
          camera={camera}
          grid={false}
          isLoading={isAsking}
          onAsk={onAsk}
          visualAnalystAvailable={visualAnalystAvailable}
        />
        <div className="vi-bottom-links">
          <button
            type="button"
            aria-label="Video history"
            onClick={onOpenHistory}
          >
            <IconHistory size={20} /> <span>History</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function GridOperations({
  analysisStateById,
  incidents,
  intelligenceById,
  onAsk,
  onFocus,
  onOpenActivity,
  onOpenRules,
  streams,
  isAsking,
  vstApiUrl,
}: {
  analysisStateById: Record<string, SourceAnalysisState>;
  incidents: AnalyticsIncident[];
  intelligenceById: Record<string, SourceIntelligence>;
  onAsk: (query: string) => void;
  onFocus: (stream: VisionStream) => void;
  onOpenActivity: () => void;
  onOpenRules: (stream: VisionStream) => void;
  streams: VisionStream[];
  isAsking: boolean;
  vstApiUrl?: string | null;
}) {
  // A single Thor demo is designed for one to eight cameras. Keep every
  // supported source visible in the overview; the grid scrolls when a third
  // or fourth row is required instead of silently hiding cameras after four.
  const visibleStreams = streams.slice(0, 8);
  const operatorIncidents = consolidateIncidents(incidents).filter(
    (incident) =>
      isOperatorRelevantIncident(incident) &&
      incidentVerdict(incident) !== "rejected"
  );
  const searchableCount = visibleStreams.filter(
    (stream) => (intelligenceById[stream.streamId]?.semanticSegments ?? 0) > 0
  ).length;
  const analyzingCount = visibleStreams.filter(
    (stream) =>
      sourceKind(stream) !== "Live" ||
      !["paused", "partial"].includes(
        analysisStateById[stream.streamId] ?? "unknown"
      )
  ).length;
  const attentionItems = operatorIncidents.length
    ? operatorIncidents.slice(0, 5).map((incident) => ({
        description: incidentTitle(incident),
        id: incident.Id,
        label:
          visibleStreams.find((stream) =>
            incidentMatchesStream(incident, stream)
          )?.name ??
          incident.sensorId ??
          "Connected source",
        tone: "attention" as const,
      }))
    : visibleStreams.slice(0, 5).map((stream) => {
        const state = analysisStateById[stream.streamId];
        const intelligence = intelligenceById[stream.streamId];
        const label = cameraAnalysisLabel(stream, state, intelligence);
        return {
          description: sourceOverviewCopy(stream, state, intelligence),
          id: stream.streamId,
          label: streamDisplayName(stream.name),
          tone:
            state === "paused" || state === "partial"
              ? ("watch" as const)
              : ("healthy" as const),
        };
      });
  return (
    <section className="vi-grid-workspace">
      <div className="vi-grid-status">
        <span>{streams.length} Sources</span>
        <i>•</i>
        <strong>{streams.length} Available</strong>
      </div>
      <div className="vi-live-overview">
        <div className="vi-live-overview-main">
          <section
            className="vi-environment-now"
            aria-label="Current environment status"
          >
            <div className="vi-environment-now-heading">
              <strong>Environment now</strong>
              <span>Live status</span>
            </div>
            <div className="vi-environment-now-item is-healthy">
              <IconShieldCheck size={21} />
              <div>
                <strong>
                  {analyzingCount} {analyzingCount === 1 ? "source" : "sources"}{" "}
                  analyzing
                </strong>
                <span>Video feeds are connected to Thor.</span>
              </div>
            </div>
            <div className="vi-environment-now-item is-intelligence">
              <IconSparkles size={21} />
              <div>
                <strong>{searchableCount} searchable</strong>
                <span>Indexed moments are ready for Explore.</span>
              </div>
            </div>
            <div
              className={`vi-environment-now-item ${
                operatorIncidents.length ? "is-attention" : "is-healthy"
              }`}
            >
              {operatorIncidents.length ? (
                <IconAlertCircle size={21} />
              ) : (
                <IconCheck size={21} />
              )}
              <div>
                <strong>
                  {operatorIncidents.length
                    ? `${operatorIncidents.length} need review`
                    : "No verified alerts"}
                </strong>
                <span>
                  {operatorIncidents.length
                    ? "Evidence is retained in Activity."
                    : "No operator action is waiting."}
                </span>
              </div>
            </div>
          </section>

          <div className="vi-camera-grid">
            {visibleStreams.map((stream) => {
              const analysisState = analysisStateById[stream.streamId];
              const intelligence = intelligenceById[stream.streamId];
              const incident = operatorIncidents.find((candidate) =>
                incidentMatchesStream(candidate, stream)
              );
              const stateLabel = cameraAnalysisLabel(
                stream,
                analysisState,
                intelligence
              );
              const tone = incident
                ? "attention"
                : analysisState === "paused" || analysisState === "partial"
                ? "watch"
                : "healthy";
              return (
                <article className="vi-grid-camera" key={stream.streamId}>
                  <header>
                    <strong>{streamDisplayName(stream.name)}</strong>
                    <span className={`is-${tone}`}>{stateLabel}</span>
                  </header>
                  <div className="vi-grid-camera-media">
                    <VisionStreamCanvas
                      stream={stream}
                      vstApiUrl={vstApiUrl}
                      eager={false}
                      liveSnapshotEnabled={analysisState !== "paused"}
                      showStatus={false}
                    />
                    <button
                      className="vi-grid-focus"
                      type="button"
                      onClick={() => onFocus(stream)}
                      aria-label={`Focus ${streamDisplayName(stream.name)}`}
                    >
                      <IconArrowsMaximize size={18} />
                    </button>
                  </div>
                  <footer>
                    <p>
                      {sourceOverviewCopy(
                        stream,
                        analysisState,
                        intelligence,
                        incident
                      )}
                    </p>
                    <CameraState
                      analysisState={analysisState}
                      intelligence={intelligence}
                      stream={stream}
                    />
                    <button className="vi-grid-rule-link" type="button" onClick={() => onOpenRules(stream)}>
                      <IconShieldCheck size={14} /> Monitoring rules
                    </button>
                  </footer>
                </article>
              );
            })}
          </div>
        </div>

        <aside className="vi-live-attention" aria-label="Changes and attention">
          <header>
            <div>
              <span className="vi-eyebrow">Current state</span>
              <h2>Changes &amp; attention</h2>
            </div>
            <button type="button" onClick={onOpenActivity}>
              Activity <IconArrowRight size={15} />
            </button>
          </header>
          <div className="vi-live-attention-list">
            {attentionItems.map((item) => (
              <button type="button" key={item.id} onClick={onOpenActivity}>
                <span className={`is-${item.tone}`}>
                  {item.tone === "attention" ? (
                    <IconAlertCircle size={16} />
                  ) : item.tone === "watch" ? (
                    <IconClock size={16} />
                  ) : (
                    <IconCheck size={16} />
                  )}
                </span>
                <div>
                  <strong>{streamDisplayName(item.label)}</strong>
                  <p>{item.description}</p>
                  <small>
                    {item.tone === "healthy"
                      ? "No action needed"
                      : "Review source"}
                  </small>
                </div>
                <IconChevronRight size={16} />
              </button>
            ))}
          </div>
        </aside>
      </div>
      <VisionAnalystBar grid isLoading={isAsking} onAsk={onAsk} />
    </section>
  );
}

export function OperationsWorkspace({
  agentApiUrl,
  initialPanel,
  initialStreamId,
  initialView = "focused",
  onInvestigate,
  onOpenActivity,
  onOpenInsights,
  onOpenRules,
  visualAnalystAvailable,
  vstApiUrl,
}: OperationsWorkspaceProps) {
  const { error, isLoading, refresh, streams } = useVisionStreams(vstApiUrl);
  const [view, setView] = useState<OperationsView>(initialView);
  const [selectedId, setSelectedId] = useState<string | undefined>(
    initialStreamId
  );
  const [showCameras, setShowCameras] = useState(false);
  const [analystRequest, setAnalystRequest] =
    useState<VisionAnalystRequest | null>(null);
  const [analystResult, setAnalystResult] =
    useState<VisionAnalystResponse | null>(null);
  const [analystError, setAnalystError] = useState<string | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [playbackContext, setPlaybackContext] =
    useState<VisionAnalystPlaybackContext>({
      capturedAt: new Date().toISOString(),
    });
  const [conversationId, setConversationId] = useState(createPeerId);
  const [sourceIntelligenceById, setSourceIntelligenceById] = useState<
    Record<string, SourceIntelligence>
  >({});
  const [sourceAnalysisStateById, setSourceAnalysisStateById] = useState<
    Record<string, SourceAnalysisState>
  >({});
  const [analysisProfiles, setAnalysisProfiles] = useState<SourceAnalysisProfile[]>([]);
  const [sourceAnalysisProfileById, setSourceAnalysisProfileById] = useState<
    Record<string, SourceAnalysisProfile>
  >({});
  const [sourceControlErrorById, setSourceControlErrorById] = useState<
    Record<string, string>
  >({});
  const [intelligenceRefresh, setIntelligenceRefresh] = useState(0);
  const [intelligenceLoading, setIntelligenceLoading] = useState(false);
  const [showAnalystClip, setShowAnalystClip] = useState(false);
  const [showVideoHistory, setShowVideoHistory] = useState(
    initialPanel === "history"
  );
  const [analyticsIncidents, setAnalyticsIncidents] = useState<
    AnalyticsIncident[]
  >([]);
  const sourceSelectionIsManual = useRef(Boolean(initialStreamId));

  useEffect(() => {
    const controller = new AbortController();
    loadAnalysisProfileCatalog(controller.signal)
      .then(setAnalysisProfiles)
      .catch(() => setAnalysisProfiles([]));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!streams.length) return;
    const controller = new AbortController();
    Promise.all(streams.map(async (stream) => {
      try {
        return [stream.streamId, await loadSourceAnalysisProfile(stream.sensorId, controller.signal)] as const;
      } catch {
        return null;
      }
    })).then((entries) => {
      if (!controller.signal.aborted) {
        setSourceAnalysisProfileById(Object.fromEntries(entries.filter((entry): entry is readonly [string, SourceAnalysisProfile] => entry !== null)));
      }
    });
    return () => controller.abort();
  }, [intelligenceRefresh, streams]);

  const prioritizedStreams = useMemo(() => {
    return [...streams].sort((left, right) => {
      const score = (stream: VisionStream) => {
        const intelligence = sourceIntelligenceById[stream.streamId];
        return (
          (sourceKind(stream) === "Live" ? 1_000_000_000 : 0) +
          (intelligence?.evidenceEvents ?? 0) * 1_000_000 +
          (intelligence?.trackedObservations ?? 0) * 100 +
          (intelligence?.semanticSegments ?? 0)
        );
      };
      return score(right) - score(left);
    });
  }, [sourceIntelligenceById, streams]);

  useEffect(() => {
    if (!selectedId && prioritizedStreams.length) {
      setSelectedId(prioritizedStreams[0].streamId);
    }
  }, [prioritizedStreams, selectedId]);

  const selected =
    prioritizedStreams.find((stream) => stream.streamId === selectedId) ??
    prioritizedStreams[0];

  useEffect(() => {
    let disposed = false;
    fetch("/api/vision/incidents", { cache: "no-store" })
      .then(async (response) =>
        response.ok
          ? (response.json() as Promise<{ incidents?: AnalyticsIncident[] }>)
          : { incidents: [] }
      )
      .then((payload) => {
        if (!disposed) setAnalyticsIncidents(payload.incidents ?? []);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, []);

  const selectedEvidenceEvents = useMemo(() => {
    if (!selected) return [];
    const normalize = (value: string) =>
      value.toLowerCase().replace(/[^a-z0-9]/g, "");
    const sourceIds = [selected.name, selected.sensorId, selected.streamId].map(
      normalize
    );
    return consolidateIncidents(analyticsIncidents)
      .filter((incident) => {
        const sensor = normalize(incident.sensorId ?? "");
        return (
          Boolean(sensor) &&
          isOperatorRelevantIncident(incident) &&
          incidentVerdict(incident) === "confirmed" &&
          sourceIds.some(
            (sourceId) =>
              sourceId === sensor ||
              sourceId.includes(sensor) ||
              sensor.includes(sourceId)
          )
        );
      })
      .map((incident) => ({
        endTime: incident.end,
        id: incident.Id,
        label: incidentTitle(incident),
        startTime: incident.timestamp,
      }));
  }, [analyticsIncidents, selected]);

  useEffect(() => {
    if (!streams.length) return;
    let disposed = false;
    const loadIntelligence = async () => {
      setIntelligenceLoading(true);
      try {
        const [intelligenceEntries, statusEntries] = await Promise.all([
          Promise.all(
            streams.map(async (stream) => {
              const params = new URLSearchParams({
                name: stream.name,
                sensorId: stream.sensorId,
              });
              const response = await fetch(
                `/api/vision/source-intelligence?${params.toString()}`,
                { cache: "no-store" }
              );
              if (!response.ok) return null;
              return [
                stream.streamId,
                (await response.json()) as SourceIntelligence,
              ] as const;
            })
          ),
          Promise.all(
            streams
              .filter((stream) => sourceKind(stream) === "Live")
              .map(async (stream) => {
                if (!agentApiUrl)
                  return [
                    stream.streamId,
                    "unknown" as const,
                  ] as const;
                try {
                  const response = await fetch(
                    `${agentApiUrl}/rtsp-streams/${encodeURIComponent(
                      stream.sensorId
                    )}/analysis`,
                    { cache: "no-store" }
                  );
                  const payload = (await response.json()) as {
                    analysisProfileId?: string;
                    state?: SourceAnalysisState;
                  };
                  if (response.ok && payload.analysisProfileId) {
                    const profile = analysisProfiles.find((candidate) => candidate.id === payload.analysisProfileId);
                    if (profile) {
                      setSourceAnalysisProfileById((current) => ({ ...current, [stream.streamId]: profile }));
                    }
                  }
                  return [
                    stream.streamId,
                    response.ok && payload.state ? payload.state : "unknown",
                  ] as const;
                } catch {
                  return [
                    stream.streamId,
                    "unknown" as const,
                  ] as const;
                }
              })
          ),
        ]);
        if (disposed) return;
        const next = Object.fromEntries(
          intelligenceEntries.filter(
            (entry): entry is readonly [string, SourceIntelligence] =>
              Boolean(entry)
          )
        );
        setSourceIntelligenceById(next);
        setSourceAnalysisStateById(
          Object.fromEntries(statusEntries.map(([id, state]) => [id, state]))
        );
        if (!sourceSelectionIsManual.current) {
          const ranked = [...streams].sort((left, right) => {
            const score = (stream: VisionStream) =>
              (sourceKind(stream) === "Live" ? 1_000_000_000 : 0) +
              (next[stream.streamId]?.evidenceEvents ?? 0) * 1_000_000 +
              (next[stream.streamId]?.trackedObservations ?? 0) * 100 +
              (next[stream.streamId]?.semanticSegments ?? 0);
            return score(right) - score(left);
          });
          if (ranked[0]) setSelectedId(ranked[0].streamId);
        }
      } finally {
        if (!disposed) setIntelligenceLoading(false);
      }
    };
    void loadIntelligence();
    const interval = window.setInterval(loadIntelligence, 15_000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [agentApiUrl, analysisProfiles, intelligenceRefresh, streams]);

  useEffect(() => {
    setConversationId(createPeerId());
    setAnalystRequest(null);
    setAnalystResult(null);
    setAnalystError(null);
  }, [selected?.streamId, view]);

  if (!selected) {
    return (
      <EmptyOperations
        error={error}
        isLoading={isLoading}
        onRefresh={refresh}
      />
    );
  }

  const ask = async (query: string) => {
    const scopedStreams = view === "grid" ? prioritizedStreams : [selected];
    const request: VisionAnalystRequest = {
      askedAt: new Date().toISOString(),
      conversationId,
      query,
      scope: view === "grid" ? "all-sources" : "selected-source",
      sources: scopedStreams.map((stream) => ({
        kind: sourceKind(stream) === "Live" ? "live" : "replay",
        name: stream.name,
        ...(view === "focused" && stream.streamId === selected.streamId
          ? { playback: playbackContext }
          : {}),
        sensorId: stream.sensorId,
        streamId: stream.streamId,
      })),
    };
    setAnalystRequest(request);
    setAnalystResult(null);
    setAnalystError(null);
    setIsAsking(true);
    try {
      const response = await fetch("/api/vision/analyst", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Timezone": Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        body: JSON.stringify(request),
      });
      const payload = (await response.json()) as VisionAnalystResponse & {
        error?: string;
      };
      if (!response.ok)
        throw new Error(
          payload.error || `Vision Analyst returned ${response.status}.`
        );
      setAnalystResult(payload);
    } catch (requestError) {
      setAnalystError(
        requestError instanceof Error
          ? requestError.message
          : "The local Vision Analyst is unavailable."
      );
      // Do not let a failed or ungrounded agent turn contaminate the next
      // attempt through server-side conversation memory.
      setConversationId(createPeerId());
    } finally {
      setIsAsking(false);
    }
  };
  const focus = (stream: VisionStream) => {
    sourceSelectionIsManual.current = true;
    setSelectedId(stream.streamId);
    setView("focused");
  };
  const openCameraPicker = () => {
    setShowCameras(true);
  };
  const toggleSelectedAnalysis = async () => {
    if (!agentApiUrl || sourceKind(selected) !== "Live") return;
    const current = sourceAnalysisStateById[selected.streamId] ?? "unknown";
    const action = current === "paused" ? "resume" : "pause";
    setSourceControlErrorById((errors) => ({
      ...errors,
      [selected.streamId]: "",
    }));
    setSourceAnalysisStateById((states) => ({
      ...states,
      [selected.streamId]: "changing",
    }));
    try {
      const response = await fetch("/api/vision/source-analysis", {
        body: JSON.stringify({
          action,
          name: selected.name,
          sourceId: selected.sensorId,
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      const payload = (await response.json()) as {
        message?: string;
        state?: SourceAnalysisState;
      };
      if (!response.ok || payload.state === "partial" || !payload.state)
        throw new Error(
          payload.message || "Live analysis could not be updated."
        );
      setSourceAnalysisStateById((states) => ({
        ...states,
        [selected.streamId]: payload.state as SourceAnalysisState,
      }));
      setIntelligenceRefresh((value) => value + 1);
    } catch (controlError) {
      // The local control route coordinates several independent services. A
      // late dependency failure can produce a 5xx even after the requested
      // state has already been reached. Reconcile once before presenting a
      // partial failure so the UI reflects the actual Thor state.
      try {
        await new Promise((resolve) => window.setTimeout(resolve, 400));
        const statusResponse = await fetch(
          `${agentApiUrl}/rtsp-streams/${encodeURIComponent(
            selected.sensorId
          )}/analysis`,
          { cache: "no-store" }
        );
        const statusPayload = (await statusResponse.json()) as {
          state?: SourceAnalysisState;
        };
        const expectedState: SourceAnalysisState =
          action === "pause" ? "paused" : "active";
        if (statusResponse.ok && statusPayload.state === expectedState) {
          setSourceAnalysisStateById((states) => ({
            ...states,
            [selected.streamId]: expectedState,
          }));
          setSourceControlErrorById((errors) => ({
            ...errors,
            [selected.streamId]: "",
          }));
          setIntelligenceRefresh((value) => value + 1);
          return;
        }
      } catch {
        // Preserve the original control error below.
      }
      setSourceAnalysisStateById((states) => ({
        ...states,
        [selected.streamId]: "partial",
      }));
      setSourceControlErrorById((errors) => ({
        ...errors,
        [selected.streamId]:
          controlError instanceof Error
            ? controlError.message
            : "Live analysis could not be updated.",
      }));
    }
  };

  const setSelectedAnalysisProfile = async (profileId: string) => {
    if (!agentApiUrl) return;
    const isLiveSource = sourceKind(selected) === "Live";
    const requestedProfile = analysisProfiles.find((profile) => profile.id === profileId);
    if (!requestedProfile?.ready) return;
    setSourceControlErrorById((errors) => ({
      ...errors,
      [selected.streamId]: "",
    }));
    setSourceAnalysisStateById((states) => ({
      ...states,
      [selected.streamId]: "changing",
    }));
    try {
      const response = await fetch("/api/vision/source-analysis", {
        body: JSON.stringify({
          action: "configure",
          analysisProfileId: profileId,
          name: selected.name,
          sourceKind: isLiveSource ? "live" : "recorded",
          sourceId: selected.sensorId,
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      const payload = (await response.json()) as {
        analysisProfileId?: string;
        message?: string;
        state?: SourceAnalysisState;
      };
      if (
        !response.ok ||
        payload.state === "partial" ||
        payload.analysisProfileId !== profileId ||
        !payload.state
      ) {
        throw new Error(
          payload.message ||
            (isLiveSource
              ? "The scene analytics mode could not be updated."
              : "The recording could not be reprocessed.")
        );
      }
      setSourceAnalysisProfileById((profiles) => ({
        ...profiles,
        [selected.streamId]: requestedProfile,
      }));
      setSourceAnalysisStateById((states) => ({
        ...states,
        [selected.streamId]: payload.state as SourceAnalysisState,
      }));
      setIntelligenceRefresh((value) => value + 1);
    } catch (profileError) {
      setSourceAnalysisStateById((states) => ({
        ...states,
        [selected.streamId]: "partial",
      }));
      setSourceControlErrorById((errors) => ({
        ...errors,
        [selected.streamId]:
          profileError instanceof Error
            ? profileError.message
            : isLiveSource
            ? "The scene analytics mode could not be updated."
            : "The recording could not be reprocessed.",
      }));
    }
  };

  return (
    <div className="vi-operations">
      <LiveModeNav
        active="monitor"
        action={
          <button
            className="vi-live-sources-button"
            type="button"
            onClick={openCameraPicker}
          >
            <IconGridDots size={17} /> All sources
          </button>
        }
        onSelect={(mode) => {
          if (mode === "activity") onOpenActivity();
          else if (mode === "insights") onOpenInsights();
          else if (mode === "rules") onOpenRules();
          else {
            setView("grid");
            setShowCameras(false);
          }
        }}
      />
      <div className="vi-operations-content">
        {view === "grid" ? (
          <GridOperations
            analysisStateById={sourceAnalysisStateById}
            incidents={analyticsIncidents}
            intelligenceById={sourceIntelligenceById}
            isAsking={isAsking}
            onAsk={ask}
            onFocus={focus}
            onOpenActivity={onOpenActivity}
            onOpenRules={onOpenRules}
            streams={prioritizedStreams}
            vstApiUrl={vstApiUrl}
          />
        ) : (
          <FocusedOperations
            analysisState={
              sourceAnalysisStateById[selected.streamId] ?? "unknown"
            }
            camera={selected}
            controlError={sourceControlErrorById[selected.streamId] || null}
            analysisProfile={sourceAnalysisProfileById[selected.streamId] ?? null}
            analysisProfiles={analysisProfiles}
            evidenceEvents={selectedEvidenceEvents}
            intelligence={sourceIntelligenceById[selected.streamId] ?? null}
            intelligenceLoading={intelligenceLoading}
            isAsking={isAsking}
            isUpdatingAnalysis={
              sourceAnalysisStateById[selected.streamId] === "changing"
            }
            onAsk={ask}
            onPlaybackContext={setPlaybackContext}
            onOpenHistory={() => setShowVideoHistory(true)}
            onInvestigateSource={() =>
              onInvestigate(
                "Show the most relevant activity in this source.",
                selected
              )
            }
            onToggleAnalysis={() => void toggleSelectedAnalysis()}
            onSetAnalysisProfile={(profileId) =>
              void setSelectedAnalysisProfile(profileId)
            }
            onShowCameras={openCameraPicker}
            observedRange={
              analystResult?.scope === "selected-source"
                ? analystResult.observedRange
                : undefined
            }
            showIntelligence={!showCameras}
            visualAnalystAvailable={visualAnalystAvailable}
            vstApiUrl={vstApiUrl}
          />
        )}

        {showCameras && (
          <CameraPicker
            analysisStateById={sourceAnalysisStateById}
            intelligenceById={sourceIntelligenceById}
            onClose={() => setShowCameras(false)}
            onSelect={(stream) => {
              focus(stream);
              setShowCameras(false);
            }}
            selectedId={selected.streamId}
            streams={prioritizedStreams}
            vstApiUrl={vstApiUrl}
          />
        )}

        {analystRequest && (
          <AnalystAnswerPanel
            error={analystError}
            isLoading={isAsking}
            onClose={() => {
              setAnalystRequest(null);
              setAnalystResult(null);
              setAnalystError(null);
            }}
            onInvestigate={() =>
              onInvestigate(
                analystRequest.query,
                analystRequest.scope === "selected-source"
                  ? selected
                  : undefined
              )
            }
            onPlayEvidence={
              analystResult?.scope === "selected-source" &&
              Boolean(analystResult.observedRange) &&
              sourceKind(selected) === "Replay" &&
              Boolean(vstApiUrl)
                ? () => setShowAnalystClip(true)
                : undefined
            }
            onRetry={() => void ask(analystRequest.query)}
            result={analystResult}
          />
        )}
        {showAnalystClip && analystResult?.observedRange && vstApiUrl && (
          <AnalystEvidenceClip
            onClose={() => setShowAnalystClip(false)}
            range={analystResult.observedRange}
            stream={selected}
            vstApiUrl={vstApiUrl}
          />
        )}
        {showVideoHistory && (
          <VideoHistoryPanel
            onClose={() => setShowVideoHistory(false)}
            onInvestigate={(query) => {
              setShowVideoHistory(false);
              onInvestigate(query, selected);
            }}
            stream={selected}
          />
        )}
      </div>
    </div>
  );
}
