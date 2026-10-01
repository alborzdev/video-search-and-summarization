import React, { useState } from 'react';
import styles from './VssEmbeddingScene.module.css';

const clips = [
  { camera: 'Camera 02', source: 'Receiving dock', image: '/vision/story-receiving.png', video: 'Retained dock footage', bars: [24, 42, 18, 62, 36, 80, 54, 20, 70, 43, 29, 60] },
  { camera: 'Camera 07', source: 'Warehouse aisle', image: '/vision/story-aisle.png', video: 'Retained aisle footage', bars: [62, 20, 76, 32, 50, 24, 84, 57, 18, 35, 66, 41] },
  { camera: 'Camera 11', source: 'Vehicle entrance', image: '/vision/story-entrance.png', video: 'Retained entrance footage', bars: [40, 72, 28, 56, 19, 43, 62, 81, 35, 58, 22, 76] },
];
const queries = [
  { text: 'Person carrying a box', clip: 0, order: [0, 1, 2] },
  { text: 'Warehouse aisle', clip: 1, order: [1, 0, 2] },
  { text: 'Delivery truck', clip: 2, order: [2, 0, 1] },
];

function Fingerprint({ bars, label, highlighted = false }: { bars: number[]; label: string; highlighted?: boolean }) {
  return <svg viewBox="0 0 230 46" className={styles.fingerprint} role="img" aria-label={`${label}: schematic embedding number pattern`}>
    <path d="M5 40H225" stroke="#353b40" />
    {bars.map((height, index) => <rect key={index} x={7 + index * 18} y={40 - height * .4} width="10" height={height * .4} rx="2" fill={highlighted ? '#9ee8cd' : '#657175'} />)}
  </svg>;
}

function Arrow({ label }: { label: string }) {
  return <div className={styles.arrow} aria-label={label}><span>{label}</span><svg viewBox="0 0 48 20" aria-hidden="true"><path d="M2 10H43M36 3 43 10 36 17" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg></div>;
}

export function VssEmbeddingScene() {
  const [selected, setSelected] = useState(0);
  const query = queries[selected];
  const match = clips[query.clip];
  return <div className={styles.scene}>
    <div className={styles.laneHeader}><span>01 / VIDEO → INDEX</span><span>02 / WORDS → MATCHING FOOTAGE</span></div>
    <div className={styles.grid}>
      <section className={styles.inputs} aria-label="Indexed video sources">
        <h3>Camera clips</h3>
        <div className={styles.clips}>
          {clips.map((clip, index) => <figure className={`${styles.clip} ${index === query.clip ? styles.selectedClip : ''}`} key={clip.camera}>
            <img src={clip.image} alt={`${clip.source} camera observation`} />
            <figcaption><strong>{clip.camera}</strong><span>{clip.source}</span><small>{clip.video}</small></figcaption>
          </figure>)}
        </div>
        <Arrow label="Video input" />
      </section>
      <section className={styles.space} aria-label="Cosmos Embed shared text and video embedding space">
        <div className={styles.model}><span className={styles.modelDot} /><strong>Cosmos Embed</strong><span>Video + text</span></div>
        <div className={styles.spaceHeading}><h3>Shared meaning space</h3><p>Number patterns that represent meaning</p></div>
        <div className={styles.vectors}>
          {clips.map((clip, index) => <div className={`${styles.vectorRow} ${index === query.clip ? styles.activeVector : ''}`} key={clip.camera}><span>{clip.camera}</span><Fingerprint bars={clip.bars} label={clip.camera} highlighted={index === query.clip} /></div>)}
        </div>
        <div className={styles.queryVector}><span>Query embedding</span><Fingerprint bars={match.bars.map((height, index) => Math.max(8, height + (index % 3 - 1) * 7))} label="Selected text query" highlighted /><span className={styles.sharedNote}>Same space as video</span></div>
        <span className={styles.schematic}>Schematic vectors · no confidence scores</span>
        <Arrow label="Compare patterns" />
      </section>
      <section className={styles.results} aria-label="Searchable local video index and illustrative matches">
        <div className={styles.index}><svg viewBox="0 0 32 34" aria-hidden="true"><ellipse cx="16" cy="7" rx="12" ry="5" /><path d="M4 7v19c0 7 24 7 24 0V7M4 16c0 7 24 7 24 0" /></svg><div><h3>Local searchable index</h3><p>Video vectors + source references</p></div></div>
        <div className={styles.match} aria-live="polite">
          <div className={styles.resultHeading}><strong>Matching footage</strong><span>Illustrative results</span></div>
          <img src={match.image} alt={`Top illustrative match: ${match.source}`} />
          <div className={styles.matchCaption}><strong>{match.camera} · {match.source}</strong><span>{match.video}</span></div>
          <ol className={styles.ranking}>{query.order.map((clipIndex, rank) => <li key={clips[clipIndex].camera}><span>{rank + 1}</span><strong>{clips[clipIndex].camera}</strong><span>{clips[clipIndex].source}</span></li>)}</ol>
        </div>
      </section>
      <section className={styles.query} aria-label="Try a natural-language query">
        <div><span className={styles.queryLabel}>Natural-language query</span><h3>Choose the meaning to find</h3></div>
        <div className={styles.queries}>{queries.map((item, index) => <button type="button" aria-pressed={selected === index} key={item.text} onClick={() => setSelected(index)}>{item.text}<span aria-hidden="true">↗</span></button>)}</div>
        <Arrow label="Text input" />
      </section>
    </div>
    <p className={styles.footer}>The index retains the camera, source and video reference. Similar meanings retrieve footage you can inspect.</p>
  </div>;
}
