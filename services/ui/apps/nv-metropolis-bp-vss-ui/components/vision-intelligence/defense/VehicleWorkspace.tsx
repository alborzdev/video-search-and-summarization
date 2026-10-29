// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import { IconAlertTriangle, IconVideo } from '@tabler/icons-react';
import type { DefenseSnapshot } from './types';
import { evidenceFor } from './fixtures';
import { MediaFrame } from './MediaFrame';
import styles from './Defense.module.css';

const cameras = [{ id:'rear', name:'Rear' }, { id:'left', name:'Left' }, { id:'right', name:'Right' }, { id:'front', name:'Front' }, { id:'front-left', name:'Front left' }, { id:'front-right', name:'Front right' }];
export function VehicleWorkspace({ snapshot, onReport }: { snapshot: DefenseSnapshot; onReport: () => void }) {
  const preview = snapshot.provenance === 'illustrative';
  const [selected, setSelected] = useState('rear');
  const [review, setReview] = useState(false);
  const evidence = evidenceFor(snapshot, selected);
  return <>
    <div className={styles.heading}><div><h1>Surroundings</h1><div className={styles.modeTabs}><button aria-pressed={!review} onClick={() => setReview(false)}>Drive view</button><button aria-pressed={review} onClick={() => setReview(true)}>Review</button></div></div><span className={styles.muted}>Driver remains in control</span></div>
    <div className={styles.vehicleGrid}><div>
      <MediaFrame evidence={evidence} title={cameras.find(camera => camera.id === selected)?.name + ' camera'} overlay={selected === 'rear' ? 'person' : undefined} />
      {preview && selected === 'rear' && <div className={styles.caution}><IconAlertTriangle size={19} />Person behind vehicle <small>Illustrative observation</small></div>}
    </div><aside className={styles.coverage}><h2>Camera coverage</h2><p className={styles.muted}>Schematic · not measured</p>
      <svg viewBox="0 0 300 290" role="img" aria-label="Schematic camera positions; no calibrated coverage available">
        <defs><pattern id="vehicle-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(40)"><line x1="0" y1="0" x2="0" y2="7" stroke="#657570" strokeWidth="2" /></pattern></defs>
        {cameras.map((camera, i) => { const angles = [180,270,90,0,315,45]; const available = preview && Boolean(evidenceFor(snapshot,camera.id)); return <g key={camera.id} transform={'rotate('+angles[i]+' 150 145)'}><path d="M132 106L101 35Q150 9 199 35L168 106Z" fill={available ? '#183f39' : 'url(#vehicle-hatch)'} stroke={available ? '#4fc7bb' : '#52615d'} /></g>; })}
        <rect x="127" y="103" width="46" height="85" rx="7" fill="#26332c" stroke="#89938a" /><rect x="132" y="108" width="36" height="23" rx="3" fill="#53634f" /><path d="M150 102V85M144 92L150 85L156 92" fill="none" stroke="#91a69e" />
        <text x="150" y="47">F</text><text x="63" y="82">FL</text><text x="240" y="82">FR</text><text x="34" y="157">L</text><text x="267" y="157">R</text><text x="150" y="260">REAR</text>
        {preview && <circle cx="150" cy="221" r="6" fill="#ffbd45" />}
      </svg><div className={styles.legend}><span>Illustrative view</span><span>Not connected</span></div>
    </aside></div>
    <div className={styles.sideViews}><MediaFrame evidence={evidenceFor(snapshot, 'left')} title="Left side" /><MediaFrame evidence={evidenceFor(snapshot, 'right')} title="Right side" /></div>
    <div className={styles.cameraSelector} aria-label="Vehicle camera selection">{cameras.map(camera => <button key={camera.id} aria-pressed={selected === camera.id} onClick={() => setSelected(camera.id)}><IconVideo size={16} />{camera.name}{!evidenceFor(snapshot, camera.id) && <small>Not connected</small>}</button>)}</div>
    {review && <div className={styles.decisionTray}><div><h2>Vehicle surroundings review</h2><p>{preview ? 'Review the example observation and add analyst notes.' : 'Recorded footage is needed for historical review.'}</p></div><button className={styles.primary} disabled={!preview} onClick={onReport}>Create review draft</button></div>}
  </>;
}
