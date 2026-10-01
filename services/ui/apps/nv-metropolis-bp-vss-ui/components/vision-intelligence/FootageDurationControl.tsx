// SPDX-License-Identifier: MIT

import React, { useId } from "react";
import { MAX_LOOKBACK_SECONDS, MIN_LOOKBACK_SECONDS, questionFrameCount, validLookbackSeconds } from "./footageWindow";
import styles from "./FootageDurationControl.module.css";

export function FootageDurationControl({ seconds, onChange, disabled = false }: {
  seconds: number | null;
  onChange: (seconds: number | null) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const valid = validLookbackSeconds(seconds);
  return <div className={styles.control}>
    <div className={styles.row}>
      <label htmlFor={id}>Recent footage</label>
      <div className={styles.input}>
        <input id={id} aria-label="Seconds of footage" type="number" inputMode="numeric"
          min={MIN_LOOKBACK_SECONDS} max={MAX_LOOKBACK_SECONDS} step={1}
          value={seconds ?? ""} disabled={disabled} required aria-invalid={!valid}
          aria-describedby={`${id}-hint`}
          onChange={(event) => onChange(Number.isFinite(event.currentTarget.valueAsNumber) ? event.currentTarget.valueAsNumber : null)} />
        <span>seconds</span>
      </div>
      <span className={styles.frames}>{valid ? `Up to ${questionFrameCount(seconds)} ${questionFrameCount(seconds) === 1 ? "frame" : "frames"}` : "Choose 1–60 seconds"}</span>
    </div>
    <span id={`${id}-hint`} className={styles.hint}>
      {valid && seconds > 20 ? "Sampling is capped at 20 frames across the full interval." : "About one frame per second. Shorter intervals give faster answers."}
    </span>
  </div>;
}
