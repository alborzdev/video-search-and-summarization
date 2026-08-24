// SPDX-License-Identifier: MIT

import { fireEvent, render, screen } from '@testing-library/react';
import React, { useState } from 'react';

import type { MonitoringGeometry } from '../monitoringRules';
import { MonitoringRegionEditor } from '../MonitoringRegionEditor';
import type { VisionStream } from '../types';

jest.mock('../VisionStreamCanvas', () => ({
  VisionStreamCanvas: () => <div data-testid="stream-canvas" />,
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
  it('creates, moves, and removes polygon points without pointer input', () => {
    render(<RegionHarness />);

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
