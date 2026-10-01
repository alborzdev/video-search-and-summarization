// SPDX-License-Identifier: MIT

import type { IncidentWorkflowState } from '../../../components/vision-intelligence/incidentState';
import type { NextApiRequest, NextApiResponse } from 'next';
import { exclusiveIncidentState as exclusive, readIncidentStates as readRecords, writeIncidentStates as writeRecords } from '../../../server/vision/incidentStateStore';

const VALID_STATES = new Set<IncidentWorkflowState>(['new', 'acknowledged', 'resolved']);

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method === 'GET') {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({ states: await readRecords() });
  }
  if (req.method === 'PUT') {
    const incidentId = String(req.body?.incidentId || '').trim();
    const state = req.body?.state as IncidentWorkflowState;
    if (!incidentId || incidentId.length > 256 || !VALID_STATES.has(state)) {
      return res.status(422).json({ error: 'Choose a valid incident and workflow state.' });
    }
    return exclusive(async () => {
      const records = await readRecords();
      const record = { incidentId, state, updatedAt: new Date().toISOString() };
      records[incidentId] = record;
      await writeRecords(records);
      return res.status(200).json({ record });
    });
  }
  res.setHeader('Allow', 'GET, PUT');
  return res.status(405).json({ error: 'Method not allowed.' });
}
