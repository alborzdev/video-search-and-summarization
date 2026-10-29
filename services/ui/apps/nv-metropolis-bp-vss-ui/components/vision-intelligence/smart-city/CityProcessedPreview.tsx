// SPDX-License-Identifier: MIT
import React, { useLayoutEffect, useRef } from 'react';
import type { CityPreviewFrame } from './types';
import type { PreviewPair } from './useProcessedPreview';
import styles from './SmartCity.module.css';

/** The matching SVG is committed first; draw its already decoded pixels before paint. */
export function CityProcessedPreview({ pair, onPresented, onFailure, presentable = true }: { pair: PreviewPair; onPresented: (frame: CityPreviewFrame) => void; onFailure: () => void; presentable?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const renderer = useRef<ImageBitmapRenderingContext | CanvasRenderingContext2D | null>(null);
  const drawn = useRef<PreviewPair | null>(null);
  useLayoutEffect(() => {
    if (!presentable) return;
    if (pair.released) { onFailure(); return; }
    const element = canvas.current;
    if (!element || pair.transferredTo && pair.transferredTo !== element) { onFailure(); return; }
    try {
      // Transfer the decoded image's ownership instead of drawing a second
      // full-frame copy. Browsers without bitmaprenderer keep the opaque 2D path.
      const context = renderer.current ?? (renderer.current = element.getContext('bitmaprenderer', { alpha: false })
        ?? element.getContext('2d', { alpha: false }));
      if (!context) { onFailure(); return; }
      if (drawn.current !== pair) {
        // Preserve the original image aspect ratio for CSS object-fit and the
        // matching SVG, including when the JPEG itself is downscaled.
        if (element.width !== pair.frame.image.width) element.width = pair.frame.image.width;
        if (element.height !== pair.frame.image.height) element.height = pair.frame.image.height;
        if ('transferFromImageBitmap' in context) {
          if (pair.transferredTo) { onFailure(); return; }
          context.transferFromImageBitmap(pair.bitmap);
          pair.transferredTo = element;
          element.dataset.previewRenderer = 'bitmaprenderer';
        } else {
          context.drawImage(pair.bitmap, 0, 0, element.width, element.height);
          element.dataset.previewRenderer = '2d';
        }
        drawn.current = pair;
        if (pair.timing) {
          element.dataset.previewRequestMs = pair.timing.requestMs.toFixed(1);
          element.dataset.previewDecodeMs = pair.timing.decodeMs.toFixed(1);
          element.dataset.previewCommitMs = (performance.now() - pair.timing.readyAtMs).toFixed(1);
        }
      }
      onPresented(pair.frame);
    } catch { onFailure(); }
  }, [pair, onPresented, onFailure, presentable]);
  return <canvas ref={canvas} className={styles.processedPreview} style={{ visibility: presentable ? 'visible' : 'hidden' }} aria-label="Frame matched analyzed camera preview" />;
}
