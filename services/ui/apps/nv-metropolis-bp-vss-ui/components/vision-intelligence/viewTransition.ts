// SPDX-License-Identifier: MIT
import { flushSync } from 'react-dom';

type NavigationTransition = {
  ready: Promise<void>;
  finished: Promise<void>;
  skipTransition: () => void;
};
type TransitionDocument = Document & {
  startViewTransition?: (update: () => void) => NavigationTransition;
};
let activeTransition: NavigationTransition | undefined;
let applyingUpdate = false;

/** Animate user navigation without remounting retained cameras or delaying input. */
export function animateViewChange(update: () => void) {
  if (applyingUpdate || typeof document === 'undefined') { update(); return; }
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    activeTransition?.skipTransition();
    update();
    return;
  }
  const page = document as TransitionDocument;
  if (!page.startViewTransition) {
    flushSync(update);
    document.querySelector('.vi-main')?.animate?.(
      [{ opacity: 0, translate: '0 8px' }, { opacity: 1, translate: '0 0' }],
      { duration: 240, easing: 'cubic-bezier(.22,.61,.36,1)' },
    );
    return;
  }
  activeTransition?.skipTransition();
  page.documentElement.dataset.viTransition = 'navigation';
  const transition = page.startViewTransition(() => {
    applyingUpdate = true;
    try { flushSync(update); } finally { applyingUpdate = false; }
  });
  activeTransition = transition;
  // A newer click can skip the animation; the state update still runs.
  void transition.ready.catch(() => undefined);
  void transition.finished.catch(() => undefined).then(() => {
    if (activeTransition !== transition) return;
    activeTransition = undefined;
    delete page.documentElement.dataset.viTransition;
  });
}
