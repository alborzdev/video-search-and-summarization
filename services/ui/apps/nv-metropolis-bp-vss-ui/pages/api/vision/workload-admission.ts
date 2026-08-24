// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";

import {
  evaluateAllWorkloadAdmissions,
  evaluateWorkloadAdmission,
  isWorkloadClass,
  WORKLOAD_CLASSES,
} from "../../../server/vision/workloadAdmission";
import { readWorkloadAdmissionFacts } from "../../../server/vision/workloadAdmissionAdapter";

export { readWorkloadAdmissionFacts } from "../../../server/vision/workloadAdmissionAdapter";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed." });
  }

  const workload = Array.isArray(req.query.workload)
    ? undefined
    : req.query.workload;
  if (workload !== undefined && !isWorkloadClass(workload)) {
    return res.status(400).json({
      error: "Choose a supported workload class.",
      supportedWorkloads: WORKLOAD_CLASSES,
    });
  }

  const facts = await readWorkloadAdmissionFacts();
  res.setHeader("Cache-Control", "no-store");
  if (workload) {
    return res.status(200).json(evaluateWorkloadAdmission(workload, facts));
  }
  return res.status(200).json({
    admissions: evaluateAllWorkloadAdmissions(facts),
    checkedAt: new Date().toISOString(),
    qualifications: facts.qualifications,
    telemetry: facts.telemetry,
    vlm: facts.vlm,
  });
}
