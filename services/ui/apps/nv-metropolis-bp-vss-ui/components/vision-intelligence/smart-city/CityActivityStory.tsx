// SPDX-License-Identifier: MIT
import React, { useState } from "react";
import { cityStoryAsset } from "./cityStoryAssets";
import s from "./CityActivityStory.module.css";

const metrics = [
  { name:"People", unit:"Crossings per 15 minutes", values:[18,26,43,68,94,76,49,30], max:100, insight:"Crossing demand peaks around 08:00" },
  { name:"Vehicles", unit:"Vehicles per 15 minutes", values:[40,65,90,130,160,125,85,55], max:200, insight:"Vehicle volume rises during the morning peak" },
  { name:"Stopped time", unit:"Average stopped time · seconds", values:[8,12,20,35,56,44,28,15], max:60, insight:"Stopped time builds up as traffic gets busier" },
] as const;

export function ActivityOverTime({ onInteract }: { onInteract?: () => void }) {
  const [selected, setSelected] = useState(0);
  const metric = metrics[selected];
  return <div className={s.activity}>
    <div className={s.heading}><span>The same intersection over time</span><small>Illustrative sample data</small></div>
    <div className={s.snapshots}>
      {[['07:00','intersection-referenced.png','Before the peak'],['08:00','intersection-queue.png','Morning peak'],['09:00','intersection-referenced.png','Traffic eases']].map(([time,asset,label])=><figure key={time}>
        <img src={cityStoryAsset(asset)} alt={label}/><figcaption><strong>{time}</strong><span>{label}</span></figcaption>
      </figure>)}
    </div>
    <div className={s.controls} role="group" aria-label="Activity metric">{metrics.map((item,i)=><button type="button" key={item.name} aria-pressed={selected===i} onClick={()=>{onInteract?.();setSelected(i);}}>{item.name}</button>)}</div>
    <div className={s.unit}>{metric.unit}</div>
    <svg className={s.chart} viewBox="0 0 800 250" role="img" aria-label={`${metric.unit}: ${metric.values.join(', ')}. Illustrative 15-minute intervals from 07:00 to 09:00.`}>
      {[0,.5,1].map(f=><g key={f}><line x1="50" x2="778" y1={205-f*170} y2={205-f*170} stroke="#365344"/><text x="38" y={210-f*170} textAnchor="end">{metric.max*f}</text></g>)}
      {metric.values.map((value,i)=><rect key={i} x={65+i*88} y={205-value/metric.max*170} width="52" height={value/metric.max*170} rx="4" fill={i===4?'#d9bc7e':'#9bc7af'} />)}
      {['07:00','07:30','08:00','08:30','09:00'].map((time,i)=><text key={time} x={50+i*182} y="236" textAnchor="middle">{time}</text>)}
    </svg>
    <p className={s.insight} role="status">{metric.insight}</p>
  </div>;
}
