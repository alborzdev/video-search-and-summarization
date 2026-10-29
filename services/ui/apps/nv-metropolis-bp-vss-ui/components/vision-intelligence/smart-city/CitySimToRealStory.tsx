// SPDX-License-Identifier: MIT
import React from "react";
import { IconArrowRight, IconCheck, IconVideo } from "@tabler/icons-react";
import { cityStoryAsset } from "./cityStoryAssets";
import s from "./CitySimToRealStory.module.css";

export function SparkProduct() {
  return <svg viewBox="45 265 716 257" role="img" aria-label="NVIDIA DGX Spark" className={s.spark} style={{ viewTransitionName: "city-story-spark" } as React.CSSProperties}>
    <image href={cityStoryAsset("dgx-spark.png")} width="800" height="800" />
  </svg>;
}

export function SimToRealStory() {
  return <div className={s.workflow}>
  <div className={s.flow} role="group" aria-label="Virtual cameras in the digital twin on DGX Spark stream over RTSP to the Anvil T5 for analytics testing and validation">
    <section className={s.stage}>
      <header><small>SIMULATION</small><h2>Test in a digital twin</h2></header>
      <div className={s.input}>
        <div className={s.twinFrame}>
          <svg viewBox="0 0 1672 941" role="img" aria-label="Customizable digital twin with virtual camera positions" style={{ viewTransitionName: "city-story-twin" } as React.CSSProperties}>
            <image href={cityStoryAsset("intersection-referenced.png")} width="1672" height="941" />
            {[[1043,522],[518,405],[1118,260],[642,202]].map(([x,y],i)=><g key={i} transform={`translate(${x} ${y})`}>
              <circle r="18" fill="#0b1c14" stroke="#b8f1d4" strokeWidth="4" />
              <text textAnchor="middle" y="7" fill="#d5f5e4" fontSize="21">{i+1}</text>
            </g>)}
          </svg>
        </div>
        <span>Place virtual cameras in Isaac Sim</span>
      </div>
      <figure className={s.hardware}>
        <div className={s.product}><SparkProduct /></div>
        <figcaption>DGX Spark<span>Runs the environment and virtual cameras</span></figcaption>
      </figure>
    </section>
    <div className={s.transfer}>
      <span className={s.cameraHeading}>Virtual cameras</span>
      <div className={s.virtualCameras} aria-label="Four virtual cameras inside the digital twin">
        {[1,2,3,4].map(id=><div key={id}><IconVideo stroke={1.4} aria-hidden="true"/><span>0{id}</span></div>)}
      </div>
      <div className={s.streamLink}><strong>RTSP</strong></div>
      <IconArrowRight className={s.outgoing} aria-hidden="true" />
    </div>
    <section className={s.stage}>
      <header><small>LOCAL ANALYTICS</small><h2>Run the full pipeline</h2></header>
      <figure className={s.analyticsDevice}>
        <img src="/vision/anvil-t5.png" alt="Connect Tech Anvil-T5 with NVIDIA Jetson Thor" />
        <figcaption>Anvil T5<span>Your real analytics software + VSS</span></figcaption>
      </figure>
      <div className={s.validation}>
        {["Detect and track", "Measure zones and events", "Save video and reports"].map(label=><span key={label}><IconCheck size={16} aria-hidden="true" />{label}</span>)}
      </div>
    </section>
  </div>

  </div>;
}
