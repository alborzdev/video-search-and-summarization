// SPDX-License-Identifier: MIT
import { IconArrowDown, IconArrowRight, IconCheck, IconFileText, IconPlayerPlay } from "@tabler/icons-react";
import React, { useState } from "react";
import { cityStoryEvents as savedEvents } from "./cityStoryEvents";
import { cityStoryAsset } from "./cityStoryAssets";
import s from "./CityVssStory.module.css";


export function ContinuousCaptureStory() {
  return <div className={s.capture} role="group" aria-label="Continuous recording saves each detected event with video and a report locally in VSS">
    <div className={s.recordingLabel}><span />Continuous recording</div>
    <div className={s.recordingStrip}>
      {[{ time: "08:00", asset: "intersection-referenced.png" }, ...savedEvents].map((event) =>
        <figure key={event.time}>
          <img src={cityStoryAsset(event.asset)} alt="" />
          <figcaption>{event.time}</figcaption>
        </figure>
      )}
    </div>
    <div className={s.timeline} aria-hidden="true"><i /><i /><i /></div>
    <IconArrowDown className={s.downArrow} aria-hidden="true" />
    <div className={s.saveFlow}>
      <figure className={s.device}>
        <img src="/vision/anvil-t5.png" alt="Anvil T5 edge computer" />
        <figcaption>Anvil T5<span>VSS running locally</span></figcaption>
      </figure>
      <IconArrowRight className={s.flowArrow} aria-hidden="true" />
      <div className={s.history}>
        <div className={s.historyHeading}>Every detected event</div>
        {savedEvents.map((event, index) => <div className={s.savedEvent} key={event.title} style={{ animationDelay: `${index * .35}s`, viewTransitionName:`city-record-${event.key}` } as React.CSSProperties}>
          <img src={cityStoryAsset(event.asset)} alt="" style={{viewTransitionName:`city-event-${event.key}`} as React.CSSProperties}/>
          <span><strong>{event.title}</strong><small>{event.track} · {event.time} · Video + report</small></span>
          <IconCheck size={17} aria-label="Saved" />
        </div>)}
        <div className={s.continues}>The history keeps building<span aria-hidden="true"> · · ·</span></div>
      </div>
    </div>
  </div>;
}

export function SavedReviewStory({ onInteract }: { onInteract?: () => void }) {
  const [selected, setSelected] = useState(0);
  const event = savedEvents[selected];
  return <div className={s.review}>
    <div className={s.reviewLabel}>Saved in VSS <span>Choose an event to review</span></div>
    <div className={s.eventPicker} role="group" aria-label="Illustrated saved events">
      {savedEvents.map((item, index) => <button type="button" key={item.title} aria-pressed={selected === index} onClick={() => { onInteract?.(); setSelected(index); }}>
        <img src={cityStoryAsset(item.asset)} alt="" />
        <span><small>{item.time} · {item.track}</small>{item.title}</span>
      </button>)}
    </div>
    <IconArrowDown className={s.reviewArrow} aria-hidden="true" />
    <article className={s.report} style={{viewTransitionName:`city-record-${event.key}`} as React.CSSProperties} aria-label={`Saved report: ${event.title}`}>
      <div className={s.clip}>
        <img key={event.asset} style={{viewTransitionName:`city-event-${event.key}`} as React.CSSProperties} src={cityStoryAsset(event.asset)} alt={`Source footage illustration: ${event.title}`} />
        <span><IconPlayerPlay size={19} aria-hidden="true" />Matching video · {event.time}</span>
      </div>
      <div className={s.reportText}>
        <div className={s.reportLabel}><IconFileText size={19} aria-hidden="true" /> Event report</div>
        <h2>{event.title}</h2>
        <div className={s.recordIdentity}><strong>{event.track}</strong><span>{event.time} · {event.detail}</span></div>
        <p>{event.summary}</p>
        <span className={s.savedLabel}><IconCheck size={16} aria-hidden="true" /> Saved with source video</span>
      </div>
    </article>
    <div className={s.reviewOutcome}>Video and reports stay linked in VSS</div>
  </div>;
}
