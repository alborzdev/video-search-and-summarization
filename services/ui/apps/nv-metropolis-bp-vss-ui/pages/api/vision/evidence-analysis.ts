// SPDX-License-Identifier: MIT

import type {
  EvidenceAnalysisRequest,
  EvidenceAnalysisResponse,
} from "../../../components/vision-intelligence/evidenceAnalysis";
import type { NextApiRequest, NextApiResponse } from "next";
import {
  CosmosReservationError,
  withCosmosReservation,
} from "../../../server/vision/cosmosReservation";
import {
  admitWorkload,
  WorkloadAdmissionError,
  workloadAdmissionFailure,
  type WorkloadAdmissionFailure,
} from "../../../server/vision/workloadAdmissionAdapter";

interface EvidenceAnalysisError {
  error: string;
}

class EvidenceRequestError extends Error {
  constructor(message: string, readonly statusCode: number) {
    super(message);
  }
}

interface EvidenceOutcome {
  payload: EvidenceAnalysisResponse | EvidenceAnalysisError;
  status: number;
}

async function forwardEvidenceAnalysis(
  request: EvidenceAnalysisRequest
): Promise<EvidenceOutcome> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs());
  try {
    const upstream = await fetch(analysisEndpoint(), {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
      signal: controller.signal,
    });
    const payload = (await upstream.json().catch(() => null)) as
      | EvidenceAnalysisResponse
      | EvidenceAnalysisError
      | null;
    if (!upstream.ok || !payload || "error" in payload) {
      return {
        payload:
          payload && "error" in payload
            ? payload
            : { error: "Evidence analysis returned an unreadable response." },
        status: upstream.status >= 400 ? upstream.status : 502,
      };
    }
    return { payload, status: 200 };
  } catch (error) {
    const aborted = controller.signal.aborted;
    return {
      payload: {
        error: aborted
          ? "Evidence analysis took too long. Try fewer or shorter clips."
          : error instanceof Error
          ? error.message
          : "Evidence analysis is unavailable.",
      },
      status: aborted ? 504 : 502,
    };
  } finally {
    clearTimeout(timeout);
  }
}

function analysisEndpoint(): string {
  if (process.env.EVIDENCE_ANALYSIS_API_URL) {
    return process.env.EVIDENCE_ANALYSIS_API_URL;
  }
  return `http://127.0.0.1:${
    process.env.VSS_AGENT_PORT || "8100"
  }/api/v1/evidence-analysis`;
}

function validateRequest(
  value: unknown
): asserts value is EvidenceAnalysisRequest {
  if (!value || typeof value !== "object") {
    throw new EvidenceRequestError(
      "A valid evidence analysis request is required.",
      400
    );
  }
  const request = value as Partial<EvidenceAnalysisRequest>;
  const queryLength =
    typeof request.query === "string" ? request.query.trim().length : 0;
  if (queryLength < 1 || queryLength > 1_000) {
    throw new EvidenceRequestError("The investigation query is invalid.", 400);
  }
  if (
    request.question !== undefined &&
    (typeof request.question !== "string" ||
      request.question.trim().length < 1 ||
      request.question.length > 1_000)
  ) {
    throw new EvidenceRequestError("The follow-up question is invalid.", 400);
  }
  if (
    !Array.isArray(request.evidence) ||
    request.evidence.length < 1 ||
    request.evidence.length > 6
  ) {
    throw new EvidenceRequestError(
      "Select between one and six retained clips.",
      400
    );
  }
  const identities = new Set<string>();
  for (const item of request.evidence) {
    if (!item || typeof item !== "object") {
      throw new EvidenceRequestError(
        "One of the selected clips is invalid.",
        400
      );
    }
    if (
      typeof item.client_id !== "string" ||
      typeof item.sensor_id !== "string" ||
      typeof item.source_name !== "string" ||
      typeof item.start_time !== "string" ||
      typeof item.end_time !== "string" ||
      !Number.isFinite(Date.parse(item.start_time)) ||
      !Number.isFinite(Date.parse(item.end_time)) ||
      Date.parse(item.end_time) <= Date.parse(item.start_time)
    ) {
      throw new EvidenceRequestError(
        "One of the selected clips has invalid source or time information.",
        400
      );
    }
    if (identities.has(item.client_id)) {
      throw new EvidenceRequestError("Selected clips must be unique.", 400);
    }
    identities.add(item.client_id);
  }
}

function timeoutMs(): number {
  const configured = Number(
    process.env.EVIDENCE_ANALYSIS_TIMEOUT_MS || 480_000
  );
  return Number.isFinite(configured)
    ? Math.min(600_000, Math.max(60_000, configured))
    : 480_000;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<
    EvidenceAnalysisResponse | EvidenceAnalysisError | WorkloadAdmissionFailure
  >
) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "Method not allowed." });
  }
  try {
    validateRequest(req.body);
  } catch (error) {
    const requestError =
      error instanceof EvidenceRequestError
        ? error
        : new EvidenceRequestError(
            "A valid evidence analysis request is required.",
            400
          );
    return res
      .status(requestError.statusCode)
      .json({ error: requestError.message });
  }

  try {
    await admitWorkload("evidence_analysis");
    const outcome = await withCosmosReservation(() =>
      forwardEvidenceAnalysis(req.body)
    );
    if (outcome.status === 200) res.setHeader("Cache-Control", "no-store");
    return res.status(outcome.status).json(outcome.payload);
  } catch (error) {
    if (error instanceof WorkloadAdmissionError) {
      return res.status(error.statusCode).json(workloadAdmissionFailure(error));
    }
    const requestError =
      error instanceof EvidenceRequestError || error instanceof CosmosReservationError
        ? error
        : new EvidenceRequestError(
            error instanceof Error
              ? error.message
              : "Evidence analysis is unavailable.",
            502
          );
    return res.status(requestError.statusCode).json({
      error: requestError.message,
    });
  }
}
