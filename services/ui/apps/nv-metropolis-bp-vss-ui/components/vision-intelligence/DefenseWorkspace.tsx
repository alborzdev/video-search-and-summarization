// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import { IconShieldCheck, IconDrone, IconTruck, IconPlugConnected, IconInfoCircle } from '@tabler/icons-react';
import type { DefenseMode, DefenseScenario } from './defense/types';
import { snapshotFor } from './defense/fixtures';
import { SiteWorkspace } from './defense/SiteWorkspace';
import { DroneWorkspace } from './defense/DroneWorkspace';
import { VehicleWorkspace } from './defense/VehicleWorkspace';
import { ReportDraft } from './defense/ReportDraft';
import { DefenseDialog } from './defense/Dialog';
import styles from './defense/Defense.module.css';
import { LocalVisionLauncher } from './LocalVisionLauncher';

const scenarios = [{ id:'site', name:'Site security', icon:IconShieldCheck }, { id:'drone', name:'Drone inspection', icon:IconDrone }, { id:'vehicle', name:'Vehicle awareness', icon:IconTruck }] as const;
export function DefenseWorkspace({ onOpenSources, onOpenExplainer }: { onOpenSources: () => void; onOpenExplainer?: () => void }) {
  const [scenario, setScenario] = useState<DefenseScenario>('site');
  const [mode, setMode] = useState<DefenseMode>('preview');
  const [report, setReport] = useState(false);
  const [connections, setConnections] = useState(false);
  const snapshot = snapshotFor(mode);
  return <div className={styles.workspace} data-testid="defense-workspace">
    <div className={styles.toolbar}><nav aria-label="Defense scenarios" className={styles.scenarios}>{scenarios.map(({ id, name, icon:Icon }) => <button key={id} aria-pressed={scenario === id} onClick={() => { setScenario(id); setReport(false); }}><Icon size={19} />{name}</button>)}</nav>
      <div className={styles.actions}>{onOpenExplainer && <button onClick={onOpenExplainer}>How it works</button>}<LocalVisionLauncher captureSelector='[data-testid="defense-workspace"] [data-local-vision-source]' /><label className={styles.modeLabel}><span>Data</span><select aria-label="Defense data mode" value={mode} onChange={event => { setMode(event.target.value as DefenseMode); setReport(false); }}><option value="preview">Design preview</option><option value="disconnected">No sources connected</option></select></label><button onClick={() => setConnections(true)} aria-label="Defense source readiness"><IconPlugConnected size={18} /><span>Sources</span></button></div>
    </div>
    <div className={styles.content} key={mode}>
      <div hidden={scenario !== 'site'}><SiteWorkspace snapshot={snapshot} onReport={() => setReport(true)} /></div>
      <div hidden={scenario !== 'drone'}><DroneWorkspace snapshot={snapshot} onReport={() => setReport(true)} /></div>
      <div hidden={scenario !== 'vehicle'}><VehicleWorkspace snapshot={snapshot} onReport={() => setReport(true)} /></div>
    </div>
    <footer className={styles.footer}><span><IconInfoCircle size={14} />{mode === 'preview' ? 'Illustrative imagery & example events · no live inference' : 'No camera sources connected · no observations available'}</span><span>Processing target: local</span></footer>
    {report && <ReportDraft mode={mode} scenario={scenario} onClose={() => setReport(false)} />}
    {connections && <DefenseDialog title="Defense source readiness" onClose={() => setConnections(false)}>
      <p>The workspace is ready for camera integration. No Defense sources or analysis profile are connected yet.</p>
      <dl className={styles.facts}><div><dt>Site security</dt><dd>RTSP source, person tracking, zone rule and matched evidence.</dd></div><div><dt>Drone inspection</dt><dd>Inspection imagery, capture pose, task-trained detector and view-request controller.</dd></div><div><dt>Vehicle awareness</dt><dd>Synchronized cameras, calibration, source health and depth for measured positions.</dd></div><div><dt>Questions & reports</dt><dd>VSS evidence clips and Cosmos analyst with explicit source/time scope.</dd></div></dl>
      <button className={styles.primary} onClick={onOpenSources}>Open existing camera management</button>
    </DefenseDialog>}
  </div>;
}
