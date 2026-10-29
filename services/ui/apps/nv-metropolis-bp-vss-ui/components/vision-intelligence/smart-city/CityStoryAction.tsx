// SPDX-License-Identifier: MIT

import s from "./CityDiorama.module.css";
import {
  IconArrowRight,
  IconCheck,
  IconCpu,
  IconWalk,
  IconVideo,
} from "@tabler/icons-react";
import React from "react";

const asset = "/vision/smart-city-story/";

/** Each chapter has an on-scene demonstration, separate from its explanatory copy. */
export function CityStoryAction({
  active,
  moment,
}: {
  active: number;
  moment: number;
}) {
  if (active === 0)
    return (
      <div className={s.openingPrompt}>
        <span>Watch the crossing.</span>
        <small>Scroll to reveal what the AI sees.</small>
      </div>
    );
  if (active === 1)
    return (
      <div className={s.cameraFrame}>
        <div>
          <IconVideo size={16} /> Crossing detail <small>Illustration</small>
        </div>
        <i className={s.scan} />
        <span className={s.cameraCaption}>
          Video enters the local system <IconArrowRight size={14} />
        </span>
      </div>
    );
  if (active === 2)
    return (
      <div className={s.observation}>
        <IconWalk size={28} />
        <div>
          <small>DETECTION</small>
          <strong>Person found</strong>
        </div>
        <span className={s.check}>
          <IconCheck size={18} />
        </span>
      </div>
    );
  if (active === 3)
    return (
      <div className={s.momentRail}>
        {["At the curb", "In the crossing", "On the pavement"].map(
          (label, i) => (
            <div key={label} data-current={moment === i}>
              <span>0{i + 1}</span>
              <i />
              <strong>{label}</strong>
              <small>P12</small>
            </div>
          )
        )}
      </div>
    );
  if (active === 4)
    return (
      <div className={s.groundLesson}>
        <span>Image position</span>
        <i />
        <strong>Ground position</strong>
        <small>Calibrated to this intersection</small>
      </div>
    );
  if (active === 5)
    return (
      <div className={s.ruleLesson}>
        <span>IF</span>
        <strong>Person inside crossing</strong>
        <IconArrowRight size={18} />
        <span>THEN</span>
        <strong>Occupied</strong>
      </div>
    );
  if (active === 6)
    return (
      <div className={s.signalLesson}>
        <div>
          <span>Walk phase</span>
          <strong>Ending soon</strong>
        </div>
        <div className={s.phaseBar}>
          <i />
        </div>
        <footer>
          <IconWalk size={20} />
          <strong>
            {moment === 0
              ? "Person at the curb"
              : moment === 2
              ? "Crossing clear"
              : "Person still crossing"}
          </strong>
          <span>{moment === 1 ? "EVENT" : "STATE"}</span>
        </footer>
        <small>Illustrative signal input</small>
      </div>
    );
  if (active === 7)
    return (
      <div className={s.requestLesson}>
        <small>SIMULATED REQUEST</small>
        <div>
          <span>
            <IconWalk size={24} />
            <strong>Crossing occupied</strong>
          </span>
          <i />
          <span>
            <IconCpu size={24} />
            <strong>Local event</strong>
          </span>
          <i />
          <span>
            <IconCheck size={24} />
            <strong>Controller receives request</strong>
          </span>
        </div>
      </div>
    );
  if (active === 8)
    return (
      <div className={s.clearLesson} data-clear={moment === 2}>
        <span>
          {moment === 2 ? <IconCheck size={27} /> : <IconWalk size={27} />}
        </span>
        <div>
          <small>
            {moment === 2
              ? "EVENT CLEARED"
              : moment === 0
              ? "AT THE CURB"
              : "CROSSING OCCUPIED"}
          </small>
          <strong>
            {moment === 2 ? "They are across." : "Follow them to the pavement."}
          </strong>
        </div>
      </div>
    );
  if (active === 9)
    return (
      <div className={s.evidenceLesson}>
        <header>One event. Its evidence.</header>
        <div>
          {["before", "occupied", "clear"].map((name, i) => (
            <figure key={name} style={{ "--order": i } as React.CSSProperties}>
              <svg
                viewBox="650 490 400 230"
                role="img"
                aria-label={`Crossing ${name}`}
              >
                <image
                  href={`${asset}crossing-${name}.png`}
                  width="1672"
                  height="941"
                />
              </svg>
              <figcaption>
                <span>0{i + 1}</span>
                {name}
              </figcaption>
            </figure>
          ))}
        </div>
        <footer>
          Camera clip <IconArrowRight size={12} /> Event record{" "}
          <IconArrowRight size={12} /> Reviewed report
        </footer>
      </div>
    );
  if (active === 10)
    return (
      <div className={s.ruleLesson}>
        <span>TRACKS</span>
        <strong>Queue grows</strong>
        <IconArrowRight size={18} />
        <span>EVENT</span>
        <strong>Crossing blocked</strong>
      </div>
    );
  if (active === 11)
    return (
      <div className={s.directionLesson}>
        <span>
          Allowed <IconArrowRight size={27} />
        </span>
        <span>
          <IconArrowRight size={27} /> Observed
        </span>
        <strong>Direction mismatch</strong>
      </div>
    );
  return (
    <div className={s.edgeLesson}>
      <div className={s.edgeSources}>
        <span>
          <IconVideo size={21} /> Street cameras
        </span>
        <div>
          <img
            src={`${asset}crossing-occupied.png`}
            alt="Illustrated crossing source"
          />
          <img
            src={`${asset}queue-render.png`}
            alt="Illustrated queue source"
          />
        </div>
      </div>
      <i className={s.edgeLink} />
      <div className={s.edgeDevice}>
        <img
          src="/vision/anvil-t5.png"
          alt="Connect Tech Anvil-T5 local processing"
        />
        <strong>Connect Tech Anvil-T5</strong>
        <small>Target booth hardware</small>
      </div>
      <i className={s.edgeLink} />
      <div className={s.edgeOutput}>
        <IconCpu size={26} />
        <strong>Useful events</strong>
        <span>Detect · Track · Explain</span>
      </div>
    </div>
  );
}
