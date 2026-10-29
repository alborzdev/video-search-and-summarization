// SPDX-License-Identifier: MIT
import { cityRequest } from '../useCity';
describe('city JSON response boundary', () => {
  it('rejects unreadable HTTP200 JSON instead of installing an error object as site/rules data', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => { throw new SyntaxError('bad JSON'); } });
    await expect(cityRequest('rules')).rejects.toThrow('unreadable response');
  });
  it.each([null, 7, 'not a city payload'])('rejects invalid primitive response %s', async value => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => value }); await expect(cityRequest('site')).rejects.toThrow('unreadable response');
  });
  it('checks cancellation again after the response body resolves', async () => {
    const controller = new AbortController(); global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => { controller.abort(); return { rules: [], revision: 1 }; } });
    await expect(cityRequest('rules', { signal: controller.signal })).rejects.toEqual(expect.objectContaining({ name: 'AbortError' }));
  });
});
