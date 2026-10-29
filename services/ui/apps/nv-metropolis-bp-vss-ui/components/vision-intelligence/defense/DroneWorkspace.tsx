// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import { IconArrowRight, IconFileDescription, IconPhoto, IconCheck } from '@tabler/icons-react';
import type { DefenseSnapshot } from './types';
import { evidenceFor } from './fixtures';
import { MediaFrame } from './MediaFrame';
import { InspectionMap } from './InspectionMap';
import { DefenseDialog } from './Dialog';
import styles from './Defense.module.css';

export function DroneWorkspace({ snapshot, onReport }: { snapshot: DefenseSnapshot; onReport: () => void }) {
  const preview = snapshot.provenance === 'illustrative';
  const [view, setView] = useState<'survey' | 'inspect'>('survey');
  const [request, setRequest] = useState(false);
  const [details, setDetails] = useState(false);
  const [history, setHistory] = useState(false);
  return <>
    <div className={styles.heading}><div><h1>{view === 'survey' ? 'Airfield surface survey' : 'Inspect finding 03'}</h1>{view === 'inspect' && <span className={styles.muted}>Possible loose object · Service apron</span>}</div>
      <nav className={styles.steps} aria-label="Inspection workflow"><button aria-current={view === 'survey' ? 'step' : undefined} onClick={() => setView('survey')}>1 <span>Survey</span></button><button disabled={!preview} aria-current={view === 'inspect' ? 'step' : undefined} onClick={() => setView('inspect')}>2 <span>Inspect</span></button><button disabled={!preview} onClick={onReport}>3 <span>Report</span></button></nav>
    </div>
    {view === 'survey' ? <div className={styles.surveyGrid}>
      <InspectionMap preview={preview} onInspect={preview ? () => setView('inspect') : undefined} />
      <aside className={styles.inspector}><div className={styles.split}><h2>Review queue</h2><span>{preview ? '1 finding' : 'No findings'}</span></div>
        {preview ? <><button className={styles.finding} onClick={() => setView('inspect')}><b>03</b><div><strong>Possible loose object</strong><span>Service apron</span><small>First pass · 14:32:08</small></div><img src="/defense-preview/drone-wide.png" alt="Illustrative first-pass image" /></button>
          <MediaFrame evidence={evidenceFor(snapshot, 'pass')} title="First pass" />
          <button className={styles.primary} onClick={() => setView('inspect')}>Inspect finding<IconArrowRight size={18} /></button>
          <button onClick={() => setHistory(!history)} aria-expanded={history}>Show capture history</button>
          {history && <ol className={styles.history}><li>14:32:08 · First pass example</li><li>14:32:16 · View request example</li><li>14:32:24 · Closer image example</li></ol>}
        </> : <p>Connect an inspection camera to collect images and review findings.</p>}
        <p className={styles.limitation}>Coverage records captured images, not surface clearance.</p>
      </aside>
    </div> : <>
      <div className={styles.compareGrid}><MediaFrame evidence={evidenceFor(snapshot, 'pass')} title="First pass" /><MediaFrame evidence={evidenceFor(snapshot, 'close')} title="Closer view" /></div>
      <div className={styles.decisionTray}><div><h2>Object observed on the surface</h2><p>Closer image example. Removal has not been checked.</p></div><div className={styles.captureSteps}><span><IconCheck size={16} />First pass</span><span><IconCheck size={16} />Closer view example</span></div><div className={styles.actions}><button onClick={() => setDetails(true)}><IconPhoto size={18} />Image details</button><button onClick={() => setRequest(true)}>Request another view</button><button className={styles.primary} onClick={onReport}><IconFileDescription size={18} />Add finding to report</button></div></div>
    </>}
    {request && <DefenseDialog title="Request another view" onClose={() => setRequest(false)}><p>A real capture request needs a connected camera controller, a valid viewpoint and a returned capture ID.</p><p className={styles.muted}>No drone or camera command has been sent. This preview contains two illustrative stills.</p><button className={styles.primary} onClick={() => { setRequest(false); setDetails(true); }}>Review available image details</button></DefenseDialog>}
    {details && <DefenseDialog title="Image details" onClose={() => setDetails(false)}><dl className={styles.facts}><div><dt>Source</dt><dd>Camera D1 (illustrative)</dd></div><div><dt>First pass</dt><dd>14:32:08 · example time</dd></div><div><dt>Closer image</dt><dd>14:32:24 · example time</dd></div><div><dt>Pose / calibration</dt><dd>Not supplied</dd></div><div><dt>Provenance</dt><dd>AI-generated design assets, not camera evidence</dd></div></dl></DefenseDialog>}
  </>;
}
