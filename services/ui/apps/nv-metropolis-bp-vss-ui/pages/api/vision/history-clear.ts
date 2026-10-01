// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from "next";
import { activeHistoryClearJob, cancelHistoryClearPreview, getHistoryClearJob, HistoryClearError, previewHistoryClear, startHistoryClear } from "../../../server/vision/historyClear";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader("Cache-Control", "no-store");
  try {
    if (req.method === "GET") {
      if (req.query.jobId !== undefined) {
        if (typeof req.query.jobId !== "string") return res.status(422).json({ error: "Choose a valid cleanup operation." });
        return res.status(200).json({ job: await getHistoryClearJob(req.query.jobId) });
      }
      const activeJob = activeHistoryClearJob();
      if (activeJob) return res.status(200).json({ activeJob });
      let disconnected = false;
      res.once("close", () => { if (!res.writableEnded) disconnected = true; });
      const preview = await previewHistoryClear();
      if (disconnected) {
        // Closing during the count must also release snapshots whose token
        // never reached the browser. This changes no history or source state.
        await cancelHistoryClearPreview(preview.planId).catch(() => undefined);
        return;
      }
      return res.status(200).json(preview);
    }
    if (req.method === "POST") {
      if (typeof req.body?.planId !== "string" || req.body?.confirmation !== "CLEAR_HISTORY") return res.status(422).json({ error: "Preview and confirm the history to clear first." });
      return res.status(202).json({ job: await startHistoryClear(req.body.planId, req.body.confirmation) });
    }
    if (req.method === "DELETE") {
      if (typeof req.body?.planId !== "string") return res.status(422).json({ error: "Choose a valid history preview." });
      await cancelHistoryClearPreview(req.body.planId);
      return res.status(200).json({ status: "cancelled" });
    }
    res.setHeader("Allow", "GET, POST, DELETE");
    return res.status(405).json({ error: "Method not allowed." });
  } catch (error) {
    return res.status(error instanceof HistoryClearError ? error.status : 503).json({ error: error instanceof Error ? error.message : "History cleanup is unavailable. Try again." });
  }
}
