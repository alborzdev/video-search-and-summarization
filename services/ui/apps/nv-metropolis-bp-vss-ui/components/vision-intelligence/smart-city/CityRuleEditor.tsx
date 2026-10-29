// SPDX-License-Identifier: MIT
import React, { useEffect, useId, useMemo, useState } from 'react';
import { IconArrowBackUp, IconDeviceFloppy, IconTrash, IconX } from '@tabler/icons-react';
import type { CityRule, CitySource, Point } from './types';
import { ruleCaption, sourceName } from './presentation';
import styles from './SmartCity.module.css';
export interface RuleDraft { sourceId: string; id?: string; name: string; kind: string; classes: string[]; points: Point[]; minimumDurationMs: number; countThreshold: number; direction: Point; rulesRevision?: number; }
const RULE_TYPES = ['occupancy-threshold', 'area-entry', 'line-crossing', 'dwell', 'stopped-in-zone', 'queue', 'wrong-way'];
const EPS = 1e-9;
const cross = (a: Point, b: Point, c: Point) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
const onSegment = (p: Point, a: Point, b: Point) => Math.abs(cross(a, b, p)) <= EPS && p[0] >= Math.min(a[0], b[0]) - EPS && p[0] <= Math.max(a[0], b[0]) + EPS && p[1] >= Math.min(a[1], b[1]) - EPS && p[1] <= Math.max(a[1], b[1]) + EPS;
const opposite = (a: number, b: number) => (a > EPS && b < -EPS) || (a < -EPS && b > EPS);
const intersects = (a: Point, b: Point, c: Point, d: Point) => (opposite(cross(a, b, c), cross(a, b, d)) && opposite(cross(c, d, a), cross(c, d, b))) || onSegment(c, a, b) || onSegment(d, a, b) || onSegment(a, c, d) || onSegment(b, c, d);

/** Match the service's bounded geometry/condition constraints before submitting a revision. */
export function ruleDraftError(draft: RuleDraft, sources: CitySource[]): string | null {
  if (!sources.some(source => source.id === draft.sourceId)) return 'Choose an available camera.';
  if (!draft.name.trim() || draft.name.length > 200) return 'Enter a rule name of 1–200 characters.';
  if (!RULE_TYPES.includes(draft.kind)) return 'Choose a detection rule type.';
  if (!draft.classes.length) return 'Choose at least one object class.';
  if (!Number.isInteger(draft.minimumDurationMs) || draft.minimumDurationMs < 0 || draft.minimumDurationMs > 3_600_000) return 'Use a trigger duration from 0 to 3600 seconds.';
  if (!Number.isInteger(draft.countThreshold) || draft.countThreshold < 1 || draft.countThreshold > 10_000) return 'Use a whole object threshold from 1 to 10000.';
  const points = draft.points; const line = draft.kind === 'line-crossing';
  if (line ? points.length !== 2 : points.length < 3) return line ? 'Place exactly two line endpoints.' : 'Place at least three polygon vertices.';
  if (points.length > 128) return 'Use no more than 128 polygon vertices.';
  if (points.some(point => point.length !== 2 || point.some(value => !Number.isFinite(value) || value < 0 || value > 1))) return 'Place each point inside the camera image.';
  for (let i = 0; i < points.length; i++) {
    const a = points[i]; const b = points[(i + 1) % points.length];
    if (Math.hypot(a[0] - b[0], a[1] - b[1]) < EPS) return 'Place distinct points. Use Undo point to remove duplicates.';
  }
  if (!line) {
    const area = points.reduce((sum, a, i) => { const b = points[(i + 1) % points.length]; return sum + a[0] * b[1] - b[0] * a[1]; }, 0);
    if (Math.abs(area) < EPS) return 'Draw a polygon with an area, not a straight line.';
    for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) {
      if (j === i + 1 || (i === 0 && j === points.length - 1)) continue;
      if (intersects(points[i], points[(i + 1) % points.length], points[j], points[(j + 1) % points.length])) return 'Polygon edges must not cross. Use Undo point to adjust the boundary.';
    }
  }
  if ((line || draft.kind === 'wrong-way') && (draft.direction.length !== 2 || !draft.direction.every(Number.isFinite) || Math.hypot(...draft.direction) < EPS)) return 'Choose a nonzero movement direction.';
  return null;
}

export function CityRuleEditor({ draft, onChange, onClose, onSave, onDelete, rules, sources, saving, error, onEdit }: {
  draft: RuleDraft; onChange: (value: RuleDraft) => void; onClose: () => void;
  onSave: () => void; onDelete: (rule: CityRule) => void; rules: CityRule[]; sources: CitySource[];
  saving: boolean; error: string | null; onEdit: (rule: CityRule) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  useEffect(() => { setConfirmDelete(null); }, [draft.id, draft.sourceId]);
  const validationId = useId();
  const line = draft.kind === 'line-crossing';
  const validationError = useMemo(() => ruleDraftError(draft, sources), [draft, sources]);
  return <section className={styles.ruleEditor} aria-label="Edit city zones and directed lines" aria-busy={saving}>
    <header><div><span>Monitoring</span><h2>{draft.id ? 'Edit rule' : 'Draw a rule'}</h2></div><button type="button" onClick={onClose} aria-label="Close rule editor"><IconX size={20} /></button></header>
    <h3 className={styles.ruleStep}>1 · Choose the camera</h3>
    <label>Camera<select aria-label="Rule camera" disabled={saving} value={draft.sourceId} onChange={event => onChange({ ...draft, sourceId: event.target.value, points: [] })}>{sources.map(source => <option key={source.id} value={source.id}>{sourceName(source)}</option>)}</select></label>
    <h3 className={styles.ruleStep}>2 · Draw the monitoring area</h3>
    <div className={styles.drawHelp}><strong>{draft.points.length} {line ? '/ 2 points' : 'vertices placed'}</strong><span>{saving ? 'Saving this rule. Drawing is paused.' : line && draft.points.length === 2 ? 'Line complete. Use Undo point to change an endpoint.' : `Click the camera image to draw ${line ? 'the directed line.' : 'the polygon boundary.'}`}</span><button type="button" disabled={saving || !draft.points.length} onClick={() => onChange({ ...draft, points: draft.points.slice(0, -1) })}><IconArrowBackUp size={15} />Undo point</button></div>
    <h3 className={styles.ruleStep}>3 · Define what matters</h3>
    <label>Rule name<input disabled={saving} value={draft.name} maxLength={200} onChange={event => onChange({ ...draft, name: event.target.value })} placeholder="e.g. Pedestrian crossing" /></label>
    <label>Detect<select aria-label="Detection rule type" disabled={saving} value={draft.kind} onChange={event => onChange({ ...draft, kind: event.target.value, points: line === (event.target.value === 'line-crossing') ? draft.points : [] })}><option value="occupancy-threshold">Occupancy</option><option value="area-entry">Area entry</option><option value="line-crossing">Directed line crossing</option><option value="dwell">Dwell in area</option><option value="stopped-in-zone">Stopped vehicle</option><option value="queue">Vehicle queue</option><option value="wrong-way">Wrong-way movement</option></select></label>
    <fieldset disabled={saving}><legend>Object classes</legend><div className={styles.classChoices}>{['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler'].map(name => <label key={name}><input type="checkbox" checked={draft.classes.includes(name)} onChange={event => onChange({ ...draft, classes: event.target.checked ? [...draft.classes, name] : draft.classes.filter(item => item !== name) })} />{name}</label>)}</div></fieldset>
    {line ? <button type="button" disabled={saving} className={styles.outlineButton} onClick={() => onChange({ ...draft, direction: [-draft.direction[0], -draft.direction[1]] })}>Reverse crossing direction</button> : <div className={styles.formRow}><label>Trigger after (s)<input type="number" disabled={saving} min="0" max="3600" step="0.001" value={Number.isFinite(draft.minimumDurationMs) ? draft.minimumDurationMs / 1000 : ''} onChange={event => onChange({ ...draft, minimumDurationMs: Math.round(event.target.valueAsNumber * 1000) })} /></label><label>Object threshold<input type="number" disabled={saving} min="1" max="10000" step="1" value={Number.isFinite(draft.countThreshold) ? draft.countThreshold : ''} onChange={event => onChange({ ...draft, countThreshold: event.target.valueAsNumber })} /></label></div>}
    {draft.kind === 'wrong-way' && <button type="button" disabled={saving} className={styles.outlineButton} onClick={() => onChange({ ...draft, direction: [-draft.direction[0], -draft.direction[1]] })}>Reverse allowed direction</button>}

    {error && <p className={styles.error} role="alert">{error}</p>}
    {validationError && <p id={validationId} className={styles.ruleValidation} role="status">{validationError}</p>}
    <div className={styles.editorActions}><button type="button" className={styles.primaryButton} disabled={Boolean(validationError) || saving} aria-describedby={validationError ? validationId : undefined} onClick={onSave}><IconDeviceFloppy size={18} />{saving ? 'Saving rule…' : 'Save rule'}</button><button type="button" className={styles.outlineButton} disabled={saving} onClick={onClose}>Cancel</button></div>
    <p className={styles.muted}>Rules become active after the analytics service accepts the revision.</p>
    <details className={styles.savedRulesDisclosure}><summary>Manage existing rules ({rules.length})</summary><div className={styles.savedRules}><h3>Saved rules</h3>{rules.length ? rules.map(rule => <div key={rule.id}><button type="button" disabled={saving} onClick={() => { setConfirmDelete(null); onEdit(rule); }}><strong>{rule.name}</strong><span>{ruleCaption(rule)} · {rule.enabled ? 'Enabled' : 'Disabled'}</span></button><button type="button" disabled={saving} aria-label={confirmDelete === rule.id ? `Confirm deletion of ${rule.name}` : `Delete ${rule.name}`} title={confirmDelete === rule.id ? 'Click again to confirm delete' : 'Delete rule'} onClick={() => { if (confirmDelete === rule.id) { onDelete(rule); setConfirmDelete(null); } else setConfirmDelete(rule.id); }}><IconTrash size={16} />{confirmDelete === rule.id ? 'Confirm' : null}</button></div>) : <p>No rules saved yet.</p>}</div></details>
  </section>;
}
