// SPDX-License-Identifier: MIT

import type { MonitoringGeometry, MonitoringPoint } from './monitoringRules';
import type { VisionStream } from './types';
import { VisionStreamCanvas } from './VisionStreamCanvas';
import {
  IconArrowBackUp,
  IconCheck,
  IconPlus,
  IconPolygon,
  IconTrash,
} from '@tabler/icons-react';
import React, { MouseEvent, PointerEvent, useRef, useState } from 'react';

interface MonitoringRegionEditorProps {
  geometry: MonitoringGeometry;
  onChange: (geometry: MonitoringGeometry) => void;
  stream: VisionStream;
  vstApiUrl?: string | null;
}

const VIEWBOX_WIDTH = 1000;
const VIEWBOX_HEIGHT = 562.5;

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function eventPoint(event: MouseEvent<SVGSVGElement> | PointerEvent<SVGSVGElement>): MonitoringPoint {
  const bounds = event.currentTarget.getBoundingClientRect();
  return {
    x: clamp((event.clientX - bounds.left) / Math.max(1, bounds.width)),
    y: clamp((event.clientY - bounds.top) / Math.max(1, bounds.height)),
  };
}

function keyboardPoint(points: MonitoringPoint[]): MonitoringPoint {
  const startingPoints: MonitoringPoint[] = [
    { x: 0.25, y: 0.25 },
    { x: 0.75, y: 0.25 },
    { x: 0.75, y: 0.75 },
    { x: 0.25, y: 0.75 },
  ];
  if (points.length < startingPoints.length) return startingPoints[points.length];

  const first = points[0];
  const last = points.at(-1)!;
  return { x: (first.x + last.x) / 2, y: (first.y + last.y) / 2 };
}

export function MonitoringRegionEditor({
  geometry,
  onChange,
  stream,
  vstApiUrl,
}: MonitoringRegionEditorProps) {
  const [dragging, setDragging] = useState<number | null>(null);
  const moved = useRef(false);
  const polygon = geometry.points
    .map((point) => `${point.x * VIEWBOX_WIDTH},${point.y * VIEWBOX_HEIGHT}`)
    .join(' ');

  const replacePoint = (index: number, point: MonitoringPoint) => {
    onChange({
      ...geometry,
      points: geometry.points.map((candidate, candidateIndex) =>
        candidateIndex === index ? point : candidate,
      ),
    });
  };

  const removePoint = (index: number) => {
    onChange({
      ...geometry,
      points: geometry.points.filter((_, candidateIndex) => candidateIndex !== index),
    });
  };

  return (
    <div className="vi-region-editor">
      <div className="vi-region-stage">
        <VisionStreamCanvas
          className="vi-region-video"
          eager
          liveSnapshotEnabled
          showReplayControls={false}
          showStatus={false}
          stream={stream}
          vstApiUrl={vstApiUrl}
        />
        <svg
          aria-label="Monitoring area editor"
          className="vi-region-overlay"
          onClick={(event) => {
            if (moved.current || dragging !== null || geometry.points.length >= 16) {
              moved.current = false;
              return;
            }
            onChange({ ...geometry, points: [...geometry.points, eventPoint(event)] });
          }}
          onPointerMove={(event) => {
            if (dragging === null) return;
            moved.current = true;
            replacePoint(dragging, eventPoint(event));
          }}
          onPointerUp={(event) => {
            if (dragging !== null) event.currentTarget.releasePointerCapture(event.pointerId);
            setDragging(null);
            window.setTimeout(() => { moved.current = false; }, 0);
          }}
          viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        >
          {geometry.points.length >= 2 && (
            <polyline
              className="vi-region-shape"
              points={polygon}
              {...(geometry.points.length >= 3 ? { fill: 'rgba(8, 197, 191, 0.17)' } : {})}
            />
          )}
          {geometry.points.length >= 3 && (
            <line
              className="vi-region-closing-line"
              x1={geometry.points.at(-1)!.x * VIEWBOX_WIDTH}
              y1={geometry.points.at(-1)!.y * VIEWBOX_HEIGHT}
              x2={geometry.points[0].x * VIEWBOX_WIDTH}
              y2={geometry.points[0].y * VIEWBOX_HEIGHT}
            />
          )}
          {geometry.points.map((point, index) => (
            <g
              key={index}
              aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight Delete Backspace"
              aria-label={`Region point ${index + 1}, ${Math.round(point.x * 100)} percent from left, ${Math.round(point.y * 100)} percent from top. Use arrow keys to move; Delete to remove.`}
              className="vi-region-handle-group"
              focusable="true"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                const step = event.shiftKey ? 0.05 : 0.01;
                const movements: Record<string, [number, number]> = {
                  ArrowDown: [0, step],
                  ArrowLeft: [-step, 0],
                  ArrowRight: [step, 0],
                  ArrowUp: [0, -step],
                };
                const movement = movements[event.key];
                if (movement) {
                  event.preventDefault();
                  replacePoint(index, {
                    x: clamp(point.x + movement[0]),
                    y: clamp(point.y + movement[1]),
                  });
                } else if (event.key === 'Delete' || event.key === 'Backspace') {
                  event.preventDefault();
                  removePoint(index);
                }
              }}
              role="group"
              tabIndex={0}
            >
              <circle
                className="vi-region-handle-hit"
                cx={point.x * VIEWBOX_WIDTH}
                cy={point.y * VIEWBOX_HEIGHT}
                r="18"
                onPointerDown={(event) => {
                  event.stopPropagation();
                  event.currentTarget.ownerSVGElement?.setPointerCapture(event.pointerId);
                  setDragging(index);
                }}
              />
              <circle
                className="vi-region-handle"
                cx={point.x * VIEWBOX_WIDTH}
                cy={point.y * VIEWBOX_HEIGHT}
                r="7"
              />
              <text
                className="vi-region-handle-number"
                x={point.x * VIEWBOX_WIDTH}
                y={point.y * VIEWBOX_HEIGHT + 3}
              >
                {index + 1}
              </text>
            </g>
          ))}
        </svg>
        <div className="vi-region-label">
          <IconPolygon size={16} /> Monitored area
        </div>
      </div>
      <div className="vi-region-toolbar">
        <div>
          {geometry.points.length >= 3 ? (
            <span className="is-complete"><IconCheck size={15} /> Area ready · drag or focus points to refine</span>
          ) : (
            <span>Click the video or use Add point {3 - geometry.points.length} more {3 - geometry.points.length === 1 ? 'time' : 'times'} to close the area</span>
          )}
        </div>
        <button
          type="button"
          disabled={geometry.points.length >= 16}
          onClick={() => onChange({
            ...geometry,
            points: [...geometry.points, keyboardPoint(geometry.points)],
          })}
        >
          <IconPlus size={16} /> Add point
        </button>
        <button
          type="button"
          disabled={!geometry.points.length}
          onClick={() => onChange({ ...geometry, points: geometry.points.slice(0, -1) })}
        >
          <IconArrowBackUp size={16} /> Undo
        </button>
        <button
          type="button"
          disabled={!geometry.points.length}
          onClick={() => onChange({ ...geometry, points: [] })}
        >
          <IconTrash size={16} /> Clear
        </button>
      </div>
    </div>
  );
}
