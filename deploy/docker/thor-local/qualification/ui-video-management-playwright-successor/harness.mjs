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
const MAX_AGENT_DELETE_RESPONSE_BYTES = 64 * 1024;
const UPLOAD_CHUNK_BYTES = 10 * 1024 * 1024;
const WORKFLOW_DEADLINE_MS = 175 * 1000;
const CLEANUP_RESERVE_MS = 45 * 1000;
const ACTION_TIMEOUT_MS = 15 * 1000;
const LONG_WAIT_TIMEOUT_MS = 90 * 1000;
const CLEANUP_HTTP_TIMEOUT_MS = 7 * 1000;
const STREAM_PROJECTION_POLL_ATTEMPTS = 4;
const STREAM_PROJECTION_POLL_INTERVAL_MS = 750;

let currentPhase = "startup";

function remainingTimeout(deadline, maximum) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error("deadline");
  return Math.max(1, Math.min(maximum, remaining));
}

async function withinDeadline(operation, deadline, maximum) {
  const timeout = remainingTimeout(deadline, maximum);
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(() => operation(timeout)),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("deadline")), timeout);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

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
  const seenSensorIds = new Set();
  for (const sensor of value) {
    if (!sensor || typeof sensor !== "object" || Array.isArray(sensor)) {
      throw new Error("streams");
    }
    for (const [sensorId, streams] of Object.entries(sensor)) {
      if (!sensorId || seenSensorIds.has(sensorId) || !Array.isArray(streams)) {
        throw new Error("streams");
      }
      seenSensorIds.add(sensorId);
      if (streams.length === 0) {
        rows.push({ sensorId, streamId: "", name: "", emptySensor: true });
        continue;
      }
      for (const stream of streams) {
        if (!stream || typeof stream !== "object" || Array.isArray(stream)) {
          throw new Error("streams");
        }
        rows.push({ ...stream, sensorId, emptySensor: false });
      }
    }
  }
  return rows.sort((a, b) =>
    `${a.sensorId}:${a.streamId}`.localeCompare(`${b.sensorId}:${b.streamId}`),
  );
}

async function main() {
  currentPhase = "input";
  const input = await stdinJson();
  const workflowDeadline = Date.now() + WORKFLOW_DEADLINE_MS;
  const cleanupDeadline = workflowDeadline + CLEANUP_RESERVE_MS;
  const uiOrigin = numericLoopbackOrigin(input.ui_origin);
  const cdpOrigin = numericLoopbackOrigin(input.cdp_origin);
  const vstOrigin = numericLoopbackOrigin(input.vst_origin);
  const agentOrigin = numericLoopbackOrigin(input.agent_origin);
  if ([uiOrigin, vstOrigin, agentOrigin].includes(cdpOrigin)) {
    throw new Error("origin");
  }
  const vstApiBase = `${vstOrigin}/vst/api`;

  const moduleUrl = pathToFileURL(input.playwright_module).href;
  const imported = await import(moduleUrl);
  const chromium = imported.chromium ?? imported.default?.chromium;
  if (!chromium || typeof chromium.connectOverCDP !== "function") {
    throw new Error("playwright");
  }

  const browser = await chromium.connectOverCDP(cdpOrigin, {
    timeout: remainingTimeout(workflowDeadline, 10000),
  });
  const contexts = browser.contexts();
  if (contexts.length !== 1) throw new Error("browser-context");
  const page = await withinDeadline(
    () => contexts[0].newPage(),
    workflowDeadline,
    ACTION_TIMEOUT_MS,
  );
  page.setDefaultTimeout(ACTION_TIMEOUT_MS);
  page.setDefaultNavigationTimeout(ACTION_TIMEOUT_MS);
  let actions = 1;
  let apiExchanges = 0;
  const consoleErrors = [];
  const redirectStatuses = [];

  await page.addInitScript(({ uploadUrl }) => {
    const captures = [];
    Object.defineProperty(globalThis, "__vssUploadCaptures", {
      configurable: false,
      enumerable: false,
      writable: false,
      value: captures,
    });
    const stateByRequest = new WeakMap();
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
    const originalSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function open(method, url, ...rest) {
      stateByRequest.set(this, {
        method: String(method).toUpperCase(),
        url: new URL(String(url), globalThis.location.href).href,
        headers: {},
      });
      return originalOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.setRequestHeader = function setRequestHeader(name, value) {
      const state = stateByRequest.get(this);
      if (state) state.headers[String(name).toLowerCase()] = String(value);
      return originalSetRequestHeader.call(this, name, value);
    };
    XMLHttpRequest.prototype.send = function send(body) {
      const state = stateByRequest.get(this);
      if (state?.method === "POST" && state.url === uploadUrl) {
        captures.push((async () => {
          try {
            if (!(body instanceof FormData)) return { error: "form-data" };
            const media = body.get("mediaFile");
            const formFileName = body.get("filename");
            if (!(media instanceof Blob) || typeof formFileName !== "string") {
              return { error: "media-part" };
            }
            const payload = await media.arrayBuffer();
            const digest = await crypto.subtle.digest("SHA-256", payload);
            const payloadSha = Array.from(new Uint8Array(digest), (byte) =>
              byte.toString(16).padStart(2, "0")
            ).join("");
            return {
              fileName: state.headers["nvstreamer-file-name"],
              formFileName,
              identifier: state.headers["nvstreamer-identifier"],
              chunkNumber: Number(state.headers["nvstreamer-chunk-number"]),
              totalChunks: Number(state.headers["nvstreamer-total-chunks"]),
              isLastChunk: state.headers["nvstreamer-is-last-chunk"],
              payloadBytes: payload.byteLength,
              payloadSha,
            };
          } catch (_error) {
            return { error: "capture" };
          }
        })());
      }
      return originalSend.call(this, body);
    };
  }, { uploadUrl: `${vstApiBase}/v1/storage/file` });

  const workflowAct = async (operation) => {
    if (actions >= MAX_ACTIONS - CLEANUP_ACTION_RESERVE) {
      throw new Error("browser-budget");
    }
    actions += 1;
    return withinDeadline((timeout) => {
      page.setDefaultTimeout(timeout);
      page.setDefaultNavigationTimeout(timeout);
      return operation(timeout);
    }, workflowDeadline, ACTION_TIMEOUT_MS);
  };
  const cleanupAct = async (operation) => {
    if (actions >= MAX_ACTIONS) throw new Error("browser-budget");
    actions += 1;
    return withinDeadline((timeout) => operation(timeout), cleanupDeadline, CLEANUP_HTTP_TIMEOUT_MS);
  };
  const workflowWait = async (operation, maximum = ACTION_TIMEOUT_MS) =>
    withinDeadline((timeout) => {
      page.setDefaultTimeout(timeout);
      return operation(timeout);
    }, workflowDeadline, maximum);
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(sha(message.text()));
  });
  page.on("pageerror", (error) => consoleErrors.push(sha(error.message)));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (
      (url.origin === vstOrigin && url.pathname.startsWith("/vst/api/")) ||
      (url.origin === agentOrigin && url.pathname.startsWith("/api/"))
    ) {
      apiExchanges += 1;
      if (apiExchanges > MAX_API) consoleErrors.push(sha("api-budget"));
      if (response.status() >= 300 && response.status() < 400) {
        redirectStatuses.push(response.status());
      }
    }
  });
  const ownedIds = new Set();
  const fixtureNames = input.fixtures.map((row) => row.path.split("/").at(-1));
  const streamNames = fixtureNames.map((name) => name.replace(/\.[^.]+$/, ""));
  if (new Set(streamNames).size !== streamNames.length) {
    throw new Error("owned-name-collision");
  }
  const rtspName = input.owned_rtsp_name;
  const ownedNames = new Set([...streamNames, rtspName]);
  const registered = new Map();
  let preStateCaptured = false;
  let beforeDigest = null;
  let cleanupVerified = false;
  let ownedMutationStarted = false;

  const readStreams = async (
    deadline = workflowDeadline,
    maximum = ACTION_TIMEOUT_MS,
  ) => {
    const timeout = remainingTimeout(deadline, maximum);
    const value = await withinDeadline(() => page.evaluate(async (request) => {
      const response = await fetch(request.url, {
        redirect: "error",
        signal: AbortSignal.timeout(request.timeout),
      });
      if (!response.ok) throw new Error("stream list failed");
      return response.json();
    }, {
      url: `${vstApiBase}/v1/replay/streams`,
      timeout,
    }), deadline, maximum);
    return flattenStreams(value);
  };

  const pollStreams = async (
    predicate,
    deadline = workflowDeadline,
    maximum = ACTION_TIMEOUT_MS,
  ) => {
    let rows = [];
    for (let attempt = 0; attempt < STREAM_PROJECTION_POLL_ATTEMPTS; attempt += 1) {
      rows = await readStreams(deadline, maximum);
      if (predicate(rows)) return rows;
      if (attempt + 1 < STREAM_PROJECTION_POLL_ATTEMPTS) {
        await withinDeadline(
          () => new Promise((resolve) => setTimeout(resolve, STREAM_PROJECTION_POLL_INTERVAL_MS)),
          deadline,
          STREAM_PROJECTION_POLL_INTERVAL_MS + 1,
        );
      }
    }
    return rows;
  };

  const unrelated = (rows) =>
    rows.filter((row) => !ownedIds.has(String(row.sensorId)));

  const uniqueNamedRow = (rows, name) => {
    const matches = rows.filter((row) => String(row.name) === name);
    if (matches.length !== 1 || !String(matches[0].sensorId)) {
      throw new Error("owned-name-reconciliation");
    }
    return matches[0];
  };

  const reconcileAndCleanup = async () => {
    if (!preStateCaptured || beforeDigest === null) return;
    currentPhase = "cleanup-reconcile";
    const observed = ownedMutationStarted
      ? await pollStreams(
          (rows) => rows.some((row) => ownedNames.has(String(row.name))),
          cleanupDeadline,
          CLEANUP_HTTP_TIMEOUT_MS,
        )
      : await readStreams(cleanupDeadline, CLEANUP_HTTP_TIMEOUT_MS);
    for (let index = 0; index < 2; index += 1) {
      const matches = observed.filter(
        (row) => String(row.name) === streamNames[index],
      );
      if (matches.length > 1) throw new Error("owned-name-reconciliation");
      if (matches.length === 1) {
        const sensorId = String(matches[0].sensorId);
        if (!sensorId) throw new Error("owned-name-reconciliation");
        ownedIds.add(sensorId);
        registered.set(sensorId, {
          kind: "video",
          name: streamNames[index],
        });
      }
    }
    const rtspMatches = observed.filter((row) => String(row.name) === rtspName);
    if (rtspMatches.length > 1) throw new Error("owned-name-reconciliation");
    if (rtspMatches.length === 1) {
      const sensorId = String(rtspMatches[0].sensorId);
      if (!sensorId) throw new Error("owned-name-reconciliation");
      ownedIds.add(sensorId);
      registered.set(sensorId, { kind: "rtsp", name: rtspName });
    }

    let deletionFailed = false;
    for (const [sensorId, resource] of [...registered.entries()].reverse()) {
      const path =
        resource.kind === "rtsp"
          ? `/rtsp-streams/delete/${encodeURIComponent(resource.name)}`
          : `/videos/${encodeURIComponent(sensorId)}`;
      try {
        await cleanupAct((timeout) =>
          page.evaluate(async (request) => {
            const response = await fetch(request.url, {
              method: "DELETE",
              redirect: "error",
              signal: AbortSignal.timeout(request.timeout),
            });
            const declaredLength = response.headers.get("content-length");
            if (
              declaredLength !== null &&
              (!/^\d+$/.test(declaredLength) ||
                Number(declaredLength) > request.maxResponseBytes)
            ) {
              throw new Error("agent-delete-response");
            }
            const text = await response.text();
            if (
              new TextEncoder().encode(text).byteLength > request.maxResponseBytes
            ) {
              throw new Error("agent-delete-response");
            }
            let value;
            try {
              value = JSON.parse(text);
            } catch (_error) {
              throw new Error("agent-delete-response");
            }
            if (
              !response.ok ||
              !value ||
              typeof value !== "object" ||
              Array.isArray(value) ||
              value.status !== "success"
            ) {
              throw new Error("agent-delete-response");
            }
            if (
              (request.kind === "video" &&
                value.video_id !== request.expectedIdentity) ||
              (request.kind === "rtsp" && value.name !== request.expectedName)
            ) {
              throw new Error("agent-delete-identity");
            }
          }, {
            url: `${agentOrigin}/api/v1${path}`,
            kind: resource.kind,
            expectedIdentity: sensorId,
            expectedName: resource.name,
            maxResponseBytes: MAX_AGENT_DELETE_RESPONSE_BYTES,
            timeout,
          }),
        );
      } catch (_error) {
        deletionFailed = true;
      }
    }
    currentPhase = "cleanup-postconditions";
    const finalRows = await pollStreams(
      (rows) =>
        !rows.some(
          (row) =>
            ownedIds.has(String(row.sensorId)) || ownedNames.has(String(row.name)),
        ),
      cleanupDeadline,
      CLEANUP_HTTP_TIMEOUT_MS,
    );
    if (
      deletionFailed ||
      finalRows.some(
        (row) =>
          ownedIds.has(String(row.sensorId)) || ownedNames.has(String(row.name)),
      )
    ) {
      throw new Error("cleanup-owned-remains");
    }
    const finalDigest = sha(JSON.stringify(stable(unrelated(finalRows))));
    if (finalDigest !== beforeDigest) throw new Error("cleanup-unrelated-drift");
    registered.clear();
    cleanupVerified = true;
  };

  try {
    currentPhase = "page-open";
    await workflowAct(() => page.setViewportSize({ width: 1440, height: 900 }));
    await workflowAct((timeout) =>
      page.goto(`${uiOrigin}/`, { waitUntil: "domcontentloaded", timeout }),
    );
    await workflowAct(() => page.getByTestId("sidebar-tab-video-management").click());
    await workflowWait((timeout) =>
      page.getByText("Video Management", { exact: true }).first().waitFor({ timeout }),
    );

    const overlay = page.locator(
      "nextjs-portal, [data-nextjs-dialog-overlay], #webpack-dev-server-client-overlay",
    );
    const [title, rawBodyText, overlayCount] = await workflowWait(() =>
      Promise.all([
        page.title(),
        page.locator("body").innerText(),
        overlay.count(),
      ]),
    );
    const bodyText = rawBodyText.trim();
    if (
      page.url() !== `${uiOrigin}/` ||
      !title.trim() ||
      bodyText.length < 20 ||
      overlayCount !== 0
    ) {
      throw new Error("page-identity");
    }

    currentPhase = "responsive-render";
    await workflowAct(() => page.setViewportSize({ width: 390, height: 844 }));
    const mobileOverflow = await workflowWait(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      ),
    );
    if (mobileOverflow) throw new Error("mobile-overflow");
    const mobileShot = await workflowWait((timeout) =>
      page.screenshot({ type: "png", timeout }),
    );
    await workflowAct(() => page.setViewportSize({ width: 1440, height: 900 }));
    const desktopShot = await workflowWait((timeout) =>
      page.screenshot({ type: "png", timeout }),
    );

    currentPhase = "pre-state";
    const before = await readStreams();
    if (
      before.some(
        (row) =>
          ownedIds.has(String(row.sensorId)) ||
          streamNames.includes(String(row.name)) ||
          String(row.name) === rtspName,
      )
    ) {
      throw new Error("collision");
    }
    beforeDigest = sha(JSON.stringify(stable(unrelated(before))));
    preStateCaptured = true;

    currentPhase = "upload-dialog";
    await workflowAct(async (timeout) => {
      const chooserPromise = page.waitForEvent("filechooser", { timeout });
      await page.getByRole("button", { name: "+ Upload Video", exact: true }).click();
      const chooser = await chooserPromise;
      await chooser.setFiles(input.fixtures.map((row) => row.path));
    });
    await workflowWait((timeout) =>
      page.getByText("Upload Files", { exact: true }).waitFor({ timeout }),
    );
    for (const name of fixtureNames) {
      await workflowWait((timeout) =>
        page.getByText(name, { exact: true }).waitFor({ timeout }),
      );
    }

    await workflowAct(() => page.getByText(fixtureNames[0], { exact: true }).click());
    await workflowWait((timeout) =>
      page.getByText(input.template_field_name, { exact: true }).waitFor({ timeout }),
    );
    currentPhase = "upload-progress";
    ownedMutationStarted = true;
    await workflowAct(() => page.getByRole("button", { name: /^Upload \(2\)$/ }).click());
    const progressPanel = page.getByTestId("upload-progress-panel");
    await workflowWait((timeout) => progressPanel.waitFor({ timeout }));
    await workflowWait(
      (timeout) =>
        page
          .getByTestId("upload-progress-panel-summary")
          .getByText(/2 succeeded/)
          .waitFor({ timeout }),
      LONG_WAIT_TIMEOUT_MS,
    );
    await workflowAct(() => progressPanel.locator("button").last().click());
    await workflowWait((timeout) =>
      progressPanel.waitFor({ state: "detached", timeout }),
    );

    currentPhase = "chunk-integrity";
    const capturedChunks = await workflowWait(
      () => page.evaluate(async () => {
        const captures = globalThis.__vssUploadCaptures;
        if (!Array.isArray(captures)) throw new Error("upload-capture");
        return Promise.all(captures);
      }),
      LONG_WAIT_TIMEOUT_MS,
    );
    if (capturedChunks.length !== 4) throw new Error("chunk-count");
    const identifiers = new Set();
    for (let index = 0; index < fixtureNames.length; index += 1) {
      const fileName = fixtureNames[index];
      const expectedFixture = await fs.readFile(input.fixtures[index].path);
      if (sha(expectedFixture) !== input.fixtures[index].sha256) {
        throw new Error("fixture-drift");
      }
      const chunks = capturedChunks
        .filter((row) => row.fileName === fileName)
        .sort((left, right) => left.chunkNumber - right.chunkNumber);
      if (
        chunks.length !== 2 ||
        chunks.some((row) => row.totalChunks !== 2) ||
        chunks[0].chunkNumber !== 1 ||
        chunks[0].isLastChunk !== "false" ||
        chunks[1].chunkNumber !== 2 ||
        chunks[1].isLastChunk !== "true" ||
        chunks.some((row) => row.formFileName !== fileName || row.error) ||
        !chunks[0].identifier ||
        chunks[0].identifier !== chunks[1].identifier
      ) {
        throw new Error("chunk-protocol");
      }
      identifiers.add(chunks[0].identifier);
      for (const chunk of chunks) {
        const start = (chunk.chunkNumber - 1) * UPLOAD_CHUNK_BYTES;
        const end = Math.min(start + UPLOAD_CHUNK_BYTES, expectedFixture.length);
        const expectedPayload = expectedFixture.subarray(start, end);
        if (
          chunk.payloadBytes !== expectedPayload.length ||
          chunk.payloadSha !== sha(expectedPayload)
        ) {
          throw new Error("chunk-payload-digest");
        }
      }
    }
    if (identifiers.size !== 2) throw new Error("chunk-identifier");

    currentPhase = "upload-projection";
    const afterUpload = await pollStreams((rows) =>
      streamNames.every(
        (name) => rows.filter((row) => String(row.name) === name).length === 1,
      ),
    );
    for (let index = 0; index < 2; index += 1) {
      const row = uniqueNamedRow(afterUpload, streamNames[index]);
      const sensorId = String(row.sensorId);
      ownedIds.add(sensorId);
      registered.set(sensorId, {
        kind: "video",
        name: streamNames[index],
      });
      await workflowWait((timeout) =>
        page.getByText(streamNames[index], { exact: true }).waitFor({ timeout }),
      );
    }

    currentPhase = "rtsp-negative";
    await workflowAct(() => page.getByRole("button", { name: "+ Add RTSP" }).click());
    await workflowAct(() => page.locator("#add-rtsp-url").fill("http://127.0.0.1/not-rtsp"));
    await workflowAct(() => page.locator("#add-rtsp-sensor-name").fill(rtspName));
    await workflowAct(() => page.getByRole("button", { name: "Add RTSP", exact: true }).click());
    await workflowWait((timeout) =>
      page
        .getByText('RTSP URL must start with "rtsp://".', { exact: true })
        .waitFor({ timeout }),
    );
    currentPhase = "rtsp-positive";
    await workflowAct(() =>
      page.locator("#add-rtsp-url").fill(`rtsp://127.0.0.1:18554/${rtspName}`),
    );
    await workflowAct(() => page.getByRole("button", { name: "Add RTSP", exact: true }).click());
    await workflowWait((timeout) =>
      page.getByTestId("add-rtsp-dialog").waitFor({ state: "detached", timeout }),
    );
    await workflowWait((timeout) =>
      page.getByText(rtspName, { exact: true }).waitFor({ timeout }),
    );

    currentPhase = "rtsp-projection";
    const afterRtsp = await pollStreams(
      (rows) => rows.filter((row) => String(row.name) === rtspName).length === 1,
    );
    const rtspRow = uniqueNamedRow(afterRtsp, rtspName);
    const rtspSensorId = String(rtspRow.sensorId);
    ownedIds.add(rtspSensorId);
    registered.set(rtspSensorId, { kind: "rtsp", name: rtspName });

    currentPhase = "bulk-delete-cancel";
    for (const name of [...streamNames, rtspName]) {
      const card = page
        .getByText(name, { exact: true })
        .locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
      await workflowAct(() => card.locator('input[type="checkbox"]').check());
    }
    await workflowAct(() => page.getByRole("button", { name: "Delete Selected", exact: true }).click());
    const confirm = page.getByTestId("delete-confirm-dialog");
    await workflowWait((timeout) => confirm.waitFor({ timeout }));
    await workflowWait((timeout) =>
      confirm
        .getByText("This deletion is irreversible and cannot be undone.", {
          exact: true,
        })
        .waitFor({ timeout }),
    );
    for (const name of [...streamNames, rtspName]) {
      await workflowWait((timeout) =>
        confirm.getByText(name, { exact: true }).waitFor({ timeout }),
      );
    }
    await workflowAct(() => confirm.getByRole("button", { name: "Cancel", exact: true }).click());
    await workflowWait((timeout) => confirm.waitFor({ state: "detached", timeout }));
    for (const name of [...streamNames, rtspName]) {
      await workflowWait((timeout) =>
        page.getByText(name, { exact: true }).waitFor({ timeout }),
      );
    }

    currentPhase = "bulk-delete-confirm";
    await workflowAct(() => page.getByRole("button", { name: "Delete Selected", exact: true }).click());
    await workflowWait((timeout) => confirm.waitFor({ timeout }));
    await workflowWait((timeout) =>
      confirm
        .getByText("This deletion is irreversible and cannot be undone.", {
          exact: true,
        })
        .waitFor({ timeout }),
    );
    await workflowAct(() => page.getByTestId("delete-confirm-button").click());
    await workflowWait(
      (timeout) => confirm.waitFor({ state: "detached", timeout }),
      LONG_WAIT_TIMEOUT_MS,
    );

    currentPhase = "postconditions";
    const finalRows = await pollStreams(
      (rows) =>
        !rows.some(
          (row) =>
            ownedIds.has(String(row.sensorId)) || ownedNames.has(String(row.name)),
        ),
    );
    if (
      finalRows.some(
        (row) =>
          ownedIds.has(String(row.sensorId)) || ownedNames.has(String(row.name)),
      )
    ) {
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
        ordered_multichunk_protocol: true,
        upload_payload_digest_integrity: true,
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
    await withinDeadline(() => page.close(), cleanupDeadline, 2000).catch(() => {});
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
  fail(`browser_oracle_failed:${currentPhase}`);
}
