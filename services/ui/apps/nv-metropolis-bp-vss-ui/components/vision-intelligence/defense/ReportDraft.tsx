// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import { IconDownload } from '@tabler/icons-react';
import type { DefenseMode, DefenseScenario } from './types';
import { createPreviewReport } from './fixtures';
import { DefenseDialog } from './Dialog';
import styles from './Defense.module.css';
export function ReportDraft({ mode, scenario, onClose }: { mode: DefenseMode; scenario: DefenseScenario; onClose: () => void }) {
  const [notes, setNotes] = useState('');
  const [exported, setExported] = useState(false);
  const report = createPreviewReport(mode, scenario, notes);
  const download = () => {
    const current = createPreviewReport(mode, scenario, notes);
    if (!current) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(current, null, 2)], { type:'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'defense-preview-' + scenario + '.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setExported(true);
  };
  return <DefenseDialog title="Preview report draft" onClose={onClose}>
    <p className={styles.example}>Illustrative data · not saved to operational reports</p>
    {report ? <><h3>{report.title}</h3><ul>{report.observations.map(text => <li key={text}>{text}</li>)}</ul><h3>Evidence references</h3><ul>{report.evidence.map(item => <li key={item.id}>{item.sourceName} · {item.timeLabel} · illustrative still</li>)}</ul><h3>Limitations</h3><ul>{report.limitations.map(text => <li key={text}>{text}</li>)}</ul>
      <label className={styles.field}>Analyst notes<textarea value={notes} onChange={event => setNotes(event.target.value)} placeholder="Add a note to this preview draft…" /></label>
      <button className={styles.primary} onClick={download}><IconDownload size={18} />Download preview JSON</button>{exported && <p role="status">Preview JSON download requested. No operational report was created.</p>}
    </> : <p>No evidence available. Connect a source before creating an operational report.</p>}
  </DefenseDialog>;
}
