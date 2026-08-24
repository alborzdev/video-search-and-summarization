// SPDX-License-Identifier: MIT

import { createApiEndpoints } from "../api";
import type { StreamInfo, ChatSidebarQueryContext } from "../types";
import {
  getFileExtension,
  getStreamDisplayName,
  isRtspStream,
  fetchPictureWithQueue,
  getStreamType,
} from "../utils";
import { copyToClipboard } from "@nemo-agent-toolkit/ui";
import { Button } from "@nvidia/foundations-react-core";
import { IconCheck } from "@tabler/icons-react";
import React, { useState, useEffect, useRef, useCallback } from "react";

const TIMELINE_RETRY_COUNT = 5;
const TIMELINE_RETRY_DELAY_MS = 500;

interface StreamCardProps {
  stream: StreamInfo;
  isSelected: boolean;
  vstApiUrl?: string | null;
  onSelectionChange: (streamId: string, selected: boolean) => void;
  getEndTimeForStream: (streamId: string) => string | null;
  onPlay?: (stream: StreamInfo) => void;
  isLoadingPlay?: boolean;
  /** When set, adds this stream as a chip in the app Chat sidebar (and still copies JSON). */
  onAddChatQueryContext?: (ctx: ChatSidebarQueryContext) => void;
}

export const StreamCard: React.FC<StreamCardProps> = ({
  stream,
  isSelected,
  vstApiUrl,
  onSelectionChange,
  getEndTimeForStream,
  onPlay,
  isLoadingPlay = false,
  onAddChatQueryContext,
}) => {
  const extension = getFileExtension(stream.url);
  const displayName = getStreamDisplayName(stream.name);
  const isRtsp = isRtspStream(stream);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [isLoadingThumbnail, setIsLoadingThumbnail] = useState(true);
  const [thumbnailError, setThumbnailError] = useState(false);
  const currentObjectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    let retryTimer: NodeJS.Timeout | undefined;

    const fetchThumbnail = async (retryCount = 0) => {
      if (!vstApiUrl) {
        setThumbnailError(true);
        setIsLoadingThumbnail(false);
        return;
      }

      const apiEndpoints = createApiEndpoints(vstApiUrl);
      setIsLoadingThumbnail(true);
      setThumbnailError(false);

      try {
        let pictureUrl: string;

        if (isRtsp) {
          // VST's live-picture endpoint can block until its server timeout
          // when an RTSP source is disconnected even though retained footage
          // and the source record are still valid. Prefer the latest retained
          // frame whenever a timeline exists; it is stable for active, paused,
          // and recently disconnected cameras and keeps the source grid fast.
          const endTime = getEndTimeForStream(stream.streamId);
          if (!endTime && retryCount < TIMELINE_RETRY_COUNT && isMounted) {
            // Stream cards mount before the shared timeline request normally
            // completes. Do not launch a slow live-picture request during
            // that brief race; re-read the ref-backed timeline getter first.
            retryTimer = setTimeout(
              () => fetchThumbnail(retryCount + 1),
              TIMELINE_RETRY_DELAY_MS
            );
            return;
          }
          pictureUrl = endTime
            ? apiEndpoints.REPLAY_PICTURE(stream.streamId, endTime)
            : apiEndpoints.LIVE_PICTURE(stream.streamId);
        } else {
          const endTime = getEndTimeForStream(stream.streamId);
          if (!endTime) {
            if (retryCount < 5 && isMounted) {
              retryTimer = setTimeout(
                () => fetchThumbnail(retryCount + 1),
                1000
              );
              return;
            }
            throw new Error("No timeline available");
          }
          pictureUrl = apiEndpoints.REPLAY_PICTURE(stream.streamId, endTime);
        }

        const blob = await fetchPictureWithQueue(pictureUrl);
        const newUrl = URL.createObjectURL(blob);

        if (isMounted) {
          if (currentObjectUrlRef.current) {
            URL.revokeObjectURL(currentObjectUrlRef.current);
          }
          currentObjectUrlRef.current = newUrl;
          setThumbnailUrl(newUrl);
        } else {
          URL.revokeObjectURL(newUrl);
        }
      } catch {
        if (isMounted) setThumbnailError(true);
      } finally {
        if (isMounted) setIsLoadingThumbnail(false);
      }
    };

    fetchThumbnail();
    return () => {
      isMounted = false;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [stream.streamId, isRtsp, vstApiUrl, getEndTimeForStream]);

  useEffect(() => {
    return () => {
      if (currentObjectUrlRef.current) {
        URL.revokeObjectURL(currentObjectUrlRef.current);
        currentObjectUrlRef.current = null;
      }
    };
  }, []);

  const [copyState, setCopyState] = useState<"idle" | "success" | "error">(
    "idle"
  );
  const copyTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSelectionChange(stream.streamId, e.target.checked);
  };

  const handleCopyContext = useCallback(async () => {
    const data = {
      sensorName: stream.name,
      streamId: stream.streamId,
      mediaType: getStreamType(stream),
    };
    const text = JSON.stringify(data, null, 2);

    onAddChatQueryContext?.({
      id: `video-mgmt-stream:${stream.streamId}`,
      label: stream.name,
      // contextType: UI-only (chip tooltip / future grouping); not sent to the backend — see Chat onSend.
      contextType: "media/video",
      data,
    });

    try {
      await copyToClipboard(text);
      setCopyState("success");
    } catch {
      setCopyState("error");
    }
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    copyTimeoutRef.current = setTimeout(() => {
      setCopyState("idle");
      copyTimeoutRef.current = null;
    }, 2000);
  }, [stream, onAddChatQueryContext]);

  return (
    <div
      className={`vm-stream-card rounded-lg border overflow-hidden bg-white dark:bg-neutral-900 border-gray-200 dark:border-gray-700 ${
        isSelected ? "is-selected" : ""
      }`}
    >
      <div className="vm-stream-card__header flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-neutral-900">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={handleCheckboxChange}
          aria-label={`Select ${stream.name}`}
          className="w-4 h-4 rounded border-2 cursor-pointer bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-green-600 dark:text-green-500 focus:ring-green-500"
        />
        <p
          className="text-sm font-medium truncate flex-1 text-gray-800 dark:text-gray-200 min-w-0"
          title={`${displayName} · ${stream.name}`}
        >
          {displayName}
        </p>
        {onAddChatQueryContext ? (
          <Button
            kind="primary"
            size="small"
            className="flex-shrink-0 text-xs"
            onClick={handleCopyContext}
            title="Add sensor context to chat"
          >
            {copyState === "success" ? (
              <>
                <IconCheck
                  className="w-2.5 h-2.5 shrink-0"
                  style={{ color: "inherit" }}
                />
                <span>Added</span>
              </>
            ) : copyState === "error" ? (
              <span>Failed</span>
            ) : (
              <span>+ Chat</span>
            )}
          </Button>
        ) : null}
      </div>

      <div className="group relative flex items-center justify-center bg-gray-100 dark:bg-neutral-900 pb-[56.25%]">
        {thumbnailUrl && !thumbnailError ? (
          <img
            src={thumbnailUrl}
            alt={displayName}
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : isLoadingThumbnail ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="animate-pulse w-8 h-8 rounded-full bg-gray-600" />
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-200 dark:bg-neutral-900">
            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-gray-300 dark:bg-gray-700">
              <svg
                className="text-gray-500 dark:text-gray-400"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
          </div>
        )}

        <div className={`vm-stream-kind ${isRtsp ? "is-live" : ""}`}>
          {isRtsp && (
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden
            >
              <circle cx="12" cy="12" r="2" fill="currentColor" />
              <path d="M8.5 8.5a5 5 0 010 7M15.5 8.5a5 5 0 010 7" />
            </svg>
          )}
          {isRtsp ? "LIVE · RTSP" : extension || "VIDEO"}
        </div>

        {onPlay && (
          <button
            type="button"
            onClick={() => !isLoadingPlay && onPlay(stream)}
            disabled={isLoadingPlay}
            className={`absolute inset-0 flex items-center justify-center transition-colors duration-200 ${
              isLoadingPlay
                ? "bg-black/40 cursor-wait"
                : "bg-black/0 group-hover:bg-black/40 cursor-pointer"
            }`}
            aria-label={
              isLoadingPlay ? `Loading ${stream.name}` : `Play ${stream.name}`
            }
          >
            <div
              className={`vm-stream-play w-12 h-12 flex items-center justify-center rounded-full shadow-lg transition-opacity duration-200 ${
                isLoadingPlay
                  ? "opacity-100"
                  : "opacity-90 group-hover:opacity-100"
              }`}
            >
              {isLoadingPlay ? (
                <svg
                  className="w-6 h-6 text-gray-800 dark:text-white animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="3"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
              ) : (
                <svg
                  width="21"
                  height="21"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden
                >
                  <path d="M8 5v14l11-7z" />
                </svg>
              )}
            </div>
          </button>
        )}
      </div>

      <div className="vm-stream-card__footer px-3 py-2">
        <span
          className={isRtsp ? "vm-source-state is-live" : "vm-source-state"}
        >
          <i /> {isRtsp ? "Live source" : "Recorded source"}
        </span>
        <div className="flex items-center justify-end gap-2">
          {stream.metadata.codec && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {stream.metadata.codec.toUpperCase()}
            </span>
          )}
          {stream.metadata.framerate && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {parseFloat(stream.metadata.framerate).toFixed(0)} fps
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
