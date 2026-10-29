// SPDX-License-Identifier: MIT

import { LocalVisionLauncher } from "./LocalVisionLauncher";
import { CityDiorama } from "./smart-city/CityDiorama";
import { CityStoryMotionStyles, useCityStoryMotion } from "./smart-city/CityStoryMotion";
import s from "./smart-city/SmartCityStory.module.css";
import {
  cityDemoBeats as beats,
  cityDemoGroups as groups,
} from "./smart-city/cityDemoStory";
import type { SystemHealth } from "./systemHealth";
import {
  IconArrowDown,
  IconPlayerPlay,
  IconPlayerPause,
  IconArrowLeft,
  IconArrowRight,
} from "@tabler/icons-react";
import React, { useCallback, useEffect, useRef, useState } from "react";

const clamp = (value: number) => Math.max(0, Math.min(1, value));
type Props = {
  embedded?: boolean;
  onOpenDemo: () => void;
  onOpenGeneral: () => void;
  systemHealth: SystemHealth | null;
};

export function SmartCityStoryWorkspace({
  embedded = false,
  onOpenDemo,
  onOpenGeneral,
  systemHealth,
}: Props) {
  const root = useRef<HTMLDivElement>(null);
  const rail = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const nav = useRef<HTMLElement>(null);
  const [active, setActive] = useState(0);
  const transitionTo = useCityStoryMotion(setActive, canvas);
  const [tourPlaying, setTourPlaying] = useState(false);
  const activeRef = useRef(0);
  const stepHeight = useRef(600);
  const scrollContainer = useCallback(() => {
    const el = root.current;
    return embedded ? el?.closest<HTMLElement>("[data-city-scroll]") : el;
  }, [embedded]);
  const storyStart = useCallback((container: HTMLElement, el: HTMLElement) =>
    embedded
      ? el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
      : 0, [embedded]);
  const scrollToChapter = useCallback((index: number, behavior: ScrollBehavior) => {
    const el = root.current;
    const container = scrollContainer();
    if (!el || !container) return;
    container.scrollTo({ top: storyStart(container, el) + index * stepHeight.current, behavior });
  }, [scrollContainer, storyStart]);
  const go = (index: number) => {
    setTourPlaying(false);
    const next = Math.max(0, Math.min(beats.length - 1, index));
    // Jump the scroll position; animate the selected scenes, not intervening chapters.
    scrollToChapter(next, "auto");
  };
  useEffect(() => {
    const el = root.current;
    const container = scrollContainer();
    if (!el || !container) return;
    let frame = 0;
    let previousHeight = 0;
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
      const navHeight = nav.current?.offsetHeight ?? 56;
      const height = Math.max(1, container.clientHeight - navHeight);
      const start = storyStart(container, el);
      // Keep the reader at the same point when the panel or viewport resizes.
      if (previousHeight && previousHeight !== height && container.scrollTop >= start) {
        const position = (container.scrollTop - start) / previousHeight;
        rail.current?.style.setProperty("--step-height", `${height}px`);
        container.scrollTop = start + position * height;
      }
      previousHeight = container.clientHeight > 0 ? height : 0;
      stepHeight.current = height;
      el.style.setProperty("--nav-height", `${navHeight}px`);
      rail.current?.style.setProperty("--step-height", `${height}px`);
      const progress = Math.max(
        0,
        Math.min(beats.length - 1, (container.scrollTop - start) / height)
      );
      const index = Math.min(beats.length - 1, Math.floor(progress + 0.15));
      const reduced = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
      ).matches;
      const p = reduced ? index : progress;
      const properties: Record<string, number> = {
        "--travel": p,
        "--progress": progress / (beats.length - 1),
        "--intro": 1 - clamp((p - 0.15) / 0.6),
        "--camera": clamp((p - 0.25) / 0.6),
        "--detect": clamp((p - 1.45) / 0.5),
        "--tracking": clamp((p - 2.45) / 0.5),
        "--split": clamp((p - 3.35) / 0.6),
        "--locate": clamp((p - 3.5) / 0.5),
        "--zone": clamp((p - 4.45) / 0.5),
        "--duration": clamp((p - 5.15) / 0.8),
        "--explain": clamp((p - 6.45) / 0.5),
        "--review": clamp((p - 7.45) / 0.5),
        "--edge": clamp((p - 11.4) / 0.55),
      };
      Object.entries(properties).forEach(([key, value]) =>
        stage.current?.style.setProperty(key, String(value))
      );
      el.style.setProperty("--progress", String(progress / (beats.length - 1)));
      if (index !== activeRef.current) {
        activeRef.current = index;
        transitionTo(index);
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    container.addEventListener("scroll", schedule, { passive: true });
    const observer = new ResizeObserver(schedule);
    observer.observe(container);
    if (embedded) observer.observe(el);
    if (nav.current) observer.observe(nav.current);
    const bottomNav = document.querySelector(".vi-side-nav");
    if (bottomNav) observer.observe(bottomNav);
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    motion.addEventListener("change", schedule);
    measure();
    return () => {
      container.removeEventListener("scroll", schedule);
      observer.disconnect();
      motion.removeEventListener("change", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [embedded, scrollContainer, storyStart, transitionTo]);
  useEffect(() => {
    if (stage.current && window.matchMedia("(max-width: 700px)").matches) stage.current.scrollTop = 0;
  }, [active]);
  useEffect(() => {
    if (!tourPlaying) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motion.matches || document.hidden) {
      setTourPlaying(false);
      return;
    }
    const pause = () => setTourPlaying(false);
    const hide = () => {
      if (document.hidden) pause();
    };
    const advance = window.setTimeout(
      () => {
        scrollToChapter((active + 1) % beats.length, "auto");
      },
      [5, 6, 7].includes(active) ? 8500 : [0, 1, 2, 3, 4, 9, 10, 11, 12].includes(active) ? 6000 : 4500
    );
    document.addEventListener("visibilitychange", hide);
    motion.addEventListener("change", pause);
    return () => {
      window.clearTimeout(advance);
      document.removeEventListener("visibilitychange", hide);
      motion.removeEventListener("change", pause);
    };
  }, [tourPlaying, active, scrollToChapter]);
  const platform = systemHealth?.hardwareProfile;
  const actual =
    platform === "DGX-SPARK"
      ? "DGX Spark"
      : platform === "IGX-THOR"
      ? "IGX Thor"
      : ["JETSON-THOR", "AGX-THOR", "THOR"].includes(platform ?? "")
      ? "Jetson Thor"
      : null;

  return (
    <div
      ref={root}
      className={`${s.scroll}${embedded ? ` ${s.embedded}` : ""}`}
      data-testid="smart-city-story"
      data-active-chapter={active}
      data-playing={tourPlaying}
      onWheel={() => setTourPlaying(false)}
      onTouchStart={() => setTourPlaying(false)}
      tabIndex={0}
      aria-label="Continuous Smart City story. Scroll or use left and right arrow keys."
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
          setTourPlaying(false);
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
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          go(active + (event.key === "ArrowRight" ? 1 : -1));
        }
      }}
    >
      <CityStoryMotionStyles />
      <nav ref={nav} className={s.nav} aria-label="Smart City story chapters">
        <button
          type="button"
          className={s.tour}
          aria-pressed={tourPlaying}
          onClick={() => setTourPlaying(!tourPlaying)}
        >
          {tourPlaying ? (
            <IconPlayerPause size={15} />
          ) : (
            <IconPlayerPlay size={15} />
          )}
          {tourPlaying ? "Pause story" : "Play story"}
        </button>
        <div>
          {groups.map(([name, index], i) => (
            <button
              type="button"
              key={name}
              aria-current={
                active >= index &&
                (i === groups.length - 1 || active < groups[i + 1][1])
                  ? "step"
                  : undefined
              }
              onClick={() => go(index)}
            >
              {name}
            </button>
          ))}
        </div>
        <LocalVisionLauncher className={s.general} />
        <button type="button" className={s.general} onClick={onOpenGeneral}>
          General VSS
          <IconArrowRight size={14} />
        </button>
      </nav>
      <div
        ref={rail}
        className={s.rail}
        style={{ height: `calc(var(--step-height, 650px) * ${beats.length})` }}
      >
        <div
          ref={stage}
          className={s.stage}
          data-step={active}
          data-showcase={active >= 5 && active <= 8 ? "true" : undefined}
        >
          <div ref={canvas} className={s.canvas} style={{ viewTransitionName: "city-story-scene" } as React.CSSProperties}>
            <CityDiorama
              active={active}
              beat={beats[active]}
              onInteract={() => setTourPlaying(false)}
            />
          </div>
          <div className={s.insight}>
            <span>{beats[active][3]}</span>
            {active === beats.length - 1 && (
              <button type="button" onClick={onOpenDemo}>
                {embedded ? "Back to live view" : "Open Smart City"}
                <IconArrowRight size={17} />
              </button>
            )}
          </div>
          <footer className={s.controls}>
            <button
              type="button"
              disabled={active === 0}
              aria-label="Previous city story step"
              onClick={() => go(active - 1)}
            >
              <IconArrowLeft size={18} />
            </button>
            <div className={s.dots}>
              {beats.map((beat, i) => (
                <button
                  type="button"
                  key={beat[0]}
                  aria-label={`Step ${i + 1}: ${beat[1]}`}
                  aria-current={i === active ? "step" : undefined}
                  title={beat[1]}
                  onClick={() => go(i)}
                />
              ))}
            </div>
            <span className={s.counter}>
              {String(active + 1).padStart(2, "0")} / {beats.length}
            </span>
            <button
              type="button"
              onClick={() =>
                active === beats.length - 1 ? onOpenDemo() : go(active + 1)
              }
            >
              {active === beats.length - 1 ? (embedded ? "Back to live view" : "Open workspace") : "Next step"}
              <IconArrowDown size={16} />
            </button>
          </footer>
          <div className={s.disclosure}>
            Digital twin: DGX Spark · Analytics target: Anvil T5 · Illustrated workflow
            {active === beats.length - 1 && actual
              ? ` · current host: ${actual}`
              : ""}
          </div>
        </div>
      </div>
    </div>
  );
}
