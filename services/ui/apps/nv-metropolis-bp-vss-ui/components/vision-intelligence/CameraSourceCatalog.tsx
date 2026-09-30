// SPDX-License-Identifier: MIT

import type {
  SourceAnalysisState,
  SourceIntelligence,
} from "./OperationsWorkspace";
import { VisionStreamCanvas, type PlaybackStatus } from "./VisionStreamCanvas";
import type { VisionStream } from "./types";
import { sourceKind, streamDisplayName } from "./utils";
import {
  IconArrowLeft,
  IconArrowRight,
  IconFile,
  IconPlayerPause,
  IconPlayerPlayFilled,
  IconSettings,
} from "@tabler/icons-react";
import React, { useState } from "react";

function SourcePreview({
  stream,
  vstApiUrl,
  eager,
}: {
  stream: VisionStream;
  vstApiUrl?: string | null;
  eager: boolean;
}) {
  const [playback, setPlayback] = useState<PlaybackStatus>(
    eager ? "connecting" : "idle"
  );
  return (
    <figure className="vi-camera-source-preview" data-playback={playback}>
      <div className="vi-camera-source-frame">
        <VisionStreamCanvas
          eager={eager}
          liveSnapshotEnabled={false}
          stream={stream}
          vstApiUrl={vstApiUrl}
          onPlaybackStatus={setPlayback}
        />
      </div>
      {eager && (
        <figcaption>
          {playback === "playing"
            ? "Live preview"
            : playback === "poster"
            ? "Stored preview · live video unavailable"
            : playback === "error"
            ? "Preview unavailable"
            : "Connecting live preview"}
        </figcaption>
      )}
    </figure>
  );
}

export function CameraSourceCatalog({
  streams,
  analysisStateById,
  intelligenceById,
  onFocus,
  onBack,
  onOpenRules,
  vstApiUrl,
}: {
  streams: VisionStream[];
  analysisStateById: Record<string, SourceAnalysisState>;
  intelligenceById: Record<string, SourceIntelligence>;
  onFocus: (stream: VisionStream) => void;
  onBack: () => void;
  onOpenRules: (stream?: VisionStream) => void;
  vstApiUrl?: string | null;
}) {
  const live = streams.filter((stream) => sourceKind(stream) === "Live");
  const connected = live.filter(
    (stream) => !["offline", "removed"].includes(stream.connectionState ?? "")
  );
  const disconnected = live.filter((stream) => !connected.includes(stream));
  const recordings = streams.filter((stream) => sourceKind(stream) !== "Live");
  return (
    <section className="vi-camera-catalog" aria-label="Video source browser">
      <header className="vi-camera-heading">
        <div>
          <h1>All sources</h1>
          <p>Choose a camera or recording to inspect its footage.</p>
        </div>
        <button className="vi-camera-button" type="button" onClick={onBack}>
          <IconArrowLeft size={18} />
          Back to camera
        </button>
      </header>
      {live.length > 0 && (
        <section className="vi-camera-catalog-section">
          <h2>Live cameras</h2>
          <div className="vi-camera-catalog-grid">
            {connected.map((stream, index) => {
              const state = analysisStateById[stream.streamId] ?? "unknown";
              const label =
                state === "paused"
                  ? "Analysis paused"
                  : state === "active"
                  ? "Analysis active"
                  : state === "changing"
                  ? "Updating analysis"
                  : state === "partial"
                  ? "Analysis needs attention"
                  : "Checking analysis";
              const moments =
                intelligenceById[stream.streamId]?.semanticSegments;
              return (
                <article
                  className="vi-camera-source"
                  key={`${stream.sensorId}:${stream.streamId}`}
                >
                  <SourcePreview
                    stream={stream}
                    vstApiUrl={vstApiUrl}
                    eager={index === 0}
                  />
                  <div className="vi-camera-source-content">
                    <h3>{streamDisplayName(stream.name)}</h3>
                    <div className="vi-camera-source-status">
                      <span>
                        <i />
                        {stream.connectionState === "online"
                          ? "Connected"
                          : "Checking connection"}
                      </span>
                      <span className={state === "paused" ? "is-paused" : ""}>
                        {state === "paused" && <IconPlayerPause size={16} />}{" "}
                        {label}
                      </span>
                    </div>
                    <p>
                      {state === "paused"
                        ? "Earlier footage is searchable. New activity is not being indexed."
                        : moments !== undefined && moments !== null
                        ? `${moments.toLocaleString()} indexed moments are available to search.`
                        : "Open this source to check recording and search coverage."}
                    </p>
                    <div className="vi-camera-source-actions">
                      <button
                        className="vi-camera-primary"
                        type="button"
                        aria-label={`Review source ${streamDisplayName(
                          stream.name
                        )}`}
                        onClick={() => onFocus(stream)}
                      >
                        <IconPlayerPlayFilled size={17} />
                        Review source
                      </button>
                      <button
                        className="vi-camera-button"
                        type="button"
                        aria-label={`Monitoring rules for ${streamDisplayName(
                          stream.name
                        )}`}
                        onClick={() => onOpenRules(stream)}
                      >
                        <IconSettings size={17} />
                        Monitoring rules
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
          {disconnected.length > 0 && (
            <details className="vi-camera-disconnected">
              <summary>
                {disconnected.length} disconnected cameras · Connection details
              </summary>
              <p>
                Check the camera or simulator connection before resuming
                analysis.
              </p>
              {disconnected.map((stream) => (
                <div className="vi-camera-recording-row" key={stream.streamId}>
                  <div>
                    <strong>{streamDisplayName(stream.name)}</strong>
                    <span>Disconnected</span>
                  </div>
                  <button
                    className="vi-camera-button"
                    type="button"
                    aria-label={`Review source ${streamDisplayName(
                      stream.name
                    )}`}
                    onClick={() => onFocus(stream)}
                  >
                    Review source
                    <IconArrowRight size={16} />
                  </button>
                </div>
              ))}
            </details>
          )}
        </section>
      )}
      {recordings.length > 0 && (
        <section className="vi-camera-catalog-section">
          <h2>Recorded footage</h2>
          {recordings.map((stream) => (
            <div
              className="vi-camera-recording-row"
              key={`${stream.sensorId}:${stream.streamId}`}
            >
              <IconFile size={25} />
              <div>
                <strong>{streamDisplayName(stream.name)}</strong>
                <span>Recorded video</span>
              </div>
              <button
                className="vi-camera-button"
                type="button"
                aria-label={`Open recording ${streamDisplayName(stream.name)}`}
                onClick={() => onFocus(stream)}
              >
                Open recording
                <IconArrowRight size={17} />
              </button>
            </div>
          ))}
        </section>
      )}
    </section>
  );
}
