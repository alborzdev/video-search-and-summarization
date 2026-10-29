// SPDX-License-Identifier: MIT
import type { VisionAnalystResponse } from '../analyst';
export interface CityAnswerSource { id: string; sensorId: string; name: string; mode: string; mediaUrl?: string; vstApiUrl?: string | null; }
export function liveAnswerWindow(answer: VisionAnalystResponse) {
  const window = answer.observedWindow;
  if (!window || ![window.startTime, window.endTime].every(value => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value)))) return null;
  const duration = Date.parse(window.endTime) - Date.parse(window.startTime);
  return duration > 0 && duration <= 5001 ? { ...window } : null;
}
export function normalizeAnswerEvidenceUrl(value: unknown, applicationOrigin: string, vstApiUrl?: string | null): string | null {
  if (typeof value !== 'string' || value.length > 8192 || value.trim() !== value || /[\\\u0000-\u0020]/.test(value)) return null;
  try {
    const app = new URL(applicationOrigin); const target = new URL(value, app.origin);
    if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password || target.hash) return null;
    if (target.origin === app.origin && target.pathname === '/api/vision/evidence-media') {
      const key = target.searchParams.get('key');
      return key && /^[a-f0-9]{64}$/.test(key) && [...target.searchParams.keys()].every(name => name === 'key') ? `/api/vision/evidence-media?key=${key}` : null;
    }
    const vst = vstApiUrl ? new URL(vstApiUrl, app.origin) : null;
    if (vst && (!['http:', 'https:'].includes(vst.protocol) || vst.username || vst.password)) return null;
    if (target.origin !== app.origin && target.origin !== vst?.origin) return null;
    if (!target.pathname.startsWith('/vst/storage/temp_files/') || !target.pathname.toLowerCase().endsWith('.mp4')) return null;
    return `${vst?.origin ?? app.origin}${target.pathname}${target.search}`;
  } catch { return null; }
}
export function observedWindowLabel(answer: VisionAnalystResponse): string | null {
  const window = answer.observedWindow;
  if (!window || !Number.isFinite(Date.parse(window.startTime)) || !Number.isFinite(Date.parse(window.endTime)) || Date.parse(window.endTime) <= Date.parse(window.startTime)) return null;
  const format = (value: string) => new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' });
  return `${format(window.startTime)} – ${format(window.endTime)}`;
}
