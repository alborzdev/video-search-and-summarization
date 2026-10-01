// SPDX-License-Identifier: MIT

import { useEffect, useRef } from "react";

export function isBeforeHistoryCutoff(timestamp: string | null | undefined, cutoff: string | null | undefined): boolean {
  const created = Date.parse(timestamp || "");
  const boundary = Date.parse(cutoff || "");
  return Number.isFinite(created) && Number.isFinite(boundary) && created <= boundary;
}

export function useHistoryClear(onClear: (cutoff: string) => void) {
  const latest = useRef(onClear);
  latest.current = onClear;
  const cutoff = useRef<string | null>(null);
  useEffect(() => {
    const listener = (event: Event) => {
      const job = (event as CustomEvent<{ job?: { status?: string; cutoff?: string } }>).detail?.job;
      if ((job?.status !== "complete" && job?.status !== "partial") || !Number.isFinite(Date.parse(job.cutoff || ""))) return;
      if (!cutoff.current || Date.parse(job.cutoff!) > Date.parse(cutoff.current)) cutoff.current = job.cutoff!;
      latest.current(cutoff.current!);
    };
    window.addEventListener("vision:history-cleared", listener);
    return () => window.removeEventListener("vision:history-cleared", listener);
  }, []);
  return cutoff;
}
