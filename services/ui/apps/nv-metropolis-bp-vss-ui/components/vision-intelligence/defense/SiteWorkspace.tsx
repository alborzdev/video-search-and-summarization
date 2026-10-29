// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import { IconArrowLeft, IconArrowRight, IconMap, IconLayersSubtract, IconCheck, IconMessage, IconVideo } from '@tabler/icons-react';
import type { DefenseSnapshot } from './types';
import { evidenceFor } from './fixtures';
import { MediaFrame } from './MediaFrame';
import { DefenseDialog } from './Dialog';
import styles from './Defense.module.css';

const sequence = [
  { time: '14:32:04', title: 'Approaches gate' },
  { time: '14:32:08', title: 'Crosses boundary' },
  { time: '14:32:14', title: 'Inside zone' },
];
export function SiteWorkspace({ snapshot, onReport }: { snapshot: DefenseSnapshot; onReport: () => void }) {
  const preview = snapshot.provenance === 'illustrative';
  const [investigate, setInvestigate] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [layers, setLayers] = useState(true);
  const [plan, setPlan] = useState(false);
  const [selected, setSelected] = useState(1);
  const evidence = evidenceFor(snapshot, 'gate');
  return <>
    <div className={styles.heading}>
      <div><h1>{investigate ? 'Event 014 · Investigation' : preview ? 'Person entered storage zone' : 'Site security'}</h1>{preview && !investigate && <span className={acknowledged ? styles.pill : styles.warningPill}>{acknowledged ? 'Acknowledged · preview' : 'Needs review'}</span>}</div>
      <div className={styles.actions}>{investigate ? <button onClick={() => setInvestigate(false)}><IconArrowLeft size={17} />Back to event</button> : <><button onClick={() => setPlan(true)}><IconMap size={17} />Site plan</button><button aria-pressed={layers} onClick={() => setLayers(!layers)}><IconLayersSubtract size={17} />Layers</button></>}</div>
    </div>
    <div className={investigate ? styles.investigationGrid : styles.siteGrid}>
      <div className={styles.cameraColumn}>
        <MediaFrame evidence={evidence} title="Camera 01 · Storage gate" overlay={layers && !investigate ? 'gate' : undefined} />
        {preview && <div className={styles.sequenceBar} aria-label="Illustrative event sequence">
          <span>Example sequence · still image</span>
          <div>{sequence.map((item, index) => <button key={item.time} aria-pressed={selected === index} onClick={() => setSelected(index)}><b>{index + 1}</b><span>{item.time}</span><small>{item.title}</small></button>)}</div>
        </div>}
        {!investigate && <div className={styles.cameraHints}><span><IconVideo size={17} />Camera 02 · Service yard <small>Not connected</small></span><span><IconVideo size={17} />Camera 03 · Approach <small>Not connected</small></span></div>}
      </div>
      <aside className={styles.inspector}>
        {!preview ? <><h2>No observations available</h2><p>Connect a source and a reviewed zone rule to receive entry events.</p><p className={styles.muted}>No camera footage or inference is attached to this workspace.</p></> : investigate ? <>
          <h2>What happened at the storage gate?</h2><p className={styles.muted}>Camera 01 · 14:32:00–14:32:20</p>
          <span className={styles.example}>Example response · not generated</span>
          <h3 className={styles.answer}>One person crossed into zone B.</h3>
          <div className={styles.evidenceRows}>{sequence.map((item, index) => <button key={item.time} aria-pressed={selected === index} onClick={() => setSelected(index)}><b>{index + 1}</b><span>{item.title}</span><time>{item.time}</time></button>)}</div>
          <p className={styles.scope} role="status">Selected example: {sequence[selected].title}. Video seek requires a recorded clip.</p>
          <div className={styles.limitation}><strong>Not established</strong><p>Identity and entry permission are not available from this footage.</p></div>
          <button className={styles.primary} onClick={onReport}>Create incident report<IconArrowRight size={18} /></button>
          <label className={styles.field}>Ask a follow-up<input disabled placeholder="Connect footage to ask the analyst" /></label>
        </> : <>
          <span className={styles.eyebrow}>EVENT 014</span><h2>Boundary crossed</h2>
          <dl className={styles.facts}><div><dt>Zone</dt><dd>Storage zone B</dd></div><div><dt>Example time</dt><dd>14:32:08</dd></div><div><dt>Source</dt><dd>Camera 01</dd></div></dl>
          <h3>Event sequence</h3><div className={styles.eventRows}>{sequence.map((item, index) => <button key={item.time} aria-pressed={selected === index} onClick={() => setSelected(index)}><time>{item.time}</time><span>{item.title}</span></button>)}</div>
          <p className={styles.muted}>Entry permission not established.</p>
          <button className={styles.primary} onClick={() => setInvestigate(true)}>Review evidence<IconArrowRight size={18} /></button>
          <button onClick={() => setAcknowledged(!acknowledged)}>{acknowledged ? <><IconCheck size={18} />Acknowledged · undo</> : 'Acknowledge'}</button>
          <button className={styles.quiet} onClick={() => setInvestigate(true)}><IconMessage size={18} />Ask about this event<IconArrowRight size={17} /></button>
        </>}
      </aside>
    </div>
    {plan && <DefenseDialog title="Site plan" onClose={() => setPlan(false)}>
      <div className={styles.noMedia}><IconMap size={36} /><strong>Site plan not configured</strong><span>The final environment will supply a static map, camera positions and calibration.</span></div>
      <p className={styles.muted}>Image-space zone entry can work before a ground map is available.</p>
    </DefenseDialog>}
  </>;
}
