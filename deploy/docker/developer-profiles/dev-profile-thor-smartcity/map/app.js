// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

"use strict";

const API_BASE = "/video-analytics-api";
const SENSOR_ID = "Agnew_head_on";
const PLACE = "city=Montague/intersection=Agnew_head_on";
const SVG_NS = "http://www.w3.org/2000/svg";
const VIEWPORT = { width: 1200, height: 800, padding: 90 };

const elements = {
  roadLayer: document.querySelector("#road-layer"),
  sensorLayer: document.querySelector("#sensor-layer"),
  gridLayer: document.querySelector("#grid-layer"),
  statusDot: document.querySelector("#status-dot"),
  systemStatus: document.querySelector("#system-status"),
  lastUpdate: document.querySelector("#last-update"),
  averageSpeed: document.querySelector("#average-speed"),
  flowRate: document.querySelector("#flow-rate"),
  incidentCount: document.querySelector("#incident-count"),
  incidentList: document.querySelector("#incident-list"),
  segmentId: document.querySelector("#segment-id"),
  segmentDirection: document.querySelector("#segment-direction"),
  clearSelection: document.querySelector("#clear-selection"),
  dataSource: document.querySelector("#data-source"),
};

function svgElement(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

async function fetchWithFallback(apiPath, localPath) {
  try {
    return { payload: await fetchJson(apiPath), live: true };
  } catch (_error) {
    return { payload: await fetchJson(localPath), live: false };
  }
}

function allCoordinates(roadNetwork, calibration) {
  const coordinates = [];
  for (const intersection of roadNetwork.intersections || []) {
    for (const segment of intersection.segments || []) {
      for (const point of segment.points || [segment.start, segment.end]) {
        if (Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon ?? point?.lng))) {
          coordinates.push({ lat: Number(point.lat), lon: Number(point.lon ?? point.lng) });
        }
      }
    }
  }
  for (const sensor of calibration.sensors || []) {
    const point = sensor.geoLocation;
    if (Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lng ?? point?.lon))) {
      coordinates.push({ lat: Number(point.lat), lon: Number(point.lng ?? point.lon) });
    }
  }
  return coordinates;
}

function projector(coordinates) {
  const longitudes = coordinates.map((point) => point.lon);
  const latitudes = coordinates.map((point) => point.lat);
  const minLon = Math.min(...longitudes);
  const maxLon = Math.max(...longitudes);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const lonSpan = Math.max(maxLon - minLon, 0.0001);
  const latSpan = Math.max(maxLat - minLat, 0.0001);
  const usableWidth = VIEWPORT.width - VIEWPORT.padding * 2;
  const usableHeight = VIEWPORT.height - VIEWPORT.padding * 2;
  return (point) => ({
    x: VIEWPORT.padding + ((Number(point.lon ?? point.lng) - minLon) / lonSpan) * usableWidth,
    y: VIEWPORT.height - VIEWPORT.padding - ((Number(point.lat) - minLat) / latSpan) * usableHeight,
  });
}

function drawGrid() {
  for (let x = 100; x < VIEWPORT.width; x += 100) {
    elements.gridLayer.append(svgElement("line", { x1: x, y1: 0, x2: x, y2: VIEWPORT.height }));
  }
  for (let y = 100; y < VIEWPORT.height; y += 100) {
    elements.gridLayer.append(svgElement("line", { x1: 0, y1: y, x2: VIEWPORT.width, y2: y }));
  }
}

function selectSegment(path, segment) {
  document.querySelectorAll(".road-segment.selected").forEach((node) => node.classList.remove("selected"));
  path.classList.add("selected");
  elements.segmentId.textContent = segment.id;
  elements.segmentDirection.textContent = segment.direction || "Unknown";
}

function clearSelection() {
  document.querySelectorAll(".road-segment.selected").forEach((node) => node.classList.remove("selected"));
  elements.segmentId.textContent = "No segment selected";
  elements.segmentDirection.textContent = "—";
}

function renderMap(roadNetwork, calibration) {
  elements.roadLayer.replaceChildren();
  elements.sensorLayer.replaceChildren();
  elements.gridLayer.replaceChildren();
  drawGrid();

  const coordinates = allCoordinates(roadNetwork, calibration);
  if (!coordinates.length) throw new Error("No local road coordinates were available");
  const project = projector(coordinates);

  for (const intersection of roadNetwork.intersections || []) {
    for (const segment of intersection.segments || []) {
      const points = (segment.points || [segment.start, segment.end]).map(project);
      const value = points.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
      const halo = svgElement("polyline", { points: value, class: "road-halo" });
      const path = svgElement("polyline", {
        points: value,
        class: "road-segment",
        tabindex: "0",
        role: "button",
        "aria-label": `Road segment ${segment.id}, direction ${segment.direction || "unknown"}`,
      });
      const activate = () => selectSegment(path, segment);
      path.addEventListener("click", activate);
      path.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
      elements.roadLayer.append(halo, path);
    }
  }

  for (const sensor of calibration.sensors || []) {
    const center = project({ lat: sensor.geoLocation.lat, lon: sensor.geoLocation.lng ?? sensor.geoLocation.lon });
    const group = svgElement("g", { transform: `translate(${center.x.toFixed(2)} ${center.y.toFixed(2)})` });
    group.append(
      svgElement("circle", { class: "camera-ring", r: 18 }),
      svgElement("circle", { class: "camera-core", r: 5 }),
      svgElement("line", { class: "camera-heading", x1: 0, y1: 0, x2: 25, y2: -25 }),
    );
    const label = svgElement("text", { class: "sensor-label", x: 31, y: -25 });
    label.textContent = sensor.id;
    const subtitle = svgElement("text", { class: "sensor-subtitle", x: 31, y: -7 });
    subtitle.textContent = "CAMERA / ACTIVE";
    group.append(label, subtitle);
    elements.sensorLayer.append(group);
  }
}

function firstMetric(metrics, key) {
  const values = Array.isArray(metrics) ? metrics : metrics?.metrics;
  const match = Array.isArray(values) ? values.find((item) => item?.[key] != null) : null;
  return match?.[key] ?? "—";
}

function renderIncidents(payload) {
  const incidents = Array.isArray(payload) ? payload : payload?.incidents || [];
  elements.incidentCount.textContent = String(incidents.length);
  elements.incidentList.replaceChildren();
  if (!incidents.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No incidents in the current local window.";
    elements.incidentList.append(empty);
    return;
  }
  for (const incident of incidents.slice(0, 6)) {
    const item = document.createElement("article");
    item.className = "incident";
    const title = document.createElement("strong");
    title.textContent = incident.category || incident.type || incident.analyticsModule?.description || "Traffic incident";
    const detail = document.createElement("span");
    const timestamp = incident.timestamp || incident.end;
    const displayTime = timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "time unavailable";
    detail.textContent = `${incident.sensorId || SENSOR_ID} · ${displayTime}`;
    item.append(title, detail);
    elements.incidentList.append(item);
  }
}

function renderIncidentUnavailable() {
  elements.incidentCount.textContent = "—";
  elements.incidentList.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = "Local analytics API is unavailable; the road baseline remains usable.";
  elements.incidentList.append(empty);
}

function metricQuery() {
  const to = new Date();
  const from = new Date(to.getTime() - 15 * 60 * 1000);
  return new URLSearchParams({
    fromTimestamp: from.toISOString(),
    toTimestamp: to.toISOString(),
    place: PLACE,
    flowrateUnit: "/min",
  });
}

async function refreshTelemetry() {
  const query = metricQuery();
  const incidentQuery = new URLSearchParams({ sensorId: SENSOR_ID, maxResultSize: "6" });
  const [health, metrics, incidents] = await Promise.allSettled([
    fetch(`${API_BASE}/livez`, { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error("health check failed");
      return true;
    }),
    fetchJson(`${API_BASE}/metrics/average-speed-with-flowrate?${query}`),
    fetchJson(`${API_BASE}/incidents?${incidentQuery}`),
  ]);

  const online = health.status === "fulfilled";
  elements.statusDot.className = `status-dot ${online ? "online" : "offline"}`;
  elements.systemStatus.textContent = online ? "Local analytics online" : "Local baseline · API unavailable";
  elements.lastUpdate.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  if (metrics.status === "fulfilled") {
    elements.averageSpeed.textContent = firstMetric(metrics.value, "averageSpeed");
    elements.flowRate.textContent = firstMetric(metrics.value, "flowrate");
  }
  if (incidents.status === "fulfilled") {
    renderIncidents(incidents.value);
  } else {
    renderIncidentUnavailable();
  }
}

async function initialize() {
  elements.clearSelection.addEventListener("click", clearSelection);
  try {
    const [calibration, roads] = await Promise.all([
      fetchWithFallback(`${API_BASE}/config/calibration`, "./assets/calibration.json"),
      fetchWithFallback(`${API_BASE}/config/road-network`, "./assets/road-network.json"),
    ]);
    renderMap(roads.payload, calibration.payload);
    const liveConfig = roads.live && calibration.live;
    elements.dataSource.textContent = liveConfig ? "Analytics API" : "Bundled baseline";
    await refreshTelemetry();
    window.setInterval(refreshTelemetry, 10_000);
  } catch (error) {
    elements.statusDot.className = "status-dot offline";
    elements.systemStatus.textContent = "Map initialization failed";
    elements.dataSource.textContent = error instanceof Error ? error.message : "Unknown error";
  }
}

initialize();
