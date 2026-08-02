#!/usr/bin/env node
// Concrete Playwright client for an already-running numeric-loopback browser.
// It deliberately uses connectOverCDP and contains no browser-launch primitive.

import crypto from "node:crypto";
import fsSync from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import { pathToFileURL } from "node:url";

const MAX_INPUT = 256 * 1024;
const MAX_ACTIONS = 40;
const MAX_API = 32;
const CLEANUP_ACTION_RESERVE = 3;

function fail(code) {
  fsSync.writeSync(1, JSON.stringify({ status: "error", code }));
  process.exit(1);
}

function sha(value) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(String(value));
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stable(value[key])]),
    );
  }
  return value;
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
    throw new Error("origin");
  }
  return value.origin;
}

async function stdinJson() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > MAX_INPUT) throw new Error("input");
    chunks.push(chunk);
  }
  const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("input");
  }
  return value;
}

function flattenStreams(value) {
  if (!Array.isArray(value)) throw new Error("streams");
  const rows = [];
  for (const sensor of value) {
    if (!sensor || typeof sensor !== "object" || Array.isArray(sensor)) {
      throw new Error("streams");
    }
    for (const [sensorId, streams] of Object.entries(sensor)) {
      if (!Array.isArray(streams)) throw new Error("streams");
      for (const stream of streams) {
        if (!stream || typeof stream !== "object" || Array.isArray(stream)) {
          throw new Error("streams");
        }
        rows.push({ sensorId, ...stream });
      }
    }
  }
  return rows.sort((a, b) =>
    `${a.sensorId}:${a.streamId}`.localeCompare(`${b.sensorId}:${b.streamId}`),
  );
}

async function main() {
  const input = await stdinJson();
  const uiOrigin = numericLoopbackOrigin(input.ui_origin);
  const cdpOrigin = numericLoopbackOrigin(input.cdp_origin);
  const vstOrigin = numericLoopbackOrigin(input.vst_origin);
  const agentOrigin = numericLoopbackOrigin(input.agent_origin);
  if (new Set([uiOrigin, cdpOrigin, vstOrigin, agentOrigin]).size !== 4) {
    throw new Error("origin");
  }

  const moduleUrl = pathToFileURL(input.playwright_module).href;
  const imported = await import(moduleUrl);
  const chromium = imported.chromium ?? imported.default?.chromium;
  if (!chromium || typeof chromium.connectOverCDP !== "function") {
    throw new Error("playwright");
  }

  const browser = await chromium.connectOverCDP(cdpOrigin, { timeout: 10000 });
  const contexts = browser.contexts();
  if (contexts.length !== 1) throw new Error("browser-context");
  const page = await contexts[0].newPage();
  let actions = 1;
  let apiExchanges = 0;
  const consoleErrors = [];
  const redirectStatuses = [];
  const apiOrigins = new Set([vstOrigin, agentOrigin]);

  const workflowAct = async (operation) => {
    if (actions >= MAX_ACTIONS - CLEANUP_ACTION_RESERVE) {
      throw new Error("browser-budget");
    }
    actions += 1;
    return operation();
  };
  const cleanupAct = async (operation) => {
    if (actions >= MAX_ACTIONS) throw new Error("browser-budget");
    actions += 1;
    return operation();
  };
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(sha(message.text()));
  });
  page.on("pageerror", (error) => consoleErrors.push(sha(error.message)));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (apiOrigins.has(url.origin)) {
      apiExchanges += 1;
      if (apiExchanges > MAX_API) consoleErrors.push(sha("api-budget"));
      if (response.status() >= 300 && response.status() < 400) {
        redirectStatuses.push(response.status());
      }
    }
  });

  const ownedIds = new Set(input.owned_sensor_ids);
  const fixtureNames = input.fixtures.map((row) => row.path.split("/").at(-1));
  const rtspName = input.owned_sensor_ids[2];
  const registered = new Map();
  let preStateCaptured = false;
  let beforeDigest = null;
  let cleanupVerified = false;

  const readStreams = async () => {
    const value = await page.evaluate(async (url) => {
      const response = await fetch(url, { redirect: "error" });
      if (!response.ok) throw new Error("stream list failed");
      return response.json();
    }, `${vstOrigin}/v1/replay/streams`);
    return flattenStreams(value);
  };

  const unrelated = (rows) =>
    rows.filter((row) => !ownedIds.has(String(row.sensorId)));

  const reconcileAndCleanup = async () => {
    if (!preStateCaptured || beforeDigest === null) return;
    const observed = await readStreams();
    for (let index = 0; index < 2; index += 1) {
      if (
        observed.some(
          (row) =>
            String(row.sensorId) === input.owned_sensor_ids[index] &&
            String(row.name) === fixtureNames[index],
        )
      ) {
        registered.set(input.owned_sensor_ids[index], {
          kind: "video",
          name: fixtureNames[index],
        });
      }
    }
    if (
      observed.some(
        (row) =>
          String(row.sensorId) === input.owned_sensor_ids[2] &&
          String(row.name) === rtspName,
      )
    ) {
      registered.set(input.owned_sensor_ids[2], { kind: "rtsp", name: rtspName });
    }

    let deletionFailed = false;
    for (const [sensorId, resource] of [...registered.entries()].reverse()) {
      const path =
        resource.kind === "rtsp"
          ? `/rtsp-streams/delete/${encodeURIComponent(resource.name)}`
          : `/videos/${encodeURIComponent(sensorId)}`;
      try {
        const status = await cleanupAct(() =>
          page.evaluate(async (url) => {
            const response = await fetch(url, { method: "DELETE", redirect: "error" });
            return response.status;
          }, `${agentOrigin}${path}`),
        );
        if ((status < 200 || status >= 300) && status !== 404) {
          deletionFailed = true;
        }
      } catch (_error) {
        deletionFailed = true;
      }
    }
    const finalRows = await readStreams();
    if (
      deletionFailed ||
      finalRows.some((row) => ownedIds.has(String(row.sensorId)))
    ) {
      throw new Error("cleanup-owned-remains");
    }
    const finalDigest = sha(JSON.stringify(stable(unrelated(finalRows))));
    if (finalDigest !== beforeDigest) throw new Error("cleanup-unrelated-drift");
    registered.clear();
    cleanupVerified = true;
  };

  try {
    await workflowAct(() => page.setViewportSize({ width: 1440, height: 900 }));
    await workflowAct(() => page.goto(`${uiOrigin}/`, { waitUntil: "domcontentloaded", timeout: 30000 }));
    await workflowAct(() => page.getByTestId("sidebar-tab-video-management").click());
    await page.getByText("Video Management", { exact: true }).first().waitFor();

    const title = await page.title();
    const bodyText = (await page.locator("body").innerText()).trim();
    const overlay = page.locator(
      "nextjs-portal, [data-nextjs-dialog-overlay], #webpack-dev-server-client-overlay",
    );
    if (
      page.url() !== `${uiOrigin}/` ||
      !title.trim() ||
      bodyText.length < 20 ||
      (await overlay.count()) !== 0
    ) {
      throw new Error("page-identity");
    }

    await workflowAct(() => page.setViewportSize({ width: 390, height: 844 }));
    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    if (mobileOverflow) throw new Error("mobile-overflow");
    const mobileShot = await page.screenshot({ type: "png" });
    await workflowAct(() => page.setViewportSize({ width: 1440, height: 900 }));
    const desktopShot = await page.screenshot({ type: "png" });

    const before = await readStreams();
    if (
      before.some(
        (row) =>
          ownedIds.has(String(row.sensorId)) ||
          fixtureNames.includes(String(row.name)) ||
          String(row.name) === rtspName,
      )
    ) {
      throw new Error("collision");
    }
    beforeDigest = sha(JSON.stringify(stable(unrelated(before))));
    preStateCaptured = true;

    const fileInput = page.locator('input[type="file"][accept=".mp4,.mkv"]').first();
    await workflowAct(() => fileInput.setInputFiles(input.fixtures.map((row) => row.path)));
    await page.getByText("Upload Files", { exact: true }).waitFor();
    for (const name of fixtureNames) {
      await page.getByText(name, { exact: true }).waitFor();
    }

    await workflowAct(() => page.getByText(fixtureNames[0], { exact: true }).click());
    await page.getByText(input.template_field_name, { exact: true }).waitFor();
    await workflowAct(() => page.getByRole("button", { name: /^Upload \(2\)$/ }).click());
    const progressPanel = page.getByTestId("upload-progress-panel");
    await progressPanel.waitFor();
    await page
      .getByTestId("upload-progress-panel-summary")
      .getByText(/2 succeeded/)
      .waitFor({ timeout: 120000 });
    await workflowAct(() => progressPanel.locator("button").last().click());
    await progressPanel.waitFor({ state: "detached" });

    const afterUpload = await readStreams();
    for (let index = 0; index < 2; index += 1) {
      if (
        !afterUpload.some(
          (row) =>
            String(row.sensorId) === input.owned_sensor_ids[index] &&
            String(row.name) === fixtureNames[index],
        )
      ) {
        throw new Error("upload-readback");
      }
      registered.set(input.owned_sensor_ids[index], {
        kind: "video",
        name: fixtureNames[index],
      });
      await page.getByText(fixtureNames[index], { exact: true }).waitFor();
    }

    await workflowAct(() => page.getByRole("button", { name: "+ Add RTSP" }).click());
    await workflowAct(() => page.locator("#add-rtsp-url").fill("http://127.0.0.1/not-rtsp"));
    await workflowAct(() => page.locator("#add-rtsp-sensor-name").fill(rtspName));
    await workflowAct(() => page.getByRole("button", { name: "Add RTSP", exact: true }).click());
    await page.getByText('RTSP URL must start with "rtsp://".', { exact: true }).waitFor();
    await workflowAct(() =>
      page.locator("#add-rtsp-url").fill(`rtsp://127.0.0.1:18554/${rtspName}`),
    );
    await workflowAct(() => page.getByRole("button", { name: "Add RTSP", exact: true }).click());
    await page.getByTestId("add-rtsp-dialog").waitFor({ state: "detached" });
    await page.getByText(rtspName, { exact: true }).waitFor();

    const afterRtsp = await readStreams();
    if (
      !afterRtsp.some(
        (row) =>
          String(row.sensorId) === input.owned_sensor_ids[2] &&
          String(row.name) === rtspName,
      )
    ) {
      throw new Error("rtsp-readback");
    }
    registered.set(input.owned_sensor_ids[2], { kind: "rtsp", name: rtspName });

    for (const name of [...fixtureNames, rtspName]) {
      const card = page
        .getByText(name, { exact: true })
        .locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
      await workflowAct(() => card.locator('input[type="checkbox"]').check());
    }
    await workflowAct(() => page.getByRole("button", { name: "Delete Selected", exact: true }).click());
    const confirm = page.getByTestId("delete-confirm-dialog");
    await confirm.waitFor();
    for (const name of [...fixtureNames, rtspName]) {
      await confirm.getByText(name, { exact: true }).waitFor();
    }
    await workflowAct(() => confirm.getByRole("button", { name: "Cancel", exact: true }).click());
    await confirm.waitFor({ state: "detached" });
    for (const name of [...fixtureNames, rtspName]) {
      await page.getByText(name, { exact: true }).waitFor();
    }

    await workflowAct(() => page.getByRole("button", { name: "Delete Selected", exact: true }).click());
    await confirm.waitFor();
    await workflowAct(() => page.getByTestId("delete-confirm-button").click());
    await confirm.waitFor({ state: "detached", timeout: 120000 });

    const finalRows = await readStreams();
    if (finalRows.some((row) => ownedIds.has(String(row.sensorId)))) {
      throw new Error("owned-remains");
    }
    const afterDigest = sha(JSON.stringify(stable(unrelated(finalRows))));
    if (afterDigest !== beforeDigest) throw new Error("unrelated-drift");
    registered.clear();
    cleanupVerified = true;
    if (consoleErrors.length || redirectStatuses.length || apiExchanges > MAX_API) {
      throw new Error("browser-health");
    }

    return {
      status: "pass",
      browser_actions: actions,
      api_exchanges: apiExchanges,
      semantic_checkpoints: 11,
      checks: {
        page_identity: true,
        not_blank: true,
        no_framework_overlay: true,
        console_health: true,
        desktop_screenshot: sha(desktopShot),
        mobile_screenshot: sha(mobileShot),
        interaction_proof: true,
        mp4: true,
        mkv: true,
        multi_upload: true,
        rtsp_positive: true,
        rtsp_adjacent_negative: true,
        upload_progress: true,
        template_environment: true,
        bulk_delete_confirm: true,
        bulk_delete_cancel: true,
      },
      cleanup: {
        registered_owned_resources: 3,
        deleted_owned_resources: 3,
        owned_absent: true,
        unrelated_state_restored: true,
      },
    };
  } finally {
    let cleanupError = null;
    if (!cleanupVerified && preStateCaptured) {
      try {
        await reconcileAndCleanup();
      } catch (error) {
        cleanupError = error;
      }
    }
    await page.close().catch(() => {});
    if (cleanupError) throw cleanupError;
  }
}

try {
  const result = await main();
  fsSync.writeSync(1, JSON.stringify(result));
  // Ending this selected client tears down its CDP socket without sending a
  // Browser.close command to the operator-preexisting browser.
  process.exit(0);
} catch (_error) {
  fail("browser_oracle_failed");
}
