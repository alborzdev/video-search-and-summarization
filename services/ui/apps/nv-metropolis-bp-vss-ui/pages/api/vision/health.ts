// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from "next";

type ServiceKey =
  | "agent"
  | "analytics"
  | "embedding"
  | "llm"
  | "perception"
  | "video"
  | "vlm";

interface ServiceHealth {
  key: ServiceKey;
  label: string;
  latencyMs: number | null;
  ok: boolean;
}

interface ThorMetrics {
  activeStreams: number | null;
  gpuTemperatureC: number | null;
  gpuUtilizationPercent: number | null;
  memoryTotalBytes: number | null;
  memoryUsedBytes: number | null;
  powerWatts: number | null;
  sampleAgeSeconds: number | null;
}

export function metricValue(
  metrics: string,
  name: string,
  labelsPattern = ""
): number | null {
  const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = metrics.match(
    new RegExp(`^${escapedName}${labelsPattern}\\s+([0-9.eE+-]+)$`, "m")
  );
  const value = match ? Number(match[1]) : Number.NaN;
  return Number.isFinite(value) ? value : null;
}

async function readThorMetrics(): Promise<ThorMetrics | null> {
  const endpoint =
    process.env.TEGRASTATS_METRICS_URL || "http://172.17.0.1:19101/metrics";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1_500);
  try {
    const response = await fetch(endpoint, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const metrics = await response.text();
    if (metricValue(metrics, "jetson_tegrastats_up") !== 1) return null;
    const gpuRatio = metricValue(
      metrics,
      "jetson_tegrastats_gpu_utilization_ratio"
    );
    const gpuPower = metricValue(
      metrics,
      "jetson_tegrastats_power_milliwatts",
      '\\{rail="VDD_GPU",aggregation="current"\\}'
    );
    let activeStreams: number | null = null;
    try {
      const streamsResponse = await fetch(
        process.env.VST_STREAMS_URL ||
          "http://127.0.0.1:30888/vst/api/v1/live/streams",
        { cache: "no-store", signal: controller.signal }
      );
      if (streamsResponse.ok) {
        const catalog = (await streamsResponse.json()) as Array<
          Record<string, unknown[]>
        >;
        activeStreams = catalog.reduce(
          (count, sensor) =>
            count +
            Object.values(sensor).reduce(
              (total, streams) => total + streams.length,
              0
            ),
          0
        );
      }
    } catch {
      // Hardware measurements remain useful when the stream count is unavailable.
    }
    return {
      activeStreams,
      gpuTemperatureC: metricValue(
        metrics,
        "jetson_tegrastats_temperature_celsius",
        '\\{zone="gpu"\\}'
      ),
      gpuUtilizationPercent: gpuRatio === null ? null : gpuRatio * 100,
      memoryTotalBytes: metricValue(
        metrics,
        "jetson_tegrastats_ram_total_bytes"
      ),
      memoryUsedBytes: metricValue(metrics, "jetson_tegrastats_ram_used_bytes"),
      powerWatts: gpuPower === null ? null : gpuPower / 1_000,
      sampleAgeSeconds: metricValue(
        metrics,
        "jetson_tegrastats_sample_age_seconds"
      ),
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

async function probe(
  key: ServiceKey,
  label: string,
  url: string
): Promise<ServiceHealth> {
  const started = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3_000);
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: controller.signal,
    });
    return { key, label, latencyMs: Date.now() - started, ok: response.ok };
  } catch {
    return { key, label, latencyMs: null, ok: false };
  } finally {
    clearTimeout(timeout);
  }
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed." });
  }

  const [video, agent, analytics, perception, embedding, vlm, llm, thor] =
    await Promise.all([
      probe(
        "video",
        "Video I/O",
        process.env.VST_HEALTH_URL || "http://127.0.0.1:30888/health"
      ),
      probe(
        "agent",
        "Vision Agent",
        process.env.VISION_AGENT_HEALTH_URL || "http://127.0.0.1:8100/health"
      ),
      probe(
        "analytics",
        "Analytics",
        process.env.VA_MCP_HEALTH_URL || "http://127.0.0.1:9901/health"
      ),
      probe(
        "perception",
        "Detection + tracking",
        process.env.RTVI_CV_HEALTH_URL ||
          "http://127.0.0.1:9000/api/v1/health/get-dsready-state"
      ),
      probe(
        "embedding",
        "Video embedding",
        process.env.RTVI_EMBED_HEALTH_URL || "http://127.0.0.1:8017/v1/ready"
      ),
      probe(
        "vlm",
        "Cosmos visual reasoning",
        process.env.RTVI_VLM_HEALTH_URL ||
          "http://127.0.0.1:8018/v1/health/ready"
      ),
      probe(
        "llm",
        "Nemotron synthesis",
        process.env.NEMOTRON_HEALTH_URL || "http://127.0.0.1:30081/v1/models"
      ),
      readThorMetrics(),
    ]);
  const services = [video, agent, analytics, perception, embedding, vlm, llm];
  const healthy = services.filter((service) => service.ok).length;
  const status =
    healthy === services.length ? "online" : healthy ? "degraded" : "offline";

  res.setHeader("Cache-Control", "no-store");
  return res.status(status === "offline" ? 503 : 200).json({
    checkedAt: new Date().toISOString(),
    services,
    status,
    thor,
  });
}
