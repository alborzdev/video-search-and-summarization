// SPDX-License-Identifier: MIT
import React, { useCallback, useEffect, useRef } from "react";
import { flushSync } from "react-dom";

type StoryTransition = {
  skipTransition: () => void;
  ready: Promise<void>;
  finished: Promise<void>;
};
type TransitionDocument = Document & {
  startViewTransition?: (update: () => void) => StoryTransition;
};

/** Keep the current scene mounted; browser snapshots provide the outgoing frame. */
export function useCityStoryMotion(
  setActive: (index: number) => void,
  canvas: React.RefObject<HTMLDivElement>
) {
  const pending = useRef<(() => void) | null>(null);
  const revision = useRef(0);
  useEffect(() => () => {
    revision.current += 1;
    pending.current?.();
  }, []);

  return useCallback((index: number) => {
    const current = ++revision.current;
    pending.current?.();
    pending.current = null;
    const commit = () => {
      if (current === revision.current) flushSync(() => setActive(index));
    };
    const el = canvas.current;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || document.hidden || !el) {
      setActive(index);
      return;
    }
    const doc = document as TransitionDocument;
    if (doc.startViewTransition) {
      const transition = doc.startViewTransition(commit);
      pending.current = () => transition.skipTransition();
      // Rapid navigation legitimately skips a snapshot; the latest update still wins.
      void transition.ready.catch(() => {});
      void transition.finished.catch(() => {});
      return;
    }
    // Older browsers use a short fade-through rather than cutting between scenes.
    if (!el.animate) {
      setActive(index);
      return;
    }
    let animation = el.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: 160, easing: "ease-out", fill: "forwards",
    });
    pending.current = () => animation.cancel();
    void animation.finished.then(() => {
      if (current !== revision.current) return;
      commit();
      animation.cancel();
      animation = el.animate([
        { opacity: 0, transform: "translateY(12px)" },
        { opacity: 1, transform: "translateY(0)" },
      ], { duration: 560, easing: "cubic-bezier(.22,1,.36,1)" });
      return animation.finished;
    }).catch(() => {});
  }, [canvas, setActive]);
}

// Named snapshots animate only the explainer; the application shell stays still.
export function CityStoryMotionStyles() {
  return <style>{`
    ::view-transition { pointer-events: none; }
    ::view-transition-group(root),
    ::view-transition-old(root),
    ::view-transition-new(root) { animation: none; }
    ::view-transition-group(city-story-scene),
    ::view-transition-group(city-story-copy) {
      animation-duration: 720ms;
      animation-timing-function: cubic-bezier(.22,1,.36,1);
    }
    ::view-transition-old(city-story-scene) {
      animation: city-scene-leave 500ms cubic-bezier(.4,0,.2,1) both;
    }
    ::view-transition-new(city-story-scene) {
      animation: city-scene-enter 720ms cubic-bezier(.22,1,.36,1) both;
    }
    ::view-transition-old(city-story-copy) {
      animation: city-copy-leave 220ms ease-out both;
    }
    ::view-transition-new(city-story-copy) {
      animation: city-copy-enter 560ms 120ms cubic-bezier(.22,1,.36,1) both;
    }
    ::view-transition-group(city-record-queue),
    ::view-transition-group(city-record-direction),
    ::view-transition-group(city-record-emergency),
    ::view-transition-group(city-event-queue),
    ::view-transition-group(city-event-direction),
    ::view-transition-group(city-event-emergency) {
      animation-duration: 1000ms;
      animation-timing-function: cubic-bezier(.22,.8,.2,1);
    }
    ::view-transition-group(city-story-twin),
    ::view-transition-group(city-story-spark) {
      animation-duration: 1100ms;
      animation-timing-function: cubic-bezier(.3,.8,.2,1);
    }
    ::view-transition-old(city-story-twin),
    ::view-transition-new(city-story-twin),
    ::view-transition-old(city-story-spark),
    ::view-transition-new(city-story-spark) {
      animation-duration: 1100ms;
      height: 100%;
      width: 100%;
      object-fit: contain;
    }
    /* The device is the same image in both scenes: move it without dissolving. */
    ::view-transition-new(city-story-spark) {
      animation: none;
      mix-blend-mode: normal;
    }
    /* Remove the old card before the shared device leaves it. Its snapshot is
       separate so scene scaling cannot drag or ghost the border. */
    ::view-transition-group(city-story-spark-card) { animation: none; z-index: 3; }
    ::view-transition-group(city-story-spark) { z-index: 4; }
    ::view-transition-old(city-story-spark-card) {
      animation: city-card-leave 180ms ease-out both;
      mix-blend-mode: normal;
    }
    ::view-transition-new(city-story-spark-card) {
      animation: city-card-enter 300ms 650ms ease-out both;
      mix-blend-mode: normal;
    }
    @keyframes city-card-leave { to { opacity: 0; } }
    @keyframes city-card-enter { from { opacity: 0; } to { opacity: 1; } }
    ::view-transition-image-pair(city-story-scene),
    ::view-transition-image-pair(city-story-copy) { isolation: auto; }
    ::view-transition-old(city-story-scene),
    ::view-transition-new(city-story-scene),
    ::view-transition-old(city-story-copy),
    ::view-transition-new(city-story-copy) { mix-blend-mode: normal; }
    @keyframes city-scene-leave {
      to { opacity: 0; transform: translateY(-10px) scale(.992); }
    }
    @keyframes city-scene-enter {
      from { opacity: 0; transform: translateY(18px) scale(1.012); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    @keyframes city-copy-leave { to { opacity: 0; transform: translateY(-6px); } }
    @keyframes city-copy-enter {
      from { opacity: 0; transform: translateY(14px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      ::view-transition-group(*), ::view-transition-old(*), ::view-transition-new(*) {
        animation: none !important;
      }
    }
  `}</style>;
}
