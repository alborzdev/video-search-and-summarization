/** @jest-environment node */
import { readFile } from 'node:fs/promises';
import { visualQuestionBlockReason } from '../visualQuestionReadiness';
jest.mock('node:fs/promises', () => ({ readFile: jest.fn() }));
const read = readFile as jest.Mock;
it.each(['active', 'paused', 'draft'])('blocks only active continuous VLM monitoring (%s)', async (status) => {
  read.mockResolvedValue(JSON.stringify([{ engine: 'vlm', status, sourceIds: ['other-camera'] }]));
  expect(await visualQuestionBlockReason()).toBe(status === 'active' ? 'Pause visual monitoring in Alert rules to ask a question.' : null);
});
it('does not block detector rules or a missing local rule store', async () => {
  read.mockResolvedValue(JSON.stringify([{ engine: 'deepstream', status: 'active' }]));
  expect(await visualQuestionBlockReason()).toBeNull();
  read.mockRejectedValue(Object.assign(new Error(), { code: 'ENOENT' }));
  expect(await visualQuestionBlockReason()).toBeNull();
});
