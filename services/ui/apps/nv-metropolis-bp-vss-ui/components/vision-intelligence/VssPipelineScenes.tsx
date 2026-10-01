import React, { useState } from 'react';
import s from './VssPipelineScenes.module.css';

const frames = ['story-receiving.png', 'story-receiving-inside.png', 'story-receiving-after.png'];
const positions = [{left:64.7,top:33.3,width:7.7,height:23},{left:43.7,top:41.7,width:8.3,height:24.3},{left:34.5,top:48,width:8.8,height:25.7}];
const phases = ['Approach', 'In zone', 'Clear'];
function Frame({ phase, zone = false }: {phase:number;zone?:boolean}) {
  return <div className={s.frame}>
    <img src={`/vision/${frames[phase]}`} alt={`Illustrative receiving camera: person carrying a box, ${phases[phase].toLowerCase()}`} width={1672} height={941} />
    {zone && <svg viewBox="0 0 1000 563" className={s.zone} aria-hidden="true"><path d="M440 310 590 294 610 394 448 423Z" fill={phase===1?'#edc57945':'#edc57918'} stroke="#edc579" strokeWidth="2"/><text x="470" y="445" fill="#ffe0a3" fontSize="17">Receiving zone</text></svg>}
    <span className={s.box} style={{left:`${positions[phase].left}%`,top:`${positions[phase].top}%`,width:`${positions[phase].width}%`,height:`${positions[phase].height}%`}}><b>Person · 07</b></span>
    <span className={s.camera}>02 / Receiving</span>
  </div>;
}
function Arrow({children}:{children:React.ReactNode}) { return <div className={s.arrow}><span>{children}</span><span aria-hidden="true">⟶</span></div>; }
export function VssTrackingScene() {
  const [similar,setSimilar] = useState(false);
  return <div className={s.scene}>
    <div className={s.sequence}>{frames.map((_,i)=><div key={i}><Frame phase={i}/><div className={s.frameCaption}><span>0{i+1} / {['Detect a person','Link the next observation','Keep the same track'][i]}</span><strong>07</strong></div></div>)}</div>
    <div className={s.trackLine}><i/><span>One camera · one continuous track · three observations</span><i/></div>
    <div className={s.tabs}><button aria-pressed={!similar} onClick={()=>setSimilar(false)}>Search with words</button><button aria-pressed={similar} onClick={()=>setSimilar(true)}>Find related footage</button></div>
    <div className={s.flow} aria-live="polite"><div className={s.input}><small>{similar?'SELECT AN OBJECT':'DESCRIBE WHAT YOU WANT'}</small><strong>{similar?'Person · 07':'“Person in an orange vest”'}</strong><p>{similar?'Start from a visible object in your footage.':'Describe people, objects or activities in everyday language.'}</p></div><Arrow>{similar?'Object crop':'Text query'}</Arrow><div className={s.process}><small>{similar?'OBJECT EMBEDDINGS':'SEMANTIC SEARCH'}</small><strong>{similar?'Compare appearance':'Match visual meaning'}</strong><p>{similar?'Look for similar indexed object representations.':'Compare your words with indexed video clips.'}</p></div><Arrow>Matching footage</Arrow><div className={s.output}><small>RETURN TO THE EVIDENCE</small><strong>{similar?'Related object sightings':'Relevant camera moments'}</strong><p>{similar?'Similar appearance is a lead to inspect, not proof of identity.':'Keep the camera and time attached to every result.'}</p></div></div>
    <p className={s.note}>{similar?'Related-object search requires object embeddings. It is a configurable capability, not a claim of active cross-camera identity matching in this demo.':'Detection supplies object labels; tracking connects observations within a camera. Semantic search is a parallel way to find footage.'}</p>
  </div>;
}
export function VssAgentScene() {
  const [summary,setSummary]=useState(false);
  return <div className={s.scene}>
    <div className={s.tabs}><button aria-pressed={!summary} onClick={()=>setSummary(false)}>Ask about a moment</button><button aria-pressed={summary} onClick={()=>setSummary(true)}>Summarize a period</button></div>
    <div className={s.agentFlow} aria-live="polite">
      <div className={s.question}><small>YOU ASK</small><h3>{summary?'“Summarize activity at receiving.”':'“What is the person carrying?”'}</h3><div className={s.sourceChip}>Camera 02 · {summary?'Selected time range':'Selected video window'}</div><img src="/vision/story-receiving-inside.png" alt="The receiving footage supplied as context"/></div>
      <div className={s.reasoning}><div className={s.routeLabel}>FOOTAGE → GROUNDED RESPONSE</div><div><b>01</b><section><h4>{summary?'Prepare source history':'Inspect the footage'}</h4><p>{summary?'Process the selected footage into captions and searchable history.':'Sample the selected video window for visual analysis.'}</p></section></div><span className={s.down}>↓</span><div><b>02</b><section><h4>{summary?'Retrieve relevant history':'Reason about the scene'}</h4><p>{summary?'Give the AI agent the observations relevant to your question.':'Cosmos Reason evaluates the visible evidence against the question.'}</p></section></div><span className={s.down}>↓</span><div><b>03</b><section><h4>Answer with context</h4><p>Keep the source and inspected period alongside the response.</p></section></div></div>
      <div className={s.answer}><small>ILLUSTRATIVE ANSWER</small><span className={s.answerMark}>✳</span><h3>{summary?'A concise account of activity.':'A box, held in both hands.'}</h3><p>{summary?'A person in an orange vest crossed the receiving floor carrying a cardboard box, passing through the marked area.':'The person is carrying a cardboard box across the receiving floor.'}</p><div className={s.evidence}><span>Evidence context</span><strong>Camera 02 / Receiving</strong><span>{summary?'Summary of the prepared period':'Inspected video window'}</span></div></div>
    </div><p className={s.note}>{summary?'Period summaries require prepared source history; recording and embedding alone do not create it. Playable citations depend on retained footage and available references.':'A live question inspects a recent video window. The response describes the selected footage, rather than every camera at once.'}</p>
  </div>;
}
export function VssAlertScene() {
  const [area,setArea]=useState(true); const [phase,setPhase]=useState(1);
  const triggered=!area||phase===1; const cleared=area&&phase===2;
  return <div className={s.scene}>
    <div className={s.tabs}><button aria-pressed={area} onClick={()=>setArea(true)}>Area entry</button><button aria-pressed={!area} onClick={()=>setArea(false)}>Visual condition</button></div>
    <div className={s.alertFlow}>
      <div className={s.rule}><small>01 / DEFINE THE RULE</small><h3>{area?'Person enters receiving zone':'Someone is carrying a box'}</h3><label>Camera<span>02 · Receiving</span></label><label>{area?'Object class':'Condition'}<span>{area?'Person':'Describe the activity'}</span></label><label>{area?'Region':'Evaluation'}<span>{area?'Marked floor area':'Sampled video windows'}</span></label><p>{area?'Detection + tracking locate a person relative to your configured region.':'A visual model checks sampled footage against your written condition.'}</p></div>
      <div className={s.alertCamera}><small>02 / EVALUATE THE FOOTAGE</small><Frame phase={phase} zone={area}/><div className={s.phaseControls}>{phases.map((label,i)=><button key={label} aria-pressed={phase===i} onClick={()=>setPhase(i)}>{label}</button>)}</div><p>{area?(phase===0?'Outside the region':phase===1?'Person 07 intersects the region':'Person 07 has left the region'):'The box-carrying condition is visible in this sample.'}</p></div>
      <div className={`${s.verdict} ${triggered||cleared?s.observed:''}`} aria-live="polite"><small>03 / REVIEW THE RESULT</small><span className={s.verdictIcon}>{triggered?'!':cleared?'✓':'—'}</span><h3>{triggered?'Condition observed':cleared?'Zone clear. Evidence retained.':'No entry yet.'}</h3><p>{triggered?'Create an event candidate with its camera, time and supporting footage.':cleared?'The earlier event remains available for an operator to inspect.':'The person is visible, but has not entered the configured region.'}</p>{(triggered||cleared)&&<div className={s.event}><span>Event candidate</span><strong>{area?'Person in receiving zone':'Person carrying a box'}</strong><span>Camera 02 · Review with footage</span></div>}</div>
    </div><p className={s.note}>Interactive illustration, not a live alert. Visual conditions use sampled windows; area rules use configured detection and tracking analytics. Review candidates against their evidence.</p>
  </div>;
}
