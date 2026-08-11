#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const ACK = 'I_AUTHORIZE_OWNED_UI_ALERT_RULE_LIFECYCLE';
const MAX_DURATION_MS = 240_000;
const HTTP_TIMEOUT_MS = 20_000;
const UI_TIMEOUT_MS = 90_000;
const UI_ORIGIN = 'http://127.0.0.1:3001';
const GATEWAY_ORIGIN = 'http://127.0.0.1:7777';
const AGENT_BASE = `${GATEWAY_ORIGIN}/api/v1`;
const ALERTS_BASE = `${GATEWAY_ORIGIN}/alert-bridge/api/v1`;
const VST_BASE = `${GATEWAY_ORIGIN}/vst/api`;
const RTVLM_ORIGIN = 'http://127.0.0.1:8018';
const ELASTIC_ORIGIN = 'http://127.0.0.1:9200';
const PUBLISH_ORIGIN = 'rtsp://127.0.0.1:8554';
const INCIDENT_INDEX_PATTERNS = ['mdx-incidents-*', 'mdx-vlm-incidents-*'];
const VST_TEMP_CONTAINER_DIR = '/home/vst/vst_release/webroot/temp_files';

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
  for (const key of [
    'ack', 'run-id', 'fixture', 'playwright-module', 'chromium', 'output', 'temp-files-dir',
    'contract',
  ]) {
    if (!values[key]) fail(`missing_${key}`);
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

async function poll(operation, predicate, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  let latest;
  while (Date.now() < deadline) {
    latest = await operation();
    if (predicate(latest)) return latest;
    await new Promise(resolve => setTimeout(resolve, 750));
  }
  fail('poll_timeout');
}

function alertRules(envelope) {
  const rows = envelope?.rules;
  if (!Array.isArray(rows)) fail('alert_rules_envelope');
  return rows;
}

function sensorRows(envelope) {
  if (!Array.isArray(envelope)) fail('sensor_list_envelope');
  return envelope;
}

function nestedStreamRows(envelope) {
  if (!Array.isArray(envelope)) fail('stream_catalog_envelope');
  const rows = [];
  for (const sensor of envelope) {
    if (!sensor || typeof sensor !== 'object' || Array.isArray(sensor)) fail('stream_catalog_row');
    for (const [sensorId, streams] of Object.entries(sensor)) {
      if (!Array.isArray(streams)) fail('stream_catalog_streams');
      if (streams.length === 0) rows.push({ sensorId, empty: true });
      for (const stream of streams) rows.push({ sensorId, ...stream });
    }
  }
  return rows;
}

function rtvlmRows(envelope) {
  if (!Array.isArray(envelope)) fail('rtvlm_envelope');
  return envelope;
}

function containsOwned(value, owned) {
  if (typeof value === 'string') return owned.some(item => item && value.includes(item));
  if (Array.isArray(value)) return value.some(item => containsOwned(item, owned));
  if (value && typeof value === 'object') {
    return Object.entries(value).some(([key, item]) => containsOwned(key, owned) || containsOwned(item, owned));
  }
  return false;
}

function unrelatedDigest(rows, owned) {
  return sha(canonical(rows.filter(row => !containsOwned(row, owned))));
}

async function snapshot() {
  const [rules, sensors, sensorStreams, liveStreams, rtvlm] = await Promise.all([
    jsonRequest(`${ALERTS_BASE}/realtime`),
    jsonRequest(`${VST_BASE}/v1/sensor/list`),
    jsonRequest(`${VST_BASE}/v1/sensor/streams`),
    jsonRequest(`${VST_BASE}/v1/live/streams`),
    jsonRequest(`${RTVLM_ORIGIN}/v1/streams/get-stream-info`),
  ]);
  if ([rules, sensors, sensorStreams, liveStreams, rtvlm].some(row => row.status !== 200)) {
    fail('snapshot_http');
  }
  return {
    rules: alertRules(rules.body),
    sensors: sensorRows(sensors.body),
    sensorStreams: nestedStreamRows(sensorStreams.body),
    liveStreams: nestedStreamRows(liveStreams.body),
    rtvlm: rtvlmRows(rtvlm.body),
  };
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
      resolve(Buffer.concat(stdout));
    });
  });
}

async function ownedIncidentHits(sensorName) {
  const hits = [];
  for (const pattern of INCIDENT_INDEX_PATTERNS) {
    const response = await jsonRequest(`${ELASTIC_ORIGIN}/${pattern}/_search?size=100`, {
      method: 'POST',
      body: JSON.stringify({ query: { term: { 'sensorId.keyword': sensorName } } }),
    });
    if (response.status !== 200 || !Array.isArray(response.body?.hits?.hits)) {
      fail('incident_search');
    }
    for (const hit of response.body.hits.hits) {
      if (
        typeof hit?._index !== 'string' || typeof hit?._id !== 'string' ||
        hit?._source?.sensorId !== sensorName ||
        !/^(mdx-incidents|mdx-vlm-incidents)-\d{4}-\d{2}-\d{2}$/.test(hit._index) ||
        !/^[A-Za-z0-9_-]{1,128}$/.test(hit._id)
      ) {
        fail('incident_identity');
      }
      hits.push(hit);
    }
  }
  return hits;
}

async function ownedTempFiles(tempDir, sensorName) {
  const entries = await fs.readdir(tempDir, { withFileTypes: true });
  return entries
    .filter(entry => entry.isFile() && entry.name.startsWith(`${sensorName}_`))
    .map(entry => entry.name)
    .sort();
}

async function cleanupOwnedIncidentArtifacts(tempDir, sensorName) {
  let deletedDocuments = 0;
  let deletedFiles = 0;
  let emptyRounds = 0;
  for (let round = 0; round < 8 && emptyRounds < 2; round += 1) {
    const hits = await ownedIncidentHits(sensorName);
    for (const hit of hits) {
      const response = await jsonRequest(
        `${ELASTIC_ORIGIN}/${encodeURIComponent(hit._index)}/_doc/${encodeURIComponent(hit._id)}?refresh=wait_for`,
        { method: 'DELETE' },
      );
      if (response.status !== 200 || !['deleted', 'not_found'].includes(response.body?.result)) {
        fail('incident_delete');
      }
      if (response.body.result === 'deleted') deletedDocuments += 1;
    }
    const files = await ownedTempFiles(tempDir, sensorName);
    for (const name of files) {
      if (!/^[A-Za-z0-9_.-]+\.(jpg|mp4)$/.test(name)) fail('owned_temp_name');
      await runCommand('/usr/bin/docker', [
        'exec', '-u', '0', 'vss-vios-streamprocessing',
        'rm', '--', `${VST_TEMP_CONTAINER_DIR}/${name}`,
      ]);
      deletedFiles += 1;
    }
    if (hits.length === 0 && files.length === 0) emptyRounds += 1;
    else emptyRounds = 0;
    if (emptyRounds < 2) await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if ((await ownedIncidentHits(sensorName)).length !== 0) fail('owned_incidents_remain');
  if ((await ownedTempFiles(tempDir, sensorName)).length !== 0) fail('owned_temp_files_remain');
  return { deletedDocuments, deletedFiles };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const started = Date.now();
  const deadline = started + MAX_DURATION_MS;
  const fixture = path.resolve(args.fixture);
  const modulePath = path.resolve(args['playwright-module']);
  const chromiumPath = path.resolve(args.chromium);
  const output = path.resolve(args.output);
  const tempFilesDir = path.resolve(args['temp-files-dir']);
  const contractPath = path.resolve(args.contract);
  const fixtureRaw = await fs.readFile(fixture);
  const moduleRaw = await fs.readFile(modulePath);
  const contractRaw = await fs.readFile(contractPath);
  const contract = JSON.parse(contractRaw);
  if (
    contract?.package_id !== 'ui-alerts-rule-lifecycle-runtime-successor' ||
    contract?.capability_id !== 'runtime.ui.alerts-tab'
  ) {
    fail('contract_identity');
  }
  await fs.access(chromiumPath);
  await fs.access(tempFilesDir);
  if (chromiumPath !== '/snap/bin/chromium') fail('chromium_path');

  const sensorName = `thor-alert-ui-${args['run-id']}`;
  const alertType = `owned-${args['run-id']}`;
  const prompt = 'Detect a person visible in the live video.';
  const publishUrl = `${PUBLISH_ORIGIN}/${sensorName}`;
  const inputUrl = `rtsp://172.18.0.1:8554/${sensorName}`;
  const owned = [sensorName, alertType];
  let ownedSensorId = '';
  let ownedRuleId = '';
  let browser;
  let publisher;
  let workflowPassed = false;
  let incidentCleanup = { deletedDocuments: 0, deletedFiles: 0 };
  const mutations = [];
  const consoleErrors = [];
  const screenshots = {};
  const before = await snapshot();
  const beforeDigests = {
    rules: sha(canonical(before.rules)),
    sensors: unrelatedDigest(before.sensors, owned),
    sensor_streams: unrelatedDigest(before.sensorStreams, owned),
    live_streams: unrelatedDigest(before.liveStreams, owned),
    rtvlm_streams: unrelatedDigest(before.rtvlm, owned),
  };
  if (containsOwned(before, owned)) fail('owned_name_collision');
  if ((await ownedIncidentHits(sensorName)).length !== 0) fail('owned_incident_collision');
  if ((await ownedTempFiles(tempFilesDir, sensorName)).length !== 0) fail('owned_temp_collision');

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

    const imported = await import(pathToFileURL(modulePath).href);
    const chromium = imported.chromium ?? imported.default?.chromium;
    if (!chromium?.launch) fail('playwright_module');
    browser = await chromium.launch({
      executablePath: chromiumPath,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.setDefaultTimeout(UI_TIMEOUT_MS);
    page.setDefaultNavigationTimeout(UI_TIMEOUT_MS);
    page.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('request', request => {
      const method = request.method();
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const url = request.url();
        if (!isNumericLoopback(url)) fail('external_mutation');
        mutations.push({ method, path: new URL(url).pathname });
        if (new URL(url).pathname.includes('/generate')) fail('agent_generate_prohibited');
      }
    });

    await page.goto(UI_ORIGIN, { waitUntil: 'networkidle' });
    if ((await page.title()) !== 'THOR LOCAL VSS') fail('page_identity');
    await page.getByTestId('sidebar-tab-video-management').click();
    await page.getByRole('button', { name: '+ Add RTSP', exact: true }).click();
    await page.locator('#add-rtsp-url').fill(inputUrl);
    await page.locator('#add-rtsp-sensor-name').fill(sensorName);
    const addResponsePromise = page.waitForResponse(response =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/api/v1/rtsp-streams/add',
    );
    await page.getByRole('button', { name: 'Add RTSP', exact: true }).click();
    const addResponse = await addResponsePromise;
    const addBody = await addResponse.json();
    if (addResponse.status() !== 200 || addBody?.status !== 'success' || addBody?.name !== sensorName) {
      fail('ui_sensor_create');
    }
    ownedSensorId = addBody.sensorId;
    if (typeof ownedSensorId !== 'string' || !ownedSensorId) fail('owned_sensor_id');
    owned.push(ownedSensorId);
    await page.getByTestId('add-rtsp-dialog').waitFor({ state: 'detached' });
    await page.getByText(sensorName, { exact: true }).waitFor();

    const registered = await poll(snapshot, state =>
      state.sensorStreams.some(row => containsOwned(row, [ownedSensorId, sensorName])) &&
      state.rtvlm.some(row => containsOwned(row, [ownedSensorId, sensorName])),
      45_000,
    );
    const canonicalSensorRow = registered.sensorStreams.find(row =>
      containsOwned(row, [ownedSensorId, sensorName]),
    );
    const liveSensorRow = registered.liveStreams.find(row =>
      containsOwned(row, [ownedSensorId, sensorName]),
    );
    if (!canonicalSensorRow?.url || !liveSensorRow?.url || canonicalSensorRow.url === liveSensorRow.url) {
      fail('port_reconciliation_fixture');
    }

    await page.getByTestId('sidebar-tab-alerts').click();
    await page.getByTestId('alerts-component').waitFor();
    await page.getByTestId('alerts-view-create').click();
    await page.getByTestId('create-alert-rules-view').waitFor();
    await page.getByTestId('add-new-alert-button-inline').click();
    const sensorInput = page.getByTestId('realtime-alert-draft-sensor');
    await sensorInput.fill(sensorName);
    const option = page.getByRole('option', { name: sensorName, exact: true });
    await option.waitFor();
    await option.click();
    await page.getByPlaceholder('e.g. collision').fill(alertType);
    await page.getByPlaceholder('Detect any vehicle collisions').fill(prompt);

    const createResponsePromise = page.waitForResponse(response =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/alert-bridge/api/v1/realtime',
    );
    await page.getByTestId('realtime-alert-draft-save').click();
    const createResponse = await createResponsePromise;
    const createRequest = createResponse.request().postDataJSON();
    const createBody = await createResponse.json();
    if (![200, 201].includes(createResponse.status())) fail('ui_rule_create_http');
    ownedRuleId = createBody?.rule?.id ?? createBody?.id ?? '';
    if (typeof ownedRuleId !== 'string' || !ownedRuleId) fail('owned_rule_id');
    owned.push(ownedRuleId);
    if (
      createRequest?.sensor_name !== sensorName ||
      createRequest?.alert_type !== alertType ||
      createRequest?.prompt !== prompt ||
      createRequest?.live_stream_url !== canonicalSensorRow.url ||
      createRequest?.live_stream_url === liveSensorRow.url
    ) {
      fail('canonical_url_not_submitted');
    }

    const row = page.getByTestId('realtime-alert-row').filter({ hasText: alertType });
    await row.waitFor();
    await row.getByText(prompt, { exact: true }).waitFor();
    await row.getByText('active', { exact: true }).waitFor();
    await row.getByRole('button', { name: `Delete alert rule ${ownedRuleId}`, exact: true }).waitFor();
    const persisted = await jsonRequest(`${ALERTS_BASE}/realtime`);
    const persistedRule = alertRules(persisted.body).find(rule => rule.id === ownedRuleId);
    if (
      persisted.status !== 200 || persistedRule?.sensor_name !== sensorName ||
      persistedRule?.live_stream_url !== canonicalSensorRow.url || persistedRule?.status !== 'active'
    ) {
      fail('rule_persistence');
    }
    const alertShot = `/tmp/vss-alert-rule-${process.pid}.png`;
    await page.screenshot({ path: alertShot, fullPage: true });
    screenshots.alert_rule = sha(await fs.readFile(alertShot));
    await fs.unlink(alertShot);

    const deleteRulePromise = page.waitForResponse(response =>
      response.request().method() === 'DELETE' &&
      new URL(response.url()).pathname === `/alert-bridge/api/v1/realtime/${ownedRuleId}`,
    );
    await row.getByRole('button', { name: `Delete alert rule ${ownedRuleId}`, exact: true }).click();
    await row.getByRole('button', { name: `Confirm delete of alert rule ${ownedRuleId}`, exact: true }).click();
    const deleteRuleResponse = await deleteRulePromise;
    if (deleteRuleResponse.status() !== 200) fail('ui_rule_delete');
    await row.waitFor({ state: 'detached' });
    await poll(
      () => jsonRequest(`${ALERTS_BASE}/realtime`),
      result => result.status === 200 && !alertRules(result.body).some(rule => rule.id === ownedRuleId),
    );
    ownedRuleId = '';

    await page.getByTestId('sidebar-tab-video-management').click();
    const card = page.getByTestId('video-streams-grid').getByText(sensorName, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
    await card.locator('input[type="checkbox"]').check();
    await page.getByRole('button', { name: 'Delete Selected', exact: true }).click();
    const confirm = page.getByTestId('delete-confirm-dialog');
    await confirm.waitFor();
    const deleteSensorPromise = page.waitForResponse(response =>
      response.request().method() === 'DELETE' &&
      new URL(response.url()).pathname === `/api/v1/rtsp-streams/delete/${sensorName}`,
    );
    await page.getByTestId('delete-confirm-button').click();
    const deleteSensorResponse = await deleteSensorPromise;
    if (deleteSensorResponse.status() !== 200) fail('ui_sensor_delete');
    await confirm.waitFor({ state: 'detached' });
    await page.getByTestId('video-streams-grid').getByText(sensorName, { exact: true })
      .waitFor({ state: 'detached' });
    ownedSensorId = '';

    const videoShot = `/tmp/vss-alert-clean-${process.pid}.png`;
    await page.screenshot({ path: videoShot, fullPage: true });
    screenshots.video_management_cleanup = sha(await fs.readFile(videoShot));
    await fs.unlink(videoShot);
    workflowPassed = true;
  } finally {
    if (ownedRuleId) {
      await jsonRequest(`${ALERTS_BASE}/realtime/${encodeURIComponent(ownedRuleId)}`, {
        method: 'DELETE', timeout: 15_000,
      }).catch(() => null);
    }
    if (ownedSensorId) {
      await jsonRequest(`${AGENT_BASE}/rtsp-streams/delete/${encodeURIComponent(sensorName)}`, {
        method: 'DELETE', timeout: 30_000,
      }).catch(() => null);
    }
    if (browser) await browser.close().catch(() => null);
    await stopProcess(publisher);
    incidentCleanup = await cleanupOwnedIncidentArtifacts(tempFilesDir, sensorName);
  }

  const after = await poll(snapshot, state =>
    !containsOwned(state.rules, owned) &&
    !containsOwned(state.sensorStreams, owned) &&
    !containsOwned(state.liveStreams, owned) &&
    !containsOwned(state.rtvlm, owned),
    45_000,
  );
  const afterDigests = {
    rules: sha(canonical(after.rules)),
    sensors: unrelatedDigest(after.sensors, owned),
    sensor_streams: unrelatedDigest(after.sensorStreams, owned),
    live_streams: unrelatedDigest(after.liveStreams, owned),
    rtvlm_streams: unrelatedDigest(after.rtvlm, owned),
  };
  const cleanupExact = canonical(beforeDigests) === canonical(afterDigests);
  const allowedMutations = [
    ['POST', '/api/v1/rtsp-streams/add'],
    ['POST', '/alert-bridge/api/v1/realtime'],
    ['DELETE', '/alert-bridge/api/v1/realtime/'],
    ['DELETE', '/api/v1/rtsp-streams/delete/'],
  ];
  const mutationsAllowed = mutations.every(row => allowedMutations.some(([method, prefix]) =>
    row.method === method && row.path.startsWith(prefix),
  ));
  const duration = Date.now() - started;
  if (!workflowPassed || !cleanupExact || !mutationsAllowed || consoleErrors.length || duration > MAX_DURATION_MS) {
    fail('postconditions');
  }

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
      playwright_module_sha256: sha(moduleRaw),
      numeric_loopback_http_only: true,
    },
    browser: {
      title: 'THOR LOCAL VSS',
      console_error_count: consoleErrors.length,
      screenshot_sha256: screenshots,
    },
    lifecycle: {
      sensor_created_through_ui: true,
      rule_created_through_ui: true,
      rule_persisted_active_and_rendered: true,
      canonical_sensor_stream_url_used: true,
      differing_live_catalog_url_rejected: true,
      rule_deleted_through_ui: true,
      sensor_deleted_through_ui: true,
      mutation_sequence: mutations.map(row => `${row.method} ${row.path.replace(/\/[^/]+$/, '/<owned>')}`),
      agent_generate_request_count: 0,
    },
    cleanup: {
      exact_unrelated_state_restored: cleanupExact,
      before_sha256: beforeDigests,
      after_sha256: afterDigests,
      owned_absent_from_active_catalogs: true,
      publisher_stopped: publisher?.exitCode !== null,
      owned_incident_documents_deleted: incidentCleanup.deletedDocuments,
      owned_vst_temp_files_deleted: incidentCleanup.deletedFiles,
      owned_incident_artifacts_absent: true,
    },
  };
  await fs.writeFile(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o644 });
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
}

main().catch(error => {
  process.stderr.write(`${JSON.stringify({ status: 'failed', code: error?.code ?? error?.message ?? 'unknown' })}\n`);
  process.exitCode = 1;
});
