// SPDX-License-Identifier: MIT

import type { CapabilitiesWorkspaceProps } from "./CapabilitiesWorkspace";
import { industryBeats, VssIndustryScene } from "./VssIndustryScenes";
import s from "./VssStoryWorkspace.module.css";
import {
  IconArrowDown,
  IconArrowLeft,
  IconArrowRight,
  IconSearch,
  IconMessageCircle,
  IconBell,
} from "@tabler/icons-react";
import React, { useEffect, useRef, useState } from "react";

const beats = [
  [
    "The big picture",
    "Your cameras. Intelligence on site.",
    "VSS turns camera footage into searchable moments, answers and alerts — processed on site.",
  ],
  [
    "01 / Capture",
    "Start with a moment.",
    "A person carries a box across the receiving floor.",
  ],
  [
    "02 / Embed",
    "Give that moment a fingerprint.",
    "Cosmos Embed gives the clip a pattern of numbers called an embedding. Similar scenes get similar patterns.",
  ],
  [
    "03 / Remember",
    "Keep it ready to find.",
    "Store that fingerprint with the camera, time and a reference to the footage.",
  ],
  [
    "04 / Search",
    "Now, ask for what you want.",
    "Cosmos Embed turns your words into a pattern it can compare with the video.",
  ],
  [
    "05 / Match",
    "Similar meaning. A moment to inspect.",
    "Compare the two patterns. Retrieve a likely match, then check the original footage.",
  ],
  [
    "06 / Detect",
    "Another layer: see the person.",
    "Alongside search, a detector finds objects and marks where they are.",
  ],
  [
    "07 / Track",
    "Follow them through the scene.",
    "The same track ID connects the person’s positions within this camera.",
  ],
  [
    "08 / Explore",
    "Use a sighting to find more.",
    "With object embeddings enabled, compare appearance to find related footage.",
  ],
  [
    "09 / Ask",
    "Ask about what you see.",
    "A visual model inspects the selected footage to answer your question.",
  ],
  [
    "10 / Summarize",
    "Turn a period into a short account.",
    "Turn footage into a history of visual observations. AI then summarizes the selected period.",
  ],
  [
    "11 / Define",
    "Tell it what matters.",
    "Choose a camera and describe a visual condition to watch for.",
  ],
  [
    "12 / Evaluate",
    "Check the footage for that condition.",
    "A visual model checks samples from the camera: is someone carrying a box?",
  ],
  [
    "13 / Review",
    "Bring the evidence to an operator.",
    "Keep the camera, time and footage together so a person can verify what happened.",
  ],
  ...industryBeats,
] as const;
const groups = [
  ["Overview", 0],
  ["Search", 1],
  ["Tracking", 6],
  ["Ask", 9],
  ["Alerts", 11],
  ["In practice", 14],
] as const;
function CameraIcon() {
  return (
    <svg viewBox="0 0 80 64" aria-hidden="true">
      <path
        d="m12 11 44 9-7 26-44-9z"
        fill="#243f36"
        stroke="#a8e4ce"
        strokeWidth="2"
      />
      <path
        d="m56 23 16-2-6 20-15-6M23 41l-4 12H8M19 53v6"
        fill="none"
        stroke="#a8e4ce"
        strokeWidth="3"
      />
      <circle cx="45" cy="31" r="5" fill="#9ee8cd" />
    </svg>
  );
}
function Fingerprint({ query = false }: { query?: boolean }) {
  return (
    <div
      className={s.fingerprint}
      aria-label={
        query ? "Text embedding illustration" : "Video embedding illustration"
      }
    >
      {[24, 45, 30, 66, 38, 83, 51, 30, 71, 42, 65, 35].map((h, i) => (
        <i
          key={i}
          style={{ height: `${h + (query ? ((i % 3) - 1) * 5 : 0)}%` }}
        />
      ))}
    </div>
  );
}
export function VssStoryWorkspace({ onOpenDemo, systemHealth }: CapabilitiesWorkspaceProps) {
  const processingHardware = systemHealth?.hardwareProfile === "DGX-SPARK"
    ? "DGX Spark"
    : systemHealth?.hardwareProfile === "IGX-THOR"
    ? "IGX Thor"
    : ["JETSON-THOR", "AGX-THOR", "THOR"].includes(systemHealth?.hardwareProfile || "")
    ? "Jetson Thor"
    : "configured local hardware";
  const root = useRef<HTMLDivElement>(null),
    track = useRef<HTMLDivElement>(null),
    stage = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const activeRef = useRef(0);
  const go = (i: number) => {
    const el = root.current;
    if (!el) return;
    el.scrollTo({
      top: Math.max(0, Math.min(beats.length - 1, i)) * (el.clientHeight - 56),
      behavior:
        window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
        Math.abs(i - activeRef.current) > 1
          ? "auto"
          : "smooth",
    });
  };
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const bottomNav = document.querySelector(".vi-side-nav");
      el.style.setProperty(
        "--bottom-nav",
        `${
          window.matchMedia("(max-width: 900px)").matches && bottomNav
            ? bottomNav.getBoundingClientRect().height
            : 0
        }px`
      );
      const height = Math.max(1, el.clientHeight - 56);
      const progress = Math.min(
        beats.length - 1,
        Math.max(0, el.scrollTop / height)
      );
      const index = Math.min(beats.length - 1, Math.floor(progress + 0.15));
      stage.current?.style.setProperty("--travel", String(progress));
      stage.current?.style.setProperty(
        "--beat",
        String(progress - Math.floor(progress))
      );
      stage.current?.style.setProperty(
        "--enter",
        String(Math.min(1, Math.max(0, (progress - index + 0.15) / 0.65)))
      );
      el.style.setProperty("--progress", String(progress / (beats.length - 1)));
      track.current?.style.setProperty("--step-height", `${height}px`);
      if (index !== activeRef.current) {
        activeRef.current = index;
        setActive(index);
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    el.addEventListener("scroll", schedule, { passive: true });
    const observer = new ResizeObserver(schedule);
    observer.observe(el);
    const bottomNav = document.querySelector(".vi-side-nav");
    if (bottomNav) observer.observe(bottomNav);
    measure();
    return () => {
      el.removeEventListener("scroll", schedule);
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  // Short viewports can scroll inside a scene; each new beat starts at its heading.
  useEffect(() => {
    if (stage.current) stage.current.scrollTop = 0;
  }, [active]);
  const embedding = active >= 2 && active <= 5;
  const tracking = active >= 6 && active <= 8;
  const ask = active === 9 || active === 10;
  const alerts = active >= 11 && active <= 13;
  return (
    <div
      ref={root}
      className={s.scroll}
      data-testid="vss-story"
      data-active-chapter={active}
      tabIndex={0}
      aria-label="Interactive VSS story. Scroll or use left and right arrow keys."
      onKeyDown={(event) => {
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
          return;
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          go(active + (event.key === "ArrowRight" ? 1 : -1));
        }
      }}
    >
      <nav className={s.nav} aria-label="VSS story chapters">
        <span>Inside VSS</span>
        <div>
          {groups.map(([name, index], i) => (
            <button
              key={name}
              onClick={() => go(index)}
              aria-current={
                active >= index &&
                (i === groups.length - 1 || active < groups[i + 1][1])
                  ? "step"
                  : undefined
              }
            >
              {name}
            </button>
          ))}
        </div>
        <span>
          {String(active + 1).padStart(2, "0")} / {beats.length}
        </span>
      </nav>
      <div
        ref={track}
        className={s.track}
        style={{ height: `calc(var(--step-height, 800px) * ${beats.length})` }}
      >
        <div
          ref={stage}
          className={s.stage}
          data-scene={active}
          data-industry-scene={active >= 14}
        >
          <header className={s.heading}>
            <span>{beats[active][0]}</span>
            <h1>{beats[active][1]}</h1>
            <p>{beats[active][2]}</p>
          </header>
          <div className={s.visual}>
            {active >= 14 && (
              <VssIndustryScene step={active - 14} onJump={go} />
            )}
            {active === 10 && (
              <div className={s.historyScene}>
                <div className={s.historyHeader}>
                  <CameraIcon />
                  <span>Receiving · selected period</span>
                </div>
                {[
                  ["00:00", "story-receiving.png", "Person carrying a box"],
                  [
                    "00:04",
                    "story-receiving-inside.png",
                    "Crosses the receiving floor",
                  ],
                  [
                    "00:08",
                    "story-receiving-after.png",
                    "Continues across the scene",
                  ],
                ].map(([time, image, caption], i) => (
                  <div
                    className={s.historyMoment}
                    key={time}
                    style={{ "--order": i } as React.CSSProperties}
                  >
                    <img src={`/vision/${image}`} alt={caption} />
                    <div>
                      <small>Clip {time}</small>
                      <strong>{caption}</strong>
                    </div>
                  </div>
                ))}
                <div className={s.historyReady}>
                  Prepared history <span>Observations linked to footage →</span>
                </div>
              </div>
            )}
            {active === 0 && (
              <div className={s.overview}>
                <div className={s.cameras}>
                  {[
                    ["Receiving", "story-receiving.png"],
                    ["Aisle", "story-aisle.png"],
                    ["Entrance", "story-entrance.png"],
                  ].map(([label, img]) => (
                    <div key={label}>
                      <CameraIcon />
                      <div>
                        <img
                          src={`/vision/${img}`}
                          alt={`${label} camera feed`}
                        />
                        <span>{label} camera</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className={s.feedLine}>
                  <span>Video feeds</span>
                  <i />
                </div>
                <div className={s.anvil}>
                  <img src="/vision/anvil-t5.png" alt="Connect Tech Anvil T5" />
                  <strong>Anvil T5</strong>
                  <span>AI stays on site</span>
                </div>
                <div className={s.feedLine}>
                  <i />
                </div>
                <div className={s.outcomes}>
                  {[
                    [IconSearch, "Find a moment", 1],
                    [IconMessageCircle, "Ask your video", 9],
                    [IconBell, "Spot an event", 11],
                  ].map(([Icon, label, index]) => {
                    const Component = Icon as typeof IconSearch;
                    return (
                      <button
                        key={String(label)}
                        onClick={() => go(Number(index))}
                      >
                        <Component size={22} />
                        <span>{String(label)}</span>
                        <IconArrowRight size={15} />
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div
              className={s.footage}
              aria-hidden={active === 0 || active === 10 || active >= 14}
            >
              <div className={s.cameraCaption}>
                <CameraIcon />
                <span>
                  Receiving camera <i /> <small>Illustrative footage</small>
                </span>
              </div>
              <div className={s.photo}>
                <img
                  aria-hidden={active === 7 || active === 8}
                  src="/vision/story-receiving.png"
                  alt="A person in an orange vest carries a box across a warehouse"
                />
                <img
                  aria-hidden={active !== 7 && active !== 8}
                  className={s.laterFrame}
                  src="/vision/story-receiving-inside.png"
                  alt="The same person further along the receiving floor"
                />
                {tracking && (
                  <div className={s.detection}>
                    <span>Person{active >= 7 ? " · 07" : ""}</span>
                  </div>
                )}
                {active === 7 && (
                  <div className={s.earlierPosition}>
                    <span>07 · earlier</span>
                  </div>
                )}
                {(active === 9 || active === 12 || active === 13) && (
                  <div className={s.evidenceFocus} aria-hidden="true" />
                )}
                {active === 7 && (
                  <svg
                    className={s.path}
                    viewBox="0 0 1000 563"
                    aria-hidden="true"
                  >
                    <path d="M680 307Q610 325 480 370" />
                  </svg>
                )}
                {active === 12 && (
                  <div className={s.inspect}>
                    Checking: person carrying a box
                  </div>
                )}
              </div>
              <span className={s.clipLabel}>
                {active === 7
                  ? "Same camera. Same track."
                  : "One moment · Camera 02"}
              </span>
            </div>
            {embedding && (
              <div className={s.embedScene}>
                {active === 2 && (
                  <div className={s.transform}>
                    <span>Cosmos Embed</span>
                    <div className={s.transfer}>⟶</div>
                  </div>
                )}
                <div className={s.stored}>
                  <div className={s.indexLayers}>
                    <i />
                    <i />
                  </div>
                  <div className={s.vector}>
                    <span>
                      {active === 2
                        ? "A visual fingerprint"
                        : "Saved video fingerprint"}
                    </span>
                    <Fingerprint />
                    <small>Camera 02 · Clip 00:00–00:08 · Footage ↗</small>
                  </div>
                  {active >= 3 && (
                    <span className={s.indexLabel}>Local video index</span>
                  )}
                </div>
                {active >= 4 && (
                  <div className={s.query}>
                    <span>You search</span>
                    <strong>“Person carrying a box”</strong>
                    <small>Cosmos Embed ↓</small>
                    <Fingerprint query />
                  </div>
                )}
                {active === 5 && (
                  <div className={s.compareLink}>
                    <span>Compare meaning</span>
                    <svg viewBox="0 0 80 70" aria-hidden="true">
                      <path d="M65 5V30H10M18 22 10 30 18 38M65 65V30" />
                    </svg>
                  </div>
                )}
                {active === 5 && (
                  <div className={s.match}>
                    <IconSearch size={19} />
                    <strong>Candidate found</strong>
                    <span>Inspect the original clip ↗</span>
                  </div>
                )}
              </div>
            )}
            {active === 8 && (
              <div className={s.related}>
                <span>Selected object</span>
                <strong>Person · 07</strong>
                <Fingerprint />
                <span>Compare object embeddings</span>
                <div className={s.relatedResult}>
                  <img
                    src="/vision/story-receiving-after.png"
                    alt="Illustrative related object sighting"
                  />
                  <b>Related footage</b>
                </div>
                <small>Similar appearance ≠ confirmed identity</small>
              </div>
            )}
            {ask && (
              <div className={s.conversation}>
                <div className={s.bubble}>
                  {active === 9
                    ? "What is this person carrying?"
                    : "Summarize the receiving activity."}
                </div>
                <div className={s.thinking}>
                  {active === 9
                    ? "Inspect footage → Cosmos Reason"
                    : "Visual observations → summary"}
                </div>
                <div className={s.response}>
                  <span>Illustrative answer</span>
                  <strong>
                    {active === 9
                      ? "A cardboard box."
                      : "A person crossed receiving carrying a box."}
                  </strong>
                  <small>Camera 02 · Selected clip 00:00–00:08</small>
                </div>
              </div>
            )}
            {alerts && (
              <div className={s.alert}>
                <span>
                  {active === 11
                    ? "Your rule"
                    : active === 12
                    ? "Evaluate sampled footage"
                    : "Event candidate"}
                </span>
                <IconBell size={28} />
                <strong>
                  {active === 13
                    ? "Person carrying a box observed"
                    : "Watch for someone carrying a box"}
                </strong>
                <div className={s.ruleCamera}>
                  <CameraIcon /> Receiving camera
                </div>
                {active === 11 && (
                  <span className={s.rulePill}>Condition defined</span>
                )}
                {active === 12 && (
                  <span className={s.rulePill}>Visible condition → match</span>
                )}
                {active === 13 && (
                  <div className={s.eventEvidence}>
                    <img
                      src="/vision/story-receiving.png"
                      alt="Footage supporting the event candidate"
                    />
                    <span>
                      Camera 02 · Clip 00:00–00:08
                      <br />
                      <b>Ready for operator review</b>
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
          <footer className={s.controls}>
            <button
              onClick={() => go(active - 1)}
              disabled={active === 0}
              aria-label="Previous story step"
            >
              <IconArrowLeft size={18} />
            </button>
            <div className={s.stepDots}>
              {beats.map((beat, i) => (
                <button
                  key={beat[0]}
                  onClick={() => go(i)}
                  aria-label={`Step ${i + 1}: ${beat[1]}`}
                  title={beat[1]}
                  aria-current={active === i ? "step" : undefined}
                />
              ))}
            </div>
            <button
              onClick={() => active === beats.length - 1 && onOpenDemo ? onOpenDemo() : go(active === beats.length - 1 ? 0 : active + 1)}
            >
              {active === beats.length - 1 ? onOpenDemo ? "Explore your video" : "Back to start" : "Next step"}
              <IconArrowDown size={16} />
            </button>
          </footer>
          <div className={s.disclosure}>
            {active >= 14
              ? "Illustrative industry workflows · site-specific configuration and validation required"
              : active === 0
              ? `Anvil illustrated · processing on ${processingHardware} · capacity depends on workload`
              : active === 8
              ? "Related-object search requires object embeddings."
              : active === 10
              ? "Summaries require prepared source history."
              : "Illustrative sequence and clip times · not live inference"}
          </div>
        </div>
      </div>
    </div>
  );
}
