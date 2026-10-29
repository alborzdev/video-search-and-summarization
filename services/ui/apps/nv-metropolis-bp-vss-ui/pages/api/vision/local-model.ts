// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';

export const config = { api: { bodyParser: { sizeLimit: '3mb' }, responseLimit: '12mb' } };
const IMAGE_LIMIT = 2 * 1024 * 1024;
const RESPONSE_LIMIT = 12 * 1024 * 1024;
const TASKS = ['segment', 'detect', 'point', 'describe'];
const INPUT_FIELDS = new Set(['task', 'image_base64', 'object', 'grounded_by', 'presence']);
// Exclude runtime receipts, local filenames, configuration and upstream errors.
const OUTPUT_FIELDS = new Set(['status', 'ready', 'busy', 'state', 'model', 'segmenter_name', 'operation', 'task', 'object', 'image', 'width', 'height', 'rgb_sha256', 'timings_ms', 'preprocess', 'moondream_load', 'describe', 'presence', 'detect', 'point', 'segmenter_load', 'image_encode', 'mask_decode', 'total', 'queue', 'serialization', 'description', 'objects', 'points', 'box', 'grounding', 'x', 'y', 'x_min', 'x_max', 'y_min', 'y_max', 'source_index', 'mask_png_base64', 'mask_overlay_png_base64', 'mask_metadata', 'score', 'predicted_iou', 'selected_candidate', 'candidate_scores', 'area', 'area_pixels', 'grounded_by', 'presence_mode', 'decision', 'segmenter_used', 'valid_grounding_count', 'grounding_generation_limit', 'grounding_returned_at_limit', 'truncated', 'request_id', 'max_objects', 'max_image_side', 'warm', 'loading', 'inference_ms', 'total_ms', 'model_load_ms', 'input_image', 'output_image', 'mask_count', 'masks', 'raw_grounding', 'model_identity', 'moondream', 'segmenter', 'runtime', 'device', 'gb10_compat', 'format', 'encoded_bytes', 'resized', 'max_dimension', 'source_width', 'source_height', 'inference_width', 'inference_height', 'exif_transposed', 'service_timings_ms', 'image_prepare', 'process_phase', 'accuracy_evaluated', 'mask_encoding', 'score_kind', 'candidate_count', 'mask_area', 'mask_fraction']);
export function publicLocalVisionPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(publicLocalVisionPayload);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([key]) => OUTPUT_FIELDS.has(key)).map(([key, item]) => [key, publicLocalVisionPayload(item)]));
  return value;
}
export function validateLocalVisionInput(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const body = value as Record<string, unknown>;
  if (Object.keys(body).some(key => !INPUT_FIELDS.has(key)) || typeof body.task !== 'string' || !TASKS.includes(body.task)) return null;
  const image = body.image_base64;
  if (typeof image !== 'string' || !image || image.length > Math.ceil(IMAGE_LIMIT / 3) * 4 || image.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(image)) return null;
  const bytes = Buffer.from(image, 'base64');
  if (bytes.length > IMAGE_LIMIT || bytes.toString('base64') !== image) return null;
  const png = bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  const jpeg = bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
  const webp = bytes.subarray(0, 4).toString() === 'RIFF' && bytes.subarray(8, 12).toString() === 'WEBP';
  if (!png && !jpeg && !webp) return null;
  const object = typeof body.object === 'string' ? body.object.trim() : '';
  if ((body.task !== 'describe' && !object) || object.length > 200 || /[\x00-\x1f]/.test(object)) return null;
  if (body.grounded_by !== undefined && (typeof body.grounded_by !== 'string' || !['point', 'detect'].includes(body.grounded_by))) return null;
  if (body.presence !== undefined && (typeof body.presence !== 'string' || !['off', 'query'].includes(body.presence))) return null;
  return { task: body.task, image_base64: image, ...(body.task === 'describe' ? {} : { object }), ...(body.task === 'segment' ? { grounded_by: body.grounded_by ?? 'point', presence: body.presence ?? 'off' } : {}) };
}
async function boundedJson(response: Response): Promise<unknown> {
  if (Number(response.headers.get('content-length') ?? 0) > RESPONSE_LIMIT) throw new Error('Response too large');
  if (!response.body) throw new Error('Empty response');
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength; if (size > RESPONSE_LIMIT) { await reader.cancel(); throw new Error('Response too large'); }
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } finally { reader.releaseLock(); }
}
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET' && req.method !== 'POST') { res.setHeader('Allow', 'GET, POST'); return res.status(405).json({ error: 'Method not allowed.' }); }
  if (req.method === 'POST' && req.headers.origin) {
    try { if (new URL(req.headers.origin).host !== req.headers.host) return res.status(403).json({ error: 'Use the local vision inspector in this app.' }); }
    catch { return res.status(403).json({ error: 'Invalid request origin.' }); }
  }
  const check = req.query.check ?? 'ready';
  if (req.method === 'GET' && check !== 'ready' && check !== 'health') return res.status(400).json({ error: 'Unknown service check.' });
  const body = req.method === 'POST' ? validateLocalVisionInput(req.body) : undefined;
  if (req.method === 'POST' && !body) return res.status(422).json({ error: 'Choose a PNG, JPEG or WebP image up to 2 MiB, a valid task, and an object prompt up to 200 characters.' });
  const token = process.env.LOCAL_VISION_API_TOKEN;
  if (!token) return res.status(503).json({ status: 'unavailable', ready: false, error: 'Local vision is not configured. Start it with the VSS runtime.' });
  let base: URL;
  try {
    base = new URL(process.env.LOCAL_VISION_API_URL || 'http://127.0.0.1:8026');
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw new Error('Invalid backend');
  } catch { return res.status(503).json({ status: 'unavailable', ready: false, error: 'Local vision configuration is unavailable.' }); }
  const abort = new AbortController(); const timer = setTimeout(() => abort.abort(), req.method === 'POST' ? 120_000 : 5_000);
  const close = () => { if (!res.writableEnded) abort.abort(); }; res.on?.('close', close);
  try {
    const response = await fetch(new URL(req.method === 'POST' ? '/infer' : `/${check}`, base), {
      method: req.method, headers: { 'Content-Type': 'application/json', 'X-VSS-Model-Token': token },
      ...(body ? { body: JSON.stringify(body) } : {}), signal: abort.signal, redirect: 'error', cache: 'no-store',
    });
    const payload = await boundedJson(response);
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Invalid model response');
    if (!response.ok) {
      const state = publicLocalVisionPayload(payload) as Record<string, unknown>;
      const status = [400, 413, 422, 429, 503].includes(response.status) ? response.status : 502;
      const error = status === 429 ? 'Local vision is busy. Wait for the current image to finish, then retry.' : status === 503 ? 'Local vision is loading or unavailable. Check readiness and retry.' : [400, 413, 422].includes(status) ? 'The image or prompt could not be processed. Choose another image and retry.' : 'The local model request failed. Check the local service and retry.';
      if (status === 429) res.setHeader('Retry-After', '2');
      return res.status(status).json({ ...state, error });
    }
    return res.status(200).json(publicLocalVisionPayload(payload));
  } catch {
    return res.status(abort.signal.aborted ? 504 : 502).json({ status: 'unavailable', ready: false, error: abort.signal.aborted ? 'The local model request timed out. Check the service before retrying.' : 'Local vision is unavailable. Check the service and retry.' });
  } finally { clearTimeout(timer); res.off?.('close', close); }
}
