// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { IconArrowLeft, IconArrowRight, IconChartBar, IconDownload, IconFileText, IconPlayerPlay, IconSearch, IconVideo } from '@tabler/icons-react';
import type { CityWorkspaceView } from './types';
import styles from './CityEdgePage.module.css';

const PRIORITIES = ['Turning traffic', 'Queue build-up', 'Pedestrian crossing', 'Curb access', 'Blocked crossing'];
const STEPS = [
  { title: 'See', text: 'Detect and track people and vehicles.', icon: IconVideo, image: 'southwest', view: 'overview' },
  { title: 'Understand', text: 'Measure movement, queue, crossing and curb activity.', icon: IconChartBar, image: 'overview', view: 'measurements' },
  { title: 'Review', text: 'Open the footage behind a finding.', icon: IconPlayerPlay, image: 'northeast', view: 'search' },
  { title: 'Decide', text: 'Give traffic teams evidence for the next action.', icon: IconFileText, image: null, view: null },
] as const;

export interface DeploymentRequirements { siteType: string; cameras: number; priorities: string[]; retention: string; notes: string; }
export function deploymentBrief(requirements: DeploymentRequirements) {
  if (!Number.isSafeInteger(requirements.cameras) || requirements.cameras < 1 || requirements.cameras > 10000 || !requirements.priorities.length || requirements.priorities.some(value => !PRIORITIES.includes(value))) return null;
  return { schemaVersion: 'city.pilot-discussion.v1', generatedAt: new Date().toISOString(),
    requirements: { ...requirements, notes: requirements.notes.trim().slice(0, 2000) },
    demoReference: 'Two Isaac Sim cameras on the local edge system. Counts and events are camera-owned.',
    nextStep: 'Review camera placement, scene conditions, retention, integrations and compute with the team.',
    scope: 'Discussion requirements only. This is not a hardware quote, capacity calculation, accuracy result or deployment guarantee.' };
}

/** Educational navigation and a local requirements handoff; no extra video decoding or inference. */
export function CityEdgePage({ cameraCount, liveCameraCount, onView, onReview }: {
  cameraCount: number; liveCameraCount: number; onView: (view: CityWorkspaceView) => void; onReview: () => void;
}) {
  const pageRoot = useRef<HTMLElement>(null);
  const [briefOpen, setBriefOpen] = useState(false);
  useEffect(() => { const root=pageRoot.current; if(root) { root.scrollTop=0; const main=root.closest('main'); if(main) main.scrollTop=0; } },[briefOpen]);
  const [requirements, setRequirements] = useState<DeploymentRequirements>({ siteType: 'Signalized intersection', cameras: 2, priorities: PRIORITIES.slice(0, 3), retention: 'Discuss with the team', notes: '' });
  const [saved, setSaved] = useState(false);
  const update = (change: Partial<DeploymentRequirements>) => { setSaved(false); setRequirements(value => ({ ...value, ...change })); };
  const save = () => {
    const brief = deploymentBrief(requirements); if (!brief) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(brief, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'smart-city-pilot-discussion.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setSaved(true);
  };
  if (briefOpen) return <section ref={pageRoot} className={styles.page} aria-label="Edge AI pilot discussion">
    <button type="button" className={styles.back} onClick={() => setBriefOpen(false)}><IconArrowLeft size={18} />Back to Why edge AI</button>
    <header className={styles.heading}><div><h1>Plan an edge AI pilot</h1><p>Turn the demo into a focused discussion about your site.</p></div></header>
    <div className={styles.briefGrid}>
      <form className={styles.form} onSubmit={event => { event.preventDefault(); save(); }} id="city-pilot-requirements">
        <h2>Your pilot requirements</h2>
        <label>Site type<select value={requirements.siteType} onChange={event => update({ siteType: event.target.value })}>{['Signalized intersection', 'Curbside corridor', 'Pedestrian crossing', 'Other traffic site'].map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Planned camera count<input type="number" min="1" max="10000" step="1" required value={Number.isNaN(requirements.cameras) ? '' : requirements.cameras} onChange={event => update({ cameras: event.target.value === '' ? NaN : Number(event.target.value) })} /></label>
        <fieldset><legend>Monitoring priorities</legend>{PRIORITIES.map(value => <label key={value} className={styles.check}><input type="checkbox" checked={requirements.priorities.includes(value)} onChange={event => update({ priorities: event.target.checked ? [...requirements.priorities, value] : requirements.priorities.filter(item => item !== value) })} />{value}</label>)}</fieldset>
        {!requirements.priorities.length && <p className={styles.note}>Choose at least one monitoring priority.</p>}
        <label>Retention requirement<select value={requirements.retention} onChange={event => update({ retention: event.target.value })}>{['Discuss with the team', 'Live review only', 'Short event clips', 'Site retention policy'].map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Notes (optional)<textarea rows={3} maxLength={2000} placeholder="Camera locations, lighting, networking, or integration needs" value={requirements.notes} onChange={event => update({ notes: event.target.value })} /></label>
      </form>
      <section className={styles.summary} aria-label="Discussion brief"><h2>Discussion brief</h2><div className={styles.briefImages}><img src="/smart-city/demo-v9/southwest.png" alt="Captured southwest simulator view" loading="lazy" /><img src="/smart-city/demo-v9/northeast.png" alt="Captured northeast simulator view" loading="lazy" /></div><span className={styles.imageNote}>Demo images · Not live video</span>
        <dl><div><dt>Site type</dt><dd>{requirements.siteType}</dd></div><div><dt>Planned camera count</dt><dd>{Number.isSafeInteger(requirements.cameras) ? requirements.cameras : 'Enter a whole number'}</dd></div><div><dt>Monitoring priorities</dt><dd>{requirements.priorities.length ? <ul>{requirements.priorities.map(value => <li key={value}>{value}</li>)}</ul> : 'Choose a priority'}</dd></div><div><dt>Retention requirement</dt><dd>{requirements.retention}</dd></div></dl>
        <footer><h3>Demo reference</h3><p>Two Isaac Sim cameras on the local edge system.</p><p>Counts and events are camera-owned.</p></footer>
      </section>
    </div>
    <div className={styles.briefActions}><button type="submit" form="city-pilot-requirements" className={styles.primary} disabled={!deploymentBrief(requirements)}><IconDownload size={18} />Download discussion brief</button><button type="button" className={styles.secondary} onClick={() => onView('overview')}><IconArrowLeft size={18} />Return to demo</button><div><p>{saved ? 'Discussion brief downloaded.' : 'Saved as a local file. No contact details are sent.'}</p><span>Use this brief to scope a pilot. Camera capacity and accuracy need site-specific validation.</span></div></div>
    {saved && <span role="status" className={styles.saved}>Discussion brief downloaded.</span>}
  </section>;
  return <section ref={pageRoot} className={styles.page} aria-label="Why edge AI">
    <header className={styles.heading}><div><h1>From camera feeds to useful traffic evidence.</h1><p>Analyze video close to the cameras. Give traffic teams events, measurements and reviewable footage.</p></div><div className={styles.actions}><button type="button" className={styles.primary} onClick={() => setBriefOpen(true)}><IconFileText size={18} />Build a deployment brief</button><button type="button" className={styles.secondary} onClick={() => onView('overview')}><IconArrowLeft size={18} />Back to live intersection</button></div></header>
    <div className={styles.workflow}><figure className={styles.hero}><img src="/smart-city/demo-v9/southwest.png" alt="The actual simulated city intersection used by this demonstration" /><figcaption>Two simulated cameras · One intersection<span>Demo image · Not live video</span></figcaption></figure>
      <ol className={styles.steps}>{STEPS.map((step, index) => <li key={step.title}><button type="button" onClick={() => step.view === 'search' ? onReview() : step.view ? onView(step.view) : setBriefOpen(true)}><span className={styles.number}>{String(index + 1).padStart(2, '0')}</span><step.icon size={26} stroke={1.6} /><span className={styles.stepCopy}><strong>{step.title}</strong><span>{step.text}</span></span>{step.image ? <img src={`/smart-city/demo-v9/${step.image}.png`} alt="Captured simulator example" loading="lazy" /> : <IconArrowRight size={24} />}</button></li>)}</ol>
    </div>
    <footer className={styles.proof}><section><h2>Shown on this demo</h2><p><IconVideo size={20} />{liveCameraCount === cameraCount && cameraCount > 0 ? `${cameraCount === 2 ? 'Two' : cameraCount} live camera feeds` : `${cameraCount} configured cameras · ${liveCameraCount} live`}</p><p><IconChartBar size={20} />Camera-owned measurements</p><p><IconSearch size={20} />Local video questions and clip search</p></section><section><h2>Plan for your site</h2><p>Camera placement, scene conditions, retention and workload determine the system you need.</p><button type="button" className={styles.link} onClick={() => onView('overview')}>Explore the city problems<IconArrowRight size={17} /></button></section><section className={styles.scope}><h2>Why process at the edge?</h2><p>Run video analysis on the camera network. Share selected evidence and results with operations.</p><small>This prototype supports operator review. It does not control traffic signals.</small></section></footer>
  </section>;
}
