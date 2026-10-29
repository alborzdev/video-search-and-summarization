// SPDX-License-Identifier: MIT
import React, { useState } from "react";
import { TrackBox, crossingZone } from "./CityTrackOverlay";
import { cityStoryAsset } from "./cityStoryAssets";
import s from "./CityCameraStory.module.css";


const people = [
  { id: "P-17", x: 681, y: 374, width: 81, height: 137, color: "#c4f3db" },
  { id: "P-23", x: 809, y: 400, width: 91, height: 141, color: "#f4cd88" },
  { id: "P-31", x: 1007, y: 435, width: 93, height: 133, color: "#b6d5ff" },
] as const;

export function DetectionDemo({ onInteract }: { onInteract?: () => void }) {
  const [showTracks, setShowTracks] = useState(true);
  return <div className={s.cameraStory}>
    <div className={s.viewHeading}><span>CAM 01 / SOUTH CROSSING</span><button type="button" aria-pressed={showTracks} onClick={()=>{onInteract?.();setShowTracks(v=>!v);}}>{showTracks ? "See original view" : "Show AI observations"}</button></div>
    <div className={s.heroFrame}>
      <svg viewBox="0 0 1672 941" role="img" aria-label="Illustrated street camera with three pedestrians and two cars">
        <image href={cityStoryAsset("crossing-referenced.png")} width="1672" height="941"/>
        {showTracks && <g>
          {people.map((p,i)=><TrackBox key={p.id} track={p} delay={i*.25} labelScale={1.3}/>)}
          <TrackBox track={{id:"V-08",x:620,y:84,width:168,height:179,color:"#f4cd88"}} delay={.8}/>
          <TrackBox track={{id:"V-12",x:780,y:119,width:160,height:173,color:"#c4f3db"}} delay={1}/>
        </g>}
      </svg>
      <div className={s.frameCaption}><strong>{showTracks ? "People and vehicles with IDs" : "Original camera video"}</strong><span>{showTracks ? "Each ID follows an object through successive frames." : "Turn on observations to see what the AI adds."}</span></div>
    </div>
    <div className={s.sceneFooter}><span>Camera video</span><i>→</i><span>Object detection</span><i>→</i><strong>ID + position</strong></div>
  </div>;
}

const areas = [
  { name: "Crossing", image: "crossing-referenced.png", crop: "0 0 1672 941", path: "M440 370 1340 530 1320 710 350 490Z", result: "3 people in the crossing", className: "People", condition: "Inside the area", note: "Know when the crossing is still occupied." },
  { name: "Blocked crossing", image: "intersection-queue.png", crop: "400 340 850 478.125", path: crossingZone, result: "Vehicle blocking the crossing", className: "Vehicles", condition: "Stays past the limit", note: "Locate a stopped vehicle obstructing the crossing." },
] as const;
export function AreaRuleDemo({ onInteract }: { onInteract?: () => void }) {
  const [choice, setChoice] = useState(0);
  const [replay, setReplay] = useState(0);
  const area = areas[choice];
  return <div className={s.cameraStory}>
    <div className={s.viewHeading}><div className={s.areaTabs} aria-label="Choose an illustrated area">{areas.map((a,i)=><button type="button" key={a.name} aria-pressed={choice===i} onClick={()=>{onInteract?.();setChoice(i);setReplay(n=>n+1);}}>{a.name}</button>)}</div><button type="button" aria-label="Replay area rule" onClick={()=>{onInteract?.();setReplay(n=>n+1);}}>Replay ↻</button></div>
    <div className={s.heroFrame} key={`${choice}-${replay}`}>
      <span className={s.eventFocus}>Event focus</span>
      <svg viewBox={area.crop} role="img" aria-label={`Illustrated camera with a marked ${area.name.toLowerCase()} zone`}>
        <image href={cityStoryAsset(area.image)} width="1672" height="941"/>
        <path d={area.path} className={s.streetZone} pathLength="1"/>
        {choice === 0 ? people.map((p,i)=><TrackBox key={p.id} track={p} delay={.65+i*.2} labelScale={1.3}/>) : <TrackBox track={{id:"V-21",x:791,y:536,width:98,height:101,color:"#f4cd88"}} delay={.7}/>}
      </svg>
      <div className={s.areaResult} role="status"><span className={s.statusDot}/><div><strong>{area.result}</strong><span>{area.note}</span></div></div>
    </div>
    <div className={s.ruleSummary}><div><small>WHAT</small><strong>{area.className}</strong></div><div><small>WHERE</small><strong>{area.name}</strong></div><div><small>WHEN</small><strong>{area.condition}</strong></div></div>
  </div>;
}

// Generated views explain the intended association; no simulated identities enter the live data path.
// Reference: https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_MV3DT.html
export function MultiCameraDemo() {
  return <div className={s.multiCameraStory}>
    <div className={s.viewHeading}><span>PEOPLE AND VEHICLES KEEP THEIR IDs</span><small>Illustrated camera views</small></div>
    <div className={s.cameraPair}>
      {[0, 1].map(view => {
        const reverse = view === 1;
        const personTracks = people.map((p, i) => reverse ? { ...p, x: [875, 669, 491][i], y: [257, 246, 250][i], width: [104, 99, 94][i], height: [162, 158, 143][i] } : p);
        const vehicle = { id: "V-08", x: reverse ? 980 : 620, y: reverse ? 524 : 84, width: reverse ? 275 : 168, height: reverse ? 265 : 179, color: "#f4cd88" };
        const silverVehicle = { id: "V-12", x: reverse ? 642 : 780, y: reverse ? 534 : 119, width: reverse ? 249 : 160, height: reverse ? 258 : 173, color: "#c4f3db" };
        return <figure key={view}>
          <figcaption><span>CAM 0{view + 1}</span><strong>{reverse ? "From the opposite signal" : "At the crossing"}</strong></figcaption>
          <svg viewBox={reverse ? "280 80 1300 812.5" : "280 0 1300 812.5"} role="img" aria-label={`Camera 0${view+1}: pedestrians P-17, P-23, P-31 and cars V-08 (red), V-12 (silver)`}>
            <image href={cityStoryAsset(reverse ? "crossing-referenced-reverse.png" : "crossing-referenced.png")} width="1672" height="941"/>
            {[...personTracks, vehicle, silverVehicle].map(track => <TrackBox key={track.id} track={track} labelScale={1.8} delay={reverse ? .45 : 0}/>)}
          </svg>
        </figure>;
      })}
    </div>
    <div className={s.sharedIds} role="status">{[...people, {id:"V-08",color:"#f4cd88"}, {id:"V-12",color:"#c4f3db"}].map(p=><span key={p.id} style={{color:p.color}}>{p.id}</span>)}</div>
    <div className={s.trackerExplanation}><strong>MV3DT</strong><span>Same IDs across cameras</span><b>Runs locally on Anvil T5</b></div>
  </div>;
}
