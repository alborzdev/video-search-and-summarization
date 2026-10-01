// SPDX-License-Identifier: MIT

import { IconCheck, IconTrash, IconX } from "@tabler/icons-react";
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styles from "./ClearHistoryControl.module.css";

type Counts = Partial<Record<"indexedMoments" | "recordings" | "reports" | "answers" | "detections" | "events" | "captions", number | null>>;
interface HistoryPlan {
  planId: string;
  cutoff: string;
  expiresAt: string;
  counts: Counts;
  sourceCount: number;
  warnings: string[];
}
type HistoryPreviewResponse = HistoryPlan | { activeJob: HistoryClearJob };
export interface HistoryClearJob {
  id: string;
  status: "running" | "complete" | "partial" | "failed";
  cutoff: string;
  steps: Array<{ id: string; label: string; status: "pending" | "running" | "complete" | "failed"; deleted?: number; error?: string }>;
  deletedCounts: Counts;
  errors: string[];
}

const API = "/api/vision/history-clear";
const JOB_STORAGE_KEY = "vision-history-clear-job-v1";
const COUNT_LABELS: Array<[keyof Counts, string]> = [
  ["indexedMoments", "Indexed moments"], ["recordings", "Recordings"],
  ["reports", "Reports"], ["answers", "Saved answers"], ["detections", "Detections"],
  ["events", "Past events"], ["captions", "Captions"],
];

function releasePlan(planId: string): void {
  void fetch(API, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ planId }),
  }).catch(() => undefined);
}

function rememberJob(job: HistoryClearJob): void {
  try {
    if (job.status === "running") window.sessionStorage.setItem(JOB_STORAGE_KEY, job.id);
    else window.sessionStorage.removeItem(JOB_STORAGE_KEY);
  } catch { /* Progress still works without browser storage. */ }
}

async function readResponse<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || payload.message || "History cleanup is unavailable. Try again.");
  return payload as T;
}

export function openClearHistory() {
  window.dispatchEvent(new Event("vision:open-history-clear"));
}

export function ClearHistoryControl({ hideTrigger = false }: { hideTrigger?: boolean }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<HistoryPlan | null>(null);
  const [job, setJob] = useState<HistoryClearJob | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  const openRef = useRef(open);
  openRef.current = open;
  const activePlan = useRef<HistoryPlan | null>(null);
  const submittedPlans = useRef(new Set<string>());
  const notifiedJob = useRef<string | null>(null);
  const dialog = useRef<HTMLElement | null>(null);
  const running = job?.status === "running";

  const releaseUnusedPlan = () => {
    const previous = activePlan.current;
    activePlan.current = null;
    if (previous && !submittedPlans.current.has(previous.planId)) releasePlan(previous.planId);
  };

  const preview = async () => {
    if (busy.current) return;
    releaseUnusedPlan();
    busy.current = true;
    setLoading(true);
    setPlan(null);
    setError(null);
    const controller = new AbortController();
    try {
      const next = await fetch(API, { cache: "no-store", signal: controller.signal }).then(readResponse<HistoryPreviewResponse>);
      if ("activeJob" in next) {
        rememberJob(next.activeJob);
        if (mounted.current) { setJob(next.activeJob); setResumeId(null); }
      } else if (!mounted.current || !openRef.current) releasePlan(next.planId);
      else { activePlan.current = next; setPlan(next); }
    } catch (cause) {
      if (!controller.signal.aborted && mounted.current) setError(cause instanceof Error ? cause.message : "Could not count the history. Try again.");
    } finally {
      if (mounted.current && !controller.signal.aborted) setLoading(false);
      busy.current = false;
    }
  };

  useEffect(() => {
    mounted.current = true;
    try { setResumeId(window.sessionStorage.getItem(JOB_STORAGE_KEY)); } catch { /* Storage may be unavailable. */ }
    return () => { mounted.current = false; releaseUnusedPlan(); };
  }, []);

  useEffect(() => {
    const show = () => { openRef.current = true; setOpen(true); };
    window.addEventListener("vision:open-history-clear", show);
    return () => window.removeEventListener("vision:open-history-clear", show);
  }, []);

  useEffect(() => {
    if (open && !job && !resumeId) void preview();
    // A fresh count is requested on every opening, not on unrelated state updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !starting) close();
      if (event.key !== "Tab" || !dialog.current) return;
      const controls = Array.from(dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), [tabindex="0"]'));
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); previousFocus?.focus(); };
  }, [open, starting]);

  useEffect(() => {
    const jobId = running ? job?.id : resumeId;
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      let continuePolling = true;
      try {
        const result = await fetch(`${API}?jobId=${encodeURIComponent(jobId)}`, { cache: "no-store", signal: controller.signal }).then(readResponse<{ job: HistoryClearJob }>);
        if (controller.signal.aborted) return;
        setJob(result.job);
        setResumeId(null);
        setError(null);
        continuePolling = result.job.status === "running";
      } catch (cause) {
        if (controller.signal.aborted) return;
        setError(`Could not check cleanup progress. Retrying automatically. ${cause instanceof Error ? cause.message : ""}`);
      }
      if (continuePolling && !controller.signal.aborted) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, resumeId ? 0 : 1000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job?.id, running, resumeId]);

  useEffect(() => {
    if (!job) return;
    rememberJob(job);
    if (job.status !== "running" && notifiedJob.current !== job.id) {
      notifiedJob.current = job.id;
      window.dispatchEvent(new CustomEvent("vision:history-cleared", { detail: { job } }));
    }
  }, [job]);

  const start = async () => {
    if (!plan || busy.current || job || resumeId) return;
    if (Date.parse(plan.expiresAt) <= Date.now()) { releaseUnusedPlan(); setError("The history count has expired. Refresh the count before clearing."); setPlan(null); return; }
    busy.current = true;
    submittedPlans.current.add(plan.planId);
    setStarting(true);
    setError(null);
    const controller = new AbortController();
    try {
      const result = await fetch(API, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planId: plan.planId, confirmation: "CLEAR_HISTORY" }), signal: controller.signal,
      }).then(readResponse<{ job: HistoryClearJob }>);
      rememberJob(result.job);
      if (!controller.signal.aborted && mounted.current) setJob(result.job);
    } catch (cause) {
      if (!controller.signal.aborted && mounted.current) setError(cause instanceof Error ? cause.message : "Could not start cleanup. Retry to check the same request.");
    } finally {
      busy.current = false;
      if (mounted.current && !controller.signal.aborted) setStarting(false);
    }
  };

  const close = () => {
    if (starting) return;
    openRef.current = false;
    releaseUnusedPlan();
    if (!job) setPlan(null);
    setOpen(false);
  };
  const freshPreview = () => { setJob(null); setPlan(null); void preview(); };
  const terminal = job && job.status !== "running";
  const title = job?.status === "complete" ? "History cleared" : job?.status === "partial" ? "Some history remains" : job?.status === "failed" ? "History could not be cleared" : running ? "Clearing previous history" : "Clear previous history?";
  const visibleCounts = COUNT_LABELS.filter(([key]) => !((key === "answers" || key === "captions") && plan?.counts[key] === 0));
  const emptyHistory = plan && COUNT_LABELS.every(([key]) => plan.counts[key] === 0);

  return <>
    {!hideTrigger && <button className={styles.trigger} type="button" onClick={() => { openRef.current = true; setOpen(true); }}><IconTrash size={16} />{running || resumeId ? "Clearing history…" : "Clear history"}</button>}
    {/* Keep the dialog above the mobile navigation while inheriting the app's theme. */}
    {open && createPortal(<div className={styles.backdrop} onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <section ref={dialog} tabIndex={-1} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="vi-clear-history-title" aria-describedby="vi-clear-history-description">
        <header><div><span className={styles.eyebrow}>History</span><h2 id="vi-clear-history-title">{title}</h2></div><button className={styles.close} disabled={starting} aria-label="Close history cleanup" type="button" onClick={close}><IconX size={19} /></button></header>
        <p id="vi-clear-history-description">{job?.status === "complete" ? "Previous history is cleared. New moments can appear when live indexing is active." : "Remove previous indexed moments, recordings, answers, reports, detections, captions and past events. This cannot be undone."}</p>
        <div className={styles.keep}><IconCheck size={18} /><div><strong>Capture and indexing are unchanged</strong><p>Active capture and indexing keep running. Cameras, monitoring rules, settings and cached models stay in place. New history arriving after the cleanup cutoff stays.</p></div></div>
        {loading && <p className={styles.status} role="status">Counting previous history…</p>}
        {resumeId && !job && <p className={styles.status} role="status">Checking the previous cleanup…</p>}
        {!job && plan && !loading && <>{emptyHistory ? <p className={styles.status}>No previous stored history (0 items). You can still clear answers shown in this browser.</p> : <div className={styles.counts}>{visibleCounts.map(([key, label]) => <div key={key}><strong>{typeof plan.counts[key] === "number" ? plan.counts[key]!.toLocaleString() : "Unavailable"}</strong><span>{label}</span></div>)}</div>}<p className={styles.cutoff}>Cleanup cutoff: {new Date(plan.cutoff).toLocaleString()}. Counts may grow while the cameras are live.</p>{plan.warnings?.length > 0 && <ul className={styles.warning}>{plan.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}</>}
        {job && <div aria-live="polite"><ol className={styles.steps}>{job.steps.map((step) => <li key={step.id} data-status={step.status}><span>{step.status === "complete" ? <IconCheck size={15} /> : step.status === "failed" ? <IconX size={15} /> : <i />}</span><div><strong>{step.label}</strong>{step.error && <p>{step.error}</p>}</div><em>{step.status === "complete" ? `${typeof step.deleted === "number" ? `${step.deleted.toLocaleString()} removed · ` : ""}Done` : step.status === "failed" ? "Failed" : step.status === "running" ? "Clearing…" : "Waiting"}</em></li>)}</ol>{job.status === "partial" && <p className={styles.warning}>Some cleanup steps failed. Review the details below and try again to clear the remaining history.</p>}{job.errors?.length > 0 && <ul className={styles.warning}>{job.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}</div>}
        {error && <p className={styles.warning} role="alert">{error}</p>}
        <footer><button type="button" disabled={starting} onClick={close}>{running || terminal || resumeId ? "Close" : "Cancel"}</button>{terminal ? <button type="button" onClick={freshPreview}>Review remaining history</button> : !running && !resumeId && (plan ? <><button type="button" disabled={loading || starting} onClick={() => void preview()}>Refresh count</button><button className={styles.danger} type="button" disabled={loading || starting} onClick={() => void start()}><IconTrash size={16} />{starting ? "Starting cleanup…" : "Clear all previous history"}</button></> : <button type="button" disabled={loading} onClick={() => void preview()}>Refresh count</button>)}</footer>
        {running && <p className={styles.footnote}>You can close this dialog. Cleanup continues in the background.</p>}
      </section>
    </div>, document.querySelector(".vi-app") ?? document.body)}
  </>;
}
