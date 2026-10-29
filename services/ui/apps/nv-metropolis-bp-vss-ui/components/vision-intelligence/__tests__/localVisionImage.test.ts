// SPDX-License-Identifier: MIT
import { prepareDisplayedImage } from '../localVisionImage';
beforeEach(() => {
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ fillStyle: '', fillRect: jest.fn(), drawImage: jest.fn() } as unknown as CanvasRenderingContext2D);
  jest.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/jpeg;base64,YWJj');
});
it('fits a displayed large inspection image without changing its aspect ratio or illustration label', () => {
  const img = document.createElement('img'); Object.defineProperties(img, { naturalWidth: { value: 1672 }, naturalHeight: { value: 941 } });
  const prepared = prepareDisplayedImage(img, 'Illustration · Closer view');
  expect(prepared.provenance).toBe('Illustration · Closer view · 1024 × 576 prepared image');
  expect(prepared.base64).toBe('YWJj'); expect(HTMLCanvasElement.prototype.toDataURL).toHaveBeenCalledWith('image/jpeg', .92);
});
it('rejects oversized decoded images before drawing them into a canvas', () => {
  const img = document.createElement('img'); Object.defineProperties(img, { naturalWidth: { value: 8000 }, naturalHeight: { value: 6000 } });
  expect(() => prepareDisplayedImage(img, 'input')).toThrow('16 million pixels'); expect(HTMLCanvasElement.prototype.getContext).not.toHaveBeenCalled();
});
it('rejects a media element without a decoded frame', () => { expect(() => prepareDisplayedImage(document.createElement('video'), 'camera')).toThrow('has not loaded'); });
