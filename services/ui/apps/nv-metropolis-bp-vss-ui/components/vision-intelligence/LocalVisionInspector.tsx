// SPDX-License-Identifier: MIT
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { IconUpload, IconX, IconRefresh, IconArrowRight } from '@tabler/icons-react';
import s from './LocalVisionInspector.module.css';
import { prepareDisplayedImage, prepareUploadedImage, type PreparedVisionImage } from './localVisionImage';

type Task = 'segment' | 'detect' | 'point' | 'describe';
type Grounding = { point?: number[]; box?: number[]; source_index?: number; mask_png_base64?: string };
export type LocalVisionResult = {
  operation: Task; status: string; description?: string; objects?: Grounding[]; points?: Grounding[];
  image?: { width: number; height: number }; input_image?: { resized?: boolean };
  timings_ms?: Record<string, number>; grounding_returned_at_limit?: boolean;
  model_identity?: { moondream: string; segmenter: string; runtime: string };
};
const API = '/api/vision/local-model';
const TASKS: { id: Task; label: string; help: string }[] = [
  { id: 'segment', label: 'Segment', help: 'Moondream finds a point. SAM2.1 Tiny draws the object mask.' },
  { id: 'detect', label: 'Detect', help: 'Moondream returns boxes for the requested object.' },
  { id: 'point', label: 'Point', help: 'Moondream marks the requested object with a point.' },
  { id: 'describe', label: 'Describe', help: 'Moondream describes the visible scene.' },
];
export function resultMessage(result: LocalVisionResult): string {
  if (result.status === 'presence_rejected') return 'The presence check did not find the requested object.';
  if (result.status === 'presence_unrecognized') return 'The presence check was inconclusive. No mask was produced.';
  if (result.status === 'invalid_grounding') return 'The model returned invalid coordinates. No result was drawn.';
  if (result.operation === 'describe') return result.description || 'No description was returned.';
  const count = (result.operation === 'point' ? result.points : result.objects)?.length ?? 0;
  const noun = result.operation === 'segment' ? 'mask' : result.operation === 'point' ? 'point' : 'box';
  return count ? `${count} ${noun}${count === 1 ? '' : noun === 'box' ? 'es' : 's'} returned` : 'No objects found for this prompt.';
}
function MaskLayer({ base64 }: { base64: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let active = true; const mask = new Image();
    mask.onload = () => {
      if (!active || !canvas.current) return;
      const el = canvas.current; el.width = mask.naturalWidth; el.height = mask.naturalHeight;
      const context = el.getContext('2d'); if (!context) return;
      context.drawImage(mask, 0, 0); const pixels = context.getImageData(0, 0, el.width, el.height);
      for (let index = 0; index < pixels.data.length; index += 4) {
        const present = pixels.data[index] > 127; pixels.data[index] = 72; pixels.data[index + 1] = 224; pixels.data[index + 2] = 184; pixels.data[index + 3] = present ? 115 : 0;
      }
      context.putImageData(pixels, 0, 0);
    };
    mask.src = `data:image/png;base64,${base64}`;
    return () => { active = false; mask.onload = null; };
  }, [base64]);
  return <canvas ref={canvas} className={s.overlay} aria-label="Predicted object mask" />;
}
export function LocalVisionInspector({ onClose, captureSelector }: { onClose: () => void; captureSelector?: string }) {
  const sources = useMemo(() => captureSelector ? Array.from(document.querySelectorAll<HTMLImageElement | HTMLVideoElement | HTMLCanvasElement>(captureSelector)).filter(element => element.getClientRects().length && !element.closest('[hidden]')).map((element, index) => ({ element, label: element.getAttribute('data-local-vision-source') || `${element.tagName === 'VIDEO' ? 'Video' : 'Camera'} frame ${index + 1}` })) : [], [captureSelector]);
  const [sourceIndex, setSourceIndex] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null); const controller = useRef<AbortController | null>(null); const uploadSequence = useRef(0);
  const [groundedBy, setGroundedBy] = useState<'point' | 'detect'>('point');
  const [task, setTask] = useState<Task>('segment'); const [object, setObject] = useState('');
  const [image, setImage] = useState<PreparedVisionImage | null>(null);
  const [result, setResult] = useState<LocalVisionResult | null>(null); const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null); const [ready, setReady] = useState(false);
  const [health, setHealth] = useState('Checking service'); const [checking, setChecking] = useState(false);
  const [showOverlay, setShowOverlay] = useState(true);
  const [requestMs, setRequestMs] = useState<number | null>(null);
  const checkHealth = async (signal?: AbortSignal) => {
    setChecking(true);
    try {
      const response = await fetch(API, { signal, cache: 'no-store' }); const value = await response.json();
      const available = response.ok && (value.ready === true || value.status === 'ready');
      setReady(available); setHealth(available ? value.busy ? 'Busy' : 'Ready on this device' : ['loading', 'warming'].includes(value.status) || ['loading', 'warming'].includes(value.state) ? 'Models loading' : 'Service unavailable');
    } catch (cause) { if ((cause as Error).name !== 'AbortError') { setReady(false); setHealth('Service unavailable'); } }
    finally { if (!signal?.aborted) setChecking(false); }
  };
  useEffect(() => {
    const el = dialog.current; el?.showModal(); const healthController = new AbortController(); void checkHealth(healthController.signal);
    return () => { healthController.abort(); controller.current?.abort(); uploadSequence.current++; el?.close(); };
  }, []);
  const upload = async (file?: File) => {
    if (!file) return; const sequence = ++uploadSequence.current; setResult(null); setError(null); setImage(null);
    try { const prepared = await prepareUploadedImage(file); if (sequence === uploadSequence.current) setImage(prepared); }
    catch (cause) { if (sequence === uploadSequence.current) setError((cause as Error).message); }
  };
  const capture = () => {
    const source = sources[sourceIndex]; if (!source || running) return;
    try { const prepared = prepareDisplayedImage(source.element, source.label); uploadSequence.current++; setImage(prepared); setResult(null); setError(null); }
    catch (cause) { setError((cause as Error).name === 'SecurityError' ? 'This source does not allow browser frame capture. Upload an image instead.' : (cause as Error).message); }
  };
  const run = async () => {
    if (!image || running || !ready || (task !== 'describe' && !object.trim())) return;
    setRunning(true); setError(null); setResult(null); setShowOverlay(true); setRequestMs(null);
    const started = performance.now();
    const abort = new AbortController(); controller.current = abort; const timeout = setTimeout(() => abort.abort(), 125_000);
    try {
      const response = await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ task, image_base64: image.base64, ...(task === 'describe' ? {} : { object: object.trim() }), ...(task === 'segment' ? { grounded_by: groundedBy, presence: 'off' } : {}) }) });
      const value = await response.json(); if (!response.ok) throw new Error(value.error || 'The local model request failed.');
      setResult(value); setRequestMs(performance.now() - started);
    } catch (cause) { setError((cause as Error).name === 'AbortError' ? 'Request stopped or timed out. The service may still be finishing this image.' : (cause as Error).message); }
    finally { clearTimeout(timeout); setRunning(false); controller.current = null; }
  };
  const groundings = result?.operation === 'point' ? result.points ?? [] : result?.objects ?? [];
  const hasOverlay = groundings.some(item => item.box || item.point || item.mask_png_base64);
  const timing = result?.timings_ms;
  return <dialog ref={dialog} className={s.dialog} aria-label="Local vision inspector" onCancel={onClose}>
    <header className={s.header}><div><span className={s.eyebrow}>LOCAL MODEL WORKBENCH</span><h2>Inspect an image</h2></div><button type="button" onClick={onClose} aria-label="Close local vision inspector"><IconX size={21} /></button></header>
    <div className={s.service}><span data-ready={ready}><i />{health}</span><span>Moondream2{task === 'segment' && <><IconArrowRight size={13} />SAM2.1 Tiny</>}</span><button type="button" aria-label="Check local vision readiness" disabled={checking || running} onClick={() => void checkHealth()}><IconRefresh size={14} />Refresh</button></div>
    <div className={s.layout}>
      <section className={s.preview} aria-label="Image and model output">
        <div className={s.imageArea}>{image ? <div className={s.imageFrame}>
          <img src={image.url} alt={`Input: ${image.name}`} />
          {showOverlay && groundings.map((item, index) => <React.Fragment key={index}>{item.mask_png_base64 && <MaskLayer base64={item.mask_png_base64} />}{item.box?.length === 4 && <span className={s.box} aria-label={`Detection ${index + 1}`} style={{ left: `${item.box[0] * 100}%`, top: `${item.box[1] * 100}%`, width: `${(item.box[2] - item.box[0]) * 100}%`, height: `${(item.box[3] - item.box[1]) * 100}%` }} />}{item.point?.length === 2 && <span className={s.point} aria-label={`Point ${index + 1}`} style={{ left: `${item.point[0] * 100}%`, top: `${item.point[1] * 100}%` }} />}</React.Fragment>)}
        </div> : <div className={s.empty}><IconUpload size={32} /><strong>Add an image to begin</strong><p>Use a camera frame or inspection image.<br />The model runs locally on this device.</p></div>}</div>
        <div className={s.imageBar}><span>{image?.provenance || image?.name || 'PNG, JPEG or WebP · up to 10 MiB · fitted to 1024 px'}</span>{hasOverlay && <label><input type="checkbox" checked={showOverlay} onChange={event => setShowOverlay(event.target.checked)} />Show result</label>}</div>
      </section>
      <section className={s.controls} aria-label="Local model controls">
        {sources.length > 0 && <div className={s.capture}><label>Displayed source<select aria-label="Displayed source image" value={sourceIndex} disabled={running} onChange={event => setSourceIndex(Number(event.target.value))}>{sources.map((source, index) => <option key={index} value={index}>{source.label}</option>)}</select></label><button type="button" disabled={running} onClick={capture}>Use displayed image</button></div>}
        <label className={s.upload}><IconUpload size={17} />{image ? 'Change image' : 'Choose image'}<input aria-label="Upload image for local vision" type="file" accept="image/png,image/jpeg,image/webp" disabled={running} onChange={event => { void upload(event.target.files?.[0]); event.target.value = ''; }} /></label>
        <div className={s.tasks} role="group" aria-label="Vision task">{TASKS.map(item => <button type="button" key={item.id} aria-pressed={task === item.id} disabled={running} onClick={() => { setTask(item.id); setResult(null); setError(null); }}>{item.label}</button>)}</div>
        {task === 'segment' && <div className={s.tasks} role="group" aria-label="Segmentation guidance">{(['point', 'detect'] as const).map(mode => <button type="button" key={mode} aria-pressed={groundedBy === mode} disabled={running} onClick={() => { setGroundedBy(mode); setResult(null); setError(null); }}>{mode === 'point' ? 'Point guidance' : 'Box guidance'}</button>)}</div>}
        <p className={s.help}>{task === 'segment' && groundedBy === 'detect' ? 'Moondream finds a box. SAM2.1 Tiny uses it to draw the object mask.' : TASKS.find(item => item.id === task)?.help}</p>
        {task !== 'describe' && <label className={s.prompt}>Object to find<input type="text" maxLength={200} placeholder="e.g. aircraft, person, cargo box" value={object} disabled={running} onChange={event => { setObject(event.target.value); setResult(null); }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void run(); } }} /></label>}
        <button type="button" className={s.run} disabled={!image || !ready || running || (task !== 'describe' && !object.trim())} onClick={() => void run()}>{running ? 'Processing image…' : `Run ${task}`}<IconArrowRight size={17} /></button>
        {!ready && <p className={s.notice}>Start local vision with VSS, then refresh readiness.</p>}
        {error && <p className={s.error} role="alert">{error}</p>}
        <div className={s.result} aria-live="polite" aria-busy={running}>{running ? <p>Running on this device. A cold model load can take longer.</p> : result ? <><span className={s.eyebrow}>MODEL RESULT</span><p>{resultMessage(result)}</p>{result.grounding_returned_at_limit && <p className={s.notice}>Reached the 3-object limit. Additional objects may be present.</p>}{result.input_image?.resized && <p className={s.notice}>Image resized to fit a 1024-pixel longest side.</p>}{timing && <dl className={s.timings}>{[['Request', requestMs ?? timing.total], ['Grounding', (timing.point ?? 0) + (timing.detect ?? 0)], ['Mask', (timing.image_encode ?? 0) + (timing.mask_decode ?? 0)]].map(([label, value]) => typeof value === 'number' && value > 0 ? <div key={label}><dt>{label}</dt><dd>{Math.round(value).toLocaleString()} ms</dd></div> : null)}</dl>}{timing && (timing.moondream_load > 0 || timing.segmenter_load > 0) && <p className={s.notice}>Request includes model loading.</p>}</> : <p>The result will appear here after processing.</p>}</div>
      </section>
    </div>
    <footer className={s.footer}>One image per request · Teal: predicted mask · Amber: model point or box · Review results before use</footer>
  </dialog>;
}
