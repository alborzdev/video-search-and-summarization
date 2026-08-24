// SPDX-License-Identifier: MIT
import { cleanAgentAnswer, extractObservedRange, extractSuccessfulEvidenceTools } from '../analyst';

describe('Vision Analyst response helpers', () => {
  it('removes internal reasoning while preserving the visitor-facing answer', () => {
    expect(cleanAgentAnswer(
      '<agent-think><agent-think-step>private trace</agent-think-step></agent-think>\n\nTwo forklifts crossed the loading area.'
    )).toBe('Two forklifts crossed the loading area.');
  });

  it('extracts the precise video-understanding interval from the tool trace', () => {
    expect(extractObservedRange(
      '<agent-think><agent-think-step>Tool: video_understanding Args: {} Result: 6.4-78.0 A forklift moved. 78.0-228.5 Workers entered.</agent-think-step></agent-think> Answer'
    )).toEqual({ startSeconds: 6.4, endSeconds: 228.5 });
  });

  it('requires a successful visual evidence tool instead of trusting any agent answer', () => {
    expect(extractSuccessfulEvidenceTools(
      '<agent-think><agent-think-step>Tool: video_understanding Args: {} Result: 4.0-12.0 A person crossed.</agent-think-step></agent-think> Answer'
    )).toEqual(['video_understanding']);
    expect(extractSuccessfulEvidenceTools(
      '<agent-think><agent-think-step>Tool: video_understanding Args: {} Result: Error: clip unavailable.</agent-think-step></agent-think> I seem to be having a problem.'
    )).toEqual([]);
  });

  it('removes an unclosed private trace rather than leaking it into the UI', () => {
    expect(cleanAgentAnswer('<agent-think>private trace that never closed')).toBe('');
  });

  it('removes tool-relative range prefixes from visitor-facing prose', () => {
    expect(cleanAgentAnswer('0.6-13.1 seconds, A forklift is moving near two workers.')).toBe(
      'A forklift is moving near two workers.'
    );
  });

  it('turns tool-relative decimal timestamps into natural clip language', () => {
    expect(cleanAgentAnswer(
      'At 0.0, two people are visible. At 1.27, a forklift remains still. From 6.23 to 14.9, the area clears. By 19.87, no activity occurs.'
    )).toBe(
      'At the start of the inspected clip, two people are visible. During the inspected clip, a forklift remains still. Later in the inspected clip, the area clears. By the end of the inspected clip, no activity occurs.'
    );
  });
});
