// SPDX-License-Identifier: MIT

import styles from "./GuidedDemoWorkspace.module.css";
import { LiveDemoWorkspace } from "./LiveDemoWorkspace";
import type {
  SourceIntelligence,
  SourceAnalysisState,
} from "./OperationsWorkspace";
import {
  loadSourceAnalysisProfile,
  type SourceAnalysisProfile,
} from "./analysisProfiles";
import type { MonitoringRule } from "./monitoringRules";
import type { VisionStream } from "./types";
import { useVisionStreams } from "./useVisionStreams";
import { sourceKind, streamDisplayName } from "./utils";
import {
  IconArrowLeft,
  IconArrowRight,
  IconBell,
  IconCamera,
  IconCpu,
  IconFileText,
  IconFocus2,
  IconMessageCircle,
  IconSearch,
  IconShieldCheck,
} from "@tabler/icons-react";
import dynamic from "next/dynamic";
import React, { useEffect, useMemo, useRef, useState } from "react";

const InvestigateWorkspace = dynamic(() =>
  import("./InvestigateWorkspace").then((m) => m.InvestigateWorkspace)
);
const AlertRulesWorkspace = dynamic(() =>
  import("./AlertRulesWorkspace").then((m) => m.AlertRulesWorkspace)
);
const ActivityInsightsWorkspace = dynamic(() =>
  import("./ActivityInsightsWorkspace").then((m) => m.ActivityInsightsWorkspace)
);

const chapters = [
  {
    id: "watch",
    label: "Watch",
    icon: IconCamera,
    title: "Start with the real scene.",
    description:
      "Live camera footage. Search and visual reasoning, processed on this device.",
    say: "This simulator publishes an RTSP feed, just like a network camera. VSS turns that feed into video we can search and ask about.",
    action:
      "Check the live view and its connection status before exploring recent activity.",
    check:
      "Connected, live preview playing, and a recent indexing time. A static scene can still be a live feed.",
  },
  {
    id: "ask",
    label: "Ask",
    icon: IconMessageCircle,
    title: "Ask your video.",
    description:
      "Ask about the scene. Then replay the seconds behind the answer.",
    say: "The agent retrieves recent recorded footage and uses a local vision model to answer. We can check exactly what it inspected.",
    action:
      "Choose a question, press Ask the video, then Replay inspected clip. Save a report if you want to keep it.",
    check:
      "Compare the answer with the inspected clip. Ask about people, equipment, or visible activity without assuming they are present.",
  },
  {
    id: "search",
    label: "Find",
    icon: IconSearch,
    title: "Describe it. Find the moment.",
    description:
      "Search the camera’s recent indexed history in everyday language.",
    say: "Cosmos Embed represents the meaning of video and our query as embeddings. Similarity brings back candidate clips, with source and time.",
    action:
      "Try pallets and storage racks, or a person walking through a warehouse aisle. Play a matching clip, then ask a focused follow-up.",
    check:
      "Confirm the selected camera and timestamps. A ranked match is a candidate to inspect, not proof that an activity happened.",
  },
  {
    id: "track",
    label: "Follow",
    icon: IconFocus2,
    title: "Inspect detections and track IDs.",
    description:
      "See the boxes and recorded observations behind an object detection.",
    say: "Detection locates objects; tracking links observations within a camera. Appearance search adds another way to retrieve footage when object embeddings are indexed.",
    action:
      "Use the search results below. Play a clip, choose Inspect detected objects, and compare a box and its track ID with the footage.",
    check:
      "Check the actual footage and labels. Use Find similar when the separate object embedding index is available. Similar appearance does not establish identity.",
  },
  {
    id: "alerts",
    label: "Monitor",
    icon: IconBell,
    title: "Tell VSS what to watch for.",
    description:
      "Define a visible condition. Let real matching footage trigger a review.",
    say: "Instead of watching every screen, we define a condition and inspect the video whenever the model finds a match.",
    action:
      "Choose a visible warehouse condition, such as a forklift appearing or an aisle being blocked. Review the rule before activating it.",
    check:
      "One continuous visual rule can run at a time. Pause it before asking another visual question. A model match still needs a person to review its evidence.",
  },
  {
    id: "evidence",
    label: "Review",
    icon: IconFileText,
    title: "Bring it back to the evidence.",
    description:
      "Open the event, replay its footage, and keep a report for follow-up.",
    say: "The result is more than an answer or notification: it has a camera, a time, and footage we can review and retain.",
    action:
      "Refresh events, open a matching event and play its clip. Save an evidence report. Open a saved report to show its retained video.",
    check:
      "Check the triggering rule and observed time. Saved reports retain earlier evidence. Pause a rule when monitoring is no longer needed.",
  },
] as const;
type Chapter = (typeof chapters)[number]["id"];

interface Props {
  agentApiUrl?: string | null;
  mdxWebApiUrl?: string | null;
  searchByImageEnabled?: boolean;
  visualAnalystAvailable?: boolean | null;
  vstApiUrl?: string | null;
  onOpenLive: (stream?: VisionStream) => void;
  onOpenSystem: () => void;
  onOpenExplainer: () => void;
}

export function GuidedDemoWorkspace(props: Props) {
  const { streams, error, isLoading, refresh } = useVisionStreams(
    props.vstApiUrl
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const cameras = streams.filter((stream) => sourceKind(stream) === "Live");
  const source =
    cameras.find((stream) => stream.streamId === selectedId) ??
    cameras.find((stream) => /digital-twin/i.test(stream.url)) ??
    cameras.find((stream) => stream.connectionState === "online") ??
    cameras[0];

  useEffect(() => {
    // Health updates must not select a different camera and remount the
    // workflow while an operator is writing a question or creating a rule.
    if (source && selectedId !== source.streamId) setSelectedId(source.streamId);
  }, [selectedId, source?.streamId]);

  if (!source)
    return (
      <section className={styles.empty}>
        <IconCamera size={34} />
        <h1>
          {isLoading ? "Finding your camera…" : "Connect a camera to begin."}
        </h1>
        <p>
          {error ??
            "Connect a live source to explore its indexed footage and evidence."}
        </p>
        <button type="button" onClick={() => void refresh()}>
          Refresh sources
        </button>
        <button type="button" onClick={props.onOpenSystem}>
          Manage sources
        </button>
      </section>
    );

  // A deliberate source change resets evidence belonging to the previous camera.
  return (
    <DemoJourney
      key={source.streamId}
      {...props}
      source={source}
      cameras={cameras}
      onSelect={setSelectedId}
    />
  );
}

function DemoJourney({
  source,
  cameras,
  onSelect,
  ...props
}: Props & {
  source: VisionStream;
  cameras: VisionStream[];
  onSelect: (id: string) => void;
}) {
  const [step, setStep] = useState<Chapter>("watch");
  const [notes, setNotes] = useState(false);
  const [openedSearch, setOpenedSearch] = useState(false);
  const [searchRequest, setSearchRequest] = useState({
    camera: source,
    query: "",
  });
  const [intelligence, setIntelligence] = useState<SourceIntelligence | null>(
    null
  );
  const [profile, setProfile] = useState<SourceAnalysisProfile | null>(null);
  const [analysis, setAnalysis] = useState<SourceAnalysisState>("unknown");
  const [visualRuleActive, setVisualRuleActive] = useState<boolean | null>(
    null
  );
  const [statusError, setStatusError] = useState(false);
  const [eventsMode, setEventsMode] = useState<"activity" | "insights">(
    "activity"
  );
  const scroller = useRef<HTMLDivElement>(null);
  const index = chapters.findIndex((chapter) => chapter.id === step);
  const chapter = chapters[index];
  const inSearch = step === "search" || step === "track";
  const queries = useMemo(
    () => ["pallets and storage racks", "person walking through a warehouse aisle", "forklift near a pallet"],
    []
  );

  function go(next: Chapter) {
    if (next === "search" || next === "track") setOpenedSearch(true);
    setStep(next);
    scroller.current?.scrollTo({
      top: 0,
      behavior: "instant" as ScrollBehavior,
    });
  }

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const read = async (url: string) => {
      const response = await fetch(url, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Status unavailable");
      return response.json();
    };
    const load = async () => {
      const params = new URLSearchParams({
        name: source.name,
        sensorId: source.sensorId,
      });
      const results = await Promise.allSettled([
        read(`/api/vision/source-intelligence?${params}`),
        props.agentApiUrl
          ? read(
              `${props.agentApiUrl}/rtsp-streams/${encodeURIComponent(
                source.sensorId
              )}/analysis`
            )
          : Promise.reject(new Error("Agent unavailable")),
        loadSourceAnalysisProfile(source.sensorId, controller.signal),
        read("/api/vision/monitoring-rules"),
      ]);
      if (controller.signal.aborted) return;
      const [indexed, state, detector, rules] = results;
      setIntelligence(indexed.status === "fulfilled" ? indexed.value : null);
      setStatusError(indexed.status === "rejected");
      setAnalysis(
        state.status === "fulfilled"
          ? state.value.state ?? "unknown"
          : "unknown"
      );
      setProfile(detector.status === "fulfilled" ? detector.value : null);
      setVisualRuleActive(
        rules.status === "fulfilled"
          ? (rules.value.rules ?? []).some(
              (rule: MonitoringRule) =>
                rule.engine === "vlm" && rule.status === "active"
            )
          : null
      );
      timer = setTimeout(() => void load(), 20_000);
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [source.name, source.sensorId, props.agentApiUrl]);

  const indexingTime =
    intelligence?.lastSemanticAt &&
    Number.isFinite(Date.parse(intelligence.lastSemanticAt))
      ? new Date(intelligence.lastSemanticAt).toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
          second: "2-digit",
        })
      : null;
  const indexLabel =
    analysis === "paused"
      ? "Indexing paused"
      : intelligence?.semanticFresh === true
      ? "Index up to date"
      : intelligence?.semanticFresh === false
      ? "Indexing delayed"
      : "Checking index";

  return (
    <div
      className={styles.root}
      ref={scroller}
      aria-label="Video workflow"
    >
      <nav className={styles.rail} aria-label="Workflow chapters">
        <div className={styles.chapters}>
          {chapters.map((item, i) => (
            <button
              type="button"
              key={item.id}
              aria-label={`Step ${i + 1}: ${item.label}`}
              aria-current={step === item.id ? "step" : undefined}
              onClick={() => go(item.id)}
            >
              <span>{String(i + 1).padStart(2, "0")}</span>
              {item.label}
            </button>
          ))}
        </div>
        <div className={styles.arrows}>
          <button
            type="button"
            disabled={index === 0}
            aria-label="Previous workflow step"
            onClick={() => go(chapters[index - 1].id)}
          >
            <IconArrowLeft size={18} />
          </button>
          <button
            type="button"
            disabled={index === chapters.length - 1}
            aria-label="Next workflow step"
            onClick={() => go(chapters[index + 1].id)}
          >
            <IconArrowRight size={18} />
          </button>
        </div>
      </nav>
      <div className={styles.content}>
        <div className={styles.context}>
          <label>
            <IconCamera size={16} />
            <select
              aria-label="Workflow camera"
              value={source.streamId}
              onChange={(event) => onSelect(event.target.value)}
            >
              {cameras.map((camera) => (
                <option value={camera.streamId} key={camera.streamId}>
                  {streamDisplayName(camera.name)}
                </option>
              ))}
            </select>
          </label>
          <span>
            <IconShieldCheck size={15} /> Local video + AI
          </span>
          <button
            type="button"
            aria-expanded={notes}
            onClick={() => setNotes((value) => !value)}
          >
            Workflow tips
          </button>
        </div>
        <header key={step} className={styles.heading}>
          <span className={styles.kicker}>
            VIDEO WORKFLOW <i /> {String(index + 1).padStart(2, "0")} / 06
          </span>
          <h1>{chapter.title}</h1>
          <p>{chapter.description}</p>
        </header>
        {notes && (
          <aside className={styles.notes} aria-label="Workflow tips">
            <div>
              <span>How it works</span>
              <p>{chapter.say}</p>
            </div>
            <div>
              <span>Try</span>
              <p>{chapter.action}</p>
            </div>
            <div>
              <span>Check</span>
              <p>{chapter.check}</p>
            </div>
          </aside>
        )}
        {step === "ask" && visualRuleActive === true && (
          <div className={styles.notice} role="status">
            A visual monitoring rule is running.{" "}
            <button type="button" onClick={() => go("alerts")}>
              Pause it in Monitor
            </button>{" "}
            before asking a visual question.
          </div>
        )}
        {step === "track" && (
          <div className={styles.tip}>
            <IconFocus2 size={21} />
            <div>
              <strong>
                Play a clip → Inspect detected objects → Check the track ID
              </strong>
              <p>
                {props.searchByImageEnabled
                  ? "Your search results stay here. Inspect the recorded boxes and track IDs. The optional Find similar action needs indexed object embeddings as well as detector metadata."
                  : "Visual object search is not configured on this deployment. You can still review clips and search using words."}
              </p>

            </div>
          </div>
        )}
        {step === "alerts" && (
          <div className={styles.tip}>
            <IconBell size={21} />
            <div>
              <strong>
                Watch for a forklift, a person, or an obstructed aisle.
              </strong>
              <p>
                Resume an existing rule or create one below. Wait for a real
                match, then pause the rule and move to Review.
              </p>
            </div>
            <button type="button" onClick={() => go("evidence")}>
              Review matches <IconArrowRight size={16} />
            </button>
          </div>
        )}
        <div className={styles.tool}>
          {/* Keep the same desk mounted through Watch/Ask and later chapters: no lost answer or renewed capture warm-up. */}
          <div hidden={step !== "watch" && step !== "ask"}>
            <LiveDemoWorkspace
              streams={[source]}
              analysisById={{ [source.streamId]: analysis }}
              guidePhase={step === "watch" ? "watch" : "ask"}
              guideWatchPanel={
                <aside
                  className={styles.overview}
                  aria-label="Real camera processing status"
                >
                  <div className={styles.path}>
                    <div>
                      <span>
                        <IconCamera size={21} />
                      </span>
                      <div>
                        <strong>Your camera</strong>
                        <small>
                          RTSP ·{" "}
                          {source.connectionState === "online"
                            ? "Video I/O reports online"
                            : source.connectionState === "offline"
                            ? "Video I/O reports offline"
                            : "Connection unconfirmed"}
                        </small>
                      </div>
                    </div>
                    <div>
                      <span>
                        <IconCpu size={21} />
                      </span>
                      <div>
                        <strong>Local intelligence</strong>
                        <small>
                          {props.visualAnalystAvailable === true
                            ? "Visual AI available"
                            : props.visualAnalystAvailable === false
                            ? "Visual AI unavailable"
                            : "Checking visual AI"}
                        </small>
                      </div>
                    </div>
                    <div>
                      <span>
                        <IconSearch size={21} />
                      </span>
                      <div>
                        <strong>Searchable history</strong>
                        <small>{indexLabel}</small>
                      </div>
                    </div>
                  </div>
                  <div className={styles.index}>
                    <strong>
                      {intelligence?.semanticSegments?.toLocaleString() ?? "—"}
                    </strong>
                    <span>indexed video segments</span>
                    <small>
                      {statusError
                        ? "Index status unavailable"
                        : indexingTime
                        ? `Searchable through ${indexingTime}`
                        : "Awaiting index coverage"}
                    </small>
                  </div>
                  <p className={styles.try}>
                    Explore the activity in view.
                    <br />
                    Ask a question or search recent footage.
                  </p>
                  {(analysis !== "active" ||
                    intelligence?.semanticFresh === false) && (
                    <button
                      type="button"
                      onClick={() => props.onOpenLive(source)}
                    >
                      Check camera analysis <IconArrowRight size={15} />
                    </button>
                  )}
                  <details>
                    <summary>Source connection</summary>
                    <code>{source.url}</code>
                    <p>
                      Indexed segments are video intervals, not a count of
                      people. Recording enables questions and replay; indexing
                      enables search.
                    </p>
                  </details>
                </aside>
              }
              onExplore={(query) => {
                setSearchRequest({ camera: source, query });
                go("search");
              }}
              onOpenEvents={() => go("evidence")}
              onOpenRules={() => go("alerts")}
              onOpenLive={props.onOpenLive}
              vstApiUrl={props.vstApiUrl}
              visualAnalystAvailable={props.visualAnalystAvailable}
            />
          </div>
          {openedSearch && (
            <div hidden={!inSearch}>
              <InvestigateWorkspace
                isActive={inSearch}
                initialRequest={searchRequest}
                suggestedQueries={queries}
                initialTimeRange="15m"
                objectActionLabel="Inspect detected objects"
                agentApiUrl={props.agentApiUrl}
                mdxWebApiUrl={props.mdxWebApiUrl}
                searchByImageEnabled={props.searchByImageEnabled}
                vstApiUrl={props.vstApiUrl}
              />
            </div>
          )}
          {step === "alerts" && (
            <AlertRulesWorkspace
              source={source}
              onManageSources={props.onOpenSystem}
              vstApiUrl={props.vstApiUrl}
            />
          )}
          {step === "evidence" && (
            <ActivityInsightsWorkspace
              source={source}
              initialMode={eventsMode}
              onModeChange={(mode) =>
                mode === "live" ? go("watch") : setEventsMode(mode)
              }
              onOpenRules={() => go("alerts")}
              vstApiUrl={props.vstApiUrl}
            />
          )}
        </div>
        <footer className={styles.footer}>
          <div>
            <chapter.icon size={22} />
            <span>
              <strong>
                {index === 5
                  ? "The whole story, in real footage."
                  : `Next: ${chapters[
                      index + 1
                    ].label.toLowerCase()} the video.`}
              </strong>
              <small>
                {index === 5
                  ? "Watch → ask → find → follow → monitor → review."
                  : chapters[index + 1].description}
              </small>
            </span>
          </div>
          {index < 5 ? (
            <button type="button" onClick={() => go(chapters[index + 1].id)}>
              Continue to {chapters[index + 1].label}{" "}
              <IconArrowRight size={18} />
            </button>
          ) : (
            <div className={styles.finish}>
              <button type="button" onClick={() => go("watch")}>
                Back to the live scene <IconArrowRight size={18} />
              </button>
              <button type="button" onClick={props.onOpenExplainer}>
                Explore how it works
              </button>
            </div>
          )}
        </footer>
      </div>
    </div>
  );
}
