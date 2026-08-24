// SPDX-License-Identifier: MIT

import { proxyVstPictureUrl } from "./utils";
import {
  IconArrowLeft,
  IconBox,
  IconRefresh,
  IconSearch,
} from "@tabler/icons-react";
import React, { useEffect, useMemo, useState } from "react";

export interface DetectedObject {
  bbox: {
    bottomY: number;
    leftX: number;
    rightX: number;
    topY: number;
  };
  id: string;
  type?: string;
}

export interface VisualReference {
  objectId: string;
  objectType: string;
  sensorId: string;
  sensorName: string;
  timestamp: string;
}

interface FrameApiObject {
  bbox?: {
    bottom?: number;
    bottomY?: number;
    left?: number;
    leftX?: number;
    right?: number;
    rightX?: number;
    top?: number;
    topY?: number;
  };
  class?: string;
  className?: string;
  id?: string;
  objectId?: string;
  objectType?: string;
  type?: string;
}

interface FrameApiItem {
  frame_timestamp?: string;
  metadata?: { objects?: FrameApiObject[] };
  objects?: FrameApiObject[];
  timestamp?: string;
}

interface FindSimilarSelectorProps {
  frameTimestamp: string;
  mdxWebApiUrl: string;
  onCancel: () => void;
  onSearch: (reference: VisualReference) => Promise<string | null>;
  preferredObjectType?: string;
  sensorId: string;
  sensorName: string;
  vstApiUrl: string;
}

interface FrameSelectionData {
  height: number;
  objects: DetectedObject[];
  pictureUrl: string;
  timestamp: string;
  width: number;
}

// Search chunks and detector frames have independent sampling cadences. This
// window finds the nearest real detector frame without inventing metadata.
const FRAME_WINDOW_MS = 5_000;

function finiteCoordinate(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function parseDetectedObjects(
  objects: FrameApiObject[]
): DetectedObject[] {
  return objects.flatMap((object) => {
    const id = object.id ?? object.objectId;
    const bbox = object.bbox;
    if (id === undefined || id === null || !bbox) return [];

    const leftX = finiteCoordinate(bbox.leftX ?? bbox.left);
    const topY = finiteCoordinate(bbox.topY ?? bbox.top);
    const rightX = finiteCoordinate(bbox.rightX ?? bbox.right);
    const bottomY = finiteCoordinate(bbox.bottomY ?? bbox.bottom);
    if (
      leftX === null ||
      topY === null ||
      rightX === null ||
      bottomY === null ||
      rightX <= leftX ||
      bottomY <= topY
    ) {
      return [];
    }

    return [
      {
        bbox: { bottomY, leftX, rightX, topY },
        id: String(id),
        type:
          object.type ?? object.class ?? object.className ?? object.objectType,
      },
    ];
  });
}

export function closestFrame(
  payload: unknown,
  requestedTimestamp: string,
  preferredObjectType?: string
): { objects: DetectedObject[]; timestamp: string } | null {
  const shaped = payload as { frames?: FrameApiItem[] };
  const frames: FrameApiItem[] = Array.isArray(payload)
    ? (payload as FrameApiItem[])
    : Array.isArray(shaped?.frames)
    ? shaped.frames
    : [];
  const requested = Date.parse(requestedTimestamp);
  const preferred = preferredObjectType?.trim().toLowerCase() ?? "";
  let best: FrameApiItem | null = null;
  let bestDelta = Number.POSITIVE_INFINITY;
  let bestPreferred: FrameApiItem | null = null;
  let bestPreferredDelta = Number.POSITIVE_INFINITY;

  for (const frame of frames) {
    const timestamp = frame.timestamp ?? frame.frame_timestamp;
    const parsed = timestamp ? Date.parse(timestamp) : Number.NaN;
    if (!timestamp || !Number.isFinite(parsed)) continue;
    const delta = Math.abs(parsed - requested);
    const objects = parseDetectedObjects(
      frame.metadata?.objects ?? frame.objects ?? []
    );
    const containsPreferredObject =
      preferred.length > 0 &&
      objects.some((object) => {
        const type = object.type?.trim().toLowerCase();
        return Boolean(type && preferred.includes(type));
      });
    if (containsPreferredObject && delta < bestPreferredDelta) {
      bestPreferred = frame;
      bestPreferredDelta = delta;
    }
    if (delta < bestDelta) {
      best = frame;
      bestDelta = delta;
    }
  }

  best = bestPreferred ?? best;
  if (!best) return null;
  return {
    objects: parseDetectedObjects(best.metadata?.objects ?? best.objects ?? []),
    timestamp: best.timestamp ?? best.frame_timestamp ?? requestedTimestamp,
  };
}

function imageDimensions(
  url: string,
  signal: AbortSignal
): Promise<{ height: number; width: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const abort = () => {
      image.src = "";
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", abort, { once: true });
    image.onload = () => {
      signal.removeEventListener("abort", abort);
      resolve({
        height: image.naturalHeight || image.height,
        width: image.naturalWidth || image.width,
      });
    };
    image.onerror = () => {
      signal.removeEventListener("abort", abort);
      reject(new Error("The selected video frame could not be loaded."));
    };
    image.src = url;
  });
}

function objectLabel(object: DetectedObject): string {
  return `${object.type?.trim() || "Object"} ${object.id}`;
}

export function FindSimilarSelector({
  frameTimestamp,
  mdxWebApiUrl,
  onCancel,
  onSearch,
  preferredObjectType,
  sensorId,
  sensorName,
  vstApiUrl,
}: FindSimilarSelectorProps) {
  const [retryKey, setRetryKey] = useState(0);
  const [data, setData] = useState<FrameSelectionData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setData(null);
      setError(null);
      setSearchError(null);
      setSelectedObjectId(null);
      try {
        const requestedMs = Date.parse(frameTimestamp);
        if (!Number.isFinite(requestedMs)) {
          throw new Error("The selected frame has an invalid timestamp.");
        }
        const fromTimestamp = new Date(
          requestedMs - FRAME_WINDOW_MS
        ).toISOString();
        const toTimestamp = new Date(
          requestedMs + FRAME_WINDOW_MS
        ).toISOString();
        const frameParams = new URLSearchParams({
          fromTimestamp,
          sensorId: sensorName,
          toTimestamp,
        });
        const metadataResponse = await fetch(
          `${mdxWebApiUrl}/frames?${frameParams.toString()}`,
          { signal: controller.signal }
        );
        if (!metadataResponse.ok) {
          throw new Error(
            `Object metadata returned ${metadataResponse.status}.`
          );
        }
        const match = closestFrame(
          await metadataResponse.json(),
          frameTimestamp,
          preferredObjectType
        );
        if (!match) {
          throw new Error(
            "No indexed detector frame was found near this moment."
          );
        }

        const pictureParams = new URLSearchParams({
          startTime: match.timestamp,
        });
        const pictureUrl = proxyVstPictureUrl(
          `${vstApiUrl}/v1/replay/stream/${encodeURIComponent(
            sensorId
          )}/picture?${pictureParams.toString()}`
        );
        const dimensions = await imageDimensions(pictureUrl, controller.signal);
        if (!dimensions.width || !dimensions.height) {
          throw new Error("The selected frame has no usable dimensions.");
        }
        if (!controller.signal.aborted) {
          setData({ ...dimensions, ...match, pictureUrl });
        }
      } catch (requestError) {
        if (
          !controller.signal.aborted &&
          !(
            requestError instanceof DOMException &&
            requestError.name === "AbortError"
          )
        ) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Objects could not be loaded for this frame."
          );
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [
    frameTimestamp,
    mdxWebApiUrl,
    preferredObjectType,
    retryKey,
    sensorId,
    sensorName,
    vstApiUrl,
  ]);

  const selectedObject = useMemo(
    () =>
      data?.objects.find((object) => object.id === selectedObjectId) ?? null,
    [data?.objects, selectedObjectId]
  );

  if (!data) {
    return (
      <div className="vi-object-selector-state" aria-live="polite">
        {error ? (
          <>
            <IconBox size={30} />
            <strong>Objects are unavailable at this moment</strong>
            <p>{error}</p>
            <div>
              <button
                type="button"
                onClick={() => setRetryKey((key) => key + 1)}
              >
                <IconRefresh size={16} /> Retry
              </button>
              <button type="button" onClick={onCancel}>
                <IconArrowLeft size={16} /> Choose another moment
              </button>
            </div>
          </>
        ) : (
          <>
            <span className="vi-spinner" />
            <strong>Loading detector objects at this frame…</strong>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="vi-object-selector">
      <div className="vi-object-selector-stage">
        <svg
          aria-label={`${data.objects.length} detected objects available for visual search`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          viewBox={`0 0 ${data.width} ${data.height}`}
        >
          <image
            height={data.height}
            href={data.pictureUrl}
            width={data.width}
          />
          {data.objects.map((object) => {
            const selected = object.id === selectedObjectId;
            const width = object.bbox.rightX - object.bbox.leftX;
            const height = object.bbox.bottomY - object.bbox.topY;
            const label = objectLabel(object);
            const labelWidth = Math.max(92, label.length * 12 + 26);
            const labelY = Math.max(2, object.bbox.topY - 31);
            return (
              <g
                aria-label={`Select ${label}`}
                className={selected ? "is-selected" : ""}
                key={`${object.id}-${object.bbox.leftX}`}
                onClick={() => {
                  setSearchError(null);
                  setSelectedObjectId(selected ? null : object.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSearchError(null);
                    setSelectedObjectId(selected ? null : object.id);
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <rect
                  className="vi-object-box"
                  height={height}
                  vectorEffect="non-scaling-stroke"
                  width={width}
                  x={object.bbox.leftX}
                  y={object.bbox.topY}
                />
                <rect
                  className="vi-object-label-bg"
                  height="27"
                  rx="5"
                  width={labelWidth}
                  x={object.bbox.leftX}
                  y={labelY}
                />
                <text
                  className="vi-object-label"
                  x={object.bbox.leftX + 11}
                  y={labelY + 19}
                >
                  {label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="vi-object-selector-bar">
        <div>
          <IconBox size={18} />
          {data.objects.length ? (
            selectedObject ? (
              <span className={searchError ? "is-error" : undefined}>
                <strong>{objectLabel(selectedObject)}</strong>
                {searchError ?? "Selected as the visual reference"}
              </span>
            ) : (
              <span>
                <strong>Select a detected object</strong>
                These are real tracker boxes from the paused indexed frame.
              </span>
            )
          ) : (
            <span>
              <strong>No detector boxes at this moment</strong>
              Return to playback and pause where an object is clearly visible.
            </span>
          )}
        </div>
        <div className="vi-object-selector-actions">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="is-primary"
            disabled={!selectedObject || searching}
            type="button"
            onClick={async () => {
              if (!selectedObject) return;
              setSearching(true);
              setSearchError(null);
              try {
                const failure = await onSearch({
                  objectId: selectedObject.id,
                  objectType: selectedObject.type?.trim() || "Object",
                  sensorId,
                  sensorName,
                  timestamp: data.timestamp,
                });
                if (failure) setSearchError(failure);
              } finally {
                setSearching(false);
              }
            }}
          >
            {searching ? (
              <>
                <span className="vi-spinner" /> Checking visual index…
              </>
            ) : (
              <>
                <IconSearch size={16} /> Find similar
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
