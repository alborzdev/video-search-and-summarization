#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { readFile, stat, unlink } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const ACK = 'I_ACK_UI_SEARCH_CONTRACT_CURRENT_RUNTIME_READ_ONLY';
const PACKAGE_ID = 'thor-ui-search-contract-current-runtime-successor-v1';
const QUERY = 'verify critic ordering';
const QUERY_SHA256 = '7c8a2c020264937e1f1d6e6f40038f7a617e1db116edfc746a45fb5a1d9b52cf';
const MAX_DURATION_MS = 120000;
const MAX_ACTIONS = 18;
const MAX_RESPONSES = 250;
const MAX_SCREENSHOT_BYTES = 8388608;
const sha = (value) => createHash('sha256').update(value).digest('hex');

function fail(code) {
  throw new Error(code);
}

function numericLoopbackOrigin(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    fail('invalid_ui_origin');
  }
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1') fail('invalid_ui_origin');
  if (parsed.username || parsed.password || parsed.search || parsed.hash) fail('invalid_ui_origin');
  if (parsed.pathname !== '/' && parsed.pathname !== '') fail('invalid_ui_origin');
  return parsed.origin;
}

function isNumericLoopbackHttp(value) {
  try {
    const parsed = new URL(value);
    return ['http:', 'https:'].includes(parsed.protocol) && parsed.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

async function screenshotInfo(path) {
  const [body, details] = await Promise.all([readFile(path), stat(path)]);
  if (details.size < 1 || details.size > MAX_SCREENSHOT_BYTES || body.length !== details.size) {
    fail('screenshot_bound');
  }
  return { sha256: sha(body), bytes: details.size };
}

async function makeDiagnostics(page, context) {
  const value = {
    console_error_hashes: [],
    console_warning_hashes: [],
    page_error_hashes: [],
    request_failure_hashes: [],
    expected_audio_probe_abort_count: 0,
    response_rows: [],
    non_loopback_request_count: 0,
    non_loopback_response_count: 0,
    non_loopback_websocket_count: 0,
  };
  await context.route('**/*', async (route) => {
    const requestUrl = route.request().url();
    let parsed;
    try {
      parsed = new URL(requestUrl);
    } catch {
      await route.abort('blockedbyclient');
      return;
    }
    if (['http:', 'https:'].includes(parsed.protocol) && parsed.hostname !== '127.0.0.1') {
      value.non_loopback_request_count += 1;
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  page.on('console', (event) => {
    if (event.type() === 'error') value.console_error_hashes.push(sha(event.text()));
    if (event.type() === 'warning') value.console_warning_hashes.push(sha(event.text()));
  });
  page.on('pageerror', (error) => value.page_error_hashes.push(sha(error.message)));
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText || 'unknown';
    let path = 'invalid';
    try {
      path = new URL(request.url()).pathname;
    } catch {
      // Keep the fixed sentinel only.
    }
    if (
      request.method() === 'HEAD'
      && request.resourceType() === 'fetch'
      && path === '/audio/recording.wav'
      && failure === 'net::ERR_ABORTED'
    ) {
      value.expected_audio_probe_abort_count += 1;
      return;
    }
    value.request_failure_hashes.push(sha(`${request.method()}:${path}:${failure}`));
  });
  page.on('websocket', (socket) => {
    if (!isNumericLoopbackHttp(socket.url().replace(/^ws/, 'http'))) value.non_loopback_websocket_count += 1;
  });
  page.on('response', (response) => {
    let parsed;
    try {
      parsed = new URL(response.url());
    } catch {
      return;
    }
    if (!['http:', 'https:'].includes(parsed.protocol)) return;
    if (parsed.hostname !== '127.0.0.1') {
      value.non_loopback_response_count += 1;
      return;
    }
    value.response_rows.push({ status: response.status(), method: response.request().method(), path_sha256: sha(parsed.pathname) });
  });
  return value;
}

function summarizeDiagnostics(value, overlayCount) {
  const statusCounts = {};
  for (const row of value.response_rows) statusCounts[String(row.status)] = (statusCounts[String(row.status)] || 0) + 1;
  return {
    console_error_hashes: [...new Set(value.console_error_hashes)].sort(),
    console_warning_hashes: [...new Set(value.console_warning_hashes)].sort(),
    page_error_hashes: [...new Set(value.page_error_hashes)].sort(),
    request_failure_hashes: [...new Set(value.request_failure_hashes)].sort(),
    expected_audio_probe_abort_count: value.expected_audio_probe_abort_count,
    response_status_counts: statusCounts,
    failing_response_hashes: value.response_rows
      .filter((row) => row.status >= 400)
      .map((row) => sha(JSON.stringify(row)))
      .sort(),
    non_loopback_request_count: value.non_loopback_request_count,
    non_loopback_response_count: value.non_loopback_response_count,
    non_loopback_websocket_count: value.non_loopback_websocket_count,
    framework_error_overlay_count: overlayCount,
  };
}

async function overflow(page) {
  return page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
}

function assertNoOverflow(value) {
  if (value.document > value.viewport || value.body > value.viewport) fail('horizontal_overflow');
}

async function runFlow(browser, inputs, screenshotPath) {
  let actions = 0;
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    timezoneId: 'America/Toronto',
  });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const diagnostics = await makeDiagnostics(page, context);
  let requestRaw;
  let responseRaw;
  let fulfilledCount = 0;
  const pixel = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyIiBoZWlnaHQ9IjIiPjxyZWN0IHdpZHRoPSIyIiBoZWlnaHQ9IjIiIGZpbGw9IiM3NmI5MDAiLz48L3N2Zz4=';
  const base = {
    screenshot_url: pixel,
    description: '',
    start_time: '2026-08-10T23:45:10Z',
    end_time: '2026-08-10T23:45:11Z',
    sensor_id: 'contract-fixture',
    object_ids: [],
  };
  const rows = [
    { ...base, video_name: 'critic-rejected', similarity: 1, critic_result: { result: 'rejected', criteria_met: {} } },
    { ...base, video_name: 'critic-confirmed', similarity: -1, critic_result: { result: 'confirmed', criteria_met: {} } },
    { ...base, video_name: 'critic-unverified', similarity: 0.25, critic_result: { result: 'unverified', criteria_met: {} } },
  ];
  try {
    await page.goto(`${inputs.uiOrigin}/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForLoadState('networkidle', { timeout: 30000 });
    await page.getByTestId('sidebar-tab-search').click();
    actions += 2;
    const component = page.getByTestId('search-component');
    await component.waitFor({ state: 'visible' });
    await page.waitForLoadState('networkidle', { timeout: 30000 });
    const initialContent = await component.innerText();
    if (initialContent.trim().length < 8) fail('search_page_identity');

    const sourceControl = page.getByTestId('search-source-type');
    await sourceControl.waitFor({ state: 'visible' });
    const sourceDefaultText = await sourceControl.innerText();
    if (!sourceDefaultText.includes('Video File')) fail('source_default');
    await sourceControl.click();
    await page.getByText('RTSP', { exact: true }).last().click();
    await page.waitForFunction(() => document.querySelector('[data-testid="search-source-type"]')?.textContent?.includes('RTSP'));
    await sourceControl.click();
    await page.getByText('Video File', { exact: true }).last().click();
    await page.waitForFunction(() => document.querySelector('[data-testid="search-source-type"]')?.textContent?.includes('Video File'));
    actions += 4;

    await page.getByTestId('search-filter-button').click();
    actions += 1;
    const dialog = page.getByTestId('search-filter-dialog');
    await dialog.waitFor({ state: 'visible' });
    const topKInput = page.getByTestId('search-filter-topk').locator('input');
    const similarityInput = page.getByTestId('search-filter-similarity').locator('input');
    const defaults = {
      top_k: Number(await topKInput.inputValue()),
      similarity: Number(await similarityInput.inputValue()),
    };
    await topKInput.fill('0');
    await topKInput.blur();
    const topKMinimum = Number(await topKInput.inputValue());
    if (topKMinimum !== 1) fail('top_k_minimum');
    await topKInput.fill('1');
    await page.getByTestId('search-filter-apply').click();
    actions += 2;
    await dialog.waitFor({ state: 'hidden' });
    const filterText = await page.getByTestId('search-filter-tags').innerText();

    await page.route('**/api/v1/search', async (route) => {
      const request = route.request();
      let parsed;
      try {
        parsed = new URL(request.url());
      } catch {
        await route.abort('blockedbyclient');
        return;
      }
      if (request.method() !== 'POST' || parsed.hostname !== '127.0.0.1' || parsed.pathname !== '/api/v1/search') {
        await route.continue();
        return;
      }
      requestRaw = request.postDataBuffer();
      responseRaw = Buffer.from(JSON.stringify({ data: rows, search_messages: [] }), 'utf8');
      fulfilledCount += 1;
      await route.fulfill({ status: 200, contentType: 'application/json', body: responseRaw });
    });
    await page.getByTestId('search-input').locator('input').fill(QUERY);
    const responsePromise = page.waitForResponse((response) => {
      try {
        const parsed = new URL(response.url());
        return response.request().method() === 'POST'
          && parsed.hostname === '127.0.0.1'
          && parsed.pathname === '/api/v1/search';
      } catch {
        return false;
      }
    }, { timeout: 30000 });
    await page.getByTestId('search-button').click();
    actions += 2;
    const response = await responsePromise;
    await page.getByTestId('search-result-card').first().waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="search-result-card"]').length === 3);
    if (!requestRaw || !responseRaw || fulfilledCount !== 1 || response.status() !== 200) fail('fixture_transport');
    let requestBody;
    try {
      requestBody = JSON.parse(requestRaw.toString('utf8'));
    } catch {
      fail('request_json');
    }
    if (requestBody.query !== QUERY
        || Number(requestBody.top_k) !== 1
        || requestBody.agent_mode !== false
        || requestBody.source_type !== 'video_file'
        || !Array.isArray(requestBody.video_sources)
        || requestBody.video_sources.length !== 0
        || requestBody.timestamp_start !== null
        || requestBody.timestamp_end !== null) {
      fail('request_contract');
    }

    const cardTexts = await page.getByTestId('search-result-card').allInnerTexts();
    const criticOrder = cardTexts.map((text) => {
      if (text.includes('Confirmed')) return 'confirmed';
      if (text.includes('Unverified')) return 'unverified';
      if (text.includes('Rejected')) return 'rejected';
      return 'missing';
    });
    if (JSON.stringify(criticOrder) !== JSON.stringify(['confirmed', 'unverified', 'rejected'])) fail('critic_order');
    if (!cardTexts.every((text) => text.includes('23:45:10') && text.includes('23:45:11'))) fail('local_time');
    const similarities = (await page.getByTestId('search-result-similarity').allTextContents()).map((value) => Number(value.trim()));
    if (JSON.stringify(similarities) !== JSON.stringify([-1, 0.25, 1])) fail('similarity_range');
    const desktopOverflow = await overflow(page);
    assertNoOverflow(desktopOverflow);
    await page.screenshot({ path: screenshotPath });
    const screenshot = await screenshotInfo(screenshotPath);

    await page.setViewportSize({ width: 390, height: 844 });
    actions += 1;
    await page.waitForTimeout(300);
    const mobileOverflow = await overflow(page);
    assertNoOverflow(mobileOverflow);

    const overlayCount = await page.locator('[data-nextjs-dialog-overlay], nextjs-portal, #webpack-dev-server-client-overlay').count();
    const summarized = summarizeDiagnostics(diagnostics, overlayCount);
    const responseCount = Object.values(summarized.response_status_counts).reduce((a, b) => a + b, 0);
    if (actions < 10 || actions > MAX_ACTIONS || responseCount < 1 || responseCount > MAX_RESPONSES) fail('browser_bound');
    for (const key of ['console_error_hashes', 'console_warning_hashes', 'page_error_hashes', 'request_failure_hashes', 'failing_response_hashes']) {
      if (summarized[key].length !== 0) fail(`browser_${key}`);
    }
    if (summarized.expected_audio_probe_abort_count !== 1) fail('browser_audio_probe_abort_boundary');
    for (const key of ['non_loopback_request_count', 'non_loopback_response_count', 'non_loopback_websocket_count', 'framework_error_overlay_count']) {
      if (summarized[key] !== 0) fail(`browser_${key}`);
    }

    return {
      actions,
      page_identity: {
        initial_content_sha256: sha(initialContent),
        initial_content_bytes: Buffer.byteLength(initialContent),
        search_component_visible: true,
      },
      source_contract: {
        default_video_file: true,
        values: ['Video File', 'RTSP'],
        rtsp_and_video_file_round_trip: true,
      },
      filter_contract: {
        defaults,
        top_k_minimum: topKMinimum,
        top_k_minimum_selected: filterText.includes('1'),
      },
      request_contract: {
        query_sha256: sha(QUERY),
        query_bytes: Buffer.byteLength(QUERY),
        body_sha256: sha(requestRaw),
        top_k: Number(requestBody.top_k),
        source_type_video_file: true,
        agent_mode_false: true,
        empty_video_sources: true,
        null_time_range: true,
      },
      critic_contract: {
        fixture_response_sha256: sha(responseRaw),
        fixture_response_status: response.status(),
        fixture_response_intercepted_once: fulfilledCount === 1,
        input_order: ['rejected', 'confirmed', 'unverified'],
        rendered_order: criticOrder,
        rendered_card_count: cardTexts.length,
        similarities,
      },
      time_contract: {
        browser_time_zone_sha256: sha('America/Toronto'),
        literal_local_time_sha256: sha('23:45:10'),
        local_time_without_offset_conversion: true,
      },
      desktop: { overflow: desktopOverflow, screenshot },
      mobile: { overflow: mobileOverflow },
      diagnostics: summarized,
    };
  } finally {
    await context.close();
  }
}

const mode = process.argv[2] || 'plan';
if (mode === 'plan') {
  console.log(JSON.stringify({
    schema_version: 1,
    package_id: PACKAGE_ID,
    mode: 'plan',
    status: 'ready_inert',
    default_execution_enabled: false,
    authorization_required: true,
    persistent_mutations: 0,
    warehouse_sample_bundle: 'excluded',
  }));
  process.exit(0);
}
if (mode !== 'run') fail('invalid_mode');
if (process.env.VSS_UI_SEARCH_CONTRACT_ACK !== ACK) fail('authorization_required');

const inputs = {
  uiOrigin: numericLoopbackOrigin(process.env.VSS_UI_ORIGIN || ''),
  playwrightEntry: process.env.VSS_PLAYWRIGHT_ENTRY || '',
  browserExecutable: process.env.VSS_BROWSER_EXECUTABLE || '',
  targetCommit: process.env.VSS_TARGET_COMMIT || '',
};
if (!/^[0-9a-f]{40}$/.test(inputs.targetCommit)) fail('invalid_target_commit');
if (!inputs.playwrightEntry.startsWith('/') || !inputs.browserExecutable.startsWith('/')) fail('invalid_browser_path');
if (Buffer.byteLength(QUERY) !== 22 || sha(QUERY) !== QUERY_SHA256) fail('invalid_query_contract');

const started = Date.now();
const screenshotPath = `/tmp/vss-ui-search-contract-${process.pid}.png`;
let browser;
let browserClosed = false;
let screenshotDeleted = false;
try {
  const { chromium } = await import(pathToFileURL(inputs.playwrightEntry).href);
  browser = await chromium.launch({
    executablePath: inputs.browserExecutable,
    headless: true,
    args: ['--no-sandbox', '--no-proxy-server'],
  });
  const flow = await runFlow(browser, inputs, screenshotPath);
  const browserVersion = browser.version();
  await browser.close();
  browser = undefined;
  browserClosed = true;
  await unlink(screenshotPath);
  screenshotDeleted = true;
  const durationMs = Date.now() - started;
  const responseCount = Object.values(flow.diagnostics.response_status_counts).reduce((a, b) => a + b, 0);
  if (durationMs < 1 || durationMs > MAX_DURATION_MS || flow.actions > MAX_ACTIONS || responseCount > MAX_RESPONSES) {
    fail('runtime_bound');
  }
  console.log(JSON.stringify({
    schema_version: 1,
    package_id: PACKAGE_ID,
    status: 'passed_current_candidate',
    captured_at: new Date().toISOString(),
    target_commit: inputs.targetCommit,
    identity: {
      node_sha256: sha(await readFile(process.execPath)),
      playwright_entry_sha256: sha(await readFile(inputs.playwrightEntry)),
      browser_executable_sha256: sha(await readFile(inputs.browserExecutable)),
      browser_version_sha256: sha(browserVersion),
      ui_origin_sha256: sha(inputs.uiOrigin),
    },
    bounds: {
      duration_ms: durationMs,
      browser_actions: flow.actions,
      loopback_browser_responses: responseCount,
      max_duration_ms: MAX_DURATION_MS,
      max_browser_actions: MAX_ACTIONS,
      max_loopback_browser_responses: MAX_RESPONSES,
    },
    flow,
    cleanup: {
      isolated_browser_closed: browserClosed,
      temporary_screenshot_deleted_after_hashing: screenshotDeleted,
    },
    warehouse_sample_bundle: 'excluded',
  }));
} finally {
  if (browser) await browser.close().catch(() => undefined);
  await unlink(screenshotPath).catch(() => undefined);
}
