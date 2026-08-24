// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";

import { fetchSourceIntelligence } from "../../../server/vision/sourceIntelligence";

export {
  fetchSourceIntelligence,
  type SourceIntelligenceResult,
} from "../../../server/vision/sourceIntelligence";

const SOURCE_ID_PATTERN = /^[A-Za-z0-9._: -]{1,256}$/;

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed." });
  }

  const sensorId =
    typeof req.query.sensorId === "string" ? req.query.sensorId.trim() : "";
  const name = typeof req.query.name === "string" ? req.query.name.trim() : "";
  if (!SOURCE_ID_PATTERN.test(sensorId) || !SOURCE_ID_PATTERN.test(name)) {
    return res.status(400).json({ error: "A valid source is required." });
  }

  const intelligence = await fetchSourceIntelligence(sensorId, name);
  res.setHeader("Cache-Control", "private, max-age=10, stale-while-revalidate=30");
  return res.status(intelligence ? 200 : 503).json(
    intelligence ?? { error: "Source intelligence data is unavailable." }
  );
}
