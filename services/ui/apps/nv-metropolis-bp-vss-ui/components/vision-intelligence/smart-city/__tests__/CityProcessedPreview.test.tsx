// SPDX-License-Identifier: MIT
import React from 'react';
import { render } from '@testing-library/react';
import { CityProcessedPreview } from '../CityProcessedPreview';
import type { PreviewPair } from '../useProcessedPreview';
function pair(sequence: string, width = 1000, height = 1000): PreviewPair {
  return { frame: { sequence, image: { width, height } } as any, bitmap: { close: jest.fn() } as unknown as ImageBitmap, receivedAtMs: 1, configurationKey: 'site' };
}
describe('analyzed preview canvas ownership', () => {
  it('reuses a same-size backing store while drawing each exact pair before presentation', () => {
    const draw = jest.fn(); const present = jest.fn(); const failure = jest.fn();
    const getContext = jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((kind: string) => kind === '2d' ? { drawImage: draw } as any : null);
    const width = jest.spyOn(HTMLCanvasElement.prototype, 'width', 'set'); const height = jest.spyOn(HTMLCanvasElement.prototype, 'height', 'set');
    const first = pair('1'); const next = pair('2'); const resized = pair('3', 1920, 1080);
    const { rerender, unmount } = render(<CityProcessedPreview pair={first} onPresented={present} onFailure={failure} />);
    expect(width).toHaveBeenCalledTimes(1); expect(height).toHaveBeenCalledTimes(1);
    rerender(<CityProcessedPreview pair={next} onPresented={present} onFailure={failure} />);
    expect(width).toHaveBeenCalledTimes(1); expect(height).toHaveBeenCalledTimes(1); expect(draw).toHaveBeenLastCalledWith(next.bitmap, 0, 0, 1000, 1000);
    expect(draw.mock.invocationCallOrder[1]).toBeLessThan(present.mock.invocationCallOrder[1]);
    rerender(<CityProcessedPreview pair={resized} onPresented={present} onFailure={failure} />);
    expect(width).toHaveBeenCalledTimes(2); expect(height).toHaveBeenCalledTimes(2); expect(draw).toHaveBeenLastCalledWith(resized.bitmap, 0, 0, 1920, 1080);
    expect(present).toHaveBeenLastCalledWith(resized.frame); expect(failure).not.toHaveBeenCalled(); unmount();
    expect(getContext).toHaveBeenCalledWith('2d', { alpha: false });
    // The hook owns decoded pixels. Canvas drawing must not prematurely close them.
    for (const value of [first, next, resized]) expect(value.bitmap.close).not.toHaveBeenCalled();
  });
  it('transfers each exact bitmap once, including callback changes and hide/show, before reporting its frame', () => {
    const transfer = jest.fn(); const present = jest.fn(); const failure = jest.fn();
    jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((kind: string) => kind === 'bitmaprenderer' ? { transferFromImageBitmap: transfer } as any : null);
    const first = pair('1'); const next = pair('2');
    const { rerender, container } = render(<CityProcessedPreview pair={first} onPresented={present} onFailure={failure} />);
    expect(transfer).toHaveBeenCalledWith(first.bitmap);
    expect(first.transferredTo).toBe(container.querySelector('canvas'));
    expect(container.querySelector('canvas')).toHaveAttribute('width', '1000');
    expect(container.querySelector('canvas')).toHaveAttribute('height', '1000');
    expect(transfer.mock.invocationCallOrder[0]).toBeLessThan(present.mock.invocationCallOrder[0]);
    rerender(<CityProcessedPreview pair={first} onPresented={present} onFailure={() => failure()} />);
    rerender(<CityProcessedPreview pair={first} onPresented={present} onFailure={failure} presentable={false} />);
    rerender(<CityProcessedPreview pair={first} onPresented={present} onFailure={failure} />);
    expect(transfer).toHaveBeenCalledTimes(1);
    rerender(<CityProcessedPreview pair={next} onPresented={present} onFailure={failure} />);
    expect(transfer).toHaveBeenCalledTimes(2); expect(transfer).toHaveBeenLastCalledWith(next.bitmap);
    expect(present).toHaveBeenLastCalledWith(next.frame); expect(failure).not.toHaveBeenCalled();
    expect(container.querySelector('canvas')).toHaveAttribute('data-preview-renderer', 'bitmaprenderer');
    expect(first.bitmap.close).not.toHaveBeenCalled();
  });
  it('does not try to reuse a consumed bitmap after its canvas is replaced', () => {
    const transfer = jest.fn(); const present = jest.fn(); const failure = jest.fn();
    jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ transferFromImageBitmap: transfer } as any);
    const value = pair('1');
    const first = render(<CityProcessedPreview pair={value} onPresented={present} onFailure={failure} />);
    first.unmount(); present.mockClear();
    render(<CityProcessedPreview pair={value} onPresented={present} onFailure={failure} />);
    expect(transfer).toHaveBeenCalledTimes(1); expect(present).not.toHaveBeenCalled(); expect(failure).toHaveBeenCalledTimes(1);
  });
  it('does not report presentation when pixels cannot be drawn', () => {
    const failure = jest.fn(); const present = jest.fn(); jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: () => { throw new Error('draw failed'); } } as any);
    render(<CityProcessedPreview pair={pair('1')} onPresented={present} onFailure={failure} />);
    expect(failure).toHaveBeenCalledTimes(1); expect(present).not.toHaveBeenCalled();
  });
  it('rejects a skipped pair released before canvas commit without reading its pixels', () => {
    const failure = jest.fn(); const present = jest.fn(); const draw = jest.fn(); jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: draw } as any);
    render(<CityProcessedPreview pair={{ ...pair('skipped'), released: true }} onPresented={present} onFailure={failure} />);
    expect(draw).not.toHaveBeenCalled(); expect(failure).toHaveBeenCalledTimes(1); expect(present).not.toHaveBeenCalled();
  });
});
