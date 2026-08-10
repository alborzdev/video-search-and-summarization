#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, stat, unlink } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const HERE = new URL('.', import.meta.url);
const CONTRACT = JSON.parse(await readFile(new URL('./contract.json', HERE), 'utf8'));
const ACK = CONTRACT.authorization.acknowledgement;
const PACKAGE_ID = CONTRACT.package_id;
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

function endpointSummary(value, expectedProtocol) {
  const parsed = new URL(value);
  if (parsed.hostname !== '127.0.0.1' || parsed.protocol !== expectedProtocol) {
    fail(`configured endpoint is not ${expectedProtocol} numeric loopback`);
  }
  return {
    scope: 'numeric_loopback',
    protocol: expectedProtocol.slice(0, -1),
    sha256: sha(value),
    bytes: Buffer.byteLength(value),
  };
}

function parseRuntimeEnv(body) {
  if (Buffer.byteLength(body) > CONTRACT.bounds.max_runtime_env_bytes) fail('runtime environment response exceeded bound');
  const match = body.match(/^window\.__ENV\s*=\s*(\{.*\});?\s*$/s);
  if (!match) fail('runtime environment response shape drifted');
  const value = JSON.parse(match[1]);
  if (!value || Array.isArray(value) || typeof value !== 'object') fail('runtime environment root must be an object');
  return value;
}

function containerState(name) {
  const format = [
    '{{.Id}}', '{{.Image}}', '{{.Config.Image}}', '{{.State.Running}}',
    '{{.State.StartedAt}}', '{{.RestartCount}}', '{{.State.OOMKilled}}',
  ].join('|');
  const raw = execFileSync('docker', ['inspect', name, '--format', format], {
    encoding: 'utf8',
    timeout: 15000,
    maxBuffer: 65536,
  }).trim();
  const state = JSON.parse(execFileSync('docker', ['inspect', name, '--format', '{{json .State}}'], {
    encoding: 'utf8',
    timeout: 15000,
    maxBuffer: 65536,
  }).trim());
  const [containerId, imageId, configuredImage, running, startedAt, restartCount, oomKilled] = raw.split('|');
  if (!containerId || !imageId || !configuredImage || !startedAt) fail(`container identity incomplete for ${name}`);
  return {
    container_id_sha256: sha(containerId),
    image_id: imageId,
    configured_image: configuredImage,
    running: running === 'true',
    health: state.Health?.Status ?? 'none',
    started_at_sha256: sha(startedAt),
    restart_count: Number(restartCount),
    oom_killed: oomKilled === 'true',
  };
}

function relatedRuntimeState() {
  return Object.fromEntries(Object.values(CONTRACT.runtime).map((row) => [row.container, containerState(row.container)]));
}

function safeDiagnostics(page, options = {}) {
  const state = {
    console_hashes: [],
    page_error_hashes: [],
    synthetic_profile_hydration_recovery_counts: {},
    response_rows: [],
    non_loopback_response_count: 0,
  };
  page.on('console', (event) => {
    if (['warning', 'error'].includes(event.type())) state.console_hashes.push(sha(`${event.type()}:${event.text()}`));
  });
  page.on('pageerror', (error) => {
    const hydrationRecovery = error.message.match(/^Minified React error #(418|423);/);
    if (
      options.allowSyntheticProfileHydrationRecovery &&
      hydrationRecovery &&
      CONTRACT.runtime_boundary.synthetic_profile_override_expected_react_hydration_recovery_codes.includes(hydrationRecovery[1])
    ) {
      const code = hydrationRecovery[1];
      state.synthetic_profile_hydration_recovery_counts[code] =
        (state.synthetic_profile_hydration_recovery_counts[code] || 0) + 1;
      return;
    }
    state.page_error_hashes.push(sha(error.message));
  });
  page.on('response', (response) => {
    const parsed = new URL(response.url());
    if (!['http:', 'https:'].includes(parsed.protocol)) return;
    if (parsed.hostname !== '127.0.0.1') {
      state.non_loopback_response_count += 1;
      return;
    }
    state.response_rows.push({
      method: response.request().method(),
      path_sha256: sha(parsed.pathname),
      status: response.status(),
    });
  });
  return state;
}

function summarizeDiagnostics(state) {
  const responseStatusCounts = {};
  for (const row of state.response_rows) responseStatusCounts[String(row.status)] = (responseStatusCounts[String(row.status)] || 0) + 1;
  return {
    console_hashes: [...new Set(state.console_hashes)].sort(),
    page_error_hashes: [...new Set(state.page_error_hashes)].sort(),
    synthetic_profile_hydration_recovery_counts: state.synthetic_profile_hydration_recovery_counts,
    response_status_counts: responseStatusCounts,
    failing_response_hashes: state.response_rows.filter((row) => row.status >= 400).map((row) => sha(JSON.stringify(row))).sort(),
    non_loopback_response_count: state.non_loopback_response_count,
    loopback_response_count: state.response_rows.length,
  };
}

async function screenshotInfo(page, path) {
  await page.screenshot({ path });
  const [body, details] = await Promise.all([readFile(path), stat(path)]);
  return { sha256: sha(body), bytes: details.size };
}

async function openPage(browser, uiOrigin, viewport, options = {}) {
  const context = await browser.newContext({ viewport, permissions: ['clipboard-read', 'clipboard-write'] });
  if (options.captureWebSocketSends) {
    await context.addInitScript(() => {
      window.__vssCapturedWebSocketSends = [];
      WebSocket.prototype.send = function captureOnly(data) {
        window.__vssCapturedWebSocketSends.push(String(data));
      };
    });
  }
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const diagnostics = safeDiagnostics(page, options);
  return { context, page, diagnostics };
}

async function gotoUi(page, uiOrigin) {
  await page.goto(`${uiOrigin}/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.getByTestId('sidebar-nav').waitFor({ state: 'visible' });
  await page.waitForTimeout(750);
}

async function firstVisible(locator) {
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = locator.nth(index);
    if (await candidate.isVisible().catch(() => false)) return candidate;
  }
  fail('no visible matching locator');
}

async function measureSidebar(separator) {
  return separator.evaluate((node) => {
    const panel = node.parentElement.getBoundingClientRect();
    const outer = node.parentElement.parentElement.getBoundingClientRect();
    return {
      panel_width: panel.width,
      outer_width: outer.width,
      ratio: panel.width / outer.width,
      panel_x: panel.x,
    };
  });
}

async function dragSidebar(page, separator, targetX) {
  const box = await separator.boundingBox();
  if (!box) fail('resize separator has no bounding box');
  await page.mouse.move(box.x + 2, 200);
  await page.mouse.down();
  await page.mouse.move(targetX, 200, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(150);
}

async function runCurrentProfile(browser, uiOrigin, screenshotPath) {
  let actions = 0;
  const { context, page, diagnostics } = await openPage(browser, uiOrigin, { width: 1440, height: 900 });
  try {
    await gotoUi(page, uiOrigin);
    const envResponse = await context.request.get(`${uiOrigin}/__ENV.js`);
    if (envResponse.status() !== 200) fail('runtime environment request failed');
    const envBody = await envResponse.text();
    const runtimeEnv = parseRuntimeEnv(envBody);
    const requiredFlags = {
      NEXT_PUBLIC_ENABLE_CHAT_TAB: 'false',
      NEXT_PUBLIC_ENABLE_CHAT_SIDEBAR: 'true',
      NEXT_PUBLIC_CHAT_SIDEBAR_OPEN_DEFAULT: 'true',
      NEXT_PUBLIC_ENABLE_SEARCH_TAB: 'true',
      NEXT_PUBLIC_ENABLE_ALERTS_TAB: 'true',
      NEXT_PUBLIC_ENABLE_DASHBOARD_TAB: 'true',
      NEXT_PUBLIC_ENABLE_VIDEO_MANAGEMENT_TAB: 'true',
      NEXT_PUBLIC_ENABLE_MAP_TAB: 'false',
      NEXT_PUBLIC_SIDEBAR_CHAT_WEB_SOCKET_DEFAULT_ON: 'true',
    };
    for (const [key, expected] of Object.entries(requiredFlags)) {
      if (runtimeEnv[key] !== expected) fail(`current profile flag drifted: ${key}`);
    }

    const tabs = await page.locator('[data-testid^="sidebar-tab-"]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-testid')));
    const expectedTabs = ['sidebar-tab-search', 'sidebar-tab-alerts', 'sidebar-tab-dashboard', 'sidebar-tab-video-management'];
    if (JSON.stringify(tabs) !== JSON.stringify(expectedTabs)) fail('current visible tab set drifted');

    const themeButton = page.locator('button[title^="Switch to "]');
    const themeBefore = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    const titleBefore = await themeButton.getAttribute('title');
    await themeButton.click(); actions += 1;
    await page.waitForFunction(() => !document.documentElement.classList.contains('dark'));
    const themeLight = !await page.evaluate(() => document.documentElement.classList.contains('dark'));
    const titleLight = await themeButton.getAttribute('title');
    await themeButton.click(); actions += 1;
    await page.waitForFunction(() => document.documentElement.classList.contains('dark'));
    const themeRestored = await page.evaluate(() => document.documentElement.classList.contains('dark'));

    const separator = page.getByRole('separator', { name: 'Resize Chat sidebar' });
    const resizeInitial = await measureSidebar(separator);
    await dragSidebar(page, separator, 100); actions += 1;
    const resizeMaximum = await measureSidebar(separator);
    await dragSidebar(page, separator, 1400); actions += 1;
    const resizeMinimum = await measureSidebar(separator);
    const storedWidth = Number(await page.evaluate(() => sessionStorage.getItem('nvMetropolis_chatSidebarWidth')));

    await page.getByTestId('chat-sidebar-close').click(); actions += 1;
    await page.getByTestId('chat-sidebar-open').waitFor({ state: 'visible' });
    const collapsedStored = await page.evaluate(() => sessionStorage.getItem('nvMetropolis_chatSidebarOpen'));
    await page.getByTestId('chat-sidebar-open').click(); actions += 1;
    await page.getByTestId('chat-sidebar-close').waitFor({ state: 'visible' });
    const openedStored = await page.evaluate(() => sessionStorage.getItem('nvMetropolis_chatSidebarOpen'));

    const uploadInputs = page.locator('input[type="file"][accept*=".mp4"]');
    const uploadInputCount = await uploadInputs.count();
    const uploadAccepts = await uploadInputs.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('accept')));
    const dropZoneTextVisible = await page.getByTestId('upload-drop-zone-text').isVisible().catch(() => false);

    const chatMenu = page.locator('button:has(svg path[d="M4 6l16 0"])').last();
    await chatMenu.click(); actions += 1;
    await page.getByRole('button', { name: 'New chat', exact: true }).waitFor({ state: 'visible' });
    const folderButton = page.locator('button:has(svg.tabler-icon-folder-plus)');
    await folderButton.click(); actions += 1;
    const newFolderCount = await page.getByText('New folder', { exact: true }).count();
    await page.getByRole('button', { name: 'Settings', exact: true }).click(); actions += 1;
    await page.getByRole('heading', { name: 'Settings', exact: true }).waitFor({ state: 'visible' });
    const settingsLabels = await page.locator('label:visible').allTextContents();
    const settingsFieldAfterLabel = (label, tag) => page
      .locator('label', { hasText: label })
      .locator(`xpath=following-sibling::${tag}[1]`);
    const httpValue = await settingsFieldAfterLabel('HTTP URL for Chat Completion', 'input').inputValue();
    const websocketValue = await settingsFieldAfterLabel('WebSocket URL for Chat Completion', 'input').inputValue();
    const schemaSelect = settingsFieldAfterLabel('WebSocket Schema', 'select');
    const schemaOptions = await schemaSelect.locator('option').allTextContents();
    const selectedSchema = await schemaSelect.inputValue();
    const intermediate = page.locator('#enableIntermediateSteps');
    const intermediateInitiallyEnabled = await intermediate.isChecked();
    await intermediate.click(); actions += 1;
    const intermediateDisabled = !await intermediate.isChecked();
    await intermediate.click(); actions += 1;
    const intermediateRestored = await intermediate.isChecked();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click(); actions += 1;
    const folderPersistedCount = await page.getByText('New folder', { exact: true }).count();
    await page.locator('button:has(svg path[d="M4 6l16 0"])').last().click(); actions += 1;

    await page.getByTestId('chat-sidebar-close').click(); actions += 1;
    await page.getByTestId('sidebar-tab-video-management').click(); actions += 1;
    const plusChat = page.getByText('+ Chat', { exact: true });
    const visiblePlusChat = await firstVisible(plusChat);
    const visiblePlusChatCount = await plusChat.evaluateAll((nodes) => nodes.filter((node) => {
      const style = window.getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
    }).length);
    await visiblePlusChat.click(); actions += 1;
    const highlightedLabel = await page.getByTestId('chat-sidebar-open').getAttribute('aria-label');
    const addedStateCount = await page.getByText('Added', { exact: true }).count();
    await page.getByTestId('chat-sidebar-open').click(); actions += 1;
    const chipButtons = page.locator('button[aria-label^="Remove "]');
    const chipCount = await chipButtons.count();
    const screenshot = await screenshotInfo(page, screenshotPath);
    if (chipCount !== 1) fail('context chip did not render exactly once');
    await chipButtons.first().click(); actions += 1;
    const chipCountAfterRemove = await chipButtons.count();
    await page.getByTestId('chat-sidebar-close').click(); actions += 1;
    const clearedLabel = await page.getByTestId('chat-sidebar-open').getAttribute('aria-label');

    return {
      actions,
      runtime_env: {
        sha256: sha(envBody),
        bytes: Buffer.byteLength(envBody),
        required_flags_match: true,
        flag_count: Object.keys(runtimeEnv).length,
      },
      tabs: { visible: tabs, legacy_chat_absent: !tabs.includes('sidebar-tab-chat'), map_absent: !tabs.includes('sidebar-tab-map') },
      theme: {
        initial_dark: themeBefore,
        switch_to_light_title: titleBefore === 'Switch to light theme',
        light_rendered: themeLight,
        switch_to_dark_title: titleLight === 'Switch to dark theme',
        dark_restored: themeRestored,
      },
      sidebar: {
        initial: resizeInitial,
        maximum: resizeMaximum,
        minimum: resizeMinimum,
        stored_width: storedWidth,
        collapsed_storage_false: collapsedStored === 'false',
        opened_storage_true: openedStored === 'true',
      },
      uploads: {
        input_count: uploadInputCount,
        accept_values: [...new Set(uploadAccepts)].sort(),
        mp4: uploadAccepts.length > 0 && uploadAccepts.every((value) => value?.includes('.mp4') || value?.includes('video/mp4')),
        mkv: uploadAccepts.length > 0 && uploadAccepts.every((value) => value?.includes('.mkv') || value?.includes('video/x-matroska')),
        mime_aliases_present: uploadAccepts.some((value) => value?.includes('video/mp4') && value.includes('video/x-matroska')),
        adjacent_avi_absent: uploadAccepts.every((value) => !value?.includes('.avi')),
        drop_zone_text_visible: dropZoneTextVisible,
      },
      history: {
        new_chat_visible: true,
        folder_control_visible: true,
        new_folder_count: newFolderCount,
        folder_persisted_count: folderPersistedCount,
      },
      settings: {
        required_labels_present: [
          'HTTP URL for Chat Completion', 'WebSocket URL for Chat Completion',
          'WebSocket Schema', 'Enable Intermediate Steps',
        ].every((label) => settingsLabels.some((value) => value.includes(label))),
        http_endpoint: endpointSummary(httpValue, 'http:'),
        websocket_endpoint: endpointSummary(websocketValue, 'ws:'),
        schema_options: schemaOptions,
        selected_schema: selectedSchema,
        intermediate_initially_enabled: intermediateInitiallyEnabled,
        intermediate_disabled: intermediateDisabled,
        intermediate_restored: intermediateRestored,
      },
      context_action: {
        visible_plus_chat_count: visiblePlusChatCount,
        added_state_count: addedStateCount,
        highlighted_when_collapsed: Boolean(highlightedLabel?.includes('new context or message')),
        chip_count: chipCount,
        chip_count_after_remove: chipCountAfterRemove,
        highlight_cleared_after_open: !clearedLabel?.includes('new context or message'),
      },
      screenshot,
      diagnostics: summarizeDiagnostics(diagnostics),
    };
  } finally {
    await context.close();
  }
}

async function runProfileBoundary(browser, uiOrigin, screenshotPath) {
  let actions = 0;
  const { context, page, diagnostics } = await openPage(
    browser,
    uiOrigin,
    { width: 1440, height: 900 },
    { allowSyntheticProfileHydrationRecovery: true },
  );
  let envProof = null;
  try {
    await page.route('**/__ENV.js', async (route) => {
      const response = await route.fetch();
      const beforeBody = await response.text();
      const runtimeEnv = parseRuntimeEnv(beforeBody);
      if (runtimeEnv.NEXT_PUBLIC_ENABLE_CHAT_TAB !== 'false' || runtimeEnv.NEXT_PUBLIC_ENABLE_CHAT_SIDEBAR !== 'true') {
        fail('profile-boundary source flags drifted');
      }
      const before = { ...runtimeEnv };
      runtimeEnv.NEXT_PUBLIC_ENABLE_CHAT_TAB = 'true';
      const afterBody = `window.__ENV = ${JSON.stringify(runtimeEnv)};`;
      const changedKeys = Object.keys(runtimeEnv).filter((key) => before[key] !== runtimeEnv[key]);
      envProof = {
        before_sha256: sha(beforeBody),
        after_sha256: sha(afterBody),
        before_bytes: Buffer.byteLength(beforeBody),
        after_bytes: Buffer.byteLength(afterBody),
        changed_keys: changedKeys,
        sidebar_remained_enabled: runtimeEnv.NEXT_PUBLIC_ENABLE_CHAT_SIDEBAR === 'true',
      };
      await route.fulfill({ response, body: afterBody, contentType: 'application/javascript' });
    });
    await gotoUi(page, uiOrigin);
    if (!envProof) fail('profile-boundary runtime environment was not intercepted');
    const tabs = await page.locator('[data-testid^="sidebar-tab-"]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-testid')));
    const expectedTabs = ['sidebar-tab-chat', 'sidebar-tab-search', 'sidebar-tab-alerts', 'sidebar-tab-dashboard', 'sidebar-tab-video-management'];
    if (JSON.stringify(tabs) !== JSON.stringify(expectedTabs)) fail('alternate profile visible tab set drifted');
    await page.getByTestId('sidebar-tab-chat').click(); actions += 1;
    await page.waitForTimeout(250);
    const onChat = {
      main_chat_visible: await page.getByTestId('chat-textarea').filter({ visible: true }).count() === 1,
      floating_open_visible: await page.getByTestId('chat-sidebar-open').isVisible().catch(() => false),
      floating_close_visible: await page.getByTestId('chat-sidebar-close').isVisible().catch(() => false),
    };
    await page.getByTestId('sidebar-tab-search').click(); actions += 1;
    await page.waitForTimeout(250);
    const onSearch = {
      floating_sidebar_visible: await page.getByTestId('chat-sidebar-close').isVisible().catch(() => false),
      sidebar_chat_visible: await page.getByTestId('chat-textarea').filter({ visible: true }).count() === 1,
    };
    const screenshot = await screenshotInfo(page, screenshotPath);
    return {
      actions,
      runtime_env: envProof,
      tabs,
      profile_controlled_chat_transition: envProof.changed_keys.length === 1 && envProof.changed_keys[0] === 'NEXT_PUBLIC_ENABLE_CHAT_TAB',
      legacy_and_global_coexist: onChat.main_chat_visible && !onChat.floating_open_visible && !onChat.floating_close_visible && onSearch.floating_sidebar_visible && onSearch.sidebar_chat_visible,
      on_chat: onChat,
      on_search: onSearch,
      screenshot,
      diagnostics: summarizeDiagnostics(diagnostics),
    };
  } finally {
    await context.close();
  }
}

async function runReportBoundary(browser, uiOrigin, screenshotPath) {
  let actions = 0;
  const { context, page, diagnostics } = await openPage(browser, uiOrigin, { width: 1600, height: 1000 }, { captureWebSocketSends: true });
  let fixtureResponseCount = 0;
  const validId = `${CONTRACT.fixture.namespace}-valid`;
  const adjacentId = `alert-${CONTRACT.fixture.namespace}-fallback`;
  const sensor = `${CONTRACT.fixture.namespace}-sensor`;
  const fixtureContract = {
    incident_count: 2,
    valid_id_class: 'non_fallback',
    adjacent_id_class: 'fallback_prefix',
    category: 'Qualification',
    transport_send_suppressed: true,
  };
  try {
    await page.route('**/video-analytics-api/incidents?*', async (route) => {
      fixtureResponseCount += 1;
      const timestamp = new Date().toISOString();
      const end = new Date(Date.now() + 1000).toISOString();
      const incidents = [
        {
          Id: validId,
          timestamp,
          end,
          sensorId: sensor,
          category: 'Qualification',
          analyticsModule: { description: 'Bounded UI fixture', info: { triggerModules: 'Browser', verdict: 'true' } },
          fixture: true,
        },
        {
          Id: adjacentId,
          timestamp,
          end,
          sensorId: sensor,
          category: 'Qualification',
          analyticsModule: { description: 'Adjacent boundary', info: { triggerModules: 'Browser', verdict: 'false' } },
          fixture: true,
        },
      ];
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ incidents }) });
    });
    await gotoUi(page, uiOrigin);
    await page.getByTestId('sidebar-tab-alerts').click(); actions += 1;
    await page.getByTestId('alert-row').first().waitFor({ state: 'visible' });
    const rowCount = await page.getByTestId('alert-row').count();
    await page.getByRole('button', { name: new RegExp(`^Expand alert ${validId}`) }).click(); actions += 1;
    const generateReport = page.getByText('Generate Report', { exact: true });
    await generateReport.waitFor({ state: 'visible' });
    const generateReportCount = await generateReport.count();
    await generateReport.click(); actions += 1;
    await page.waitForFunction(() => window.__vssCapturedWebSocketSends.length === 1, undefined, { timeout: 30000 });
    const captured = await page.evaluate(() => window.__vssCapturedWebSocketSends.slice());
    if (captured.length !== 1) fail('Generate Report did not produce exactly one suppressed outbound frame');
    const wire = JSON.parse(captured[0]);
    const messages = wire?.content?.messages;
    const text = messages?.at(-1)?.content?.[0]?.text;
    if (!Array.isArray(messages) || typeof text !== 'string') fail('Generate Report outbound shape drifted');
    const screenshot = await screenshotInfo(page, screenshotPath);
    return {
      actions,
      fixture_contract_sha256: sha(JSON.stringify(fixtureContract)),
      fixture_response_count: fixtureResponseCount,
      row_count: rowCount,
      valid_generate_report_count: generateReportCount,
      adjacent_generate_report_suppressed: generateReportCount === 1 && rowCount === 2,
      sent_state_visible: await page.getByText('Sent', { exact: true }).count() === 1,
      transport: {
        captured_send_count: captured.length,
        actual_send_count: 0,
        send_suppressed: true,
      },
      wire: {
        type: wire.type,
        schema_type: wire.schema_type,
        message_count: messages.length,
        roles: messages.map((message) => message.role),
        text_sha256: sha(text),
        text_bytes: Buffer.byteLength(text),
        contains_valid_incident_marker: text.includes(validId),
        contains_sensor_marker: text.includes(sensor),
        id_present_not_retained: typeof wire.id === 'string' && wire.id.length > 0,
        conversation_id_present_not_retained: typeof wire.conversation_id === 'string' && wire.conversation_id.length > 0,
      },
      screenshot,
      diagnostics: summarizeDiagnostics(diagnostics),
    };
  } finally {
    await context.close();
  }
}

function assertRuntimeIdentity(runtime) {
  for (const row of Object.values(CONTRACT.runtime)) {
    const actual = runtime[row.container];
    if (!actual || actual.configured_image !== row.configured_image || actual.image_id !== row.image_id || !actual.running || actual.restart_count !== 0 || actual.oom_killed) {
      fail(`runtime identity or health drifted: ${row.container}`);
    }
  }
}

function closeEnough(value, expected, tolerance = 0.00002) {
  return Math.abs(value - expected) <= tolerance;
}

function assertRun(current, profile, report, diagnostics, bounds, preState, postState) {
  assertRuntimeIdentity(preState);
  if (JSON.stringify(preState) !== JSON.stringify(postState)) fail('related runtime state changed');
  if (!current.theme.initial_dark || !current.theme.light_rendered || !current.theme.dark_restored || !current.theme.switch_to_light_title || !current.theme.switch_to_dark_title) fail('theme state model failed');
  if (!closeEnough(current.sidebar.minimum.ratio, 1 / 3) || !closeEnough(current.sidebar.maximum.ratio, 2 / 3) || !closeEnough(current.sidebar.stored_width / current.sidebar.minimum.outer_width, 1 / 3) || !current.sidebar.collapsed_storage_false || !current.sidebar.opened_storage_true) fail('sidebar collapse/resize state model failed');
  if (current.uploads.input_count < 1 || !current.uploads.mp4 || !current.uploads.mkv || !current.uploads.adjacent_avi_absent || !current.uploads.drop_zone_text_visible) fail(`upload format state model failed: ${JSON.stringify(current.uploads)}`);
  if (!current.history.new_chat_visible || !current.history.folder_control_visible || current.history.new_folder_count !== 1 || current.history.folder_persisted_count !== 1) fail('history/folder state model failed');
  if (!current.settings.required_labels_present || current.settings.selected_schema !== 'chat_stream' || JSON.stringify(current.settings.schema_options) !== JSON.stringify(['chat_stream', 'chat', 'generate_stream', 'generate']) || !current.settings.intermediate_initially_enabled || !current.settings.intermediate_disabled || !current.settings.intermediate_restored) fail('settings state model failed');
  if (current.context_action.visible_plus_chat_count < 1 || current.context_action.added_state_count !== 1 || !current.context_action.highlighted_when_collapsed || current.context_action.chip_count !== 1 || current.context_action.chip_count_after_remove !== 0 || !current.context_action.highlight_cleared_after_open) fail('+ Chat or unseen-indicator state model failed');
  if (!profile.profile_controlled_chat_transition || !profile.legacy_and_global_coexist || JSON.stringify(profile.runtime_env.changed_keys) !== JSON.stringify(['NEXT_PUBLIC_ENABLE_CHAT_TAB'])) fail('profile/legacy coexistence boundary failed');
  if (report.row_count !== 2 || report.valid_generate_report_count !== 1 || !report.adjacent_generate_report_suppressed || !report.sent_state_visible || report.transport.captured_send_count !== 1 || report.transport.actual_send_count !== 0 || !report.transport.send_suppressed || report.wire.type !== 'user_message' || report.wire.schema_type !== 'chat_stream' || report.wire.message_count !== 1 || JSON.stringify(report.wire.roles) !== JSON.stringify(['user']) || !report.wire.contains_valid_incident_marker || !report.wire.contains_sensor_marker || !report.wire.id_present_not_retained || !report.wire.conversation_id_present_not_retained) fail('Generate Report boundary failed');
  if (diagnostics.some((row) => row.non_loopback_response_count !== 0 || row.page_error_hashes.length !== 0 || row.failing_response_hashes.length !== 0)) fail(`unexpected browser diagnostic: ${JSON.stringify(diagnostics)}`);
  if (bounds.duration_ms > CONTRACT.bounds.max_duration_ms || bounds.browser_actions > CONTRACT.bounds.max_browser_actions || bounds.loopback_browser_responses > CONTRACT.bounds.max_loopback_browser_responses) fail('runtime bound exceeded');
}

const mode = process.argv[2] || 'plan';
if (mode === 'plan') {
  console.log(JSON.stringify({
    schema_version: 1,
    package_id: PACKAGE_ID,
    mode: 'plan',
    default_execution_enabled: false,
    acknowledgement_required: ACK,
    browser_contexts: CONTRACT.bounds.browser_contexts,
    persistent_mutation: false,
    report_transport_send_suppressed: true,
    warehouse_sample_bundle: 'excluded',
  }, null, 2));
  process.exit(0);
}
if (mode !== 'run') fail('mode must be plan or run');
if (process.env.VSS_UI_GLOBAL_CHAT_ACK !== ACK) fail('exact acknowledgement is required');
const uiOrigin = numericLoopbackOrigin(process.env.VSS_UI_ORIGIN || '');
const playwrightEntry = process.env.VSS_PLAYWRIGHT_ENTRY || '';
const browserExecutable = process.env.VSS_BROWSER_EXECUTABLE || '';
const targetCommit = process.env.VSS_TARGET_COMMIT || '';
if (!/^[0-9a-f]{40}$/.test(targetCommit) || targetCommit !== CONTRACT.target_commit) fail('exact target commit is required');
if (!playwrightEntry.startsWith('/')) fail('absolute Playwright entry path is required');
if (!browserExecutable.startsWith('/')) fail('absolute browser executable path is required');

const sourceHashes = {};
for (const lock of CONTRACT.source_locks) {
  const body = await readFile(lock.path);
  sourceHashes[lock.path] = sha(body);
  if (sourceHashes[lock.path] !== lock.sha256) fail(`source lock drifted: ${lock.path}`);
}

const started = Date.now();
const screenshots = {
  current: `/tmp/vss-ui-global-chat-current-${process.pid}.png`,
  profile: `/tmp/vss-ui-global-chat-profile-${process.pid}.png`,
  report: `/tmp/vss-ui-global-chat-report-${process.pid}.png`,
};
const preState = relatedRuntimeState();
let browser;
try {
  const { chromium } = await import(pathToFileURL(playwrightEntry).href);
  browser = await chromium.launch({ executablePath: browserExecutable, headless: true, args: ['--no-sandbox'] });
  const current = await runCurrentProfile(browser, uiOrigin, screenshots.current);
  const profile = await runProfileBoundary(browser, uiOrigin, screenshots.profile);
  const report = await runReportBoundary(browser, uiOrigin, screenshots.report);
  const browserVersion = browser.version();
  await browser.close();
  browser = undefined;
  await Promise.all(Object.values(screenshots).map((path) => unlink(path)));
  const postState = relatedRuntimeState();
  const diagnostics = [current.diagnostics, profile.diagnostics, report.diagnostics];
  const bounds = {
    duration_ms: Date.now() - started,
    browser_actions: current.actions + profile.actions + report.actions,
    loopback_browser_responses: diagnostics.reduce((total, row) => total + row.loopback_response_count, 0),
    max_duration_ms: CONTRACT.bounds.max_duration_ms,
    max_browser_actions: CONTRACT.bounds.max_browser_actions,
    max_loopback_browser_responses: CONTRACT.bounds.max_loopback_browser_responses,
    browser_contexts: CONTRACT.bounds.browser_contexts,
  };
  assertRun(current, profile, report, diagnostics, bounds, preState, postState);
  const receipt = {
    schema_version: 1,
    package_id: PACKAGE_ID,
    status: 'passed_current_candidate',
    captured_at: new Date().toISOString(),
    target_commit: targetCommit,
    contract_sha256: sha(await readFile(new URL('./contract.json', HERE))),
    harness_sha256: sha(await readFile(new URL('./harness.mjs', HERE))),
    identity: {
      node_sha256: sha(await readFile(process.execPath)),
      playwright_entry_sha256: sha(await readFile(playwrightEntry)),
      browser_executable_sha256: sha(await readFile(browserExecutable)),
      browser_version_sha256: sha(browserVersion),
      ui_origin_sha256: sha(uiOrigin),
      source_hashes: sourceHashes,
    },
    pre_state: { related_runtime: preState },
    bounds,
    current_profile: current,
    profile_boundary: profile,
    report_boundary: report,
    post_state: { related_runtime: postState },
    cleanup: {
      mutation: 'browser_session_only',
      isolated_contexts_closed: 3,
      browser_closed: true,
      temporary_screenshots_deleted_after_hashing: true,
      server_resources_created: 0,
      server_resources_changed: 0,
      server_resources_deleted: 0,
      runtime_environment_override_discarded: true,
      report_fixture_discarded: true,
      report_transport_send_suppressed: true,
      related_runtime_state_unchanged: true,
    },
    warehouse_sample_bundle: 'excluded',
  };
  console.log(JSON.stringify(receipt, null, 2));
} finally {
  if (browser) await browser.close().catch(() => undefined);
  await Promise.all(Object.values(screenshots).map((path) => unlink(path).catch(() => undefined)));
}
