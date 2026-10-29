// SPDX-License-Identifier: MIT
import React from "react";
import { IconArrowRight, IconFileText, IconVideo } from "@tabler/icons-react";
import { cityStoryAsset } from "./cityStoryAssets";
import s from "./CityClosingStory.module.css";

export function CityClosingStory({ title, description }: { title: string; description: string }) {
  return <div className={s.closing}>
    <header className={s.heading}>
      <span>FROM SIMULATION TO YOUR SITE</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
    <div className={s.composition}>
      <section className={s.scenarios} aria-label="Test scenarios in Isaac Sim on DGX Spark">
        <div className={s.sceneStack}>
          {[
            ["intersection-referenced.png", "Crossings"],
            ["intersection-queue.png", "Queues"],
            ["intersection-emergency.png", "Emergency access"],
          ].map(([asset,label],i)=><figure key={asset} style={{ "--card":i } as React.CSSProperties}>
            <img src={cityStoryAsset(asset)} alt={label}/><figcaption>{label}</figcaption>
          </figure>)}
        </div>
        <h2>Test difficult scenarios</h2>
        <p>Isaac Sim on DGX Spark</p>
      </section>
      <section className={s.engine} aria-label="Run the full analytics workflow locally on Anvil T5">
        <div className={s.deviceStage}>
          <div className={s.halo} aria-hidden="true"/>
          <img src="/vision/anvil-t5.png" alt="Anvil T5 edge computer"/>
        </div>
        <h2>Anvil T5 <span>+ VSS</span></h2>
        <p>Detection, tracking and local recording</p>
      </section>
      <section className={s.evidence} aria-label="Keep source video, events and reports for review">
        <div className={s.paperStack}>
          <div className={s.paper}>
            <div className={s.paperHeading}><IconFileText size={21} aria-hidden="true"/><span>Event report</span></div>
            <img src={cityStoryAsset("intersection-emergency.png")} alt="Source footage linked to an event report"/>
            <i/><i/><i/>
            <div className={s.paperFoot}><IconVideo size={15} aria-hidden="true"/> Source video attached</div>
          </div>
        </div>
        <h2>Keep the evidence</h2>
        <p>Saved video, events and reports</p>
      </section>
    </div>
    <div className={s.deployment}>
      <div className={s.siteCameras} aria-hidden="true"><IconVideo/><IconVideo/></div>
      <div><small>WHEN YOU MOVE TO THE REAL SITE</small><strong>Connect real cameras to the same Anvil T5</strong></div>
      <span className={s.rtsp}>RTSP <IconArrowRight size={20} aria-hidden="true"/></span>
    </div>
  </div>;
}
