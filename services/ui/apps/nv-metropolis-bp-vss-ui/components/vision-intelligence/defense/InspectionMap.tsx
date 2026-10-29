// SPDX-License-Identifier: MIT
import React from 'react';
import styles from './Defense.module.css';

export function InspectionMap({ preview, onInspect, site = false }: { preview: boolean; onInspect?: () => void; site?: boolean }) {
  return <section className={styles.map}>
    <div className={styles.mediaHeader}><strong>{site ? 'Site plan' : 'Reference map + capture footprints'}</strong><span>Illustrative layout</span></div>
    {preview ? <div className={styles.mapBody}>
      <img src="/defense-preview/airfield-map.png" alt="Illustrative overhead reference layout, not a reconstruction" />
      <svg viewBox="0 0 1000 560" className={styles.mapOverlay} aria-label="Example capture footprints; not measured coverage">
        <defs><pattern id={site ? 'site-hatch' : 'drone-hatch'} width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="12" stroke="#b7c6c3" strokeWidth="2" opacity=".4" /></pattern></defs>
        <path d="M0 0H280L590 560H0Z" fill={'url(#' + (site ? 'site-hatch' : 'drone-hatch') + ')'} />
        {!site && <><path d="M325 110L410 220L515 320L675 430L850 470" stroke="#4fc7bb" strokeWidth="3" strokeDasharray="8 5" fill="none" />
          {[ [325,110], [410,220], [515,320], [675,430], [850,470] ].map(([x,y]) => <g key={x}><rect x={x-37} y={y-24} width="74" height="48" fill="#4fc7bb" fillOpacity=".23" stroke="#70d9d0" transform={'rotate(30 '+x+' '+y+')'} /><circle cx={x} cy={y} r="5" fill="#8ee6dc" /></g>)}</>}
      </svg>
      <span className={styles.unobserved}>Not yet inspected</span>
      {onInspect && <button className={styles.mapPin} onClick={onInspect} aria-label="Inspect finding 03">03</button>}
      <div className={styles.mapLegend}><span>Captured</span><span>Not captured</span><span>Finding</span></div>
    </div> : <div className={styles.noMedia}><strong>Map not configured</strong><span>Reference map, camera poses and calibration required.</span></div>}
  </section>;
}
