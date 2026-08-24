// SPDX-License-Identifier: MIT
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { VideoManagementComponent } from '../../lib-src/VideoManagementComponent';
import { videoStream, rtspStream } from '../helpers/streamFixtures';

const mockOpenVideoModal = jest.fn(() => Promise.resolve());
const mockCloseVideoModal = jest.fn();

jest.mock('@nemo-agent-toolkit/ui', () => ({
  UploadFilesDialog: () => null,
  useChatVideoUploadCompleteSubscription: jest.fn(),
  VideoModal: ({ isOpen, title }: { isOpen: boolean; title: string }) =>
    isOpen ? <div data-testid="video-modal">{title}</div> : null,
  useVideoModal: () => ({
    videoModal: { isOpen: false, videoUrl: '', title: '' },
    openVideoModal: mockOpenVideoModal,
    closeVideoModal: mockCloseVideoModal,
    openVideoModalFromUrl: jest.fn(),
    openVideoModalFromAlert: jest.fn(),
    loadingAlertId: null,
  }),
  copyToClipboard: jest.fn(),
}));

jest.mock('../../lib-src/chunkedUpload', () => ({
  chunkedUpload: jest.fn().mockResolvedValue({ sensorId: 'mock-sensor' }),
  notifyUploadComplete: jest.fn().mockResolvedValue(undefined),
}));

const mockTimelines = new Map([
  ['vid-1', {
    sizeInMegabytes: 100,
    state: 'active',
    timelines: [
      { startTime: '2025-01-01T00:00:00Z', endTime: '2025-01-01T00:03:30Z', sizeInMegabytes: 50 },
      { startTime: '2025-01-01T01:00:00Z', endTime: '2025-01-01T01:03:30Z', sizeInMegabytes: 50 },
    ],
  }],
  ['rtsp-1', {
    sizeInMegabytes: 200,
    state: 'active',
    timelines: [
      { startTime: '2025-01-01T00:00:00Z', endTime: '2025-01-01T12:00:00Z', sizeInMegabytes: 200 },
    ],
  }],
]);

jest.mock('../../lib-src/hooks', () => ({
  useStreams: () => ({
    streams: [videoStream, rtspStream],
    isLoading: false,
    error: null,
    refetch: jest.fn(),
  }),
  useStorageTimelines: () => ({
    timelines: mockTimelines,
    isLoading: false,
    error: null,
    refetch: jest.fn(),
    getEndTimeForStream: jest.fn(() => '2025-01-01T01:03:25Z'),
    getTimelineRangeForStream: jest.fn((streamId: string) => {
      if (streamId === 'vid-1') return { startTime: '2025-01-01T00:00:00Z', endTime: '2025-01-01T01:03:30Z' };
      return null;
    }),
    getLastTimelineForStream: jest.fn((streamId: string) => {
      const info = mockTimelines.get(streamId);
      if (!info?.timelines?.length) return null;
      const last = info.timelines[info.timelines.length - 1];
      return { startTime: last.startTime, endTime: last.endTime };
    }),
  }),
}));

jest.mock('../../lib-src/utils', () => {
  const actual = jest.requireActual('../../lib-src/utils');
  return {
    ...actual,
    fetchPictureWithQueue: jest.fn(() => Promise.reject(new Error('no thumbnail'))),
  };
});
jest.mock('../../lib-src/api', () => ({
  createApiEndpoints: () => ({
    LIVE_PICTURE: jest.fn(),
    REPLAY_PICTURE: jest.fn(),
  }),
}));

jest.mock('@tabler/icons-react', () => ({
  IconCheck: () => <span data-testid="icon-check" />,
  IconCopy: () => <span data-testid="icon-copy" />,
}));

jest.mock('../../lib-src/components/LiveStreamModal', () => ({
  LiveStreamModal: ({ isOpen, title }: { isOpen: boolean; title: string }) =>
    isOpen ? <div data-testid="live-stream-modal">{title}</div> : null,
}));

const defaultProps = {
  videoManagementData: {
    systemStatus: 'ok',
    vstApiUrl: 'https://vst.example.com/vst',
    agentApiUrl: 'https://agent.example.com',
  },
};

function renderComponent(props: Partial<Parameters<typeof VideoManagementComponent>[0]> = {}) {
  return render(<VideoManagementComponent {...defaultProps} {...props} />);
}

describe('VideoManagementComponent — video playback', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders play buttons for all streams', async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: `Play ${videoStream.name}` })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: `Play ${rtspStream.name}` })).toBeInTheDocument();
    });
  });

  it('calls openVideoModal with full last timeline segment for uploaded video', async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: `Play ${videoStream.name}` })).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: `Play ${videoStream.name}` }));
    });

    expect(mockOpenVideoModal).toHaveBeenCalledTimes(1);
    const callArgs = mockOpenVideoModal.mock.calls[0][0];
    expect(callArgs.video_name).toBe('test_video');
    expect(callArgs.sensor_id).toBe('sensor-vid');
    expect(callArgs.start_time).toBe('2025-01-01T01:00:00Z');
    expect(callArgs.end_time).toBe('2025-01-01T01:03:30Z');
  });

  it('opens the live WebRTC player for an RTSP stream', async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: `Play ${rtspStream.name}` })).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: `Play ${rtspStream.name}` }));
    });

    expect(mockOpenVideoModal).not.toHaveBeenCalled();
    expect(screen.getByTestId('live-stream-modal')).toHaveTextContent('Camera 1');
  });

  it('renders VideoModal component', () => {
    renderComponent();

    expect(screen.queryByTestId('video-modal')).not.toBeInTheDocument();
  });

  it('clears selected live analytics and retained clips without removing the source', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: 'OK', json: async () => ({ deleted: 0 }) })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({
          status: 'success',
          message: 'reset',
          sensorId: rtspStream.streamId,
          name: rtspStream.name,
          deletedDocuments: 123,
          deletedByCategory: { embeddings: 20, detections: 103 },
          recordingsCleared: true,
          analysisResumed: true,
          resetAt: '2026-08-17T17:00:00Z',
        }),
      })
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: 'OK', json: async () => ({ removedFiles: 2 }) })
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: 'OK', json: async () => ({ deleted: true }) });
    global.fetch = fetchMock;
    renderComponent();

    fireEvent.click(screen.getByRole('checkbox', { name: `Select ${rtspStream.name}` }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear live data (1)' }));
    expect(screen.getByText('CLEAR GENERATED LIVE DATA')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Clear and resume' }));
    });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Cleared 123 generated records and retained live clips');
    });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/vision/live-alert-rules?sourceId=sensor-rtsp');
    expect(fetchMock.mock.calls[1][0]).toBe('https://agent.example.com/rtsp-streams/rtsp-1/reset');
    expect(fetchMock.mock.calls[2][0]).toBe('/api/vision/evidence-cache?sensorId=rtsp-1');
    expect(fetchMock.mock.calls[3][0]).toBe('/api/vision/video-history?sourceId=sensor-rtsp');
  });

  it('does not offer live reset for a recorded-video selection', () => {
    renderComponent();

    fireEvent.click(screen.getByRole('checkbox', { name: `Select ${videoStream.name}` }));
    expect(screen.getByRole('button', { name: 'Clear live data (1)' })).toBeDisabled();
  });
});
