// SPDX-License-Identifier: MIT

import { VisionStreamCanvas } from "./VisionStreamCanvas";
import type { VisionAnalystRequest, VisionAnalystResponse } from "./analyst";
import {
  consolidateIncidents,
  incidentTitle,
  incidentVerdict,
  isOperatorRelevantIncident,
  type ConsolidatedIncident,
} from "./incidentModel";
import type { SystemHealth } from "./systemHealth";
import type { VisionStream } from "./types";
import { useVisionStreams } from "./useVisionStreams";
import { createPeerId, sourceKind, streamDisplayName } from "./utils";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconBolt,
  IconCheck,
  IconClock,
  IconPlayerPlay,
  IconRefresh,
  IconSearch,
  IconShieldCheck,
  IconSparkles,
} from "@tabler/icons-react";
import React, { FormEvent, useEffect, useMemo, useState } from "react";

interface SourceIntelligence {
  captionSegments: number | null;
  evidenceEvents: number | null;
  indexingDelaySeconds: number | null;
  lastSemanticAt?: string | null;
  semanticFresh?: boolean | null;
  semanticSegments: number | null;
  trackedObservations: number | null;
}

type AnalysisState = "active" | "changing" | "partial" | "paused" | "unknown";

interface HomeWorkspaceProps {
  agentApiUrl?: string | null;
  onExplore: (query: string, stream?: VisionStream) => void;
  onOpenEvents: () => void;
  onOpenLive: (stream?: VisionStream) => void;
  systemHealth: SystemHealth | null;
  visualAnalystAvailable?: boolean | null;
  vstApiUrl?: string | null;
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function incidentForStream(
  incidents: ConsolidatedIncident[],
  stream: VisionStream
): ConsolidatedIncident | undefined {
  const identities = [stream.name, stream.sensorId, stream.streamId].map(
    normalize
  );
  return incidents.find((incident) => {
    const source = normalize(incident.sensorId ?? "");
    return (
      Boolean(source) &&
      identities.some(
        (identity) =>
          identity === source ||
          identity.includes(source) ||
          source.includes(identity)
      )
    );
  });
}

function relativeTime(value: string | null | undefined): string {
  if (!value) return "Awaiting first indexed moment";
  const elapsed = Date.now() - Date.parse(value);
  if (!Number.isFinite(elapsed)) return "Recently indexed";
  const seconds = Math.max(0, Math.round(elapsed / 1_000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

export function sourceTimelineContext(
  stream: VisionStream,
  lastSemanticAt: string | null | undefined
): string {
  // Archived media keeps its original capture timestamps. Presenting those as
  // live recency (for example, “14327h ago”) is misleading and visually noisy.
  return sourceKind(stream) === "Replay"
    ? "Indexed locally"
    : relativeTime(lastSemanticAt);
}

function sourceStatus(
  stream: VisionStream,
  intelligence: SourceIntelligence | undefined,
  analysisState: AnalysisState | undefined
): { label: string; tone: "attention" | "healthy" | "watch" } {
  if (sourceKind(stream) === "Replay") {
    return {
      label: intelligence?.semanticSegments ? "Searchable" : "Ready",
      tone: "healthy",
    };
  }
  if (analysisState === "paused") return { label: "Paused", tone: "watch" };
  if (analysisState === "partial")
    return { label: "Needs attention", tone: "attention" };
  if (analysisState === "changing") return { label: "Updating", tone: "watch" };
  if (intelligence?.semanticFresh === false)
    return { label: "Indexing delayed", tone: "watch" };
  return { label: "Analyzing", tone: "healthy" };
}

function sourceSummary(
  stream: VisionStream,
  intelligence: SourceIntelligence | undefined,
  analysisState: AnalysisState | undefined,
  incident: ConsolidatedIncident | undefined
): string {
  if (incident) return incidentTitle(incident);
  if (analysisState === "paused")
    return "Video is available; intelligence processing is paused.";
  if ((intelligence?.trackedObservations ?? 0) > 0)
    return `${intelligence?.trackedObservations?.toLocaleString()} tracked observations are available for review.`;
  if ((intelligence?.semanticSegments ?? 0) > 0)
    return `${intelligence?.semanticSegments?.toLocaleString()} indexed moments are ready to search.`;
  return sourceKind(stream) === "Live"
    ? "Live video is connected and waiting for its first indexed moment."
    : "Recorded footage is connected and ready to inspect.";
}

export function HomeWorkspace({
  agentApiUrl,
  onExplore,
  onOpenEvents,
  onOpenLive,
  systemHealth,
  visualAnalystAvailable,
  vstApiUrl,
}: HomeWorkspaceProps) {
  const {
    error: sourceError,
    isLoading,
    refresh,
    streams,
  } = useVisionStreams(vstApiUrl);
  const [intelligenceById, setIntelligenceById] = useState<
    Record<string, SourceIntelligence>
  >({});
  const [analysisById, setAnalysisById] = useState<
    Record<string, AnalysisState>
  >({});
  const [incidents, setIncidents] = useState<ConsolidatedIncident[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<VisionAnalystResponse | null>(null);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!streams.length) return;
    let disposed = false;
    const load = async () => {
      const [incidentResult, intelligenceEntries, analysisEntries] =
        await Promise.all([
          fetch("/api/vision/incidents", { cache: "no-store" })
            .then(async (response) =>
              response.ok
                ? ((await response.json()) as { incidents?: any[] })
                    .incidents ?? []
                : []
            )
            .catch(() => []),
          Promise.all(
            streams.map(async (stream) => {
              const params = new URLSearchParams({
                name: stream.name,
                sensorId: stream.sensorId,
              });
              try {
                const response = await fetch(
                  `/api/vision/source-intelligence?${params.toString()}`,
                  { cache: "no-store" }
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
                if (!agentApiUrl)
                  return [stream.streamId, "unknown" as AnalysisState] as const;
                try {
                  const response = await fetch(
                    `${agentApiUrl}/rtsp-streams/${encodeURIComponent(
                      stream.sensorId
                    )}/analysis`,
                    { cache: "no-store" }
                  );
                  const payload = (await response.json()) as {
                    state?: AnalysisState;
                  };
                  return [
                    stream.streamId,
                    response.ok && payload.state ? payload.state : "unknown",
                  ] as const;
                } catch {
                  return [stream.streamId, "unknown" as AnalysisState] as const;
                }
              })
          ),
        ]);
      if (disposed) return;
      setIncidents(
        consolidateIncidents(incidentResult).filter(isOperatorRelevantIncident)
      );
      setIntelligenceById(
        Object.fromEntries(
          intelligenceEntries.filter(
            (entry): entry is readonly [string, SourceIntelligence] =>
              Boolean(entry)
          )
        )
      );
      setAnalysisById(Object.fromEntries(analysisEntries));
    };
    void load();
    const interval = window.setInterval(load, 20_000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [agentApiUrl, streams]);

  const rankedStreams = useMemo(
    () =>
      [...streams].sort((left, right) => {
        const score = (stream: VisionStream) => {
          const incident = incidentForStream(incidents, stream);
          const intelligence = intelligenceById[stream.streamId];
          return (
            (incident && incidentVerdict(incident) !== "rejected"
              ? 10_000_000
              : 0) +
            (sourceKind(stream) === "Live" ? 1_000_000 : 0) +
            (intelligence?.evidenceEvents ?? 0) * 1_000 +
            (intelligence?.semanticSegments ?? 0)
          );
        };
        return score(right) - score(left);
      }),
    [incidents, intelligenceById, streams]
  );
  const featured = rankedStreams[0];
  const liveCount = streams.filter(
    (stream) => sourceKind(stream) === "Live"
  ).length;
  const pausedCount = Object.values(analysisById).filter(
    (state) => state === "paused"
  ).length;
  // Indexed history remains searchable even when a live source is paused or
  // its newest segment is delayed. Keep this definition aligned with Live and
  // Explore rather than treating freshness as data availability.
  const searchableCount = Object.values(intelligenceById).filter(
    (value) => (value.semanticSegments ?? 0) > 0
  ).length;
  const attentionIncidents = incidents.filter(
    (incident) => incidentVerdict(incident) !== "rejected"
  );
  const latestIncident = attentionIncidents[0];

  const submitQuestion = async (event: FormEvent) => {
    event.preventDefault();
    const query = question.trim();
    if (!query || !streams.length || visualAnalystAvailable === false) return;
    setAsking(true);
    setAnswer(null);
    setAnswerError(null);
    const request: VisionAnalystRequest = {
      askedAt: new Date().toISOString(),
      conversationId: createPeerId(),
      query,
      scope: "all-sources",
      sources: rankedStreams.map((stream) => ({
        kind: sourceKind(stream) === "Live" ? "live" : "replay",
        name: stream.name,
        sensorId: stream.sensorId,
        streamId: stream.streamId,
      })),
    };
    try {
      const response = await fetch("/api/vision/analyst", {
        body: JSON.stringify(request),
        headers: {
          "Content-Type": "application/json",
          "X-Timezone": Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        method: "POST",
      });
      const payload = (await response.json()) as VisionAnalystResponse & {
        error?: string;
      };
      if (!response.ok)
        throw new Error(
          payload.error || `Vision Analyst returned ${response.status}.`
        );
      setAnswer(payload);
    } catch (requestError) {
      setAnswerError(
        requestError instanceof Error
          ? requestError.message
          : "The local Vision Analyst is unavailable."
      );
    } finally {
      setAsking(false);
    }
  };

  if (isLoading && !streams.length) {
    return (
      <section className="vi-home vi-home--loading">
        <span className="vi-spinner" /> Building the current environment brief…
      </section>
    );
  }

  if (!streams.length) {
    return (
      <section className="vi-home vi-home--empty">
        <IconSearch size={28} />
        <h1>No sources are connected yet</h1>
        <p>
          {sourceError ?? "Connect a camera or recording in System to begin."}
        </p>
        <button type="button" onClick={() => void refresh()}>
          <IconRefresh size={17} /> Refresh sources
        </button>
      </section>
    );
  }

  return (
    <section className="vi-home">
      <div className="vi-home-layout">
        <div className="vi-home-primary">
          <article className="vi-environment-brief">
            {featured && (
              <div className="vi-brief-media">
                <VisionStreamCanvas
                  eager={false}
                  showStatus={false}
                  stream={featured}
                  vstApiUrl={vstApiUrl}
                />
                <button
                  className="vi-brief-media-open"
                  type="button"
                  onClick={() => onOpenLive(featured)}
                  aria-label={`Open ${streamDisplayName(featured.name)}`}
                >
                  <IconPlayerPlay size={16} />{" "}
                  {streamDisplayName(featured.name)}
                </button>
              </div>
            )}
            <div className="vi-environment-copy">
              <h1>Environment brief</h1>
              <p className="vi-environment-summary">
                {latestIncident
                  ? `${incidentTitle(
                      latestIncident
                    )} was observed ${relativeTime(
                      latestIncident.timestamp
                    )}. The supporting clip and model verdict remain attached.`
                  : `The environment is operating normally. ${liveCount} live ${
                      liveCount === 1 ? "feed is" : "feeds are"
                    } connected${
                      pausedCount
                        ? `, with analysis paused on ${pausedCount}`
                        : ""
                    }. ${searchableCount} ${
                      searchableCount === 1 ? "source has" : "sources have"
                    } searchable visual moments.`}
              </p>
              <div className="vi-brief-meta">
                <span className="vi-brief-freshness">
                  <i /> Updated just now
                </span>
                <span>
                  {liveCount} live {liveCount === 1 ? "stream" : "streams"}
                </span>
                <span>Processing locally</span>
              </div>
              <div className="vi-brief-actions">
                <button
                  className="vi-button vi-button--primary"
                  type="button"
                  onClick={
                    attentionIncidents.length
                      ? onOpenEvents
                      : () => onOpenLive()
                  }
                >
                  {attentionIncidents.length
                    ? "Review evidence"
                    : "Open live view"}
                  <IconArrowRight size={17} />
                </button>
                <button
                  className="vi-button vi-button--quiet"
                  type="button"
                  onClick={() =>
                    onExplore("Show the most important recent activity.")
                  }
                >
                  Explore what happened
                </button>
              </div>
            </div>
          </article>

          <form className="vi-home-ask" onSubmit={submitQuestion}>
            <IconSparkles size={21} />
            <div>
              <label htmlFor="vi-home-question">
                Ask CT AI about this environment
              </label>
              <input
                id="vi-home-question"
                aria-label="Ask CT AI about this environment"
                disabled={asking || visualAnalystAvailable === false}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={
                  visualAnalystAvailable === false
                    ? "Visual reasoning is unavailable — open System for details"
                    : "What needs attention right now?"
                }
                value={question}
              />
            </div>
            <button
              type="submit"
              aria-label="Ask environment question"
              disabled={
                asking || !question.trim() || visualAnalystAvailable === false
              }
            >
              {asking ? (
                <span className="vi-spinner" />
              ) : (
                <IconArrowRight size={20} />
              )}
            </button>
          </form>
          {!answer && !answerError && (
            <div className="vi-home-suggestions">
              {[
                "What needs attention?",
                "Where is activity changing?",
                "Summarize the current scene",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => setQuestion(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
          {(answer || answerError) && (
            <div
              className={
                answerError ? "vi-home-answer is-error" : "vi-home-answer"
              }
            >
              <div>
                {answerError ? (
                  <IconAlertTriangle size={19} />
                ) : (
                  <IconSparkles size={19} />
                )}
                <strong>
                  {answerError
                    ? "Question could not complete"
                    : "Vision Analyst"}
                </strong>
              </div>
              <p>{answerError ?? answer?.answer}</p>
              {answer && (
                <button type="button" onClick={() => onExplore(answer.query)}>
                  Find supporting evidence <IconArrowRight size={16} />
                </button>
              )}
            </div>
          )}

          <div className="vi-home-section-heading">
            <div>
              <span className="vi-eyebrow">Live world</span>
              <h2>What each source understands</h2>
            </div>
            <button type="button" onClick={() => onOpenLive()}>
              View all sources <IconArrowRight size={16} />
            </button>
          </div>
          <div className="vi-world-grid">
            {rankedStreams.slice(0, 8).map((stream) => {
              const intelligence = intelligenceById[stream.streamId];
              const analysisState = analysisById[stream.streamId];
              const incident = incidentForStream(incidents, stream);
              const status = sourceStatus(stream, intelligence, analysisState);
              return (
                <article className="vi-world-card" key={stream.streamId}>
                  <div className="vi-world-card-media">
                    <VisionStreamCanvas
                      eager={false}
                      showStatus={false}
                      stream={stream}
                      vstApiUrl={vstApiUrl}
                    />
                  </div>
                  <button
                    className="vi-world-card-copy"
                    type="button"
                    onClick={() => onOpenLive(stream)}
                  >
                    <div>
                      <strong>{streamDisplayName(stream.name)}</strong>
                      <span className={`is-${status.tone}`}>
                        {status.label}
                      </span>
                    </div>
                    <p>
                      {sourceSummary(
                        stream,
                        intelligence,
                        analysisState,
                        incident
                      )}
                    </p>
                    <small>
                      {sourceKind(stream)} ·{" "}
                      {sourceTimelineContext(
                        stream,
                        intelligence?.lastSemanticAt
                      )}
                    </small>
                  </button>
                </article>
              );
            })}
          </div>
        </div>

        <aside className="vi-home-rail">
          <div className="vi-home-rail-heading">
            <span className="vi-eyebrow">Local edge</span>
            <h2>NVIDIA Thor</h2>
            <p>Inference and indexed evidence stay on this device.</p>
          </div>
          <div className="vi-edge-proof">
            <IconShieldCheck size={21} />
            <div>
              <strong>On-device boundary</strong>
              <span>No cloud inference configured</span>
            </div>
          </div>
          <dl className="vi-edge-metrics">
            <div>
              <dt>Services</dt>
              <dd>
                {systemHealth
                  ? `${
                      systemHealth.services.filter((service) => service.ok)
                        .length
                    }/${systemHealth.services.length}`
                  : "Checking"}
              </dd>
            </div>
            <div>
              <dt>Video sources</dt>
              <dd>{systemHealth?.thor?.activeStreams ?? streams.length}</dd>
            </div>
            <div>
              <dt>GPU temperature</dt>
              <dd>
                {systemHealth?.thor?.gpuTemperatureC == null
                  ? "Unavailable"
                  : `${systemHealth.thor.gpuTemperatureC.toFixed(0)}°C`}
              </dd>
            </div>
            <div>
              <dt>GPU power</dt>
              <dd>
                {systemHealth?.thor?.powerWatts == null
                  ? "Unavailable"
                  : `${systemHealth.thor.powerWatts.toFixed(1)} W`}
              </dd>
            </div>
          </dl>
          <div className="vi-pipeline-proof">
            <span>Local pipeline</span>
            <ol>
              <li>
                <IconCheck size={15} /> Video I/O
              </li>
              <li>
                <IconBolt size={15} /> Embed + retrieve
              </li>
              <li>
                <IconSparkles size={15} /> Reason + explain
              </li>
            </ol>
          </div>
          <div className="vi-noticed-list">
            <div className="vi-noticed-heading">
              <IconClock size={17} /> What the system noticed
            </div>
            {incidents.slice(0, 3).map((incident) => (
              <button type="button" key={incident.Id} onClick={onOpenEvents}>
                <span
                  className={
                    incidentVerdict(incident) === "confirmed"
                      ? "is-attention"
                      : "is-watch"
                  }
                />
                <div>
                  <strong>{incidentTitle(incident)}</strong>
                  <small>{relativeTime(incident.timestamp)}</small>
                </div>
              </button>
            ))}
            {!incidents.length && (
              <p>No operator-relevant events are waiting for review.</p>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
