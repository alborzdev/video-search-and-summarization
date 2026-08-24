// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import type { VisionStream } from "./types";
import { sourceKind, streamDisplayName } from "./utils";
import type { VideoHistoryAnswer, VideoHistoryRecord } from "./videoHistory";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconClock,
  IconDatabase,
  IconHistory,
  IconPlayerPlay,
  IconRefresh,
  IconSearch,
  IconSparkles,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import React, { FormEvent, useEffect, useMemo, useState } from "react";

interface HistoryMessage {
  content: string;
  role: "assistant" | "user";
}

interface VideoHistoryPanelProps {
  onClose: () => void;
  onInvestigate: (query: string) => void;
  stream: VisionStream;
}

function defaultsFor(stream: VisionStream): {
  events: string;
  scenario: string;
} {
  if (/traffic|road|intersection|vehicle|jaywalk/i.test(stream.name)) {
    return {
      events:
        "pedestrian crossing, stopped vehicle, near collision, unusual traffic activity",
      scenario: "traffic monitoring",
    };
  }
  if (/warehouse|forklift|loading|dock|aisle/i.test(stream.name)) {
    return {
      events:
        "person and vehicle proximity, restricted-zone entry, blocked aisle, unusual activity",
      scenario: "warehouse monitoring",
    };
  }
  return {
    events: "notable activity, safety risk, movement changes",
    scenario: "activity monitoring",
  };
}

function displaySummary(value?: string): string {
  if (!value) return "Video history is ready for questions.";
  try {
    const parsed = JSON.parse(value) as { video_summary?: string };
    return parsed.video_summary?.trim() || value;
  } catch {
    return value.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
  }
}

function formatDate(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
        month: "short",
        day: "numeric",
      }).format(date);
}

async function waitForHistoryBuild(
  sourceId: string,
  signal?: AbortSignal
): Promise<VideoHistoryRecord> {
  const deadline = Date.now() + 12 * 60_000;
  while (Date.now() < deadline) {
    const response = await fetch(
      `/api/vision/video-history?sourceId=${encodeURIComponent(sourceId)}`,
      { cache: "no-store", signal }
    );
    if (response.ok) {
      const payload = (await response.json()) as VideoHistoryRecord;
      if (payload.status === "ready") return payload;
      if (payload.status === "error") {
        throw new Error(
          payload.error || "Video history synchronization failed."
        );
      }
    }
    await new Promise((resolve) => window.setTimeout(resolve, 3_000));
  }
  throw new Error(
    "Video history is still synchronizing locally. You can close this panel and reopen History to check its completed state."
  );
}

export function VideoHistoryPanel({
  onClose,
  onInvestigate,
  stream,
}: VideoHistoryPanelProps) {
  const defaults = useMemo(() => defaultsFor(stream), [stream]);
  const [record, setRecord] = useState<VideoHistoryRecord | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [scenario, setScenario] = useState(defaults.scenario);
  const [events, setEvents] = useState(defaults.events);
  const [isBuilding, setIsBuilding] = useState(false);
  const [buildSeconds, setBuildSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [answer, setAnswer] = useState<VideoHistoryAnswer | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [isPreparingVideo, setIsPreparingVideo] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const dialogRef = useDialogAccessibility<HTMLDivElement>({ isOpen: true, onClose });
  const citationDialogRef = useDialogAccessibility<HTMLDivElement>({
    isOpen: Boolean(videoUrl || videoError || isPreparingVideo),
    onClose: () => { setVideoUrl(null); setVideoError(null); },
  });

  useEffect(() => {
    const controller = new AbortController();
    setStatusLoading(true);
    fetch(
      `/api/vision/video-history?sourceId=${encodeURIComponent(
        stream.sensorId
      )}`,
      {
        cache: "no-store",
        signal: controller.signal,
      }
    )
      .then(async (response) => {
        if (response.status === 404) return null;
        const payload = (await response.json()) as VideoHistoryRecord & {
          error?: string;
        };
        if (!response.ok)
          throw new Error(
            payload.error || "Video history status is unavailable."
          );
        return payload;
      })
      .then((payload) => {
        if (!controller.signal.aborted) {
          setRecord(payload);
          if (payload) {
            setScenario(payload.scenario);
            setEvents(payload.events.join(", "));
            if (payload.status === "building") {
              setIsBuilding(true);
              setBuildSeconds(0);
              void waitForHistoryBuild(stream.sensorId, controller.signal)
                .then((ready) => setRecord(ready))
                .catch((requestError) => {
                  if (!controller.signal.aborted) {
                    setError(
                      requestError instanceof Error
                        ? requestError.message
                        : "Video history synchronization failed."
                    );
                  }
                })
                .finally(() => {
                  if (!controller.signal.aborted) setIsBuilding(false);
                });
            }
          }
        }
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Video history status is unavailable."
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setStatusLoading(false);
      });
    return () => controller.abort();
  }, [stream.sensorId]);

  useEffect(() => {
    if (!isBuilding) return;
    const timer = window.setInterval(
      () => setBuildSeconds((seconds) => seconds + 1),
      1_000
    );
    return () => window.clearInterval(timer);
  }, [isBuilding]);

  const build = async () => {
    const eventList = events
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!scenario.trim() || !eventList.length) return;
    setIsBuilding(true);
    setBuildSeconds(0);
    setError(null);
    try {
      const response = await fetch("/api/vision/video-history", {
        body: JSON.stringify({
          action: "start",
          events: eventList,
          scenario: scenario.trim(),
          source: {
            id: stream.sensorId,
            kind: sourceKind(stream) === "Live" ? "live" : "replay",
            name: stream.name,
          },
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      let payload: (VideoHistoryRecord & { error?: string }) | null = null;
      try {
        payload = (await response.json()) as VideoHistoryRecord & {
          error?: string;
        };
      } catch {
        // A long local graph rebuild can outlive the ingress response timeout.
      }
      if (!response.ok) {
        if ([502, 503, 504].includes(response.status)) {
          payload = await waitForHistoryBuild(stream.sensorId);
        } else {
          throw new Error(
            payload?.error || `Video history returned ${response.status}.`
          );
        }
      }
      if (payload?.status === "building")
        payload = await waitForHistoryBuild(stream.sensorId);
      if (payload?.status === "error")
        throw new Error(
          payload.error || "Video history synchronization failed."
        );
      if (!payload)
        throw new Error("Video history returned an unreadable response.");
      setRecord(payload);
      setMessages([]);
      setAnswer(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Video history could not be built."
      );
    } finally {
      setIsBuilding(false);
    }
  };

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || isAsking || !record) return;
    const nextMessages: HistoryMessage[] = [
      ...messages,
      { content: nextQuestion, role: "user" as const },
    ].slice(-8);
    setQuestion("");
    setIsAsking(true);
    setError(null);
    try {
      const response = await fetch("/api/vision/video-history", {
        body: JSON.stringify({
          action: "ask",
          messages: nextMessages,
          sourceId: stream.sensorId,
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      const payload = (await response.json()) as VideoHistoryAnswer & {
        error?: string;
      };
      if (!response.ok)
        throw new Error(
          payload.error || `Video history returned ${response.status}.`
        );
      setAnswer(payload);
      setMessages(
        [
          ...nextMessages,
          { content: payload.answer, role: "assistant" as const },
        ].slice(-8)
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The history question could not be answered."
      );
    } finally {
      setIsAsking(false);
    }
  };

  const playCitation = async (startTime: string, endTime: string) => {
    setVideoUrl(null);
    setVideoError(null);
    setIsPreparingVideo(true);
    try {
      const params = new URLSearchParams({
        endTime,
        sensorId: stream.sensorId,
        startTime,
      });
      const response = await fetch(`/api/vision/evidence?${params.toString()}`);
      const payload = (await response.json()) as {
        error?: string;
        videoUrl?: string;
      };
      if (!response.ok || !payload.videoUrl)
        throw new Error(payload.error || "The cited clip is unavailable.");
      setVideoUrl(payload.videoUrl);
    } catch (requestError) {
      setVideoError(
        requestError instanceof Error
          ? requestError.message
          : "The cited clip is unavailable."
      );
    } finally {
      setIsPreparingVideo(false);
    }
  };

  const clearHistory = async () => {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    setError(null);
    try {
      const response = await fetch(
        `/api/vision/video-history?sourceId=${encodeURIComponent(
          stream.sensorId
        )}`,
        { method: "DELETE" }
      );
      const payload = (await response.json()) as { error?: string };
      if (!response.ok)
        throw new Error(payload.error || "Video history could not be cleared.");
      setRecord(null);
      setAnswer(null);
      setMessages([]);
      setConfirmClear(false);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Video history could not be cleared."
      );
    }
  };

  const buildingLabel =
    sourceKind(stream) === "Live"
      ? buildSeconds < 12
        ? "Capturing fresh Cosmos captions…"
        : "Linking observed activity into source history…"
      : buildSeconds < 8
      ? "Preparing retained footage…"
      : "Cosmos is captioning and linking the replay…";
  const lastUserQuestion = messages
    .filter((message) => message.role === "user")
    .at(-1)?.content;

  return (
    <div
      ref={dialogRef}
      className="vi-evidence-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Video history"
    >
      <section className="vi-history-panel">
        <header>
          <div>
            <span>
              <IconHistory size={18} /> Video history
            </span>
            <h1>{streamDisplayName(stream.name)}</h1>
            <p>
              Source-scoped LVS + Neo4j memory built from locally processed
              captions.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close video history"
          >
            <IconX size={19} />
          </button>
        </header>
        {statusLoading ? (
          <div className="vi-history-loading">
            <span className="vi-spinner" /> Checking source history…
          </div>
        ) : isBuilding ? (
          <div className="vi-history-build-progress" aria-live="polite">
            <span className="vi-spinner" />
            <div>
              <strong>{buildingLabel}</strong>
              <span>
                This runs locally on Thor. You can close this panel; the sync
                continues in the background.
              </span>
            </div>
            <time>{buildSeconds}s</time>
          </div>
        ) : (
          <>
            <div className="vi-history-status">
              <div className={record?.status === "ready" ? "is-ready" : ""}>
                <IconDatabase size={18} />
                <span>
                  <strong>
                    {record?.status === "ready"
                      ? "History ready"
                      : "History not built"}
                  </strong>
                  <small>
                    {record?.lastSynchronizedAt
                      ? `Synced ${formatDate(record.lastSynchronizedAt)}`
                      : "Build once, then ask about more than the current view"}
                  </small>
                </span>
              </div>
              {record?.status === "ready" && (
                <button type="button" onClick={() => void build()}>
                  <IconRefresh size={15} />{" "}
                  {record.sourceKind === "live"
                    ? "Sync new history"
                    : "Rebuild"}
                </button>
              )}
            </div>
            {!record || record.status !== "ready" ? (
              <div className="vi-history-setup">
                <div>
                  <IconSparkles size={18} />
                  <span>
                    <strong>Choose what this history should understand</strong>
                    <small>
                      These fields guide Cosmos captioning and keep the graph
                      useful for the scenario.
                    </small>
                  </span>
                </div>
                <label>
                  Scenario
                  <input
                    aria-label="Video history scenario"
                    value={scenario}
                    onChange={(event) => setScenario(event.target.value)}
                    maxLength={1_024}
                  />
                </label>
                <label>
                  Events of interest
                  <textarea
                    aria-label="Video history events"
                    value={events}
                    onChange={(event) => setEvents(event.target.value)}
                    placeholder="Comma-separated events"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void build()}
                  disabled={!scenario.trim() || !events.trim()}
                >
                  <IconHistory size={17} /> Build searchable history
                </button>
              </div>
            ) : (
              <>
                <section className="vi-history-summary">
                  <span>
                    <IconClock size={16} /> Indexed history
                  </span>
                  <p>{displaySummary(record.summary)}</p>
                  <small>
                    {record.timelineStart && record.timelineEnd
                      ? `${formatDate(record.timelineStart)} – ${formatDate(
                          record.timelineEnd
                        )}`
                      : "Retained source history"}{" "}
                    · {record.scenario}
                  </small>
                </section>
                <form className="vi-history-question" onSubmit={ask}>
                  <IconSparkles size={19} />
                  <input
                    aria-label="Ask video history"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="Ask what happened earlier, how activity changed, or when an event occurred…"
                  />
                  <button
                    type="submit"
                    disabled={!question.trim() || isAsking}
                    aria-label="Ask video history question"
                  >
                    {isAsking ? (
                      <span className="vi-spinner" />
                    ) : (
                      <IconArrowRight size={18} />
                    )}
                  </button>
                </form>
                <div className="vi-history-suggestions">
                  {[
                    "What activity occurred over this period?",
                    "What safety-relevant activity occurred?",
                    "When was activity highest?",
                  ].map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      disabled={isAsking}
                      onClick={() => setQuestion(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
                {answer && (
                  <section className="vi-history-answer" aria-live="polite">
                    <span>
                      <IconSparkles size={16} /> Grounded history answer
                    </span>
                    <p>{answer.answer}</p>
                    {answer.warning && (
                      <div className="vi-history-warning">
                        <IconAlertTriangle size={15} /> {answer.warning}
                      </div>
                    )}
                    {answer.citations.length > 0 && (
                      <div className="vi-history-citations">
                        {answer.citations.map((citation, index) => (
                          <button
                            type="button"
                            key={`${citation.startTime}-${index}`}
                            onClick={() =>
                              void playCitation(
                                citation.startTime,
                                citation.endTime
                              )
                            }
                          >
                            <IconPlayerPlay size={14} /> Evidence {index + 1}
                            <small>{citation.label}</small>
                          </button>
                        ))}
                      </div>
                    )}
                    <button
                      className="vi-history-find-related"
                      type="button"
                      onClick={() =>
                        onInvestigate(
                          lastUserQuestion || "Show related activity"
                        )
                      }
                    >
                      <IconSearch size={15} /> Find related clips in Investigate
                    </button>
                  </section>
                )}
              </>
            )}
          </>
        )}
        {error && (
          <div className="vi-history-error" role="alert">
            <IconAlertTriangle size={17} /> {error}
          </div>
        )}
        {record?.status === "ready" && !isBuilding && (
          <footer>
            <button
              type="button"
              className={confirmClear ? "is-confirm" : ""}
              onClick={() => void clearHistory()}
            >
              <IconTrash size={15} />{" "}
              {confirmClear
                ? "Confirm clear graph history"
                : "Clear this source history"}
            </button>
            {confirmClear && (
              <button type="button" onClick={() => setConfirmClear(false)}>
                Cancel
              </button>
            )}
          </footer>
        )}
      </section>
      {(videoUrl || videoError || isPreparingVideo) && (
        <div
          ref={citationDialogRef}
          className="vi-history-video"
          role="dialog"
          aria-modal="true"
          aria-label="History citation"
        >
          <button
            type="button"
            onClick={() => {
              setVideoUrl(null);
              setVideoError(null);
            }}
            aria-label="Close history citation"
          >
            <IconX size={18} />
          </button>
          {videoUrl ? (
            <video src={videoUrl} controls autoPlay playsInline />
          ) : (
            <div>
              {isPreparingVideo ? (
                <>
                  <span className="vi-spinner" /> Preparing cited footage…
                </>
              ) : (
                videoError
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
