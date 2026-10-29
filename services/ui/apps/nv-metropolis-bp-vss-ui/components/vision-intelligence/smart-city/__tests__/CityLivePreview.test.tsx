// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CityLivePreview } from '../CityLivePreview';
import { useVisionStreams } from '../../useVisionStreams';
jest.mock('../../useVisionStreams', () => ({ useVisionStreams: jest.fn() }));
jest.mock('../../VisionStreamCanvas', () => ({ VisionStreamCanvas: () => <div>Live video</div> }));
const props = { source: { id: 'camera', name: 'Camera', width: 1280, height: 720 }, onFrame: jest.fn(), onStatus: jest.fn() };
it('distinguishes a failed camera service from a successful empty inventory and offers retry', () => {
  const refresh = jest.fn();
  (useVisionStreams as jest.Mock).mockReturnValue({ streams: [], error: 'Failed to fetch', isLoading: false, refresh });
  const { rerender } = render(<CityLivePreview {...props} />);
  expect(screen.getByText('Camera service unavailable')).toBeInTheDocument();
  expect(screen.queryByText('Camera not found in VSS')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh cameras' })); expect(refresh).toHaveBeenCalledTimes(1);
  (useVisionStreams as jest.Mock).mockReturnValue({ streams: [], error: null, isLoading: false, refresh });
  rerender(<CityLivePreview {...props} />);
  expect(screen.getByText('Camera not found in VSS')).toBeInTheDocument();
});
