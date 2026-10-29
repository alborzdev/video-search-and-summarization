// SPDX-License-Identifier: MIT
import React, { useEffect, useState } from "react";
import s from "./CityCrossingDuration.module.css";

const sampleSeconds = 6;

/** A bounded illustrative sequence, independent of live analytics or signal control. */
export function CityCrossingDuration() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let timer: ReturnType<typeof setInterval> | undefined;
    const stop = () => { if (timer !== undefined) clearInterval(timer); };
    const finish = () => { stop(); setElapsed(sampleSeconds); };
    const onMotion = () => { if (motion.matches) finish(); };
    if (motion.matches) finish();
    else {
      let seconds = 0;
      timer = setInterval(() => {
        seconds += 1;
        setElapsed(seconds);
        if (seconds >= sampleSeconds) stop();
      }, 1000);
    }
    motion.addEventListener("change", onMotion);
    return () => { stop(); motion.removeEventListener("change", onMotion); };
  }, []);

  return <section className={s.duration} aria-label="Illustrative crossing occupancy duration">
    <div className={s.readout}>
      <div><span>Time occupied</span><strong role="timer" aria-label={`${elapsed} seconds occupied`}>{String(elapsed).padStart(2, "0")}<small>s</small></strong></div>
      <p><i aria-hidden="true"/>3 people<br/>still inside</p>
    </div>
    <div className={s.timeline} aria-hidden="true"><i style={{ transform: `scaleX(${elapsed / sampleSeconds})` }}/></div>
    <div className={s.endpoints}><span>First entry</span><span>Still occupied</span></div>
    <small className={s.note}>Illustrative timing · continues until the zone is empty</small>
  </section>;
}
