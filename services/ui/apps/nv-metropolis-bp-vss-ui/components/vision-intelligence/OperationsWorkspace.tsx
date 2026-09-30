// SPDX-License-Identifier: MIT

import { CameraSourceCatalog } from "./CameraSourceCatalog";
import { LiveAnswerReport } from "./LiveAnswerReport";
import { LiveCameraView } from "./LiveCameraView";
import { VideoHistoryPanel } from "./VideoHistoryPanel";
import { VisionStreamCanvas } from "./VisionStreamCanvas";
import {
  loadAnalysisProfileCatalog,
  loadSourceAnalysisProfile,
  type SourceAnalysisProfile,
} from "./analysisProfiles";
import type {
  VisionAnalystPlaybackContext,
  VisionAnalystRequest,
  VisionAnalystResponse,
} from "./analyst";
import { evidenceClipEndpoint } from "./evidenceClip";
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
import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import {
  IconAlertCircle,
  IconEye,
  IconPlayerPlay,
  IconRefresh,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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

export interface SourceIntelligence {
  captionSegments: number | null;
  evidenceEvents: number | null;
  indexingDelaySeconds: number | null;
  lastCaptionAt?: string | null;
  lastSemanticAt?: string | null;
  semanticFresh?: boolean | null;
  semanticSegments: number | null;
  trackedObservations: number | null;
}

export type SourceAnalysisState =
  | "active"
  | "changing"
  | "partial"
  | "paused"
  | "unknown";

function incidentMatchesStream(
  incident: ConsolidatedIncident,
  stream: VisionStream
): boolean {
  const sensor = incident.sensorId?.trim();
  return (
    Boolean(sensor) &&
    [stream.sensorId, stream.streamId].some(
      (sourceId) => sourceId.trim() === sensor
    )
  );
}

function formatObservedRange(result: VisionAnalystResponse): string | null {
  if (result.observedWindow) {
    const formatTime = (value: string) =>
      new Date(value).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
      });
    return `${formatTime(result.observedWindow.startTime)} – ${formatTime(
      result.observedWindow.endTime
    )}`;
  }
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
  reportSource,
  onRetry,
  result,
}: {
  error: string | null;
  isLoading: boolean;
  onClose: () => void;
  onInvestigate: () => void;
  onPlayEvidence?: () => void;
  reportSource?: VisionAnalystRequest["sources"][number];
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
            <span>Processed locally on this device</span>
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
          {result.observedWindow && reportSource && (
            <LiveAnswerReport
              key={result.generatedAt}
              result={result}
              source={reportSource}
            />
          )}
        </>
      )}
    </aside>
  );
}

function AnalystEvidenceClip({
  onClose,
  range,
  window: observedWindow,
  stream,
  vstApiUrl,
}: {
  onClose: () => void;
  range?: { endSeconds: number; startSeconds: number };
  window?: { startTime: string; endTime: string };
  stream: VisionStream;
  vstApiUrl: string;
}) {
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useDialogAccessibility<HTMLDivElement>({
    isOpen: true,
    onClose,
  });

  const rangeStart = range?.startSeconds;
  const rangeEnd = range?.endSeconds;
  useEffect(() => {
    const controller = new AbortController();
    const prepare = async () => {
      try {
        let startTime = observedWindow?.startTime;
        let endTime = observedWindow?.endTime;
        if (!startTime || !endTime) {
          if (rangeStart === undefined || rangeEnd === undefined)
            throw new Error("The inspected interval is unavailable.");
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
          if (!timeline)
            throw new Error("This source has no recorded timeline.");
          const timelineStart = Date.parse(timeline.startTime);
          const timelineEnd = Date.parse(timeline.endTime);
          if (
            !Number.isFinite(timelineStart) ||
            !Number.isFinite(timelineEnd)
          ) {
            throw new Error("The recording timeline is invalid.");
          }
          startTime = new Date(
            Math.min(timelineEnd, timelineStart + rangeStart * 1_000)
          ).toISOString();
          endTime = new Date(
            Math.min(timelineEnd, timelineStart + rangeEnd * 1_000)
          ).toISOString();
        }
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
  }, [
    rangeEnd,
    rangeStart,
    observedWindow?.startTime,
    observedWindow?.endTime,
    stream.streamId,
    vstApiUrl,
  ]);

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
              observedWindow,
            } as VisionAnalystResponse)}{" "}
            {observedWindow
              ? "from this RTSP feed. This is a recent recorded interval, not the current frame."
              : "of this recording."}
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

export function OperationsWorkspace({
  agentApiUrl,
  initialPanel,
  initialStreamId,
  initialView = "focused",
  onInvestigate,
  onOpenRules,
  visualAnalystAvailable,
  vstApiUrl,
}: OperationsWorkspaceProps) {
  const { error, isLoading, refresh, streams } = useVisionStreams(vstApiUrl);
  const [view, setView] = useState<OperationsView>(initialView);
  const [selectedId, setSelectedId] = useState<string | undefined>(
    initialStreamId
  );
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
  const [analysisProfiles, setAnalysisProfiles] = useState<
    SourceAnalysisProfile[]
  >([]);
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
  const questionGeneration = useRef(0);
  const questionController = useRef<AbortController | null>(null);
  const questionScope = useRef("");
  const playbackSource = useRef("");
  const historySource = useRef("");
  const pollGeneration = useRef(0);
  const controlVersions = useRef<Record<string, number>>({});
  const controlMutations = useRef(new Set<string>());
  const workspaceMounted = useRef(true);

  const invalidateAsyncWork = useCallback(() => {
    workspaceMounted.current = false;
    ++questionGeneration.current;
    ++pollGeneration.current;
    questionController.current?.abort();
  }, []);
  useEffect(() => {
    workspaceMounted.current = true;
    return invalidateAsyncWork;
  }, [invalidateAsyncWork]);

  useEffect(() => {
    const controller = new AbortController();
    loadAnalysisProfileCatalog(controller.signal)
      .then((profiles) => {
        if (!controller.signal.aborted) setAnalysisProfiles(profiles);
      })
      .catch(() => {
        if (!controller.signal.aborted) setAnalysisProfiles([]);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!streams.length) return;
    const controller = new AbortController();
    Promise.all(
      streams.map(async (stream) => {
        const version = controlVersions.current[stream.streamId] ?? 0;
        if (controlMutations.current.has(stream.streamId)) return null;
        try {
          const profile = await loadSourceAnalysisProfile(
            stream.sensorId,
            controller.signal
          );
          if (
            controller.signal.aborted ||
            controlMutations.current.has(stream.streamId) ||
            (controlVersions.current[stream.streamId] ?? 0) !== version
          )
            return null;
          return [stream.streamId, profile] as const;
        } catch {
          return null;
        }
      })
    ).then((entries) => {
      if (!controller.signal.aborted) {
        setSourceAnalysisProfileById((current) => ({
          ...current,
          ...Object.fromEntries(
            entries.filter(
              (entry): entry is readonly [string, SourceAnalysisProfile] =>
                entry !== null
            )
          ),
        }));
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
  const selectedSourceKey = selected
    ? `${selected.sensorId}\0${selected.streamId}`
    : "";
  questionScope.current = `${selectedSourceKey}\0${view}`;

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
    return consolidateIncidents(analyticsIncidents)
      .filter(
        (incident) =>
          incidentMatchesStream(incident, selected) &&
          isOperatorRelevantIncident(incident) &&
          incidentVerdict(incident) === "confirmed"
      )
      .map((incident) => ({
        endTime: incident.end,
        id: incident.Id,
        label: incidentTitle(incident),
        startTime: incident.timestamp,
      }));
  }, [analyticsIncidents, selected]);

  useEffect(() => {
    if (!streams.length) return;
    const controller = new AbortController();
    const loadIntelligence = async () => {
      const generation = ++pollGeneration.current;
      const current = () =>
        !controller.signal.aborted &&
        workspaceMounted.current &&
        generation === pollGeneration.current;
      setIntelligenceLoading(true);
      try {
        const [intelligenceEntries, statusEntries] = await Promise.all([
          Promise.all(
            streams.map(async (stream) => {
              const params = new URLSearchParams({
                name: stream.name,
                sensorId: stream.sensorId,
              });
              try {
                const response = await fetch(
                  `/api/vision/source-intelligence?${params.toString()}`,
                  { cache: "no-store", signal: controller.signal }
                );
                if (!response.ok) return null;
                return [
                  stream.streamId,
                  (await response.json()) as SourceIntelligence,
                ] as const;
              } catch {
                return null;
              }
            })
          ),
          Promise.all(
            streams
              .filter((stream) => sourceKind(stream) === "Live")
              .map(async (stream) => {
                if (controlMutations.current.has(stream.streamId)) return null;
                if (!agentApiUrl)
                  return [
                    stream.streamId,
                    "unknown" as SourceAnalysisState,
                    undefined,
                  ] as const;
                try {
                  const response = await fetch(
                    `${agentApiUrl}/rtsp-streams/${encodeURIComponent(
                      stream.sensorId
                    )}/analysis`,
                    { cache: "no-store", signal: controller.signal }
                  );
                  const payload = (await response.json()) as {
                    analysisProfileId?: string;
                    state?: SourceAnalysisState;
                  };
                  const state =
                    response.ok &&
                    ["active", "paused", "partial", "unknown"].includes(
                      payload.state ?? ""
                    )
                      ? (payload.state as SourceAnalysisState)
                      : "unknown";
                  return [
                    stream.streamId,
                    state,
                    response.ok ? payload.analysisProfileId : undefined,
                  ] as const;
                } catch {
                  return [
                    stream.streamId,
                    "unknown" as SourceAnalysisState,
                    undefined,
                  ] as const;
                }
              })
          ),
        ]);
        if (!current()) return;
        const next = Object.fromEntries(
          intelligenceEntries.filter(
            (entry): entry is readonly [string, SourceIntelligence] =>
              Boolean(entry)
          )
        );
        setSourceIntelligenceById(next);
        const states: Record<string, SourceAnalysisState> = {};
        const profiles: Record<string, SourceAnalysisProfile> = {};
        for (const entry of statusEntries) {
          if (!entry || controlMutations.current.has(entry[0])) continue;
          states[entry[0]] = entry[1];
          const profile = analysisProfiles.find(
            (candidate) => candidate.id === entry[2]
          );
          if (profile) profiles[entry[0]] = profile;
        }
        setSourceAnalysisStateById((previous) => ({ ...previous, ...states }));
        setSourceAnalysisProfileById((previous) => ({
          ...previous,
          ...profiles,
        }));
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
        if (current()) setIntelligenceLoading(false);
      }
    };
    void loadIntelligence();
    const interval = window.setInterval(() => void loadIntelligence(), 15_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [agentApiUrl, analysisProfiles, intelligenceRefresh, streams]);

  useEffect(() => {
    ++questionGeneration.current;
    questionController.current?.abort();
    questionController.current = null;
    setConversationId(createPeerId());
    setAnalystRequest(null);
    setAnalystResult(null);
    setAnalystError(null);
    setIsAsking(false);
    setShowAnalystClip(false);
    setPlaybackContext({ capturedAt: new Date().toISOString() });
    playbackSource.current = selectedSourceKey;
    if (historySource.current && historySource.current !== selectedSourceKey)
      setShowVideoHistory(false);
    historySource.current = selectedSourceKey;
  }, [selectedSourceKey, view]);

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
    questionController.current?.abort();
    const controller = new AbortController();
    questionController.current = controller;
    const generation = ++questionGeneration.current;
    const scope = questionScope.current;
    const current = () =>
      workspaceMounted.current &&
      !controller.signal.aborted &&
      questionGeneration.current === generation &&
      questionScope.current === scope;
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
          ? {
              playback:
                playbackSource.current === selectedSourceKey
                  ? playbackContext
                  : { capturedAt: new Date().toISOString() },
            }
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
        signal: controller.signal,
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
      if (current()) setAnalystResult(payload);
    } catch (requestError) {
      if (current()) {
        setAnalystError(
          requestError instanceof Error
            ? requestError.message
            : "The local Vision Analyst is unavailable."
        );
        setConversationId(createPeerId());
      }
    } finally {
      if (current()) setIsAsking(false);
    }
  };

  const focus = (stream: VisionStream) => {
    sourceSelectionIsManual.current = true;
    setSelectedId(stream.streamId);
    setView("focused");
  };
  const openCameraPicker = () => {
    setView("grid");
  };
  const changeSelectedAnalysis = async (
    action: "pause" | "resume" | "configure",
    requestedProfile?: SourceAnalysisProfile
  ) => {
    if (!agentApiUrl || controlMutations.current.has(selected.streamId)) return;
    const source = selected;
    const isLiveSource = sourceKind(source) === "Live";
    if (action !== "configure" && !isLiveSource) return;
    const id = source.streamId;
    const version = (controlVersions.current[id] ?? 0) + 1;
    controlVersions.current[id] = version;
    controlMutations.current.add(id);
    ++pollGeneration.current;
    const current = () =>
      workspaceMounted.current && controlVersions.current[id] === version;
    const validState = (value?: SourceAnalysisState) =>
      value && ["active", "paused", "partial"].includes(value) ? value : null;
    const expected = (state: SourceAnalysisState | null, profileId?: string) =>
      action === "configure"
        ? Boolean(
            state && state !== "partial" && profileId === requestedProfile?.id
          )
        : state === (action === "pause" ? "paused" : "active");
    const apply = (state: SourceAnalysisState, profileId?: string) => {
      if (!current()) return;
      setSourceAnalysisStateById((states) => ({ ...states, [id]: state }));
      const profile = analysisProfiles.find(
        (candidate) => candidate.id === profileId
      );
      if (profile)
        setSourceAnalysisProfileById((profiles) => ({
          ...profiles,
          [id]: profile,
        }));
    };
    setSourceControlErrorById((errors) => ({ ...errors, [id]: "" }));
    setSourceAnalysisStateById((states) => ({ ...states, [id]: "changing" }));
    let verifiedState: SourceAnalysisState | null = null;
    try {
      const response = await fetch("/api/vision/source-analysis", {
        body: JSON.stringify({
          action,
          name: source.name,
          sourceId: source.sensorId,
          ...(action === "configure"
            ? {
                analysisProfileId: requestedProfile?.id,
                sourceKind: isLiveSource ? "live" : "recorded",
              }
            : {}),
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      const payload = (await response.json()) as {
        analysisProfileId?: string;
        error?: string;
        message?: string;
        state?: SourceAnalysisState;
      };
      verifiedState = validState(payload.state);
      if (verifiedState) apply(verifiedState, payload.analysisProfileId);
      if (!response.ok || !expected(verifiedState, payload.analysisProfileId))
        throw new Error(
          payload.error ||
            payload.message ||
            (action === "configure"
              ? isLiveSource
                ? "The scene analytics mode could not be updated."
                : "The recording could not be reprocessed."
              : "Live analysis could not be updated.")
        );
      if (requestedProfile && current())
        setSourceAnalysisProfileById((profiles) => ({
          ...profiles,
          [id]: requestedProfile,
        }));
      if (current()) setIntelligenceRefresh((value) => value + 1);
    } catch (failure) {
      // A failed multi-service update can still have reached the requested state.
      // Prefer a verified returned state; reconcile once only when none was supplied.
      if (!verifiedState && current()) {
        try {
          await new Promise((resolve) => window.setTimeout(resolve, 400));
          if (!current()) return;
          const response = await fetch(
            `${agentApiUrl}/rtsp-streams/${encodeURIComponent(
              source.sensorId
            )}/analysis`,
            { cache: "no-store" }
          );
          const payload = (await response.json()) as {
            state?: SourceAnalysisState;
            analysisProfileId?: string;
          };
          const state = response.ok ? validState(payload.state) : null;
          if (state) {
            verifiedState = state;
            apply(state, payload.analysisProfileId);
          }
          if (expected(state, payload.analysisProfileId) && current()) {
            setSourceControlErrorById((errors) => ({ ...errors, [id]: "" }));
            setIntelligenceRefresh((value) => value + 1);
            return;
          }
        } catch {
          /* Preserve the original backend error. */
        }
      }
      if (current()) {
        if (!verifiedState) apply("partial");
        setSourceControlErrorById((errors) => ({
          ...errors,
          [id]:
            failure instanceof Error
              ? failure.message
              : "Source analysis could not be updated.",
        }));
      }
    } finally {
      if (controlVersions.current[id] === version) {
        controlMutations.current.delete(id);
        ++pollGeneration.current;
        if (workspaceMounted.current) setIntelligenceLoading(false);
      }
    }
  };

  const toggleSelectedAnalysis = async () => {
    const state = sourceAnalysisStateById[selected.streamId] ?? "unknown";
    if (state === "unknown" || state === "changing") return;
    await changeSelectedAnalysis(state === "paused" ? "resume" : "pause");
  };

  const setSelectedAnalysisProfile = async (profileId: string) => {
    const profile = analysisProfiles.find(
      (candidate) => candidate.id === profileId
    );
    if (profile?.ready) await changeSelectedAnalysis("configure", profile);
  };

  const answer = analystRequest ? (
    <AnalystAnswerPanel
      error={analystError}
      isLoading={isAsking}
      onClose={() => {
        ++questionGeneration.current;
        questionController.current?.abort();
        questionController.current = null;
        setIsAsking(false);
        setShowAnalystClip(false);
        setConversationId(createPeerId());
        setAnalystRequest(null);
        setAnalystResult(null);
        setAnalystError(null);
      }}
      onInvestigate={() =>
        onInvestigate(
          analystRequest.query,
          analystRequest.scope === "selected-source" ? selected : undefined
        )
      }
      onPlayEvidence={
        analystResult?.scope === "selected-source" &&
        Boolean(
          analystResult.observedWindow ||
            (analystResult.observedRange && sourceKind(selected) === "Replay")
        ) &&
        Boolean(vstApiUrl)
          ? () => setShowAnalystClip(true)
          : undefined
      }
      reportSource={
        analystRequest.scope === "selected-source" &&
        analystRequest.sources.length === 1
          ? analystRequest.sources[0]
          : undefined
      }
      onRetry={() => void ask(analystRequest.query)}
      result={analystResult}
    />
  ) : undefined;

  return (
    <div className="vi-camera-workspace" data-view={view}>
      <div className="vi-camera-workspace-content">
        {view === "grid" ? (
          <CameraSourceCatalog
            analysisStateById={sourceAnalysisStateById}
            intelligenceById={sourceIntelligenceById}
            onFocus={focus}
            onBack={() => setView("focused")}
            onOpenRules={onOpenRules}
            streams={prioritizedStreams}
            vstApiUrl={vstApiUrl}
          />
        ) : (
          <LiveCameraView
            key={selectedSourceKey}
            analysisState={
              sourceAnalysisStateById[selected.streamId] ?? "unknown"
            }
            camera={selected}
            controlError={sourceControlErrorById[selected.streamId] || null}
            analysisProfile={
              sourceAnalysisProfileById[selected.streamId] ?? null
            }
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
            visualAnalystAvailable={visualAnalystAvailable}
            vstApiUrl={vstApiUrl}
            answer={answer}
          />
        )}
        {showAnalystClip &&
          (analystResult?.observedRange || analystResult?.observedWindow) &&
          vstApiUrl && (
            <AnalystEvidenceClip
              onClose={() => setShowAnalystClip(false)}
              range={analystResult.observedRange}
              window={analystResult.observedWindow}
              stream={selected}
              vstApiUrl={vstApiUrl}
            />
          )}
        {showVideoHistory && (
          <VideoHistoryPanel
            key={`history:${selectedSourceKey}`}
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
