#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { spawn } from 'node:child_process';

const ACK = 'I_AUTHORIZE_OWNED_REALTIME_ALERT_REPLAY';
const MAX_DURATION_MS = 240_000;
const HTTP_TIMEOUT_MS = 45_000;
const ALERT_ORIGIN = 'http://127.0.0.1:9080';
const RTVLM_ORIGIN = 'http://127.0.0.1:8018';
const ELASTIC_ORIGIN = 'http://127.0.0.1:9200';
const PUBLISH_ORIGIN = 'rtsp://127.0.0.1:8554';
// The deployed Alert Bridge persistence config uses index_prefix "ab-"
// with the logical collection "alert-realtime-rules".
const RULE_INDEX = 'ab-alert-realtime-rules';
const INCIDENT_INDEX = 'mdx-vlm-incidents-*';

const sha = value => crypto.createHash('sha256').update(
  Buffer.isBuffer(value) ? value : Buffer.from(String(value)),
).digest('hex');

const stable = value => {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
  }
  return value;
};

const canonical = value => JSON.stringify(stable(value));

function fail(code) {
  const error = new Error(code);
  error.code = code;
  throw error;
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith('--') || !value || flag.slice(2) in values) fail('arguments');
    values[flag.slice(2)] = value;
  }
  for (const key of ['ack', 'run-id', 'fixture', 'output', 'contract']) {
    if (!values[key]) fail(`missing_${key.replaceAll('-', '_')}`);
  }
  if (values.ack !== ACK) fail('acknowledgement');
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,47}$/.test(values['run-id'])) fail('run_id');
  return values;
}

function isNumericLoopback(raw) {
  const url = new URL(raw);
  const host = url.hostname.replace(/^\[|\]$/g, '');
  const family = net.isIP(host);
  return url.protocol === 'http:' && (
    (family === 4 && host.startsWith('127.')) || (family === 6 && host === '::1')
  );
}

async function jsonRequest(url, options = {}) {
  if (!isNumericLoopback(url)) fail('non_loopback_request');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout ?? HTTP_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body ? { 'content-type': 'application/json' } : {}),
        ...(options.headers ?? {}),
      },
    });
    const raw = await response.text();
    let body = null;
    try {
      body = raw ? JSON.parse(raw) : null;
    } catch {
      fail('non_json_response');
    }
    return { status: response.status, body };
  } finally {
    clearTimeout(timer);
  }
}

async function poll(operation, predicate, timeout = 45_000) {
  const deadline = Date.now() + timeout;
  let latest;
  while (Date.now() < deadline) {
    latest = await operation();
    if (predicate(latest)) return latest;
    await new Promise(resolve => setTimeout(resolve, 750));
  }
  fail('poll_timeout');
}

function rulesFrom(body) {
  if (!body || !Array.isArray(body.rules)) fail('rules_envelope');
  return body.rules;
}

function streamsFrom(body) {
  if (!Array.isArray(body)) fail('streams_envelope');
  return body;
}

function hitsFrom(body) {
  const hits = body?.hits?.hits;
  if (!Array.isArray(hits)) fail('elastic_hits_envelope');
  return hits
    .map(hit => ({ _id: hit._id, _index: hit._index, _source: hit._source }))
    .sort((left, right) => String(left._id).localeCompare(String(right._id)));
}

function containsOwned(value, owned) {
  if (typeof value === 'string') return owned.some(item => item && value.includes(item));
  if (Array.isArray(value)) return value.some(item => containsOwned(item, owned));
  if (value && typeof value === 'object') {
    return Object.entries(value).some(([key, item]) => containsOwned(key, owned) || containsOwned(item, owned));
  }
  return false;
}

function digestUnrelated(rows, owned) {
  return sha(canonical(rows.filter(row => !containsOwned(row, owned))));
}

async function runCommand(executable, args, timeout = 15_000) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    const stdout = [];
    const stderr = [];
    child.stdout.on('data', chunk => stdout.push(chunk));
    child.stderr.on('data', chunk => stderr.push(chunk));
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error('command_timeout'));
    }, timeout);
    child.once('error', error => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('exit', code => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(`command_failed_${code}_${sha(Buffer.concat(stderr)).slice(0, 12)}`));
        return;
      }
      resolve(Buffer.concat(stdout).toString('utf8'));
    });
  });
}

async function rtvlmWorkerCounts(streamId) {
  const raw = await runCommand('/usr/bin/docker', [
    'logs', '--since', '10m', 'vss-rtvi-vlm',
  ], 20_000);
  const lines = raw.split('\n');
  return {
    created: lines.filter(line =>
      line.includes('Created live stream query') && line.includes(`for videoId ${streamId}`),
    ).length,
    removed: lines.filter(line =>
      line.includes(`Removed live stream ${streamId} from pipeline for query`),
    ).length,
  };
}

async function snapshot() {
  const [rules, streams, persisted] = await Promise.all([
    jsonRequest(`${ALERT_ORIGIN}/api/v1/realtime`),
    jsonRequest(`${RTVLM_ORIGIN}/v1/streams/get-stream-info`),
    jsonRequest(`${ELASTIC_ORIGIN}/${RULE_INDEX}/_search?size=10000`),
  ]);
  if (rules.status !== 200 || streams.status !== 200) fail('snapshot_http');
  if (![200, 404].includes(persisted.status)) fail('snapshot_elastic_http');
  return {
    rules: rulesFrom(rules.body),
    streams: streamsFrom(streams.body),
    persisted: persisted.status === 404 ? [] : hitsFrom(persisted.body),
  };
}

async function persistedRule(ruleId) {
  const result = await jsonRequest(
    `${ELASTIC_ORIGIN}/${RULE_INDEX}/_doc/${encodeURIComponent(ruleId)}`,
  );
  if (result.status !== 200 || result.body?._id !== ruleId || result.body?.found !== true) {
    fail('persisted_rule');
  }
  return result.body._source;
}

function immutableConfig(rule) {
  const fields = [
    'live_stream_url', 'alert_type', 'sensor_id', 'sensor_name', 'prompt', 'system_prompt',
    'model', 'chunk_duration', 'chunk_overlap_duration',
    'num_frames_per_second_or_fixed_frames_chunk', 'use_fps_for_chunking',
    'vlm_input_width', 'vlm_input_height', 'enable_reasoning', 'max_tokens',
  ];
  return Object.fromEntries(fields.map(field => [field, rule?.[field] ?? null]));
}

function validateReplay(response, ruleId, streamId) {
  if (
    response.status !== 200 || response.body?.status !== 'success' ||
    response.body?.replayed !== 1 || response.body?.failed !== 0 ||
    response.body?.total !== 1 || !Array.isArray(response.body?.details) ||
    response.body.details.length !== 1 || response.body.details[0]?.id !== ruleId ||
    response.body.details[0]?.result !== 'success' ||
    response.body.details[0]?.rtvi_stream_id !== streamId
  ) fail('replay_response');
}

async function ownedIncidentHits(sensorId, sensorName, alertType) {
  const response = await jsonRequest(`${ELASTIC_ORIGIN}/${INCIDENT_INDEX}/_search?size=100`, {
    method: 'POST',
    body: JSON.stringify({
      query: {
        bool: {
          should: [
            { term: { 'sensorId.keyword': sensorId } },
            { term: { 'sensorId.keyword': sensorName } },
            { term: { 'category.keyword': alertType } },
          ],
          minimum_should_match: 1,
        },
      },
    }),
  });
  if (response.status === 404) return [];
  if (response.status !== 200 || !Array.isArray(response.body?.hits?.hits)) fail('incident_search');
  return response.body.hits.hits.filter(hit =>
    containsOwned(hit?._source, [sensorId, sensorName, alertType]),
  );
}

async function cleanupIncidents(sensorId, sensorName, alertType) {
  let deleted = 0;
  let emptyRounds = 0;
  for (let round = 0; round < 8 && emptyRounds < 2; round += 1) {
    const hits = await ownedIncidentHits(sensorId, sensorName, alertType);
    for (const hit of hits) {
      if (
        typeof hit?._index !== 'string' || typeof hit?._id !== 'string' ||
        !/^mdx-vlm-incidents-\d{4}-\d{2}-\d{2}$/.test(hit._index) ||
        !/^[A-Za-z0-9_-]{1,128}$/.test(hit._id)
      ) fail('incident_identity');
      const response = await jsonRequest(
        `${ELASTIC_ORIGIN}/${encodeURIComponent(hit._index)}/_doc/${encodeURIComponent(hit._id)}?refresh=wait_for`,
        { method: 'DELETE' },
      );
      if (response.status !== 200 || !['deleted', 'not_found'].includes(response.body?.result)) {
        fail('incident_delete');
      }
      if (response.body.result === 'deleted') deleted += 1;
    }
    if (hits.length === 0) emptyRounds += 1;
    else emptyRounds = 0;
    if (emptyRounds < 2) await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if ((await ownedIncidentHits(sensorId, sensorName, alertType)).length) fail('owned_incidents_remain');
  return deleted;
}

async function stopProcess(child) {
  if (!child || child.exitCode !== null) return;
  child.kill('SIGTERM');
  await Promise.race([
    new Promise(resolve => child.once('exit', resolve)),
    new Promise(resolve => setTimeout(resolve, 3000)),
  ]);
  if (child.exitCode === null) {
    child.kill('SIGKILL');
    await Promise.race([
      new Promise(resolve => child.once('exit', resolve)),
      new Promise(resolve => setTimeout(resolve, 1000)),
    ]);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const started = Date.now();
  const fixture = path.resolve(args.fixture);
  const output = path.resolve(args.output);
  const contractPath = path.resolve(args.contract);
  const [fixtureRaw, contractRaw] = await Promise.all([
    fs.readFile(fixture),
    fs.readFile(contractPath),
  ]);
  const contract = JSON.parse(contractRaw);
  if (
    contract?.package_id !== 'realtime-alert-rule-replay-runtime-successor' ||
    contract?.capability_id !== 'manifest-entry.realtime-alerts.02-rule-replay'
  ) fail('contract_identity');

  const sensorName = `thor-replay-${args['run-id']}`;
  const sensorId = crypto.randomUUID();
  const alertType = `owned_replay_${args['run-id'].replaceAll('-', '_')}`;
  const prompt = 'Is a bright purple elephant clearly visible in this video?';
  const publishUrl = `${PUBLISH_ORIGIN}/${sensorName}`;
  const inputUrl = `rtsp://172.18.0.1:8554/${sensorName}`;
  const owned = [sensorName, sensorId, alertType];
  let publisher;
  let ruleId = '';
  let workflowPassed = false;
  let deletedIncidents = 0;
  const before = await snapshot();
  if (before.rules.length !== 0 || before.persisted.length !== 0) fail('preexisting_rules');
  if (containsOwned(before, owned)) fail('owned_name_collision');
  if ((await ownedIncidentHits(sensorId, sensorName, alertType)).length) fail('owned_incident_collision');
  const beforeDigests = {
    rules: sha(canonical(before.rules)),
    persisted_rules: sha(canonical(before.persisted)),
    rtvlm_streams: digestUnrelated(before.streams, owned),
  };
  const mutationSequence = [];
  let configSha = '';
  let identitySha = '';
  let streamSha = '';
  const replayTimestampHashes = [];
  const workerCreatedCounts = [];
  const workerRemovedCounts = [];

  try {
    publisher = spawn('/usr/bin/ffmpeg', [
      '-hide_banner', '-loglevel', 'error', '-re', '-stream_loop', '-1',
      '-i', fixture, '-an', '-c:v', 'copy', '-f', 'rtsp', '-rtsp_transport', 'tcp', publishUrl,
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
    let publisherError = '';
    publisher.stderr.on('data', chunk => {
      publisherError = `${publisherError}${chunk}`.slice(-4096);
    });
    await new Promise(resolve => setTimeout(resolve, 1500));
    if (publisher.exitCode !== null) fail(`publisher_exit_${sha(publisherError).slice(0, 12)}`);

    const create = await jsonRequest(`${ALERT_ORIGIN}/api/v1/realtime`, {
      method: 'POST',
      body: JSON.stringify({
        live_stream_url: inputUrl,
        sensor_id: sensorId,
        sensor_name: sensorName,
        alert_type: alertType,
        prompt,
        system_prompt: 'Answer exactly yes or no.',
        chunk_duration: 10,
        chunk_overlap_duration: 2,
        num_frames_per_second_or_fixed_frames_chunk: 4,
        use_fps_for_chunking: false,
        vlm_input_width: 512,
        vlm_input_height: 512,
        enable_reasoning: false,
        max_tokens: 32,
      }),
    });
    mutationSequence.push('POST /api/v1/realtime');
    if (create.status !== 201 || create.body?.status !== 'success') fail('create_rule');
    ruleId = create.body?.id ?? '';
    if (!/^[0-9a-f-]{36}$/i.test(ruleId)) fail('rule_identity');
    owned.push(ruleId);
    identitySha = sha(ruleId);

    const created = await poll(snapshot, state =>
      state.rules.filter(rule => rule.id === ruleId).length === 1 &&
      state.persisted.filter(hit => hit._id === ruleId).length === 1 &&
      state.streams.filter(stream => stream.id === sensorId).length === 1,
    );
    const createdRule = created.rules.find(rule => rule.id === ruleId);
    const createdDoc = await persistedRule(ruleId);
    if (createdRule?.status !== 'active') fail('created_public_status');
    if (createdDoc?.status !== 'active') fail('created_persisted_status');
    if (createdDoc?.rtvi_stream_id !== sensorId) fail('created_persisted_stream_identity');
    configSha = sha(canonical(immutableConfig(createdDoc)));
    streamSha = sha(sensorId);
    const createdAt = createdDoc.created_at;
    if (typeof createdAt !== 'string' || !createdAt) fail('created_at');
    const initialWorkers = await poll(
      () => rtvlmWorkerCounts(sensorId),
      counts => counts.created === 1 && counts.removed === 0,
      20_000,
    );
    if (initialWorkers.created - initialWorkers.removed !== 1) fail('initial_worker_count');

    for (let replayIndex = 0; replayIndex < 2; replayIndex += 1) {
      const replay = await jsonRequest(`${ALERT_ORIGIN}/api/v1/realtime/replay`, {
        method: 'POST', body: '{}', timeout: 90_000,
      });
      mutationSequence.push('POST /api/v1/realtime/replay');
      validateReplay(replay, ruleId, sensorId);
      const state = await snapshot();
      const publicMatches = state.rules.filter(rule => rule.id === ruleId);
      const persistedMatches = state.persisted.filter(hit => hit._id === ruleId);
      const streamMatches = state.streams.filter(stream => stream.id === sensorId);
      if (publicMatches.length !== 1 || persistedMatches.length !== 1 || streamMatches.length !== 1) {
        fail('duplicate_activation');
      }
      const doc = await persistedRule(ruleId);
      if (
        doc.status !== 'active' || doc.created_at !== createdAt ||
        doc.rtvi_stream_id !== sensorId ||
        sha(canonical(immutableConfig(doc))) !== configSha
      ) fail('replay_identity_or_config');
      if (typeof doc.last_replay_at !== 'string' || !doc.last_replay_at) fail('replay_timestamp');
      replayTimestampHashes.push(sha(doc.last_replay_at));
      if (replayIndex === 1 && replayTimestampHashes[1] === replayTimestampHashes[0]) {
        fail('replay_timestamp_not_advanced');
      }
      const expectedCreated = replayIndex + 2;
      const expectedRemoved = replayIndex + 1;
      const workers = await poll(
        () => rtvlmWorkerCounts(sensorId),
        counts => counts.created === expectedCreated && counts.removed === expectedRemoved,
        20_000,
      );
      if (workers.created - workers.removed !== 1) fail('replay_worker_count');
      workerCreatedCounts.push(workers.created);
      workerRemovedCounts.push(workers.removed);
    }
    workflowPassed = true;
  } finally {
    if (ruleId) {
      const deleted = await jsonRequest(
        `${ALERT_ORIGIN}/api/v1/realtime/${encodeURIComponent(ruleId)}`,
        { method: 'DELETE', timeout: 45_000 },
      ).catch(() => null);
      mutationSequence.push('DELETE /api/v1/realtime/<owned>');
      if (deleted && deleted.status !== 200) fail('rule_delete');
      const repeated = await jsonRequest(
        `${ALERT_ORIGIN}/api/v1/realtime/${encodeURIComponent(ruleId)}`,
        { method: 'DELETE', timeout: 45_000 },
      ).catch(() => null);
      mutationSequence.push('DELETE /api/v1/realtime/<owned>');
      if (repeated && repeated.status !== 404) fail('repeated_delete');
    }
    await stopProcess(publisher);
    deletedIncidents = await cleanupIncidents(sensorId, sensorName, alertType);
  }

  const after = await poll(snapshot, state =>
    !containsOwned(state, owned) && state.rules.length === 0 && state.persisted.length === 0,
  );
  const afterDigests = {
    rules: sha(canonical(after.rules)),
    persisted_rules: sha(canonical(after.persisted)),
    rtvlm_streams: digestUnrelated(after.streams, owned),
  };
  const finalWorkers = await poll(
    () => rtvlmWorkerCounts(sensorId),
    counts => counts.created === 3 && counts.removed === 3,
    30_000,
  );
  const cleanupExact = canonical(beforeDigests) === canonical(afterDigests);
  const duration = Date.now() - started;
  if (!workflowPassed || !cleanupExact || duration > MAX_DURATION_MS) fail('postconditions');

  const receipt = {
    schema_version: 1,
    package_id: contract.package_id,
    capability_id: contract.capability_id,
    contract_sha256: sha(contractRaw),
    status: 'passed',
    run: {
      duration_ms: duration,
      fixture_bytes: fixtureRaw.length,
      fixture_sha256: sha(fixtureRaw),
      numeric_loopback_http_only: true,
      agent_generate_request_count: 0,
    },
    replay: {
      persisted_rule_created_active: true,
      replay_count: 2,
      replay_success_count: 2,
      immutable_identity_preserved: true,
      immutable_config_preserved: true,
      created_at_preserved: true,
      replay_timestamp_advanced: true,
      one_public_rule_after_each_replay: true,
      one_persisted_rule_after_each_replay: true,
      one_rtvlm_stream_after_each_replay: true,
      one_caption_worker_after_each_replay: true,
      worker_created_counts: workerCreatedCounts,
      worker_removed_counts: workerRemovedCounts,
      rule_identity_sha256: identitySha,
      stream_identity_sha256: streamSha,
      immutable_config_sha256: configSha,
      replay_timestamp_sha256: replayTimestampHashes,
      mutation_sequence: mutationSequence,
    },
    cleanup: {
      exact_unrelated_state_restored: cleanupExact,
      before_sha256: beforeDigests,
      after_sha256: afterDigests,
      rule_deleted: true,
      repeated_delete_explicit_not_found: true,
      publisher_stopped: publisher?.exitCode !== null,
      owned_incident_documents_deleted: deletedIncidents,
      owned_incident_artifacts_absent: true,
      final_caption_worker_count: finalWorkers.created - finalWorkers.removed,
    },
  };
  await fs.writeFile(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o644 });
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
}

main().catch(error => {
  process.stderr.write(`${JSON.stringify({ status: 'failed', code: error?.code ?? error?.message ?? 'unknown' })}\n`);
  process.exitCode = 1;
});
