// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import type { StreamInfo } from "../types";
import { Button } from "@nvidia/foundations-react-core";
import React, { useEffect, useState } from "react";

const POPUP_OVERLAY_VIEWPORT =
  "fixed inset-0 z-50 flex items-center justify-center bg-black/50";
/** Covers only the parent `relative` region (e.g. Video Management main pane), not the whole browser window */
const POPUP_OVERLAY_CONTAINED =
  "absolute inset-0 z-40 flex items-center justify-center bg-black/50";

interface DeleteConfirmDialogProps {
  isOpen: boolean;
  streams: StreamInfo[];
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  mode?: "delete" | "reset";
  clearRecordings?: boolean;
  onClearRecordingsChange?: (value: boolean) => void;
  /** `contained` = overlay only the nearest positioned ancestor (Video Management pane). Default `viewport` = full window. */
  overlay?: "viewport" | "contained";
}

// Cap the preview list so very large selections don't blow out the dialog height.
const MAX_NAMES_PREVIEW = 5;

export const DeleteConfirmDialog: React.FC<DeleteConfirmDialogProps> = ({
  isOpen,
  streams,
  isDeleting,
  onCancel,
  onConfirm,
  mode = "delete",
  clearRecordings = true,
  onClearRecordingsChange,
  overlay = "viewport",
}) => {
  // Snapshot the streams prop at the moment the dialog opens. The parent may
  // clear its `selectedStreams` set during the delete flow (after the API
  // resolves but before refetch finishes), which would make `streams` go empty
  // mid-confirm and cause the preview list to vanish while the dialog is still
  // visible. Snapshotting keeps the displayed list stable for the dialog's
  // entire open lifetime.
  const [snapshot, setSnapshot] = useState<StreamInfo[]>(streams);

  useEffect(() => {
    if (isOpen) {
      setSnapshot(streams);
    }
    // Intentionally only re-snapshot on open transition, not on every streams change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const dialogRef = useDialogAccessibility<HTMLDivElement>({
    isOpen,
    onClose: onCancel,
    dismissible: !isDeleting,
  });

  if (!isOpen) return null;

  const count = snapshot.length;
  const isReset = mode === "reset";

  const previewNames = snapshot.slice(0, MAX_NAMES_PREVIEW).map((s) => s.name);
  const remaining = Math.max(0, count - previewNames.length);

  const handleBackdropClick = () => {
    if (!isDeleting) onCancel();
  };

  const overlayClass =
    overlay === "contained" ? POPUP_OVERLAY_CONTAINED : POPUP_OVERLAY_VIEWPORT;
  const dialogMaxHeight =
    overlay === "contained" ? "calc(100% - 2rem)" : "calc(100dvh - 2rem)";

  return (
    <div
      className={`${overlayClass} overflow-y-auto p-4`}
      onClick={handleBackdropClick}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-confirm-title"
        aria-describedby="delete-confirm-desc"
        data-testid="delete-confirm-dialog"
        className="relative z-50 flex w-full max-w-[520px] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-black"
        style={{ maxHeight: dialogMaxHeight }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-600">
          <div className="flex items-center gap-3">
            <svg
              className="text-red-500 dark:text-red-400"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
              <path d="M10 11v6" />
              <path d="M14 11v6" />
              <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
            </svg>
            <span
              id="delete-confirm-title"
              className="text-sm font-medium uppercase tracking-wide text-gray-800 dark:text-gray-200"
            >
              {isReset ? "CLEAR GENERATED LIVE DATA" : "DELETE STREAMS/VIDEOS"}
            </span>
          </div>
          <button
            onClick={onCancel}
            disabled={isDeleting}
            aria-label="Close"
            className="p-1.5 rounded transition-colors text-gray-400 hover:text-white hover:bg-neutral-700 dark:text-gray-400 dark:hover:text-white dark:hover:bg-neutral-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div
          id="delete-confirm-desc"
          className="min-h-0 flex-1 overflow-y-auto p-6 space-y-4"
        >
          {isReset ? (
            <>
              <p className="text-sm text-gray-700 dark:text-gray-300">
                Clear embeddings, detector and tracker records, behavior
                analytics, alerts, incidents, and generated captions for the
                selected live source{count === 1 ? "" : "s"}?
              </p>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                The camera stays connected. Live analysis resumes automatically
                and new searchable data starts accumulating immediately.
              </p>
              <label className="flex items-start gap-3 rounded-md border border-gray-200 bg-gray-50 p-3 text-sm dark:border-gray-700 dark:bg-neutral-900">
                <input
                  type="checkbox"
                  checked={clearRecordings}
                  onChange={(event) =>
                    onClearRecordingsChange?.(event.target.checked)
                  }
                  disabled={isDeleting}
                  className="mt-0.5 h-4 w-4"
                />
                <span>
                  <strong className="block text-gray-800 dark:text-gray-200">
                    Also clear retained live clips
                  </strong>
                  <span className="text-gray-600 dark:text-gray-400">
                    Deletes the current VIOS archive for these cameras;
                    recording begins again after reset.
                  </span>
                </span>
              </label>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-700 dark:text-gray-300">
                Delete the selected sources and all of their generated data?
              </p>
              <p
                data-testid="delete-irreversible-warning"
                className="text-sm font-medium text-red-700 dark:text-red-300"
              >
                This removes the source, retained media, embeddings, detections,
                events, and captions. It cannot be undone.
              </p>
            </>
          )}

          {previewNames.length > 0 && (
            <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-neutral-900 max-h-40 overflow-auto">
              <ul className="m-0 p-0 list-none text-sm text-gray-700 dark:text-gray-300 divide-y divide-gray-200 dark:divide-gray-700">
                {previewNames.map((name, idx) => (
                  <li
                    key={`${name}-${idx}`}
                    className="px-3 py-2 flex items-center gap-2 min-h-9 leading-5"
                  >
                    <span
                      className="inline-block w-2 h-2 rounded-full bg-red-500 dark:bg-red-400 flex-shrink-0"
                      aria-hidden="true"
                    />
                    <span className="truncate" title={name}>
                      {name}
                    </span>
                  </li>
                ))}
                {remaining > 0 && (
                  <li className="px-3 py-2 min-h-9 flex items-center text-xs text-gray-500 dark:text-gray-400 italic leading-5">
                    + {remaining} more
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex shrink-0 items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-600">
          <Button kind="secondary" onClick={onCancel} disabled={isDeleting}>
            Cancel
          </Button>
          {/* Destructive confirm. Foundations v0.600.0 has no `danger` kind, so we render a
              styled native button that matches the nv-button padding/radius but uses the red
              accent reserved for destructive actions elsewhere in this codebase. */}
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            data-testid="delete-confirm-button"
            className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors bg-red-600 text-white hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-black disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {isDeleting && (
              <svg
                className="animate-spin"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
                <path d="M12 2a10 10 0 0 1 10 10" strokeOpacity="1" />
              </svg>
            )}
            {isDeleting
              ? isReset
                ? "Clearing..."
                : "Deleting..."
              : isReset
              ? "Clear and resume"
              : "Delete everything"}
          </button>
        </div>
      </div>
    </div>
  );
};
