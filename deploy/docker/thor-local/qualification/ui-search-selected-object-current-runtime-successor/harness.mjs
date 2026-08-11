#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { readFile, stat, unlink } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const ACK = 'I_ACK_UI_SEARCH_SELECTED_OBJECT_CURRENT_RUNTIME_AND_EXACT_INDEX_CLEANUP';
const PACKAGE_ID = 'thor-ui-search-selected-object-current-runtime-successor-v1';
const MAX_DURATION_MS = 240000;
const MAX_ACTIONS = 24;
const MAX_RESPONSES = 700;
const MAX_RESPONSE_BYTES = 4194304;
const MAX_SCREENSHOT_BYTES = 16777216;
const sha = (value) => createHash('sha256').update(value).digest('hex');

function fail(code) {
  throw new Error(code);
}

function exactPlain(value, label, maximum = 128) {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum || !/^[A-Za-z0-9_.-]+$/.test(value)) {
    fail(`invalid_${label}`);
  }
  return value;
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

function parseJsonBody(raw, code) {
  if (!Buffer.isBuffer(raw) || raw.length < 1 || raw.length > MAX_RESPONSE_BYTES) fail(code);
  try {
    return JSON.parse(raw.toString('utf8'));
  } catch {
    fail(code);
  }
}

function postDataJson(request, code) {
  const raw = request.postDataBuffer();
  if (!raw || raw.length < 1 || raw.length > MAX_RESPONSE_BYTES) fail(code);
  return { value: parseJsonBody(raw, code), raw };
}

async function screenshotInfo(path) {
  const [body, details] = await Promise.all([readFile(path), stat(path)]);
  if (details.size < 1 || details.size > MAX_SCREENSHOT_BYTES || body.length !== details.size) fail('screenshot_bound');
  return { sha256: sha(body), bytes: details.size };
}

function isNumericLoopbackHttp(value) {
  try {
    const parsed = new URL(value);
    return ['http:', 'https:'].includes(parsed.protocol) && parsed.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

async function makeDiagnostics(page, context) {
  const diagnostics = {
    console_error_hashes: [],
    console_error_codes: [],
    console_warning_hashes: [],
    expected_abort_console_count: 0,
    page_error_hashes: [],
    request_failure_hashes: [],
    expected_abort_request_count: 0,
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
      diagnostics.non_loopback_request_count += 1;
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  page.on('console', (event) => {
    const digest = sha(`${event.type()}:${event.text()}`);
    if (event.type() === 'error' && event.text().includes('net::ERR_ABORTED')) {
      diagnostics.expected_abort_console_count += 1;
    } else if (event.type() === 'error') {
      diagnostics.console_error_hashes.push(digest);
      const networkCode = event.text().match(/net::([A-Z_]+)/)?.[1]?.toLowerCase();
      diagnostics.console_error_codes.push(
        networkCode && /^[a-z_]{1,48}$/.test(networkCode)
          ? networkCode
          : event.text().includes('Failed to load resource')
            ? 'resource_load'
            : event.text().includes('Video failed to load')
              ? 'video_load'
              : event.text().includes('Error fetching video URL')
                ? 'video_fetch'
                : event.text().includes('Error fetching search')
                  ? 'search_fetch'
                  : event.text().includes('Failed to fetch sensor list')
                    ? 'sensor_fetch'
            : event.text().includes('Search by Image')
              ? 'search_by_image'
              : event.text().includes('Search error')
                ? 'search'
                : 'other',
      );
    }
    if (event.type() === 'warning') diagnostics.console_warning_hashes.push(digest);
  });
  page.on('pageerror', (error) => diagnostics.page_error_hashes.push(sha(error.message)));
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText || 'unknown';
    if (failure === 'net::ERR_ABORTED') {
      diagnostics.expected_abort_request_count += 1;
      return;
    }
    let path = 'invalid';
    try {
      path = new URL(request.url()).pathname;
    } catch {
      // Retain only the fixed sentinel.
    }
    diagnostics.request_failure_hashes.push(sha(`${request.method()}:${path}:${failure}`));
  });
  page.on('websocket', (socket) => {
    if (!isNumericLoopbackHttp(socket.url().replace(/^ws/, 'http'))) diagnostics.non_loopback_websocket_count += 1;
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

function summarizeDiagnostics(value, frameworkOverlayCount) {
  const statusCounts = {};
  for (const row of value.response_rows) statusCounts[String(row.status)] = (statusCounts[String(row.status)] || 0) + 1;
  return {
    console_error_hashes: [...new Set(value.console_error_hashes)].sort(),
    console_warning_hashes: [...new Set(value.console_warning_hashes)].sort(),
    expected_abort_console_count: value.expected_abort_console_count,
    page_error_hashes: [...new Set(value.page_error_hashes)].sort(),
    request_failure_hashes: [...new Set(value.request_failure_hashes)].sort(),
    expected_abort_request_count: value.expected_abort_request_count,
    response_status_counts: statusCounts,
    failing_response_hashes: value.response_rows
      .filter((row) => row.status >= 400)
      .map((row) => sha(JSON.stringify(row)))
      .sort(),
    non_loopback_request_count: value.non_loopback_request_count,
    non_loopback_response_count: value.non_loopback_response_count,
    non_loopback_websocket_count: value.non_loopback_websocket_count,
    framework_error_overlay_count: frameworkOverlayCount,
  };
}

async function overflow(page) {
  return page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
}

function assertNoHorizontalOverflow(value) {
  if (value.document > value.viewport || value.body > value.viewport) fail('horizontal_overflow');
}

async function frameworkOverlayCount(page) {
  return page.locator('[data-nextjs-dialog-overlay], nextjs-portal, #webpack-dev-server-client-overlay').count();
}

async function waitForSearchResponse(page) {
  return page.waitForResponse((response) => {
    let parsed;
    try {
      parsed = new URL(response.url());
    } catch {
      return false;
    }
    return response.request().method() === 'POST'
      && parsed.hostname === '127.0.0.1'
      && parsed.pathname === '/api/v1/search';
  }, { timeout: 120000 });
}

async function runFlow(browser, inputs, screenshots) {
  let actions = 0;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const diagnostics = await makeDiagnostics(page, context);
  try {
    await page.goto(`${inputs.uiOrigin}/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.getByTestId('sidebar-tab-search').click();
    actions += 2;
    const component = page.getByTestId('search-component');
    await component.waitFor({ state: 'visible' });
    const title = await page.title();
    const initialContent = await component.innerText();
    if (initialContent.trim().length < 8) fail('search_page_identity');

    const closeChat = page.getByTestId('chat-sidebar-close');
    if (await closeChat.isVisible().catch(() => false)) {
      await closeChat.click();
      actions += 1;
    }

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
    await page.getByTestId('search-filter-video-sources').click();
    await page.getByText(inputs.sensorName, { exact: true }).last().click();
    await topKInput.fill('5');
    await page.getByTestId('search-filter-apply').click();
    actions += 4;
    await dialog.waitFor({ state: 'hidden' });
    const filterText = await page.getByTestId('search-filter-tags').innerText();

    await page.getByTestId('search-input').locator('input').fill(inputs.searchText);
    actions += 1;
    const directResponsePromise = waitForSearchResponse(page);
    await page.getByTestId('search-button').click();
    actions += 1;
    const directResponse = await directResponsePromise;
    const directRaw = await directResponse.body();
    const directPayload = parseJsonBody(directRaw, 'direct_response');
    const directRequest = postDataJson(directResponse.request(), 'direct_request');
    if (directResponse.status() !== 200) fail('direct_status');
    if (directRequest.value.agent_mode !== false) fail('direct_agent_mode');
    if (directRequest.value.source_type !== 'video_file') fail('direct_source_type');
    if (Number(directRequest.value.top_k) !== 5) fail('direct_top_k');
    if (directRequest.value.reference_object !== undefined) fail('direct_reference_boundary');
    if (!Array.isArray(directRequest.value.video_sources)) fail('direct_sources_shape');
    if (directRequest.value.video_sources.length !== 1) fail('direct_sources_count');
    if (directRequest.value.video_sources[0] !== inputs.sensorName) fail('direct_source_identity');
    if (!Array.isArray(directPayload?.data) || directPayload.data.length < 1 || !Array.isArray(directPayload.search_messages)) {
      fail('direct_response_semantics');
    }
    const initialResult = directPayload.data[0];
    const initialStart = Date.parse(initialResult?.start_time);
    const expectedStart = Date.parse(inputs.timelineStart);
    if (initialResult?.sensor_id !== inputs.sensorId
        || !Number.isFinite(initialStart)
        || !Number.isFinite(expectedStart)
        || Math.abs(initialStart - expectedStart) > 500) {
      fail('direct_result_fixture_alignment');
    }
    await page.getByTestId('search-result-card').first().waitFor({ state: 'visible', timeout: 120000 });
    const directCardCount = await page.getByTestId('search-result-card').count();
    const directOverflow = await overflow(page);
    await page.screenshot({ path: screenshots.direct });
    const directScreenshot = await screenshotInfo(screenshots.direct);

    await page.getByTestId('video-play-overlay').first().click();
    actions += 1;
    const modal = page.getByTestId('video-modal');
    await modal.waitFor({ state: 'visible' });
    const video = modal.locator('video');
    await video.waitFor({ state: 'attached' });
    const videoHandle = await video.elementHandle();
    if (!videoHandle) fail('video_element_missing');
    await page.waitForFunction(
      (node) => node.readyState >= 1 || node.error !== null,
      videoHandle,
      { timeout: 30000 },
    );
    const videoFacts = await video.evaluate((node) => ({
      readyState: node.readyState,
      duration: node.duration,
      errorCode: node.error?.code || 0,
    }));
    if (videoFacts.errorCode !== 0 || videoFacts.readyState < 1 || !Number.isFinite(videoFacts.duration) || videoFacts.duration <= 0) {
      fail('video_playback_not_ready');
    }
    await video.evaluate((node) => {
      node.currentTime = 0;
      node.pause();
      node.dispatchEvent(new Event('pause'));
    });
    actions += 1;
    const imageButton = page.getByTestId('image-search-perform-button');
    await imageButton.waitFor({ state: 'visible' });
    const picturePromise = page.waitForResponse((response) => {
      try {
        const parsed = new URL(response.url());
        return response.request().method() === 'GET'
          && parsed.hostname === '127.0.0.1'
          && parsed.pathname.includes('/v1/replay/stream/')
          && parsed.pathname.endsWith('/picture');
      } catch {
        return false;
      }
    }, { timeout: 60000 });
    const framesPromise = page.waitForResponse((response) => {
      try {
        const parsed = new URL(response.url());
        return response.request().method() === 'GET'
          && parsed.hostname === '127.0.0.1'
          && parsed.pathname.endsWith('/frames');
      } catch {
        return false;
      }
    }, { timeout: 60000 });
    await imageButton.click();
    actions += 1;
    const [pictureResponse, framesResponse] = await Promise.all([picturePromise, framesPromise]);
    const [pictureRaw, framesRaw] = await Promise.all([pictureResponse.body(), framesResponse.body()]);
    if (pictureResponse.status() !== 200 || framesResponse.status() !== 200) fail('frame_fetch_status');
    if (pictureRaw.length < 1 || pictureRaw.length > MAX_RESPONSE_BYTES) fail('picture_response_bound');
    const framesPayload = parseJsonBody(framesRaw, 'frames_response');
    const frameRows = Array.isArray(framesPayload) ? framesPayload : framesPayload?.frames;
    if (!Array.isArray(frameRows) || frameRows.length !== 1) fail('frames_response_semantics');

    const overlay = page.getByTestId('search-by-image-overlay');
    await overlay.waitFor({ state: 'visible', timeout: 60000 });
    await page.getByTestId('search-by-image-hint-select').waitFor({ state: 'visible' });
    const canvas = page.getByTestId('search-by-image-canvas-container');
    const frameWidth = Number(await canvas.getAttribute('data-frame-width'));
    const frameHeight = Number(await canvas.getAttribute('data-frame-height'));
    const objectCount = Number(await canvas.getAttribute('data-objects-count'));
    if (frameWidth !== inputs.frameWidth || frameHeight !== inputs.frameHeight || objectCount !== 2) {
      fail('canvas_fixture_semantics');
    }
    const stage = canvas.locator('.konvajs-content');
    await stage.waitFor({ state: 'visible' });
    const stageBox = await stage.boundingBox();
    if (!stageBox || stageBox.width <= 0 || stageBox.height <= 0) fail('canvas_bounds');
    const centerX = (inputs.referenceBbox[0] + inputs.referenceBbox[2]) / 2;
    const centerY = (inputs.referenceBbox[1] + inputs.referenceBbox[3]) / 2;
    await page.mouse.click(
      stageBox.x + (centerX / inputs.frameWidth) * stageBox.width,
      stageBox.y + (centerY / inputs.frameHeight) * stageBox.height,
    );
    actions += 1;
    const selectedObject = page.getByTestId('search-by-image-selected-object-id');
    await selectedObject.waitFor({ state: 'visible' });
    if ((await selectedObject.innerText()).trim() !== inputs.referenceId) fail('bbox_selection_identity');
    await page.screenshot({ path: screenshots.selection });
    const selectionScreenshot = await screenshotInfo(screenshots.selection);

    const selectedResponsePromise = waitForSearchResponse(page);
    await page.getByTestId('search-by-image-search-button').click();
    actions += 1;
    const selectedResponse = await selectedResponsePromise;
    const selectedRaw = await selectedResponse.body();
    const selectedPayload = parseJsonBody(selectedRaw, 'selected_response');
    const selectedRequest = postDataJson(selectedResponse.request(), 'selected_request');
    const reference = selectedRequest.value.reference_object;
    const requestTimestamp = Date.parse(reference?.timestamp);
    if (selectedResponse.status() !== 200) fail('selected_status');
    if (selectedRequest.value.agent_mode !== false) fail('selected_agent_mode');
    if (selectedRequest.value.source_type !== 'video_file') fail('selected_source_type');
    if (Number(selectedRequest.value.top_k) !== 5) fail('selected_top_k');
    if (reference?.object_id !== inputs.referenceId) fail('selected_reference_id');
    if (reference?.sensor_name !== inputs.sensorName) fail('selected_sensor_name');
    if (reference?.sensor_id !== inputs.sensorId) fail('selected_sensor_id');
    if (!Number.isFinite(requestTimestamp)) fail('selected_timestamp_shape');
    if (Math.abs(requestTimestamp - expectedStart) > 1) fail('selected_timestamp_alignment');
    if (!Array.isArray(selectedPayload?.data)
        || selectedPayload.data.length !== 1
        || !Array.isArray(selectedPayload.search_messages)
        || selectedPayload.search_messages.length !== 0) {
      fail('selected_response_semantics');
    }
    const selectedResult = selectedPayload.data[0];
    const selectedIds = Array.isArray(selectedResult?.object_ids) ? selectedResult.object_ids.map(String) : [];
    if (selectedIds.length !== 1) fail('selected_candidate_count');
    if (selectedIds[0] !== inputs.candidateId) fail('selected_candidate_identity');
    if (selectedIds.includes(inputs.referenceId)) fail('selected_seed_not_excluded');
    if (selectedResult?.video_name !== inputs.sensorName) fail('selected_video_name');
    await modal.waitFor({ state: 'hidden' });
    await overlay.waitFor({ state: 'hidden' });
    await page.getByTestId('search-result-card').first().waitFor({ state: 'visible' });
    await page.waitForTimeout(400);
    const selectedCardCount = await page.getByTestId('search-result-card').count();
    if (selectedCardCount !== 1) fail('selected_result_render');
    const selectedSimilarity = Number((await page.getByTestId('search-result-similarity').first().innerText()).trim());
    if (!Number.isFinite(selectedSimilarity) || selectedSimilarity < -1 || selectedSimilarity > 1) fail('selected_similarity');
    await page.screenshot({ path: screenshots.result });
    const resultScreenshot = await screenshotInfo(screenshots.result);

    await page.setViewportSize({ width: 390, height: 844 });
    actions += 1;
    await page.waitForTimeout(400);
    const mobileOverflow = await overflow(page);
    assertNoHorizontalOverflow(mobileOverflow);
    const mobileBox = await component.boundingBox();
    await page.screenshot({ path: screenshots.mobile });
    const mobileScreenshot = await screenshotInfo(screenshots.mobile);

    const overlayCount = await frameworkOverlayCount(page);
    const summarizedDiagnostics = summarizeDiagnostics(diagnostics, overlayCount);
    if (actions > MAX_ACTIONS) fail('browser_action_bound');
    if (Object.values(summarizedDiagnostics.response_status_counts).reduce((a, b) => a + b, 0) > MAX_RESPONSES) {
      fail('browser_response_bound');
    }
    if (summarizedDiagnostics.non_loopback_request_count !== 0) fail('browser_non_loopback_request');
    if (summarizedDiagnostics.non_loopback_response_count !== 0) fail('browser_non_loopback_response');
    if (summarizedDiagnostics.non_loopback_websocket_count !== 0) fail('browser_non_loopback_websocket');
    if (summarizedDiagnostics.failing_response_hashes.length !== 0) fail('browser_failing_response');
    if (summarizedDiagnostics.request_failure_hashes.length !== 0) fail('browser_request_failure');
    if (summarizedDiagnostics.page_error_hashes.length !== 0) fail('browser_page_error');
    if (summarizedDiagnostics.console_error_hashes.length !== 0) {
      fail(`browser_console_${diagnostics.console_error_codes[0] || 'other'}`);
    }
    if (summarizedDiagnostics.framework_error_overlay_count !== 0) fail('browser_framework_overlay');

    return {
      actions,
      page_identity: {
        title_sha256: sha(title),
        initial_content_sha256: sha(initialContent),
        initial_content_bytes: Buffer.byteLength(initialContent),
        search_component_visible: true,
      },
      direct_search: {
        query_sha256: sha(inputs.searchText),
        query_bytes: Buffer.byteLength(inputs.searchText),
        filter_defaults: defaults,
        exact_local_source_selected: filterText.includes(inputs.sensorName),
        top_k_5_selected: filterText.includes('5'),
        http_status: directResponse.status(),
        request_body_sha256: sha(directRequest.raw),
        response_sha256: sha(directRaw),
        result_count: directPayload.data.length,
        rendered_card_count: directCardCount,
        result_aligned_to_fixture_start: true,
        playback_modal_opened: true,
        playback_metadata_loaded: true,
        playback_duration_positive: true,
        desktop_overflow: directOverflow,
        screenshot: directScreenshot,
      },
      frame_selection: {
        picture_http_status: pictureResponse.status(),
        picture_response_sha256: sha(pictureRaw),
        picture_response_bytes: pictureRaw.length,
        frames_http_status: framesResponse.status(),
        frames_response_sha256: sha(framesRaw),
        frames_response_bytes: framesRaw.length,
        frame_count: frameRows.length,
        frame_width: frameWidth,
        frame_height: frameHeight,
        object_count: objectCount,
        select_hint_visible: true,
        reference_bbox_clicked: true,
        selected_object_id_sha256: sha(inputs.referenceId),
        screenshot: selectionScreenshot,
      },
      selected_search: {
        http_status: selectedResponse.status(),
        request_body_sha256: sha(selectedRequest.raw),
        response_sha256: sha(selectedRaw),
        exact_composite_identity: true,
        agent_mode_false: true,
        source_type_video_file: true,
        result_count: selectedPayload.data.length,
        message_count: selectedPayload.search_messages.length,
        candidate_object_id_sha256: sha(inputs.candidateId),
        seed_object_id_sha256: sha(inputs.referenceId),
        seed_excluded: true,
        candidate_only: true,
        result_card_rerendered: true,
        rendered_card_count: selectedCardCount,
        human_facing_source_name_preserved: true,
        similarity: selectedSimilarity,
        modal_closed: true,
        overlay_closed: true,
        screenshot: resultScreenshot,
      },
      mobile: {
        viewport: { width: 390, height: 844 },
        component_width: mobileBox?.width || 0,
        overflow: mobileOverflow,
        screenshot: mobileScreenshot,
      },
      diagnostics: summarizedDiagnostics,
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
    acknowledgement_required: true,
    persistent_mutation: false,
    warehouse_sample_bundle: 'excluded',
  }, null, 2));
  process.exit(0);
}
if (mode !== 'run') fail('invalid_mode');
if (process.env.VSS_UI_SEARCH_ACK !== ACK) fail('authorization_required');

const inputs = {
  uiOrigin: numericLoopbackOrigin(process.env.VSS_UI_ORIGIN || ''),
  playwrightEntry: process.env.VSS_PLAYWRIGHT_ENTRY || '',
  browserExecutable: process.env.VSS_BROWSER_EXECUTABLE || '',
  targetCommit: process.env.VSS_TARGET_COMMIT || '',
  searchText: process.env.VSS_SEARCH_TEXT || '',
  sensorName: exactPlain(process.env.VSS_SENSOR_NAME || '', 'sensor_name'),
  sensorId: exactPlain(process.env.VSS_SENSOR_ID || '', 'sensor_id'),
  referenceId: exactPlain(process.env.VSS_REFERENCE_ID || '', 'reference_id'),
  candidateId: exactPlain(process.env.VSS_CANDIDATE_ID || '', 'candidate_id'),
  timelineStart: process.env.VSS_TIMELINE_START || '',
  referenceBbox: (process.env.VSS_REFERENCE_BBOX || '').split(',').map(Number),
  frameWidth: Number(process.env.VSS_FRAME_WIDTH || ''),
  frameHeight: Number(process.env.VSS_FRAME_HEIGHT || ''),
};
if (!/^[0-9a-f]{40}$/.test(inputs.targetCommit)) fail('invalid_target_commit');
if (!inputs.playwrightEntry.startsWith('/') || !inputs.browserExecutable.startsWith('/')) fail('invalid_browser_path');
if (Buffer.byteLength(inputs.searchText) !== 22 || sha(inputs.searchText) !== '2d7f96d5595fa7bcfb243f81f7eba8fc30d7817174f0d38deaeaeb447cb1d635') {
  fail('invalid_search_contract');
}
if (!Number.isFinite(Date.parse(inputs.timelineStart))) fail('invalid_timeline_start');
if (inputs.referenceBbox.length !== 4 || inputs.referenceBbox.some((value) => !Number.isFinite(value))) fail('invalid_reference_bbox');
if (!Number.isInteger(inputs.frameWidth) || !Number.isInteger(inputs.frameHeight) || inputs.frameWidth < 1 || inputs.frameHeight < 1) {
  fail('invalid_frame_dimensions');
}

const started = Date.now();
const screenshots = {
  direct: `/tmp/vss-ui-search-direct-${process.pid}.png`,
  selection: `/tmp/vss-ui-search-selection-${process.pid}.png`,
  result: `/tmp/vss-ui-search-selected-result-${process.pid}.png`,
  mobile: `/tmp/vss-ui-search-selected-mobile-${process.pid}.png`,
};
let browser;
let browserClosed = false;
let screenshotsDeleted = false;
try {
  const { chromium } = await import(pathToFileURL(inputs.playwrightEntry).href);
  browser = await chromium.launch({
    executablePath: inputs.browserExecutable,
    headless: true,
    args: ['--no-sandbox', '--no-proxy-server'],
  });
  const flow = await runFlow(browser, inputs, screenshots);
  const browserVersion = browser.version();
  await browser.close();
  browser = undefined;
  browserClosed = true;
  await Promise.all(Object.values(screenshots).map((path) => unlink(path)));
  screenshotsDeleted = true;
  const durationMs = Date.now() - started;
  const responseCount = Object.values(flow.diagnostics.response_status_counts).reduce((a, b) => a + b, 0);
  if (durationMs < 1 || durationMs > MAX_DURATION_MS || flow.actions > MAX_ACTIONS || responseCount > MAX_RESPONSES) {
    fail('runtime_bound');
  }
  const report = {
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
      sensor_name_sha256: sha(inputs.sensorName),
      sensor_id_sha256: sha(inputs.sensorId),
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
      temporary_screenshots_deleted_after_hashing: screenshotsDeleted,
    },
    warehouse_sample_bundle: 'excluded',
  };
  console.log(JSON.stringify(report));
} finally {
  if (browser) await browser.close().catch(() => undefined);
  await Promise.all(Object.values(screenshots).map((path) => unlink(path).catch(() => undefined)));
}
