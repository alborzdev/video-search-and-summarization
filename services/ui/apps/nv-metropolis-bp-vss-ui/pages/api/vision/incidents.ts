// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import type { MonitoringRule } from '../../../components/vision-intelligence/monitoringRules';

interface McpContent {
  text?: string;
  type?: string;
}

interface McpResponse {
  error?: { code?: number; message?: string };
  result?: { content?: McpContent[] };
}

function parseSseResponse(value: string): McpResponse | null {
  for (const line of value.split('\n')) {
    if (!line.startsWith('data:')) continue;
    try {
      const message = JSON.parse(line.slice(5).trim()) as McpResponse;
      // Streamable HTTP may emit progress/notification events before the
      // JSON-RPC tool result. Only a terminal result or error answers this
      // request; returning the first valid JSON object drops real incidents.
      if (message.result || message.error) return message;
    } catch {
      // Continue in case the response contains a later valid event.
    }
  }
  return null;
}

export async function fetchAnalyticsIncidents(): Promise<unknown[]> {
  const mcpUrl = process.env.VA_MCP_URL || 'http://127.0.0.1:9901/mcp';
  const initializeResponse = await fetch(mcpUrl, {
    method: 'POST',
    signal: AbortSignal.timeout(15_000),
    headers: {
      Accept: 'application/json, text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'vision-intelligence-ui', version: '1.0' },
      },
      id: 0,
    }),
  });

  const sessionId = initializeResponse.headers.get('mcp-session-id');
  if (!initializeResponse.ok || !sessionId) {
    throw new Error(`Analytics session could not be initialized (${initializeResponse.status}).`);
  }

  try {
    const toolResponse = await fetch(mcpUrl, {
      method: 'POST',
      signal: AbortSignal.timeout(15_000),
      headers: {
        Accept: 'application/json, text/event-stream',
        'Content-Type': 'application/json',
        'mcp-session-id': sessionId,
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'tools/call',
        params: {
          name: 'video_analytics__get_incidents',
          arguments: { max_count: 100, includes: ['category', 'objectIds', 'info', 'isAnomaly'] },
        },
        id: 1,
      }),
    });

    if (!toolResponse.ok) throw new Error(`Analytics query returned ${toolResponse.status}.`);
    const rpcResponse = parseSseResponse(await toolResponse.text());
    if (!rpcResponse) throw new Error('Analytics query returned an invalid event stream.');
    if (rpcResponse.error) throw new Error(rpcResponse.error.message || 'Analytics query failed.');
    const text = rpcResponse.result?.content?.find((item) => item.type === 'text' || item.text)?.text;
    if (!text) throw new Error('Analytics query did not return incident data.');
    const payload = JSON.parse(text) as { incidents?: unknown[] };
    // Older RT-VLM versions published affirmative ad-hoc file answers as
    // incidents using relative video time (epoch 1970). They are not monitoring
    // events. Retain recorded rule incidents, which carry explicit alert intent.
    return (payload.incidents ?? []).filter((value) => {
      const incident = value as { timestamp?: string; info?: Record<string, unknown> };
      return !(incident.timestamp?.startsWith('1970-01-01')
        && incident.info?.requestId && incident.info?.prompt
        && !incident.info?.alertRuleId && !incident.info?.alertCategory);
    });
  } finally {
    // Each poll owns a short-lived MCP session. Cleanup must not replace a
    // successful tool result or the original query error when the server is
    // unavailable during teardown.
    await fetch(mcpUrl, {
      method: 'DELETE',
      headers: { 'mcp-session-id': sessionId },
      signal: AbortSignal.timeout(3_000),
    }).catch(() => undefined);
  }
}


export function attributeDetectorIncident(value: unknown, rules: MonitoringRule[]): unknown {
  const incident = value as { sensorId?: string; info?: Record<string, unknown> };
  const roiId = String(incident.info?.roiId ?? '');
  const ruleId = roiId.startsWith('ctai-rule-') ? roiId.slice('ctai-rule-'.length) : undefined;
  const rule = rules.find(candidate => candidate.engine === 'deepstream' &&
    (ruleId ? candidate.id === ruleId : candidate.kind === 'proximity' &&
      [candidate.sourceId, candidate.sourceRuntimeName].includes(incident.sensorId)));
  return {
    ...(value as Record<string, unknown>),
    ...(rule ? { sensorId: rule.sourceId } : {}),
    info: { ...incident.info, ...(ruleId ? { alertRuleId: ruleId } : {}),
      ...(rule ? { alertRuleId: rule.id, runtimeSensorId: incident.sensorId } : {}) },
  };
}

export async function fetchUnifiedIncidents() {
    // The MCP deployment reads VLM verification results. Detector-backed
    // area/proximity incidents live in the analytics API's incident index.
    const [visualResult, detectorResult, rulesResult] = await Promise.allSettled([
      fetchAnalyticsIncidents(),
      fetch(`${(process.env.VIDEO_ANALYTICS_INTERNAL_URL || 'http://127.0.0.1:8081').replace(/\/$/, '')}/incidents?maxResultSize=100`, {
        cache: 'no-store', signal: AbortSignal.timeout(15_000),
      }).then(async response => {
        if (!response.ok) throw new Error(`Detector incident query returned ${response.status}.`);
        return response.json() as Promise<{ incidents?: Array<{ Id?: string }>; hasMore?: boolean; has_more?: boolean }>;
      }),
      readFile(path.join(process.env.VISION_RULES_DIR || '/tmp/vss-vision-intelligence-rules', 'rules.json'), 'utf8')
        .then(text => JSON.parse(text) as MonitoringRule[])
        .catch(error => { if (error.code === 'ENOENT') return []; throw error; }),
    ]);
    const errors: Record<string, string> = {};
    if (visualResult.status === 'rejected') errors.visual = String(visualResult.reason?.message || visualResult.reason);
    if (detectorResult.status === 'rejected') errors.detector = String(detectorResult.reason?.message || detectorResult.reason);
    if (rulesResult.status === 'rejected') errors.rules = String(rulesResult.reason?.message || rulesResult.reason);
    if (visualResult.status === 'rejected' && detectorResult.status === 'rejected') {
      throw new Error(Object.values(errors).join(' '));
    }
    const visualIncidents = visualResult.status === 'fulfilled' ? visualResult.value : [];
    const structured = detectorResult.status === 'fulfilled' ? detectorResult.value : {};
    const savedRules = rulesResult.status === 'fulfilled' ? rulesResult.value : [];
    // Only detector-rule events belong to this feed; legacy FOV candidates
    // are inputs to verification, rather than operator-authored rules.
    const ruleIncidents = (structured.incidents ?? []).filter(value => {
      const incident = value as { category?: string; info?: Record<string, unknown> };
      return String(incident.info?.roiId ?? '').startsWith('ctai-rule-')
        || incident.category === 'Proximity Violation';
    }).map(value => attributeDetectorIncident(value, savedRules));
    const incidents = [...new Map([...ruleIncidents, ...visualIncidents].map(value => {
      const incident = value as { Id?: string; id?: string };
      return [incident.Id ?? incident.id ?? JSON.stringify(value), value] as const;
    })).values()].sort((left, right) =>
      Date.parse((right as { timestamp: string }).timestamp) - Date.parse((left as { timestamp: string }).timestamp));
    const hasMore = incidents.length > 100 || visualIncidents.length >= 100
      || Boolean(structured.hasMore || structured.has_more) || (structured.incidents?.length ?? 0) >= 100;

    return { incidents: incidents.slice(0, 100), hasMore,
      ...(Object.keys(errors).length ? { partial: true, errors } : {}),
    };
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ error: 'Method not allowed.' });
  }
  try {
    const payload = await fetchUnifiedIncidents();
    res.setHeader('Cache-Control', 'private, max-age=5, stale-while-revalidate=20');
    return res.status(200).json(payload);
  } catch (error) {
    return res.status(503).json({
      error: error instanceof Error ? error.message : 'Analytics are unavailable.',
      incidents: [],
    });
  }
}
