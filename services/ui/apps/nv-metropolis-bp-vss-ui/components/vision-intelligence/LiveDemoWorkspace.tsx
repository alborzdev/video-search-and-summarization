// SPDX-License-Identifier: MIT

import { LiveAnswerReport } from "./LiveAnswerReport";
import { VisionStreamCanvas, type PlaybackStatus } from "./VisionStreamCanvas";
import type { VisionAnalystRequest, VisionAnalystResponse } from "./analyst";
import { evidenceClipEndpoint } from "./evidenceClip";
import type { InvestigationRecord } from "./investigation";
import type { VisionStream } from "./types";
import { createPeerId, streamDisplayName } from "./utils";
import {
  IconArrowRight,
  IconBell,
  IconMessageCircle,
  IconPlayerPlay,
  IconSearch,
  IconUser,
  IconList,
  IconFileText,
} from "@tabler/icons-react";
import React, { FormEvent, useCallback, useEffect, useRef, useState } from "react";

interface Props {
  streams: VisionStream[];
  analysisById: Record<string, string>;
  onExplore: (query: string, stream?: VisionStream) => void;
  onOpenEvents: () => void;
  onOpenLive: (stream?: VisionStream) => void;
  onOpenRules?: (stream?: VisionStream) => void;
  visualAnalystAvailable?: boolean | null;
  vstApiUrl?: string | null;
}

const suggestions = [
  { query: "Describe the people and their activity", icon: IconMessageCircle },
  { query: "Is anyone blocking the corridor?", icon: IconUser },
  { query: "What changed in the scene?", icon: IconList },
];

export function LiveDemoWorkspace(props: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const stream =
    props.streams.find((source) => source.streamId === selectedId) ??
    props.streams.find(
      (source) =>
        /digital-twin/i.test(source.url) || /spark.*hospital/i.test(source.name)
    ) ??
    props.streams.find((source) => source.connectionState === "online") ??
    props.streams[0];
  return (
    <LiveSceneDesk
      {...props}
      key={stream.streamId}
      stream={stream}
      onSelect={setSelectedId}
    />
  );
}

function LiveSceneDesk({
  stream,
  streams,
  analysisById,
  onSelect,
  onExplore,
  onOpenEvents,
  onOpenLive,
  onOpenRules,
  visualAnalystAvailable,
  vstApiUrl,
}: Props & { stream: VisionStream; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<VisionAnalystResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capture, setCapture] = useState<"on" | "off" | "unknown">("unknown");
  const [changing, setChanging] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [readyAt, setReadyAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [clip, setClip] = useState<string | null>(null);
  const [preparingClip, setPreparingClip] = useState(false);
  const [clipError, setClipError] = useState<string | null>(null);
  const [reports, setReports] = useState<InvestigationRecord[]>([]);
  const [reportsError, setReportsError] = useState(false);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [playbackStatus, setPlaybackStatus] =
    useState<PlaybackStatus>("connecting");
  const previewAvailable = playbackStatus === "playing";
  const mounted = useRef(true);
  const captureMutation = useRef(false);
  const captureGeneration = useRef(0);
  const observedCapture = useRef<"on" | "off" | "unknown">("unknown");
  const disconnected =
    stream.connectionState === "offline" ||
    stream.connectionState === "removed";
  const warming = capture === "on" && now < readyAt;
  const canAsk =
    visualAnalystAvailable === true &&
    capture === "on" &&
    !warming &&
    !disconnected &&
    !changing &&
    !preparingClip;
  const source: VisionAnalystRequest["sources"][number] = {
    kind: "live",
    name: stream.name,
    sensorId: stream.sensorId,
    streamId: stream.streamId,
  };

  const applyCapture = useCallback((status: "on" | "off" | "unknown") => {
    if (status === "on" && observedCapture.current !== "on") {
      setReadyAt(Date.now() + 30_000);
      setNow(Date.now());
    } else if (status !== "on") {
      setReadyAt(0);
    }
    observedCapture.current = status;
    setCapture(status);
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    // Read-only status and saved results. Opening the demo never starts capture or AI ingestion.
    const readCapture = async () => {
      if (captureMutation.current) return;
      const generation = ++captureGeneration.current;
      try {
        const response = await fetch(
          `/api/vision/live-capture?streamId=${encodeURIComponent(
            stream.streamId
          )}`,
          { cache: "no-store", signal: controller.signal }
        );
        const payload = await response.json();
        if (!response.ok || !["on", "off"].includes(payload.recordingStatus))
          throw new Error(payload.error || "Capture status is unavailable.");
        if (
          mounted.current &&
          !captureMutation.current &&
          generation === captureGeneration.current
        ) {
          applyCapture(payload.recordingStatus);
          setCaptureError(null);
        }
      } catch (failure) {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          !captureMutation.current &&
          generation === captureGeneration.current
        ) {
          applyCapture("unknown");
          setCaptureError(
            failure instanceof Error
              ? failure.message
              : "Capture status is unavailable."
          );
        }
      }
    };
    void readCapture();
    void fetch("/api/vision/investigations", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Saved reviews unavailable");
        return response.json();
      })
      .then((payload) => {
        if (mounted.current)
          setReports(
            (payload.investigations ?? [])
              .filter((report: InvestigationRecord) =>
                report.evidence.some(
                  (item) => item.sensor_id === stream.sensorId
                )
              )
              .slice(0, 3)
          );
      })
      .catch(() => {
        if (!controller.signal.aborted && mounted.current)
          setReportsError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted && mounted.current)
          setReportsLoading(false);
      });
    const poll = window.setInterval(() => void readCapture(), 15_000);
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearInterval(poll);
    };
  }, [applyCapture, stream.sensorId, stream.streamId]);

  useEffect(() => {
    if (!readyAt) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(tick);
  }, [readyAt]);

  const toggleCapture = async () => {
    if (changing || captureMutation.current || asking || capture === "unknown")
      return;
    setChanging(true);
    captureMutation.current = true;
    ++captureGeneration.current;
    setCaptureError(null);
    const action = capture === "on" ? "stop" : "start";
    let verified = false;
    try {
      const response = await fetch("/api/vision/live-capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ streamId: stream.streamId, action }),
      });
      const payload = await response.json();
      verified = ["on", "off"].includes(payload.recordingStatus);
      if (mounted.current && verified) applyCapture(payload.recordingStatus);
      if (!response.ok)
        throw new Error(payload.error || "Capture could not be updated.");
      if (!verified) throw new Error("Capture status could not be verified.");
    } catch (failure) {
      if (mounted.current) {
        if (!verified) applyCapture("unknown");
        setCaptureError(
          failure instanceof Error
            ? failure.message
            : "Capture could not be updated."
        );
      }
    } finally {
      captureMutation.current = false;
      if (mounted.current) setChanging(false);
    }
  };

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!canAsk || asking || !query.trim()) return;
    setAsking(true);
    setError(null);
    setAnswer(null);
    setClip(null);
    setClipError(null);
    try {
      const response = await fetch("/api/vision/analyst", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Timezone": Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        body: JSON.stringify({
          askedAt: new Date().toISOString(),
          conversationId: createPeerId(),
          query: query.trim(),
          scope: "selected-source",
          sources: [source],
        } satisfies VisionAnalystRequest),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "The video could not be inspected.");
      if (mounted.current) setAnswer(payload);
    } catch (failure) {
      if (mounted.current)
        setError(
          failure instanceof Error
            ? failure.message
            : "The video could not be inspected."
        );
    } finally {
      if (mounted.current) setAsking(false);
    }
  };

  const playEvidence = async () => {
    if (!answer?.observedWindow || preparingClip) return;
    setPreparingClip(true);
    setClipError(null);
    try {
      const response = await fetch(
        evidenceClipEndpoint(
          stream.streamId,
          answer.observedWindow.startTime,
          answer.observedWindow.endTime
        )
      );
      const payload = await response.json();
      if (!response.ok || !payload.videoUrl)
        throw new Error(payload.error || "The inspected clip is unavailable.");
      if (mounted.current) setClip(payload.videoUrl);
    } catch (failure) {
      if (mounted.current)
        setClipError(
          failure instanceof Error
            ? failure.message
            : "The inspected clip is unavailable."
        );
    } finally {
      if (mounted.current) setPreparingClip(false);
    }
  };
  const analysisState = analysisById[stream.streamId];
  const analysisLabel =
    analysisState === "paused"
      ? "Analysis paused"
      : analysisState === "active"
      ? "Search indexing active"
      : analysisState === "partial"
      ? "Analysis needs attention"
      : "Checking analysis";

  return (
    <section className="vi-showcase" aria-label="Live digital twin demo">
      <div className="vi-showcase-intro">
        <h1>Turn live activity into answers.</h1>
        <p>
          Watch the Sim, ask about people and activity, then replay the
          evidence.
        </p>
      </div>
      <div className="vi-showcase-desk">
        <div className="vi-showcase-scene">
          <figure className="vi-showcase-video">
            <div className="vi-showcase-video-heading">
              {streams.length > 1 ? (
                <select
                  aria-label="Demo camera"
                  value={stream.streamId}
                  onChange={(event) => onSelect(event.target.value)}
                  disabled={asking || changing}
                >
                  {streams.map((item) => (
                    <option key={item.streamId} value={item.streamId}>
                      {streamDisplayName(item.name)}
                    </option>
                  ))}
                </select>
              ) : (
                <strong>{streamDisplayName(stream.name)}</strong>
              )}
              <span
                className={
                  stream.connectionState === "online" ? "is-connected" : ""
                }
              >
                <i />
                {stream.connectionState === "online"
                  ? "Connected"
                  : disconnected
                  ? "Disconnected"
                  : "Checking connection"}
              </span>
            </div>
            <div className="vi-showcase-media">
              {clip ? (
                <video
                  key={clip}
                  src={clip}
                  controls
                  autoPlay
                  muted
                  playsInline
                  aria-label="Inspected video evidence"
                  onError={() =>
                    setClipError(
                      "This clip could not play. Try preparing it again."
                    )
                  }
                />
              ) : (
                <VisionStreamCanvas
                  stream={stream}
                  vstApiUrl={vstApiUrl}
                  liveSnapshotEnabled={false}
                  onPlaybackStatus={setPlaybackStatus}
                />
              )}
            </div>
            <figcaption>
              <span>
                <i
                  className={clip || !previewAvailable ? "" : "is-connected"}
                />
                {clip
                  ? "Inspected clip · recorded evidence"
                  : previewAvailable
                  ? "Live preview"
                  : playbackStatus === "poster"
                  ? "Stored preview · live video unavailable"
                  : playbackStatus === "error"
                  ? "Live preview unavailable"
                  : "Connecting live preview"}
              </span>
              {clip ? (
                <button type="button" onClick={() => setClip(null)}>
                  Return to live
                </button>
              ) : (
                <button type="button" onClick={() => onOpenLive(stream)}>
                  {analysisLabel} <IconArrowRight size={14} />
                </button>
              )}
            </figcaption>
          </figure>
          <div className="vi-showcase-capture">
            <div>
              <strong>
                {capture === "on"
                  ? warming
                    ? `Capturing video · ready in ${Math.max(
                        1,
                        Math.ceil((readyAt - now) / 1000)
                      )}s`
                    : "Live questions ready"
                  : capture === "off"
                  ? "Start capture to ask about new activity"
                  : "Checking live capture"}
              </strong>
              <span>
                {capture === "on"
                  ? "Recent footage is recorded for answers and replay."
                  : "Preview stays available while capture is off."}
              </span>
            </div>
            <button
              type="button"
              className="vi-button"
              disabled={
                changing ||
                asking ||
                capture === "unknown" ||
                (capture === "off" && disconnected)
              }
              onClick={() => void toggleCapture()}
            >
              {changing
                ? "Updating capture…"
                : capture === "on"
                ? "Stop capture"
                : "Start live capture"}
            </button>
          </div>
          {captureError && (
            <p className="vi-showcase-error" role="alert">
              {captureError}
            </p>
          )}
          <ol className="vi-showcase-steps">
            <li>
              <span>1</span>Spawn avatars in the Sim
            </li>
            <li>
              <span>2</span>Ask about the activity
            </li>
            <li>
              <span>3</span>Replay the evidence
            </li>
          </ol>
        </div>
        <aside className="vi-showcase-inspector" aria-label="Ask this scene">
          <h2>Ask this scene</h2>
          <p>Each answer inspects a recent video interval.</p>
          <div className="vi-showcase-prompts">
            {suggestions.map(({ query: suggestion, icon: Icon }) => (
              <button
                type="button"
                key={suggestion}
                disabled={asking}
                onClick={() => setQuery(suggestion)}
                aria-pressed={query === suggestion}
              >
                <Icon size={21} />
                <span>{suggestion}</span>
                <IconArrowRight size={17} />
              </button>
            ))}
          </div>
          <form onSubmit={ask}>
            <label htmlFor="vi-demo-question">Your question</label>
            <textarea
              id="vi-demo-question"
              value={query}
              maxLength={1000}
              placeholder="Ask about this scene…"
              disabled={asking}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button
              type="submit"
              className="vi-showcase-ask"
              disabled={!canAsk || asking || !query.trim()}
            >
              {asking ? "Inspecting video…" : "Ask the video"}
              {asking ? (
                <span className="vi-spinner" />
              ) : (
                <IconArrowRight size={20} />
              )}
            </button>
          </form>
          {visualAnalystAvailable !== true && (
            <p className="vi-showcase-notice">
              {visualAnalystAvailable === false
                ? "Visual AI is unavailable. Check System before asking."
                : "Checking visual AI readiness."}
            </p>
          )}
          <div
            className="vi-showcase-answer"
            aria-live="polite"
            aria-busy={asking}
          >
            {asking ? (
              <>
                <strong>Inspecting the recent footage</strong>
                <p>
                  The live preview continues while AI reviews the recorded
                  interval.
                </p>
              </>
            ) : error ? (
              <>
                <strong>Question could not complete</strong>
                <p role="alert">{error}</p>
              </>
            ) : answer ? (
              <>
                <strong>What the video shows</strong>
                <p className="vi-showcase-answer-text">{answer.answer}</p>
                {answer.observedWindow ? (
                  <>
                    <div className="vi-showcase-window">
                      Inspected{" "}
                      {new Date(
                        answer.observedWindow.startTime
                      ).toLocaleTimeString()}{" "}
                      –{" "}
                      {new Date(
                        answer.observedWindow.endTime
                      ).toLocaleTimeString()}
                      <span>
                        Recorded interval ·{" "}
                        {Math.round(
                          (Date.parse(answer.observedWindow.endTime) -
                            Date.parse(answer.observedWindow.startTime)) /
                            1000
                        )}{" "}
                        seconds
                      </span>
                    </div>
                    <button
                      className="vi-button"
                      type="button"
                      disabled={preparingClip}
                      onClick={() => void playEvidence()}
                    >
                      <IconPlayerPlay size={17} />
                      {preparingClip
                        ? "Preparing clip…"
                        : "Replay inspected clip"}
                    </button>
                    <LiveAnswerReport
                      key={answer.generatedAt}
                      result={answer}
                      source={source}
                    />
                  </>
                ) : (
                  <p>
                    No inspected interval was returned; this answer has no
                    playable evidence.
                  </p>
                )}
                <button
                  className="vi-showcase-related"
                  type="button"
                  onClick={() => onExplore(answer.query, stream)}
                >
                  Find related moments <IconArrowRight size={15} />
                </button>
              </>
            ) : (
              <>
                <IconMessageCircle size={22} />
                <div>
                  <strong>Your answer appears here</strong>
                  <p>
                    AI observations will include the inspected time window and a
                    route to the footage.
                  </p>
                </div>
              </>
            )}
          </div>
          {clipError && (
            <p className="vi-showcase-error" role="alert">
              {clipError}
            </p>
          )}
        </aside>
      </div>
      <section
        className="vi-showcase-features"
        aria-label="Video intelligence features"
      >
        <h2>Show what video can do</h2>
        <div>
          <article>
            <span>1</span>
            <div>
              <h3>Find a moment</h3>
              <p>Search people and activities in indexed video.</p>
              <button
                className="vi-button"
                type="button"
                onClick={() =>
                  onExplore(
                    "person walking through a hospital corridor",
                    stream
                  )
                }
              >
                <IconSearch size={18} />
                Search this scene <IconArrowRight size={16} />
              </button>
            </div>
          </article>
          <article>
            <span>2</span>
            <div>
              <h3>Watch a condition</h3>
              <p>Use a plain-language rule to surface matching activity.</p>
              <button
                className="vi-button"
                type="button"
                disabled={!onOpenRules}
                onClick={() => onOpenRules?.(stream)}
              >
                <IconBell size={18} />
                Set an alert <IconArrowRight size={16} />
              </button>
            </div>
          </article>
          <article>
            <span>3</span>
            <div>
              <h3>Keep the evidence</h3>
              <p>Save an answer with its video for review.</p>
              <button
                className="vi-button"
                type="button"
                onClick={onOpenEvents}
              >
                <IconFileText size={18} />
                View reports <IconArrowRight size={16} />
              </button>
            </div>
          </article>
        </div>
        {analysisState === "paused" && (
          <p className="vi-showcase-index-note">
            Search uses earlier indexed video.{" "}
            <button type="button" onClick={() => onOpenLive(stream)}>
              Resume analysis in Live cameras
            </button>{" "}
            to make new activity searchable.
          </p>
        )}
      </section>
      <section className="vi-showcase-saved" aria-label="Earlier evidence">
        <div>
          <h2>Earlier evidence</h2>
          <p>Saved reviews stay available while live analysis is paused.</p>
          <button type="button" onClick={onOpenEvents}>
            Open saved reviews <IconArrowRight size={16} />
          </button>
        </div>
        {reports.length ? (
          <ul>
            {reports.map((report) => (
              <li key={report.id}>
                <a href={report.report_url}>
                  <strong>{report.title}</strong>
                  <span>
                    {new Date(report.created_at).toLocaleString()} ·{" "}
                    {report.evidence.every(
                      (item) => item.media_status === "retained"
                    )
                      ? "Video retained"
                      : "Video depends on source retention"}
                  </span>
                  <IconArrowRight size={16} />
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p>
            {reportsLoading
              ? "Loading saved reviews…"
              : reportsError
              ? "Saved reviews could not be loaded. Open Events & reports to retry."
              : "No saved reviews for this scene yet. Ask a question, replay its clip, then save a report."}
          </p>
        )}
      </section>
    </section>
  );
}
