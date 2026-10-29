// SPDX-License-Identifier: MIT
import { liveAnswerWindow, normalizeAnswerEvidenceUrl } from '../answerEvidence';
import type { VisionAnalystResponse } from '../../analyst';
const answer = (startTime = '2026-10-22T12:00:00Z', endTime = '2026-10-22T12:00:05Z') => ({ observedWindow: { startTime, endTime } } as VisionAnalystResponse);
describe('bounded answer evidence scope', () => {
  it('accepts only a returned positive interval of at most five seconds', () => {
    expect(liveAnswerWindow(answer())).toEqual(answer().observedWindow);
    expect(liveAnswerWindow(answer(undefined, '2026-10-22T12:00:06Z'))).toBeNull();
    expect(liveAnswerWindow(answer(undefined, '2026-10-22T11:59:59Z'))).toBeNull();
    expect(liveAnswerWindow(answer('2026-10-22T12:00:00', '2026-10-22T12:00:05'))).toBeNull();
    expect(liveAnswerWindow({} as VisionAnalystResponse)).toBeNull();
  });
  it('normalizes only the same-origin evidence proxy or known VST MP4 export origin', () => {
    const key = 'a'.repeat(64);
    expect(normalizeAnswerEvidenceUrl(`/api/vision/evidence-media?key=${key}`, 'http://booth.test', 'http://video.test/vst/api')).toBe(`/api/vision/evidence-media?key=${key}`);
    expect(normalizeAnswerEvidenceUrl('/vst/storage/temp_files/clip.mp4?token=opaque', 'http://booth.test', 'http://video.test/vst/api')).toBe('http://video.test/vst/storage/temp_files/clip.mp4?token=opaque');
    expect(normalizeAnswerEvidenceUrl('http://video.test/vst/storage/temp_files/clip.mp4', 'http://booth.test', 'http://video.test/vst/api')).toBe('http://video.test/vst/storage/temp_files/clip.mp4');
  });
  it.each(['javascript:alert(1)', 'https://untrusted.test/vst/storage/temp_files/clip.mp4', 'http://user:password@video.test/vst/storage/temp_files/clip.mp4', '//untrusted.test/vst/storage/temp_files/clip.mp4', '/api/vision/evidence-media?key=invalid', '/vst/api/v1/storage/all', '/vst/storage/temp_files/clip.mp4#other', '/vst\\storage\\temp_files\\clip.mp4'])('rejects unsafe or unrelated media URL %s', value => {
    expect(normalizeAnswerEvidenceUrl(value, 'http://booth.test', 'http://video.test/vst/api')).toBeNull();
  });
});
