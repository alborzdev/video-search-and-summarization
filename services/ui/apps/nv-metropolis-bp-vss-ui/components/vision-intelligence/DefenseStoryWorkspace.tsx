// SPDX-License-Identifier: MIT

import { DefenseDiorama } from "./defense/DefenseDiorama";
import s from "./defense/DefenseStory.module.css";
import { defenseWorldFrame } from "./defense/defenseDioramaMotion";
import {
  defenseBeats as beats,
  defenseGroups as groups,
} from "./defense/defenseStory";
import type { SystemHealth } from "./systemHealth";
import {
  IconArrowLeft,
  IconArrowRight,
  IconPlayerPlay,
  IconPlayerPause,
  IconCamera,
  IconDrone,
  IconTruck,
} from "@tabler/icons-react";
import React, { useEffect, useRef, useState } from "react";

const missions = [
  {
    name: "Airfield recovery",
    job: "Find damage",
    image: "damage.png",
    input: "Drone camera",
    location: "At the ground station",
    output: "Finding + source image",
    process: "Locate the finding. Outline it. Save the evidence.",
    index: 1,
    icon: IconDrone,
  },
  {
    name: "Site watch",
    job: "Focus the watch",
    image: "site.png",
    input: "Site IP cameras",
    location: "On the local site network",
    output: "Entry event + camera",
    process: "Detect. Track. Apply the entry rule.",
    index: 3,
    icon: IconCamera,
  },
  {
    name: "Vehicle visibility",
    job: "Reveal the blind spot",
    image: "vehicle.png",
    input: "Vehicle GMSL cameras",
    location: "Inside the vehicle",
    output: "Person cue + rear view",
    process: "Process the views. Highlight the person.",
    index: 5,
    icon: IconTruck,
  },
] as const;
function missionIndex(active: number) {
  return active < 3 ? 0 : active < 5 ? 1 : 2;
}
function HardwareFlow({ active }: { active: number }) {
  const m = missions[missionIndex(active)];
  const general = active === 0 || active >= 7;
  return (
    <div className={s.hardwareFlow} aria-label="Camera to Anvil to operator">
      <div className={s.flowInput}>
        <IconCamera size={25} />
        <div>
          <small>01 / CAMERA INPUT</small>
          <strong>{general ? "Drone · Site · Vehicle" : m.input}</strong>
          <span>
            {general
              ? "See the work as it happens"
              : active < 3
              ? "Video downlink to the ground"
              : active < 5
              ? "Video over the local network"
              : "Cameras mounted around the vehicle"}
          </span>
        </div>
      </div>
      <IconArrowRight className={s.flowArrow} size={22} />
      <div className={s.flowCompute}>
        <img src="/vision/anvil-t5.png" alt="Connect Tech Anvil-T5" />
        <div>
          <small>02 / CONNECT TECH ANVIL-T5</small>
          <strong>{general ? "Run AI beside the cameras" : m.location}</strong>
          <span>
            {general
              ? "Camera input · Local inference · Local evidence"
              : m.process}
          </span>
        </div>
      </div>
      <IconArrowRight className={s.flowArrow} size={22} />
      <div className={s.flowOutput}>
        <small>03 / OPERATOR OUTPUT</small>
        <strong>{general ? "A result you can act on" : m.output}</strong>
        <span>Review the source. Decide the next action.</span>
      </div>
    </div>
  );
}
export function DefenseStoryWorkspace({
  onOpenDemo,
  onOpenGeneral,
  systemHealth,
}: {
  onOpenDemo: () => void;
  onOpenGeneral: () => void;
  systemHealth: SystemHealth | null;
}) {
  const root = useRef<HTMLDivElement>(null),
    rail = useRef<HTMLDivElement>(null),
    stage = useRef<HTMLDivElement>(null),
    nav = useRef<HTMLElement>(null);
  const activeRef = useRef(0),
    stepHeight = useRef(600);
  const [active, setActive] = useState(0),
    [playing, setPlaying] = useState(false);
  const go = (index: number) => {
    setPlaying(false);
    const next = Math.max(0, Math.min(beats.length - 1, index));
    root.current?.scrollTo({
      top: next * stepHeight.current,
      behavior:
        window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
        Math.abs(next - activeRef.current) > 1
          ? "auto"
          : "smooth",
    });
  };
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let frame = 0,
      previousHeight = 0,
      previousProgress = 0;
    const measure = () => {
      frame = 0;
      const bottom = document.querySelector(".vi-side-nav");
      const navHeight = nav.current?.offsetHeight ?? 56;
      const height = Math.max(1, el.clientHeight - navHeight);
      el.style.setProperty(
        "--bottom-nav",
        `${
          window.matchMedia("(max-width: 900px)").matches && bottom
            ? bottom.getBoundingClientRect().height
            : 0
        }px`
      );
      if (previousHeight && previousHeight !== height)
        el.scrollTop = previousProgress * height;
      previousHeight = el.clientHeight > 0 ? height : 0;
      stepHeight.current = height;
      el.style.setProperty("--nav-height", `${navHeight}px`);
      rail.current?.style.setProperty("--step-height", `${height}px`);
      const progress = Math.max(
        0,
        Math.min(beats.length - 1, el.scrollTop / height)
      );
      previousProgress = progress;
      const reduced = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
      ).matches;
      const world = defenseWorldFrame(
        reduced ? Math.floor(progress + 0.15) : progress
      );
      stage.current?.style.setProperty("--world-scale", String(world.scale));
      stage.current?.style.setProperty("--world-x", `${world.x}px`);
      stage.current?.style.setProperty("--world-y", `${world.y}px`);
      el.style.setProperty("--progress", String(progress / (beats.length - 1)));
      const next = Math.min(beats.length - 1, Math.floor(progress + 0.15));
      if (next !== activeRef.current) {
        activeRef.current = next;
        setActive(next);
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(el);
    if (nav.current) observer.observe(nav.current);
    const bottom = document.querySelector(".vi-side-nav");
    if (bottom) observer.observe(bottom);
    el.addEventListener("scroll", schedule, { passive: true });
    measure();
    return () => {
      observer.disconnect();
      el.removeEventListener("scroll", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  useEffect(() => {
    if (stage.current) stage.current.scrollTop = 0;
  }, [active]);
  useEffect(() => {
    if (!playing) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motion.matches || document.hidden) {
      setPlaying(false);
      return;
    }
    const stop = () => setPlaying(false),
      hide = () => {
        if (document.hidden) stop();
      };
    const timer = window.setTimeout(
      () =>
        root.current?.scrollTo({
          top: ((active + 1) % beats.length) * stepHeight.current,
          behavior: "smooth",
        }),
      active === 0 || active === 8 ? 9000 : 7500
    );
    document.addEventListener("visibilitychange", hide);
    motion.addEventListener("change", stop);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", hide);
      motion.removeEventListener("change", stop);
    };
  }, [playing, active]);
  const beat = beats[active];
  return (
    <div
      ref={root}
      className={s.scroll}
      data-testid="defense-story"
      data-active-chapter={active}
      data-playing={playing}
      tabIndex={0}
      aria-label="Defense story. Scroll or use arrow keys."
      onWheel={() => setPlaying(false)}
      onTouchStart={() => setPlaying(false)}
      onKeyDown={(event) => {
        if (
          [
            "ArrowRight",
            "ArrowLeft",
            "PageDown",
            "PageUp",
            "Home",
            "End",
            " ",
          ].includes(event.key)
        )
          setPlaying(false);
        if (
          (event.target as HTMLElement).closest(
            "button,input,textarea,select,a"
          ) ||
          event.altKey ||
          event.ctrlKey ||
          event.metaKey ||
          event.shiftKey
        )
          return;
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
            ? beats.length - 1
            : ["ArrowRight", "PageDown"].includes(event.key)
            ? active + 1
            : ["ArrowLeft", "PageUp"].includes(event.key)
            ? active - 1
            : null;
        if (next !== null) {
          event.preventDefault();
          go(next);
        }
      }}
    >
      <nav ref={nav} className={s.nav} aria-label="Defense story chapters">
        <button
          className={s.play}
          aria-pressed={playing}
          onClick={() => setPlaying(!playing)}
        >
          {playing ? (
            <IconPlayerPause size={15} />
          ) : (
            <IconPlayerPlay size={15} />
          )}{" "}
          {playing ? "Pause story" : "Play story"}
        </button>
        <div className={s.chapters}>
          {groups.map(([label, index], i) => (
            <button
              key={label}
              aria-current={
                active >= index &&
                (i === groups.length - 1 || active < groups[i + 1][1])
                  ? "step"
                  : undefined
              }
              onClick={() => go(index)}
            >
              {label}
            </button>
          ))}
        </div>
        <button className={s.exit} onClick={onOpenDemo}>
          Defense workspace <IconArrowRight size={15} />
        </button>
      </nav>
      <div
        ref={rail}
        className={s.rail}
        style={{ height: `calc(var(--step-height, 650px) * ${beats.length})` }}
      >
        <div ref={stage} className={s.stage} data-step={active}>
          <div className={s.sceneMain}>
            <DefenseDiorama
              active={active}
              go={go}
              pause={() => setPlaying(false)}
              onOpenDemo={onOpenDemo}
            />
          </div>
          <HardwareFlow active={active} />
          <div className={s.insight}>{beat.detail}</div>
          <footer className={s.controls}>
            <button
              disabled={active === 0}
              aria-label="Previous defense story step"
              onClick={() => go(active - 1)}
            >
              <IconArrowLeft size={18} />
            </button>
            <div className={s.dots}>
              {beats.map((item, i) => (
                <button
                  key={item.label}
                  aria-current={i === active ? "step" : undefined}
                  aria-label={`Step ${i + 1}: ${item.title.replace("\n", " ")}`}
                  title={item.title.replace("\n", " ")}
                  onClick={() => go(i)}
                />
              ))}
            </div>
            <span>
              {String(active + 1).padStart(2, "0")} / {beats.length}
            </span>
            <button
              onClick={() =>
                active === beats.length - 1 ? go(0) : go(active + 1)
              }
            >
              {active === beats.length - 1 ? "Replay story" : "Next step"}{" "}
              <IconArrowRight size={16} />
            </button>
          </footer>
          <div className={s.disclosure}>
            <span>
              Illustrated workflow · sample events
              {active === 2 ? " · recorded mask from local inference" : ""}
              {active === 8 && systemHealth?.hardwareProfile
                ? ` · current host: ${systemHealth.hardwareProfile}`
                : ""}
            </span>
            <button onClick={onOpenGeneral}>
              Inside VSS <IconArrowRight size={12} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
