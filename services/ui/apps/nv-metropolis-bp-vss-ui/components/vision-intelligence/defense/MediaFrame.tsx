// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import { IconCameraOff, IconMaximize } from '@tabler/icons-react';
import { DefenseDialog } from './Dialog';
import type { DefenseEvidence } from './types';
import styles from './Defense.module.css';

export function MediaFrame({ evidence, title, overlay, className = '' }: {
  evidence?: DefenseEvidence; title?: string; overlay?: 'gate' | 'person'; className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const hasImage = evidence?.imageUrl && failedUrl !== evidence.imageUrl;
  const content = <>{hasImage ? <img data-local-vision-source={`Illustration · ${title || evidence.sourceName}`} loading="lazy" src={evidence.imageUrl!} alt={evidence.observation || evidence.sourceName} onError={() => setFailedUrl(evidence.imageUrl)} /> : <div className={styles.noMedia}><IconCameraOff size={30} /><strong>{failedUrl ? 'Preview image unavailable' : 'No camera connected'}</strong><span>Connect a source when footage is ready.</span></div>}
    {hasImage && overlay === 'gate' && <svg className={styles.overlay} viewBox="0 0 1672 941" aria-label="Illustrative storage boundary"><polygon points="857,575 1258,556 1575,818 714,835" /><rect x="929" y="383" width="105" height="209" /><text x="933" y="371">P-014</text></svg>}
    {hasImage && overlay === 'person' && <svg className={styles.overlay} viewBox="0 0 1672 941" aria-label="Illustrative person annotation"><rect x="1033" y="303" width="146" height="284" /></svg>}
  </>;
  return <section className={styles.media + ' ' + className}>
    <div className={styles.mediaHeader}><strong>{title || evidence?.sourceName}</strong><span>{evidence ? evidence.timeLabel + ' · Illustration' : 'Not connected'}</span>{hasImage && <button aria-label={'Enlarge ' + (title || evidence?.sourceName)} onClick={() => setExpanded(true)}><IconMaximize size={16} /></button>}</div>
    <div className={styles.image}>{content}</div>
    {expanded && <DefenseDialog title="Expanded source image" onClose={() => setExpanded(false)}><div className={styles.image}>{content}</div><p>Illustrative image · no live source or inference</p></DefenseDialog>}
  </section>;
}
