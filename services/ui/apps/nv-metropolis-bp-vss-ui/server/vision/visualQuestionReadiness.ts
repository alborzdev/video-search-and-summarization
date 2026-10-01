// SPDX-License-Identifier: MIT
import { readFile } from 'node:fs/promises';
import path from 'node:path';

export async function visualQuestionBlockReason(): Promise<string | null> {
  try {
    const rules: unknown = JSON.parse(await readFile(path.join(
      process.env.VISION_RULES_DIR || '/tmp/vss-vision-intelligence-rules', 'rules.json'), 'utf8'));
    if (!Array.isArray(rules)) throw new Error('Invalid monitoring rules');
    return rules.some((rule) => rule?.engine === 'vlm' && rule?.status === 'active')
      ? 'Pause visual monitoring in Alert rules to ask a question.' : null;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    return 'Visual monitoring status is unavailable. Retry before asking a question.';
  }
}
