// SPDX-License-Identifier: MIT

import { cityStoryEvents } from "./cityStoryEvents";
import { EventSequenceReadout, useEventSequence } from "./CityEventSequence";
import { CityCrossingDuration } from "./CityCrossingDuration";
import { TrackBox, crossingZone } from "./CityTrackOverlay";
import { AreaRuleDemo, DetectionDemo, MultiCameraDemo } from "./CityTrackingConcepts";
import { SimToRealStory, SparkProduct } from "./CitySimToRealStory";
import { ContinuousCaptureStory, SavedReviewStory } from "./CityVssStory";
import { ActivityOverTime } from "./CityActivityStory";
import { CityClosingStory } from "./CityClosingStory";
import { cityStoryAsset } from "./cityStoryAssets";
import s from "./CityDemo.module.css";
import { cityDemoCases } from "./cityDemoStory";
import {
  IconPlayerPlay,
  IconVideo,
} from "@tabler/icons-react";
import React, { useEffect, useState } from "react";


const cameras = [
  {
    id: "01",
    name: "South crossing",
    image: "intersection-referenced.png",
    crop: "530 510 580 350",
    x: 1043,
    y: 522,
  },
  {
    id: "02",
    name: "Traffic approach",
    image: "intersection-queue.png",
    crop: "620 340 550 360",
    x: 518,
    y: 405,
  },
  {
    id: "03",
    name: "East approach",
    image: "intersection-queue.png",
    crop: "860 170 400 320",
    x: 1118,
    y: 260,
  },
  {
    id: "04",
    name: "Intersection overview",
    image: "intersection-referenced.png",
    crop: "480 240 700 450",
    x: 642,
    y: 202,
  },
] as const;
export function CityDiorama({
  active,
  beat,
  onInteract,
}: {
  active: number;
  beat: readonly string[];
  onInteract?: () => void;
}) {
  const selected =
    active >= 5 && active <= 8 ? cityDemoCases[active - 5] : null;
  const [analysis, setAnalysis] = useState(true);
  const [replay, setReplay] = useState(0);
  useEffect(() => {
    setAnalysis(true);
  }, [active]);
  const elapsed = useEventSequence(analysis && (active === 6 || active === 7), `${active}-${replay}`);
  const event = cityStoryEvents.find(item => item.key === selected?.id);
  const focus = selected?.focus ?? [1, 0, 0];
  const image = selected?.asset ?? "intersection-referenced.png";
  return (
    <section
      className={s.layout}
      data-step={active}
      aria-label={selected?.name ?? "Multi-camera edge AI architecture"}
    >
      <div className={s.visual}>
        <svg
          className={s.diorama}
          style={{ viewTransitionName: active === 0 ? "city-story-twin" : "none" } as React.CSSProperties}
          data-testid="city-diorama"
          viewBox="0 0 1672 941"
          role="img"
          aria-label="Architectural city scene with camera locations and illustrated analysis"
        >
          <defs>
            <marker
              id="city-demo-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M1 1 8 5 1 9" fill="none" stroke="#b6efd2" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </marker>
            <marker id="city-observed-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M1 1 8 5 1 9" fill="none" stroke="#f4cd88" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </marker>
          </defs>
          <g
            className={s.framing}
            style={{
              transform: `translate(${focus[1]}px,${focus[2]}px) scale(${focus[0]})`,
            }}
          >
            {["intersection-referenced.png", "intersection-queue.png", "intersection-direction.png", "intersection-emergency.png"].map((src) => (
              <image className={s.sceneImage} key={src} href={cityStoryAsset(src)} width="1672" height="941" preserveAspectRatio="none" opacity={src === image ? 1 : 0} />
            ))}
            {active === 0 &&
              cameras.map((c, i) => (
                <g
                  key={c.id}
                  className={s.cameraPin}
                  style={{ animationDelay: `${i * 0.22}s` }}
                  transform={`translate(${c.x},${c.y})`}
                >
                  <path d="M0 0 -20 -42H-95" />
                  <circle r="6" />
                  <rect x="-105" y="-70" width="95" height="28" rx="5" />
                  <text x="-94" y="-51">
                    CAM {c.id}
                  </text>
                </g>
              ))}
            {selected && analysis && (
              <g key={`${active}-${replay}`} data-testid="case-observations">
                {(selected.id === "crossing" || selected.id === "queue") && (
                  <path
                    className={s.zone}
                    pathLength="1"
                    d={crossingZone}
                  />
                )}
                {selected.id === "crossing" && (
                  <>
                    {[
                      { id: "P-17", x: 695, y: 555, width: 24, height: 59, color: "#c4f3db" },
                      { id: "P-23", x: 736, y: 560, width: 25, height: 59, color: "#f4cd88" },
                      { id: "P-31", x: 805, y: 581, width: 30, height: 58, color: "#b6d5ff" },
                    ].map((track, i) => <TrackBox key={track.id} track={track} labelScale={.7} labelOffsetX={i === 0 ? -12 : 0}/>)}

                  </>
                )}
                {selected.id === "queue" && (
                  <TrackBox track={{ id: "V-21", x: 791, y: 536, width: 98, height: 101, color: "#f4cd88" }} labelScale={.8}/>
                )}
                {selected.id === "direction" && (
                  <>
                    <TrackBox track={{ id: "V-08", x: 687, y: 728, width: 91, height: 103, color: "#f4cd88" }} labelScale={.8}/>
                    <g className={s.positionHistory} aria-label="Illustrative positions at 0, 2 and 4 seconds">
                      <path d="M810 663 770 738 730 817" pathLength="1" style={{strokeDasharray:1,strokeDashoffset:1-Math.min(1,elapsed/4)}}/>
                      {[[810,663],[770,738],[730,817]].map(([x,y],i)=><g key={i} opacity={elapsed >= i*2 ? 1 : .15}>
                        <circle cx={x} cy={y} r="7"/><text x={x+17} y={y+4}>{i*2}s</text>
                      </g>)}
                    </g>
                    <g className={s.directionGuide}>
                      <path d="M726 840 702 885" stroke="#f4cd88" markerEnd="url(#city-observed-arrow)"/>
                      <path d="M857 786 900 699" stroke="#b6efd2" markerEnd="url(#city-demo-arrow)"/>
                      <g transform="translate(747 859)"><rect width="101" height="29"/><text x="11" y="20" fill="#f4cd88">Observed</text></g>
                      <g transform="translate(883 659)"><rect width="91" height="29"/><text x="11" y="20" fill="#b6efd2">Allowed</text></g>
                    </g>
                  </>
                )}
                {selected.id === "emergency" && (
                  <>
                    <TrackBox track={{ id: "V-30", x: 439, y: 318, width: 183, height: 131, color: "#c4f3db" }} labelScale={.8}/>
                    <TrackBox track={{ id: "V-22", x: 883, y: 428, width: 76, height: 78, color: "#f4cd88" }} labelScale={.8}/>
                    <path className={s.path} pathLength="1" d="M624 432 842 487" markerEnd="url(#city-demo-arrow)" />
                    <text className={s.sceneLabel} x="627" y="404">Ambulance approach</text>
                  </>
                )}


              </g>
            )}
          </g>
        </svg>
        <div
          key={`${active}-${replay}`}
          className={s.visualContent}
          data-testid="city-scene-action"
        >
          {active === 0 && (
            <div className={s.introDevice} style={{viewTransitionName: "city-story-spark-card"} as React.CSSProperties}>
              <SparkProduct />
              <div>
                <strong>Digital twin demo on DGX Spark</strong>
                <span>Isaac Sim + configurable virtual cameras.</span>
              </div>
            </div>
          )}
          {active === 1 && <SimToRealStory />}
          {active === 12 && <CityClosingStory title={beat[1]} description={beat[2]} />}
          {active === 2 && <DetectionDemo onInteract={onInteract} />}
          {active === 4 && <AreaRuleDemo onInteract={onInteract} />}
          {active === 3 && <MultiCameraDemo />}
          {active === 11 && <ActivityOverTime onInteract={onInteract} />}
          {selected && (
            <>
              <div className={s.caseSource}>
                <IconVideo size={15} />
                <strong>CAM {selected.camera}</strong>
                <span>
                  {cameras.find((c) => c.id === selected.camera)?.name}
                </span>
              </div>
              <div className={`${s.caseEvent} ${event && analysis ? s.eventCard : ""}`}>
                {event && analysis && <img className={s.eventThumbnail} src={cityStoryAsset(event.asset)} alt="" style={{viewTransitionName:`city-event-${event.key}`} as React.CSSProperties}/>}
                <small>
                  {analysis ? "Event focus" : "Original view"}
                </small>
                <strong role="status">
                  {analysis ? selected.status : "Street scene"}
                </strong>
                {event && analysis && <span className={s.eventIdentity}>{event.track} · {event.time}</span>}
              </div>
            </>
          )}
          {active === 9 && <ContinuousCaptureStory />}
          {active === 10 && <SavedReviewStory onInteract={onInteract} />}
        </div>
        <span className={s.visualNote}>
          Illustrated digital twin and camera views
        </span>
      </div>
      <div className={s.copy} hidden={active === 12} style={{ viewTransitionName: "city-story-copy" } as React.CSSProperties}>
        <header key={active}>
          <span>{beat[0]}</span>
          <h1>{beat[1]}</h1>
          <p>{beat[2]}</p>
        </header>
        <div className={s.detail} hidden={active === 1 || active >= 9}>
          {(active === 2 || active === 4) ? <div className={s.localCompute}>
            <img src="/vision/anvil-t5.png" alt="Anvil T5 edge computer" />
            <div>
              <small>LOCAL ANALYTICS</small>
              <strong>Runs locally on Anvil T5</strong>
              <span>{active === 2 ? "Detection + tracking" : "Zone rules + occupancy"}</span>
            </div>
          </div> : selected ? <>
            {selected.id === "crossing" && analysis && <CityCrossingDuration key={`${active}-${replay}`} />}
            {(selected.id === "queue" || selected.id === "direction") && analysis && <EventSequenceReadout kind={selected.id} elapsed={elapsed}/>}
            <p className={s.takeaway}><span>WHY IT MATTERS</span>{selected.value}</p>
            <div className={s.caseControls}>
              <button type="button" aria-pressed={analysis} onClick={() => { onInteract?.(); setAnalysis(!analysis); }}>
                {analysis ? "Hide observations" : "Show observations"}
              </button>
              <button type="button" onClick={() => { onInteract?.(); setAnalysis(true); setReplay(n => n + 1); }}>
                <IconPlayerPlay size={13} />Replay
              </button>
            </div>
            {selected.source && <a href={selected.source} target="_blank" rel="noreferrer">Why cities use this ↗</a>}
          </> : <div className={s.conceptSteps}>
            {(active === 0 ? ["Place cameras where you need them", "Repeat and compare traffic scenarios"] :
              active === 1 ? ["Live RTSP streams", "Processed on NVIDIA Jetson Thor"] :
              active === 2 ? ["Person or vehicle", "ID and position over time"] :
              active === 4 ? ["Crossing occupancy", "Next: measure crossing occupancy"] :
              active === 3 ? ["Same object, consistent ID", "MV3DT runs in the local pipeline"] :
              active === 10 ? ["Saved locally in VSS", "Searchable events and reports"] :
              ["Local video and storage", "Share reports when needed"]
            ).map((label,i) => <div key={label}><b>0{i+1}</b><span>{label}</span></div>)}
          </div>}
        </div>
      </div>

    </section>
  );
}
