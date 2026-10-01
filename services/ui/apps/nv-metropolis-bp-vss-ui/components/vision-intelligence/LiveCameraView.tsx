// SPDX-License-Identifier: MIT

import { CameraActivityPanel } from "./CameraActivityPanel";
import { CameraQuestionComposer } from "./CameraQuestionComposer";
import type {
  SourceAnalysisState,
  SourceIntelligence,
} from "./OperationsWorkspace";
import { VisionStreamCanvas, type PlaybackStatus } from "./VisionStreamCanvas";
import type { SourceAnalysisProfile } from "./analysisProfiles";
import type { VisionAnalystPlaybackContext } from "./analyst";
import type { VisionStream } from "./types";
import { useLiveCapture } from "./useLiveCapture";
import { DEFAULT_LOOKBACK_SECONDS, validLookbackSeconds } from "./footageWindow";
import { sourceKind, streamDisplayName } from "./utils";
import {
  IconArrowRight,
  IconChevronDown,
  IconEye,
  IconHistory,
} from "@tabler/icons-react";
import React, { useState } from "react";

export function LiveCameraView({
  camera,
  analysisState,
  intelligence,
  intelligenceLoading,
  analysisProfile,
  analysisProfiles,
  controlError,
  isAsking,
  isUpdatingAnalysis,
  onAsk,
  onPlaybackContext,
  onOpenHistory,
  onInvestigateSource,
  onToggleAnalysis,
  onSetAnalysisProfile,
  onShowCameras,
  evidenceEvents,
  observedRange,
  vstApiUrl,
  visualAnalystAvailable,
  answer,
}: {
  camera: VisionStream;
  analysisState: SourceAnalysisState;
  intelligence: SourceIntelligence | null;
  intelligenceLoading: boolean;
  analysisProfile: SourceAnalysisProfile | null;
  analysisProfiles: SourceAnalysisProfile[];
  controlError: string | null;
  isAsking: boolean;
  isUpdatingAnalysis: boolean;
  onAsk: (query: string, lookbackSeconds?: number) => void;
  onPlaybackContext: (context: VisionAnalystPlaybackContext) => void;
  onOpenHistory: () => void;
  onInvestigateSource: () => void;
  onToggleAnalysis: () => void;
  onSetAnalysisProfile: (profileId: string) => void;
  onShowCameras: () => void;
  evidenceEvents: Array<{
    endTime?: string;
    id: string;
    label: string;
    startTime: string;
  }>;
  observedRange?: { endSeconds: number; startSeconds: number };
  vstApiUrl?: string | null;
  visualAnalystAvailable?: boolean | null;
  answer?: React.ReactNode;
}) {
  const [playback, setPlayback] = useState<PlaybackStatus>("connecting");
  const [lookbackSeconds, setLookbackSeconds] = useState<number | null>(DEFAULT_LOOKBACK_SECONDS);
  const validDuration = validLookbackSeconds(lookbackSeconds);
  const capture = useLiveCapture(camera, {
    visualAnalystAvailable,
    busy: isAsking,
    lookbackSeconds: validDuration ? lookbackSeconds : DEFAULT_LOOKBACK_SECONDS,
  });
  const live = sourceKind(camera) === "Live";
  const disconnected =
    live && (camera.connectionState === "removed" ||
      (camera.connectionState === "offline" && playback !== "playing"));
  const connectionLabel = !live
    ? "Recorded video"
    : disconnected
    ? "Disconnected · RTSP feed"
    : playback === "playing"
    ? "Connected · RTSP feed"
    : "Checking connection · RTSP feed";
  const videoLabel =
    playback === "playing"
      ? live
        ? "Live preview"
        : "Recorded playback"
      : playback === "poster"
      ? live
        ? "Stored preview · live video unavailable"
        : "Stored preview"
      : playback === "error"
      ? "Video preview unavailable"
      : live
      ? "Connecting live preview"
      : "Preparing recorded playback";
  const notice =
    capture.questionBlockReason
      ? capture.questionBlockReason
      : visualAnalystAvailable !== true
      ? visualAnalystAvailable === false
        ? "Visual AI is unavailable. Check System readiness."
        : "Checking visual AI readiness."
      : disconnected && !capture.canAsk
      ? "Connect this camera before asking about live activity."
      : live && capture.capture === "off"
      ? "Start live capture to ask about recent footage."
      : live && capture.capture === "unknown"
      ? "Checking live recording before enabling questions."
      : capture.warming
      ? capture.readinessError || (capture.remainingSeconds === null
        ? `Waiting for ${validDuration ? lookbackSeconds : DEFAULT_LOOKBACK_SECONDS} seconds of recent recorded footage.`
        : `Preparing footage · about ${capture.remainingSeconds}s more footage needed`)
      : undefined;
  return (
    <section
      className="vi-camera-focused"
      aria-label="Selected camera workspace"
    >
      <header className="vi-camera-heading">
        <div>
          <h1>{streamDisplayName(camera.name)}</h1>
          <p
            className={
              !disconnected && playback === "playing" ? "is-connected" : ""
            }
          >
            <i />
            {connectionLabel}
          </p>
        </div>
        <button
          className="vi-camera-button"
          type="button"
          aria-label="Sources"
          onClick={onShowCameras}
        >
          <IconEye size={19} />
          Sources
          <IconChevronDown size={17} />
        </button>
      </header>
      <div className="vi-camera-layout">
        <div className="vi-camera-scene">
          <figure className="vi-camera-video" data-playback={playback}>
            <div className="vi-camera-video-frame">
              <VisionStreamCanvas
                evidenceEvents={evidenceEvents}
                liveSnapshotEnabled={false}
                observedRange={observedRange}
                showReplayControls={!live}
                stream={camera}
                vstApiUrl={vstApiUrl}
                onPlaybackContext={onPlaybackContext}
                onPlaybackStatus={setPlayback}
              />
            </div>
            <figcaption>
              <span>
                <i className={playback === "playing" ? "is-playing" : ""} />
                {videoLabel}
              </span>
              <button
                type="button"
                aria-label="Video history"
                onClick={onOpenHistory}
              >
                <IconHistory size={18} />
                Video history
                <IconArrowRight size={15} />
              </button>
            </figcaption>
          </figure>
          <CameraQuestionComposer
            name={camera.name}
            recorded={!live}
            canAsk={capture.canAsk && (!live || validDuration)}
            isLoading={isAsking}
            notice={notice}
            questionBlockReason={capture.questionBlockReason}
            onAsk={(query) => {
              if (!live) onAsk(query);
              else if (validLookbackSeconds(lookbackSeconds)) onAsk(query, lookbackSeconds);
            }}
            lookbackSeconds={lookbackSeconds}
            onLookbackSecondsChange={setLookbackSeconds}
            durationDisabled={capture.changing}
            onStartCapture={
              live &&
              capture.capture === "off" &&
              camera.connectionState !== "removed" &&
              visualAnalystAvailable === true &&
              !capture.changing
                ? () => void capture.toggle()
                : undefined
            }
          >
            {answer}
          </CameraQuestionComposer>
        </div>
        <CameraActivityPanel
          stream={camera}
          analysisState={analysisState}
          analysisProfile={analysisProfile}
          analysisProfiles={analysisProfiles}
          intelligence={intelligence}
          isLoading={intelligenceLoading}
          isUpdating={isUpdatingAnalysis}
          isAsking={isAsking}
          controlError={controlError}
          capture={capture}
          livePreviewAvailable={playback === "playing"}
          visualAnalystAvailable={visualAnalystAvailable}
          onToggleAnalysis={onToggleAnalysis}
          onSetAnalysisProfile={onSetAnalysisProfile}
          onInvestigate={onInvestigateSource}
        />
      </div>
    </section>
  );
}
