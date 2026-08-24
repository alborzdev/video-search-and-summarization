// SPDX-License-Identifier: MIT

export type PrimarySection =
  | 'capabilities'
  | 'events'
  | 'explore'
  | 'home'
  | 'live'
  | 'monitoring'
  | 'system';

export type OperationsView = 'focused' | 'grid' | 'activity' | 'insights';

export interface VisionStreamMetadata {
  bitrate?: string;
  codec?: string;
  framerate?: string;
  govlength?: string;
  resolution?: string;
}

export interface VisionStream {
  isMain: boolean;
  metadata: VisionStreamMetadata;
  name: string;
  sensorId: string;
  streamId: string;
  type?: string;
  url: string;
  vodUrl: string;
}

export type VisionStreamsApiResponse = Array<
  Record<string, Array<Omit<VisionStream, 'sensorId'>>>
>;

export interface StreamTimeline {
  startTime: string;
  endTime: string;
}
