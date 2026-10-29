// SPDX-License-Identifier: MIT
import React, { useEffect, useState } from "react";
import s from "./CityCrossingDuration.module.css";

export function useEventSequence(enabled: boolean, resetKey: string) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!enabled) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let timer: ReturnType<typeof setInterval> | undefined;
    const stop = () => { if (timer !== undefined) clearInterval(timer); };
    const finish = () => { stop(); setElapsed(6); };
    const change = () => { if (motion.matches) finish(); };
    if (motion.matches) finish();
    else {
      let seconds = 0;
      timer = setInterval(() => { seconds += 1; setElapsed(seconds); if (seconds === 6) stop(); }, 1000);
    }
    motion.addEventListener("change", change);
    return () => { stop(); motion.removeEventListener("change", change); };
  }, [enabled, resetKey]);
  return elapsed;
}

export function EventSequenceReadout({ kind, elapsed }: { kind: "queue" | "direction"; elapsed: number }) {
  const queue = kind === "queue";
  const positions = Math.min(3, Math.floor(elapsed / 2) + 1);
  return <section className={s.duration} aria-label={queue ? "Illustrative blockage timing" : "Illustrative direction sequence"}>
    <div className={s.readout}>
      <div><span>{queue ? "V-21 · stopped in crossing" : "V-08 · tracked positions"}</span>
        <strong role={queue ? "timer" : undefined} aria-label={queue ? `${elapsed} seconds stopped` : `${positions} tracked positions`}>{queue ? String(elapsed).padStart(2,"0") : positions}<small>{queue ? "s" : "/ 3"}</small></strong>
      </div>
      <p><i aria-hidden="true"/>{queue ? (elapsed >= 5 ? "5 s rule met" : "Checking duration") : (positions === 3 ? "Direction mismatch" : "Following movement")}</p>
    </div>
    <div className={s.timeline} aria-hidden="true"><i style={{transform:`scaleX(${queue ? elapsed / 6 : (positions - 1) / 2})`}}/></div>
    <div className={s.endpoints}><span>{queue ? "Vehicle stops" : "First position"}</span><span>{queue ? "Still obstructing" : "+4 s"}</span></div>
    <small className={s.note}>{queue ? "Illustrative 5-second rule · configure for the site" : "Illustrative position history · dots show earlier observations"}</small>
  </section>;
}
