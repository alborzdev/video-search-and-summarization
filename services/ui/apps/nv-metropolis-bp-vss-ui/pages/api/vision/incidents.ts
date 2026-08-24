// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';

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

  const toolResponse = await fetch(mcpUrl, {
    method: 'POST',
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
        arguments: { max_count: 100, includes: ['objectIds', 'info'] },
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
  return payload.incidents ?? [];
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ error: 'Method not allowed.' });
  }

  try {
    const incidents = await fetchAnalyticsIncidents();

    res.setHeader('Cache-Control', 'private, max-age=5, stale-while-revalidate=20');
    return res.status(200).json({ incidents, hasMore: false });
  } catch (error) {
    return res.status(503).json({
      error: error instanceof Error ? error.message : 'Analytics are unavailable.',
      incidents: [],
    });
  }
}
