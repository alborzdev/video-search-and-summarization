// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import { rm } from 'node:fs/promises';

const storeDirectory = `/tmp/vss-incident-state-test-${process.pid}`;

function responseHarness() {
  const state: { body?: any; statusCode: number } = { statusCode: 200 };
  const response = {
    json(body: unknown) { state.body = body; return response; },
    setHeader() { return response; },
    status(statusCode: number) { state.statusCode = statusCode; return response; },
  } as unknown as NextApiResponse;
  return { response, state };
}

describe('incident state API', () => {
  let handler: (req: NextApiRequest, res: NextApiResponse) => Promise<unknown>;
  beforeAll(async () => {
    process.env.VISION_RULES_DIR = storeDirectory;
    handler = (await import('../../../pages/api/vision/incident-state')).default;
  });
  afterAll(async () => {
    await rm(storeDirectory, { force: true, recursive: true });
    delete process.env.VISION_RULES_DIR;
  });

  it('persists acknowledgement and resolution independently from model verdicts', async () => {
    const put = responseHarness();
    await handler({ method: 'PUT', body: { incidentId: 'incident-1', state: 'acknowledged' }, query: {} } as unknown as NextApiRequest, put.response);
    expect(put.state.statusCode).toBe(200);
    expect(put.state.body.record).toMatchObject({ incidentId: 'incident-1', state: 'acknowledged' });

    const get = responseHarness();
    await handler({ method: 'GET', query: {} } as unknown as NextApiRequest, get.response);
    expect(get.state.body.states['incident-1']).toMatchObject({ state: 'acknowledged' });
  });
});
