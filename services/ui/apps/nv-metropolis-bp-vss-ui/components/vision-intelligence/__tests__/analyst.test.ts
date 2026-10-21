// SPDX-License-Identifier: MIT
import { cleanAgentAnswer } from '../analyst';

describe('Vision Analyst response helpers', () => {
  it('removes internal reasoning while preserving the visitor-facing answer', () => {
    expect(cleanAgentAnswer(
      '<agent-think><agent-think-step>private trace</agent-think-step></agent-think>\n\nTwo forklifts crossed the loading area.'
    )).toBe('Two forklifts crossed the loading area.');
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
