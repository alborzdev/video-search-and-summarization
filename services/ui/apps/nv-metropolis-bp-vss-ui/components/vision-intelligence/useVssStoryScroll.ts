import { useCallback, useEffect, useRef, useState } from 'react';

const COMPACT_QUERY = '(max-width: 1000px), (max-height: 650px)';
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const clamp = (value: number, lower: number, upper: number) => Math.min(upper, Math.max(lower, value));

/** Native scrolling inside the explainer's own viewport; no wheel interception. */
export function useVssStoryScroll(chapterCount = 4) {
  const rootRef = useRef<HTMLDivElement>(null);
  const storyRef = useRef<HTMLElement>(null);
  const stepRefs = useRef<Array<HTMLElement | null>>([]);
  const [active, setActive] = useState(0);
  const activeRef = useRef(0);
  const [compact, setCompact] = useState(false);
  const compactRef = useRef(false);
  const reducedMotionRef = useRef(false);
  const scheduleRef = useRef<(() => void) | null>(null);

  const scrollToElement = useCallback((element: HTMLElement | null) => {
    const root = rootRef.current;
    if (!root || !element) return;
    const rootBox = root.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    const top = root.scrollTop + box.top - rootBox.top - root.clientTop;
    root.scrollTo({
      top: clamp(top - 56, 0, Math.max(0, root.scrollHeight - root.clientHeight)),
      behavior: reducedMotionRef.current ? 'auto' : 'smooth',
    });
  }, []);

  const jumpTo = useCallback((index: number) => {
    const root = rootRef.current;
    const element = stepRefs.current[clamp(Math.round(index), 0, chapterCount - 1)];
    if (!root || !element) return;
    if (compactRef.current) {
      scrollToElement(element);
      return;
    }
    const rootBox = root.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    const center = root.scrollTop + box.top - rootBox.top - root.clientTop + box.height / 2;
    root.scrollTo({
      top: clamp(center - root.clientHeight / 2, 0, Math.max(0, root.scrollHeight - root.clientHeight)),
      behavior: reducedMotionRef.current ? 'auto' : 'smooth',
    });
  }, [scrollToElement, chapterCount]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const compactMedia = window.matchMedia(COMPACT_QUERY);
    const motionMedia = window.matchMedia(REDUCED_MOTION_QUERY);
    let frame: number | null = null;
    let disposed = false;

    const measure = () => {
      frame = null;
      if (disposed) return;
      const viewport = root.getBoundingClientRect();
      const center = root.scrollTop + root.clientHeight / 2;
      const centers = stepRefs.current.slice(0, chapterCount).map((step) => {
        if (!step) return null;
        const box = step.getBoundingClientRect();
        return root.scrollTop + box.top - viewport.top - root.clientTop + box.height / 2;
      });
      let nearest = 0;
      let distance = Infinity;
      centers.forEach((stepCenter, index) => {
        if (stepCenter === null) return;
        const candidate = Math.abs(center - stepCenter);
        if (candidate < distance) {
          nearest = index;
          distance = candidate;
        }
      });
      if (distance !== Infinity && activeRef.current !== nearest) {
        activeRef.current = nearest;
        setActive(nearest);
      }
      const travel = root.scrollHeight - root.clientHeight;
      root.style.setProperty('--story-progress', String(travel > 0 ? clamp(root.scrollTop / travel, 0, 1) : 0));
      const first = centers[0];
      const last = centers[chapterCount - 1];
      const sceneProgress = first != null && last != null && last > first
        ? clamp((center - first) / (last - first) * (chapterCount - 1), 0, chapterCount - 1)
        : 0;
      storyRef.current?.style.setProperty('--scene-progress', String(sceneProgress));
    };
    const schedule = () => {
      if (!disposed && frame === null) frame = window.requestAnimationFrame(measure);
    };
    scheduleRef.current = schedule;
    const updateCompact = () => {
      compactRef.current = compactMedia.matches;
      setCompact(compactMedia.matches);
      schedule();
    };
    const updateMotion = () => { reducedMotionRef.current = motionMedia.matches; };
    updateCompact();
    updateMotion();
    root.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    compactMedia.addEventListener('change', updateCompact);
    motionMedia.addEventListener('change', updateMotion);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(schedule);
    observer?.observe(root);
    if (storyRef.current) observer?.observe(storyRef.current);
    schedule();

    return () => {
      disposed = true;
      if (frame !== null) window.cancelAnimationFrame(frame);
      root.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      compactMedia.removeEventListener('change', updateCompact);
      motionMedia.removeEventListener('change', updateMotion);
      observer?.disconnect();
      scheduleRef.current = null;
    };
  }, [chapterCount]);

  // Compact layout changes can replace the step elements after the media event.
  useEffect(() => { scheduleRef.current?.(); }, [compact]);

  return { rootRef, storyRef, stepRefs, active, compact, jumpTo, scrollToElement };
}
