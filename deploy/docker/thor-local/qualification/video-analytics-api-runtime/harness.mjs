#!/usr/bin/env node

// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { promisify } from "node:util";
import {
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
  unlinkSync,
} from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const execFile = promisify(execFileCallback);
const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../../../..");
const fixtures = resolve(here, "fixtures");
const apiBase = process.env.VSS_VIDEO_ANALYTICS_URL ?? "http://127.0.0.1:8081";
const brokerlessApiBase = "http://127.0.0.1:18081";
const esBase = process.env.VSS_VIDEO_ANALYTICS_ES_URL ?? "http://127.0.0.1:9200";
const apiContainer = process.env.VSS_VIDEO_ANALYTICS_CONTAINER ?? "vss-video-analytics-api";
const oracleContainer = "vss-video-analytics-runtime-oracle";
const brokerlessContainer = "vss-video-analytics-brokerless-oracle";
const apiImage = "nvcr.io/nvidia/vss-core/vss-video-analytics-api:3.2.0";
const behaviorImage = "nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1";
const behaviorConfig = resolve(
  repo,
  "deploy/docker/services/analytics/behavior-analytics/configs/vss-behavior-analytics-config.json",
);
const expectedPath = resolve(
  repo,
  "deploy/docker/thor-local/qualification/expected/video-analytics.json",
);
const openapiPath = resolve(
  repo,
  "services/analytics/video-analytics-api/src/app/specification/openapi.json",
);
const semanticDocumentsPath = resolve(fixtures, "semantic-documents.json");
const brokerlessConfigPath = resolve(fixtures, "brokerless-config.json");
const imageDataDir = resolve(
  repo,
  "deploy/docker/data-dir/data_log/vss_video_analytics_api",
);

const sensor = "vss-oracle-video-analytics";
const place = "city=VSSOracle/building=Thor";
const corridor = "city=VSSOracle/corridor=Thor";
const city = "city=VSSOracle";
const fromTimestamp = "2026-08-10T00:00:00.000Z";
const toTimestamp = "2026-08-10T23:59:59.000Z";
const pointTimestamp = "2026-08-10T06:00:05.000Z";
const metricFromTimestamp = "2026-08-10T06:00:00.000Z";
const metricToTimestamp = "2026-08-10T06:00:10.000Z";
const behaviorIndex = "mdx-behavior-vss-oracle-runtime";
const semanticIndices = [
  "mdx-raw-vss-oracle-runtime",
  "mdx-frames-vss-oracle-runtime",
  "mdx-bev-vss-oracle-runtime",
  "mdx-events-vss-oracle-runtime",
  "mdx-alerts-vss-oracle-runtime",
  "mdx-incidents-vss-oracle-runtime",
  "mdx-mtmc-vss-oracle-runtime",
  "mdx-sensor-lookup",
  "mdx-rtls-vss-oracle-runtime",
  "mdx-amr-locations-vss-oracle-runtime",
  "mdx-amr-events-vss-oracle-runtime",
  "mdx-space-utilization-vss-oracle-runtime",
];
const mutableIndices = [
  "mdx-calibration",
  "mdx-calibration-audit",
  "mdx-calibration-images",
  "mdx-road-network",
  "mdx-usd-assets",
  "mdx-occupancy-reset",
  "mdx-cluster-labels",
  "mdx-configs",
  "mdx-configs-audit",
  behaviorIndex,
  ...semanticIndices,
];
const mutableTemplates = [
  "mdx-calibration-template",
  "mdx-calibration-audit-template",
];
const persistentMappingTemplates = {
  "mdx_rtls_template": {
    objectCounts: "nested",
  },
  "mdx-road-network-template": {
    "roadNetwork.intersections.segments.start.lat": "float",
    "roadNetwork.intersections.segments.start.lng": "float",
    "roadNetwork.intersections.segments.end.lat": "float",
    "roadNetwork.intersections.segments.end.lng": "float",
    "roadNetwork.intersections.segments.points.lat": "float",
    "roadNetwork.intersections.segments.points.lng": "float",
    "roadNetwork.intersections.segments.points.alt": "float",
  },
  "mdx-usd-assets-template": {
    "usdAssets.assets.bbox.dimension.x": "double",
    "usdAssets.assets.bbox.dimension.y": "double",
    "usdAssets.assets.bbox.dimension.z": "double",
  },
};
const managedBehaviorContainers = [
  "vss-behavior-analytics",
  "vss-behavior-analytics-thor-candidates",
];

const receipt = {
  schema_version: 1,
  tool_id: "thor-video-analytics-api-runtime",
  status: "failed",
  started_at: new Date().toISOString(),
  runtime: {},
  openapi: {},
  fixtures: {},
  requests: [],
  operations: {},
  cleanup: {},
  blockers: [],
  failure: null,
};

const stoppedContainers = [];
let oracleStarted = false;
let brokerlessStarted = false;
let cleanupAttempted = false;
let preFileSet = new Set();

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function sleep(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

function log(message) {
  process.stderr.write(`[video-analytics-runtime] ${message}\n`);
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function command(program, args, { allowFailure = false, timeout = 30_000 } = {}) {
  try {
    const result = await execFile(program, args, {
      cwd: repo,
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
      timeout,
    });
    return { code: 0, stdout: result.stdout, stderr: result.stderr };
  } catch (error) {
    if (!allowFailure) {
      throw new Error(
        `${program} ${args.join(" ")} failed: ${String(error.stderr || error.message).trim()}`,
      );
    }
    return {
      code: Number.isInteger(error.code) ? error.code : 1,
      stdout: error.stdout ?? "",
      stderr: error.stderr ?? String(error.message),
    };
  }
}

async function dockerContainerState(name) {
  const result = await command(
    "docker",
    ["inspect", "--format", "{{.State.Status}}", name],
    { allowFailure: true },
  );
  if (result.code !== 0) return null;
  return result.stdout.trim();
}

async function waitFor(predicate, description, timeoutMs = 30_000, intervalMs = 500) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const value = await predicate();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await sleep(intervalMs);
  }
  throw new Error(
    `Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ""}`,
  );
}

async function rawFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(options.timeoutMs ?? 20_000),
  });
  const body = Buffer.from(await response.arrayBuffer());
  let json = null;
  const contentType = response.headers.get("content-type") ?? "";
  if (body.length > 0 && contentType.includes("json")) {
    try {
      json = JSON.parse(body.toString("utf8"));
    } catch {
      json = null;
    }
  }
  return { response, body, json, contentType };
}

async function apiRequest({
  label,
  method = "GET",
  path,
  body,
  headers,
  expectedStatuses = [200],
  operationKey = null,
  polarity = "positive",
  baseUrl = apiBase,
}) {
  const started = Date.now();
  const result = await rawFetch(`${baseUrl}${path}`, { method, body, headers });
  const record = {
    label,
    method,
    path: path.replace(/video-analytics-api-[0-9-]+/g, "video-analytics-api-<reference>"),
    operation_key: operationKey,
    polarity,
    status: result.response.status,
    duration_ms: Date.now() - started,
    content_type: result.contentType,
    body_bytes: result.body.length,
    body_sha256: sha256(result.body),
  };
  receipt.requests.push(record);
  assert(
    expectedStatuses.includes(result.response.status),
    `${label} returned HTTP ${result.response.status}; expected ${expectedStatuses.join("/")}: ${result.body.toString("utf8").slice(0, 800)}`,
  );
  return result;
}

async function esRequest(path, { method = "GET", body = undefined, expectedStatuses = [200] } = {}) {
  const headers = body === undefined ? undefined : { "content-type": "application/json" };
  const result = await rawFetch(`${esBase}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  assert(
    expectedStatuses.includes(result.response.status),
    `Elasticsearch ${method} ${path} returned HTTP ${result.response.status}: ${result.body.toString("utf8").slice(0, 800)}`,
  );
  return result;
}

async function existsInEs(path) {
  const result = await rawFetch(`${esBase}${path}`, { method: "HEAD" });
  assert([200, 404].includes(result.response.status), `Unexpected Elasticsearch HEAD ${path}: ${result.response.status}`);
  return result.response.status === 200;
}

function jsonBody(value) {
  return {
    body: JSON.stringify(value),
    headers: { "content-type": "application/json" },
  };
}

function fileForm(field, path, mediaType = "application/json") {
  const form = new FormData();
  form.append(field, new Blob([readFileSync(path)], { type: mediaType }), basename(path));
  return form;
}

function query(path, parameters) {
  const url = new URL(path, "http://qualification.invalid");
  for (const [key, value] of Object.entries(parameters)) {
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, String(item));
    } else if (value !== null && value !== undefined) {
      url.searchParams.append(key, String(value));
    }
  }
  return `${url.pathname}${url.search}`;
}

function listFiles(path) {
  if (!existsSync(path)) return [];
  return readdirSync(path)
    .filter((name) => statSync(resolve(path, name)).isFile())
    .sort();
}

function flattenMapping(properties, prefix = "", result = {}) {
  for (const [name, definition] of Object.entries(properties ?? {})) {
    const path = prefix ? `${prefix}.${name}` : name;
    if (definition.type) result[path] = definition.type;
    if (definition.properties) flattenMapping(definition.properties, path, result);
  }
  return result;
}

async function verifyPersistentMappingTemplates() {
  const verified = {};
  for (const [name, expectedFields] of Object.entries(persistentMappingTemplates)) {
    const result = await esRequest(`/_index_template/${encodeURIComponent(name)}`);
    const templates = result.json?.index_templates ?? [];
    assert(templates.length === 1, `Expected exactly one persistent template named ${name}`);
    const template = templates[0].index_template;
    const fields = flattenMapping(template?.template?.mappings?.properties);
    for (const [field, type] of Object.entries(expectedFields)) {
      assert(fields[field] === type, `${name} mapping ${field} is ${fields[field] ?? "absent"}; expected ${type}`);
    }
    verified[name] = {
      priority: template.priority,
      index_patterns: template.index_patterns,
      fields: expectedFields,
    };
  }
  receipt.fixtures.persistent_mapping_templates = verified;
}

async function verifyOpenApi() {
  const expected = JSON.parse(readFileSync(expectedPath, "utf8"));
  const sourceBytes = readFileSync(openapiPath);
  const source = JSON.parse(sourceBytes.toString("utf8"));
  const sourceHash = sha256(sourceBytes);
  assert(sourceHash === expected.source_files[0].sha256, "Checked-in OpenAPI SHA does not match the expected manifest");

  const containerProgram = [
    "const fs=require('fs');",
    "const candidates=['/web-api-app/specification/openapi.json','/opt/mdx/vss-video-analytics-api/specification/openapi.json','specification/openapi.json'];",
    "let openapi=null;",
    "for(const p of candidates){try{openapi=fs.readFileSync(p);break}catch(e){}}",
    "if(openapi===null){process.exitCode=2}else{process.stdout.write(openapi)}",
  ].join("");
  const extracted = await command("docker", ["exec", apiContainer, "node", "-e", containerProgram]);
  const containerBytes = Buffer.from(extracted.stdout, "utf8");
  const containerHash = sha256(containerBytes);
  assert(containerHash === sourceHash, "Running container OpenAPI differs from the checked-in exact source");

  const actualOperations = [];
  for (const [path, pathItem] of Object.entries(source.paths)) {
    for (const method of ["get", "post"]) {
      if (pathItem[method]) actualOperations.push(`${method.toUpperCase()} ${path}`);
    }
  }
  actualOperations.sort();
  const expectedOperations = expected.operations
    .map((operation) => `${operation.method} ${operation.path}`)
    .sort();
  assert(JSON.stringify(actualOperations) === JSON.stringify(expectedOperations), "OpenAPI operation set differs from expected manifest");
  assert(actualOperations.length === 56, `Expected 56 operations, found ${actualOperations.length}`);

  receipt.openapi = {
    version: source.info?.version ?? null,
    source_sha256: sourceHash,
    container_sha256: containerHash,
    operation_count: actualOperations.length,
    method_counts: {
      GET: actualOperations.filter((value) => value.startsWith("GET ")).length,
      POST: actualOperations.filter((value) => value.startsWith("POST ")).length,
    },
    exact_operation_set_match: true,
  };
}

async function preflight() {
  for (const path of [openapiPath, expectedPath, behaviorConfig, semanticDocumentsPath, brokerlessConfigPath]) {
    assert(existsSync(path), `Required file missing: ${path}`);
  }
  assert(existsSync(imageDataDir), `Video Analytics upload directory missing: ${imageDataDir}`);
  preFileSet = new Set(listFiles(imageDataDir));

  const apiState = await dockerContainerState(apiContainer);
  assert(apiState === "running", `${apiContainer} must be running (found ${apiState ?? "absent"})`);
  assert((await dockerContainerState("kafka")) === "running", "kafka must be running");
  assert((await dockerContainerState("elasticsearch")) === "running", "elasticsearch must be running");
  assert((await dockerContainerState(oracleContainer)) === null, `${oracleContainer} already exists; remove it before retrying`);
  assert((await dockerContainerState(brokerlessContainer)) === null, `${brokerlessContainer} already exists; remove it before retrying`);

  for (const name of managedBehaviorContainers) {
    const state = await dockerContainerState(name);
    assert(state === "running", `${name} must start in the running state (found ${state ?? "absent"})`);
  }
  for (const index of mutableIndices) {
    assert(!(await existsInEs(`/${encodeURIComponent(index)}`)), `Safety preflight refused existing mutable index ${index}`);
  }
  for (const template of mutableTemplates) {
    assert(!(await existsInEs(`/_index_template/${encodeURIComponent(template)}`)), `Safety preflight refused existing mutable template ${template}`);
  }
  await verifyPersistentMappingTemplates();
  const livez = await rawFetch(`${apiBase}/livez`);
  assert(livez.response.status === 200 && livez.json?.isAlive === true, "Video Analytics /livez is not healthy");
  const cluster = await esRequest("/_cluster/health");
  assert(["green", "yellow"].includes(cluster.json?.status), `Elasticsearch health is ${cluster.json?.status}`);

  const versions = await Promise.all([
    command("docker", ["--version"]),
    command("docker", ["compose", "version"]),
    command("docker", ["inspect", "--format", "{{.Config.Image}}", apiContainer]),
    command("docker", ["image", "inspect", "--format", "{{.Id}}", behaviorImage]),
  ]);
  receipt.runtime = {
    docker: versions[0].stdout.trim(),
    compose: versions[1].stdout.trim(),
    api_container: apiContainer,
    api_image: versions[2].stdout.trim(),
    behavior_oracle_image: behaviorImage,
    behavior_oracle_image_id: versions[3].stdout.trim(),
    elasticsearch_status: cluster.json.status,
    kafka_container: "kafka",
    original_behavior_containers: [...managedBehaviorContainers],
    upload_file_count_before: preFileSet.size,
  };
}

async function isolateBehaviorConsumers() {
  log("Pausing the two live behavior consumers before Kafka mutation tests.");
  for (const name of managedBehaviorContainers) {
    await command("docker", ["stop", "--time", "20", name], { timeout: 30_000 });
    stoppedContainers.push(name);
  }

  log("Starting a disposable official behavior-analytics 3.2.1 consumer.");
  await command(
    "docker",
    [
      "run",
      "--detach",
      "--name",
      oracleContainer,
      "--network",
      "host",
      "--volume",
      `${behaviorConfig}:/resources/vss-behavior-analytics-config.json:ro`,
      behaviorImage,
      "python3",
      "apps/analytics/main_analytics_2d_app.py",
      "--config",
      "/resources/vss-behavior-analytics-config.json",
    ],
    { timeout: 30_000 },
  );
  oracleStarted = true;
  await waitFor(
    async () => {
      if ((await dockerContainerState(oracleContainer)) !== "running") return false;
      const logs = await command("docker", ["logs", oracleContainer], { allowFailure: true });
      const output = `${logs.stdout}\n${logs.stderr}`;
      return /mdx-notification/.test(output) && /Kafka consumer created and partitions assigned/.test(output);
    },
    "disposable behavior-analytics config listener",
    45_000,
    1_000,
  );
}

async function uploadDocument(docType, fixtureName) {
  const fixturePath = resolve(fixtures, fixtureName);
  const result = await apiRequest({
    label: `upload ${docType}`,
    method: "POST",
    path: `/config/upload-file/${docType}`,
    body: fileForm("configFiles", fixturePath),
    expectedStatuses: [201],
    operationKey: "POST /config/upload-file/{docType}",
  });
  assert(result.json?.success === true, `${docType} upload did not report success`);
}

async function seedSemanticDocuments() {
  const fixture = JSON.parse(readFileSync(semanticDocumentsPath, "utf8"));
  assert(Array.isArray(fixture.documents), "Semantic fixture must contain a documents array");
  assert(fixture.documents.length === 14, `Expected 14 semantic documents, found ${fixture.documents.length}`);

  const allowedIndices = new Set([behaviorIndex, ...semanticIndices]);
  const seededIndices = new Set();
  for (const document of fixture.documents) {
    assert(allowedIndices.has(document.index), `Semantic fixture references unmanaged index ${document.index}`);
    assert(typeof document.id === "string" && document.id.length > 0, "Semantic fixture document ID is missing");
    assert(document.source && typeof document.source === "object", `Semantic fixture ${document.id} has no source`);
    await esRequest(
      `/${encodeURIComponent(document.index)}/_doc/${encodeURIComponent(document.id)}`,
      {
        method: "PUT",
        body: document.source,
        expectedStatuses: [200, 201],
      },
    );
    seededIndices.add(document.index);
  }
  assert(
    JSON.stringify([...seededIndices].sort()) === JSON.stringify([...allowedIndices].sort()),
    "Semantic fixture did not seed every managed semantic index",
  );
  await esRequest(`/${[...seededIndices].map(encodeURIComponent).join(",")}/_refresh`, { method: "POST" });
  receipt.fixtures.semantic_documents = {
    document_count: fixture.documents.length,
    index_count: seededIndices.size,
    indices: [...seededIndices].sort(),
  };
}

async function seedFixturesAndPositivePosts() {
  await uploadDocument("calibration", "calibration.json");
  await uploadDocument("road-network", "road-network.json");
  await uploadDocument("usd-assets", "usd-assets.json");

  const calibration = JSON.parse(readFileSync(resolve(fixtures, "calibration.json"), "utf8"));
  const upsert = await apiRequest({
    label: "calibration upsert",
    method: "POST",
    path: "/config/calibration/upsert",
    ...jsonBody(calibration),
    expectedStatuses: [201],
    operationKey: "POST /config/calibration/upsert",
  });
  assert(upsert.json?.success === true, "Calibration upsert did not report success");

  const imageForm = new FormData();
  imageForm.append(
    "images",
    new Blob([readFileSync(resolve(fixtures, "calibration-image.svg"))], { type: "image/svg+xml" }),
    "calibration-image.svg",
  );
  imageForm.append(
    "imageMetadata",
    new Blob([readFileSync(resolve(fixtures, "calibration-image-metadata.json"))], { type: "application/json" }),
    "calibration-image-metadata.json",
  );
  const imageUpload = await apiRequest({
    label: "calibration image upload",
    method: "POST",
    path: "/config/calibration/images",
    body: imageForm,
    expectedStatuses: [201],
    operationKey: "POST /config/calibration/images",
  });
  assert(imageUpload.json?.success?.complete === true, "Calibration image upload was not complete");

  await esRequest(`/${behaviorIndex}/_doc/vss-oracle-behavior-1?refresh=true`, {
    method: "PUT",
    body: JSON.parse(readFileSync(resolve(fixtures, "behavior.json"), "utf8")),
    expectedStatuses: [200, 201],
  });
  await seedSemanticDocuments();
  const clusterPost = await apiRequest({
    label: "cluster label add",
    method: "POST",
    path: "/clustering/add-label",
    ...jsonBody({
      sensorId: sensor,
      modelVersion: "vss-oracle-model-1",
      clusterIndex: "7",
      label: "Thor Qualified",
    }),
    expectedStatuses: [201],
    operationKey: "POST /clustering/add-label",
  });
  assert(clusterPost.json?.success === true, "Cluster label add did not report success");

  const occupancy = await apiRequest({
    label: "occupancy reset",
    method: "POST",
    path: "/metrics/occupancy/reset",
    ...jsonBody({
      place,
      timestamp: pointTimestamp,
      occupancyReset: 2,
      objectType: "Person",
    }),
    expectedStatuses: [201],
    operationKey: "POST /metrics/occupancy/reset",
  });
  assert(occupancy.json?.success === true, "Occupancy reset did not report success");

  const configUpdate = await apiRequest({
    label: "behavior analytics dynamic config update",
    method: "POST",
    path: "/config/update/behavior-analytics",
    ...jsonBody({ app: [{ name: "behaviorWatermarkSec", value: "30" }] }),
    expectedStatuses: [201],
    operationKey: "POST /config/update/{docType}",
  });
  assert(configUpdate.json?.status === "pending", `Dynamic config did not enter pending state: ${JSON.stringify(configUpdate.json)}`);
  const referenceId = configUpdate.json.referenceId;
  assert(/^video-analytics-api-[0-9-]+$/.test(referenceId), "Dynamic config reference ID has an unexpected shape");

  const finalStatus = await waitFor(
    async () => {
      const status = await apiRequest({
        label: "dynamic config status poll",
        path: `/config/update/status/behavior-analytics/${referenceId}`,
        expectedStatuses: [200],
        operationKey: "GET /config/update/status/{docType}/{referenceId}",
      });
      if (["success", "partial-success", "failure"].includes(status.json?.status)) return status;
      return false;
    },
    "behavior-analytics dynamic config ACK",
    35_000,
    1_000,
  );
  assert(
    finalStatus.json.status === "success",
    `Dynamic config ACK was ${finalStatus.json.status}: ${finalStatus.json.error ?? "no error"}`,
  );

  await waitFor(
    async () => {
      const result = await command(
        "docker",
        [
          "exec",
          oracleContainer,
          "python3",
          "-c",
          "import pathlib; print(sum(1 for p in pathlib.Path('/tmp/checkpoint/config').glob('*.json')))",
        ],
        { allowFailure: true },
      );
      return result.code === 0 && Number(result.stdout.trim()) >= 1;
    },
    "behavior-analytics dynamic config checkpoint",
    15_000,
    500,
  );

  const occupancyReadback = await waitFor(
    async () => {
      await esRequest("/mdx-occupancy-reset/_refresh", { method: "POST" });
      const result = await esRequest("/mdx-occupancy-reset/_search", {
        method: "POST",
        body: { query: { term: { "place.keyword": place } } },
      });
      return result.json?.hits?.total?.value === 1 ? result : false;
    },
    "exact occupancy-reset Elasticsearch readback",
    10_000,
    250,
  );
  const labelReadback = await waitFor(
    async () => {
      await esRequest("/mdx-cluster-labels/_refresh", { method: "POST" });
      const result = await esRequest("/mdx-cluster-labels/_search", {
        method: "POST",
        body: { query: { term: { "sensorId.keyword": sensor } } },
      });
      return result.json?.hits?.total?.value === 1 ? result : false;
    },
    "exact cluster-label Elasticsearch readback",
    10_000,
    250,
  );

  receipt.fixtures = {
    ...receipt.fixtures,
    sensor,
    place,
    behavior_index: behaviorIndex,
    dynamic_config_reference_shape_valid: true,
    dynamic_config_status: finalStatus.json.status,
    dynamic_config_checkpoint_observed: true,
    occupancy_readback_count: occupancyReadback.json.hits.total.value,
    cluster_label_readback_count: labelReadback.json.hits.total.value,
  };
  return referenceId;
}

function getOperations(referenceId) {
  return [
    ["/metrics/average-speed", { fromTimestamp, toTimestamp, sensorId: sensor }],
    ["/metrics/flowrate", { toTimestamp: pointTimestamp, sensorId: sensor }],
    ["/metrics/average-speed-with-flowrate", { fromTimestamp: metricFromTimestamp, toTimestamp: metricToTimestamp, sensorId: sensor }],
    ["/metrics/average-speed-with-travel-time", { fromTimestamp, toTimestamp, place: corridor }],
    ["/metrics/tripwire/counts", { fromTimestamp, toTimestamp, sensorId: sensor }],
    ["/metrics/occupancy/tripwire", { timestamp: pointTimestamp, place, objectType: "Person" }],
    ["/metrics/tripwire/histogram", { sensorId: sensor, fromTimestamp, toTimestamp }],
    ["/metrics/occupancy/fov", { fromTimestamp, toTimestamp, sensorId: sensor }],
    ["/metrics/occupancy/fov/histogram", { sensorId: sensor, fromTimestamp, toTimestamp }],
    ["/metrics/occupancy/roi", { fromTimestamp, toTimestamp, sensorId: sensor }],
    ["/metrics/occupancy/roi/histogram", { sensorId: sensor, fromTimestamp, toTimestamp }],
    ["/metrics/occupancy/roi/mutually-exclusive", { place, timestamp: pointTimestamp }],
    ["/metrics/occupancy/tracker", { place, timestamp: pointTimestamp, timeWindowInMs: 1000 }],
    ["/metrics/occupancy/tracker/histogram", { place, fromTimestamp, toTimestamp, bucketCount: 4 }],
    ["/metrics/space-utilization/histogram", { fromTimestamp, toTimestamp, bucketCount: 4 }],
    ["/metrics/last-processed-timestamp", { sensorId: sensor }],
    ["/metrics/road-network/segment-speed", { place: city, fromTimestamp, toTimestamp, segmentInfo: true }],
    ["/tracker/unique-object-count", { timestamp: pointTimestamp, timeWindowInMs: 1000, sensorIds: [sensor, `${sensor}-secondary`] }],
    ["/tracker/unique-object-count-with-locations", { place, timestamp: pointTimestamp, timeWindowInMs: 1000 }],
    ["/tracker/unique-objects", { fromTimestamp, toTimestamp, sensorIds: [sensor, `${sensor}-secondary`] }],
    ["/tracker/behavior-locations", { fromTimestamp, toTimestamp, globalId: "vss-oracle-global" }],
    ["/tracker/last-record", { place, source: "RTLS" }],
    ["/frames", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/frames/enhanced", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/frames/bev", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/frames/alerts", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/frames/high-confidence-objects", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/frames/proximity-detection", { sensorId: sensor, fromTimestamp, toTimestamp }],
    ["/frames/pts", { sensorId: sensor, frameId: 30 }],
    ["/behavior", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/behavior/pts", { sensorId: sensor, endFrameId: 60, behaviorTimeInterval: 1 }],
    ["/alerts", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/alerts/severe", { sensorId: sensor, fromTimestamp, toTimestamp }],
    ["/incidents", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/incidents/severe", { sensorId: sensor, fromTimestamp, toTimestamp }],
    ["/clustering/behavior", { sensorId: sensor, clusterIndex: "7", fromTimestamp, toTimestamp, minBehaviorDistance: 0 }],
    ["/events/tripwire", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/events/amr", { place, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    ["/events/roi", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }],
    [`/config/update/status/behavior-analytics/${referenceId}`, {}],
    ["/config/calibration", { sensorId: sensor, emptyIfNotFound: false }],
    ["/config/calibration/last-modified-timestamp", {}],
    ["/config/road-network", {}],
    ["/config/usd-assets", {}],
    ["/config/calibration/image", { sensorId: sensor, view: "camera-view" }],
    ["/config/calibration/image-metadata", { sensorId: sensor, view: "camera-view" }],
    ["/sensor/lookup", { place, x: 0, y: 0, z: 0 }],
    ["/livez", {}],
  ];
}

async function runAllGetOperations(referenceId) {
  const operations = getOperations(referenceId);
  assert(operations.length === 48, `GET operation table has ${operations.length} entries, expected 48`);
  const observedKeys = [];
  const responses = new Map();
  for (const [path, parameters] of operations) {
    const templatedPath = path.startsWith("/config/update/status/")
      ? "/config/update/status/{docType}/{referenceId}"
      : path;
    const operationKey = `GET ${templatedPath}`;
    observedKeys.push(operationKey);
    const result = await apiRequest({
      label: `GET ${templatedPath}`,
      path: query(path, parameters),
      expectedStatuses: [200],
      operationKey,
    });
    responses.set(templatedPath, result);
  }

  const expected = JSON.parse(readFileSync(expectedPath, "utf8"));
  const expectedGets = expected.operations
    .filter((operation) => operation.method === "GET")
    .map((operation) => `GET ${operation.path}`)
    .sort();
  assert(JSON.stringify(observedKeys.sort()) === JSON.stringify(expectedGets), "GET runtime table does not cover the exact OpenAPI GET set");

  assert(responses.get("/livez").json?.isAlive === true, "/livez response was not alive");
  assert(responses.get("/frames/pts").json?.pts === 1000, "/frames/pts did not calculate 1000 ms");
  const behaviorPts = responses.get("/behavior/pts").json;
  assert(behaviorPts?.startPts === 1000 && behaviorPts?.endPts === 2000, "/behavior/pts did not calculate the expected range");
  assert(
    responses.get("/config/calibration").json?.sensors?.some((entry) => entry.id === sensor),
    "Calibration readback omitted the fixture sensor",
  );
  assert(responses.get("/config/road-network").json?.city === "VSSOracle", "Road-network readback omitted fixture city");
  assert(
    responses.get("/config/usd-assets").json?.sceneUrl === "local://vss-video-analytics-oracle/scene.usd",
    "USD-assets readback omitted fixture scene",
  );
  assert(
    responses.get("/config/calibration/image-metadata").json?.imageMetadata?.some((entry) => entry.sensorId === sensor),
    "Calibration image metadata readback omitted fixture sensor",
  );
  assert(
    sha256(responses.get("/config/calibration/image").body) === sha256(readFileSync(resolve(fixtures, "calibration-image.svg"))),
    "Calibration image bytes did not round-trip exactly",
  );
  const clusters = responses.get("/clustering/behavior").json?.clusters ?? [];
  assert(
    clusters.some((entry) => entry.clusterIndex === "7" && entry.label === "thor-qualified"),
    "Clustering readback omitted the normalized label",
  );

  const responseJson = (path) => {
    const body = responses.get(path)?.json;
    assert(body !== null && body !== undefined, `${path} did not return JSON`);
    return body;
  };
  const requireMatch = (path, values, predicate, description) => {
    assert(
      Array.isArray(values) && values.some(predicate),
      `${path} omitted ${description}: ${JSON.stringify(responseJson(path))}`,
    );
  };
  const positiveMetric = (value) => Number.parseFloat(value) > 0;

  const averageSpeed = responseJson("/metrics/average-speed").metrics;
  requireMatch("/metrics/average-speed", averageSpeed, (entry) => entry.direction === "N" && positiveMetric(entry.averageSpeed), "positive northbound average speed");
  const flowrate = responseJson("/metrics/flowrate").metrics;
  requireMatch("/metrics/flowrate", flowrate, (entry) => entry.direction === "N" && positiveMetric(entry.flowrate), "positive northbound flowrate");
  requireMatch(
    "/metrics/average-speed-with-flowrate",
    responseJson("/metrics/average-speed-with-flowrate").metrics,
    (entry) => entry.direction === "N" && positiveMetric(entry.averageSpeed) && positiveMetric(entry.flowrate),
    "combined speed and flowrate",
  );
  requireMatch(
    "/metrics/average-speed-with-travel-time",
    responseJson("/metrics/average-speed-with-travel-time").metrics,
    (entry) => entry.direction === "N" && positiveMetric(entry.averageSpeed) && positiveMetric(entry.corridorTravelTime),
    "combined speed and corridor travel time",
  );

  const tripwireCounts = responseJson("/metrics/tripwire/counts");
  requireMatch(
    "/metrics/tripwire/counts",
    tripwireCounts.tripwireMetrics,
    (entry) => entry.id === "vss-oracle-tripwire-1" && entry.events.some((event) => event.objectType === "Person" && event.actualCount === 1),
    "tripwire event count",
  );
  requireMatch(
    "/metrics/occupancy/tripwire",
    responseJson("/metrics/occupancy/tripwire").occupancy,
    (entry) => entry.objectType === "Person" && entry.count === 2,
    "reset-aware Person occupancy",
  );
  requireMatch(
    "/metrics/tripwire/histogram",
    responseJson("/metrics/tripwire/histogram").tripwires,
    (entry) => entry.id === "vss-oracle-tripwire-1" && entry.histogram.some((bucket) => bucket.events.some((event) => event.objectType === "Person" && event.actualCount === 1)),
    "non-empty tripwire histogram",
  );

  requireMatch(
    "/metrics/occupancy/fov",
    responseJson("/metrics/occupancy/fov").fovOccupancy,
    (entry) => entry.type === "Person" && entry.averageCount === 3,
    "FOV Person occupancy",
  );
  requireMatch(
    "/metrics/occupancy/fov/histogram",
    responseJson("/metrics/occupancy/fov/histogram").histogram,
    (bucket) => bucket.objects.some((entry) => entry.type === "Person" && entry.averageCount === 3),
    "FOV Person histogram bucket",
  );
  requireMatch(
    "/metrics/occupancy/roi",
    responseJson("/metrics/occupancy/roi").roiOccupancy,
    (entry) => entry.roiId === "vss-oracle-roi-1" && entry.objects.some((object) => object.type === "Person" && object.averageCount === 2 && object.uniqueObjectCount === 2),
    "ROI Person occupancy",
  );
  requireMatch(
    "/metrics/occupancy/roi/histogram",
    responseJson("/metrics/occupancy/roi/histogram").rois,
    (entry) => entry.id === "vss-oracle-roi-1" && entry.histogram.some((bucket) => bucket.objects.some((object) => object.type === "Person" && object.averageCount === 2)),
    "ROI Person histogram bucket",
  );
  const mutuallyExclusive = responseJson("/metrics/occupancy/roi/mutually-exclusive");
  assert(mutuallyExclusive.occupancy === 2 && mutuallyExclusive.objectType === "Person", `/metrics/occupancy/roi/mutually-exclusive omitted exact Person occupancy: ${JSON.stringify(mutuallyExclusive)}`);

  const trackerOccupancy = responseJson("/metrics/occupancy/tracker").trackerOccupancy;
  requireMatch("/metrics/occupancy/tracker", trackerOccupancy, (entry) => entry.type === "Person" && entry.count === 3, "RTLS Person count");
  requireMatch("/metrics/occupancy/tracker", trackerOccupancy, (entry) => entry.type === "AMR" && entry.count === 1, "AMR count");
  requireMatch(
    "/metrics/occupancy/tracker/histogram",
    responseJson("/metrics/occupancy/tracker/histogram").histogram,
    (bucket) => bucket.objects.some((entry) => entry.type === "Person" && entry.averageCount === 3),
    "tracker Person histogram bucket",
  );
  requireMatch(
    "/metrics/space-utilization/histogram",
    responseJson("/metrics/space-utilization/histogram").rois,
    (entry) => entry.id === "vss-oracle-space-1" && entry.histogram.some((bucket) => bucket.metrics.avgTotalSpace === 100 && bucket.metrics.avgSpaceOccupied === 40),
    "space-utilization metrics",
  );
  const lastProcessed = responseJson("/metrics/last-processed-timestamp").latestTimestamp;
  assert(lastProcessed?.sensorId === sensor && lastProcessed.timestamp === pointTimestamp, `/metrics/last-processed-timestamp omitted the seeded frame timestamp: ${JSON.stringify(responseJson("/metrics/last-processed-timestamp"))}`);
  requireMatch(
    "/metrics/road-network/segment-speed",
    responseJson("/metrics/road-network/segment-speed").roadSegments,
    (entry) => entry.id === "vss-oracle-segment-1" && entry.speed === 6 && entry.objectCount === 1,
    "road-segment speed",
  );

  const uniqueCount = responseJson("/tracker/unique-object-count").uniqueObjectCount;
  assert(uniqueCount === 1, `/tracker/unique-object-count expected 1, received ${JSON.stringify(uniqueCount)}`);
  const countWithLocations = responseJson("/tracker/unique-object-count-with-locations");
  requireMatch("/tracker/unique-object-count-with-locations", countWithLocations.objectCounts, (entry) => entry.type === "Person" && entry.count === 3, "RTLS Person count with locations");
  requireMatch("/tracker/unique-object-count-with-locations", countWithLocations.objectCounts, (entry) => entry.type === "AMR" && entry.count === 1, "AMR count with locations");
  requireMatch("/tracker/unique-object-count-with-locations", countWithLocations.locationsOfObjects, (entry) => entry.id === "rtls-object-1", "RTLS object location");
  requireMatch("/tracker/unique-object-count-with-locations", countWithLocations.locationsOfObjects, (entry) => entry.id === "amr-1", "AMR object location");
  requireMatch(
    "/tracker/unique-objects",
    responseJson("/tracker/unique-objects").uniqueObjects,
    (entry) => entry.globalId === "vss-oracle-global" && entry.matched.some((match) => match.sensorId === sensor),
    "global tracked object",
  );
  requireMatch(
    "/tracker/behavior-locations",
    responseJson("/tracker/behavior-locations").behaviors,
    (entry) => entry.id === "vss-oracle-video-analytics #-# 1" && entry.locations?.coordinates?.length === 2,
    "matched behavior locations",
  );
  const lastRecord = responseJson("/tracker/last-record").lastRecord;
  assert(lastRecord?.place === place && lastRecord.objectCounts?.some((entry) => entry.type === "Person" && entry.count === 3), `/tracker/last-record omitted the RTLS record: ${JSON.stringify(responseJson("/tracker/last-record"))}`);

  requireMatch("/frames", responseJson("/frames").frames, (entry) => entry.id === "150" && entry.sensorId === sensor, "raw frame");
  requireMatch("/frames/enhanced", responseJson("/frames/enhanced").enhancedFrames, (entry) => entry.id === "150" && entry.fov?.some((fov) => fov.type === "Person" && fov.count === 3), "enhanced frame");
  requireMatch("/frames/bev", responseJson("/frames/bev").bevFrames, (entry) => entry.id === "bev-150" && entry.objects?.some((object) => object.id === "bev-object-1"), "BEV frame");
  requireMatch("/frames/alerts", responseJson("/frames/alerts").alerts, (entry) => entry.sensorId === sensor && entry.proximity?.clusters?.some((cluster) => cluster.id === "vss-oracle-proximity-cluster-1") && entry.restrictedArea?.some((roi) => roi.roiId === "vss-oracle-roi-1"), "frame-level proximity and restricted-area alert");
  requireMatch("/frames/high-confidence-objects", responseJson("/frames/high-confidence-objects").objects, (entry) => entry.objectId === "raw-object-1" && entry.confidence === 0.97, "high-confidence object");
  const proximity = responseJson("/frames/proximity-detection");
  assert(proximity.id === "150" && proximity.clusters?.some((entry) => entry.id === "vss-oracle-proximity-cluster-1"), `/frames/proximity-detection omitted the fixture cluster: ${JSON.stringify(proximity)}`);
  requireMatch("/behavior", responseJson("/behavior").behaviors, (entry) => entry.Id === "vss-oracle-behavior-1" && entry.speed === 4, "behavior record");

  requireMatch("/alerts", responseJson("/alerts").alerts, (entry) => entry.Id === "vss-oracle-alert-1", "alert record");
  requireMatch("/alerts/severe", responseJson("/alerts/severe").severeAlerts?.sensors, (entry) => entry === sensor, "severe-alert sensor");
  requireMatch("/incidents", responseJson("/incidents").incidents, (entry) => entry.Id === "vss-oracle-incident-1" && entry.category === "Collision Detection", "incident record");
  requireMatch("/incidents/severe", responseJson("/incidents/severe").severeIncidents?.sensors, (entry) => entry === sensor, "severe-incident sensor");
  requireMatch("/events/tripwire", responseJson("/events/tripwire").tripwireEvents, (entry) => entry.Id === "vss-oracle-tripwire-event-1" && entry.event?.id === "vss-oracle-tripwire-1", "tripwire event");
  requireMatch("/events/amr", responseJson("/events/amr").amrEvents, (entry) => entry.events?.some((event) => event.objectId === "amr-1" && event.eventType === "route-change"), "AMR route-change event");
  requireMatch("/events/roi", responseJson("/events/roi").roiEvents, (entry) => entry.Id === "vss-oracle-roi-event-1" && entry.event?.id === "vss-oracle-roi-1", "ROI event");

  const updateStatus = responseJson("/config/update/status/{docType}/{referenceId}");
  assert(updateStatus.status === "success", `Dynamic configuration status was not success: ${JSON.stringify(updateStatus)}`);
  assert(typeof responseJson("/config/calibration/last-modified-timestamp").timestamp === "string", "Calibration last-modified timestamp was absent");
  requireMatch("/sensor/lookup", responseJson("/sensor/lookup").sensorIds, (entry) => entry === sensor, "coordinate-matched sensor");

  receipt.operations.get = {
    expected: 48,
    exercised: 48,
    all_http_200: true,
    exact_openapi_set: true,
    semantic_readbacks: {
      frames_pts_ms: 1000,
      behavior_pts: { start_ms: 1000, end_ms: 2000 },
      calibration_sensor: true,
      road_network_city: true,
      usd_scene: true,
      calibration_image_exact_bytes: true,
      cluster_label: "thor-qualified",
      non_empty_data_endpoints: 40,
      analytics_metrics: {
        average_speed: true,
        flowrate: true,
        travel_time: true,
        tripwire: true,
        occupancy: true,
        space_utilization: true,
        road_segment_speed: true,
      },
      tracker_and_events: true,
      raw_enhanced_bev_frames: true,
      alerts_and_incidents: true,
      sensor_lookup: true,
    },
  };
}

async function runNegativePosts() {
  const emptyForm = () => new FormData();
  const cases = [
    ["POST /metrics/occupancy/reset", "/metrics/occupancy/reset", jsonBody({})],
    ["POST /clustering/add-label", "/clustering/add-label", jsonBody({})],
    ["POST /config/upload-file/{docType}", "/config/upload-file/calibration", { body: emptyForm() }],
    ["POST /config/update/{docType}", "/config/update/behavior-analytics", jsonBody({})],
    ["POST /config/calibration/upsert", "/config/calibration/upsert", jsonBody({})],
    ["POST /config/calibration/delete-sensor", "/config/calibration/delete-sensor", jsonBody({})],
    ["POST /config/calibration/images", "/config/calibration/images", { body: emptyForm() }],
    ["POST /config/calibration/delete-images", "/config/calibration/delete-images", jsonBody({})],
  ];
  for (const [operationKey, path, request] of cases) {
    const result = await apiRequest({
      label: `${operationKey} adjacent negative`,
      method: "POST",
      path,
      ...request,
      expectedStatuses: [400, 404, 415, 422],
      operationKey,
      polarity: "negative",
    });
    assert(result.response.status < 500, `${operationKey} adjacent negative returned 5xx`);
  }
  receipt.operations.post_negatives = {
    expected: 8,
    exercised: 8,
    exact_openapi_set: true,
    no_5xx: true,
  };
}

async function runPositiveDeletes() {
  const deleteImages = await apiRequest({
    label: "calibration image delete",
    method: "POST",
    path: "/config/calibration/delete-images",
    ...jsonBody({ calibrationImages: [{ sensorId: sensor, view: "camera-view" }] }),
    expectedStatuses: [201],
    operationKey: "POST /config/calibration/delete-images",
  });
  assert(deleteImages.json?.success?.complete === true, "Calibration image deletion was not complete");

  const deleteSensor = await apiRequest({
    label: "calibration sensor delete",
    method: "POST",
    path: "/config/calibration/delete-sensor",
    ...jsonBody({ sensorIds: [sensor] }),
    expectedStatuses: [201],
    operationKey: "POST /config/calibration/delete-sensor",
  });
  assert(deleteSensor.json?.success?.complete === true, "Calibration sensor deletion was not complete");

  await waitFor(
    async () => {
      const result = await command(
        "docker",
        [
          "exec",
          oracleContainer,
          "python3",
          "-c",
          "import pathlib; print(sum(1 for p in pathlib.Path('/tmp/checkpoint/calibration').glob('*.json')))",
        ],
        { allowFailure: true },
      );
      return result.code === 0 && Number(result.stdout.trim()) >= 3;
    },
    "behavior-analytics calibration upload/upsert/delete checkpoints",
    15_000,
    500,
  );
  receipt.fixtures.dynamic_calibration_checkpoints_observed = true;
  receipt.operations.post = {
    expected: 8,
    exercised: 8,
    all_positive_201: true,
    exact_openapi_set: true,
    upload_document_types: ["calibration", "road-network", "usd-assets"],
    calibration_delete_readback: true,
    image_delete_readback: true,
  };
}

async function runBrokerlessScenario() {
  log("Exercising the official API with kafka.brokers=null on isolated port 18081.");
  const containerConfigPath = "/opt/mdx/vss-video-analytics-api/configs/vss-video-analytics-api-brokerless.json";
  await command(
    "docker",
    [
      "run",
      "--detach",
      "--name",
      brokerlessContainer,
      "--network",
      "host",
      "--volume",
      `${brokerlessConfigPath}:${containerConfigPath}:ro`,
      apiImage,
      "node",
      "index.js",
      "--config",
      containerConfigPath,
    ],
    { timeout: 30_000 },
  );
  brokerlessStarted = true;

  await waitFor(
    async () => {
      if ((await dockerContainerState(brokerlessContainer)) !== "running") return false;
      const result = await rawFetch(`${brokerlessApiBase}/livez`, { timeoutMs: 2_000 });
      return result.response.status === 200 && result.json?.isAlive === true;
    },
    "brokerless Video Analytics API livez",
    30_000,
    500,
  );

  const livez = await apiRequest({
    label: "brokerless GET /livez",
    path: "/livez",
    expectedStatuses: [200],
    operationKey: "BROKERLESS GET /livez",
    polarity: "brokerless",
    baseUrl: brokerlessApiBase,
  });
  assert(livez.json?.isAlive === true, "Brokerless API /livez was not alive");

  const frames = await apiRequest({
    label: "brokerless non-Kafka raw-frame read",
    path: query("/frames", { sensorId: sensor, fromTimestamp, toTimestamp, maxResultSize: 1 }),
    expectedStatuses: [200],
    operationKey: "BROKERLESS GET /frames",
    polarity: "brokerless",
    baseUrl: brokerlessApiBase,
  });
  assert(frames.json?.frames?.some((entry) => entry.id === "150" && entry.sensorId === sensor), `Brokerless non-Kafka read omitted the raw frame: ${JSON.stringify(frames.json)}`);

  const brokerRequired = await apiRequest({
    label: "brokerless Kafka-dependent tracker request",
    path: query("/tracker/unique-object-count-with-locations", { place }),
    expectedStatuses: [422],
    operationKey: "BROKERLESS GET /tracker/unique-object-count-with-locations",
    polarity: "brokerless_expected_error",
    baseUrl: brokerlessApiBase,
  });
  assert(
    brokerRequired.json?.error === "A message broker like 'kafka' is required to consume messages which provide real time locations and object count.",
    `Brokerless tracker endpoint returned an unexpected error contract: ${JSON.stringify(brokerRequired.json)}`,
  );

  const logs = await command("docker", ["logs", brokerlessContainer], { allowFailure: true });
  const logText = `${logs.stdout}\n${logs.stderr}`;
  assert(!/KafkaJSConnectionError|Connection error.*9092/i.test(logText), "Brokerless API attempted a Kafka connection despite brokers=null");
  receipt.operations.brokerless = {
    config_brokers: null,
    api_started: true,
    livez_http_status: 200,
    non_kafka_endpoint: { path: "/frames", http_status: 200, fixture_frame_id: "150" },
    kafka_dependent_endpoint: {
      path: "/tracker/unique-object-count-with-locations",
      http_status: 422,
      exact_message_contract: true,
    },
    kafka_connection_attempt_observed: false,
  };
}

async function cleanup() {
  if (cleanupAttempted) return;
  cleanupAttempted = true;
  const failures = [];
  log("Cleaning only qualifier-owned indices, templates, files, and containers.");

  for (const index of mutableIndices) {
    try {
      await esRequest(`/${encodeURIComponent(index)}`, { method: "DELETE", expectedStatuses: [200, 404] });
    } catch (error) {
      failures.push(`delete index ${index}: ${error.message}`);
    }
  }
  for (const template of mutableTemplates) {
    try {
      await esRequest(`/_index_template/${encodeURIComponent(template)}`, { method: "DELETE", expectedStatuses: [200, 404] });
    } catch (error) {
      failures.push(`delete template ${template}: ${error.message}`);
    }
  }

  if (oracleStarted || (await dockerContainerState(oracleContainer)) !== null) {
    const removed = await command("docker", ["rm", "--force", oracleContainer], {
      allowFailure: true,
      timeout: 30_000,
    });
    if (removed.code !== 0) failures.push(`remove oracle container: ${removed.stderr.trim()}`);
  }
  if (brokerlessStarted || (await dockerContainerState(brokerlessContainer)) !== null) {
    const removed = await command("docker", ["rm", "--force", brokerlessContainer], {
      allowFailure: true,
      timeout: 30_000,
    });
    if (removed.code !== 0) failures.push(`remove brokerless API container: ${removed.stderr.trim()}`);
  }

  for (const name of stoppedContainers) {
    const started = await command("docker", ["start", name], { allowFailure: true, timeout: 30_000 });
    if (started.code !== 0) failures.push(`restart ${name}: ${started.stderr.trim()}`);
  }
  for (const name of stoppedContainers) {
    try {
      await waitFor(async () => (await dockerContainerState(name)) === "running", `${name} restoration`, 30_000, 500);
    } catch (error) {
      failures.push(error.message);
    }
  }

  const lingeringIndices = [];
  const lingeringTemplates = [];
  for (const index of mutableIndices) if (await existsInEs(`/${encodeURIComponent(index)}`)) lingeringIndices.push(index);
  for (const template of mutableTemplates) if (await existsInEs(`/_index_template/${encodeURIComponent(template)}`)) lingeringTemplates.push(template);
  let afterFiles = new Set(listFiles(imageDataDir));
  const qualifierFiles = [...afterFiles].filter((name) => !preFileSet.has(name));
  for (const name of qualifierFiles) {
    try {
      unlinkSync(resolve(imageDataDir, name));
    } catch (error) {
      failures.push(`delete qualifier upload ${name}: ${error.message}`);
    }
  }
  afterFiles = new Set(listFiles(imageDataDir));
  const newFiles = [...afterFiles].filter((name) => !preFileSet.has(name));
  const missingFiles = [...preFileSet].filter((name) => !afterFiles.has(name));
  if (lingeringIndices.length) failures.push(`lingering indices: ${lingeringIndices.join(", ")}`);
  if (lingeringTemplates.length) failures.push(`lingering templates: ${lingeringTemplates.join(", ")}`);
  if (newFiles.length) failures.push(`new upload files remain: ${newFiles.join(", ")}`);
  if (missingFiles.length) failures.push(`pre-existing upload files missing: ${missingFiles.join(", ")}`);
  if ((await dockerContainerState(oracleContainer)) !== null) failures.push("oracle container still exists");
  if ((await dockerContainerState(brokerlessContainer)) !== null) failures.push("brokerless API container still exists");

  receipt.cleanup = {
    attempted: true,
    qualifier_indices_absent: lingeringIndices.length === 0,
    qualifier_templates_absent: lingeringTemplates.length === 0,
    upload_file_set_exact: newFiles.length === 0 && missingFiles.length === 0,
    upload_file_count_after: afterFiles.size,
    disposable_container_absent: (await dockerContainerState(oracleContainer)) === null,
    brokerless_container_absent: (await dockerContainerState(brokerlessContainer)) === null,
    original_behavior_containers_restored: (
      await Promise.all(managedBehaviorContainers.map((name) => dockerContainerState(name)))
    ).every((state) => state === "running"),
    failures,
  };
  if (failures.length) throw new Error(`Cleanup incomplete: ${failures.join("; ")}`);
}

async function main() {
  try {
    log("Validating runtime prerequisites and exact OpenAPI identity.");
    await preflight();
    await verifyOpenApi();
    await isolateBehaviorConsumers();
    log("Creating namespaced fixtures and exercising positive POST workflows.");
    const referenceId = await seedFixturesAndPositivePosts();
    log("Exercising all 48 GET operations with contract-valid parameters.");
    await runAllGetOperations(referenceId);
    log("Exercising adjacent-negative validation for all 8 POST operations.");
    await runNegativePosts();
    log("Exercising reversible calibration deletion operations.");
    await runPositiveDeletes();
    await runBrokerlessScenario();
    await cleanup();
    receipt.status = "passed";
  } catch (error) {
    receipt.failure = error.message;
    try {
      await cleanup();
    } catch (cleanupError) {
      receipt.failure = `${receipt.failure}; ${cleanupError.message}`;
    }
  } finally {
    receipt.finished_at = new Date().toISOString();
    receipt.request_counts = {
      total: receipt.requests.length,
      positive: receipt.requests.filter((item) => item.polarity === "positive").length,
      negative: receipt.requests.filter((item) => item.polarity === "negative").length,
      status_5xx: receipt.requests.filter((item) => item.status >= 500).length,
    };
    process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  }
  process.exitCode = receipt.status === "passed" ? 0 : 1;
}

await main();
