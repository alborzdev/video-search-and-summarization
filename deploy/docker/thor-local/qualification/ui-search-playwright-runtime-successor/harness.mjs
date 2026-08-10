#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { readFile, stat, unlink } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const ACK = 'I_ACK_UI_SEARCH_READ_ONLY_RUNTIME';
const PACKAGE_ID = 'thor-ui-search-playwright-runtime-successor-v1';
const MAX_DURATION_MS = 240000;
const sha = (value) => createHash('sha256').update(value).digest('hex');

function fail(message) {
  throw new Error(message);
}

function numericLoopbackOrigin(value) {
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) fail('UI origin must use HTTP(S)');
  if (parsed.hostname !== '127.0.0.1') fail('UI origin must use numeric loopback');
  if (parsed.username || parsed.password || parsed.search || parsed.hash) fail('UI origin must not contain credentials, query, or fragment');
  if (parsed.pathname !== '/' && parsed.pathname !== '') fail('UI origin must not contain a path');
  return parsed.origin;
}

function screenshotInfo(path) {
  return Promise.all([readFile(path), stat(path)]).then(([body, details]) => ({
    sha256: sha(body),
    bytes: details.size,
  }));
}

function safeDiagnostics(page) {
  const diagnostics = { console_hashes: [], page_error_hashes: [], response_rows: [], non_loopback_response_count: 0 };
  page.on('console', (event) => {
    if (['warning', 'error'].includes(event.type())) diagnostics.console_hashes.push(sha(`${event.type()}:${event.text()}`));
  });
  page.on('pageerror', (error) => diagnostics.page_error_hashes.push(sha(error.message)));
  page.on('response', (response) => {
    const parsed = new URL(response.url());
    if (!['http:', 'https:'].includes(parsed.protocol)) return;
    if (parsed.hostname !== '127.0.0.1') {
      diagnostics.non_loopback_response_count += 1;
      return;
    }
    diagnostics.response_rows.push({
      method: response.request().method(),
      path_sha256: sha(parsed.pathname),
      status: response.status(),
    });
  });
  return diagnostics;
}

function summarizeDiagnostics(value) {
  const statusCounts = {};
  for (const row of value.response_rows) statusCounts[String(row.status)] = (statusCounts[String(row.status)] || 0) + 1;
  return {
    console_hashes: [...new Set(value.console_hashes)].sort(),
    page_error_hashes: [...new Set(value.page_error_hashes)].sort(),
    response_status_counts: statusCounts,
    failing_response_hashes: value.response_rows.filter((row) => row.status >= 400).map((row) => sha(JSON.stringify(row))).sort(),
    non_loopback_response_count: value.non_loopback_response_count,
  };
}

async function openSearchPage(browser, uiOrigin, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const diagnostics = safeDiagnostics(page);
  await page.goto(`${uiOrigin}/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.getByTestId('sidebar-tab-search').click();
  await page.getByTestId('search-component').waitFor({ state: 'visible' });
  return { context, page, diagnostics };
}

async function directSearch(browser, uiOrigin, query, sensorName, screenshots) {
  let actions = 0;
  const { context, page, diagnostics } = await openSearchPage(browser, uiOrigin, { width: 1440, height: 900 });
  actions += 2;
  try {
    const closeChat = page.getByTestId('chat-sidebar-close');
    if (await closeChat.isVisible().catch(() => false)) {
      await closeChat.click();
      actions += 1;
    }
    const component = page.getByTestId('search-component');
    await page.getByTestId('search-filter-button').click();
    actions += 1;
    const dialog = page.getByTestId('search-filter-dialog');
    await dialog.waitFor({ state: 'visible' });
    const topKInput = page.getByTestId('search-filter-topk').locator('input');
    const similarityInput = page.getByTestId('search-filter-similarity').locator('input');
    const defaults = { top_k: Number(await topKInput.inputValue()), similarity: Number(await similarityInput.inputValue()) };
    await page.getByTestId('search-filter-video-sources').click();
    await page.getByText(sensorName, { exact: true }).last().click();
    await topKInput.fill('5');
    await page.getByTestId('search-filter-apply').click();
    actions += 4;
    await dialog.waitFor({ state: 'hidden' });
    const filterText = await page.getByTestId('search-filter-tags').innerText();
    await page.getByTestId('search-input').locator('input').fill(query);
    actions += 1;
    const responsePromise = page.waitForResponse((response) => {
      const parsed = new URL(response.url());
      return response.request().method() === 'POST' && parsed.hostname === '127.0.0.1' && parsed.pathname === '/api/v1/search';
    }, { timeout: 120000 });
    await page.getByTestId('search-button').click();
    actions += 1;
    const searchResponse = await responsePromise;
    const responseBody = await searchResponse.body();
    if (responseBody.length > 4194304) fail('direct Search response exceeded bound');
    const payload = JSON.parse(responseBody.toString('utf8'));
    await page.getByTestId('search-result-card').first().waitFor({ state: 'visible', timeout: 120000 });
    const cardCount = await page.getByTestId('search-result-card').count();
    const similarities = (await page.getByTestId('search-result-similarity').allTextContents()).map((item) => Number(item.trim()));
    const desktopOverflow = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
    await page.screenshot({ path: screenshots.direct });
    const desktopScreenshot = await screenshotInfo(screenshots.direct);

    await page.getByTestId('video-play-overlay').first().click();
    actions += 1;
    const modal = page.getByTestId('video-modal');
    await modal.waitFor({ state: 'visible' });
    const video = modal.locator('video');
    await video.waitFor({ state: 'attached' });
    await video.evaluate((node) => {
      node.currentTime = 0;
      node.pause();
      node.dispatchEvent(new Event('pause'));
    });
    const imageButton = page.getByTestId('image-search-perform-button');
    const imageButtonVisible = await imageButton.isVisible().catch(() => false);
    if (!imageButtonVisible) fail('Search by Image button is not visible');
    await imageButton.click();
    actions += 1;
    await page.getByTestId('search-by-image-overlay').waitFor({ state: 'visible', timeout: 30000 });
    const noBoxes = await page.getByTestId('search-by-image-hint-no-boxes').isVisible().catch(() => false);
    const selectHint = await page.getByTestId('search-by-image-hint-select').isVisible().catch(() => false);
    await page.screenshot({ path: screenshots.image });
    const imageScreenshot = await screenshotInfo(screenshots.image);
    await page.getByTestId('video-modal-close').click();
    actions += 1;

    await page.setViewportSize({ width: 390, height: 844 });
    actions += 1;
    await page.waitForTimeout(500);
    const mobileOverflow = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
    const mobileBox = await component.boundingBox();
    await page.screenshot({ path: screenshots.mobile });
    const mobileScreenshot = await screenshotInfo(screenshots.mobile);
    return {
      actions,
      query_sha256: sha(query),
      query_bytes: Buffer.byteLength(query),
      filter_defaults: defaults,
      filter_selected_source: filterText.includes(sensorName),
      filter_top_k_5: filterText.includes('5'),
      http_status: searchResponse.status(),
      response_sha256: sha(responseBody),
      result_count: Array.isArray(payload?.data) ? payload.data.length : -1,
      rendered_card_count: cardCount,
      similarities,
      playback_modal_opened: true,
      image_flow: { button_visible: imageButtonVisible, overlay_visible: true, no_boxes_hint: noBoxes, select_hint: selectHint },
      desktop: { viewport: { width: 1440, height: 900 }, overflow: desktopOverflow, screenshot: desktopScreenshot },
      mobile: { viewport: { width: 390, height: 844 }, component_width: mobileBox?.width || 0, overflow: mobileOverflow, screenshot: mobileScreenshot },
      diagnostics: summarizeDiagnostics(diagnostics),
    };
  } finally {
    await context.close();
  }
}

async function agentCritic(browser, uiOrigin, prompt, screenshotPath) {
  let actions = 0;
  const { context, page, diagnostics } = await openSearchPage(browser, uiOrigin, { width: 1440, height: 900 });
  actions += 2;
  try {
    const openChat = page.getByTestId('chat-sidebar-open');
    if (await openChat.isVisible().catch(() => false)) {
      await openChat.click();
      actions += 1;
    }
    const textarea = page.getByTestId('chat-textarea');
    await textarea.waitFor({ state: 'visible' });
    await textarea.fill(prompt);
    await textarea.press('Enter');
    actions += 2;
    await page.waitForFunction(() => {
      const cards = [...document.querySelectorAll('[data-testid="search-result-card"]')];
      return cards.some((card) => (card.textContent || '').includes('Confirmed'));
    }, undefined, { timeout: 180000 });
    const cards = page.getByTestId('search-result-card');
    const cardCount = await cards.count();
    const cardFacts = await cards.evaluateAll((nodes) => nodes.map((node) => {
      const text = node.textContent || '';
      const label = ['Confirmed', 'Unverified', 'Rejected'].find((value) => text.includes(value)) || null;
      const criteria = [...node.querySelectorAll('span')].map((span) => (span.textContent || '').trim()).filter((value) => /^[✓✗] /.test(value) && !/^(✓ Confirmed|✗ Rejected|\? Unverified)$/.test(value));
      const similarityNode = node.querySelector('[data-testid="search-result-similarity"]');
      return { label, criteria_true: criteria.filter((value) => value.startsWith('✓ ')).length, criteria_false: criteria.filter((value) => value.startsWith('✗ ')).length, similarity: Number((similarityNode?.textContent || '').trim()) };
    }));
    await page.screenshot({ path: screenshotPath });
    const screenshot = await screenshotInfo(screenshotPath);
    const overflow = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
    return {
      actions,
      prompt_sha256: sha(prompt),
      prompt_bytes: Buffer.byteLength(prompt),
      rendered_card_count: cardCount,
      cards: cardFacts,
      assistant_message_count: await page.getByTestId('chat-message-assistant').count(),
      input_enabled_after_completion: await textarea.isEnabled(),
      overflow,
      screenshot,
      diagnostics: summarizeDiagnostics(diagnostics),
    };
  } finally {
    await context.close();
  }
}

const mode = process.argv[2] || 'plan';
if (mode === 'plan') {
  console.log(JSON.stringify({ schema_version: 1, package_id: PACKAGE_ID, mode: 'plan', default_execution_enabled: false, acknowledgement_required: ACK, persistent_mutation: false, warehouse_sample_bundle: 'excluded' }, null, 2));
  process.exit(0);
}
if (mode !== 'run') fail('mode must be plan or run');
if (process.env.VSS_UI_SEARCH_ACK !== ACK) fail('exact acknowledgement is required');
const uiOrigin = numericLoopbackOrigin(process.env.VSS_UI_ORIGIN || '');
const playwrightEntry = process.env.VSS_PLAYWRIGHT_ENTRY || '';
const browserExecutable = process.env.VSS_BROWSER_EXECUTABLE || '';
const targetCommit = process.env.VSS_TARGET_COMMIT || '';
const query = process.env.VSS_SEARCH_QUERY || '';
const agentPrompt = process.env.VSS_SEARCH_AGENT_PROMPT || '';
const sensorName = process.env.VSS_SEARCH_SENSOR_NAME || '';
if (!/^[0-9a-f]{40}$/.test(targetCommit)) fail('exact target commit is required');
if (!playwrightEntry.startsWith('/')) fail('absolute Playwright entry path is required');
if (!browserExecutable.startsWith('/')) fail('absolute browser executable path is required');
if (query.length < 8 || agentPrompt.length < 8) fail('non-trivial query and agent prompt are required');
if (!/^[A-Za-z0-9_.-]{1,128}$/.test(sensorName)) fail('safe exact sensor name is required');

const started = Date.now();
const screenshots = {
  direct: `/tmp/vss-ui-search-direct-${process.pid}.png`,
  image: `/tmp/vss-ui-search-image-${process.pid}.png`,
  mobile: `/tmp/vss-ui-search-mobile-${process.pid}.png`,
  critic: `/tmp/vss-ui-search-critic-${process.pid}.png`,
};
let browser;
try {
  const { chromium } = await import(pathToFileURL(playwrightEntry).href);
  browser = await chromium.launch({ executablePath: browserExecutable, headless: true, args: ['--no-sandbox'] });
  const direct = await directSearch(browser, uiOrigin, query, sensorName, screenshots);
  const critic = await agentCritic(browser, uiOrigin, agentPrompt, screenshots.critic);
  const browserVersion = browser.version();
  await browser.close();
  browser = undefined;
  await Promise.all(Object.values(screenshots).map((path) => unlink(path)));
  const durationMs = Date.now() - started;
  const browserActions = direct.actions + critic.actions;
  const allDiagnostics = [direct.diagnostics, critic.diagnostics];
  const report = {
    schema_version: 1,
    package_id: PACKAGE_ID,
    status: 'partial_current_candidate',
    captured_at: new Date().toISOString(),
    target_commit: targetCommit,
    contract_sha256: sha(await readFile(new URL('./contract.json', import.meta.url))),
    harness_sha256: sha(await readFile(new URL('./harness.mjs', import.meta.url))),
    identity: {
      node_sha256: sha(await readFile(process.execPath)),
      playwright_entry_sha256: sha(await readFile(playwrightEntry)),
      browser_executable_sha256: sha(await readFile(browserExecutable)),
      browser_version_sha256: sha(browserVersion),
      ui_origin_sha256: sha(uiOrigin),
    },
    bounds: {
      duration_ms: durationMs,
      browser_actions: browserActions,
      loopback_browser_responses: allDiagnostics.reduce((total, row) => total + Object.values(row.response_status_counts).reduce((a, b) => a + b, 0), 0),
      max_duration_ms: MAX_DURATION_MS,
      max_browser_actions: 30,
      max_loopback_browser_responses: 500,
    },
    direct,
    critic,
    corpus_boundary: {
      vst_frame_rendered: direct.image_flow.overlay_visible,
      tracked_bbox_present: direct.image_flow.select_hint,
      no_bbox_observed: direct.image_flow.no_boxes_hint,
      selected_object_knn_exercised: false,
      blocker: 'tracked_object_bbox_corpus_absent',
    },
    cleanup: {
      mutation: 'none_read_only',
      isolated_browser_closed: true,
      persistent_resources_created: 0,
      persistent_resources_deleted: 0,
      temporary_screenshots_deleted_after_hashing: true,
    },
    warehouse_sample_bundle: 'excluded',
  };
  if (durationMs > MAX_DURATION_MS || browserActions > 30 || report.bounds.loopback_browser_responses > 500) fail('runtime bound exceeded');
  if (direct.http_status !== 200 || direct.result_count < 1 || direct.rendered_card_count < 1) fail('direct Search path did not render a result');
  if (direct.filter_defaults.top_k !== 10 || direct.filter_defaults.similarity !== -1) fail('Search filter defaults drifted');
  if (!direct.filter_selected_source || !direct.filter_top_k_5) fail('Search filter interaction failed');
  if (!direct.image_flow.no_boxes_hint || direct.image_flow.select_hint) fail('bbox corpus boundary was not reproduced');
  if (direct.mobile.overflow.document > direct.mobile.overflow.viewport || direct.mobile.overflow.body > direct.mobile.overflow.viewport) fail('mobile horizontal overflow');
  if (!critic.cards.some((card) => card.label === 'Confirmed')) fail('agent-mode critic did not render a confirmed card');
  if (!critic.input_enabled_after_completion) fail('chat input remained disabled');
  if (allDiagnostics.some((row) => row.non_loopback_response_count !== 0 || row.page_error_hashes.length !== 0 || row.failing_response_hashes.length !== 0)) {
    console.error(JSON.stringify({ status: 'failed', reason: 'unexpected_browser_diagnostic', diagnostics: allDiagnostics }, null, 2));
    fail('unexpected browser diagnostic');
  }
  console.log(JSON.stringify(report, null, 2));
} finally {
  if (browser) await browser.close().catch(() => undefined);
  await Promise.all(Object.values(screenshots).map((path) => unlink(path).catch(() => undefined)));
}
