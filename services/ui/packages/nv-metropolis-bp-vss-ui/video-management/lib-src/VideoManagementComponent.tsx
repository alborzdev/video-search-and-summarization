// SPDX-License-Identifier: MIT

import { createApiEndpoints } from "./api";
import { chunkedUpload, notifyUploadComplete } from "./chunkedUpload";
import {
  AddRtspDialog,
  DeleteConfirmDialog,
  EmptyState,
  LoadingState,
  StreamsGrid,
  Toolbar,
  UploadProgressPanel,
  VideoManagementSidebarControls,
  AgentUploadDialog,
  LiveStreamModal,
} from "./components";
import { NUM_PARALLEL_FILE_UPLOADS } from "./constants";
import { useStreams, useStorageTimelines } from "./hooks";
import { deleteRtspStream, resetRtspStream } from "./rtspStream";
import type {
  VideoManagementComponentProps,
  UploadProgress,
  StreamInfo,
} from "./types";
import { filterStreams, isRtspStream } from "./utils";
import { requestMonitoringSetup } from "./monitoringSetup";
import { SEMANTIC_ANALYSIS_PROFILE_ID } from "./analysisProfiles";
import { deleteVideo } from "./videoDelete";
import {
  UploadFilesDialog,
  VideoModal,
  useVideoModal,
  useChatVideoUploadCompleteSubscription,
} from "@nemo-agent-toolkit/ui";
import React, {
  useState,
  useCallback,
  useMemo,
  useEffect,
  useRef,
} from "react";

async function purgeEvidenceClipCache(streamId: string): Promise<void> {
  const response = await fetch(
    `/api/vision/evidence-cache?sensorId=${encodeURIComponent(streamId)}`,
    {
      method: "DELETE",
    }
  );
  if (!response.ok) {
    throw new Error("Generated evidence clips could not be cleared");
  }
}

async function purgeVideoHistory(sourceId: string): Promise<void> {
  const response = await fetch(
    `/api/vision/video-history?sourceId=${encodeURIComponent(sourceId)}`,
    { method: "DELETE" }
  );
  // A source that never had graph history is already in the desired state.
  if (!response.ok && response.status !== 404) {
    throw new Error("Source video history could not be cleared");
  }
}

async function purgeLiveAlertFocus(sourceId: string): Promise<void> {
  const response = await fetch(
    `/api/vision/live-alert-rules?sourceId=${encodeURIComponent(sourceId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error("The source's active live alert rule could not be released");
  }
}

async function purgeMonitoringRules(sourceId: string): Promise<void> {
  const response = await fetch(
    `/api/vision/monitoring-rules?sourceId=${encodeURIComponent(sourceId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error("The source's monitoring rules could not be removed");
  }
}

export type {
  VideoManagementComponentProps,
  VideoManagementSidebarControlHandlers,
} from "./types";

export const VideoManagementComponent: React.FC<
  VideoManagementComponentProps
> = ({
  videoManagementData,
  renderControlsInLeftSidebar = false,
  onControlsReady,
  isActive = true,
  addChatQueryContext,
  registerChatVideoUploadComplete,
}) => {
  const vstApiUrl = videoManagementData?.vstApiUrl;
  const agentApiUrl = videoManagementData?.agentApiUrl;
  const chatUploadFileConfigTemplateJson =
    videoManagementData?.chatUploadFileConfigTemplateJson;
  const enableAddRtspButton = videoManagementData?.enableAddRtspButton ?? true;
  const enableVideoUpload = videoManagementData?.enableVideoUpload ?? true;

  // Upload dialog state (chat-style upload with config fields)
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<
    Array<{
      id: string;
      file: File;
      isExpanded: boolean;
      formData: Record<string, any>;
    }>
  >([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Parse config template from videoManagementData (same as Chat component)
  const configTemplate = useMemo(() => {
    if (chatUploadFileConfigTemplateJson) {
      try {
        return JSON.parse(chatUploadFileConfigTemplateJson);
      } catch (error) {
        console.warn("Failed to parse upload file config template:", error);
      }
    }
    return null;
  }, [chatUploadFileConfigTemplateJson]);

  // Generate default form data from config template (same as Chat component)
  const generateDefaultFormData = useCallback((): Record<string, any> => {
    if (!configTemplate || !Array.isArray(configTemplate.fields)) {
      return { analysisProfileId: SEMANTIC_ANALYSIS_PROFILE_ID };
    }
    return configTemplate.fields.reduce(
      (acc: Record<string, any>, field: any) => {
        acc[field["field-name"]] = field["field-default-value"];
        return acc;
      },
      { analysisProfileId: SEMANTIC_ANALYSIS_PROFILE_ID } as Record<string, any>
    );
  }, [configTemplate]);

  const generateFileId = useCallback(() => {
    return `file_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
  }, []);

  const [isRtspModalOpen, setIsRtspModalOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [appliedSearchQuery, setAppliedSearchQuery] = useState("");
  const searchInputValueRef = useRef("");
  const [showVideos, setShowVideos] = useState(true);
  const [showRtsps, setShowRtsps] = useState(true);
  const [selectedStreams, setSelectedStreams] = useState<Set<string>>(
    new Set()
  );
  const [isDeleting, setIsDeleting] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [clearResetRecordings, setClearResetRecordings] = useState(true);
  const [operationNotice, setOperationNotice] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [loadingStreamId, setLoadingStreamId] = useState<string | null>(null);
  const [liveStream, setLiveStream] = useState<StreamInfo | null>(null);

  const isUploadingRef = useRef(false);
  const uploadSessionIdRef = useRef(0);
  const uploadAbortControllerRef = useRef<AbortController | null>(null);
  const pendingFilesQueueRef = useRef<Array<{ id: string; file: File }>>([]);

  useEffect(() => {
    isUploadingRef.current = isUploading;
  }, [isUploading]);

  // Sync display filter state with enabled features so label and filter stay correct
  useEffect(() => {
    if (!enableAddRtspButton) setShowRtsps(false);
  }, [enableAddRtspButton]);
  useEffect(() => {
    if (!enableVideoUpload) setShowVideos(false);
  }, [enableVideoUpload]);

  const { streams, isLoading, error, refetch } = useStreams({ vstApiUrl });
  const {
    getEndTimeForStream,
    getLastTimelineForStream,
    refetch: refetchTimelines,
  } = useStorageTimelines({ vstApiUrl });
  const { videoModal, openVideoModal, closeVideoModal } = useVideoModal(
    vstApiUrl ?? undefined
  );

  const filteredStreams = useMemo(
    () => filterStreams(streams, showVideos, showRtsps, appliedSearchQuery),
    [streams, showVideos, showRtsps, appliedSearchQuery]
  );

  const { hasVideoStreams, hasRtspStreams } = useMemo(() => {
    const hasVideo = streams.some((stream) => !isRtspStream(stream));
    const hasRtsp = streams.some(isRtspStream);
    return { hasVideoStreams: hasVideo, hasRtspStreams: hasRtsp };
  }, [streams]);

  const refetchRef = useRef(refetch);
  const refetchTimelinesRef = useRef(refetchTimelines);
  const vstApiUrlRef = useRef(vstApiUrl);

  useEffect(() => {
    refetchRef.current = refetch;
    refetchTimelinesRef.current = refetchTimelines;
  }, [refetch, refetchTimelines]);

  useEffect(() => {
    vstApiUrlRef.current = vstApiUrl;
  }, [vstApiUrl]);

  const handleRefresh = useCallback(async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      await Promise.all([refetchRef.current(), refetchTimelinesRef.current()]);
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing]);

  // Refetch streams when component becomes active
  useEffect(() => {
    if (isActive) {
      refetchRef.current();
      refetchTimelinesRef.current();
    }
  }, [isActive]);

  const refreshStreamsAfterChatUpload = useCallback(() => {
    refetchRef.current();
    refetchTimelinesRef.current();
  }, []);

  useChatVideoUploadCompleteSubscription(
    registerChatVideoUploadComplete,
    refreshStreamsAfterChatUpload
  );

  const processUploadQueue = useCallback(
    async (
      fileEntries: Array<{
        id: string;
        file: File;
        formData?: Record<string, any>;
      }>
    ) => {
      const abortController = new AbortController();
      uploadAbortControllerRef.current = abortController;
      uploadSessionIdRef.current += 1;
      const currentSessionId = uploadSessionIdRef.current;

      setIsUploading(true);
      const isSessionValid = () =>
        uploadSessionIdRef.current === currentSessionId;

      const uploadSingleFile = async (entry: {
        id: string;
        file: File;
        formData?: Record<string, any>;
      }): Promise<void> => {
        const { id, file, formData } = entry;

        if (!isSessionValid() || abortController.signal.aborted) return;

        setUploadProgress((prev) =>
          prev.map((p) =>
            p.id === id && p.status === "pending"
              ? { ...p, status: "uploading" }
              : p
          )
        );

        try {
          if (!vstApiUrl) {
            throw new Error("VST API URL not configured");
          }
          if (!agentApiUrl) {
            throw new Error("Agent API URL not configured");
          }

          // Step 1: Chunked upload directly to the video storage service
          // (bypasses agent, avoids Cloudflare 100s timeout on large files)
          const uploadEndpoints = createApiEndpoints(vstApiUrl);
          const videoUploadApiResponse = await chunkedUpload({
            file,
            uploadUrl: uploadEndpoints.UPLOAD_FILE,
            onProgress: (progress: number) => {
              if (!isSessionValid() || abortController.signal.aborted) return;
              setUploadProgress((prev) =>
                prev.map((p) =>
                  p.id === id && p.status === "uploading"
                    ? { ...p, progress }
                    : p
                )
              );
            },
            abortSignal: abortController.signal,
          });

          if (!isSessionValid()) return;

          // Step 2: Notify agent for post-processing (embeddings, RTVI registration, etc.).
          // We forward the upload response as-is so the agent picks out the fields
          // it cares about; keeps the UI decoupled from the storage API shape.
          setUploadProgress((prev) =>
            prev.map((p) =>
              p.id === id && p.status === "uploading"
                ? { ...p, status: "processing", progress: 100 }
                : p
            )
          );

          const monitoring = await requestMonitoringSetup({
            analysisProfileId:
              typeof formData?.analysisProfileId === "string"
                ? formData.analysisProfileId
                : SEMANTIC_ANALYSIS_PROFILE_ID,
            blocking: true,
            detectionEnabled:
              typeof formData?.analysisProfileId === "string" &&
              formData.analysisProfileId !== SEMANTIC_ANALYSIS_PROFILE_ID,
            name: file.name,
            sensorId: videoUploadApiResponse.sensorId as string,
            sourceKind: "recorded",
          });

          if (!isSessionValid() || abortController.signal.aborted) return;

          // Forward the per-upload custom params collected by the dialog
          // (from chatUploadFileConfigTemplateJson) so the agent can use them
          // downstream. Sent as `custom_params` on the /complete body.
          await notifyUploadComplete(
            agentApiUrl,
            file.name,
            videoUploadApiResponse,
            {
              ...formData,
              analysisProfileId: monitoring.analysisProfileId,
              detectionEnabled: monitoring.detectionEnabled,
              monitoringRuleCreated: monitoring.ruleCreated,
            },
            abortController.signal
          );

          if (!isSessionValid()) return;

          setUploadProgress((prev) =>
            prev.map((p) =>
              p.id === id &&
              (p.status === "uploading" || p.status === "processing")
                ? {
                    ...p,
                    status: "success",
                    progress: 100,
                  }
                : p
            )
          );
        } catch (err) {
          if (!isSessionValid()) return;

          const errorMessage =
            err instanceof Error ? err.message : "Upload failed";
          const isCancelled =
            err instanceof Error &&
            (err.name === "AbortError" ||
              err.message === "Upload was cancelled");

          setUploadProgress((prev) =>
            prev.map((p) =>
              p.id === id &&
              (p.status === "uploading" ||
                p.status === "pending" ||
                p.status === "processing")
                ? {
                    ...p,
                    status: isCancelled ? "cancelled" : "error",
                    error: isCancelled ? undefined : errorMessage,
                  }
                : p
            )
          );
        }
      };

      let entriesToProcess = fileEntries;

      while (entriesToProcess.length > 0) {
        for (
          let i = 0;
          i < entriesToProcess.length;
          i += NUM_PARALLEL_FILE_UPLOADS
        ) {
          if (!isSessionValid()) break;

          const batch = entriesToProcess.slice(
            i,
            i + NUM_PARALLEL_FILE_UPLOADS
          );
          await Promise.allSettled(
            batch.map((entry) => uploadSingleFile(entry))
          );
        }

        if (!isSessionValid()) return;

        // Check for any files queued during this batch
        if (pendingFilesQueueRef.current.length > 0) {
          entriesToProcess = [...pendingFilesQueueRef.current];
          pendingFilesQueueRef.current = [];
        } else {
          entriesToProcess = [];
        }
      }

      setIsUploading(false);
      await Promise.all([refetchRef.current(), refetchTimelinesRef.current()]);
    },
    [vstApiUrl, agentApiUrl]
  );

  const handleFilesSelected = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      // Open dialog for user input (chat-style upload with config fields)
      const newItems = Array.from(files).map((file) => ({
        id: generateFileId(),
        file,
        isExpanded: true,
        formData: generateDefaultFormData(),
      }));
      setSelectedFiles((prev) => [...prev, ...newItems]);
      setShowUploadDialog(true);
    },
    [generateFileId, generateDefaultFormData]
  );

  const uploadProgressRef = useRef<UploadProgress[]>([]);

  useEffect(() => {
    uploadProgressRef.current = uploadProgress;
  }, [uploadProgress]);

  const handleCancelUploads = useCallback(async () => {
    pendingFilesQueueRef.current = [];

    if (uploadAbortControllerRef.current) {
      uploadAbortControllerRef.current.abort();
      uploadAbortControllerRef.current = null;
    }

    uploadSessionIdRef.current += 1;
    const successCount = uploadProgressRef.current.filter(
      (p) => p.status === "success"
    ).length;

    setUploadProgress((prev) =>
      prev.map((p) =>
        p.status === "pending" ||
        p.status === "uploading" ||
        p.status === "processing"
          ? { ...p, status: "cancelled" }
          : p
      )
    );
    setIsUploading(false);

    if (successCount > 0) {
      await Promise.all([refetchRef.current(), refetchTimelinesRef.current()]);
    }
  }, []);

  const handleSearch = useCallback(() => {
    const currentValue = searchInputValueRef.current;
    setAppliedSearchQuery(currentValue);
  }, []);

  const handleSearchChange = useCallback((value: string) => {
    searchInputValueRef.current = value;
    setSearchQuery(value);
  }, []);

  // When user clears the search (clear button or deletes all text), apply empty filter so streams show again
  useEffect(() => {
    if (searchQuery === "") {
      searchInputValueRef.current = "";
      setAppliedSearchQuery("");
    }
  }, [searchQuery]);

  const handleClearUploadProgress = useCallback(() => {
    setUploadProgress([]);
  }, []);

  const handleAddRtspClick = () => {
    setIsRtspModalOpen(true);
  };

  const handleRtspDialogClose = () => {
    setIsRtspModalOpen(false);
  };

  const handleRtspSuccess = useCallback(() => {
    refetchRef.current();
    refetchTimelinesRef.current();
  }, []);

  const handlePlayStream = useCallback(
    async (stream: StreamInfo) => {
      if (isRtspStream(stream)) {
        setLiveStream(stream);
        return;
      }

      const range = getLastTimelineForStream(stream.streamId);
      if (!range) return;
      const startTime = range.startTime;
      const endTime = range.endTime;

      setLoadingStreamId(stream.streamId);
      try {
        await openVideoModal({
          video_name: stream.name,
          start_time: startTime,
          end_time: endTime,
          sensor_id: stream.sensorId,
        });
      } catch {
        // openVideoModal handles errors internally; catch to prevent unhandled rejection
      } finally {
        setLoadingStreamId(null);
      }
    },
    [getLastTimelineForStream, openVideoModal]
  );

  const handleSelectionChange = useCallback(
    (streamId: string, selected: boolean) => {
      setSelectedStreams((prev) => {
        const next = new Set(prev);
        if (selected) {
          next.add(streamId);
        } else {
          next.delete(streamId);
        }
        return next;
      });
    },
    []
  );

  const handleSelectAll = useCallback(
    (selected: boolean) => {
      if (selected) {
        setSelectedStreams(new Set(filteredStreams.map((s) => s.streamId)));
      } else {
        setSelectedStreams(new Set());
      }
    },
    [filteredStreams]
  );

  // Resolve selected stream IDs back to full StreamInfo objects so the confirm
  // dialog can show the user exactly which items are about to be deleted.
  const selectedStreamInfos = useMemo(
    () => streams.filter((s) => selectedStreams.has(s.streamId)),
    [streams, selectedStreams]
  );
  const canResetSelected =
    selectedStreamInfos.length > 0 && selectedStreamInfos.every(isRtspStream);

  // Step 1 of delete: just open the confirmation dialog. The Toolbar's "Delete
  // Selected" button is wired to this so a single click never destroys data.
  const handleDeleteSelected = useCallback(() => {
    if (selectedStreams.size === 0 || isDeleting || isResetting) return;
    setShowDeleteConfirm(true);
  }, [selectedStreams.size, isDeleting, isResetting]);

  const handleResetSelected = useCallback(() => {
    if (!canResetSelected || isDeleting || isResetting) return;
    setClearResetRecordings(true);
    setShowResetConfirm(true);
  }, [canResetSelected, isDeleting, isResetting]);

  const handleCancelDelete = useCallback(() => {
    if (isDeleting) return;
    setShowDeleteConfirm(false);
  }, [isDeleting]);

  const handleCancelReset = useCallback(() => {
    if (isResetting) return;
    setShowResetConfirm(false);
  }, [isResetting]);

  // Step 2 of delete: invoked by the confirm button inside DeleteConfirmDialog.
  // This holds the actual destructive API calls that used to live in
  // handleDeleteSelected.
  const handleConfirmDelete = useCallback(async () => {
    if (selectedStreams.size === 0 || isDeleting || isResetting) return;

    const selectedStreamIds = Array.from(selectedStreams);

    const sensorToStreams = new Map<string, StreamInfo[]>();
    for (const streamId of selectedStreamIds) {
      const stream = streams.find((s) => s.streamId === streamId);
      if (stream) {
        const existing = sensorToStreams.get(stream.sensorId) || [];
        existing.push(stream);
        sensorToStreams.set(stream.sensorId, existing);
      }
    }

    const uniqueSensorIds = Array.from(sensorToStreams.keys());
    setIsDeleting(true);
    setOperationNotice(null);

    try {
      const deletePromises = uniqueSensorIds.map(async (sensorId) => {
        const sensorStreams = sensorToStreams.get(sensorId) || [];
        const firstStream = sensorStreams[0];

        // Check if this is an RTSP stream - must use agent API (by sensor name)
        if (firstStream && isRtspStream(firstStream)) {
          if (!agentApiUrl) {
            throw new Error(
              "Agent API URL not configured for RTSP stream deletion"
            );
          }
          await purgeLiveAlertFocus(sensorId);
          await purgeMonitoringRules(sensorId);
          await deleteRtspStream(agentApiUrl, firstStream.name);
          await purgeEvidenceClipCache(firstStream.streamId);
          await purgeVideoHistory(sensorId);
          return sensorId;
        }

        // Uploaded videos: use agent delete video API only (same as RTSP - no VST fallback)
        if (!agentApiUrl) {
          throw new Error("Agent API URL not configured for video deletion");
        }
        await purgeMonitoringRules(sensorId);
        await deleteVideo(agentApiUrl, sensorId);
        await purgeEvidenceClipCache(firstStream?.streamId ?? sensorId);
        await purgeVideoHistory(sensorId);
        return sensorId;
      });

      const results = await Promise.allSettled(deletePromises);
      results.forEach((r, idx) => {
        if (r.status === "rejected") {
          // eslint-disable-next-line no-console
          console.error(
            "[VideoManagement] delete failed for sensor",
            uniqueSensorIds[idx],
            r.reason
          );
        }
      });
      const failed = results.filter(
        (result) => result.status === "rejected"
      ).length;
      if (failed === 0) {
        setSelectedStreams(new Set());
        setOperationNotice({
          kind: "success",
          text: `${uniqueSensorIds.length} source${
            uniqueSensorIds.length === 1 ? "" : "s"
          } and all generated data were deleted.`,
        });
      } else {
        setOperationNotice({
          kind: "error",
          text: `${failed} source${
            failed === 1 ? "" : "s"
          } could not be fully deleted. No failed item was hidden.`,
        });
      }
      await Promise.all([refetch(), refetchTimelines()]);
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirm(false);
    }
  }, [
    selectedStreams,
    streams,
    isDeleting,
    isResetting,
    agentApiUrl,
    refetch,
    refetchTimelines,
  ]);

  const handleConfirmReset = useCallback(async () => {
    if (!canResetSelected || isResetting || !agentApiUrl) return;

    const liveSources = selectedStreamInfos.filter(isRtspStream);
    setIsResetting(true);
    setOperationNotice(null);
    try {
      const results = await Promise.allSettled(
        liveSources.map(async (stream) => {
          await purgeLiveAlertFocus(stream.sensorId);
          const result = await resetRtspStream(
            agentApiUrl,
            stream.streamId,
            stream.name,
            clearResetRecordings
          );
          await purgeEvidenceClipCache(stream.streamId);
          await purgeVideoHistory(stream.sensorId);
          return result;
        })
      );
      const successful = results.filter(
        (
          result
        ): result is PromiseFulfilledResult<
          Awaited<ReturnType<typeof resetRtspStream>>
        > => result.status === "fulfilled"
      );
      const failed = results.length - successful.length;
      const deletedDocuments = successful.reduce(
        (total, result) => total + result.value.deletedDocuments,
        0
      );
      if (failed === 0) {
        setSelectedStreams(new Set());
        setOperationNotice({
          kind: "success",
          text: `Cleared ${deletedDocuments.toLocaleString()} generated records${
            clearResetRecordings ? " and retained live clips" : ""
          }. Live analysis has resumed from a clean slate.`,
        });
      } else {
        setOperationNotice({
          kind: "error",
          text: `${failed} live source reset${
            failed === 1 ? "" : "s"
          } did not complete. The source selection was kept for retry.`,
        });
      }
      await Promise.all([refetch(), refetchTimelines()]);
    } finally {
      setIsResetting(false);
      setShowResetConfirm(false);
    }
  }, [
    agentApiUrl,
    canResetSelected,
    clearResetRecordings,
    isResetting,
    refetch,
    refetchTimelines,
    selectedStreamInfos,
  ]);

  const controlsComponent = useMemo(
    () => (
      <VideoManagementSidebarControls
        onFilesSelected={handleFilesSelected}
        enableVideoUpload={enableVideoUpload}
      />
    ),
    [handleFilesSelected, enableVideoUpload]
  );

  useEffect(() => {
    if (onControlsReady && renderControlsInLeftSidebar) {
      onControlsReady({ controlsComponent });
    }
  }, [onControlsReady, renderControlsInLeftSidebar, controlsComponent]);

  const renderMainContent = () => {
    if (isLoading) {
      return <LoadingState />;
    }

    if (error || streams.length === 0) {
      return (
        <EmptyState
          onFilesSelected={handleFilesSelected}
          enableVideoUpload={enableVideoUpload}
        />
      );
    }

    if (filteredStreams.length === 0) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-lg font-medium mb-2 text-gray-600 dark:text-gray-300">
              No streams found
            </p>
            <p className="text-sm text-gray-400 dark:text-gray-500">
              Try adjusting your search or filter criteria
            </p>
          </div>
        </div>
      );
    }

    return (
      <StreamsGrid
        streams={filteredStreams}
        selectedStreams={selectedStreams}
        vstApiUrl={vstApiUrl}
        onSelectionChange={handleSelectionChange}
        onSelectAll={handleSelectAll}
        showVideos={showVideos}
        showRtsps={showRtsps}
        getEndTimeForStream={getEndTimeForStream}
        onPlayStream={handlePlayStream}
        loadingStreamId={loadingStreamId}
        onAddChatQueryContext={addChatQueryContext}
      />
    );
  };

  return (
    <div className="vm-shell flex h-full min-h-0 min-w-0 max-w-full flex-1 flex-col bg-gray-50 text-gray-900 dark:bg-black dark:text-gray-100">
      {/* Hidden input for upload dialog add-more */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".mp4,.mkv"
        className="hidden"
        onChange={(e) => {
          const files = e.target.files;
          if (files && files.length > 0) {
            const newItems = Array.from(files).map((file) => ({
              id: generateFileId(),
              file,
              isExpanded: true,
              formData: generateDefaultFormData(),
            }));
            setSelectedFiles((prev) => [...prev, ...newItems]);
          }
          if (fileInputRef.current) fileInputRef.current.value = "";
        }}
      />

      <section className="vm-source-overview" aria-label="Source inventory">
        <div className="vm-source-overview__title">
          <span>Source inventory</span>
          <strong>{streams.length}</strong>
        </div>
        <div className="vm-source-overview__stat">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden
          >
            <path d="M15 10l4.55-2.28A1 1 0 0121 8.62v6.76a1 1 0 01-1.45.9L15 14" />
            <rect x="3" y="6" width="12" height="12" rx="2" />
          </svg>
          <div>
            <strong>{streams.filter(isRtspStream).length}</strong>
            <span>Live cameras</span>
          </div>
        </div>
        <div className="vm-source-overview__stat">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden
          >
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <path d="M7 5v14M17 5v14M3 9h4M17 9h4M3 15h4M17 15h4" />
          </svg>
          <div>
            <strong>
              {streams.filter((stream) => !isRtspStream(stream)).length}
            </strong>
            <span>Recorded videos</span>
          </div>
        </div>
        <button
          type="button"
          className="vm-refresh"
          onClick={() => void handleRefresh()}
          disabled={isRefreshing}
          aria-label={isRefreshing ? "Refreshing sources" : "Refresh sources"}
        >
          <svg
            className={isRefreshing ? "is-spinning" : ""}
            width="17"
            height="17"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden
          >
            <path d="M20 11a8 8 0 10-2.34 5.66" />
            <path d="M20 4v7h-7" />
          </svg>
          {isRefreshing ? "Refreshing" : "Refresh"}
        </button>
      </section>

      {operationNotice && (
        <div
          role={operationNotice.kind === "error" ? "alert" : "status"}
          className={`mx-4 mt-4 flex items-center justify-between gap-3 rounded-md border px-4 py-3 text-sm sm:mx-6 ${
            operationNotice.kind === "success"
              ? "border-cyan-700/50 bg-cyan-950/30 text-cyan-100"
              : "border-red-700/60 bg-red-950/30 text-red-100"
          }`}
        >
          <span>{operationNotice.text}</span>
          <button
            type="button"
            onClick={() => setOperationNotice(null)}
            aria-label="Dismiss status"
            className="text-current opacity-70 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      {/* Toolbar */}
      <Toolbar
        searchQuery={searchQuery}
        onSearchChange={handleSearchChange}
        onSearch={handleSearch}
        showVideos={showVideos}
        showRtsps={showRtsps}
        onShowVideosChange={setShowVideos}
        onShowRtspsChange={setShowRtsps}
        onFilesSelected={handleFilesSelected}
        onAddRtspClick={handleAddRtspClick}
        selectedCount={selectedStreams.size}
        onDeleteSelected={handleDeleteSelected}
        onResetSelected={handleResetSelected}
        canResetSelected={canResetSelected}
        isDeleting={isDeleting}
        isResetting={isResetting}
        enableAddRtspButton={enableAddRtspButton}
        enableVideoUpload={enableVideoUpload}
        hasVideoStreams={hasVideoStreams}
        hasRtspStreams={hasRtspStreams}
      />

      {/* Main pane: scrollable grid + upload/progress overlays confined to this tab (not full viewport) */}
      <div className="flex flex-1 min-h-0 flex-col relative">
        <div className="flex flex-1 min-h-0 flex-col overflow-auto">
          {renderMainContent()}
        </div>

        <AgentUploadDialog
          agentApiUrl={agentApiUrl}
          overlay="contained"
          open={showUploadDialog}
          files={selectedFiles}
          configTemplate={configTemplate}
          onAddMore={() => fileInputRef.current?.click()}
          onFilesDropped={(droppedFiles: File[]) => {
            const newItems = droppedFiles.map((file) => ({
              id: generateFileId(),
              file,
              isExpanded: true,
              formData: generateDefaultFormData(),
            }));
            setSelectedFiles((prev) => [...prev, ...newItems]);
          }}
          onClose={() => {
            setShowUploadDialog(false);
            setSelectedFiles([]);
          }}
          onConfirmUpload={() => {
            if (selectedFiles.length === 0) return;

            const entries = selectedFiles.map((f) => ({
              id: f.id,
              file: f.file,
              formData: f.formData,
            }));

            if (isUploadingRef.current) {
              pendingFilesQueueRef.current.push(...entries);
              const queuedProgress: UploadProgress[] = entries.map((entry) => ({
                id: entry.id,
                fileName: entry.file.name,
                progress: 0,
                status: "pending" as const,
              }));
              setUploadProgress((prev) => [...prev, ...queuedProgress]);
            } else {
              const initialProgress: UploadProgress[] = entries.map(
                (entry) => ({
                  id: entry.id,
                  fileName: entry.file.name,
                  progress: 0,
                  status: "pending" as const,
                })
              );
              setUploadProgress(initialProgress);
              processUploadQueue(entries);
            }

            setShowUploadDialog(false);
            setSelectedFiles([]);
          }}
          onToggleExpand={(id: string) =>
            setSelectedFiles((prev) =>
              prev.map((f) =>
                f.id === id ? { ...f, isExpanded: !f.isExpanded } : f
              )
            )
          }
          onRemoveFile={(id: string) =>
            setSelectedFiles((prev) => prev.filter((f) => f.id !== id))
          }
          onFieldChange={(fileId: string, fieldName: string, value: any) =>
            setSelectedFiles((prev) =>
              prev.map((f) =>
                f.id === fileId
                  ? { ...f, formData: { ...f.formData, [fieldName]: value } }
                  : f
              )
            )
          }
        />

        <UploadProgressPanel
          uploads={uploadProgress}
          onClose={handleClearUploadProgress}
          onCancel={handleCancelUploads}
        />

        <AddRtspDialog
          overlay="viewport"
          isOpen={isRtspModalOpen}
          agentApiUrl={agentApiUrl}
          onClose={handleRtspDialogClose}
          onSuccess={handleRtspSuccess}
        />

        <DeleteConfirmDialog
          overlay="viewport"
          isOpen={showDeleteConfirm}
          streams={selectedStreamInfos}
          isDeleting={isDeleting}
          onCancel={handleCancelDelete}
          onConfirm={handleConfirmDelete}
        />
        <DeleteConfirmDialog
          overlay="viewport"
          mode="reset"
          isOpen={showResetConfirm}
          streams={selectedStreamInfos}
          isDeleting={isResetting}
          clearRecordings={clearResetRecordings}
          onClearRecordingsChange={setClearResetRecordings}
          onCancel={handleCancelReset}
          onConfirm={handleConfirmReset}
        />
      </div>

      {/* Video Playback Modal */}
      <VideoModal
        isOpen={videoModal.isOpen}
        videoUrl={videoModal.videoUrl}
        title={videoModal.title}
        onClose={closeVideoModal}
      />
      <LiveStreamModal
        isOpen={liveStream !== null}
        streamId={liveStream?.streamId ?? ""}
        title={liveStream?.name ?? ""}
        vstApiUrl={vstApiUrl}
        onClose={() => setLiveStream(null)}
      />
    </div>
  );
};
