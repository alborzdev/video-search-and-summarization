#!/usr/bin/env node
// Read-only rendered Dashboard qualification against pre-existing Thor services.
// The Browser plugin is absent in this environment, so this uses connectOverCDP.

import crypto from "node:crypto";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const PACKAGE_ID = "thor-ui-dashboard-playwright-runtime-successor-v1";
const ACK = "I_ACK_UI_DASHBOARD_READ_ONLY_RUNTIME";
const MAX_DURATION_MS = 120_000;
const MAX_BROWSER_ACTIONS = 12;
const MAX_DIRECT_API_REQUESTS = 4;
const MAX_LOOPBACK_RESPONSES = 500;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const HERE = path.dirname(fileURLToPath(import.meta.url));

const sha = (value) => crypto.createHash("sha256").update(value).digest("hex");

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stable(value[key])]),
    );
  }
  return value;
}

function canonical(value) {
  return JSON.stringify(stable(value));
}

function fail(code) {
  process.stdout.write(`${JSON.stringify({ status: "error", code })}\n`);
  process.exit(1);
}

function parseArgs(argv) {
  if (argv.length === 0 || argv[0] === "plan") return { mode: "plan" };
  if (argv[0] !== "execute" || (argv.length - 1) % 2 !== 0) fail("arguments");
  const result = { mode: "execute" };
  for (let index = 1; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key.startsWith("--") || !value || key in result) fail("arguments");
    result[key.slice(2).replaceAll("-", "_")] = value;
  }
  const required = [
    "ack",
    "run_id",
    "ui_origin",
    "kibana_origin",
    "cdp_origin",
    "playwright_module",
  ];
  if (Object.keys(result).length !== required.length + 1) fail("arguments");
  for (const key of required) if (!(key in result)) fail("arguments");
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(result.run_id)) fail("run_id");
  return result;
}

function numericLoopbackOrigin(text) {
  const value = new URL(text);
  const host = value.hostname.replace(/^\[|\]$/g, "");
  const family = net.isIP(host);
  const loopback =
    (family === 4 && host.split(".")[0] === "127") ||
    (family === 6 && host === "::1");
  if (
    value.protocol !== "http:" ||
    !loopback ||
    !value.port ||
    value.username ||
    value.password ||
    (value.pathname !== "/" && value.pathname !== "") ||
    value.search ||
    value.hash
  ) {
    fail("origin");
  }
  return value.origin;
}

async function readJson(file) {
  const raw = await fs.readFile(file);
  if (raw.length === 0 || raw.length > MAX_RESPONSE_BYTES) fail("configuration");
  return { raw, value: JSON.parse(raw.toString("utf8")) };
}

async function boundedFetch(url) {
  const response = await fetch(url, {
    redirect: "error",
    signal: AbortSignal.timeout(10_000),
  });
  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length > MAX_RESPONSE_BYTES) fail("response_bound");
  return { response, buffer };
}

function dockerContainer(name, httpHealthy) {
  let value;
  try {
    value = JSON.parse(execFileSync("docker", ["inspect", name], {
      encoding: "utf8",
      timeout: 10_000,
      maxBuffer: MAX_RESPONSE_BYTES,
    }))[0];
  } catch {
    fail("container_identity");
  }
  if (!value?.Image?.match(/^sha256:[0-9a-f]{64}$/)) fail("container_identity");
  const dockerHealth = value.State?.Health?.Status;
  return {
    name,
    configured_image: value.Config?.Image,
    image_id: value.Image,
    running: value.State?.Running === true,
    healthy: httpHealthy && (dockerHealth === undefined || dockerHealth === "healthy"),
  };
}

function countBy(values, field) {
  const result = {};
  for (const value of values) {
    const key = String(value[field]);
    result[key] = (result[key] || 0) + 1;
  }
  return Object.fromEntries(Object.entries(result).sort());
}

function knownDiagnostic(text) {
  return [
    /apple-mobile-web-app-capable/i,
    /unrecognized feature.*web-share/i,
    /content security policy/i,
    /refused to execute inline script/i,
    /user_profile/i,
    /failed to load resource.*404/i,
    /now-2y/i,
    /moment.*deprecat/i,
    /^not found$/i,
    /cannot read properties of undefined.*includes/i,
  ].some((pattern) => pattern.test(text));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const contractDocument = await readJson(path.join(HERE, "contract.json"));
  const fixtureDocument = await readJson(path.join(HERE, "fixture.json"));
  const contract = contractDocument.value;
  const fixture = fixtureDocument.value;
  if (args.mode === "plan") {
    process.stdout.write(`${JSON.stringify({
      package_id: PACKAGE_ID,
      mode: "read_only",
      default_execution_enabled: false,
      acknowledgement: ACK,
      bounds: contract.bounds,
      persistent_mutation: false,
      warehouse_sample_bundle: "excluded",
    }, null, 2)}\n`);
    return;
  }
  if (args.ack !== ACK) fail("authorization_required");
  const started = Date.now();
  const uiOrigin = numericLoopbackOrigin(args.ui_origin);
  const kibanaOrigin = numericLoopbackOrigin(args.kibana_origin);
  const cdpOrigin = numericLoopbackOrigin(args.cdp_origin);
  if (new Set([uiOrigin, kibanaOrigin, cdpOrigin]).size !== 3) fail("origin");

  if (sha(fixtureDocument.raw) !== contract.fixture.sha256) fail("fixture_drift");
  const sourceLocks = [];
  const repoRoot = process.cwd();
  for (const lock of contract.source_locks) {
    const resolved = path.resolve(repoRoot, lock.path);
    if (!resolved.startsWith(`${path.resolve(repoRoot)}${path.sep}`)) fail("source_lock");
    const raw = await fs.readFile(resolved);
    if (sha(raw) !== lock.sha256) fail("source_lock");
    sourceLocks.push(lock);
  }

  let targetCommit;
  try {
    targetCommit = execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: repoRoot,
      encoding: "utf8",
      timeout: 10_000,
    }).trim();
  } catch {
    fail("target_identity");
  }
  if (!/^[0-9a-f]{40}$/.test(targetCommit)) fail("target_identity");

  let directApiRequests = 0;
  const direct = async (relative) => {
    if (++directApiRequests > MAX_DIRECT_API_REQUESTS) fail("api_budget");
    return boundedFetch(`${kibanaOrigin}${relative}`);
  };
  const statusResult = await direct("/kibana/api/status");
  if (!statusResult.response.ok) fail("kibana_status");
  const kibanaStatus = JSON.parse(statusResult.buffer.toString("utf8"));
  if (
    kibanaStatus?.name !== "thor" ||
    kibanaStatus?.version?.number !== contract.containers.kibana.version ||
    kibanaStatus?.status?.overall?.level !== "available"
  ) fail("kibana_status");

  const findResult = await direct(
    "/kibana/api/saved_objects/_find?type=dashboard&fields=title&fields=description",
  );
  if (!findResult.response.ok) fail("dashboard_find");
  const found = JSON.parse(findResult.buffer.toString("utf8"));
  const projection = (found.saved_objects || []).map((entry) => ({
    id: entry.id,
    title: entry.attributes?.title,
    description: entry.attributes?.description || "",
  })).sort((left, right) => left.id.localeCompare(right.id));
  const expected = fixture.dashboard;
  const selected = projection.find((entry) => entry.id === expected.id);
  if (
    !selected ||
    selected.title !== expected.title ||
    selected.description !== expected.description
  ) fail("dashboard_identity");

  const objectResult = await direct(
    `/kibana/api/saved_objects/dashboard/${encodeURIComponent(expected.id)}`,
  );
  if (!objectResult.response.ok) fail("dashboard_object");
  const dashboardObject = JSON.parse(objectResult.buffer.toString("utf8"));
  if (
    dashboardObject?.id !== expected.id ||
    dashboardObject?.attributes?.title !== expected.title ||
    dashboardObject?.attributes?.description !== expected.description ||
    !Array.isArray(dashboardObject?.references) ||
    dashboardObject.references.length < expected.required_panel_titles.length
  ) fail("dashboard_object");

  const negativeResult = await direct(
    `/kibana/api/saved_objects/dashboard/${fixture.adjacent_negative.dashboard_id}`,
  );
  if (negativeResult.response.status !== fixture.adjacent_negative.expected_status) {
    fail("adjacent_negative");
  }

  const moduleRaw = await fs.readFile(args.playwright_module);
  const imported = await import(pathToFileURL(args.playwright_module).href);
  const chromium = imported.chromium ?? imported.default?.chromium;
  if (!chromium || typeof chromium.connectOverCDP !== "function") fail("playwright");

  const browser = await chromium.connectOverCDP(cdpOrigin, { timeout: 10_000 });
  const contexts = browser.contexts();
  if (contexts.length !== 1) fail("browser_context");
  const page = await contexts[0].newPage();
  let browserActions = 1;
  const consoleEvents = [];
  const pageErrors = [];
  const responses = [];
  page.setDefaultTimeout(30_000);
  page.setDefaultNavigationTimeout(30_000);
  page.on("console", (event) => {
    if (["warning", "error"].includes(event.type())) {
      consoleEvents.push({ type: event.type(), text: event.text() });
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    const url = new URL(response.url());
    const host = url.hostname.replace(/^\[|\]$/g, "");
    if (host.startsWith("127.") || host === "::1") {
      responses.push({ path: url.pathname, status: response.status() });
    }
  });

  let desktop;
  let mobile;
  let frameBody;
  let iframePath;
  let iframeHashPrefix;
  let sandboxTokens;
  try {
    await page.setViewportSize(fixture.viewports.desktop);
    browserActions += 1;
    await page.goto(uiOrigin, { waitUntil: "domcontentloaded" });
    browserActions += 1;
    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    browserActions += 1;
    const iframe = page.getByTitle(fixture.iframe.title);
    await iframe.waitFor({ state: "attached" });
    const iframeHandle = await iframe.elementHandle();
    const frame = await iframeHandle?.contentFrame();
    if (!frame) fail("iframe");
    await frame.waitForURL(
      (url) => url.href.includes(fixture.iframe.path),
      { timeout: 30_000 },
    );
    await frame.locator("body").waitFor({ state: "visible" });
    await page.waitForTimeout(5_000);
    frameBody = await frame.locator("body").innerText();
    const pageText = await page.locator("body").innerText();
    const iframeSrc = await iframe.getAttribute("src");
    const parsedIframe = new URL(iframeSrc, uiOrigin);
    iframePath = parsedIframe.pathname;
    iframeHashPrefix = parsedIframe.hash;
    sandboxTokens = (await iframe.getAttribute("sandbox")).split(/\s+/).filter(Boolean).sort();
    const expectedTokens = [...fixture.iframe.required_sandbox_tokens].sort();
    if (
      (await page.title()) !== fixture.ui_title ||
      !pageText.includes("Dashboard") ||
      /next\.js.*error|application error|webpack.*error/i.test(pageText) ||
      iframePath !== fixture.iframe.path ||
      !iframeHashPrefix.startsWith(fixture.iframe.hash_prefix) ||
      canonical(sandboxTokens) !== canonical(expectedTokens) ||
      !expected.required_panel_titles.every((title) => frameBody.includes(title)) ||
      (frameBody.match(/No results found/g) || []).length < expected.minimum_no_result_panels
    ) fail("render_semantics");

    const desktopBox = await iframe.boundingBox();
    if (
      !desktopBox ||
      desktopBox.width < fixture.viewports.desktop.minimum_iframe_width ||
      desktopBox.height < fixture.viewports.desktop.minimum_iframe_height
    ) fail("desktop_layout");
    const desktopPath = `/tmp/vss-dashboard-${args.run_id}-desktop.png`;
    await page.screenshot({ path: desktopPath, fullPage: false });
    browserActions += 1;
    const desktopRaw = await fs.readFile(desktopPath);
    desktop = {
      viewport_width: fixture.viewports.desktop.width,
      viewport_height: fixture.viewports.desktop.height,
      iframe_width: desktopBox.width,
      iframe_height: desktopBox.height,
      screenshot_sha256: sha(desktopRaw),
      screenshot_bytes: desktopRaw.length,
    };

    await page.setViewportSize(fixture.viewports.mobile);
    browserActions += 1;
    await page.waitForTimeout(2_000);
    const mobileBox = await iframe.boundingBox();
    const overflow = await page.evaluate(() => ({
      body: [document.body.scrollWidth, document.body.clientWidth],
      document: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
    }));
    if (
      !mobileBox ||
      mobileBox.width < fixture.viewports.mobile.minimum_iframe_width ||
      mobileBox.height < fixture.viewports.mobile.minimum_iframe_height ||
      overflow.body[0] > overflow.body[1] ||
      overflow.document[0] > overflow.document[1]
    ) fail("mobile_layout");
    const mobilePath = `/tmp/vss-dashboard-${args.run_id}-mobile.png`;
    await page.screenshot({ path: mobilePath, fullPage: false });
    browserActions += 1;
    const mobileRaw = await fs.readFile(mobilePath);
    mobile = {
      viewport_width: fixture.viewports.mobile.width,
      viewport_height: fixture.viewports.mobile.height,
      iframe_width: mobileBox.width,
      iframe_height: mobileBox.height,
      screenshot_sha256: sha(mobileRaw),
      screenshot_bytes: mobileRaw.length,
    };
  } finally {
    await page.close();
  }

  const unknownDiagnostics = [
    ...consoleEvents.map((entry) => entry.text),
    ...pageErrors,
  ].filter((text) => !knownDiagnostic(text));
  const notFoundPaths = [...new Set(
    responses.filter((response) => response.status === 404).map((response) => response.path),
  )];
  const unknown404Paths = notFoundPaths.filter(
    (value) => value !== fixture.expected_security_disabled_diagnostics.browser_404_path,
  );
  if (
    unknownDiagnostics.length ||
    unknown404Paths.length ||
    responses.length > MAX_LOOPBACK_RESPONSES ||
    browserActions > MAX_BROWSER_ACTIONS
  ) fail("console_or_response_health");

  const durationMs = Date.now() - started;
  if (durationMs > MAX_DURATION_MS) fail("duration_bound");
  const uiPreflight = await boundedFetch(uiOrigin);
  if (!uiPreflight.response.ok) fail("ui_health");
  const uiIdentity = dockerContainer(contract.containers.ui.name, true);
  const kibanaIdentity = dockerContainer(contract.containers.kibana.name, true);
  if (
    uiIdentity.configured_image !== contract.containers.ui.configured_image ||
    kibanaIdentity.configured_image !== contract.containers.kibana.configured_image ||
    !uiIdentity.running || !uiIdentity.healthy ||
    !kibanaIdentity.running || !kibanaIdentity.healthy
  ) fail("container_identity");

  const diagnosticHashes = [...new Set([
    ...consoleEvents.map((entry) => sha(entry.text)),
    ...pageErrors.map((message) => sha(message)),
  ])].sort();
  const receipt = {
    schema_version: 1,
    package_id: PACKAGE_ID,
    status: "passed_current_candidate",
    captured_at: new Date().toISOString(),
    target_commit: targetCommit,
    contract_sha256: sha(contractDocument.raw),
    fixture_sha256: sha(fixtureDocument.raw),
    harness_sha256: sha(await fs.readFile(fileURLToPath(import.meta.url))),
    identity: {
      node_sha256: sha(await fs.readFile(process.execPath)),
      playwright_entry_sha256: sha(moduleRaw),
      ui: uiIdentity,
      kibana: kibanaIdentity,
      source_locks: sourceLocks,
    },
    bounds: {
      duration_ms: durationMs,
      browser_actions: browserActions,
      direct_api_requests: directApiRequests,
      loopback_browser_responses: responses.length,
      max_duration_ms: MAX_DURATION_MS,
      max_browser_actions: MAX_BROWSER_ACTIONS,
      max_direct_api_requests: MAX_DIRECT_API_REQUESTS,
      max_loopback_browser_responses: MAX_LOOPBACK_RESPONSES,
    },
    checks: {
      page_identity: true,
      not_blank: frameBody.length > 0,
      no_framework_overlay: true,
      console_health_explained: true,
      interaction_proof: true,
      iframe_embedded: true,
      saved_object_present: true,
      desktop_render: true,
      mobile_render: true,
      mobile_no_horizontal_overflow: true,
      adjacent_negative: true,
    },
    dashboard: {
      id: selected.id,
      title: selected.title,
      description: selected.description,
      saved_object_sha256: sha(Buffer.from(canonical(dashboardObject))),
      find_projection_sha256: sha(Buffer.from(canonical(projection))),
      dashboard_count: projection.length,
      required_panel_titles: expected.required_panel_titles,
      minimum_no_result_panels: expected.minimum_no_result_panels,
    },
    render: {
      iframe_title: fixture.iframe.title,
      iframe_path: iframePath,
      iframe_hash_prefix: fixture.iframe.hash_prefix,
      iframe_sandbox_tokens: sandboxTokens,
      frame_body_sha256: sha(Buffer.from(frameBody)),
      frame_body_bytes: Buffer.byteLength(frameBody),
      desktop,
      mobile,
    },
    adjacent_negative: {
      status: negativeResult.response.status,
      body_sha256: sha(negativeResult.buffer),
      body_bytes: negativeResult.buffer.length,
    },
    diagnostics: {
      response_status_counts: countBy(responses, "status"),
      known_security_profile_404_count: responses.filter(
        (response) => response.status === 404 &&
          response.path === fixture.expected_security_disabled_diagnostics.browser_404_path,
      ).length,
      unknown_404_paths: unknown404Paths,
      console_warning_count: consoleEvents.filter((entry) => entry.type === "warning").length,
      console_error_count: consoleEvents.filter((entry) => entry.type === "error").length,
      page_error_count: pageErrors.length,
      diagnostic_hashes: diagnosticHashes,
      classification: fixture.expected_security_disabled_diagnostics.classification,
      local_security_gap_open: true,
    },
    cleanup: {
      mutation: "none_read_only",
      persistent_resources_created: 0,
      persistent_resources_deleted: 0,
      persistent_state_unchanged: true,
      temporary_screenshots_only: true,
    },
    browser_plugin: "absent_regular_playwright_fallback",
    warehouse_sample_bundle: "excluded",
  };
  await new Promise((resolve, reject) => {
    process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`, (error) => {
      if (error) reject(error);
      else resolve();
    });
  });
  // connectOverCDP leaves a transport socket referenced; exiting disconnects only
  // this short-lived client and deliberately does not send Browser.close.
  process.exit(0);
}

main().catch(() => fail("runtime_failure"));
