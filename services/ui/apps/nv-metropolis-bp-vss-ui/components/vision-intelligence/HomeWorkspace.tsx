// SPDX-License-Identifier: MIT

import { VisionStreamCanvas } from "./VisionStreamCanvas";
import type { VisionAnalystRequest, VisionAnalystResponse } from "./analyst";
import {
  consolidateIncidents,
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
  onOpenSystem?: () => void;
  systemHealth: SystemHealth | null;
  visualAnalystAvailable?: boolean | null;
  vstApiUrl?: string | null;
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function recordingInvitation(stream: VisionStream | undefined) {
  const name = stream?.name.toLowerCase().replace(/\.mp4$/, "");
  if (name === "qa-recovery-20260928") return {
    query: "person carrying a box",
    action: "Find a person carrying a box",
    context: "Warehouse operations · Review how goods are handled",
  };
  if (name === "conveyor-box-movement-demo") return {
    query: "box moving on a conveyor belt",
    action: "Find a box moving on the conveyor",
    context: "Production & logistics · Follow an item through the line",
  };
  if (name === "conveyor-package-review-demo") return {
    query: "crumpled cardboard box on a conveyor",
    action: "Find a box to inspect",
    context: "Package review · Find footage for human inspection (simulation)",
  };
  return { query: "", action: "Search this video", context: "Find an activity you want to review" };
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
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

export function sourceTimelineContext(
  stream: VisionStream,
  lastSemanticAt: string | null | undefined
): string {
  // Archived media keeps its original capture timestamps. Presenting those as
  // live recency (for example, “14327h ago”) is misleading and visually noisy.
  if (!lastSemanticAt) return "Awaiting first indexed moment";
  return sourceKind(stream) === "Replay"
    ? "Indexed locally"
    : `Last indexed ${relativeTime(lastSemanticAt).toLowerCase()}`;
}

function sourceStatus(
  stream: VisionStream,
  intelligence: SourceIntelligence | undefined,
  analysisState: AnalysisState | undefined
): { label: string; tone: "attention" | "healthy" | "watch" } {
  if (stream.connectionState === "offline" || stream.connectionState === "removed") {
    return { label: "Disconnected", tone: "attention" };
  }
  if (sourceKind(stream) === "Replay") {
    return {
      label: intelligence?.semanticSegments ? "Searchable" : "Checking index",
      tone: intelligence?.semanticSegments ? "healthy" : "watch",
    };
  }
  if (analysisState === "paused") return { label: "Paused", tone: "watch" };
  if (analysisState === "partial")
    return { label: "Needs attention", tone: "attention" };
  if (analysisState === "changing") return { label: "Updating", tone: "watch" };
  if (intelligence?.semanticFresh === false)
    return { label: "Indexing delayed", tone: "watch" };
  return intelligence?.semanticFresh === true
    ? { label: "Analyzing", tone: "healthy" }
    : { label: "Checking", tone: "watch" };
}

export function HomeWorkspace({
  agentApiUrl,
  onExplore,
  onOpenLive,
  onOpenSystem,
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
  const [selectedRecordingId, setSelectedRecordingId] = useState<string | null>(null);

  useEffect(() => {
    try {
      setSelectedRecordingId(sessionStorage.getItem("vision-demo-recording"));
    } catch {
      // Choosing a chapter still works when browser storage is unavailable.
    }
  }, []);

  function selectRecording(streamId: string) {
    setSelectedRecordingId(streamId);
    try {
      sessionStorage.setItem("vision-demo-recording", streamId);
    } catch {
      // Persistence is optional; do not interrupt the current demonstration.
    }
  }

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
            ((intelligence?.semanticSegments ?? 0) > 0 ? 2_000_000 : 0) +
            (sourceKind(stream) === "Replay" ? 1_000_000 : 0) +
            (intelligence?.evidenceEvents ?? 0) * 1_000 +
            (intelligence?.semanticSegments ?? 0)
          );
        };
        return score(right) - score(left);
      }),
    [incidents, intelligenceById, streams]
  );
  const recordings = rankedStreams.filter((stream) => sourceKind(stream) === "Replay");
  const featured = recordings.find((stream) => stream.streamId === selectedRecordingId)
    ?? recordings.find((stream) => stream.name === "qa-recovery-20260928")
    ?? recordings.find((stream) => stream.name === "conveyor-box-movement-demo")
    ?? rankedStreams[0];
  const invitation = recordingInvitation(featured);
  const connectedCamera = rankedStreams.find((stream) => sourceKind(stream) === "Live" && stream.connectionState === "online");
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
    <section className="vi-home vi-demo-home">
      {recordings.length > 1 && (
        <div className="vi-demo-recordings" role="group" aria-label="Choose a demo recording">
          <span>Choose a recording</span>
          {recordings.map((stream) => (
            <button type="button" key={stream.streamId}
              aria-pressed={featured?.streamId === stream.streamId}
              onClick={() => selectRecording(stream.streamId)}>
              {streamDisplayName(stream.name)}
            </button>
          ))}
        </div>
      )}
      {featured && (
        <div className="vi-demo-feature">
          <div className="vi-demo-start">
            <span className="vi-demo-eyebrow">Video AI · On this Jetson</span>
            <h1>Ask your video<br />what happened.</h1>
            <p>Find an activity in video, ask about what you see, and open the footage behind the answer. All processed on this device.</p>
            <div className="vi-demo-invitation">
              <span>{invitation.context}</span>
              <button className="vi-button vi-button--primary" type="button"
                onClick={() => onExplore(invitation.query, featured)}>
                {invitation.action} <IconArrowRight size={18} />
              </button>
              <small>Search the footage first. Then ask your own question.</small>
            </div>
          </div>
          <figure>
            <div className="vi-demo-media">
              <VisionStreamCanvas
                key={featured.streamId}
                eager={sourceKind(featured) === "Replay"}
                showReplayControls
                stream={featured}
                vstApiUrl={vstApiUrl}
              />
            </div>
            <figcaption>
              <strong>{sourceKind(featured) === "Replay" ? "Recorded footage" : "Camera footage"}</strong>
              <span>{streamDisplayName(featured.name)} · {sourceStatus(featured, intelligenceById[featured.streamId], analysisById[featured.streamId]).label}</span>
            </figcaption>
          </figure>
        </div>
      )}
      {connectedCamera && (
        <section className="vi-demo-camera-entry" aria-label="Try a camera stream">
          <div>
            <span className="vi-demo-eyebrow">Try a camera stream</span>
            <h2>{visualAnalystAvailable === true ? "Ask about the scene. Check the video behind the answer." : "Preview a connected camera stream."}</h2>
            <p>{streamDisplayName(connectedCamera.name)}</p>
            <small>{visualAnalystAvailable === false
              ? "Video preview is available. Local AI answers are currently unavailable; check System for readiness."
              : visualAnalystAvailable !== true
              ? "Preview the stream while local AI readiness is checked."
              : analysisById[connectedCamera.streamId] === "paused"
              ? "Continuous analysis is paused. You can still preview the stream and ask an individual question."
              : "Open the stream, ask a question, then replay the inspected interval."}</small>
          </div>
          <button className="vi-button" type="button" onClick={() => onOpenLive(connectedCamera)}>
            Open camera stream <IconArrowRight size={18} />
          </button>
        </section>
      )}
      <ol className="vi-demo-journey" aria-label="Video intelligence workflow">
        <li><span>01</span><div><h2>Search in plain language</h2><p>Describe the activity you want to find.</p></div></li>
        <li><span>02</span><div><h2>See the exact moment</h2><p>Play the matching clip and check what happened.</p></div></li>
        <li><span>03</span><div><h2>Get an answer with evidence</h2><p>Ask a follow-up and save the answer with its video.</p></div></li>
      </ol>
      <details className="vi-demo-sources" aria-label="Source details">
        <summary>Sources and connection status <span>{streams.length} sources · {streams.filter((stream) => stream.connectionState === "offline").length} disconnected</span></summary>
        <div className="vi-home-section-heading">
          <h2>Available recordings and cameras</h2>
          <button type="button" onClick={() => onOpenLive()}>View all sources <IconArrowRight size={16} /></button>
        </div>
        {rankedStreams.map((stream) => {
          const intelligence = intelligenceById[stream.streamId];
          const status = sourceStatus(stream, intelligence, analysisById[stream.streamId]);
          return <button className="vi-demo-source" type="button" key={stream.streamId} onClick={() => onOpenLive(stream)}>
            <strong>{streamDisplayName(stream.name)}</strong>
            <span>{sourceKind(stream) === "Replay" ? "Recorded video" : "Camera"}</span>
            <span className={`is-${status.tone}`}>{status.label}</span>
            <IconArrowRight size={17} />
          </button>;
        })}
      </details>
      <footer className="vi-demo-local">
        <span><IconShieldCheck size={19} /> Video and AI on this device</span>
        <button type="button" onClick={onOpenSystem}>System <IconArrowRight size={16} /></button>
      </footer>
      <details className="vi-demo-advanced">
        <summary>Ask across sources</summary>
        <p>For an answer grounded in a specific moment, find and select a clip first.</p>
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
                  disabled={asking || visualAnalystAvailable === false}
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

      </details>
    </section>
  );
}
