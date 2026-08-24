// SPDX-License-Identifier: MIT

interface CountResponse {
  count?: number;
}

interface LatestDocumentResponse {
  hits?: {
    hits?: Array<{ _source?: { "@timestamp"?: string; timestamp?: string } }>;
    total?: number | { value?: number };
  };
}

export interface SourceIntelligenceResult {
  captionSegments: number | null;
  evidenceEvents: number | null;
  generatedAt: string;
  indexingDelaySeconds: number | null;
  lastCaptionAt: string | null;
  lastSemanticAt: string | null;
  semanticFresh: boolean | null;
  semanticSegments: number | null;
  source: { name: string; sensorId: string };
  trackedObservations: number | null;
}

async function countDocuments(
  elasticsearchUrl: string,
  indexPattern: string,
  fields: string[],
  values: string[]
): Promise<number | null> {
  try {
    const response = await fetch(
      `${elasticsearchUrl.replace(/\/$/, "")}/${indexPattern}/_count`,
      {
        body: JSON.stringify({
          query: {
            bool: {
              minimum_should_match: 1,
              should: fields.flatMap((field) =>
                values.map((value) => ({ term: { [field]: value } }))
              ),
            },
          },
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }
    );
    if (!response.ok) return null;
    const payload = (await response.json()) as CountResponse;
    return Number.isFinite(payload.count) ? Number(payload.count) : null;
  } catch {
    return null;
  }
}

async function latestDocumentTimestamp(
  elasticsearchUrl: string,
  indexPattern: string,
  fields: string[],
  values: string[]
): Promise<string | null> {
  try {
    const response = await fetch(
      `${elasticsearchUrl.replace(/\/$/, "")}/${indexPattern}/_search`,
      {
        body: JSON.stringify({
          _source: ["timestamp"],
          query: {
            bool: {
              minimum_should_match: 1,
              should: fields.flatMap((field) =>
                values.map((value) => ({ term: { [field]: value } }))
              ),
            },
          },
          size: 1,
          sort: [{ timestamp: { order: "desc" } }],
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }
    );
    if (!response.ok) return null;
    const payload = (await response.json()) as LatestDocumentResponse;
    const timestamp = payload.hits?.hits?.[0]?._source?.timestamp;
    return typeof timestamp === "string" && Number.isFinite(Date.parse(timestamp))
      ? timestamp
      : null;
  } catch {
    return null;
  }
}

async function captionStatus(
  elasticsearchUrl: string,
  sensorId: string
): Promise<{ count: number | null; latest: string | null }> {
  const index = `default_${sensorId.replaceAll("-", "_").toLowerCase()}`;
  try {
    const response = await fetch(
      `${elasticsearchUrl.replace(/\/$/, "")}/${encodeURIComponent(index)}/_search`,
      {
        body: JSON.stringify({
          _source: ["@timestamp"],
          query: {
            term: { "metadata.content_metadata.doc_type.keyword": "raw_events" },
          },
          size: 1,
          sort: [{ "@timestamp": { order: "desc", unmapped_type: "date" } }],
          track_total_hits: true,
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }
    );
    if (response.status === 404) return { count: 0, latest: null };
    if (!response.ok) return { count: null, latest: null };
    const payload = (await response.json()) as LatestDocumentResponse;
    const total = payload.hits?.total;
    const count =
      typeof total === "number"
        ? total
        : typeof total?.value === "number"
        ? total.value
        : null;
    const latest = payload.hits?.hits?.[0]?._source?.["@timestamp"];
    return {
      count,
      latest:
        typeof latest === "string" && Number.isFinite(Date.parse(latest))
          ? latest
          : null,
    };
  } catch {
    return { count: null, latest: null };
  }
}

/**
 * Reads source-scoped index facts without changing Elasticsearch or starting
 * analysis. API routes and server aggregators share this single adapter.
 */
export async function fetchSourceIntelligence(
  sensorId: string,
  name: string
): Promise<SourceIntelligenceResult | null> {
  const elasticsearchUrl =
    process.env.ELASTIC_SEARCH_ENDPOINT || "http://127.0.0.1:9200";
  const values = [...new Set([sensorId, name])];
  const semanticFields = ["info.sensorId.keyword", "sensor.id.keyword"];
  const [
    semanticSegments,
    trackedObservations,
    evidenceEvents,
    lastSemanticAt,
    captions,
  ] = await Promise.all([
    countDocuments(
      elasticsearchUrl,
      "mdx-embed-filtered-*",
      semanticFields,
      values
    ),
    countDocuments(
      elasticsearchUrl,
      "mdx-raw-*",
      ["sensorId.keyword", "sensor.id.keyword", "info.sensorId.keyword"],
      values
    ),
    countDocuments(
      elasticsearchUrl,
      "mdx-incidents-*",
      ["sensorId.keyword", "sensor.id.keyword"],
      values
    ),
    latestDocumentTimestamp(
      elasticsearchUrl,
      "mdx-embed-filtered-*",
      semanticFields,
      values
    ),
    captionStatus(elasticsearchUrl, sensorId),
  ]);
  if (
    ![semanticSegments, trackedObservations, evidenceEvents, captions.count].some(
      (value) => value !== null
    )
  ) {
    return null;
  }
  const lastSemanticTimestamp = lastSemanticAt
    ? Date.parse(lastSemanticAt)
    : Number.NaN;
  const indexingDelaySeconds = Number.isFinite(lastSemanticTimestamp)
    ? Math.max(0, Math.round((Date.now() - lastSemanticTimestamp) / 1_000))
    : null;
  return {
    captionSegments: captions.count,
    evidenceEvents,
    generatedAt: new Date().toISOString(),
    indexingDelaySeconds,
    lastCaptionAt: captions.latest,
    lastSemanticAt,
    semanticFresh:
      indexingDelaySeconds !== null ? indexingDelaySeconds <= 45 : null,
    semanticSegments,
    source: { name, sensorId },
    trackedObservations,
  };
}
