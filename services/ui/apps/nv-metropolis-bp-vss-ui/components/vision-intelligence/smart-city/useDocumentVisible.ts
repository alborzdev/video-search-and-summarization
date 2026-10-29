// SPDX-License-Identifier: MIT
import { useSyncExternalStore } from 'react';

const subscribe = (onChange: () => void) => {
  document.addEventListener('visibilitychange', onChange);
  return () => document.removeEventListener('visibilitychange', onChange);
};
const snapshot = () => document.visibilityState !== 'hidden';
const serverSnapshot = () => true;

/** Suspend browser-only work in background tabs; camera analysis stays on the device. */
export function useDocumentVisible(): boolean {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}
