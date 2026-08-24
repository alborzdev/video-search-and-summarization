// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";

import { readSearchCoverage } from "../../../server/vision/searchCoverage";

export { readSearchCoverage } from "../../../server/vision/searchCoverage";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed." });
  }

  try {
    const coverage = await readSearchCoverage();
    res.setHeader("Cache-Control", "private, max-age=15, stale-while-revalidate=45");
    return res.status(200).json(coverage);
  } catch {
    res.setHeader("Cache-Control", "no-store");
    return res.status(503).json({
      error: "Configured source coverage is unavailable. Check Video I/O, then refresh.",
    });
  }
}
