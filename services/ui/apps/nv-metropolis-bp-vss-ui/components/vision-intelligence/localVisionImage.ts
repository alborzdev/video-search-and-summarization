// SPDX-License-Identifier: MIT
export type PreparedVisionImage = { url: string; base64: string; name: string; provenance?: string };
const MAX_PIXELS = 16_000_000;
export function prepareDisplayedImage(element: HTMLImageElement | HTMLVideoElement | HTMLCanvasElement, name: string): PreparedVisionImage {
  const width = element instanceof HTMLVideoElement ? element.videoWidth : element instanceof HTMLImageElement ? element.naturalWidth : element.width;
  const height = element instanceof HTMLVideoElement ? element.videoHeight : element instanceof HTMLImageElement ? element.naturalHeight : element.height;
  if (!width || !height) throw new Error('The displayed image has not loaded yet.');
  if (width * height > MAX_PIXELS) throw new Error('Choose an image with no more than 16 million pixels.');
  const scale = Math.min(1, 1024 / Math.max(width, height)); const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext('2d'); if (!context) throw new Error('Image preparation is unavailable in this browser.');
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(element, 0, 0, canvas.width, canvas.height); const url = canvas.toDataURL('image/jpeg', .92);
  const base64 = url.slice(url.indexOf(',') + 1);
  if (!url.startsWith('data:image/jpeg;base64,') || base64.length > Math.ceil(2 * 1024 * 1024 / 3) * 4) throw new Error('The prepared image is too large. Choose a smaller image.');
  const origin = element instanceof HTMLVideoElement ? `Displayed video frame at ${element.currentTime.toFixed(2)} s` : name;
  return { url, base64, name, provenance: `${origin} · ${canvas.width} × ${canvas.height} prepared image` };
}
export async function prepareUploadedImage(file: File): Promise<PreparedVisionImage> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) throw new Error('Choose a PNG, JPEG or WebP image up to 10 MiB.');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('This image could not be read.')); image.src = url; });
    return prepareDisplayedImage(image, file.name);
  } finally { URL.revokeObjectURL(url); }
}
