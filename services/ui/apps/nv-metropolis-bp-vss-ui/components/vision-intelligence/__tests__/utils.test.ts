// SPDX-License-Identifier: MIT
import type { VisionStreamsApiResponse } from '../types';
import {
  createLiveWebSocketUrl,
  isLiveStream,
  parseVisionStreams,
  proxyVstPictureUrl,
  sourceKind,
  streamDisplayName,
} from '../utils';

describe('vision intelligence stream utilities', () => {
  const response: VisionStreamsApiResponse = [
    {
      'sensor-a': [
        {
          isMain: true,
          metadata: { codec: 'h264', resolution: '1920x1080' },
          name: 'sample-sim-traffic',
          streamId: 'stream-a',
          type: 'FileDownload',
          url: '/videos/traffic.mp4',
          vodUrl: '/videos/traffic.mp4',
        },
      ],
    },
    {
      'sensor-b': [
        {
          isMain: true,
          metadata: { codec: 'h264' },
          name: 'loading_dock_rtsp',
          streamId: 'stream-b',
          url: 'rtsp://camera/live',
          vodUrl: '',
        },
      ],
    },
  ];

  it('flattens sensor-grouped VIOS streams without losing sensor identity', () => {
    expect(parseVisionStreams(response)).toEqual([
      expect.objectContaining({ sensorId: 'sensor-a', streamId: 'stream-a' }),
      expect.objectContaining({ sensorId: 'sensor-b', streamId: 'stream-b' }),
    ]);
  });

  it('distinguishes RTSP live sources from file-backed replays', () => {
    const [replay, live] = parseVisionStreams(response);
    expect(isLiveStream(replay)).toBe(false);
    expect(sourceKind(replay)).toBe('Replay');
    expect(isLiveStream(live)).toBe(true);
    expect(sourceKind(live)).toBe('Live');
  });

  it('creates readable, scenario-neutral display names', () => {
    expect(streamDisplayName('sample-sim-traffic')).toBe('Traffic — Main Intersection');
    expect(streamDisplayName('sample-sim-jaywalking')).toBe('Traffic — Pedestrian Crossing');
    expect(streamDisplayName('nvidia-warehouse-loading-dock-camera-01-4min')).toBe('Warehouse — Loading Dock');
    expect(streamDisplayName('pit-POV.mp4')).toBe('Motorsport — Driver POV');
  });

  it('creates the VIOS WebSocket signaling endpoint from the configured API URL', () => {
    expect(createLiveWebSocketUrl('https://thor.test/vst/api', 'stream-a', 'peer-a')).toBe(
      'wss://thor.test/vst/api/v1/live/ws?connectionId=peer-a&streamId=stream-a'
    );
  });

  it('keeps same-origin VST pictures behind the stable image proxy', () => {
    expect(
      proxyVstPictureUrl(
        `${window.location.origin}/vst/api/v1/live/stream/camera-1/picture?width=1280`
      )
    ).toBe(
      '/api/vision/vst-image?path=%2Fvst%2Fapi%2Fv1%2Flive%2Fstream%2Fcamera-1%2Fpicture%3Fwidth%3D1280'
    );
  });
});
