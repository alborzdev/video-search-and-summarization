import React, { useLayoutEffect } from 'react';
import { act, fireEvent, render } from '@testing-library/react';
import { useVssStoryScroll } from '../useVssStoryScroll';

const compactQuery = '(max-width: 1000px), (max-height: 650px)';
const motionQuery = '(prefers-reduced-motion: reduce)';
let hook: ReturnType<typeof useVssStoryScroll>;
let root: HTMLDivElement;
let scrollTo: jest.Mock;
let frames: Map<number, FrameRequestCallback>;
let media: Map<string, { matches: boolean; listeners: Set<() => void>; addEventListener: jest.Mock; removeEventListener: jest.Mock }>;
let disconnect: jest.Mock;

const rect = (top: number, height: number) => ({ top, height, bottom: top + height, left: 0, right: 900, width: 900, x: 0, y: top, toJSON: () => ({}) } as DOMRect);

function Harness({ count = 4 }: { count?: number }) {
  hook = useVssStoryScroll(count);
  useLayoutEffect(() => {
    root = hook.rootRef.current!;
    Object.defineProperties(root, {
      clientHeight: { configurable: true, value: 600 },
      clientTop: { configurable: true, value: 2 },
      scrollHeight: { configurable: true, value: 3600 },
      scrollTop: { configurable: true, writable: true, value: 300 },
    });
    root.getBoundingClientRect = () => rect(120, 604);
    scrollTo = jest.fn();
    root.scrollTo = scrollTo;
    hook.stepRefs.current.forEach((step, index) => {
      // Step positions move with the independent root's scroll, not the window.
      step!.getBoundingClientRect = () => rect(122 + 500 + index * 600 - root.scrollTop, 500);
    });
  }, []);
  return <div ref={hook.rootRef}><section ref={hook.storyRef}>
    {Array.from({ length: count }, (_, index) => index).map(index => <article key={index} ref={element => { hook.stepRefs.current[index] = element; }} />)}
  </section><output data-testid="active">{hook.active}</output></div>;
}

function flushFrame() {
  act(() => {
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach(callback => callback(0));
  });
}
function changeMedia(query: string, matches: boolean) {
  act(() => {
    const entry = media.get(query)!;
    entry.matches = matches;
    entry.listeners.forEach(listener => listener());
  });
}

beforeEach(() => {
  frames = new Map();
  let frameId = 0;
  jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => {
    frames.set(++frameId, callback);
    return frameId;
  });
  jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(id => { frames.delete(id); });
  media = new Map();
  [compactQuery, motionQuery].forEach(query => {
    const listeners = new Set<() => void>();
    media.set(query, {
      matches: false,
      listeners,
      addEventListener: jest.fn((_event, listener) => listeners.add(listener)),
      removeEventListener: jest.fn((_event, listener) => listeners.delete(listener)),
    });
  });
  (window.matchMedia as jest.Mock).mockImplementation(query => media.get(query));
  disconnect = jest.fn();
  global.ResizeObserver = class {
    observe = jest.fn();
    unobserve = jest.fn();
    disconnect = disconnect;
  } as unknown as typeof ResizeObserver;
});

it('centers desktop chapter jumps in an offset, bordered independent viewport', () => {
  render(<Harness />);
  act(() => hook.jumpTo(2));
  // Chapter 2 center is content coordinate 1950; root viewport center is 300.
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 1650, behavior: 'smooth' });
  expect(root.scrollTop).toBe(300);
});

it('switches compact navigation to the step top below the sticky header', () => {
  render(<Harness />);
  changeMedia(compactQuery, true);
  expect(hook.compact).toBe(true);
  act(() => hook.jumpTo(1));
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 1044, behavior: 'smooth' });
  changeMedia(compactQuery, false);
  act(() => hook.jumpTo(1));
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 1050, behavior: 'smooth' });
});

it('honors live reduced-motion changes for chapter and element navigation', () => {
  render(<Harness />);
  changeMedia(motionQuery, true);
  act(() => hook.jumpTo(3));
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 2250, behavior: 'auto' });
  act(() => hook.scrollToElement(hook.stepRefs.current[0]));
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 444, behavior: 'auto' });
  changeMedia(motionQuery, false);
  act(() => hook.scrollToElement(hook.stepRefs.current[0]));
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 444, behavior: 'smooth' });
});

it('tracks the nearest measured step, coalesces scroll frames, and releases listeners on unmount', () => {
  const view = render(<Harness />);
  flushFrame();
  expect(hook.active).toBe(0);
  const focus = document.activeElement;
  root.scrollTop = 1600;
  fireEvent.scroll(root);
  fireEvent.scroll(root);
  expect(frames.size).toBe(1);
  flushFrame();
  expect(hook.active).toBe(2);
  expect(document.activeElement).toBe(focus);
  root.scrollTop = 800;
  fireEvent.scroll(root);
  flushFrame();
  expect(hook.active).toBe(1);
  const remove = jest.spyOn(root, 'removeEventListener');
  fireEvent.scroll(root);
  expect(frames.size).toBe(1);
  view.unmount();
  expect(frames.size).toBe(0);
  expect(remove).toHaveBeenCalledWith('scroll', expect.any(Function));
  expect(disconnect).toHaveBeenCalledTimes(1);
  expect(media.get(compactQuery)!.listeners.size).toBe(0);
  expect(media.get(motionQuery)!.listeners.size).toBe(0);
});

it("tracks a fifth chapter without clamping it to the fourth", () => {
  render(<Harness count={5} />);
  root.scrollTop = 2850;
  fireEvent.scroll(root);
  flushFrame();
  expect(hook.active).toBe(4);
  act(() => hook.jumpTo(4));
  expect(scrollTo).toHaveBeenLastCalledWith({ top: 2850, behavior: "smooth" });
});
