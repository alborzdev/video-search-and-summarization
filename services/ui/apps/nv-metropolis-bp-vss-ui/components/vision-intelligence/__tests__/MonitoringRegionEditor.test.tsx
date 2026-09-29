// SPDX-License-Identifier: MIT

import { act, fireEvent, render, screen } from '@testing-library/react';
import React, { useState } from 'react';

import type { MonitoringGeometry } from '../monitoringRules';
import { MonitoringRegionEditor } from '../MonitoringRegionEditor';
import type { VisionStream } from '../types';

jest.mock('../VisionStreamCanvas', () => ({
  VisionStreamCanvas: ({ onPreviewAvailable }: { onPreviewAvailable?: (available: boolean) => void }) => <div data-testid="stream-canvas">
    <button onClick={() => onPreviewAvailable?.(true)}>Load camera frame</button>
    <button onClick={() => onPreviewAvailable?.(false)}>Lose camera frame</button>
  </div>,
}));

const stream: VisionStream = {
  isMain: true,
  metadata: {},
  name: 'Keyboard test camera',
  sensorId: 'camera-1',
  streamId: 'camera-1',
  type: 'Camera',
  url: 'rtsp://camera.local/live',
  vodUrl: 'rtsp://camera.local/live',
};

function RegionHarness() {
  const [geometry, setGeometry] = useState<MonitoringGeometry>({
    frameHeight: 1080,
    frameWidth: 1920,
    kind: 'polygon',
    points: [],
  });

  return (
    <>
      <output data-testid="geometry">{JSON.stringify(geometry)}</output>
      <MonitoringRegionEditor geometry={geometry} onChange={setGeometry} stream={stream} />
    </>
  );
}

function geometry(): MonitoringGeometry {
  return JSON.parse(screen.getByTestId('geometry').textContent ?? '{}') as MonitoringGeometry;
}

describe('MonitoringRegionEditor keyboard workflow', () => {
  it('offers recovery after a preview timeout and enables editing when a frame arrives', () => {
    jest.useFakeTimers();
    const view = render(<RegionHarness />);
    try {
      act(() => { jest.advanceTimersByTime(8_000); });
      expect(screen.getByRole('status', { name: 'Camera preview status' })).toHaveTextContent('No camera frame available');
      fireEvent.click(screen.getByRole('button', { name: 'Retry preview' }));
      expect(screen.getByRole('status', { name: 'Camera preview status' })).toHaveTextContent('Loading camera preview');
      fireEvent.click(screen.getByRole('button', { name: 'Load camera frame' }));
      expect(screen.queryByRole('status', { name: 'Camera preview status' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Add point' })).toBeEnabled();
    } finally { view.unmount(); jest.useRealTimers(); }
  });
  it('prevents drawing a region without a visible source frame', () => {
    render(<RegionHarness />);
    expect(screen.getByRole('button', { name: 'Add point' })).toBeDisabled();
    expect(screen.queryByLabelText('Monitoring area editor')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load camera frame' }));
    expect(screen.getByRole('button', { name: 'Add point' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Lose camera frame' }));
    expect(screen.getByRole('button', { name: 'Add point' })).toBeDisabled();
  });
  it('creates, moves, and removes polygon points without pointer input', () => {
    render(<RegionHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Load camera frame' }));

    const addPoint = screen.getByRole('button', { name: 'Add point' });
    fireEvent.click(addPoint);
    fireEvent.click(addPoint);
    fireEvent.click(addPoint);

    expect(screen.getByText(/Area ready/i)).toBeInTheDocument();
    expect(screen.getAllByRole('group', { name: /^Region point/ })).toHaveLength(3);
    expect(geometry().points[0]).toEqual({ x: 0.25, y: 0.25 });

    fireEvent.keyDown(screen.getAllByRole('group', { name: /^Region point/ })[0], {
      key: 'ArrowRight',
    });
    expect(geometry().points[0]).toEqual({ x: 0.26, y: 0.25 });

    fireEvent.keyDown(screen.getAllByRole('group', { name: /^Region point/ })[0], {
      key: 'ArrowDown',
      shiftKey: true,
    });
    expect(geometry().points[0]).toEqual({ x: 0.26, y: 0.3 });

    fireEvent.keyDown(screen.getAllByRole('group', { name: /^Region point/ })[0], {
      key: 'Delete',
    });
    expect(screen.getAllByRole('group', { name: /^Region point/ })).toHaveLength(2);
    expect(geometry().points).toHaveLength(2);
  });
});
