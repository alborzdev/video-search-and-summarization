// SPDX-License-Identifier: MIT
import { fetchPictureWithQueue } from '../../lib-src/utils';

it('uses the image proxy for same-origin camera pictures and rejects placeholders', async () => {
  global.fetch = jest.fn(async () => ({
    ok: true, headers: { get: () => '503' }, blob: jest.fn(),
  })) as jest.Mock;
  await expect(fetchPictureWithQueue('/vst/api/v1/live/stream/camera/picture')).rejects.toThrow('preview is unavailable');
  expect(global.fetch).toHaveBeenCalledWith('/api/vision/vst-image?path=%2Fvst%2Fapi%2Fv1%2Flive%2Fstream%2Fcamera%2Fpicture');
});

it('returns real image bytes from the proxy', async () => {
  const picture = new Blob(['frame'], { type: 'image/jpeg' });
  global.fetch = jest.fn(async () => ({ ok: true, headers: { get: () => null }, blob: async () => picture })) as jest.Mock;
  await expect(fetchPictureWithQueue('/vst/api/v1/storage/stream/camera/picture?startTime=2025-01-01')).resolves.toBe(picture);
});
